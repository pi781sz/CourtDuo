"""The invitation engine against a real Postgres (CLAUDE.md, "Invitation
engine"; build order step 7). Skipped cleanly when TEST_DATABASE_URL is
unset — see tests/conftest.py.

The concurrency tests here are the reason this file exists. CLAUDE.md
says the atomic lock at accept time is what protects the data and that
"without this you will eventually double-book someone", and a mock cannot
demonstrate that: two mocked sessions never contend, so a completely
unlocked implementation would pass. Every "simultaneously" test below runs
two real transactions on two real connections through an asyncio.Barrier,
so both are in flight when they reach the lock and Postgres has to pick a
winner.

All pzt_ids and names are invented; CLAUDE.md forbids real scraped player
data from ever entering git.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.invitation_engine import (
    RespondFailure,
    SendFailure,
    accept_invitation,
    not_attending_invitation,
    reject_invitation,
    send_invitation,
)
from bot.partner_selection import run_pre_invitation_checks
from db import crud
from db.models import (
    Account,
    AgeCategory,
    Event,
    Gender,
    Invitation,
    InvitationState,
    Player,
    PlayType,
    Tournament,
)

_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
_GUID = "inv-t1"


# --- fixtures (invented data) ---------------------------------------------------


def _tournament(guid: str = _GUID, closes_at: datetime | None = None) -> Tournament:
    return Tournament(
        guid=guid,
        name=f"Turniej testowy {guid}",
        type_prefix="WTK",
        age_category=AgeCategory.MLODZICY,
        ranga=5,
        date_from=date(2026, 8, 22),
        date_to=date(2026, 8, 23),
        wojewodztwo="testowe",
        venue_address=None,
        venue_city="Testowo",
        entry_deadline=None,
        withdrawal_deadline=None,
        search_closes_at=closes_at or (_NOW + timedelta(days=15)),
    )


async def _add_tournament(session: AsyncSession, gender: Gender = Gender.GIRLS, guid: str = _GUID) -> Tournament:
    tournament = _tournament(guid)
    session.add(tournament)
    await session.flush()
    session.add(
        Event(
            tournament_guid=guid,
            category_label="Kategoria testowa",
            gender=gender,
            play_type=PlayType.DOUBLES,
            draw_format=None,
            is_doubles=True,
        )
    )
    await session.flush()
    return tournament


async def _add_user(
    session: AsyncSession,
    pzt_id: str,
    full_name: str,
    telegram_id: int,
    gender: Gender = Gender.GIRLS,
    with_account: bool = True,
) -> Player:
    player = Player(
        pzt_id=pzt_id, full_name=full_name, club=None, age_category=AgeCategory.MLODZICY, gender=gender
    )
    session.add(player)
    await session.flush()
    if with_account:
        session.add(
            Account(
                telegram_id=telegram_id,
                pzt_id=pzt_id,
                full_name=full_name,
                gender="W" if gender is Gender.GIRLS else "M",
            )
        )
        await session.flush()
    return player


async def _account(session: AsyncSession, pzt_id: str) -> Account:
    return await crud.get_account_by_pzt_id(session, pzt_id)


async def _states(session: AsyncSession) -> dict[int, InvitationState]:
    result = await session.execute(select(Invitation).order_by(Invitation.id))
    return {row.id: row.state for row in result.scalars().all()}


# --- sending --------------------------------------------------------------------


async def test_send_creates_a_pending_invitation_expiring_at_search_closes_at(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "SND001", "Testowa Anna", 5001)
    invitee = await _add_user(db_session, "SND002", "Testowa Jagoda", 5002)

    result = await send_invitation(db_session, await _account(db_session, "SND001"), tournament, invitee, _NOW)

    assert result.failure is None
    assert result.invitation.state is InvitationState.PENDING
    # CLAUDE.md: 10:00 Europe/Warsaw on the start date, already computed
    # in UTC by the scraper -- taken as stored, never recomputed here.
    assert result.invitation.expires_at == tournament.search_closes_at
    assert result.invitee_account.telegram_id == 5002


async def test_send_refuses_a_fourth_pending_invitation_for_one_tournament(db_session: AsyncSession):
    # CLAUDE.md: "A player may have up to 3 pending outgoing invitations
    # per tournament", enforced inside the send transaction rather than
    # only by step 6's friendly check.
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "SND010", "Testowa Anna", 5010)
    invitees = [
        await _add_user(db_session, f"SND01{i}", f"Testowa Osoba{i}", 5010 + i) for i in range(1, 5)
    ]
    account = await _account(db_session, "SND010")

    outcomes = [await send_invitation(db_session, account, tournament, invitee, _NOW) for invitee in invitees]

    assert [o.failure for o in outcomes[:3]] == [None, None, None]
    assert outcomes[3].failure is SendFailure.MAX_PENDING_REACHED
    assert await crud.count_pending_outgoing_invitations(db_session, "SND010", _GUID) == 3


async def test_send_refuses_when_the_named_player_does_not_use_courtduo(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "SND020", "Testowa Anna", 5020)
    invitee = await _add_user(db_session, "SND021", "Testowa Jagoda", 0, with_account=False)

    result = await send_invitation(db_session, await _account(db_session, "SND020"), tournament, invitee, _NOW)

    assert result.failure is SendFailure.INVITEE_NOT_ON_COURTDUO


async def test_send_refuses_when_the_inviter_was_matched_after_step_6_checked(db_session: AsyncSession):
    # Step 6 checks this before asking for a name; nothing re-runs it while
    # the player types, so the send transaction has to.
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "SND030", "Testowa Anna", 5030)
    await _add_user(db_session, "SND031", "Testowa Ola", 5031)
    invitee = await _add_user(db_session, "SND032", "Testowa Jagoda", 5032)
    account = await _account(db_session, "SND030")
    event = await crud.get_doubles_event(db_session, _GUID, Gender.GIRLS)
    db_session.add(
        Invitation(
            inviter_pzt_id="SND031",
            invitee_pzt_id="SND030",
            tournament_guid=_GUID,
            event_id=event.id,
            state=InvitationState.ACCEPTED,
            expires_at=_NOW + timedelta(days=15),
        )
    )
    await db_session.flush()

    result = await send_invitation(db_session, account, tournament, invitee, _NOW)

    assert result.failure is SendFailure.INVITER_ALREADY_MATCHED
    # Their own partner may be named to them; the invitee's may not.
    assert result.inviter_partner_pzt_id == "SND031"


async def test_send_refuses_a_gender_mismatch(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "SND040", "Testowa Anna", 5040)
    invitee = await _add_user(db_session, "SND041", "Testowy Marek", 5041, gender=Gender.BOYS)

    result = await send_invitation(db_session, await _account(db_session, "SND040"), tournament, invitee, _NOW)

    assert result.failure is SendFailure.GENDER_MISMATCH


async def test_send_refuses_when_the_invitee_already_invited_the_inviter(db_session: AsyncSession):
    # PROBLEM 3 (CLAUDE.md, "Pre-invitation checks"): Jagoda invited Anna a
    # moment ago -- after bot.partner_selection's pre-check ran, this test
    # simulates -- so Anna's send must be refused by the transaction itself,
    # not only by the pre-check, and no second invitation must be created.
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "SND050", "Testowa Anna", 5050)
    await _add_user(db_session, "SND051", "Testowa Jagoda", 5051)
    anna = await _account(db_session, "SND050")
    jagoda = await _account(db_session, "SND051")
    await send_invitation(db_session, jagoda, tournament, await _player(db_session, "SND050"), _NOW)

    result = await send_invitation(db_session, anna, tournament, await _player(db_session, "SND051"), _NOW)

    assert result.failure is SendFailure.ALREADY_INVITED_BY_INVITEE
    assert await crud.count_pending_outgoing_invitations(db_session, "SND050", _GUID) == 0
    assert await crud.count_pending_outgoing_invitations(db_session, "SND051", _GUID) == 1


# --- accepting ------------------------------------------------------------------


async def test_accept_matches_both_players_and_cancels_their_other_invitations(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "ACC001", "Testowa Anna", 6001)
    await _add_user(db_session, "ACC002", "Testowa Jagoda", 6002)
    await _add_user(db_session, "ACC003", "Testowa Ola", 6003)
    await _add_user(db_session, "ACC004", "Testowa Ewa", 6004)
    anna = await _account(db_session, "ACC001")
    ola = await _account(db_session, "ACC003")

    chosen = (await send_invitation(db_session, anna, tournament, await _player(db_session, "ACC002"), _NOW)).invitation
    others = (await send_invitation(db_session, anna, tournament, await _player(db_session, "ACC004"), _NOW)).invitation
    incoming = (
        await send_invitation(db_session, ola, tournament, await _player(db_session, "ACC002"), _NOW)
    ).invitation

    result = await accept_invitation(db_session, chosen.id, "ACC002", _NOW)

    assert result.failure is None
    states = await _states(db_session)
    assert states[chosen.id] is InvitationState.ACCEPTED
    # Both players' other pending invitations go, not just the invitee's.
    assert states[others.id] is InvitationState.CANCELLED
    assert states[incoming.id] is InvitationState.CANCELLED
    assert {row.id for row in result.cancelled} == {others.id, incoming.id}


async def test_accept_refuses_an_expired_invitation_and_marks_it_expired(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "EXP001", "Testowa Anna", 6101)
    await _add_user(db_session, "EXP002", "Testowa Jagoda", 6102)
    event = await crud.get_doubles_event(db_session, _GUID, Gender.GIRLS)
    invitation = await crud.create_invitation(
        db_session, "EXP001", "EXP002", tournament.guid, event.id, _NOW - timedelta(minutes=1)
    )

    result = await accept_invitation(db_session, invitation.id, "EXP002", _NOW)

    assert result.failure is RespondFailure.EXPIRED
    # Lazily evaluated on read rather than by a scheduled job, but a
    # PENDING invitation past its expiry must never be acceptable.
    assert (await _states(db_session))[invitation.id] is InvitationState.EXPIRED


async def test_accept_refuses_when_a_player_is_already_matched_by_an_untouched_row(db_session: AsyncSession):
    # The re-verification inside the lock, reached when a pending
    # invitation outlived a match that never cancelled it.
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "MTC001", "Testowa Anna", 6201)
    await _add_user(db_session, "MTC002", "Testowa Jagoda", 6202)
    await _add_user(db_session, "MTC003", "Testowa Ola", 6203)
    event = await crud.get_doubles_event(db_session, _GUID, Gender.GIRLS)
    stale = await crud.create_invitation(
        db_session, "MTC001", "MTC002", tournament.guid, event.id, _NOW + timedelta(days=15)
    )
    db_session.add(
        Invitation(
            inviter_pzt_id="MTC003",
            invitee_pzt_id="MTC002",
            tournament_guid=_GUID,
            event_id=event.id,
            state=InvitationState.ACCEPTED,
            expires_at=_NOW + timedelta(days=15),
        )
    )
    await db_session.flush()

    result = await accept_invitation(db_session, stale.id, "MTC002", _NOW)

    assert result.failure is RespondFailure.PLAYER_ALREADY_MATCHED
    # The already-matched player is the responder, so they may be told so.
    assert result.responder_already_matched is True
    assert (await _states(db_session))[stale.id] is InvitationState.PENDING


async def test_accept_refuses_a_tap_from_someone_who_is_not_the_invitee(db_session: AsyncSession):
    # Callback payloads come from the client, so this is authorization.
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "OWN001", "Testowa Anna", 6301)
    await _add_user(db_session, "OWN002", "Testowa Jagoda", 6302)
    await _add_user(db_session, "OWN003", "Testowa Ola", 6303)
    anna = await _account(db_session, "OWN001")
    invitation = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "OWN002"), _NOW)
    ).invitation

    result = await accept_invitation(db_session, invitation.id, "OWN003", _NOW)

    assert result.failure is RespondFailure.NOT_YOURS
    assert (await _states(db_session))[invitation.id] is InvitationState.PENDING


# --- rejecting and "nie jadę na ten turniej" -------------------------------------


async def test_reject_closes_only_that_invitation(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "REJ001", "Testowa Anna", 6401)
    await _add_user(db_session, "REJ002", "Testowa Jagoda", 6402)
    await _add_user(db_session, "REJ003", "Testowa Ola", 6403)
    anna = await _account(db_session, "REJ001")
    rejected = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "REJ002"), _NOW)
    ).invitation
    untouched = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "REJ003"), _NOW)
    ).invitation

    result = await reject_invitation(db_session, rejected.id, "REJ002", _NOW)

    assert result.failure is None
    states = await _states(db_session)
    assert states[rejected.id] is InvitationState.REJECTED
    # "Rejection is instant and free": the inviter's other pending
    # invitations stand.
    assert states[untouched.id] is InvitationState.PENDING


async def test_reject_frees_the_inviter_to_invite_someone_else_immediately(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "REJ010", "Testowa Anna", 6410)
    await _add_user(db_session, "REJ011", "Testowa Jagoda", 6411)
    await _add_user(db_session, "REJ012", "Testowa Ola", 6412)
    anna = await _account(db_session, "REJ010")
    invitation = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "REJ011"), _NOW)
    ).invitation
    await reject_invitation(db_session, invitation.id, "REJ011", _NOW)

    again = await send_invitation(db_session, anna, tournament, await _player(db_session, "REJ012"), _NOW)

    assert again.failure is None


async def test_not_attending_leaves_no_persistent_state_about_player_and_tournament(db_session: AsyncSession):
    # CLAUDE.md is emphatic: NOT_ATTENDING closes one invitation and
    # nothing else. It must not block, hide or filter any future
    # invitation to that player for that tournament -- players change
    # their minds, enter late and withdraw.
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "NAT001", "Testowa Anna", 6501)
    await _add_user(db_session, "NAT002", "Testowa Jagoda", 6502)
    await _add_user(db_session, "NAT003", "Testowa Ola", 6503)
    anna = await _account(db_session, "NAT001")
    ola = await _account(db_session, "NAT003")
    jagoda = await _player(db_session, "NAT002")
    first = (await send_invitation(db_session, anna, tournament, jagoda, _NOW)).invitation

    answered = await not_attending_invitation(db_session, first.id, "NAT002", _NOW)

    assert answered.failure is None
    assert (await _states(db_session))[first.id] is InvitationState.NOT_ATTENDING

    # Step 6's courtesy checks do not filter on it...
    assert await run_pre_invitation_checks(db_session, anna, tournament, jagoda) is None
    assert await run_pre_invitation_checks(db_session, ola, tournament, jagoda) is None
    # ...the same inviter may ask the same player again...
    again = await send_invitation(db_session, anna, tournament, jagoda, _NOW)
    assert again.failure is None
    assert again.invitation.state is InvitationState.PENDING
    # ...and so may a different player, for the same tournament.
    from_someone_else = await send_invitation(db_session, ola, tournament, jagoda, _NOW)
    assert from_someone_else.failure is None


async def test_an_answered_invitation_cannot_be_answered_again(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "TWC001", "Testowa Anna", 6601)
    await _add_user(db_session, "TWC002", "Testowa Jagoda", 6602)
    anna = await _account(db_session, "TWC001")
    invitation = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "TWC002"), _NOW)
    ).invitation
    await reject_invitation(db_session, invitation.id, "TWC002", _NOW)

    result = await accept_invitation(db_session, invitation.id, "TWC002", _NOW)

    assert result.failure is RespondFailure.ALREADY_ANSWERED
    assert (await _states(db_session))[invitation.id] is InvitationState.REJECTED


# --- concurrency: two real transactions, one winner ------------------------------


async def _player(session: AsyncSession, pzt_id: str) -> Player:
    return await crud.get_player_by_pzt_id(session, pzt_id)


# How long to let a rival transaction run before concluding it is blocked
# in Postgres rather than merely slow. Everything here talks to a local
# socket, so anything that hasn't finished in this long is waiting on a
# lock.
_LOCK_WAIT_SECONDS = 0.3


async def _accept_in_own_transaction(
    sessionmaker: async_sessionmaker[AsyncSession], invitation_id: int, responder: str
):
    """One accept on its own connection. The `SELECT 1` opens the
    transaction up front, so the accept that follows is contending from
    inside a live transaction rather than starting one from cold."""
    async with sessionmaker() as session:
        await session.execute(text("SELECT 1"))
        result = await accept_invitation(session, invitation_id, responder, _NOW)
        await session.commit()
        return result


async def _race(
    sessionmaker: async_sessionmaker[AsyncSession],
    first: tuple[int, str],
    second: tuple[int, str],
):
    """Two accepts, overlapped deliberately rather than hopefully.

    The first transaction runs to the point where it has taken its locks
    and written, and is then *held open* while the second one starts. Two
    things are then true only if the locking is real: the second
    transaction cannot get past the lock while the first holds it, and
    once the first commits the second must find its own invitation already
    gone. Letting both simply run under `asyncio.gather` proves neither —
    the event loop is free to run them end to end, and an implementation
    with no lock at all passes.

    Returns (first result, second result, whether the second one blocked).
    """
    async with sessionmaker() as winner:
        first_result = await accept_invitation(winner, first[0], first[1], _NOW)
        rival = asyncio.create_task(_accept_in_own_transaction(sessionmaker, second[0], second[1]))
        await asyncio.sleep(_LOCK_WAIT_SECONDS)
        blocked = not rival.done()
        await winner.commit()
        second_result = await rival
    return first_result, second_result, blocked


async def _committed_states(sessionmaker: async_sessionmaker[AsyncSession]) -> dict[int, InvitationState]:
    async with sessionmaker() as session:
        return await _states(session)


async def test_two_players_accepting_the_same_inviter_simultaneously_only_one_wins(
    db_sessionmaker: async_sessionmaker[AsyncSession],
):
    # Anna invites both Jagoda and Ola. They tap Zatwierdź at the same
    # moment. Anna can only have one partner, so exactly one must win --
    # and it must be decided by the database, not by luck of scheduling.
    async with db_sessionmaker() as setup:
        tournament = await _add_tournament(setup)
        await _add_user(setup, "CON001", "Testowa Anna", 7001)
        await _add_user(setup, "CON002", "Testowa Jagoda", 7002)
        await _add_user(setup, "CON003", "Testowa Ola", 7003)
        anna = await _account(setup, "CON001")
        to_jagoda = (
            await send_invitation(setup, anna, tournament, await _player(setup, "CON002"), _NOW)
        ).invitation
        to_ola = (await send_invitation(setup, anna, tournament, await _player(setup, "CON003"), _NOW)).invitation
        jagoda_id, ola_id = to_jagoda.id, to_ola.id
        await setup.commit()

    jagoda_result, ola_result, blocked = await _race(
        db_sessionmaker, (jagoda_id, "CON002"), (ola_id, "CON003")
    )

    assert blocked, "the second accept did not wait for the first — the lock is not doing its job"
    assert jagoda_result.failure is None
    assert ola_result.failure is not None
    states = await _committed_states(db_sessionmaker)
    assert states == {jagoda_id: InvitationState.ACCEPTED, ola_id: InvitationState.CANCELLED}


async def test_one_player_accepting_two_invitations_at_once_only_one_wins(
    db_sessionmaker: async_sessionmaker[AsyncSession],
):
    # The mirror image: Jagoda holds invitations from two different
    # players and taps both at once.
    async with db_sessionmaker() as setup:
        tournament = await _add_tournament(setup)
        await _add_user(setup, "CON011", "Testowa Anna", 7011)
        await _add_user(setup, "CON012", "Testowa Jagoda", 7012)
        await _add_user(setup, "CON013", "Testowa Ola", 7013)
        from_anna = (
            await send_invitation(
                setup, await _account(setup, "CON011"), tournament, await _player(setup, "CON012"), _NOW
            )
        ).invitation
        from_ola = (
            await send_invitation(
                setup, await _account(setup, "CON013"), tournament, await _player(setup, "CON012"), _NOW
            )
        ).invitation
        anna_id, ola_id = from_anna.id, from_ola.id
        await setup.commit()

    from_anna_result, from_ola_result, blocked = await _race(
        db_sessionmaker, (anna_id, "CON012"), (ola_id, "CON012")
    )

    assert blocked, "the second accept did not wait for the first — the lock is not doing its job"
    assert from_anna_result.failure is None
    assert from_ola_result.failure is not None
    states = await _committed_states(db_sessionmaker)
    assert states == {anna_id: InvitationState.ACCEPTED, ola_id: InvitationState.CANCELLED}


async def test_accept_reads_committed_state_even_when_the_session_saw_it_earlier(
    db_sessionmaker: async_sessionmaker[AsyncSession],
):
    # The lock is worth nothing if the state check behind it reads a value
    # cached before the lock was taken. SQLAlchemy does not refresh an
    # object already in the identity map unless asked to, and
    # accept_invitation loads the invitation once to find out who is in it
    # before it can lock anything — so this is a real, reachable staleness,
    # not a theoretical one.
    async with db_sessionmaker() as setup:
        tournament = await _add_tournament(setup)
        await _add_user(setup, "STL001", "Testowa Anna", 7101)
        await _add_user(setup, "STL002", "Testowa Jagoda", 7102)
        invitation = (
            await send_invitation(
                setup, await _account(setup, "STL001"), tournament, await _player(setup, "STL002"), _NOW
            )
        ).invitation
        invitation_id = invitation.id
        await setup.commit()

    async with db_sessionmaker() as session:
        seen_earlier = await crud.get_invitation_by_id(session, invitation_id)
        assert seen_earlier.state is InvitationState.PENDING

        # Somebody else answers it and commits, on another connection.
        async with db_sessionmaker() as elsewhere:
            await reject_invitation(elsewhere, invitation_id, "STL002", _NOW)
            await elsewhere.commit()

        result = await accept_invitation(session, invitation_id, "STL002", _NOW)
        await session.commit()

    assert result.failure is RespondFailure.ALREADY_ANSWERED
    assert (await _committed_states(db_sessionmaker))[invitation_id] is InvitationState.REJECTED


async def test_no_player_is_ever_matched_twice_across_an_overlapping_web(
    db_sessionmaker: async_sessionmaker[AsyncSession],
):
    # Four invitations, every one of them sharing a player with another:
    # Anna->Jagoda, Anna->Ewa, Ola->Jagoda, Ola->Ewa. All four are tapped
    # at once. Two matches are possible here (Anna-Jagoda with Ola-Ewa, or
    # Anna-Ewa with Ola-Jagoda) and the lock must allow the second one
    # while refusing every combination that would match somebody twice.
    async with db_sessionmaker() as setup:
        tournament = await _add_tournament(setup)
        for i, name in enumerate(("Anna", "Jagoda", "Ola", "Ewa")):
            await _add_user(setup, f"CON02{i}", f"Testowa {name}", 7020 + i)
        taps = []
        for inviter_id in ("CON020", "CON022"):
            for invitee_id in ("CON021", "CON023"):
                sent = await send_invitation(
                    setup, await _account(setup, inviter_id), tournament, await _player(setup, invitee_id), _NOW
                )
                taps.append((sent.invitation.id, invitee_id))
        await setup.commit()

    async with db_sessionmaker() as winner:
        held = await accept_invitation(winner, taps[0][0], taps[0][1], _NOW)
        rivals = [
            asyncio.create_task(_accept_in_own_transaction(db_sessionmaker, invitation_id, responder))
            for invitation_id, responder in taps[1:]
        ]
        await asyncio.sleep(_LOCK_WAIT_SECONDS)
        # Every one of the other three shares a player with the held
        # match, directly or through a shared row, so none may proceed
        # while it is open.
        assert all(not rival.done() for rival in rivals), "an accept slipped past the lock"
        await winner.commit()
        results = [held, *await asyncio.gather(*rivals)]

    async with db_sessionmaker() as session:
        result = await session.execute(select(Invitation).where(Invitation.state == InvitationState.ACCEPTED))
        accepted = list(result.scalars().all())
    players = [p for row in accepted for p in (row.inviter_pzt_id, row.invitee_pzt_id)]
    assert len(players) == len(set(players)), "a player was matched twice at one tournament"
    # Anna-Jagoda, and then Ola-Ewa on the players it left free.
    assert len(accepted) == 2
    # Every accept that reported success must be one of the matches that
    # actually survived: nobody may be told "🟢 Partner: ..." on the
    # strength of a write another transaction then overwrote.
    assert {row.id for row in accepted} == {r.invitation.id for r in results if r.failure is None}

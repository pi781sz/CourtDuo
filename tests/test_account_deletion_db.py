"""Account deletion, blocking and the "confirm in person" match-release
flow against a real Postgres (CLAUDE.md, "Not yet built" -> step 12,
"Account deletion and blocking"). Skipped cleanly when TEST_DATABASE_URL
is unset -- see tests/conftest.py.

Invented names, telegram ids and pzt_ids only (CLAUDE.md rule 4).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.account_deletion import delete_account, purge_finished_tournament_snapshots
from bot.invitation_engine import (
    ReleaseFailure,
    RespondFailure,
    SendFailure,
    accept_invitation,
    release_deleted_partner_match,
    send_invitation,
)
from bot.moje_deble import entry_line, group_by_tournament, partner_deleted_entries
from bot.registration import RegistrationOutcome, register_by_pzt_id
from db import crud
from db.models import (
    Account,
    AccountViewer,
    AgeCategory,
    BlockedPztId,
    Event,
    Gender,
    Invitation,
    InvitationState,
    Player,
    PlayType,
    Ranking,
    RankingList,
    Tournament,
    ViewerInviteToken,
)

_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
_GUID = "del-t1"


async def _add_tournament(
    session: AsyncSession, guid: str = _GUID, date_from: date = date(2026, 8, 22), date_to: date | None = None
) -> Tournament:
    tournament = Tournament(
        guid=guid,
        name=f"Turniej testowy {guid}",
        type_prefix="WTK",
        age_category=AgeCategory.MLODZICY,
        ranga=5,
        date_from=date_from,
        date_to=date_to or date_from,
        wojewodztwo="testowe",
        venue_address=None,
        venue_city="Testowo",
        entry_deadline=None,
        withdrawal_deadline=None,
        search_closes_at=_NOW + timedelta(days=15),
    )
    session.add(tournament)
    await session.flush()
    session.add(
        Event(
            tournament_guid=guid,
            category_label="Kategoria testowa",
            gender=Gender.GIRLS,
            play_type=PlayType.DOUBLES,
            draw_format=None,
            is_doubles=True,
        )
    )
    await session.flush()
    return tournament


async def _add_user(session: AsyncSession, pzt_id: str, full_name: str, telegram_id: int) -> Player:
    player = Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=AgeCategory.MLODZICY, gender=Gender.GIRLS)
    session.add(player)
    await session.flush()
    session.add(Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name=full_name, gender="W"))
    await session.flush()
    return player


async def _account(session: AsyncSession, pzt_id: str) -> Account:
    return await crud.get_account_by_pzt_id(session, pzt_id)


async def _player(session: AsyncSession, pzt_id: str) -> Player:
    return await crud.get_player_by_pzt_id(session, pzt_id)


async def _invitation(session: AsyncSession, invitation_id: int) -> Invitation:
    return await session.get(Invitation, invitation_id)


# --- Self-service deletion -------------------------------------------------------


async def test_delete_removes_the_account_and_its_viewers(db_session: AsyncSession):
    await _add_tournament(db_session)
    await _add_user(db_session, "DEL001", "Testowa Anna", 9001)
    account = await _account(db_session, "DEL001")
    db_session.add(AccountViewer(account_id=account.id, viewer_telegram_id=9999, viewer_display_name="Testowy Rodzic"))
    db_session.add(ViewerInviteToken(account_id=account.id, token="tok-del-1", expires_at=_NOW + timedelta(days=1)))
    await db_session.flush()

    await delete_account(db_session, account, today=date(2026, 8, 7))

    assert await crud.get_account_by_pzt_id(db_session, "DEL001") is None
    viewers = (await db_session.execute(select(AccountViewer).where(AccountViewer.account_id == account.id))).scalars().all()
    assert viewers == []
    tokens = (await db_session.execute(select(ViewerInviteToken).where(ViewerInviteToken.account_id == account.id))).scalars().all()
    assert tokens == []
    # CLAUDE.md step 12: players.full_name is PZT's own roster data and is
    # never erased by a CourtDuo account deletion.
    assert await crud.get_player_by_pzt_id(db_session, "DEL001") is not None


async def test_delete_cancels_pending_sent_and_received_invitations(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "DEL010", "Testowa Anna", 9010)
    await _add_user(db_session, "DEL011", "Testowa Jagoda", 9011)
    await _add_user(db_session, "DEL012", "Testowa Ola", 9012)
    anna = await _account(db_session, "DEL010")

    sent = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "DEL011"), _NOW)
    ).invitation
    received = (
        await send_invitation(
            db_session, await _account(db_session, "DEL012"), tournament, await _player(db_session, "DEL010"), _NOW
        )
    ).invitation

    result = await delete_account(db_session, anna, today=date(2026, 8, 7))

    assert [i.id for i in result.cancelled_sent] == [sent.id]
    assert [i.id for i in result.cancelled_received] == [received.id]
    assert (await _invitation(db_session, sent.id)).state is InvitationState.CANCELLED
    assert (await _invitation(db_session, received.id)).state is InvitationState.CANCELLED


async def test_delete_leaves_a_confirmed_match_accepted_with_a_name_snapshot(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "DEL020", "Testowa Anna", 9020)
    await _add_user(db_session, "DEL021", "Testowa Jagoda", 9021)
    anna = await _account(db_session, "DEL020")
    sent = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "DEL021"), _NOW)
    ).invitation
    await accept_invitation(db_session, sent.id, "DEL021", _NOW)
    await db_session.flush()

    result = await delete_account(db_session, anna, today=date(2026, 8, 7))

    assert [i.id for i in result.confirmed_matches] == [sent.id]
    stored = await _invitation(db_session, sent.id)
    assert stored.state is InvitationState.ACCEPTED
    # CLAUDE.md step 12: the deleted side's own name is snapshotted;
    # Jagoda's account still exists, so her side is never touched.
    assert stored.inviter_name_snapshot == "Testowa Anna"
    assert stored.invitee_name_snapshot is None

    # bot.moje_deble reads the snapshot for the remaining player and shows
    # the distinct "confirm in person" status, not a plain match.
    invitations = await crud.get_invitations_for_player(db_session, "DEL021")
    groups = group_by_tournament(invitations, "DEL021", date(2026, 8, 7), "pl")
    [group] = groups
    [entry] = group.entries
    assert entry.partner_account_deleted is True
    assert entry_line(entry, "pl") == "⚠️ Anna Testowa — potwierdź osobiście"
    assert [e.invitation_id for e in partner_deleted_entries(groups)] == [sent.id]


async def test_reregistering_clears_a_stale_name_snapshot(db_session: AsyncSession):
    tournament = await _add_tournament(db_session, guid="del-t8")
    await _add_user(db_session, "DEL080", "Testowa Anna", 9090)
    await _add_user(db_session, "DEL081", "Testowa Jagoda", 9091)
    anna = await _account(db_session, "DEL080")
    sent = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "DEL081"), _NOW)
    ).invitation
    await accept_invitation(db_session, sent.id, "DEL081", _NOW)
    await db_session.flush()
    await delete_account(db_session, anna, today=date(2026, 8, 7))
    assert (await _invitation(db_session, sent.id)).inviter_name_snapshot == "Testowa Anna"

    db_session.add(Ranking(player_pzt_id="DEL080", ranking_list=RankingList.W14, year=2026, month=8, position=5))
    await db_session.flush()

    result = await register_by_pzt_id(db_session, telegram_id=9092, raw_pzt_id="DEL080")

    assert result.outcome is RegistrationOutcome.SUCCESS
    assert (await _invitation(db_session, sent.id)).inviter_name_snapshot is None


async def test_delete_erases_own_pending_external_invites_only(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "DEL030", "Testowa Anna", 9030)
    await _add_user(db_session, "DEL031", "Testowa Ola", 9031)
    non_user = Player(pzt_id="DEL032", full_name="Testowa Ewa", club=None, age_category=AgeCategory.MLODZICY, gender=Gender.GIRLS)
    db_session.add(non_user)
    await db_session.flush()
    # Anna's own referral of a non-user -- must be erased.
    await crud.create_pending_external_invite_if_missing(db_session, "DEL030", "DEL032", tournament.guid)
    # Ola's referral naming Anna, back when Anna had no account -- not
    # Anna's own data, so it survives her deletion.
    await crud.create_pending_external_invite_if_missing(db_session, "DEL031", "DEL030", tournament.guid)
    await db_session.flush()

    await delete_account(db_session, await _account(db_session, "DEL030"), today=date(2026, 8, 7))

    remaining = await crud.get_pending_external_invites_for_invitee(db_session, "DEL030")
    assert [row.inviter_pzt_id for row in remaining] == ["DEL031"]


async def test_delete_does_not_snapshot_invitations_for_finished_tournaments(db_session: AsyncSession):
    tournament = await _add_tournament(db_session, guid="del-t2", date_from=date(2026, 7, 1))
    await _add_user(db_session, "DEL040", "Testowa Anna", 9040)
    await _add_user(db_session, "DEL041", "Testowa Jagoda", 9041)
    anna = await _account(db_session, "DEL040")
    sent = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "DEL041"), _NOW)
    ).invitation
    await accept_invitation(db_session, sent.id, "DEL041", _NOW)
    await db_session.flush()

    # "today" is well after the tournament finished.
    await delete_account(db_session, anna, today=date(2026, 8, 7))

    stored = await _invitation(db_session, sent.id)
    assert stored.inviter_name_snapshot is None


# --- Manual release after a partner's deletion ------------------------------------


async def test_release_frees_the_tournament_only_for_the_remaining_player(db_session: AsyncSession):
    tournament = await _add_tournament(db_session, guid="del-t3")
    await _add_user(db_session, "DEL050", "Testowa Anna", 9050)
    await _add_user(db_session, "DEL051", "Testowa Jagoda", 9051)
    anna = await _account(db_session, "DEL050")
    sent = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "DEL051"), _NOW)
    ).invitation
    await accept_invitation(db_session, sent.id, "DEL051", _NOW)
    await db_session.flush()
    await delete_account(db_session, anna, today=date(2026, 8, 7))

    # A third party (not one of the two players) may not release it.
    forbidden = await release_deleted_partner_match(db_session, sent.id, "SOMEONE_ELSE")
    assert forbidden.failure is ReleaseFailure.NOT_YOURS
    assert (await _invitation(db_session, sent.id)).state is InvitationState.ACCEPTED

    result = await release_deleted_partner_match(db_session, sent.id, "DEL051")
    assert result.failure is None
    assert (await _invitation(db_session, sent.id)).state is InvitationState.CANCELLED

    # Released -- the remaining player is now free to be matched again at
    # this tournament (CLAUDE.md: "Once released, they may invite someone
    # else for that tournament").
    assert await crud.get_matched_invitation(db_session, "DEL051", tournament.guid) is None


async def test_release_refuses_a_match_whose_partner_is_still_registered(db_session: AsyncSession):
    tournament = await _add_tournament(db_session, guid="del-t4")
    await _add_user(db_session, "DEL060", "Testowa Anna", 9060)
    await _add_user(db_session, "DEL061", "Testowa Jagoda", 9061)
    anna = await _account(db_session, "DEL060")
    sent = (
        await send_invitation(db_session, anna, tournament, await _player(db_session, "DEL061"), _NOW)
    ).invitation
    await accept_invitation(db_session, sent.id, "DEL061", _NOW)
    await db_session.flush()

    result = await release_deleted_partner_match(db_session, sent.id, "DEL061")

    assert result.failure is ReleaseFailure.PARTNER_NOT_DELETED
    assert (await _invitation(db_session, sent.id)).state is InvitationState.ACCEPTED


# --- Snapshot purge ---------------------------------------------------------------


async def test_purge_clears_snapshots_only_for_finished_tournaments(db_session: AsyncSession):
    live = await _add_tournament(db_session, guid="del-t5", date_from=date(2026, 8, 22))
    finished = await _add_tournament(db_session, guid="del-t6", date_from=date(2026, 7, 1))
    await _add_user(db_session, "DEL070", "Testowa Anna", 9070)
    await _add_user(db_session, "DEL071", "Testowa Jagoda", 9071)
    await _add_user(db_session, "DEL072", "Testowa Ola", 9072)
    anna = await _account(db_session, "DEL070")

    live_sent = (
        await send_invitation(db_session, anna, live, await _player(db_session, "DEL071"), _NOW)
    ).invitation
    await accept_invitation(db_session, live_sent.id, "DEL071", _NOW)
    finished_sent = (
        await send_invitation(db_session, anna, finished, await _player(db_session, "DEL072"), _NOW)
    ).invitation
    await accept_invitation(db_session, finished_sent.id, "DEL072", _NOW)
    await db_session.flush()

    # Force both snapshots to look pre-existing (as if written before the
    # "not finished" filter applied), so the purge is the only thing that
    # ever clears the finished one.
    (await _invitation(db_session, live_sent.id)).inviter_name_snapshot = "Testowa Anna"
    (await _invitation(db_session, finished_sent.id)).inviter_name_snapshot = "Testowa Anna"
    await db_session.flush()

    purged = await purge_finished_tournament_snapshots(db_session, today=date(2026, 8, 7))

    assert purged == 1
    assert (await _invitation(db_session, live_sent.id)).inviter_name_snapshot == "Testowa Anna"
    assert (await _invitation(db_session, finished_sent.id)).inviter_name_snapshot is None


# --- Blocking ----------------------------------------------------------------------


async def test_blocked_pzt_id_cannot_register(db_session: AsyncSession):
    db_session.add(Player(pzt_id="BLK001", full_name="Testowy Marek", club=None, age_category=AgeCategory.MLODZICY, gender=Gender.BOYS))
    db_session.add(Ranking(player_pzt_id="BLK001", ranking_list=RankingList.M14, year=2026, month=8, position=1))
    db_session.add(BlockedPztId(pzt_id="BLK001", blocked_at=_NOW, reason="test"))
    await db_session.flush()

    result = await register_by_pzt_id(db_session, telegram_id=7001, raw_pzt_id="BLK001")

    assert result.outcome is RegistrationOutcome.BLOCKED
    assert await crud.get_account_by_pzt_id(db_session, "BLK001") is None


async def test_block_on_an_existing_account_stops_send_and_accept(db_session: AsyncSession):
    tournament = await _add_tournament(db_session, guid="del-t7")
    await _add_user(db_session, "BLK010", "Testowa Anna", 9080)
    await _add_user(db_session, "BLK011", "Testowa Jagoda", 9081)
    anna = await _account(db_session, "BLK010")

    result = await send_invitation(db_session, anna, tournament, await _player(db_session, "BLK011"), _NOW)
    assert result.failure is None
    pending = result.invitation

    db_session.add(BlockedPztId(pzt_id="BLK011", blocked_at=_NOW, reason="test"))
    await db_session.flush()

    blocked_accept = await accept_invitation(db_session, pending.id, "BLK011", _NOW)
    assert blocked_accept.failure is RespondFailure.BLOCKED

    blocked_send = await send_invitation(db_session, anna, tournament, await _player(db_session, "BLK011"), _NOW)
    assert blocked_send.failure is SendFailure.BLOCKED

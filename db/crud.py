"""Upsert functions the scrapers call to persist what they scrape.

Every function here is idempotent — re-running a scraper for data that
hasn't changed is a no-op write (`INSERT ... ON CONFLICT DO UPDATE`),
never a duplicate row. Player/tournament/event identity comes from PZT's
own ids (pzt_id, guid) rather than a surrogate id, which is exactly what
makes that possible: a re-scrape lands on the same row.

Because db.models.enums re-exports the scrapers' own AgeCategory/Gender/
PlayType/RankingList enums, a scraped dataclass's enum fields pass
straight into a mapped column with no translation step.

No bot logic lives here beyond straightforward persistence:
can_send_invitation (the entitlement check CLAUDE.md's "Monetisation"
section asks to be routed through from day one), the account CRUD that
registration needs, and the invitation queries below. The invitation
engine's decisions — which transaction runs, what it re-verifies, what it
cancels — live in bot.invitation_engine; this module only supplies the
statements it runs, including the two locking statements
(lock_invitation_slot, lock_tournament_invitations_for_players) whose
exact shape the engine's correctness depends on.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from scrapers.rankings.models import RankingEntry as ScrapedRankingEntry
from scrapers.tournaments.models import Event as ScrapedEvent
from scrapers.tournaments.models import Tournament as ScrapedTournament

from .models import (
    Account,
    AccountViewer,
    AgeCategory,
    AlarmState,
    BlockedPztId,
    Event,
    Gender,
    Invitation,
    InvitationState,
    PendingExternalInvite,
    Player,
    Ranking,
    RankingList,
    ScraperRun,
    SupportConversation,
    SupportOperatorSession,
    SupportThread,
    Tournament,
    ViewerInviteToken,
)

logger = logging.getLogger(__name__)

# CLAUDE.md, "Tournament selection": how far ahead a tournament's
# date_from may be and still be offered. The single source of truth for
# this — get_eligible_tournaments, get_eligible_tournament_counts_by_category
# and their tests all import it rather than repeating the day count.
ELIGIBILITY_WINDOW_DAYS = 28

# CLAUDE.md, "Tournament selection": ranga 6/7 are internal club events and
# must never appear -- not in the eligible list, and not in the per-category
# counts that decide whether a category button looks available. A NULL
# ranga is *not* hidden (bot.tournament_search.ranga_prefix handles the
# NULL-ranga display case); `ranga.not_in(HIDDEN_RANGAS)` alone would drop
# those rows too, since SQL NULL comparisons are neither true nor false, so
# every query below OR's in an explicit `ranga.is_(None)` escape hatch.
HIDDEN_RANGAS = frozenset({6, 7})

_AGE_CATEGORY_BY_LABEL = {c.label: c for c in AgeCategory}
_GENDER_BY_LABEL = {g.value: g for g in Gender}

# accounts.gender is the single-letter 'M'/'W' code bot.registration.derive_gender
# stores (from a ranking-list code's own prefix); Event.gender is the scraped
# Gender enum. This maps one to the other for the eligibility filter in
# get_eligible_tournaments.
_GENDER_BY_ACCOUNT_CODE = {"M": Gender.BOYS, "W": Gender.GIRLS}
_ACCOUNT_CODE_BY_GENDER = {gender: code for code, gender in _GENDER_BY_ACCOUNT_CODE.items()}


def gender_for_account_code(code: str) -> Gender:
    return _GENDER_BY_ACCOUNT_CODE[code]


def account_code_for_gender(gender: Gender | None) -> str | None:
    """The inverse of gender_for_account_code, for a `players.gender` value
    that has no account of its own yet -- CLAUDE.md step 8.6, CHANGE 1: the
    "does not use CourtDuo" message needs a gendered pronoun (ją/go) for a
    player who, by definition, has no accounts.gender to read. None passes
    through unchanged -- bot.invitation_text.gendered() already falls back
    to the masculine form for an unknown code.
    """
    if gender is None:
        return None
    return _ACCOUNT_CODE_BY_GENDER[gender]


async def upsert_tournament(session: AsyncSession, tournament: ScrapedTournament) -> Tournament | None:
    """Inserts or updates one tournament and all of its events.

    Returns None (and writes nothing) if the tournament has no GUID —
    without it there's no stable key to upsert against; see
    scrapers.tournaments.parser's "no extractable GUID" warning, logged
    when this happens at scrape time already.
    """
    if tournament.guid is None:
        logger.warning("Skipping tournament with no GUID: %.80s", tournament.name)
        return None

    values = {
        "name": tournament.name,
        "type_prefix": tournament.type_prefix,
        "age_category": tournament.age_category,
        "ranga": tournament.ranga,
        "date_from": tournament.date_from,
        "date_to": tournament.date_to,
        "wojewodztwo": tournament.wojewodztwo,
        "venue_address": tournament.venue_address,
        "venue_city": tournament.venue_city,
        "entry_deadline": tournament.entry_deadline,
        "withdrawal_deadline": tournament.withdrawal_deadline,
        "search_closes_at": tournament.search_closes_at,
    }
    stmt = insert(Tournament).values(guid=tournament.guid, **values)
    stmt = stmt.on_conflict_do_update(index_elements=[Tournament.guid], set_=values)
    await session.execute(stmt)

    for event in tournament.events:
        await upsert_event(session, tournament.guid, event)

    result = await session.execute(select(Tournament).where(Tournament.guid == tournament.guid))
    return result.scalar_one()


async def upsert_event(session: AsyncSession, tournament_guid: str, event: ScrapedEvent) -> Event:
    """Inserts or updates one event of a tournament.

    Identity is (tournament, category_label, gender, play_type) — see
    uq_event_identity — since PZT's Rozgrywki block has no id of its own
    for a single event line.
    """
    stmt = insert(Event).values(
        tournament_guid=tournament_guid,
        category_label=event.category_label,
        gender=event.gender,
        play_type=event.play_type,
        draw_format=event.draw_format,
        is_doubles=event.is_doubles,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Event.tournament_guid, Event.category_label, Event.gender, Event.play_type],
        set_={"draw_format": event.draw_format, "is_doubles": event.is_doubles},
    )
    await session.execute(stmt)

    result = await session.execute(
        select(Event).where(
            Event.tournament_guid == tournament_guid,
            Event.category_label == event.category_label,
            Event.gender == event.gender,
            Event.play_type == event.play_type,
        )
    )
    return result.scalar_one()


async def upsert_player(
    session: AsyncSession,
    pzt_id: str,
    full_name: str,
    club: str | None,
    age_category: AgeCategory | None,
    gender: Gender | None,
) -> Player:
    values = {"full_name": full_name, "club": club, "age_category": age_category, "gender": gender}
    stmt = insert(Player).values(pzt_id=pzt_id, **values)
    stmt = stmt.on_conflict_do_update(index_elements=[Player.pzt_id], set_=values)
    await session.execute(stmt)

    result = await session.execute(select(Player).where(Player.pzt_id == pzt_id))
    return result.scalar_one()


async def upsert_ranking_entry(session: AsyncSession, entry: ScrapedRankingEntry) -> Ranking | None:
    """Upserts the player (name/club/derived age_category+gender) named in
    a ranking row, then the ranking row itself for entry.year/entry.month.

    Returns None (and writes nothing) if PZT rendered the row with no
    pzt_id — CLAUDE.md's "Identity" makes the alphabetical roster the
    registration lookup table, and a row with no id can't be linked to an
    account later. scrapers.rankings.parser already logs this case.
    """
    if entry.pzt_id is None:
        logger.warning(
            "Skipping ranking entry with no pzt_id: %.60s (%s)", entry.full_name, entry.ranking_list.code
        )
        return None

    age_category = _AGE_CATEGORY_BY_LABEL[entry.ranking_list.age_category_label]
    gender = _GENDER_BY_LABEL[entry.ranking_list.gender_label]
    await upsert_player(session, entry.pzt_id, entry.full_name, entry.club, age_category, gender)

    values = {"position": entry.position}
    stmt = insert(Ranking).values(
        player_pzt_id=entry.pzt_id,
        ranking_list=entry.ranking_list,
        year=entry.year,
        month=entry.month,
        **values,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Ranking.player_pzt_id, Ranking.ranking_list, Ranking.year, Ranking.month],
        set_=values,
    )
    await session.execute(stmt)

    result = await session.execute(
        select(Ranking).where(
            Ranking.player_pzt_id == entry.pzt_id,
            Ranking.ranking_list == entry.ranking_list,
            Ranking.year == entry.year,
            Ranking.month == entry.month,
        )
    )
    return result.scalar_one()


async def store_tournaments(session: AsyncSession, tournaments: list[ScrapedTournament]) -> tuple[int, int]:
    """Upserts a batch of scraped tournaments. Returns (tournaments_written, doubles_events_written)."""
    written = 0
    doubles_events = 0
    for tournament in tournaments:
        if await upsert_tournament(session, tournament) is None:
            continue
        written += 1
        doubles_events += len(tournament.doubles_events)
    return written, doubles_events


async def store_ranking_entries(session: AsyncSession, entries: list[ScrapedRankingEntry]) -> int:
    """Upserts a batch of scraped ranking entries. Returns entries_written."""
    written = 0
    for entry in entries:
        if await upsert_ranking_entry(session, entry) is not None:
            written += 1
    return written


async def get_latest_ranking_period(session: AsyncSession, ranking_list: RankingList) -> tuple[int, int] | None:
    """The newest (year, month) stored for a ranking list — what the bot
    should read (CLAUDE.md, "Rankings": history is kept, but the bot
    always reads the newest period)."""
    result = await session.execute(
        select(Ranking.year, Ranking.month)
        .where(Ranking.ranking_list == ranking_list)
        .order_by(Ranking.year.desc(), Ranking.month.desc())
        .limit(1)
    )
    row = result.first()
    return (row.year, row.month) if row else None


async def get_account_by_telegram_id(session: AsyncSession, telegram_id: int) -> Account | None:
    result = await session.execute(select(Account).where(Account.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_account_by_id(session: AsyncSession, account_id: int) -> Account | None:
    return await session.get(Account, account_id)


async def get_account_by_pzt_id(session: AsyncSession, pzt_id: str) -> Account | None:
    """Used by registration to refuse a pzt_id that's already bound to a
    different Telegram account (CLAUDE.md, "one PZT player = one Telegram
    account"). `pzt_id` must already be normalized — see
    bot.registration.normalize_pzt_id.
    """
    result = await session.execute(select(Account).where(Account.pzt_id == pzt_id))
    return result.scalar_one_or_none()


async def create_account(session: AsyncSession, telegram_id: int, pzt_id: str, full_name: str, gender: str) -> Account:
    """Creates the account row on first successful registration
    (CLAUDE.md, "Identity": one Telegram account is one PZT player).
    Callers must already have verified this telegram_id has no account
    and this pzt_id isn't bound elsewhere — see bot.registration.
    """
    account = Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name=full_name, gender=gender)
    session.add(account)
    await session.flush()
    return account


async def get_player_by_pzt_id(session: AsyncSession, pzt_id: str) -> Player | None:
    result = await session.execute(select(Player).where(Player.pzt_id == pzt_id))
    return result.scalar_one_or_none()


async def get_latest_ranking_for_player(session: AsyncSession, pzt_id: str) -> Ranking | None:
    result = await session.execute(
        select(Ranking)
        .where(Ranking.player_pzt_id == pzt_id)
        .order_by(Ranking.year.desc(), Ranking.month.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_ranking_period_overall(session: AsyncSession) -> tuple[int, int] | None:
    """The newest (year, month) present anywhere in the rankings table.

    Registration (CLAUDE.md's LOOKUP RULES) looks a typed PZT id up in
    this single newest period rather than per-list, since PZT publishes
    all eight lists together each month (see scrapers.rankings.models,
    RANKING_INDEX_URL) — there is one canonical "current" period, and
    using it lets a stale/missing single list surface as a gender
    conflict or a not-found instead of silently matching an older month.
    """
    result = await session.execute(
        select(Ranking.year, Ranking.month).order_by(Ranking.year.desc(), Ranking.month.desc()).limit(1)
    )
    row = result.first()
    return (row.year, row.month) if row else None


async def get_rankings_for_player_in_period(
    session: AsyncSession, pzt_id: str, year: int, month: int
) -> list[Ranking]:
    """Every ranking-list row a normalized pzt_id appears under in one
    period — usually one, but a player who plays up appears in more than
    one age category (CLAUDE.md, LOOKUP RULES). Matched case-insensitively
    since `pzt_id` is normalized (bot.registration.normalize_pzt_id) but
    the scraped column isn't guaranteed to be uppercase.
    """
    result = await session.execute(
        select(Ranking).where(
            func.upper(Ranking.player_pzt_id) == pzt_id,
            Ranking.year == year,
            Ranking.month == month,
        )
    )
    return list(result.scalars().all())


async def get_player_own_age_category(session: AsyncSession, pzt_id: str) -> AgeCategory | None:
    """CLAUDE.md step 8.3, "Deriving a player's own age category": the
    LOWEST ranking list a player appears in for the newest (year, month)
    overall in `rankings` -- e.g. a player in M14 and M16 is a U14 player
    playing up, so their category is 14. `players.age_category` is a
    snapshot of whichever ranking row was scraped last (db.crud.
    upsert_ranking_entry) and is not guaranteed to be the lowest one, so
    this is derived fresh from `rankings` rather than read off that column.

    Returns None when the player has no ranking rows in the newest period
    at all -- registration requires a PZT id present in a ranking list, so
    this should not happen for a registered player, but it must never be
    guessed at.
    """
    period = await get_latest_ranking_period_overall(session)
    if period is None:
        return None
    year, month = period
    rankings = await get_rankings_for_player_in_period(session, pzt_id.upper(), year, month)
    if not rankings:
        return None
    return min(
        (_AGE_CATEGORY_BY_LABEL[r.ranking_list.age_category_label] for r in rankings),
        key=lambda category: category.value,
    )


async def get_tournament_by_guid(session: AsyncSession, guid: str) -> Tournament | None:
    result = await session.execute(select(Tournament).where(Tournament.guid == guid))
    return result.scalar_one_or_none()


def tournament_search_still_open(tournament: Tournament, today: date, now: datetime) -> bool:
    """The "within the window, search still open" half of CLAUDE.md build
    order step 9's PART 2 eligibility check, for a specific tournament a
    pending_external_invites row already points at. Deliberately narrower
    than get_eligible_tournaments: gender/age_category/ranga were already
    true of this exact tournament when the attempt was stored
    (bot.invitation_send.send_not_on_courtduo_response only ever writes a
    row after every one of step 6's checks passed) and cannot change
    underneath an existing row, so re-checking them here would be redundant.
    """
    if tournament.date_from is None or tournament.search_closes_at is None:
        return False
    cutoff = today + timedelta(days=ELIGIBILITY_WINDOW_DAYS)
    return today <= tournament.date_from <= cutoff and tournament.search_closes_at > now


async def get_eligible_tournaments(
    session: AsyncSession, gender: Gender, age_category: AgeCategory, today: date, now: datetime
) -> list[Tournament]:
    """Tournaments eligible for step 5's place search (CLAUDE.md,
    "Tournament selection"): matching `age_category` (step 5.1 asks for
    this first, before place), `date_from` within the next
    ELIGIBILITY_WINDOW_DAYS days, the search window still open, ranga not
    one of HIDDEN_RANGAS (step 5.4: internal club events), and at
    least one `Gra podwójna` event matching `gender`.

    `today`/`now` are passed in rather than computed here: `today` should
    be the Europe/Warsaw wall-clock date the window counts from, while
    `search_closes_at` is already a UTC instant and compares directly
    against `now` — see bot.handlers.tournament_search, which computes both.

    An EXISTS subquery (rather than a join) is what keeps a tournament
    with several matching doubles events from coming back more than once.
    """
    cutoff = today + timedelta(days=ELIGIBILITY_WINDOW_DAYS)
    has_matching_doubles_event = (
        select(Event.id)
        .where(
            Event.tournament_guid == Tournament.guid,
            Event.is_doubles.is_(True),
            Event.gender == gender,
        )
        .exists()
    )
    result = await session.execute(
        select(Tournament)
        .where(
            Tournament.age_category == age_category,
            Tournament.date_from.is_not(None),
            Tournament.date_from >= today,
            Tournament.date_from <= cutoff,
            Tournament.search_closes_at.is_not(None),
            Tournament.search_closes_at > now,
            or_(Tournament.ranga.is_(None), Tournament.ranga.not_in(HIDDEN_RANGAS)),
            has_matching_doubles_event,
        )
        .order_by(Tournament.date_from.asc(), func.coalesce(Tournament.venue_city, Tournament.wojewodztwo).asc())
    )
    return list(result.scalars().all())


async def get_eligible_tournament_counts_by_category(
    session: AsyncSession, gender: Gender, today: date, now: datetime
) -> dict[AgeCategory, int]:
    """How many eligible tournaments each age category has, for the step
    5.1 category-choice screen (CLAUDE.md, "Tournament selection") — one
    grouped query rather than one `get_eligible_tournaments` call per
    category. Same eligibility rules as `get_eligible_tournaments` minus
    the age_category filter itself. A category absent from the returned
    dict has zero eligible tournaments.
    """
    cutoff = today + timedelta(days=ELIGIBILITY_WINDOW_DAYS)
    has_matching_doubles_event = (
        select(Event.id)
        .where(
            Event.tournament_guid == Tournament.guid,
            Event.is_doubles.is_(True),
            Event.gender == gender,
        )
        .exists()
    )
    result = await session.execute(
        select(Tournament.age_category, func.count(Tournament.guid))
        .where(
            Tournament.date_from.is_not(None),
            Tournament.date_from >= today,
            Tournament.date_from <= cutoff,
            Tournament.search_closes_at.is_not(None),
            Tournament.search_closes_at > now,
            or_(Tournament.ranga.is_(None), Tournament.ranga.not_in(HIDDEN_RANGAS)),
            has_matching_doubles_event,
        )
        .group_by(Tournament.age_category)
    )
    return {age_category: count for age_category, count in result.all()}


async def can_send_invitation(account: Account, tournament: Tournament) -> bool:
    """Entitlement gate for sending a new invitation (CLAUDE.md,
    "Monetisation — build now, enable later").

    Always True today — everything is free at launch. Invitation creation
    must always route through this function rather than checking
    account.plan/invitations_used directly, so that when paid tiers launch
    exactly one function changes.
    """
    return True


# CLAUDE.md, "Invitation engine": "A player may have up to 3 pending
# outgoing invitations per tournament." The real invariant is enforced by
# the `enforce_max_pending_invitations` Postgres trigger (see the
# invitation-only-schema migration) with its own literal 3 -- SQL can't
# reference a Python constant. This one backs the friendly pre-invitation
# check in CLAUDE.md's "Pre-invitation checks" (build order step 6), which
# exists to give a player an error *before* hitting that trigger, not to
# replace it.
MAX_PENDING_INVITATIONS_PER_TOURNAMENT = 3


async def get_matched_invitation(session: AsyncSession, pzt_id: str, tournament_guid: str) -> Invitation | None:
    """The ACCEPTED invitation that already locks `pzt_id` into a partner
    at this tournament, if any -- `pzt_id` may appear as either side. Backs
    two of CLAUDE.md's "Pre-invitation checks": "the inviter is already
    matched" (checked before a name is even asked for) and, via the
    resolved candidate's pzt_id, "the named player is already matched".
    """
    result = await session.execute(
        select(Invitation).where(
            Invitation.tournament_guid == tournament_guid,
            Invitation.state == InvitationState.ACCEPTED,
            or_(Invitation.inviter_pzt_id == pzt_id, Invitation.invitee_pzt_id == pzt_id),
        )
    )
    return result.scalar_one_or_none()


async def get_pending_invitation(
    session: AsyncSession, inviter_pzt_id: str, invitee_pzt_id: str, tournament_guid: str
) -> Invitation | None:
    """CLAUDE.md, "Pre-invitation checks": "a pending invitation to that
    same person for that tournament already exists"."""
    result = await session.execute(
        select(Invitation).where(
            Invitation.tournament_guid == tournament_guid,
            Invitation.inviter_pzt_id == inviter_pzt_id,
            Invitation.invitee_pzt_id == invitee_pzt_id,
            Invitation.state == InvitationState.PENDING,
        )
    )
    return result.scalar_one_or_none()


# CLAUDE.md step 8.3, PROBLEM 5: a REJECTED or NOT_ATTENDING answer blocks
# the same inviter from re-inviting the same player to the same tournament
# -- "rejection is instant and free" still holds, but for someone else, not
# the same person again.
_ANSWERED_INVITATION_STATES = (InvitationState.REJECTED, InvitationState.NOT_ATTENDING)


async def get_answered_invitation(
    session: AsyncSession, inviter_pzt_id: str, invitee_pzt_id: str, tournament_guid: str
) -> Invitation | None:
    """CLAUDE.md step 8.3, PROBLEM 5: an invitation `inviter_pzt_id` already
    sent `invitee_pzt_id` for this tournament that was answered REJECTED or
    NOT_ATTENDING, if any. Directional -- `invitee_pzt_id` inviting
    `inviter_pzt_id` back afterwards is a separate action this does not see.
    """
    result = await session.execute(
        select(Invitation).where(
            Invitation.tournament_guid == tournament_guid,
            Invitation.inviter_pzt_id == inviter_pzt_id,
            Invitation.invitee_pzt_id == invitee_pzt_id,
            Invitation.state.in_(_ANSWERED_INVITATION_STATES),
        )
    )
    return result.scalars().first()


async def count_pending_outgoing_invitations(session: AsyncSession, inviter_pzt_id: str, tournament_guid: str) -> int:
    """CLAUDE.md, "Pre-invitation checks": "the inviter already has 3
    pending outgoing invitations for this tournament".

    Counts every PENDING row, expired or not, exactly as the
    `enforce_max_pending_invitations` trigger does — a divergence between
    the two would mean the friendly check passes and the trigger then
    raises. Expiry can't distort this count in practice: an invitation
    expires at 10:00 on the tournament's start date, by which time
    `search_closes_at` has passed and the tournament can no longer be
    selected at all (see get_eligible_tournaments), so there is no way to
    reach the send flow for a tournament whose PENDING rows have expired.
    """
    result = await session.execute(
        select(func.count(Invitation.id)).where(
            Invitation.tournament_guid == tournament_guid,
            Invitation.inviter_pzt_id == inviter_pzt_id,
            Invitation.state == InvitationState.PENDING,
        )
    )
    return result.scalar_one()


async def get_doubles_event(session: AsyncSession, tournament_guid: str, gender: Gender) -> Event | None:
    """The `Gra podwójna` event an invitation for this tournament hangs
    off (`invitations.event_id`), for the inviting player's gender.

    A tournament can carry more than one matching doubles event when PZT
    splits a draw across category labels; `order_by(Event.id)` makes the
    pick deterministic rather than whatever order the planner returns.
    Returns None when the tournament has no doubles draw for that gender
    at all, which the caller must treat as "cannot invite here" — the
    eligibility filter should already have excluded such a tournament.
    """
    result = await session.execute(
        select(Event)
        .where(
            Event.tournament_guid == tournament_guid,
            Event.is_doubles.is_(True),
            Event.gender == gender,
        )
        .order_by(Event.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_invitation_by_id(session: AsyncSession, invitation_id: int) -> Invitation | None:
    result = await session.execute(select(Invitation).where(Invitation.id == invitation_id))
    return result.scalar_one_or_none()


async def get_invitations_for_player(session: AsyncSession, pzt_id: str) -> list[Invitation]:
    """Every invitation `pzt_id` appears in, on either side, in any state
    (CLAUDE.md, "Moje deble" status view; build order step 8). Eagerly
    loads the tournament and both players' names, since bot.moje_deble
    renders every row without issuing a query per row.

    Nothing is filtered here beyond "involves this player" -- which states
    are shown and which tournaments have finished are display decisions
    left to bot.moje_deble, per CLAUDE.md: "Nothing is deleted from the
    database — this is a display filter only."
    """
    result = await session.execute(
        select(Invitation)
        .options(
            selectinload(Invitation.tournament),
            selectinload(Invitation.inviter),
            selectinload(Invitation.invitee),
        )
        .where(or_(Invitation.inviter_pzt_id == pzt_id, Invitation.invitee_pzt_id == pzt_id))
    )
    return list(result.scalars().all())


def _advisory_lock_key(inviter_pzt_id: str, tournament_guid: str) -> int:
    """A stable signed-64-bit key for one (inviter, tournament) send slot.

    Hashed in Python rather than with Postgres' `hashtext()` so the key
    can't shift with a server version or collation change — a lock key
    that changes underneath a running bot would silently stop serializing
    anything. Collisions only cost two unrelated inviters a moment of
    serialization, never correctness.
    """
    digest = hashlib.blake2b(f"{inviter_pzt_id}\x00{tournament_guid}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


async def lock_invitation_slot(session: AsyncSession, inviter_pzt_id: str, tournament_guid: str) -> None:
    """Serializes every concurrent invitation *send* by one player for one
    tournament, so CLAUDE.md's "up to 3 pending outgoing invitations per
    tournament" can be counted and acted on atomically.

    Row locks can't do this job: the rows that would break the limit are
    the ones being inserted, and `SELECT ... FOR UPDATE` cannot lock a row
    that does not exist yet (two sends starting from zero pending rows
    would lock nothing, count zero, and both insert). A transaction-scoped
    advisory lock keyed on the slot itself has no such gap. It is released
    automatically at COMMIT or ROLLBACK.

    Deadlock-free by construction: a send takes this lock and then only
    reads, while an accept takes row locks and never asks for this one, so
    no cycle between the two paths is possible.
    """
    await session.execute(select(func.pg_advisory_xact_lock(_advisory_lock_key(inviter_pzt_id, tournament_guid))))


async def lock_tournament_invitations_for_players(
    session: AsyncSession, tournament_guid: str, pzt_ids: tuple[str, str]
) -> list[Invitation]:
    """`SELECT ... FOR UPDATE` over every invitation at one tournament that
    either player appears in, on either side — the lock CLAUDE.md's
    "Atomic locking is mandatory" calls for, and the whole reason two
    people cannot be double-booked.

    Three details this depends on, none of them optional:

    - **No state filter.** Under READ COMMITTED, a statement that blocks
      on a row lock re-evaluates its WHERE clause against the row version
      the winning transaction committed. A `state = 'PENDING'` predicate
      would therefore *drop* the row that just became ACCEPTED — the loser
      would see no conflict and accept on top of it. States are compared
      in Python, after the lock, precisely so the row can never vanish
      from under the check.
    - **`ORDER BY id`.** Postgres locks rows in the order the plan emits
      them, so a fixed order means two transactions covering overlapping
      sets take those rows in the same sequence and one simply waits,
      instead of the two deadlocking on a lock-order inversion.
    - **`populate_existing`.** Rows already in the session's identity map
      are not refreshed by a later query by default, so without this the
      caller could re-check `state` against the stale value it read
      before taking the lock — the exact check the lock exists to make
      trustworthy.

    Two accept transactions conflict exactly when they need to: each locks
    every row involving either of its two players, so any pair of accepts
    sharing a player shares at least one row and serializes on it.
    """
    result = await session.execute(
        select(Invitation)
        .where(
            Invitation.tournament_guid == tournament_guid,
            or_(Invitation.inviter_pzt_id.in_(pzt_ids), Invitation.invitee_pzt_id.in_(pzt_ids)),
        )
        .order_by(Invitation.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def lock_invitation(session: AsyncSession, invitation_id: int) -> Invitation | None:
    """One invitation row, locked — enough for the answers that change
    only that row (Odrzuć, "Nie jadę na ten turniej"), where the race to
    guard against is an accept elsewhere cancelling this same row.

    `populate_existing` for the same reason as in
    lock_tournament_invitations_for_players: the caller must read the
    committed state, not whatever the identity map already held.
    """
    result = await session.execute(
        select(Invitation)
        .where(Invitation.id == invitation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def create_invitation(
    session: AsyncSession,
    inviter_pzt_id: str,
    invitee_pzt_id: str,
    tournament_guid: str,
    event_id: int,
    expires_at: datetime,
) -> Invitation:
    """Inserts one PENDING invitation. `expires_at` is the tournament's
    already-stored `search_closes_at` (10:00 Europe/Warsaw on the start
    date, converted to UTC at scrape time) — never recomputed here, and
    never an offset arithmetic of its own (CLAUDE.md, "Invitation
    engine").
    """
    invitation = Invitation(
        inviter_pzt_id=inviter_pzt_id,
        invitee_pzt_id=invitee_pzt_id,
        tournament_guid=tournament_guid,
        event_id=event_id,
        state=InvitationState.PENDING,
        expires_at=expires_at,
    )
    session.add(invitation)
    await session.flush()
    return invitation


# --- Non-user invite flow (CLAUDE.md scenario 2; build order step 9) --------


async def create_pending_external_invite_if_missing(
    session: AsyncSession, inviter_pzt_id: str, invitee_pzt_id: str, tournament_guid: str
) -> None:
    """Remembers one "share this invite" attempt against a named player who
    is on PZT's roster but has no CourtDuo account yet, so they can be
    notified of it once they register (CLAUDE.md scenario 2). `ON CONFLICT
    DO NOTHING` against uq_pending_external_invite_inviter_invitee_tournament
    is what makes this safe to call every time the "does not use CourtDuo
    yet" screen is shown -- re-showing it (e.g. the player reopens the same
    chat) must not create a second row for the same (inviter, invitee,
    tournament).
    """
    stmt = (
        insert(PendingExternalInvite)
        .values(inviter_pzt_id=inviter_pzt_id, invitee_pzt_id=invitee_pzt_id, tournament_guid=tournament_guid)
        .on_conflict_do_nothing(
            index_elements=[
                PendingExternalInvite.inviter_pzt_id,
                PendingExternalInvite.invitee_pzt_id,
                PendingExternalInvite.tournament_guid,
            ]
        )
    )
    await session.execute(stmt)


async def get_pending_external_invites_for_invitee(
    session: AsyncSession, invitee_pzt_id: str
) -> list[PendingExternalInvite]:
    """Every stored attempt to invite `invitee_pzt_id`, across every
    inviter and tournament -- looked up once, on successful registration
    (CLAUDE.md scenario 2: "When someone registers whose name matches,
    notify Adam"). Eagerly loads the tournament, since the caller needs its
    eligibility fields for every row without a query each.
    """
    result = await session.execute(
        select(PendingExternalInvite)
        .options(selectinload(PendingExternalInvite.tournament))
        .where(PendingExternalInvite.invitee_pzt_id == invitee_pzt_id)
    )
    return list(result.scalars().all())


async def delete_pending_external_invite(session: AsyncSession, pending_id: int) -> None:
    """Removes one row once it has served its purpose -- notified (or found
    no longer worth notifying about) on the invitee's registration, or
    acted on via the "send the real invitation" offer. Nothing else in
    CourtDuo ever reads a row past that point.
    """
    pending = await session.get(PendingExternalInvite, pending_id)
    if pending is not None:
        await session.delete(pending)


# --- Read-only viewers (CLAUDE.md "Identity", step 10) -----------------------

# CLAUDE.md, DATA: "Maximum 3 active viewers per account." Checked both
# when a fresh invite token is created (bot.viewers.create_invite_token)
# and again when one is consumed (bot.viewers.bind_viewer), since two
# outstanding tokens for the same account could otherwise both be
# consumed and push the count past 3.
MAX_ACTIVE_VIEWERS = 3


async def create_viewer_invite_token(
    session: AsyncSession, account_id: int, token: str, expires_at: datetime
) -> ViewerInviteToken:
    row = ViewerInviteToken(account_id=account_id, token=token, expires_at=expires_at)
    session.add(row)
    await session.flush()
    return row


async def get_viewer_invite_token(session: AsyncSession, token: str) -> ViewerInviteToken | None:
    result = await session.execute(select(ViewerInviteToken).where(ViewerInviteToken.token == token))
    return result.scalar_one_or_none()


async def mark_viewer_invite_token_consumed(session: AsyncSession, token_row: ViewerInviteToken, now: datetime) -> None:
    """Burns a token whether or not binding actually adds a new viewer row
    (CLAUDE.md step 10: "single-use... The token is consumed") -- a token
    reused because the viewer already has active access, or reused past
    the 3-viewer cap, must not remain usable for a second attempt.
    """
    token_row.consumed_at = now
    await session.flush()


async def count_active_viewers(session: AsyncSession, account_id: int) -> int:
    result = await session.execute(
        select(func.count(AccountViewer.id)).where(
            AccountViewer.account_id == account_id, AccountViewer.revoked_at.is_(None)
        )
    )
    return result.scalar_one()


async def get_active_viewer(session: AsyncSession, account_id: int, viewer_telegram_id: int) -> AccountViewer | None:
    result = await session.execute(
        select(AccountViewer).where(
            AccountViewer.account_id == account_id,
            AccountViewer.viewer_telegram_id == viewer_telegram_id,
            AccountViewer.revoked_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def add_viewer(
    session: AsyncSession, account_id: int, viewer_telegram_id: int, viewer_display_name: str | None = None
) -> AccountViewer:
    row = AccountViewer(
        account_id=account_id, viewer_telegram_id=viewer_telegram_id, viewer_display_name=viewer_display_name
    )
    session.add(row)
    await session.flush()
    return row


async def get_active_viewers_for_account(session: AsyncSession, account_id: int) -> list[AccountViewer]:
    """Every currently-active viewer of `account_id`, for the Podgląd list
    screen and for bot.viewers.forward_to_viewers -- ordered by grant time
    so the list is stable across renders."""
    result = await session.execute(
        select(AccountViewer)
        .where(AccountViewer.account_id == account_id, AccountViewer.revoked_at.is_(None))
        .order_by(AccountViewer.granted_at.asc())
    )
    return list(result.scalars().all())


async def get_active_viewer_grants_for_telegram_id(session: AsyncSession, viewer_telegram_id: int) -> list[AccountViewer]:
    """Every account `viewer_telegram_id` currently has read-only access
    to -- a Telegram account can be granted access by more than one player
    independently (CLAUDE.md step 10: the unique constraint is scoped per
    account, not per viewer). Eagerly loads the watched account, since the
    read-only Moje deble chooser renders every row without a query each.
    """
    result = await session.execute(
        select(AccountViewer)
        .options(selectinload(AccountViewer.account))
        .where(AccountViewer.viewer_telegram_id == viewer_telegram_id, AccountViewer.revoked_at.is_(None))
        .order_by(AccountViewer.granted_at.asc())
    )
    return list(result.scalars().all())


async def revoke_viewer(session: AsyncSession, account_id: int, viewer_id: int, now: datetime) -> AccountViewer | None:
    """Revokes one active viewer grant, verifying it belongs to
    `account_id` first -- a player may only revoke their own grants, never
    somebody else's by guessing an id. Returns None (no-op) if the row
    doesn't exist, isn't this account's, or is already revoked.
    """
    result = await session.execute(
        select(AccountViewer).where(
            AccountViewer.id == viewer_id,
            AccountViewer.account_id == account_id,
            AccountViewer.revoked_at.is_(None),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    row.revoked_at = now
    await session.flush()
    return row


# --- Account deletion and blocking (CLAUDE.md step 12) -----------------------


async def is_pzt_id_blocked(session: AsyncSession, pzt_id: str) -> bool:
    """CLAUDE.md step 12, "Blocking": checked at registration and on every
    invitation send/accept, so a block takes effect immediately for
    someone already registered rather than only at the next registration
    attempt. `blocked_pzt_ids` is written only by a human at psql (see
    docs/RUNBOOK.md) -- there is no code path anywhere that writes to it.
    """
    result = await session.execute(select(BlockedPztId.pzt_id).where(BlockedPztId.pzt_id == pzt_id))
    return result.scalar_one_or_none() is not None


async def clear_name_snapshots_for_pzt_id(session: AsyncSession, pzt_id: str) -> None:
    """If `pzt_id` registers again after an earlier account of theirs was
    deleted, any name snapshot bot.account_deletion.delete_account left on
    their side of an invitation is stale -- they are back, so Moje deble
    should go back to showing the live match (🟢) instead of "confirm in
    person" (⚠️). Called from bot.registration.register_by_pzt_id right
    after a fresh account is created. A no-op for the overwhelming
    majority of registrations, which never had a snapshot to begin with.
    """
    result = await session.execute(
        select(Invitation).where(
            or_(
                (Invitation.inviter_pzt_id == pzt_id) & Invitation.inviter_name_snapshot.is_not(None),
                (Invitation.invitee_pzt_id == pzt_id) & Invitation.invitee_name_snapshot.is_not(None),
            )
        )
    )
    for invitation in result.scalars().all():
        if invitation.inviter_pzt_id == pzt_id:
            invitation.inviter_name_snapshot = None
        if invitation.invitee_pzt_id == pzt_id:
            invitation.invitee_name_snapshot = None
    await session.flush()


async def purge_finished_tournament_name_snapshots(session: AsyncSession, today: date) -> int:
    """CLAUDE.md step 12, "What is actually erased, and what is kept":
    "Purge those snapshots once the tournament has finished." A tournament
    is finished the same way bot.moje_deble.tournament_finished defines it
    -- `date_to` where present, otherwise `date_from`, over at the end of
    that Europe/Warsaw day -- reimplemented here as a SQL predicate rather
    than imported, since this runs as one bulk UPDATE rather than a
    row-by-row Python loop. Returns the number of invitation rows touched,
    for the caller to log.

    Run off the same 6-hour periodic loop as the staleness check
    (bot.staleness) rather than a scheduler of its own -- see
    bot.account_deletion.purge_finished_tournament_snapshots.
    """
    finished_guid = (
        select(Tournament.guid).where(func.coalesce(Tournament.date_to, Tournament.date_from) < today).scalar_subquery()
    )
    stmt = (
        update(Invitation)
        .where(
            Invitation.tournament_guid.in_(finished_guid),
            or_(Invitation.inviter_name_snapshot.is_not(None), Invitation.invitee_name_snapshot.is_not(None)),
        )
        .values(inviter_name_snapshot=None, invitee_name_snapshot=None)
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def delete_pending_external_invites_by_inviter(session: AsyncSession, inviter_pzt_id: str) -> None:
    """CLAUDE.md step 12, "What is actually erased": every still-open
    "invite a non-user" attempt `inviter_pzt_id` made themselves -- their
    own referral, not anyone else's. A row where `inviter_pzt_id` is the
    *invitee* named by somebody else is not this player's own data to
    erase and is left alone.
    """
    await session.execute(delete(PendingExternalInvite).where(PendingExternalInvite.inviter_pzt_id == inviter_pzt_id))


async def delete_account(session: AsyncSession, account: Account) -> None:
    """The one DELETE that removes an `accounts` row (CLAUDE.md step 12,
    "Self-service deletion": "the account row and its viewers go").
    `account_viewers` and `viewer_invite_tokens` both carry
    `ondelete="CASCADE"` foreign keys to `accounts.id`, so Postgres removes
    them itself -- nothing else needs deleting for those two tables. The
    `players` row (and therefore every invitation's FK to it) is untouched:
    it is PZT's own public roster data, not something a CourtDuo account
    deletion erases -- see db.models.invitations' module docstring.
    """
    await session.delete(account)
    await session.flush()


# --- Staleness alarm (CLAUDE.md "Operations") --------------------------------


async def record_scraper_run(
    session: AsyncSession,
    scraper: str,
    started_at: datetime,
    finished_at: datetime,
    ok: bool,
    items_seen: int | None,
    items_written: int | None,
    detail: str | None,
) -> ScraperRun:
    """Records one invocation of a scraper. Callers (scrapers.tournaments
    and scrapers.rankings __main__ modules) write this in a session of its
    own, separate from the session that wrote the scraped data, and commit
    it independently -- so a run that fails halfway through the data write
    still leaves a row behind saying so (CLAUDE.md "Operations").
    """
    run = ScraperRun(
        scraper=scraper,
        started_at=started_at,
        finished_at=finished_at,
        ok=ok,
        items_seen=items_seen,
        items_written=items_written,
        detail=detail,
    )
    session.add(run)
    await session.flush()
    return run


async def get_latest_successful_scraper_run(session: AsyncSession, scraper: str) -> ScraperRun | None:
    """The newest ok=True row for `scraper` -- what bot.staleness measures
    staleness against. A run of failures never moves this: only a
    successful run does (CLAUDE.md "Operations", "a run of failures does
    not reset the clock").
    """
    result = await session.execute(
        select(ScraperRun)
        .where(ScraperRun.scraper == scraper, ScraperRun.ok.is_(True))
        .order_by(ScraperRun.finished_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_scraper_run(session: AsyncSession, scraper: str) -> ScraperRun | None:
    """The newest row for `scraper` regardless of outcome -- used to show
    "last run: failed - <detail>" alongside the last *successful* run.
    """
    result = await session.execute(
        select(ScraperRun).where(ScraperRun.scraper == scraper).order_by(ScraperRun.finished_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def get_alarm_state(session: AsyncSession, key: str) -> AlarmState | None:
    # populate_existing: without it, a `key` already in this session's
    # identity map (e.g. read once, then updated via set_alarm_state's own
    # Core-level UPSERT, which bypasses the ORM and never touches the
    # identity map) would be returned with its stale, pre-update attribute
    # values instead of a fresh read -- the same trap
    # lock_tournament_invitations_for_players documents above.
    result = await session.execute(
        select(AlarmState).where(AlarmState.key == key).execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def set_alarm_state(session: AsyncSession, key: str, firing: bool, last_sent_at: datetime | None) -> AlarmState:
    """Upserts the (firing, last_sent_at) pair for one scraper's alarm.
    Persistent rather than in-memory (CLAUDE.md "Operations": the service
    runs with Restart=always, and in-memory state would fire one alert per
    restart during a crash loop).
    """
    values = {"firing": firing, "last_sent_at": last_sent_at}
    stmt = insert(AlarmState).values(key=key, **values)
    stmt = stmt.on_conflict_do_update(index_elements=[AlarmState.key], set_=values)
    await session.execute(stmt)
    result = await session.execute(
        select(AlarmState).where(AlarmState.key == key).execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def create_support_thread(
    session: AsyncSession, operator_chat_id: int, operator_message_id: int, user_telegram_id: int
) -> SupportThread:
    """One row per (operator, delivered message) -- CLAUDE.md "Operations"
    > "Support". Called once per recipient in `alarm_recipients()` for
    every relayed /pomoc message, so whichever operator replies routes
    back to the right user.
    """
    row = SupportThread(
        operator_chat_id=operator_chat_id,
        operator_message_id=operator_message_id,
        user_telegram_id=user_telegram_id,
    )
    session.add(row)
    await session.flush()
    return row


async def get_support_thread(session: AsyncSession, operator_chat_id: int, operator_message_id: int) -> SupportThread | None:
    """Looks up which user an operator's reply-to message belongs to.
    Returns None for an unmapped message (too old, never written, or the
    reply-to came from a chat/message pair this table never saw) so the
    caller can tell the operator plainly rather than guessing a recipient.
    """
    result = await session.execute(
        select(SupportThread).where(
            SupportThread.operator_chat_id == operator_chat_id,
            SupportThread.operator_message_id == operator_message_id,
        )
    )
    return result.scalar_one_or_none()


async def get_support_conversation(session: AsyncSession, user_telegram_id: int) -> SupportConversation | None:
    """CLAUDE.md "Operations" > "Support": whether this player's plain text
    right now should be relayed -- the caller (bot.middlewares.support_conversation)
    still has to check `is_open` and the 30-minute idle window itself,
    since a row can exist and simply be closed or stale."""
    result = await session.execute(
        select(SupportConversation).where(SupportConversation.user_telegram_id == user_telegram_id)
    )
    return result.scalar_one_or_none()


async def open_support_conversation(session: AsyncSession, user_telegram_id: int, now: datetime) -> SupportConversation:
    """/pomoc, and every silent reopen implied by it -- upserts is_open=True
    with a fresh last_activity_at."""
    values = {"is_open": True, "last_activity_at": now}
    stmt = insert(SupportConversation).values(user_telegram_id=user_telegram_id, **values)
    stmt = stmt.on_conflict_do_update(index_elements=[SupportConversation.user_telegram_id], set_=values)
    await session.execute(stmt)
    result = await session.execute(
        select(SupportConversation)
        .where(SupportConversation.user_telegram_id == user_telegram_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def touch_support_conversation(session: AsyncSession, user_telegram_id: int, now: datetime) -> None:
    """Called after a message is actually relayed, so the 30-minute idle
    window resets on real activity rather than freezing at the open."""
    await session.execute(
        update(SupportConversation)
        .where(SupportConversation.user_telegram_id == user_telegram_id)
        .values(last_activity_at=now)
    )


async def close_support_conversation(session: AsyncSession, user_telegram_id: int) -> None:
    """A no-op when no row exists -- every caller (a command, a persistent-
    keyboard label, expiry, the operator closing) may fire for a player who
    never had a conversation open in the first place."""
    await session.execute(
        update(SupportConversation)
        .where(SupportConversation.user_telegram_id == user_telegram_id)
        .values(is_open=False)
    )


async def get_operator_session(session: AsyncSession, operator_telegram_id: int) -> SupportOperatorSession | None:
    """A row's mere presence is what "this operator has a conversation
    open" means -- the caller still has to check the 60-minute idle
    window itself."""
    result = await session.execute(
        select(SupportOperatorSession).where(SupportOperatorSession.operator_telegram_id == operator_telegram_id)
    )
    return result.scalar_one_or_none()


async def open_operator_session(
    session: AsyncSession, operator_telegram_id: int, user_telegram_id: int, now: datetime
) -> SupportOperatorSession:
    """Tapping "Reply: {name}" on an incoming support message, or the same
    button reused as "reopen" after expiry -- either way, upserts the one
    row this operator may hold onto whichever player it now names."""
    values = {"user_telegram_id": user_telegram_id, "last_activity_at": now}
    stmt = insert(SupportOperatorSession).values(operator_telegram_id=operator_telegram_id, **values)
    stmt = stmt.on_conflict_do_update(index_elements=[SupportOperatorSession.operator_telegram_id], set_=values)
    await session.execute(stmt)
    result = await session.execute(
        select(SupportOperatorSession)
        .where(SupportOperatorSession.operator_telegram_id == operator_telegram_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def touch_operator_session(session: AsyncSession, operator_telegram_id: int, now: datetime) -> None:
    await session.execute(
        update(SupportOperatorSession)
        .where(SupportOperatorSession.operator_telegram_id == operator_telegram_id)
        .values(last_activity_at=now)
    )


async def close_operator_session(session: AsyncSession, operator_telegram_id: int) -> None:
    """A no-op when no row exists. A row in this table is the only thing
    that means "open" -- closing always deletes it rather than flipping a
    flag, unlike support_conversations, which a player might reopen with
    the same is_open column later."""
    await session.execute(
        delete(SupportOperatorSession).where(SupportOperatorSession.operator_telegram_id == operator_telegram_id)
    )

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
section asks to be routed through from day one) and the account CRUD that
registration needs. The invitation engine itself (invitation send/accept/
reject transactions) is bot code, out of scope for this task.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from scrapers.rankings.models import RankingEntry as ScrapedRankingEntry
from scrapers.tournaments.models import Event as ScrapedEvent
from scrapers.tournaments.models import Tournament as ScrapedTournament

from .models import (
    Account,
    AgeCategory,
    Event,
    Gender,
    Player,
    Ranking,
    RankingList,
    Tournament,
)

logger = logging.getLogger(__name__)

_AGE_CATEGORY_BY_LABEL = {c.label: c for c in AgeCategory}
_GENDER_BY_LABEL = {g.value: g for g in Gender}


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


async def can_send_invitation(account: Account, tournament: Tournament) -> bool:
    """Entitlement gate for sending a new invitation (CLAUDE.md,
    "Monetisation — build now, enable later").

    Always True today — everything is free at launch. Invitation creation
    must always route through this function rather than checking
    account.plan/invitations_used directly, so that when paid tiers launch
    exactly one function changes.
    """
    return True

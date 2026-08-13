"""Staleness alarm (see CLAUDE.md, "Operations").

Without this, a dead scraper is invisible: the bot keeps serving whatever
is already in the database until every tournament ages out of the 28-day
search window (CLAUDE.md, "Tournament selection"), and then answers every
search with "nothing found" -- indistinguishable from a genuine empty
result. This module notices instead, by watching `scraper_runs`
(db.models.ScraperRun) -- one row per real scraper invocation, written by
scrapers.tournaments.__main__ and scrapers.rankings.__main__ -- rather
than any column on `tournaments` itself.

Earlier drafts of this feature assumed a `tournaments.scraped_at` column
that could be checked directly. That column was never added, and
`Tournament.updated_at` (db.models.base.TimestampMixin) cannot stand in
for it either: db.crud.upsert_tournament writes via
`INSERT ... ON CONFLICT DO UPDATE`, and SQLAlchemy does not apply a
column's `onupdate` on that path, so `updated_at` freezes at whatever
moment a tournament GUID was first inserted and never moves again on a
re-scrape. `scraper_runs` exists because there is no reliable timestamp
to piggyback on anywhere in the tournaments/rankings tables themselves.

A scraper is STALE when its newest ok=True `scraper_runs` row is older
than its threshold, or when there is no such row at all -- a run of
failures does not reset the clock, which is the entire point: a scraper
that has been failing for a week must alarm just as loudly as one that
stopped running altogether.

The alarm message text below is operator-facing English, hardcoded in
this module -- a deliberate, narrow exception to CLAUDE.md's "never
hardcode user-facing strings". These strings never reach a player; a
Telegram id must be in ALARM_TELEGRAM_IDS (an operator, never a child
player) to ever see them. Routing them through locales/pl.json instead
would put operator text one bad lookup away from a child's screen, which
is worse than the inconsistency of having one module that doesn't use
t().
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.account_deletion import purge_finished_tournament_snapshots
from bot.notifications import push
from db import crud
from db.models import ScraperRun
from db.session import get_session_factory

logger = logging.getLogger(__name__)

SCRAPERS: tuple[str, ...] = ("tournaments", "rankings")

# CLAUDE.md "Operations": rankings run weekly outside the first ten days
# of a month, so 36 hours would false-alarm every week; 9 days covers
# that gap.
_DEFAULT_THRESHOLD_HOURS: dict[str, float] = {
    "tournaments": 36,
    "rankings": 216,
}
_THRESHOLD_ENV_VARS: dict[str, str] = {
    "tournaments": "STALENESS_TOURNAMENTS_HOURS",
    "rankings": "STALENESS_RANKINGS_HOURS",
}

# CLAUDE.md "Operations": one check 30s after startup, then every 6h. Each
# check wakes a scaled-to-zero Neon compute; against a 36h threshold, 6h
# still catches a dead scraper within hours of it mattering, and the
# damage a slower alarm guards against takes weeks, not hours.
INITIAL_DELAY_SECONDS = 30
CHECK_INTERVAL_SECONDS = 6 * 3600

_REMINDER_INTERVAL = timedelta(hours=24)

# In-memory dedupe for the one failure mode that can never reach
# alarm_state: the staleness check's own database query raising (exhausted
# Neon quota, wrong credentials, network). The table that would hold
# proper dedupe state is, by definition, the thing that's unreachable --
# so a per-process, in-memory "at most one alert per 6h per scraper" is
# the correct fallback here, not a shortcut taken for convenience.
_DB_ERROR_DEDUPE_INTERVAL = timedelta(hours=6)


def threshold_hours(scraper: str) -> float:
    """The staleness threshold for `scraper`, read fresh from its env var
    override on every call (same reasoning as entitlements._allowlisted_pzt_ids:
    cheap enough not to cache, and tests need to see an override take
    effect immediately)."""
    env_var = _THRESHOLD_ENV_VARS[scraper]
    raw = os.environ.get(env_var)
    if not raw:
        return _DEFAULT_THRESHOLD_HOURS[scraper]
    return float(raw)


def alarm_recipients() -> list[int]:
    """CLAUDE.md "Operations": ALARM_TELEGRAM_IDS, comma-separated numeric
    Telegram ids, read fresh on every check. Unset or empty is valid --
    the alarm still runs and still logs, it just has nobody to tell."""
    raw = os.environ.get("ALARM_TELEGRAM_IDS", "")
    recipients: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            recipients.append(int(part))
        except ValueError:
            logger.warning("Ignoring non-numeric ALARM_TELEGRAM_IDS entry: %r", part)
    return recipients


def is_stale(latest_successful_run: ScraperRun | None, now: datetime, threshold: float) -> bool:
    """A scraper is stale when it has never had a successful run, or its
    newest successful run is older than `threshold` hours. Only ok=True
    rows are considered -- a run of failures never resets the clock."""
    if latest_successful_run is None:
        return True
    age = now - latest_successful_run.finished_at
    return age > timedelta(hours=threshold)


class AlarmAction(enum.Enum):
    """What bot.staleness's state machine (CLAUDE.md "Operations") decides
    to do for one scraper on one check."""

    NONE = "none"
    ALERT = "alert"
    REMINDER = "reminder"
    RECOVERY = "recovery"


def decide_action(*, stale: bool, firing: bool, last_sent_at: datetime | None, now: datetime) -> AlarmAction:
    """The five-transition state machine from CLAUDE.md "Operations":

    stale, not firing        -> ALERT
    stale, firing, >24h ago  -> REMINDER
    stale, firing, recent    -> NONE
    fresh, firing            -> RECOVERY
    fresh, not firing        -> NONE
    """
    if stale:
        if not firing:
            return AlarmAction.ALERT
        if last_sent_at is None or now - last_sent_at > _REMINDER_INTERVAL:
            return AlarmAction.REMINDER
        return AlarmAction.NONE
    if firing:
        return AlarmAction.RECOVERY
    return AlarmAction.NONE


def _format_age(age: timedelta) -> str:
    hours = round(age.total_seconds() / 3600)
    return f"{hours} hour{'s' if hours != 1 else ''}"


def format_alert_message(
    scraper: str, latest_successful_run: ScraperRun | None, latest_run: ScraperRun | None, now: datetime
) -> str:
    """The ALERT/REMINDER message -- same text for both, since a reminder
    is just the alert re-sent because the condition hasn't cleared."""
    lines = [f"CourtDuo alarm: {scraper} scraper is stale."]
    if latest_successful_run is None:
        lines.append("Last successful run: never.")
    else:
        age = now - latest_successful_run.finished_at
        timestamp = latest_successful_run.finished_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        lines.append(f"Last successful run: {timestamp} UTC ({_format_age(age)} ago).")
    if latest_run is not None and not latest_run.ok:
        detail = latest_run.detail or "no detail recorded"
        lines.append(f"Last run: failed - {detail}")
    lines.append("The bot is still serving whatever is already in the database.")
    return "\n".join(lines)


def format_recovery_message(scraper: str, latest_successful_run: ScraperRun | None, now: datetime) -> str:
    if latest_successful_run is None:
        # Cannot happen in practice -- RECOVERY only fires when `stale` is
        # False, which requires a successful run to compare against -- but
        # falling back rather than crashing the loop is cheap insurance.
        return f"CourtDuo alarm: {scraper} scraper has recovered."
    age = now - latest_successful_run.finished_at
    return f"CourtDuo alarm: {scraper} scraper has recovered. Last successful run: {_format_age(age)} ago."


def format_db_error_message(scraper: str, exc: Exception) -> str:
    return (
        f"CourtDuo alarm: staleness check for {scraper} failed to query the database "
        f"({type(exc).__name__}). The database may be unreachable."
    )


@dataclass
class ScraperStatus:
    """What /status shows for one scraper -- also useful as the return
    shape for anything that wants a plain snapshot without formatting it."""

    scraper: str
    latest_successful_run: ScraperRun | None
    latest_run: ScraperRun | None
    threshold_hours: float
    stale: bool


def format_status_report(statuses: list[ScraperStatus], now: datetime) -> str:
    """The /status command's plain-text body (CLAUDE.md "Operations"):
    for each scraper, its last successful run and how long ago, its last
    run and outcome (which can differ from the last *successful* one),
    and whether it is currently inside its threshold.
    """
    lines = ["CourtDuo status"]
    for status in statuses:
        lines.append("")
        lines.append(status.scraper)
        if status.latest_successful_run is None:
            lines.append("  Last successful run: never")
        else:
            age = now - status.latest_successful_run.finished_at
            timestamp = status.latest_successful_run.finished_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  Last successful run: {timestamp} UTC ({_format_age(age)} ago)")
        if status.latest_run is None:
            lines.append("  Last run: never")
        elif status.latest_run.ok:
            lines.append("  Last run: ok")
        else:
            detail = status.latest_run.detail or "no detail recorded"
            lines.append(f"  Last run: failed - {detail}")
        state = "STALE" if status.stale else "OK"
        lines.append(f"  Status: {state} (threshold {status.threshold_hours:g}h)")
    return "\n".join(lines)


async def get_scraper_status(session: AsyncSession, scraper: str, now: datetime) -> ScraperStatus:
    latest_successful = await crud.get_latest_successful_scraper_run(session, scraper)
    latest_run = await crud.get_latest_scraper_run(session, scraper)
    threshold = threshold_hours(scraper)
    return ScraperStatus(
        scraper=scraper,
        latest_successful_run=latest_successful,
        latest_run=latest_run,
        threshold_hours=threshold,
        stale=is_stale(latest_successful, now, threshold),
    )


async def _check_scraper(bot: Bot, session_factory: async_sessionmaker, scraper: str, now: datetime) -> None:
    async with session_factory() as session:
        status = await get_scraper_status(session, scraper, now)
        alarm_state = await crud.get_alarm_state(session, scraper)

    firing = alarm_state.firing if alarm_state is not None else False
    last_sent_at = alarm_state.last_sent_at if alarm_state is not None else None

    action = decide_action(stale=status.stale, firing=firing, last_sent_at=last_sent_at, now=now)
    if action is AlarmAction.NONE:
        return

    if action is AlarmAction.RECOVERY:
        message = format_recovery_message(scraper, status.latest_successful_run, now)
        new_firing = False
    else:
        message = format_alert_message(scraper, status.latest_successful_run, status.latest_run, now)
        new_firing = True

    recipients = alarm_recipients()
    if not recipients:
        logger.warning(
            "Staleness alarm for %s (%s) has no recipients -- ALARM_TELEGRAM_IDS is unset or empty",
            scraper,
            action.value,
        )
    else:
        for telegram_id in recipients:
            await push(bot, telegram_id, message)

    async with session_factory() as session:
        await crud.set_alarm_state(session, scraper, new_firing, now)
        await session.commit()


# See _DB_ERROR_DEDUPE_INTERVAL: the one place in this module where
# in-memory state is correct rather than a shortcut, because the database
# that would hold real dedupe state is exactly what's unreachable here.
_last_db_error_alert: dict[str, datetime] = {}


async def _alert_db_error(bot: Bot, scraper: str, exc: Exception, now: datetime) -> None:
    last = _last_db_error_alert.get(scraper)
    if last is not None and now - last < _DB_ERROR_DEDUPE_INTERVAL:
        return
    _last_db_error_alert[scraper] = now
    message = format_db_error_message(scraper, exc)
    recipients = alarm_recipients()
    if not recipients:
        logger.warning("Staleness check for %s failed and ALARM_TELEGRAM_IDS is unset -- nobody notified", scraper)
        return
    for telegram_id in recipients:
        await push(bot, telegram_id, message)


async def check_all(bot: Bot, session_factory: async_sessionmaker) -> None:
    now = datetime.now(timezone.utc)
    for scraper in SCRAPERS:
        try:
            await _check_scraper(bot, session_factory, scraper, now)
        except Exception as exc:  # noqa: BLE001 -- a DB error here IS an alarm condition
            logger.exception("Staleness check failed for %s", scraper)
            await _alert_db_error(bot, scraper, exc, now)


async def _loop(bot: Bot, session_factory: async_sessionmaker) -> None:
    await asyncio.sleep(INITIAL_DELAY_SECONDS)
    while True:
        # The background task must never be able to crash the bot -- wrap
        # the whole iteration, log, and keep the cadence regardless of
        # what check_all's own internal handling missed.
        try:
            await check_all(bot, session_factory)
        except Exception:
            logger.exception("Staleness alarm loop iteration failed unexpectedly")
        try:
            await _purge_name_snapshots(session_factory)
        except Exception:
            logger.exception("Name snapshot purge failed unexpectedly")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


_WARSAW_TZ = ZoneInfo("Europe/Warsaw")


async def _purge_name_snapshots(session_factory: async_sessionmaker) -> None:
    """CLAUDE.md step 12: "Add this to the same periodic task that already
    runs the staleness check -- one more query on the existing 6-hour
    loop, not a new scheduler." Its own try/except in _loop, same as
    check_all -- a purge failure must not take the staleness check (or the
    loop itself) down with it.
    """
    today = datetime.now(timezone.utc).astimezone(_WARSAW_TZ).date()
    async with session_factory() as session:
        await purge_finished_tournament_snapshots(session, today)
        await session.commit()


_TASK_KEY = "staleness_task"


async def _on_startup(bot: Bot, dispatcher: Dispatcher) -> None:
    # Reuse db.session.get_session_factory() -- same engine, same pool,
    # rather than opening a second one just for this background task.
    session_factory = get_session_factory()
    dispatcher[_TASK_KEY] = asyncio.create_task(_loop(bot, session_factory))


async def _on_shutdown(dispatcher: Dispatcher) -> None:
    task: asyncio.Task | None = dispatcher.workflow_data.get(_TASK_KEY)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def register(dispatcher: Dispatcher) -> None:
    """Wires the staleness alarm's background task into `dispatcher`'s
    lifecycle -- spawned on startup, cancelled and awaited on shutdown, as
    CLAUDE.md "Operations" specifies."""
    dispatcher.startup.register(_on_startup)
    dispatcher.shutdown.register(_on_shutdown)

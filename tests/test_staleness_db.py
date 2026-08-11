"""db.crud functions the staleness alarm (CLAUDE.md, "Operations") reads
and writes, plus bot.staleness.check_all's full state-machine behaviour
end to end -- against a real Postgres (see tests/conftest.py, skipped
cleanly when TEST_DATABASE_URL is unset).

The pure decide_action/is_stale/formatting logic is covered without a
database in tests/test_staleness.py; these tests are about the things
only a real round trip can prove: the newest-ok=True query actually
ignores a run of failures, alarm_state persists across separate sessions
(the whole reason it isn't an in-memory dict), and check_all drives a
real ALERT -> (no-op) -> RECOVERY sequence against real rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot import staleness
from db import crud

_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    return bot


# --- record_scraper_run / get_latest_*_scraper_run ---------------------------------------


async def test_get_latest_successful_run_ignores_a_trailing_run_of_failures(db_session: AsyncSession):
    await crud.record_scraper_run(
        db_session, "tournaments", _NOW - timedelta(hours=50), _NOW - timedelta(hours=49), True, 10, 10, None
    )
    await crud.record_scraper_run(
        db_session, "tournaments", _NOW - timedelta(hours=2), _NOW - timedelta(hours=1), False, 0, 0, "boom"
    )
    await db_session.flush()

    latest_successful = await crud.get_latest_successful_scraper_run(db_session, "tournaments")
    latest_run = await crud.get_latest_scraper_run(db_session, "tournaments")

    assert latest_successful is not None
    assert latest_successful.ok is True
    assert latest_successful.finished_at == _NOW - timedelta(hours=49)
    # The newest row overall is the failure -- a run of failures does not
    # reset bot.staleness's clock, but /status still needs to be able to
    # show it separately.
    assert latest_run is not None
    assert latest_run.ok is False
    assert latest_run.detail == "boom"


async def test_get_latest_successful_run_none_when_only_failures_exist(db_session: AsyncSession):
    await crud.record_scraper_run(
        db_session, "rankings", _NOW - timedelta(hours=2), _NOW - timedelta(hours=1), False, 0, 0, "no period"
    )
    await db_session.flush()

    assert await crud.get_latest_successful_scraper_run(db_session, "rankings") is None
    latest_run = await crud.get_latest_scraper_run(db_session, "rankings")
    assert latest_run is not None and latest_run.ok is False


async def test_get_latest_run_none_when_no_rows_at_all(db_session: AsyncSession):
    assert await crud.get_latest_successful_scraper_run(db_session, "tournaments") is None
    assert await crud.get_latest_scraper_run(db_session, "tournaments") is None


async def test_runs_for_one_scraper_do_not_leak_into_another(db_session: AsyncSession):
    await crud.record_scraper_run(
        db_session, "tournaments", _NOW - timedelta(hours=1), _NOW, True, 5, 5, None
    )
    await db_session.flush()

    assert await crud.get_latest_successful_scraper_run(db_session, "rankings") is None


# --- alarm_state ---------------------------------------------------------------------------


async def test_get_alarm_state_none_when_never_set(db_session: AsyncSession):
    assert await crud.get_alarm_state(db_session, "tournaments") is None


async def test_set_alarm_state_inserts_then_updates_in_place(db_session: AsyncSession):
    await crud.set_alarm_state(db_session, "tournaments", True, _NOW)
    await db_session.flush()
    state = await crud.get_alarm_state(db_session, "tournaments")
    assert state is not None
    assert state.firing is True
    assert state.last_sent_at == _NOW

    later = _NOW + timedelta(hours=1)
    await crud.set_alarm_state(db_session, "tournaments", False, later)
    await db_session.flush()
    state = await crud.get_alarm_state(db_session, "tournaments")
    assert state.firing is False
    assert state.last_sent_at == later


# --- check_all end to end -------------------------------------------------------------------


async def test_check_all_marks_both_scrapers_firing_on_first_check(
    db_sessionmaker: async_sessionmaker[AsyncSession], monkeypatch
):
    # No recipients configured -- the state machine (and alarm_state) must
    # still run in full; only the actual Telegram send is skipped.
    monkeypatch.delenv("ALARM_TELEGRAM_IDS", raising=False)
    bot = _make_bot()

    # Never ran -> both scrapers are stale and start firing.
    await staleness.check_all(bot, db_sessionmaker)
    assert bot.send_message.await_count == 0
    async with db_sessionmaker() as session:
        tournaments_state = await crud.get_alarm_state(session, "tournaments")
        rankings_state = await crud.get_alarm_state(session, "rankings")
    assert tournaments_state.firing is True
    assert rankings_state.firing is True


async def test_check_all_recovers_once_a_fresh_successful_run_lands(
    db_sessionmaker: async_sessionmaker[AsyncSession], monkeypatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "555")
    bot = _make_bot()

    # Prime both scrapers as already firing (as if a previous check alerted).
    async with db_sessionmaker() as session:
        await crud.set_alarm_state(session, "tournaments", True, datetime.now(timezone.utc) - timedelta(hours=1))
        await crud.set_alarm_state(session, "rankings", True, datetime.now(timezone.utc) - timedelta(hours=1))
        await session.commit()

    # tournaments just had a fresh successful run; rankings still never ran.
    async with db_sessionmaker() as session:
        now = datetime.now(timezone.utc)
        await crud.record_scraper_run(session, "tournaments", now - timedelta(minutes=5), now, True, 5, 5, None)
        await session.commit()

    await staleness.check_all(bot, db_sessionmaker)

    # Exactly one message: tournaments recovered. rankings is still stale
    # and firing, and its last_sent_at is recent (1h ago < 24h), so it
    # stays quiet (AlarmAction.NONE) rather than reminding again.
    assert bot.send_message.await_count == 1
    sent_text = bot.send_message.await_args.args[1]
    assert "tournaments" in sent_text
    assert "recovered" in sent_text

    async with db_sessionmaker() as session:
        tournaments_state = await crud.get_alarm_state(session, "tournaments")
        rankings_state = await crud.get_alarm_state(session, "rankings")
    assert tournaments_state.firing is False
    assert rankings_state.firing is True


async def test_check_all_reminds_after_24h_still_stale(
    db_sessionmaker: async_sessionmaker[AsyncSession], monkeypatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "555")
    bot = _make_bot()

    async with db_sessionmaker() as session:
        await crud.set_alarm_state(
            session, "tournaments", True, datetime.now(timezone.utc) - timedelta(hours=25)
        )
        # rankings just alerted recently -- should stay quiet.
        await crud.set_alarm_state(
            session, "rankings", True, datetime.now(timezone.utc) - timedelta(hours=1)
        )
        await session.commit()

    await staleness.check_all(bot, db_sessionmaker)

    assert bot.send_message.await_count == 1
    sent_text = bot.send_message.await_args.args[1]
    assert "tournaments" in sent_text
    assert "is stale" in sent_text

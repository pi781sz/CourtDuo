"""Pure logic for the staleness alarm (CLAUDE.md, "Operations"): threshold
comparison, the five-transition state machine, the never-ran case, and
message formatting. No database, no Telegram — bot.staleness's I/O is
covered separately in tests/test_staleness_db.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from bot import staleness
from bot.staleness import AlarmAction

_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


@dataclass
class _FakeRun:
    finished_at: datetime
    ok: bool = True
    detail: str | None = None


# --- is_stale -----------------------------------------------------------------------


def test_is_stale_when_there_is_no_successful_run_at_all():
    assert staleness.is_stale(None, _NOW, 36) is True


def test_is_stale_false_within_threshold():
    run = _FakeRun(finished_at=_NOW - timedelta(hours=10))
    assert staleness.is_stale(run, _NOW, 36) is False


def test_is_stale_true_past_threshold():
    run = _FakeRun(finished_at=_NOW - timedelta(hours=40))
    assert staleness.is_stale(run, _NOW, 36) is True


def test_is_stale_exactly_at_threshold_is_not_stale():
    # "older than" -- the boundary itself is still fresh.
    run = _FakeRun(finished_at=_NOW - timedelta(hours=36))
    assert staleness.is_stale(run, _NOW, 36) is False


# --- thresholds -----------------------------------------------------------------------


def test_default_thresholds():
    assert staleness.threshold_hours("tournaments") == 36
    assert staleness.threshold_hours("rankings") == 216


def test_threshold_overridable_by_env_var(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STALENESS_TOURNAMENTS_HOURS", "2")
    assert staleness.threshold_hours("tournaments") == 2
    # rankings is untouched by the tournaments override.
    assert staleness.threshold_hours("rankings") == 216


# --- alarm_recipients -------------------------------------------------------------------


def test_alarm_recipients_empty_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ALARM_TELEGRAM_IDS", raising=False)
    assert staleness.alarm_recipients() == []


def test_alarm_recipients_parses_comma_separated_ids(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", " 111, 222 ,333")
    assert staleness.alarm_recipients() == [111, 222, 333]


def test_alarm_recipients_ignores_non_numeric_entries(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "111,not-a-number,222")
    assert staleness.alarm_recipients() == [111, 222]


# --- decide_action: the five state-machine transitions ---------------------------------


def test_stale_not_firing_alerts():
    action = staleness.decide_action(stale=True, firing=False, last_sent_at=None, now=_NOW)
    assert action is AlarmAction.ALERT


def test_stale_firing_reminder_overdue_reminds():
    action = staleness.decide_action(
        stale=True, firing=True, last_sent_at=_NOW - timedelta(hours=25), now=_NOW
    )
    assert action is AlarmAction.REMINDER


def test_stale_firing_recent_send_does_nothing():
    action = staleness.decide_action(
        stale=True, firing=True, last_sent_at=_NOW - timedelta(hours=1), now=_NOW
    )
    assert action is AlarmAction.NONE


def test_fresh_firing_recovers():
    action = staleness.decide_action(stale=False, firing=True, last_sent_at=_NOW, now=_NOW)
    assert action is AlarmAction.RECOVERY


def test_fresh_not_firing_does_nothing():
    action = staleness.decide_action(stale=False, firing=False, last_sent_at=None, now=_NOW)
    assert action is AlarmAction.NONE


def test_stale_firing_never_sent_reminds_immediately():
    # A firing alarm with no last_sent_at (e.g. a row pre-dating this
    # column, or a state written by hand) must not get stuck at NONE
    # forever -- treat "never sent" as overdue.
    action = staleness.decide_action(stale=True, firing=True, last_sent_at=None, now=_NOW)
    assert action is AlarmAction.REMINDER


# --- message formatting -----------------------------------------------------------------


def test_alert_message_never_ran():
    message = staleness.format_alert_message("tournaments", None, None, _NOW)
    assert "tournaments scraper is stale" in message
    assert "Last successful run: never." in message
    assert "still serving whatever is already in the database" in message


def test_alert_message_includes_age_and_last_failure_detail():
    successful = _FakeRun(finished_at=_NOW - timedelta(hours=58))
    failed = _FakeRun(finished_at=_NOW - timedelta(hours=1), ok=False, detail="httpx.ConnectTimeout")
    message = staleness.format_alert_message("tournaments", successful, failed, _NOW)
    assert "58 hours ago" in message
    assert "Last run: failed - httpx.ConnectTimeout" in message


def test_alert_message_omits_failure_line_when_last_run_was_the_successful_one():
    successful = _FakeRun(finished_at=_NOW - timedelta(hours=40))
    message = staleness.format_alert_message("tournaments", successful, successful, _NOW)
    assert "Last run: failed" not in message


def test_recovery_message_names_the_scraper_and_recency():
    successful = _FakeRun(finished_at=_NOW - timedelta(hours=3))
    message = staleness.format_recovery_message("rankings", successful, _NOW)
    assert "rankings scraper has recovered" in message
    assert "3 hours ago" in message


def test_db_error_message_names_the_exception_class():
    message = staleness.format_db_error_message("tournaments", ConnectionError("boom"))
    assert "tournaments" in message
    assert "ConnectionError" in message


# --- format_status_report ---------------------------------------------------------------


def test_status_report_never_ran_scraper():
    status = staleness.ScraperStatus(
        scraper="rankings",
        latest_successful_run=None,
        latest_run=None,
        threshold_hours=216,
        stale=True,
    )
    report = staleness.format_status_report([status], _NOW)
    assert "rankings" in report
    assert "Last successful run: never" in report
    assert "Last run: never" in report
    assert "Status: STALE" in report


def test_status_report_healthy_scraper():
    run = _FakeRun(finished_at=_NOW - timedelta(hours=1))
    status = staleness.ScraperStatus(
        scraper="tournaments",
        latest_successful_run=run,
        latest_run=run,
        threshold_hours=36,
        stale=False,
    )
    report = staleness.format_status_report([status], _NOW)
    assert "Last run: ok" in report
    assert "Status: OK" in report

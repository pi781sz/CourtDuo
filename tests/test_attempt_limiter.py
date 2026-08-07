"""Tests for bot.attempt_limiter.FailedAttemptLimiter (CLAUDE.md, LOOKUP
RULES: cap failed PZT-id lookups at 5 per Telegram account per hour). A
fake clock replaces time.monotonic so the one-hour window can be tested
without sleeping.
"""

from __future__ import annotations

from bot.attempt_limiter import FailedAttemptLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_not_blocked_before_any_failures():
    limiter = FailedAttemptLimiter(clock=FakeClock())
    assert not limiter.is_blocked(telegram_id=1)


def test_blocked_after_max_attempts():
    clock = FakeClock()
    limiter = FailedAttemptLimiter(max_attempts=5, clock=clock)
    for _ in range(5):
        limiter.record_failure(telegram_id=1)
    assert limiter.is_blocked(telegram_id=1)


def test_not_blocked_one_under_the_cap():
    clock = FakeClock()
    limiter = FailedAttemptLimiter(max_attempts=5, clock=clock)
    for _ in range(4):
        limiter.record_failure(telegram_id=1)
    assert not limiter.is_blocked(telegram_id=1)


def test_attempts_expire_after_the_window():
    clock = FakeClock()
    limiter = FailedAttemptLimiter(max_attempts=5, window_seconds=3600, clock=clock)
    for _ in range(5):
        limiter.record_failure(telegram_id=1)
    assert limiter.is_blocked(telegram_id=1)

    clock.now += 3601
    assert not limiter.is_blocked(telegram_id=1)


def test_accounts_are_tracked_independently():
    clock = FakeClock()
    limiter = FailedAttemptLimiter(max_attempts=5, clock=clock)
    for _ in range(5):
        limiter.record_failure(telegram_id=1)
    assert limiter.is_blocked(telegram_id=1)
    assert not limiter.is_blocked(telegram_id=2)

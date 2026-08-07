"""In-memory cap on failed PZT-id lookups per Telegram account (CLAUDE.md,
LOOKUP RULES: "Cap failed attempts at 5 per Telegram account per hour ...
so the bot cannot be used to enumerate children's names"). Deliberately
not persisted to the database — a bot restart resetting the counter is
an acceptable trade for not needing a table just for this, and matches
CLAUDE.md's own "in-memory counter is fine".
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60 * 60


class FailedAttemptLimiter:
    def __init__(
        self,
        max_attempts: int = MAX_ATTEMPTS,
        window_seconds: float = WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._clock = clock
        self._attempts: dict[int, deque[float]] = defaultdict(deque)

    def _prune(self, telegram_id: int, now: float) -> None:
        attempts = self._attempts[telegram_id]
        cutoff = now - self._window_seconds
        while attempts and attempts[0] < cutoff:
            attempts.popleft()

    def is_blocked(self, telegram_id: int) -> bool:
        now = self._clock()
        self._prune(telegram_id, now)
        return len(self._attempts[telegram_id]) >= self._max_attempts

    def record_failure(self, telegram_id: int) -> None:
        now = self._clock()
        self._prune(telegram_id, now)
        self._attempts[telegram_id].append(now)

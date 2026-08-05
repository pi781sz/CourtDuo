"""Shared async rate limiting for scrapers.

PZT is a national federation, not an API provider — see the "Scraping
etiquette" section of CLAUDE.md. Every outbound request from any scraper
must go through one of these limiters so we never hammer their server.
"""

from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    """Serializes calls so consecutive acquisitions are spaced >= min_interval apart."""

    def __init__(self, min_interval: float = 2.0) -> None:
        self.min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_call: float | None = None

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._last_call is not None:
                elapsed = now - self._last_call
                remaining = self.min_interval - elapsed
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_call = time.monotonic()

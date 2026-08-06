"""Fetches and parses the eight junior ranking lists (Sort=A only).

The published (year, month) is discovered once per run from the ranking
index page — never hardcoded or computed, see CLAUDE.md "Rankings" and
the module docstring in .parser. All requests, including the index fetch,
share one rate limiter since they all hit portal.pzt.pl.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from core.http import build_client
from core.rate_limit import AsyncRateLimiter

from .models import RANKING_INDEX_URL, RankingEntry, RankingList
from .parser import parse_ranking_index, parse_ranking_page

logger = logging.getLogger(__name__)

# CLAUDE.md, "Scraping etiquette": roughly one request per 2 seconds.
_rate_limiter = AsyncRateLimiter(min_interval=2.0)


async def fetch_index_html(client: httpx.AsyncClient) -> str:
    await _rate_limiter.wait()
    response = await client.get(RANKING_INDEX_URL)
    response.raise_for_status()
    return response.text


async def discover_current_period(client: httpx.AsyncClient) -> tuple[int, int] | None:
    """Fetches the ranking index and returns the (year, month) currently published."""
    try:
        html = await fetch_index_html(client)
    except httpx.HTTPError:
        logger.exception("Failed to fetch ranking index (%s)", RANKING_INDEX_URL)
        return None
    period = parse_ranking_index(html)
    if period is None:
        logger.error("Could not discover the current ranking period from the index page")
    return period


async def fetch_ranking_list_html(client: httpx.AsyncClient, ranking_list: RankingList, year: int, month: int) -> str:
    """Fetches the raw ranking page HTML, without parsing. Used by --dump-html."""
    await _rate_limiter.wait()
    url = ranking_list.url(year, month)
    response = await client.get(url)
    response.raise_for_status()
    return response.text


async def fetch_ranking_list(
    client: httpx.AsyncClient, ranking_list: RankingList, year: int, month: int
) -> list[RankingEntry]:
    url = ranking_list.url(year, month)
    await _rate_limiter.wait()
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Failed to fetch %s %d/%d (%s)", ranking_list.code, month, year, url)
        return []
    entries = parse_ranking_page(response.text, ranking_list, year, month, url)
    logger.info("Scraped %d entries for %s %d/%d", len(entries), ranking_list.code, month, year)
    return entries


async def scrape_all_entries(
    ranking_lists: list[RankingList] | None = None,
) -> tuple[int, int, list[RankingEntry]] | None:
    """Scrapes every requested ranking list.

    Returns None if the current period couldn't be discovered (nothing is
    fetched in that case — see CLAUDE.md, "guessing the month produces
    empty pages and silent data loss"). Otherwise returns (year, month,
    entries) for the period actually used.
    """
    ranking_lists = ranking_lists if ranking_lists is not None else list(RankingList)

    async with build_client() as client:
        period = await discover_current_period(client)
        if period is None:
            return None
        year, month = period

        entries: list[RankingEntry] = []
        for ranking_list in ranking_lists:
            entries.extend(await fetch_ranking_list(client, ranking_list, year, month))

    return year, month, entries


def scrape_all_sync(ranking_lists: list[RankingList] | None = None) -> tuple[int, int, list[RankingEntry]] | None:
    return asyncio.run(scrape_all_entries(ranking_lists))

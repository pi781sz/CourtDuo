"""Fetches and parses the four junior tournament category pages.

Adult tournaments (CategoryID=19) are out of scope and never fetched here.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from core.http import build_client
from core.rate_limit import AsyncRateLimiter

from .models import AgeCategory, Tournament
from .parser import parse_category_page

logger = logging.getLogger(__name__)

# CLAUDE.md, "Scraping etiquette": roughly one request per 2 seconds.
_rate_limiter = AsyncRateLimiter(min_interval=2.0)


async def fetch_category(client: httpx.AsyncClient, age_category: AgeCategory) -> list[Tournament]:
    await _rate_limiter.wait()
    url = age_category.url
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Failed to fetch %s (%s)", age_category.label, url)
        return []
    return parse_category_page(response.text, age_category, url)


async def scrape_all(categories: list[AgeCategory] | None = None) -> list[Tournament]:
    categories = categories if categories is not None else list(AgeCategory)
    tournaments: list[Tournament] = []
    async with build_client() as client:
        for category in categories:
            tournaments.extend(await fetch_category(client, category))
    return tournaments


def scrape_all_sync(categories: list[AgeCategory] | None = None) -> list[Tournament]:
    return asyncio.run(scrape_all(categories))

"""Shared HTTP client configuration for scrapers."""

from __future__ import annotations

import os

import httpx

DEFAULT_CONTACT_EMAIL = "contact@courtduo.example"


def build_user_agent() -> str:
    contact = os.environ.get("SCRAPER_CONTACT_EMAIL") or DEFAULT_CONTACT_EMAIL
    return f"CourtDuoScraper/0.1 (+contact: {contact})"


def build_client(**kwargs: object) -> httpx.AsyncClient:
    headers = {"User-Agent": build_user_agent()}
    headers.update(kwargs.pop("headers", {}) or {})  # type: ignore[arg-type]
    return httpx.AsyncClient(headers=headers, timeout=30.0, **kwargs)  # type: ignore[arg-type]

"""Async SQLAlchemy engine/session, shared by the bot, the scrapers and
Alembic (db/migrations/env.py imports get_database_url/get_connect_args
from here so the URL normalization lives in exactly one place).
"""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# Loads .env for local development; a no-op where the environment (GitHub
# Actions secrets, the VM's systemd unit) already sets these vars.
load_dotenv()

_ASYNC_DRIVER_PREFIX = "postgresql+asyncpg://"


def normalize_database_url(raw: str) -> tuple[str, dict]:
    """Rewrites a plain `postgres(ql)://` URL into one asyncpg can use.

    .env.example documents DATABASE_URL as a plain `postgresql://` URL
    (and Heroku-style deploys sometimes set `postgres://`); both are
    rewritten to `postgresql+asyncpg://` here so callers never have to
    think about the driver scheme.

    Neon (and most managed Postgres providers) hand out URLs with an
    `sslmode` query parameter, which is a libpq convention asyncpg's DSN
    parser doesn't understand — passing it through raises at connect
    time. It's stripped from the URL here and translated into the
    `ssl` connect_args asyncpg does understand instead, so callers pass
    connect_args to create_async_engine/async_engine_from_config
    alongside the cleaned URL rather than ever touching sslmode
    themselves.
    """
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://"):
        raw = _ASYNC_DRIVER_PREFIX + raw[len("postgresql://") :]

    parts = urlsplit(raw)
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)

    connect_args: dict = {}
    remaining_pairs = []
    for key, value in query_pairs:
        if key == "sslmode":
            if value != "disable":
                connect_args["ssl"] = True
        else:
            remaining_pairs.append((key, value))

    clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(remaining_pairs), parts.fragment))
    return clean_url, connect_args


def get_database_url() -> str:
    """Reads DATABASE_URL and normalizes it to the asyncpg driver."""
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is not set")
    url, _ = normalize_database_url(raw)
    return url


def get_connect_args() -> dict:
    """The asyncpg connect_args (e.g. `ssl`) implied by DATABASE_URL."""
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is not set")
    _, connect_args = normalize_database_url(raw)
    return connect_args


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_database_url(), pool_pre_ping=True, connect_args=get_connect_args())
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory

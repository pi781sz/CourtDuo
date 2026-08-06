"""Async SQLAlchemy engine/session, shared by the bot, the scrapers and
Alembic (db/migrations/env.py imports get_database_url from here so the
URL normalization lives in exactly one place).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# Loads .env for local development; a no-op where the environment (GitHub
# Actions secrets, the VM's systemd unit) already sets these vars.
load_dotenv()

_ASYNC_DRIVER_PREFIX = "postgresql+asyncpg://"


def get_database_url() -> str:
    """Reads DATABASE_URL and normalizes it to the asyncpg driver.

    .env.example documents DATABASE_URL as a plain `postgresql://` URL
    (and Heroku-style deploys sometimes set `postgres://`); both are
    rewritten to `postgresql+asyncpg://` here so callers never have to
    think about the driver scheme.
    """
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is not set")
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://"):
        raw = _ASYNC_DRIVER_PREFIX + raw[len("postgresql://") :]
    return raw


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_database_url(), pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory

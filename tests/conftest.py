"""Shared fixtures. Database-dependent tests need TEST_DATABASE_URL (a
scratch Postgres — never the production database) and skip cleanly when
it's unset, since this sandbox has no Postgres of its own (CLAUDE.md).

Two fixtures, one engine. `db_session` is the single session almost every
test wants; `db_sessionmaker` is for the step-7 concurrency tests, which
need several sessions on separate connections running overlapping
transactions against the same schema — the whole point of those tests is
that the locking is real, so they cannot share one session.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base
from db.session import normalize_database_url

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def db_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")

    url, connect_args = normalize_database_url(TEST_DATABASE_URL)
    engine = create_async_engine(url, connect_args=connect_args)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncSession:
    async with db_sessionmaker() as session:
        yield session

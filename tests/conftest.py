"""Shared fixtures. Database-dependent tests need TEST_DATABASE_URL (a
scratch Postgres — never the production database) and skip cleanly when
it's unset, since this sandbox has no Postgres of its own (CLAUDE.md).
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
async def db_session() -> AsyncSession:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")

    url, connect_args = normalize_database_url(TEST_DATABASE_URL)
    engine = create_async_engine(url, connect_args=connect_args)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

"""Tests for db.session.normalize_database_url — a pure string
transformation, so these run with no Postgres and no TEST_DATABASE_URL
(unlike the rest of db/, which needs a live database).
"""

from __future__ import annotations

from db.session import normalize_database_url


def test_rewrites_postgres_scheme_to_asyncpg_driver():
    url, connect_args = normalize_database_url("postgres://user:pass@host/db")
    assert url == "postgresql+asyncpg://user:pass@host/db"
    assert connect_args == {}


def test_rewrites_postgresql_scheme_to_asyncpg_driver():
    url, connect_args = normalize_database_url("postgresql://user:pass@host:5432/db")
    assert url == "postgresql+asyncpg://user:pass@host:5432/db"
    assert connect_args == {}


def test_strips_sslmode_require_and_sets_ssl_connect_arg():
    url, connect_args = normalize_database_url("postgresql://user:pass@host/db?sslmode=require")
    assert url == "postgresql+asyncpg://user:pass@host/db"
    assert connect_args == {"ssl": True}


def test_sslmode_disable_strips_param_without_enabling_ssl():
    url, connect_args = normalize_database_url("postgresql://user:pass@host/db?sslmode=disable")
    assert url == "postgresql+asyncpg://user:pass@host/db"
    assert connect_args == {}


def test_no_sslmode_leaves_connect_args_empty():
    url, connect_args = normalize_database_url("postgresql://user:pass@host/db")
    assert url == "postgresql+asyncpg://user:pass@host/db"
    assert connect_args == {}


def test_preserves_other_query_parameters():
    url, connect_args = normalize_database_url("postgresql://user:pass@host/db?sslmode=require&application_name=courtduo")
    assert url == "postgresql+asyncpg://user:pass@host/db?application_name=courtduo"
    assert connect_args == {"ssl": True}


def test_already_asyncpg_scheme_is_left_alone():
    url, connect_args = normalize_database_url("postgresql+asyncpg://user:pass@host/db?sslmode=verify-full")
    assert url == "postgresql+asyncpg://user:pass@host/db"
    assert connect_args == {"ssl": True}

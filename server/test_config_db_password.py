"""Tests for production DB password hardening (Phase H-4, Issue #293).

Covers ``config._require_strong_db_password`` which rejects weak/default
PostgreSQL passwords on production startup while ignoring SQLite/other backends.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import config  # noqa: E402


def test_rejects_weak_password_in_url():
    """A weak password embedded in a postgresql:// URL is rejected."""
    for weak in ("changeme", "pcops", "postgres", "password", "pass"):
        with pytest.raises(ValueError):
            config._require_strong_db_password(
                f"postgresql://user:{weak}@db:5432/pcops"
            )


def test_rejects_empty_password_in_url():
    """An empty/missing password on a postgresql URL is rejected."""
    with pytest.raises(ValueError):
        config._require_strong_db_password("postgresql://user@db:5432/pcops")


def test_allows_strong_password_in_url():
    """A strong password passes without raising."""
    config._require_strong_db_password(
        "postgresql://user:S7r0ng-P%40ss%21@db:5432/pcops"
    )


def test_detects_url_encoded_weak_password():
    """A percent-encoded weak password is still detected (changeme)."""
    with pytest.raises(ValueError):
        config._require_strong_db_password(
            "postgresql://user:changeme@db:5432/pcops"
        )


def test_ignores_sqlite_backend():
    """SQLite (dev/test) connections are never checked."""
    config._require_strong_db_password("sqlite:///pc_ops.db")
    config._require_strong_db_password("sqlite:///:memory:")


def test_ignores_empty_database_url():
    """No DATABASE_URL → nothing to validate, no raise."""
    config._require_strong_db_password(None)
    config._require_strong_db_password("")


def test_postgres_scheme_variants():
    """postgres:// and postgresql+psycopg2:// schemes are both checked."""
    for scheme in ("postgres", "postgresql", "postgresql+psycopg2"):
        with pytest.raises(ValueError):
            config._require_strong_db_password(f"{scheme}://user:changeme@db/pcops")


def test_env_password_overrides_url(monkeypatch):
    """When POSTGRES_PASSWORD is set, it takes precedence over the URL password."""
    # Strong password in URL but weak env var → rejected.
    monkeypatch.setenv("POSTGRES_PASSWORD", "pcops")
    with pytest.raises(ValueError):
        config._require_strong_db_password("postgresql://user:Str0ngUrl@db/pcops")
    # Strong env var but weak URL password → allowed (env wins).
    monkeypatch.setenv("POSTGRES_PASSWORD", "S7r0ng-Env-Pass")
    config._require_strong_db_password("postgresql://user:changeme@db/pcops")

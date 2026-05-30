"""Tests for seed_demo.py production DB safety guard (Issue #302).

Covers ``_resolve_db_path`` and ``_guard_not_production`` which prevent
accidental seeding of the real production database.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import seed_demo  # noqa: E402


def _make_app(uri, instance_path="/app/instance"):
    """Return a minimal mock app with given SQLite URI and instance_path."""
    app = MagicMock()
    app.config = {"SQLALCHEMY_DATABASE_URI": uri}
    app.instance_path = instance_path
    return app


class TestResolveDbPath:
    def test_relative_sqlite_resolved_under_instance(self):
        app = _make_app("sqlite:///pc_ops.db", "/app/instance")
        path = seed_demo._resolve_db_path(app)
        assert path == "/app/instance/pc_ops.db"

    def test_absolute_sqlite_returned_as_is(self):
        app = _make_app("sqlite:////tmp/test.db")
        path = seed_demo._resolve_db_path(app)
        assert path == "/tmp/test.db"

    def test_memory_db_returns_none(self):
        app = _make_app("sqlite:///:memory:")
        assert seed_demo._resolve_db_path(app) is None

    def test_postgres_returns_none(self):
        app = _make_app("postgresql://user:pass@db:5432/pcops")
        assert seed_demo._resolve_db_path(app) is None

    def test_empty_uri_returns_none(self):
        app = _make_app("")
        assert seed_demo._resolve_db_path(app) is None


class TestGuardNotProduction:
    def test_allow_prod_bypasses_guard(self):
        """--allow-prod should disable all checks without error."""
        app = _make_app("sqlite:///pc_ops.db", "/app/instance")
        seed_demo._guard_not_production(app, allow_prod=True)  # must not raise

    def test_tmp_sqlite_is_allowed(self):
        """A DB under /tmp is clearly a throwaway — allowed."""
        app = _make_app("sqlite:////tmp/seed_demo.db")
        seed_demo._guard_not_production(app, allow_prod=False)  # must not raise

    def test_prod_basename_without_allow_prod_raises(self):
        """Targeting instance/pc_ops.db without --allow-prod must be rejected."""
        app = _make_app("sqlite:///pc_ops.db", "/home/user/pc-ops/instance")
        with pytest.raises(SystemExit, match="REFUSING to seed"):
            seed_demo._guard_not_production(app, allow_prod=False)

    def test_no_database_url_env_raises(self, monkeypatch):
        """If DATABASE_URL is not set and DB resolves to non-SQLite, refuse."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        app = _make_app("postgresql://user:pass@db/pcops")
        with pytest.raises(SystemExit, match="REFUSING to seed"):
            seed_demo._guard_not_production(app, allow_prod=False)

    def test_explicit_database_url_postgres_passes(self, monkeypatch):
        """If DATABASE_URL is explicitly set to postgres, operator is responsible."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db/pcops")
        app = _make_app("postgresql://user:pass@db/pcops")
        seed_demo._guard_not_production(app, allow_prod=False)  # must not raise

    def test_named_sqlite_not_prod_basename_passes(self):
        """A SQLite DB named differently from pc_ops.db is allowed."""
        app = _make_app("sqlite:///demo_data.db", "/app/instance")
        seed_demo._guard_not_production(app, allow_prod=False)  # must not raise

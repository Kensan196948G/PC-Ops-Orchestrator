"""Phase H-4 deploy-hardening tests.

Covers:
- ``_require_strong_db_password`` — production PostgreSQL weak-password fail-fast.
- ``ProductionConfig.validate_secrets`` integration of the DB-password check.
- presence of the deploy artifacts (root ``.dockerignore`` and the psycopg2
  driver in ``server/requirements.txt``).
"""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from config import (  # noqa: E402
    ProductionConfig,
    _require_strong_db_password,
)


def _strong_env(overrides=None):
    """Baseline of strong production secrets + a strong PostgreSQL URL."""
    base = {
        "SECRET_KEY": "prod-secret-key-strong-value-123456",
        "JWT_SECRET_KEY": "prod-jwt-secret-strong-value-7890",
        "AGENT_API_KEYS": "agent-key-strong-value-abcdef",
        "DATABASE_URL": "postgresql://user:Str0ng-DB-Pass!@db:5432/pc_ops",
    }
    if overrides:
        base.update(overrides)
    return base


# ── _require_strong_db_password ──────────────────────────────────────────


class TestRequireStrongDbPassword:
    def test_ignores_none(self):
        # No DATABASE_URL configured — nothing to validate.
        _require_strong_db_password(None)

    def test_ignores_sqlite(self):
        # SQLite is development/testing only; never a weak-password risk.
        _require_strong_db_password("sqlite:///:memory:")
        _require_strong_db_password("sqlite:///pc_ops.db")

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://user:pcops@localhost/pc_ops",
            "postgresql://user:changeme@localhost/pc_ops",
            "postgresql://user:pass@localhost/pc_ops",
            "postgresql://user:@localhost/pc_ops",  # empty password
            "postgresql+psycopg2://user:postgres@db:5432/pc_ops",
        ],
    )
    def test_rejects_weak_passwords_in_url(self, url, monkeypatch):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        with pytest.raises(ValueError, match="PostgreSQL"):
            _require_strong_db_password(url)

    def test_rejects_url_encoded_weak_password(self, monkeypatch):
        # "change%6De" percent-decodes to "changeme" and must still be rejected.
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        with pytest.raises(ValueError, match="PostgreSQL"):
            _require_strong_db_password("postgresql://user:change%6De@db/pc_ops")

    def test_accepts_strong_password_in_url(self, monkeypatch):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        _require_strong_db_password("postgresql://user:Str0ng-DB-Pass!@db/pc_ops")

    def test_env_var_overrides_url_and_rejects_weak(self, monkeypatch):
        # POSTGRES_PASSWORD takes precedence over the URL-embedded password.
        monkeypatch.setenv("POSTGRES_PASSWORD", "changeme")
        with pytest.raises(ValueError, match="PostgreSQL"):
            _require_strong_db_password("postgresql://user:Str0ng-DB-Pass!@db/pc_ops")

    def test_env_var_strong_passes_even_if_url_weak(self, monkeypatch):
        # A strong POSTGRES_PASSWORD shadows a placeholder password in the URL.
        monkeypatch.setenv("POSTGRES_PASSWORD", "Str0ng-DB-Pass!")
        _require_strong_db_password("postgresql://user:changeme@db/pc_ops")


# ── validate_secrets integration ─────────────────────────────────────────


def test_validate_secrets_weak_db_password_raises(monkeypatch):
    """production + 弱い埋め込み DB パスワード → ValueError で起動拒否."""
    env = _strong_env({"DATABASE_URL": "postgresql://user:changeme@db/pc_ops"})
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with mock.patch.dict(os.environ, env, clear=False):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        with pytest.raises(ValueError, match="PostgreSQL"):
            ProductionConfig.validate_secrets()


def test_validate_secrets_strong_db_password_passes(monkeypatch):
    """production + 強い DB パスワードなら validate_secrets が通過."""
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with mock.patch.dict(os.environ, _strong_env(), clear=False):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        ProductionConfig.validate_secrets()


def test_validate_secrets_sqlite_unaffected(monkeypatch):
    """SQLite (開発/テスト) では DB パスワード検査が何もしない."""
    env = _strong_env({"DATABASE_URL": "sqlite:///:memory:"})
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with mock.patch.dict(os.environ, env, clear=False):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        ProductionConfig.validate_secrets()


# ── deploy artifacts ─────────────────────────────────────────────────────


def test_dockerignore_exists_and_excludes_secrets():
    """root .dockerignore が機密/不要物を image から除外していること."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dockerignore = os.path.join(repo_root, ".dockerignore")
    assert os.path.isfile(dockerignore), ".dockerignore が repo root に存在しない"
    content = open(dockerignore, encoding="utf-8").read()
    for needed in ("server/.env", "server/instance/", "__pycache__"):
        assert needed in content, f".dockerignore に {needed} の除外が無い"


def test_requirements_includes_psycopg2():
    """本番 requirements.txt に PostgreSQL ドライバが含まれること."""
    req = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    content = open(req, encoding="utf-8").read()
    assert "psycopg2" in content, "requirements.txt に psycopg2 が無い"

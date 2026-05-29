"""config.py tests — env_bool / _require_secret / validate_secrets /
__init_subclass__ plus the Phase H-4 PostgreSQL weak-password fail-fast guard.
"""

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from config import (
    ProductionConfig,
    _INSECURE_DEFAULTS,
    _require_secret,
    _require_strong_db_password,
    env_bool,
)


# Strong baseline environment for production validation tests.
def _strong_env(overrides=None):
    base = {
        "SECRET_KEY": "prod-secret-key-strong-value-123456",
        "JWT_SECRET_KEY": "prod-jwt-secret-strong-value-7890",
        "AGENT_API_KEYS": "agent-key-strong-value-abcdef",
        "DATABASE_URL": "postgresql://user:Str0ng-DB-Pass!@db:5432/pc_ops",
    }
    if overrides:
        base.update(overrides)
    return base


# ── env_bool ─────────────────────────────────────────────────────────────


def test_env_bool_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("MY_FLAG", raising=False)
    assert env_bool("MY_FLAG", True) is True
    assert env_bool("MY_FLAG", False) is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", "on", " on "])
def test_env_bool_truthy_variants(monkeypatch, raw):
    monkeypatch.setenv("MY_FLAG", raw)
    assert env_bool("MY_FLAG", False) is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "random"])
def test_env_bool_falsy_variants(monkeypatch, raw):
    monkeypatch.setenv("MY_FLAG", raw)
    assert env_bool("MY_FLAG", True) is False


# ── _require_secret ──────────────────────────────────────────────────────


def test_require_secret_raises_when_none():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        _require_secret("SECRET_KEY", None)


def test_require_secret_raises_when_empty_string():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        _require_secret("JWT_SECRET_KEY", "")


@pytest.mark.parametrize("insecure", sorted(_INSECURE_DEFAULTS))
def test_require_secret_raises_on_insecure_default(insecure):
    with pytest.raises(ValueError, match="デフォルト値"):
        _require_secret("ANY_NAME", insecure)


def test_require_secret_returns_value_when_safe():
    assert (
        _require_secret("X", "my-strong-secret-1234567890")
        == "my-strong-secret-1234567890"
    )


# ── ProductionConfig.validate_secrets ────────────────────────────────────


def test_validate_secrets_success(monkeypatch):
    """全環境変数が安全な値なら例外なし (DATABASE_URL 未設定 = SQLite 既定)."""
    monkeypatch.setenv("SECRET_KEY", "safe-secret-xyz-0123456789")
    monkeypatch.setenv("JWT_SECRET_KEY", "safe-jwt-secret-9876543210")
    monkeypatch.setenv("AGENT_API_KEYS", "safe-agent-key-abcdef")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    ProductionConfig.validate_secrets()


def test_validate_secrets_missing_secret_key_raises(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "safe")
    monkeypatch.setenv("AGENT_API_KEYS", "safe")
    with pytest.raises(ValueError, match="SECRET_KEY"):
        ProductionConfig.validate_secrets()


def test_validate_secrets_insecure_jwt_raises(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "safe-secret-xyz")
    monkeypatch.setenv("JWT_SECRET_KEY", "change-this-jwt-secret")
    monkeypatch.setenv("AGENT_API_KEYS", "safe-agent-key")
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        ProductionConfig.validate_secrets()


def test_validate_secrets_insecure_agent_keys_raises(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "safe-secret-xyz")
    monkeypatch.setenv("JWT_SECRET_KEY", "safe-jwt-secret")
    monkeypatch.setenv("AGENT_API_KEYS", "default-agent-key")
    with pytest.raises(ValueError, match="AGENT_API_KEYS"):
        ProductionConfig.validate_secrets()


def test_validate_secrets_weak_db_password_raises(monkeypatch):
    """Phase H-4: production + 弱い埋め込み DB パスワード → RuntimeError 系 (ValueError)."""
    env = _strong_env({"DATABASE_URL": "postgresql://user:changeme@db/pc_ops"})
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with mock.patch.dict(os.environ, env, clear=False):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        with pytest.raises(ValueError, match="PostgreSQL"):
            ProductionConfig.validate_secrets()


def test_validate_secrets_strong_db_password_passes(monkeypatch):
    """Phase H-4: production + 強い DB パスワードなら通過."""
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with mock.patch.dict(os.environ, _strong_env(), clear=False):
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        ProductionConfig.validate_secrets()


# ── _require_strong_db_password (Phase H-4) ──────────────────────────────


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
        # "change%6De" decodes to "changeme" and must still be rejected.
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


# ── __init_subclass__ ────────────────────────────────────────────────────


def test_production_config_init_subclass_runs():
    class MyProdSub(ProductionConfig):
        pass

    assert issubclass(MyProdSub, ProductionConfig)


# ── Deploy hardening artifacts (.dockerignore / requirements) ────────────


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

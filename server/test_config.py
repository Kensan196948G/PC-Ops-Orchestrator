"""config.py カバレッジ拡充 — _require_secret / validate_secrets / __init_subclass__."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from config import (
    ProductionConfig,
    _INSECURE_DEFAULTS,
    _require_secret,
    env_bool,
)


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


# ── _require_secret (L19-27) ─────────────────────────────────────────────


def test_require_secret_raises_when_none():
    """L19-22: 値が None なら ValueError."""
    with pytest.raises(ValueError, match="SECRET_KEY"):
        _require_secret("SECRET_KEY", None)


def test_require_secret_raises_when_empty_string():
    """L19-22: 空文字も同様."""
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        _require_secret("JWT_SECRET_KEY", "")


@pytest.mark.parametrize("insecure", sorted(_INSECURE_DEFAULTS))
def test_require_secret_raises_on_insecure_default(insecure):
    """L23-26: insecure default 値は拒否."""
    with pytest.raises(ValueError, match="デフォルト値"):
        _require_secret("ANY_NAME", insecure)


def test_require_secret_returns_value_when_safe():
    """L27: 正常系."""
    assert (
        _require_secret("X", "my-strong-secret-1234567890")
        == "my-strong-secret-1234567890"
    )


# ── ProductionConfig.validate_secrets (L60-62) ───────────────────────────


def test_validate_secrets_success(monkeypatch):
    """全環境変数が安全な値なら例外なし."""
    monkeypatch.setenv("SECRET_KEY", "safe-secret-xyz-0123456789")
    monkeypatch.setenv("JWT_SECRET_KEY", "safe-jwt-secret-9876543210")
    monkeypatch.setenv("AGENT_API_KEYS", "safe-agent-key-abcdef")
    ProductionConfig.validate_secrets()


def test_validate_secrets_missing_secret_key_raises(monkeypatch):
    """SECRET_KEY 未設定 → ValueError."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "safe")
    monkeypatch.setenv("AGENT_API_KEYS", "safe")
    with pytest.raises(ValueError, match="SECRET_KEY"):
        ProductionConfig.validate_secrets()


def test_validate_secrets_insecure_jwt_raises(monkeypatch):
    """JWT_SECRET_KEY が insecure default → ValueError."""
    monkeypatch.setenv("SECRET_KEY", "safe-secret-xyz")
    monkeypatch.setenv("JWT_SECRET_KEY", "change-this-jwt-secret")
    monkeypatch.setenv("AGENT_API_KEYS", "safe-agent-key")
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        ProductionConfig.validate_secrets()


def test_validate_secrets_insecure_agent_keys_raises(monkeypatch):
    """AGENT_API_KEYS が insecure default → ValueError."""
    monkeypatch.setenv("SECRET_KEY", "safe-secret-xyz")
    monkeypatch.setenv("JWT_SECRET_KEY", "safe-jwt-secret")
    monkeypatch.setenv("AGENT_API_KEYS", "default-agent-key")
    with pytest.raises(ValueError, match="AGENT_API_KEYS"):
        ProductionConfig.validate_secrets()


# ── __init_subclass__ (L55-56) ───────────────────────────────────────────


def test_production_config_init_subclass_runs():
    """L55-56: サブクラス定義時に __init_subclass__ が走る."""

    class MyProdSub(ProductionConfig):
        pass

    # サブクラスが正常に作成できる = __init_subclass__ が super を呼んで通過した
    assert issubclass(MyProdSub, ProductionConfig)

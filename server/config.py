import os
from datetime import timedelta
from urllib.parse import unquote, urlsplit

_INSECURE_DEFAULTS = {
    "change-this-secret-key-in-production",
    "change-this-jwt-secret",
    "default-agent-key",
}

# Weak/placeholder database passwords that must never reach production.
_INSECURE_DB_PASSWORDS = {
    "",
    "pass",
    "pcops",
    "changeme",
    "password",
    "postgres",
}


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _require_secret(name: str, value: str | None) -> str:
    if not value:
        raise ValueError(
            f"環境変数 {name} が設定されていません。本番起動前に設定してください。"
        )
    if value in _INSECURE_DEFAULTS:
        raise ValueError(
            f"環境変数 {name} にデフォルト値が使われています。安全な値に変更してください。"
        )
    return value


def _require_strong_db_password(database_url: str | None) -> None:
    """Reject weak/default PostgreSQL passwords on production startup.

    Only PostgreSQL connections are checked; SQLite (development/testing) and
    other backends are ignored. The password is taken from the explicit
    ``POSTGRES_PASSWORD`` environment variable when present, otherwise it is
    parsed out of ``DATABASE_URL``.
    """
    if not database_url:
        return

    parts = urlsplit(database_url)
    # urlsplit lowercases the scheme; cover postgresql / postgres / +driver forms.
    if not parts.scheme.startswith(("postgresql", "postgres")):
        return

    # Prefer the dedicated env var if the deployment supplies one; otherwise
    # fall back to the password embedded in the connection URL.
    env_password = os.environ.get("POSTGRES_PASSWORD")
    if env_password is not None:
        password = env_password
    else:
        # parts.password is percent-decoded for the embedded-URL case so that
        # an encoded weak value (e.g. "changeme") is still detected.
        password = unquote(parts.password) if parts.password is not None else ""

    if password.strip().lower() in _INSECURE_DB_PASSWORDS:
        raise ValueError(
            "PostgreSQL のパスワードが弱いデフォルト値です。"
            "POSTGRES_PASSWORD または DATABASE_URL に安全な値を設定してください。"
        )


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key-in-production")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-this-jwt-secret")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    AGENT_API_KEYS = os.environ.get("AGENT_API_KEYS", "default-agent-key").split(",")

    CORS_ORIGINS: list[str] = os.environ.get("CORS_ORIGINS", "http://localhost").split(
        ","
    )


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///pc_ops.db")


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://user:pass@localhost/pc_ops"
    )

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    @classmethod
    def validate_secrets(cls):
        _require_secret("SECRET_KEY", os.environ.get("SECRET_KEY"))
        _require_secret("JWT_SECRET_KEY", os.environ.get("JWT_SECRET_KEY"))
        _require_secret("AGENT_API_KEYS", os.environ.get("AGENT_API_KEYS"))
        _require_strong_db_password(os.environ.get("DATABASE_URL"))


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    RATELIMIT_ENABLED = False


# SWAGGER_ENABLED is intentionally evaluated in app.create_app() so that runtime
# environment changes (e.g. tests toggling the flag) take effect; class-level
# defaults are bound at import time and would otherwise be sticky.
SWAGGER_DEFAULT_BY_CONFIG = {
    "development": True,
    "default": True,
    "testing": True,
    "production": False,
}


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}

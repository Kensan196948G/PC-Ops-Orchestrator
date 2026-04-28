import os
from datetime import timedelta

_INSECURE_DEFAULTS = {
    "change-this-secret-key-in-production",
    "change-this-jwt-secret",
    "default-agent-key",
}


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


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    RATELIMIT_ENABLED = False


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}

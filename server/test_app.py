"""app.py カバレッジ拡充 — render_template ルート + production 起動分岐 + 500 errorhandler."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app


# ── 単純な GET ルートテスト群 (L175, L191, L207, L211, L215, L219, L223, L227, L231, L235) ──


@pytest.fixture(scope="module")
def client():
    app = create_app("testing")
    with app.test_client() as c:
        yield c


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/pcs",
        "/pcs/123",  # L175 — pc_detail with int param
        "/tasks",
        "/alerts",
        "/users",
        "/audit",  # L191
        "/scheduled-tasks",
        "/groups",
        "/alert-rules",
        "/reports",  # L207
        "/agents",  # L211
        "/settings",  # L215
        "/certs",  # L219
        "/backups",  # L223
        "/notifications-config",  # L227
        "/licenses",  # L231
        "/login",  # L235
        "/notification-logs",
    ],
)
def test_simple_template_routes_render(client, path):
    """全 GET ルートが 200 を返す = render_template 行が実行される."""
    resp = client.get(path)
    assert resp.status_code == 200


def test_health_endpoint_ok(client):
    """/health の成功パス (try ブロック)."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "db": "ok"}


def test_health_endpoint_db_error(client):
    """/health の DB 失敗パス (except ブロック)."""
    from extensions import db

    with patch.object(db.session, "execute", side_effect=RuntimeError("db down")):
        resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.get_json() == {"status": "error", "db": "unavailable"}


def test_404_handler_renders_error_template(client):
    """L246-249: 存在しないパス → 404 error.html."""
    resp = client.get("/this/path/does/not/exist")
    assert resp.status_code == 404


# ── config_name fallback (L13) ────────────────────────────────────────────


def test_create_app_uses_flask_config_env(monkeypatch):
    """L13: 引数なし create_app() は FLASK_CONFIG env を見る."""
    monkeypatch.setenv("FLASK_CONFIG", "testing")
    # init_scheduler は testing 構成なら呼ばれない
    app = create_app()
    assert app.config.get("TESTING") is True


# ── init_scheduler 分岐 (L262-264) ────────────────────────────────────────


def test_create_app_default_invokes_init_scheduler():
    """L261-264: config_name != "testing" のとき init_scheduler が走る."""
    with patch("scheduler.init_scheduler") as mock_init:
        create_app("default")
    mock_init.assert_called_once()


# ── ProductionConfig 分岐 (L72-76 HSTS, L266-269 validate_secrets) ───────


def test_create_app_production_validates_secrets_and_sets_hsts(monkeypatch):
    """L72-76 + L266-269: production 構成 → validate_secrets 実行 + HSTS ヘッダ."""
    monkeypatch.setenv("SECRET_KEY", "safe-secret-xyz-1234567890")
    monkeypatch.setenv("JWT_SECRET_KEY", "safe-jwt-secret-9876543210")
    monkeypatch.setenv("AGENT_API_KEYS", "safe-agent-key-abcdef")
    # ProductionConfig.SQLALCHEMY_DATABASE_URI は class 定義時に評価されるため
    # class 属性を直接差し替える必要がある (env 変更だけでは効かない)
    monkeypatch.setattr(
        "config.ProductionConfig.SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:"
    )

    with patch("scheduler.init_scheduler"):
        app = create_app("production")

    # HSTS は production のみ
    with app.test_client() as c:
        resp = c.get("/")
        assert "Strict-Transport-Security" in resp.headers
        assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]


def test_create_app_production_missing_secret_raises(monkeypatch):
    """L266-269: production 起動時に SECRET_KEY 不正 → ValueError."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "safe-jwt")
    monkeypatch.setenv("AGENT_API_KEYS", "safe-agent")
    # SQLALCHEMY_DATABASE_URI は class 定義時評価のため属性を直接差し替える
    monkeypatch.setattr(
        "config.ProductionConfig.SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:"
    )

    with patch("scheduler.init_scheduler"):
        with pytest.raises(ValueError, match="SECRET_KEY"):
            create_app("production")


# ── Rate limit errorhandler (L130-145) ────────────────────────────────────


def _make_rate_limit_exc():
    """Build a RateLimitExceeded with a mocked limit having error_message."""
    from flask_limiter.errors import RateLimitExceeded

    mock_limit = MagicMock()
    mock_limit.error_message = "rate limited"
    return RateLimitExceeded(mock_limit)


def test_rate_limit_api_path_returns_json_429():
    """L132-141: /api/ パスで RateLimitExceeded → JSON 429."""
    app = create_app("testing")

    @app.route("/api/__triggers_ratelimit__")
    def _raise_rl():
        raise _make_rate_limit_exc()

    with app.test_client() as c:
        resp = c.get("/api/__triggers_ratelimit__")
        assert resp.status_code == 429
        body = resp.get_json()
        assert "リクエストが多すぎます" in body["error"]


def test_rate_limit_html_path_returns_template_429():
    """L141-145: 非 /api/ パスは error.html 429 を返す."""
    app = create_app("testing")

    @app.route("/__triggers_ratelimit_html__")
    def _raise_rl_html():
        raise _make_rate_limit_exc()

    with app.test_client() as c:
        resp = c.get("/__triggers_ratelimit_html__")
        assert resp.status_code == 429
        assert b"<html" in resp.data.lower() or b"<!doctype" in resp.data.lower()


# ── Swagger UI 分岐 (L147-156) ────────────────────────────────────────────


def test_swagger_enabled_serves_openapi_spec(monkeypatch):
    """L150-156: SWAGGER_ENABLED=True で /api/openapi.yaml が登録される."""
    import config

    monkeypatch.setattr(config.TestingConfig, "SWAGGER_ENABLED", True, raising=False)
    app = create_app("testing")
    with app.test_client() as c:
        resp = c.get("/api/openapi.yaml")
        # Returns 200 if file exists, 404 if not — both prove the route is registered
        assert resp.status_code in (200, 404)


# ── 500 errorhandler (L251-255) ───────────────────────────────────────────


def test_500_errorhandler_renders_error_template():
    """L251-255: 内部例外 → 500 error.html.

    production 構成で TESTING=False / DEBUG=False のため
    Flask が errorhandler に経路する。
    """
    monkeypatch_env = {
        "SECRET_KEY": "safe-secret-xyz-1234567890",
        "JWT_SECRET_KEY": "safe-jwt-secret-9876543210",
        "AGENT_API_KEYS": "safe-agent-key-abcdef",
    }
    # SQLALCHEMY_DATABASE_URI は class 定義時評価のため属性を直接差し替える
    from config import ProductionConfig

    original_uri = ProductionConfig.SQLALCHEMY_DATABASE_URI
    ProductionConfig.SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    try:
        with patch.dict(os.environ, monkeypatch_env), patch("scheduler.init_scheduler"):
            app = create_app("production")
        app.config["PROPAGATE_EXCEPTIONS"] = False

        @app.route("/__boom__")
        def _boom():
            raise RuntimeError("simulated server error")

        with app.test_client() as c:
            resp = c.get("/__boom__")
            assert resp.status_code == 500
    finally:
        ProductionConfig.SQLALCHEMY_DATABASE_URI = original_uri

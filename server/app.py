import os
import secrets
from flask import Flask, render_template, jsonify, send_from_directory, g
from werkzeug.middleware.proxy_fix import ProxyFix
from config import SWAGGER_DEFAULT_BY_CONFIG, config, env_bool
from extensions import db, migrate, limiter, cors

API_DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_docs")


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get("FLASK_CONFIG", "default")

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config[config_name])
    app.config["SWAGGER_ENABLED"] = env_bool(
        "SWAGGER_ENABLED",
        SWAGGER_DEFAULT_BY_CONFIG.get(config_name, False),
    )

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.before_request
    def _generate_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def inject_feature_flags():
        return {
            "swagger_enabled": bool(app.config.get("SWAGGER_ENABLED")),
            "csp_nonce": g.get("csp_nonce", ""),
        }

    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    cors.init_app(app, origins=app.config.get("CORS_ORIGINS", ["http://localhost"]))

    # CSP Phase 3 complete: all inline style="" attributes and <style> blocks have
    # been migrated to external CSS classes, so 'unsafe-inline' is removed from style-src.
    _CSP_SCRIPT_TMPL = (
        "default-src 'self'; "
        "script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    @app.after_request
    def _set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), camera=(), microphone=(), payment=()",
        )
        custom_csp = app.config.get("CONTENT_SECURITY_POLICY")
        nonce = g.get("csp_nonce", "")
        csp = custom_csp if custom_csp else _CSP_SCRIPT_TMPL.format(nonce=nonce)
        response.headers.setdefault("Content-Security-Policy", csp)
        # HSTS only makes sense over HTTPS — apply only in production where the
        # reverse proxy terminates TLS. Avoid sending it in dev/test (HTTP).
        if config_name == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    from routes.auth_routes import auth_bp
    from routes.collect import collect_bp
    from routes.tasks import tasks_bp
    from routes.pcs import pcs_bp
    from routes.dashboard import dashboard_bp
    from routes.alerts import alerts_bp
    from routes.audit import audit_bp
    from routes.scheduled_tasks import scheduled_tasks_bp
    from routes.groups import groups_bp
    from routes.alert_rules import alert_rules_bp
    from routes.metrics import metrics_bp
    from routes.reports import reports_bp
    from routes.agents import agents_bp
    from routes.notification_channels import notification_channels_bp
    from routes.certificates import certificates_bp
    from routes.licenses import licenses_bp
    from routes.api_keys import api_keys_bp
    from routes.settings import settings_bp
    from routes.backups import backups_bp
    from routes.seed import seed_bp
    from routes.job_templates import job_templates_bp
    from routes.ad_sync import ad_sync_bp
    from routes.admin_ops import admin_ops_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(collect_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(pcs_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(scheduled_tasks_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(alert_rules_bp)
    app.register_blueprint(metrics_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(notification_channels_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(api_keys_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(backups_bp)
    app.register_blueprint(seed_bp, url_prefix="/api")
    app.register_blueprint(job_templates_bp)
    app.register_blueprint(ad_sync_bp)
    app.register_blueprint(admin_ops_bp)

    # Rate limiter -> /metrics integration:
    # increment the in-process counter every time Flask-Limiter rejects a
    # request, so Prometheus can graph "ratelimit_hits_total".
    # API paths get a JSON body, HTML pages fall back to the existing 4xx
    # template so the WebUI doesn't suddenly receive raw JSON.
    from flask import request as _flask_request
    from flask_limiter.errors import RateLimitExceeded
    from metrics import bump_counter

    @app.errorhandler(RateLimitExceeded)
    def _on_rate_limit_exceeded(e):
        bump_counter("ratelimit_hits_total")
        if _flask_request.path.startswith("/api/"):
            return jsonify(
                {
                    "error": (
                        "リクエストが多すぎます。しばらく待ってから再試行してください"
                    )
                }
            ), 429
        return render_template(
            "error.html",
            code=429,
            message="リクエストが多すぎます。しばらく待ってから再試行してください",
        ), 429

    if app.config.get("SWAGGER_ENABLED", False):
        from flask_swagger_ui import get_swaggerui_blueprint

        @app.route("/api/openapi.yaml")
        def openapi_spec():
            return send_from_directory(
                API_DOCS_DIR,
                "openapi.yaml",
                mimetype="application/yaml",
            )

        swaggerui_bp = get_swaggerui_blueprint(
            "/api/docs",
            "/api/openapi.yaml",
            config={"app_name": "PC-Ops Orchestrator API"},
        )
        app.register_blueprint(swaggerui_bp)

    @app.route("/")
    def index():
        return render_template("dashboard.html")

    @app.route("/pcs")
    def pc_list():
        return render_template("pc_list.html")

    @app.route("/pcs/<int:pc_id>")
    def pc_detail(pc_id):
        return render_template("pc_detail.html", pc_id=pc_id)

    @app.route("/tasks")
    def task_list():
        return render_template("tasks.html")

    @app.route("/alerts")
    def alerts_page():
        return render_template("alerts.html")

    @app.route("/users")
    def users_page():
        return render_template("users.html")

    @app.route("/audit")
    def audit_page():
        return render_template("audit.html")

    @app.route("/scheduled-tasks")
    def scheduled_tasks_page():
        return render_template("scheduled_tasks.html")

    @app.route("/groups")
    def groups_page():
        return render_template("groups.html")

    @app.route("/alert-rules")
    def alert_rules_page():
        return render_template("alert_rules.html")

    @app.route("/reports")
    def reports_page():
        return render_template("reports.html")

    @app.route("/agents")
    def agents_page():
        return render_template("agents.html")

    @app.route("/settings")
    def settings_page():
        return render_template("settings.html")

    @app.route("/certs")
    def certs_page():
        return render_template("certs.html")

    @app.route("/backups")
    def backups_page():
        return render_template("backups.html")

    @app.route("/notifications-config")
    def notifications_config_page():
        return render_template("notifications_config.html")

    @app.route("/licenses")
    def licenses_page():
        return render_template("licenses.html")

    @app.route("/login")
    def login_page():
        return render_template("login.html")

    @app.route("/health")
    def health():
        try:
            db.session.execute(db.text("SELECT 1"))
            return jsonify({"status": "ok", "db": "ok"})
        except Exception:
            return jsonify({"status": "error", "db": "unavailable"}), 503

    @app.errorhandler(404)
    def not_found(e):
        return render_template(
            "error.html", code=404, message="ページが見つかりません"
        ), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template(
            "error.html", code=500, message="サーバーエラーが発生しました"
        ), 500

    with app.app_context():
        db.create_all()

    # Start background scheduler (skip in testing to avoid thread leaks)
    if config_name != "testing":
        from scheduler import init_scheduler

        init_scheduler(app)

    if config_name == "production":
        from config import ProductionConfig

        ProductionConfig.validate_secrets()

    return app


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    app = create_app()
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug)

import os
from flask import Flask, render_template, jsonify, send_from_directory
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

    @app.context_processor
    def inject_feature_flags():
        return {"swagger_enabled": bool(app.config.get("SWAGGER_ENABLED"))}

    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    cors.init_app(app, origins=app.config.get("CORS_ORIGINS", ["http://localhost"]))

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

    # Rate limiter -> /metrics integration:
    # increment the in-process counter every time Flask-Limiter rejects a
    # request, so Prometheus can graph "ratelimit_hits_total".
    from flask_limiter.errors import RateLimitExceeded
    from metrics import bump_counter

    @app.errorhandler(RateLimitExceeded)
    def _on_rate_limit_exceeded(e):
        bump_counter("ratelimit_hits_total")
        return jsonify(
            {"error": "リクエストが多すぎます。しばらく待ってから再試行してください"}
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


if __name__ == "__main__":
    app = create_app()
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug)

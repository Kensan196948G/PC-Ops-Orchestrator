import os
from flask import Flask, render_template, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from config import config
from extensions import db, migrate, limiter, cors


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get("FLASK_CONFIG", "default")

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config[config_name])

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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

    if app.config.get("SWAGGER_ENABLED", config_name != "production"):
        from flask_swagger_ui import get_swaggerui_blueprint

        swaggerui_bp = get_swaggerui_blueprint(
            "/api/docs",
            "/static/openapi.yaml",
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

import os
from flask import Flask, render_template, jsonify
from config import config
from extensions import db, migrate
from auth import login_required


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get("FLASK_CONFIG", "default")

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config[config_name])

    db.init_app(app)
    migrate.init_app(app, db)

    from routes.auth_routes import auth_bp
    from routes.collect import collect_bp
    from routes.tasks import tasks_bp
    from routes.pcs import pcs_bp
    from routes.dashboard import dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(collect_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(pcs_bp)
    app.register_blueprint(dashboard_bp)

    @app.route("/")
    @login_required
    def index():
        return render_template("dashboard.html")

    @app.route("/pcs")
    @login_required
    def pc_list():
        return render_template("pc_list.html")

    @app.route("/pcs/<int:pc_id>")
    @login_required
    def pc_detail(pc_id):
        return render_template("pc_detail.html", pc_id=pc_id)

    @app.route("/tasks")
    @login_required
    def task_list():
        return render_template("tasks.html")

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

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)

from flask import Blueprint, jsonify, request

from auth import admin_required, log_operation, login_required
from extensions import db
from models import SystemSetting

settings_bp = Blueprint("settings", __name__, url_prefix="/api")

_ALLOWED_KEYS = frozenset(
    {
        "timezone",
        "language",
        "log_level",
        "session_timeout_minutes",
        "jwt_expiry_hours",
        "refresh_token_days",
        "password_min_length",
        "login_lock_threshold",
        "mfa_mode",
        "heartbeat_interval_seconds",
        "agent_timeout_seconds",
        "collection_interval_minutes",
        "agent_auto_approve",
    }
)

_DEFAULTS = {
    "timezone": "Asia/Tokyo",
    "language": "ja",
    "log_level": "INFO",
    "session_timeout_minutes": "30",
    "jwt_expiry_hours": "8",
    "refresh_token_days": "30",
    "password_min_length": "8",
    "login_lock_threshold": "5",
    "mfa_mode": "disabled",
    "heartbeat_interval_seconds": "60",
    "agent_timeout_seconds": "30",
    "collection_interval_minutes": "5",
    "agent_auto_approve": "false",
}


def _get_all() -> dict:
    rows = SystemSetting.query.all()
    stored = {r.key: r.value for r in rows}
    return {k: stored.get(k, v) for k, v in _DEFAULTS.items()}


@settings_bp.route("/settings", methods=["GET"])
@login_required
def get_settings():
    return jsonify({"settings": _get_all()})


@settings_bp.route("/settings", methods=["PUT"])
@admin_required
def update_settings():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    unknown = set(data.keys()) - _ALLOWED_KEYS
    if unknown:
        return jsonify({"error": f"不明なキー: {sorted(unknown)}"}), 400

    for key, value in data.items():
        row = db.session.get(SystemSetting, key)
        if row:
            row.value = str(value)
        else:
            db.session.add(SystemSetting(key=key, value=str(value)))

    db.session.commit()
    log_operation("update_settings", "system", f"keys={sorted(data.keys())}")
    return jsonify({"message": "設定を保存しました", "settings": _get_all()})

"""AD basic integration (Phase C-3, Issue #230) — user sync only.

Endpoints:
  GET  /api/ad/config   — get current AD config (admin)
  PUT  /api/ad/config   — update AD config (admin)
  GET  /api/ad/status   — test AD connection (admin)
  POST /api/ad/sync     — trigger user sync from AD (admin)
"""

import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from auth import admin_required, hash_password, log_operation
from extensions import db
from models import SystemSetting, User

ad_sync_bp = Blueprint("ad_sync", __name__, url_prefix="/api/ad")

_AD_KEYS = frozenset(
    {
        "ad_host",
        "ad_port",
        "ad_use_ssl",
        "ad_bind_dn",
        "ad_bind_password",
        "ad_base_dn",
        "ad_user_filter",
        "ad_default_role",
    }
)

_AD_DEFAULTS = {
    "ad_host": "",
    "ad_port": "389",
    "ad_use_ssl": "false",
    "ad_bind_dn": "",
    "ad_bind_password": "",
    "ad_base_dn": "",
    "ad_user_filter": "(&(objectClass=user)(objectCategory=person))",
    "ad_default_role": "viewer",
}

_SAFE_KEYS = frozenset(_AD_KEYS - {"ad_bind_password"})


def _get_ad_config() -> dict:
    rows = SystemSetting.query.filter(SystemSetting.key.in_(_AD_KEYS)).all()
    stored = {r.key: r.value for r in rows}
    return {k: stored.get(k, v) for k, v in _AD_DEFAULTS.items()}


def _get_safe_config() -> dict:
    cfg = _get_ad_config()
    cfg["ad_bind_password"] = "***" if cfg.get("ad_bind_password") else ""
    return cfg


@ad_sync_bp.route("/config", methods=["GET"])
@admin_required
def get_ad_config():
    """Return AD config (bind_password masked)."""
    return jsonify({"config": _get_safe_config()})


@ad_sync_bp.route("/config", methods=["PUT"])
@admin_required
def update_ad_config():
    """Update AD config. Unknown keys are rejected."""
    data = request.get_json() or {}
    invalid = set(data.keys()) - _AD_KEYS
    if invalid:
        return jsonify({"error": f"不明なキー: {sorted(invalid)}"}), 400

    for key, value in data.items():
        row = SystemSetting.query.get(key)
        if row:
            row.value = str(value)
        else:
            db.session.add(SystemSetting(key=key, value=str(value)))
    db.session.commit()
    log_operation("ad_config_updated", details=f"keys={sorted(data.keys())}")
    return jsonify({"message": "AD 設定を更新しました", "config": _get_safe_config()})


@ad_sync_bp.route("/status", methods=["GET"])
@admin_required
def ad_status():
    """Test AD connection and return result."""
    from ad_client import test_ad_connection

    cfg = _get_ad_config()
    host = os.environ.get("AD_HOST") or cfg["ad_host"]
    if not host:
        return jsonify(
            {"connected": False, "message": "AD host が設定されていません"}
        ), 503

    port = int(os.environ.get("AD_PORT") or cfg["ad_port"] or 389)
    bind_dn = os.environ.get("AD_BIND_DN") or cfg["ad_bind_dn"]
    bind_password = os.environ.get("AD_BIND_PASSWORD") or cfg["ad_bind_password"]
    use_ssl = (os.environ.get("AD_USE_SSL") or cfg["ad_use_ssl"]).lower() in (
        "true",
        "1",
        "yes",
    )

    ok, message = test_ad_connection(
        host=host,
        port=port,
        bind_dn=bind_dn,
        bind_password=bind_password,
        use_ssl=use_ssl,
    )
    return jsonify({"connected": ok, "message": message}), (200 if ok else 503)


@ad_sync_bp.route("/sync", methods=["POST"])
@admin_required
def sync_ad_users():
    """Sync AD users into the local user table (upsert, no delete)."""
    from ad_client import search_ad_users

    cfg = _get_ad_config()
    host = os.environ.get("AD_HOST") or cfg["ad_host"]
    if not host:
        return jsonify({"error": "AD host が設定されていません"}), 503

    port = int(os.environ.get("AD_PORT") or cfg["ad_port"] or 389)
    bind_dn = os.environ.get("AD_BIND_DN") or cfg["ad_bind_dn"]
    bind_password = os.environ.get("AD_BIND_PASSWORD") or cfg["ad_bind_password"]
    base_dn = os.environ.get("AD_BASE_DN") or cfg["ad_base_dn"]
    user_filter = cfg["ad_user_filter"]
    use_ssl = (os.environ.get("AD_USE_SSL") or cfg["ad_use_ssl"]).lower() in (
        "true",
        "1",
        "yes",
    )
    default_role = cfg.get("ad_default_role", "viewer")

    ad_users = search_ad_users(
        host=host,
        port=port,
        bind_dn=bind_dn,
        bind_password=bind_password,
        base_dn=base_dn,
        user_filter=user_filter,
        use_ssl=use_ssl,
    )

    if ad_users is None:
        return jsonify({"error": "AD への接続に失敗しました"}), 503

    created = 0
    updated = 0
    now = datetime.now(timezone.utc)

    for ad_user in ad_users:
        username = ad_user.get("username", "").strip()
        if not username:
            continue

        existing = User.query.filter_by(username=username).first()
        if existing:
            existing.ad_dn = ad_user["dn"]
            existing.ad_synced_at = now
            updated += 1
        else:
            new_user = User(
                username=username,
                password_hash=hash_password(os.urandom(32).hex()),
                role=default_role,
                is_active=not ad_user.get("disabled", False),
                ad_dn=ad_user["dn"],
                ad_synced_at=now,
            )
            db.session.add(new_user)
            created += 1

    db.session.commit()

    log_operation(
        "ad_sync_completed",
        details=f"created={created} updated={updated} total_ad={len(ad_users)}",
    )

    return jsonify(
        {
            "message": "AD 同期が完了しました",
            "created": created,
            "updated": updated,
            "total_ad_users": len(ad_users),
            "synced_at": now.isoformat(),
        }
    )

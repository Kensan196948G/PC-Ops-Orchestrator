"""Microsoft Graph Windows Updates integration (Issue #250).

Endpoints:
  GET  /api/msgraph/config   — get current Graph config (admin, secret masked)
  PUT  /api/msgraph/config   — update Graph config (admin)
  GET  /api/msgraph/status   — test Graph connection (admin)
  POST /api/msgraph/sync     — sync Windows Update data from Graph (admin)
"""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from auth import admin_required, log_operation
from extensions import db
from models import PC, SystemSetting, WindowsUpdate

bp = Blueprint("msgraph", __name__, url_prefix="/api/msgraph")

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_SCOPE = "https://graph.microsoft.com/.default"

_CONFIG_KEYS = frozenset(
    {"msgraph_tenant_id", "msgraph_client_id", "msgraph_client_secret"}
)
_SECRET_KEY = "msgraph_client_secret"

_DEFAULTS: dict[str, str] = {
    "msgraph_tenant_id": "",
    "msgraph_client_id": "",
    "msgraph_client_secret": "",
}


def _get_config() -> dict:
    rows = SystemSetting.query.filter(SystemSetting.key.in_(_CONFIG_KEYS)).all()
    stored = {r.key: r.value or "" for r in rows}
    return {k: stored.get(k, v) for k, v in _DEFAULTS.items()}


def _get_safe_config() -> dict:
    cfg = _get_config()
    cfg[_SECRET_KEY] = "***" if cfg.get(_SECRET_KEY) else ""
    return cfg


def _acquire_token(cfg: dict) -> str:
    """Obtain an OAuth2 access token using client credentials."""
    import requests as http_req

    resp = http_req.post(
        _TOKEN_URL.format(tenant_id=cfg["msgraph_tenant_id"]),
        data={
            "grant_type": "client_credentials",
            "client_id": cfg["msgraph_client_id"],
            "client_secret": cfg["msgraph_client_secret"],
            "scope": _SCOPE,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _graph_get(token: str, path: str, params: dict | None = None) -> dict:
    import requests as http_req

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = http_req.get(
        f"{_GRAPH_BASE}{path}", headers=headers, params=params, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


@bp.route("/config", methods=["GET"])
@admin_required
def get_config():
    """Return Graph config (client_secret masked)."""
    return jsonify({"config": _get_safe_config()})


@bp.route("/config", methods=["PUT"])
@admin_required
def update_config():
    """Update Graph config. Unknown keys are rejected."""
    data = request.get_json() or {}
    invalid = set(data.keys()) - _CONFIG_KEYS
    if invalid:
        return jsonify({"error": f"不明なキー: {sorted(invalid)}"}), 400

    for key, value in data.items():
        row = db.session.get(SystemSetting, key)
        if row:
            row.value = str(value)
        else:
            db.session.add(SystemSetting(key=key, value=str(value)))
    db.session.commit()
    log_operation("update_msgraph_config", "system", f"keys={sorted(data.keys())}")
    return jsonify(
        {"message": "Graph 設定を保存しました", "config": _get_safe_config()}
    )


# ---------------------------------------------------------------------------
# Status / connection test
# ---------------------------------------------------------------------------


@bp.route("/status", methods=["GET"])
@admin_required
def status():
    """Test Microsoft Graph connection with current config."""
    cfg = _get_config()
    if not cfg["msgraph_tenant_id"] or not cfg["msgraph_client_id"]:
        return jsonify({"connected": False, "error": "設定が不完全です"}), 200

    try:
        token = _acquire_token(cfg)
        _graph_get(
            token, "/organization", params={"$select": "id,displayName", "$top": "1"}
        )
        return jsonify({"connected": True})
    except Exception as exc:
        return jsonify({"connected": False, "error": str(exc)}), 200


# ---------------------------------------------------------------------------
# Sync endpoint
# ---------------------------------------------------------------------------


@bp.route("/sync", methods=["POST"])
@admin_required
def sync():
    """Sync Windows Update data from Microsoft Graph managed devices."""
    cfg = _get_config()
    if not cfg["msgraph_tenant_id"] or not cfg["msgraph_client_id"]:
        return jsonify({"error": "Graph 設定が不完全です"}), 400

    try:
        token = _acquire_token(cfg)
    except Exception as exc:
        return jsonify({"error": f"トークン取得失敗: {exc}"}), 502

    # Fetch managed devices with update-relevant fields
    select_fields = (
        "id,deviceName,osVersion,complianceState,lastSyncDateTime,"
        "windowsActiveMalwareCount"
    )
    try:
        payload = _graph_get(
            token,
            "/deviceManagement/managedDevices",
            params={"$select": select_fields, "$top": "999"},
        )
    except Exception as exc:
        return jsonify({"error": f"managedDevices 取得失敗: {exc}"}), 502

    devices = payload.get("value", [])
    pc_map = {pc.pc_name.lower(): pc for pc in PC.query.all()}

    synced = 0
    unmatched = []
    now = datetime.now(timezone.utc)

    for dev in devices:
        device_name = (dev.get("deviceName") or "").strip()
        pc = pc_map.get(device_name.lower())
        if pc is None:
            unmatched.append(device_name)
            continue

        # Upsert: one WindowsUpdate row per (pc_id, graph device sync)
        # Use the Graph device ID as kb_id placeholder to avoid duplicates
        graph_id = dev.get("id", "")[:32]
        existing = WindowsUpdate.query.filter_by(
            pc_id=pc.id, kb_id=f"GRAPH:{graph_id}"
        ).first()

        os_ver = dev.get("osVersion", "")
        compliance = dev.get("complianceState", "unknown")
        last_sync_str = dev.get("lastSyncDateTime")
        last_sync = None
        if last_sync_str:
            try:
                last_sync = datetime.fromisoformat(last_sync_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        if existing:
            existing.title = f"[Graph] {device_name} — {compliance} — OS {os_ver}"
            existing.installed = compliance == "compliant"
            existing.installed_at = last_sync
            existing.collected_at = now
        else:
            db.session.add(
                WindowsUpdate(
                    pc_id=pc.id,
                    kb_id=f"GRAPH:{graph_id}",
                    title=f"[Graph] {device_name} — {compliance} — OS {os_ver}",
                    severity="info",
                    installed=compliance == "compliant",
                    installed_at=last_sync,
                    collected_at=now,
                )
            )
        synced += 1

    db.session.commit()
    log_operation(
        "msgraph_sync", "system", f"synced={synced} unmatched={len(unmatched)}"
    )
    return jsonify(
        {
            "synced": synced,
            "total_devices": len(devices),
            "unmatched": unmatched,
        }
    )

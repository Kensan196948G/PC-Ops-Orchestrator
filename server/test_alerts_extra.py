"""Extra coverage tests for routes/alerts.py.

Targets uncovered lines:
- sync_alerts: new alert creation loop (178-184) — requires PC in alert-worthy state
- _build_candidates:
    - pc_offline (213): last_seen > 30 min ago
    - health_critical (225): health_score < 50
    - health_warning (235): 50 <= health_score < 80
    - disk_low (248): disk_free/disk_total < 10%
    - high_memory (267): (total-available)/total > 90%
"""

import json
import sys
import os
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, Alert, User

app = create_app("testing")
client = app.test_client()

_admin_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token
    with app.app_context():
        db.create_all()
        username = f"admin_al_{_unique}"
        if not User.query.filter_by(username=username).first():
            db.session.add(User(
                username=username,
                password_hash=hash_password("AdminAl1!"),
                role="admin",
            ))
        db.session.commit()
    _admin_token = _login(f"admin_al_{_unique}", "AdminAl1!")


def teardown_module():
    """Remove all Alert rows created by this module to avoid polluting other tests."""
    with app.app_context():
        Alert.query.delete()
        db.session.commit()


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def req(method, path, token=None, params=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{path}?{qs}"
    body = json.dumps(data) if data is not None else None
    return client.open(url, method=method, headers=headers, data=body)


def _create_pc(**kwargs):
    with app.app_context():
        pc = PC(pc_name=f"AlertPC-{uuid.uuid4().hex[:6]}-{_unique}", **kwargs)
        db.session.add(pc)
        db.session.commit()
        return pc.id


def _cleanup_alerts():
    """Delete all unresolved alerts between tests to avoid duplicate source_key conflicts."""
    with app.app_context():
        Alert.query.delete()
        db.session.commit()


# ── list_alerts: severity / pc_id / resolved filters ─────────────────


def test_list_alerts_severity_filter():
    """GET /api/alerts?severity=critical → only critical alerts (line 32)."""
    r = req("GET", "/api/alerts", token=_admin_token, params={"severity": "critical"})
    assert r.status_code == 200
    data = json.loads(r.data)
    for a in data["alerts"]:
        assert a["severity"] == "critical"


def test_list_alerts_pc_id_filter():
    """GET /api/alerts?pc_id=1 → filters by pc_id (line 34)."""
    r = req("GET", "/api/alerts", token=_admin_token, params={"pc_id": "1"})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "alerts" in data


def test_list_alerts_resolved_true():
    """GET /api/alerts?resolved=true → resolved=True filter (line 24)."""
    r = req("GET", "/api/alerts", token=_admin_token, params={"resolved": "true"})
    assert r.status_code == 200
    data = json.loads(r.data)
    for a in data["alerts"]:
        assert a["resolved"] is True


# ── export_alerts_csv ────────────────────────────────────────────────


def test_export_alerts_csv_basic():
    """GET /api/alerts/export.csv → 200 text/csv."""
    r = req("GET", "/api/alerts/export.csv", token=_admin_token)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_export_alerts_csv_severity_filter():
    """GET /api/alerts/export.csv?severity=high → covers severity filter (line 64)."""
    r = req("GET", "/api/alerts/export.csv", token=_admin_token, params={"severity": "high"})
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert "ID" in content


def test_export_alerts_csv_resolved_filter():
    """GET /api/alerts/export.csv?resolved=true → resolved filter (line 60)."""
    r = req("GET", "/api/alerts/export.csv", token=_admin_token, params={"resolved": "true"})
    assert r.status_code == 200


# ── get_alert / acknowledge / resolve ────────────────────────────────


def test_get_alert_not_found():
    """GET /api/alerts/9999999 → 404."""
    r = req("GET", "/api/alerts/9999999", token=_admin_token)
    assert r.status_code == 404


def test_acknowledge_alert_not_found():
    """POST /api/alerts/9999999/acknowledge → 404 (line 129)."""
    r = req("POST", "/api/alerts/9999999/acknowledge", token=_admin_token)
    assert r.status_code == 404


def test_resolve_alert_not_found():
    """POST /api/alerts/9999999/resolve → 404 (line 145)."""
    r = req("POST", "/api/alerts/9999999/resolve", token=_admin_token)
    assert r.status_code == 404


# ── sync_alerts: PC offline (lines 178-184, 213) ─────────────────────


def test_sync_alerts_creates_offline_alert():
    """PC with old last_seen → offline alert created (lines 178-184, 213)."""
    _cleanup_alerts()
    pc_id = _create_pc(
        last_seen=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    r = req("POST", "/api/alerts/sync", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["created"] >= 1
    with app.app_context():
        alert = Alert.query.filter_by(pc_id=pc_id, alert_type="pc_offline").first()
        assert alert is not None
    _cleanup_alerts()


# ── sync_alerts: health_critical (line 225) ─────────────────────────


def test_sync_alerts_health_critical():
    """PC with health_score < 50 → health_critical alert (line 225)."""
    _cleanup_alerts()
    pc_id = _create_pc(health_score=30.0)
    r = req("POST", "/api/alerts/sync", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["created"] >= 1
    with app.app_context():
        alert = Alert.query.filter_by(pc_id=pc_id, alert_type="health_critical").first()
        assert alert is not None
    _cleanup_alerts()


# ── sync_alerts: health_warning (line 235) ──────────────────────────


def test_sync_alerts_health_warning():
    """PC with health_score between 50–80 → health_warning alert (line 235)."""
    _cleanup_alerts()
    pc_id = _create_pc(health_score=65.0)
    r = req("POST", "/api/alerts/sync", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["created"] >= 1
    with app.app_context():
        alert = Alert.query.filter_by(pc_id=pc_id, alert_type="health_warning").first()
        assert alert is not None
    _cleanup_alerts()


# ── sync_alerts: disk_low (line 248) ────────────────────────────────


def test_sync_alerts_disk_low():
    """PC with disk_free/disk_total < 10% → disk_low alert (line 248)."""
    _cleanup_alerts()
    pc_id = _create_pc(disk_total_gb=100.0, disk_free_gb=5.0)  # 5% free
    r = req("POST", "/api/alerts/sync", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["created"] >= 1
    with app.app_context():
        alert = Alert.query.filter_by(pc_id=pc_id, alert_type="disk_low").first()
        assert alert is not None
    _cleanup_alerts()


# ── sync_alerts: high_memory (line 267) ─────────────────────────────


def test_sync_alerts_high_memory():
    """PC with memory_used > 90% → high_memory alert (line 267)."""
    _cleanup_alerts()
    pc_id = _create_pc(
        memory_total_gb=16.0,
        memory_available_gb=0.5,  # ~97% used
    )
    r = req("POST", "/api/alerts/sync", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["created"] >= 1
    with app.app_context():
        alert = Alert.query.filter_by(pc_id=pc_id, alert_type="high_memory").first()
        assert alert is not None
    _cleanup_alerts()


# ── sync_alerts: already resolved / dedup (active_keys logic) ────────


def test_sync_alerts_resolves_stale():
    """After fixing PC, stale alert is resolved on next sync."""
    _cleanup_alerts()
    # Create a PC with bad health
    pc_id = _create_pc(health_score=30.0)
    req("POST", "/api/alerts/sync", token=_admin_token)
    with app.app_context():
        assert Alert.query.filter_by(pc_id=pc_id, resolved=False).count() >= 1

    # Fix the PC
    with app.app_context():
        pc = db.session.get(PC, pc_id)
        pc.health_score = 95.0
        db.session.commit()

    req("POST", "/api/alerts/sync", token=_admin_token)
    with app.app_context():
        # Previous alert should now be resolved
        alert = Alert.query.filter_by(pc_id=pc_id, resolved=True).first()
        assert alert is not None
    _cleanup_alerts()


# ── sync_alerts: existing alert dedup (already in existing_keys) ─────


def test_sync_alerts_no_duplicate_on_repeat():
    """Calling sync twice with same bad PC should not create duplicate alerts."""
    _cleanup_alerts()
    pc_id = _create_pc(health_score=30.0)

    r1 = req("POST", "/api/alerts/sync", token=_admin_token)
    count_after_first = json.loads(r1.data)["created"]
    assert count_after_first >= 1

    r2 = req("POST", "/api/alerts/sync", token=_admin_token)
    count_after_second = json.loads(r2.data)["created"]
    assert count_after_second == 0  # no new alerts created
    _cleanup_alerts()


# ── acknowledge already-resolved alert (line 131) ────────────────────


def test_acknowledge_resolved_alert_fails():
    """POST /api/alerts/<id>/acknowledge on resolved alert → 400 (line 131)."""
    _cleanup_alerts()
    pc_id = _create_pc(health_score=30.0)
    req("POST", "/api/alerts/sync", token=_admin_token)
    with app.app_context():
        alert = Alert.query.filter_by(pc_id=pc_id).first()
        assert alert is not None
        alert_id = alert.id
        alert.resolved = True
        alert.resolved_at = datetime.now(timezone.utc)
        db.session.commit()

    r = req("POST", f"/api/alerts/{alert_id}/acknowledge", token=_admin_token)
    assert r.status_code == 400
    assert "解決済み" in json.loads(r.data)["error"]
    _cleanup_alerts()


# ── resolve already-resolved alert (line 147) ────────────────────────


def test_resolve_already_resolved_alert():
    """POST /api/alerts/<id>/resolve on already resolved alert → 400 (line 147)."""
    _cleanup_alerts()
    pc_id = _create_pc(health_score=30.0)
    req("POST", "/api/alerts/sync", token=_admin_token)
    with app.app_context():
        alert = Alert.query.filter_by(pc_id=pc_id).first()
        assert alert is not None
        alert_id = alert.id
        alert.resolved = True
        alert.resolved_at = datetime.now(timezone.utc)
        db.session.commit()

    r = req("POST", f"/api/alerts/{alert_id}/resolve", token=_admin_token)
    assert r.status_code == 400
    assert "解決済み" in json.loads(r.data)["error"]
    _cleanup_alerts()


# ── acknowledge + resolve full success path ──────────────────────────


def test_acknowledge_and_resolve_alert_success():
    """Full path: create alert via sync, acknowledge, then resolve."""
    _cleanup_alerts()
    pc_id = _create_pc(health_score=30.0)
    req("POST", "/api/alerts/sync", token=_admin_token)
    with app.app_context():
        alert = Alert.query.filter_by(pc_id=pc_id).first()
        assert alert is not None
        alert_id = alert.id

    r_ack = req("POST", f"/api/alerts/{alert_id}/acknowledge", token=_admin_token)
    assert r_ack.status_code == 200
    assert "acknowledge" in json.loads(r_ack.data)["message"]

    r_res = req("POST", f"/api/alerts/{alert_id}/resolve", token=_admin_token)
    assert r_res.status_code == 200
    assert "解決済み" in json.loads(r_res.data)["message"]
    _cleanup_alerts()


# ── export CSV with data rows ────────────────────────────────────────


def test_export_csv_with_data():
    """CSV export includes data rows when alerts exist (line 94-107)."""
    _cleanup_alerts()
    pc_id = _create_pc(health_score=30.0)
    req("POST", "/api/alerts/sync", token=_admin_token)
    r = req("GET", "/api/alerts/export.csv", token=_admin_token)
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert "health_critical" in content
    _cleanup_alerts()

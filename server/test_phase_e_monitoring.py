"""Tests for Phase E monitoring features — Issue #244, #245, #246.

Covers:
- GET /api/stability/boot-analysis           — list slow-boot PCs
- GET /api/stability/boot-analysis/<pc_id>   — per-PC history
- POST /api/stability/boot-analysis/<pc_id>  — record new boot entry
- GET /api/agents/<pc_id>/network-status     — latest connectivity checks
- POST /api/agents/<pc_id>/network-status    — submit check results (single + batch)
- GET /api/stability/similar-issues?group_by=os_version
- GET /api/stability/similar-issues?group_by=location
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from auth import hash_password
from extensions import db
from models import BootTimeLog, NetworkPingLog, PC, User

app = create_app("testing")
client = app.test_client()

_unique = uuid.uuid4().hex[:8]
_admin_token = None


def setup_module():
    global _admin_token
    with app.app_context():
        db.create_all()
        username = f"admin_pe_{_unique}"
        if not User.query.filter_by(username=username).first():
            db.session.add(
                User(
                    username=username,
                    password_hash=hash_password("AdminPe1!"),
                    role="admin",
                )
            )
            db.session.commit()
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": f"admin_pe_{_unique}", "password": "AdminPe1!"}),
    )
    _admin_token = json.loads(r.data)["token"]


def _auth():
    return {"Authorization": f"Bearer {_admin_token}", "Content-Type": "application/json"}


def _post(path, data):
    return client.open(path, method="POST", headers=_auth(), data=json.dumps(data))


def _get(path):
    return client.open(path, method="GET", headers=_auth())


def _make_pc(suffix, ip="10.0.1.1", os_version="Windows 11", stability_score=None):
    with app.app_context():
        pc = PC(
            pc_name=f"PE-PC-{suffix}-{_unique}",
            ip_address=ip,
            os_version=os_version,
        )
        if stability_score is not None:
            pc.stability_score = stability_score
        db.session.add(pc)
        db.session.commit()
        return pc.id


def _add_boot_log(pc_id, duration_secs, days_ago=0):
    with app.app_context():
        ts = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=1)
        log = BootTimeLog(
            pc_id=pc_id,
            boot_duration_seconds=duration_secs,
            boot_timestamp=ts,
            collected_at=ts,
        )
        db.session.add(log)
        db.session.commit()
        return log.id


def _add_ping_log(pc_id, check_type, status, latency_ms=None, hours_ago=1):
    with app.app_context():
        ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        log = NetworkPingLog(
            pc_id=pc_id,
            check_type=check_type,
            target="8.8.8.8",
            status=status,
            latency_ms=latency_ms,
            checked_at=ts,
        )
        db.session.add(log)
        db.session.commit()
        return log.id


# ─── Boot-analysis: unauthenticated ──────────────────────────────────────────

def test_boot_analysis_list_requires_auth():
    r = client.open("/api/stability/boot-analysis", method="GET")
    assert r.status_code == 401


def test_boot_analysis_detail_requires_auth():
    r = client.open("/api/stability/boot-analysis/1", method="GET")
    assert r.status_code == 401


def test_record_boot_time_requires_auth():
    r = client.open("/api/stability/boot-analysis/1", method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps({"boot_duration_seconds": 30}))
    assert r.status_code == 401


# ─── Boot-analysis: list ─────────────────────────────────────────────────────

def test_boot_analysis_list_empty():
    """No PCs with >=2 logs → empty list."""
    r = _get("/api/stability/boot-analysis")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert isinstance(data, list)


def test_boot_analysis_list_detects_slow_boot():
    """PC with baseline 30s and latest 60s (200%) triggers alert."""
    pc_id = _make_pc("boot-slow")
    # baseline logs (days_ago=10, 9) → avg 30s
    _add_boot_log(pc_id, 30, days_ago=10)
    _add_boot_log(pc_id, 30, days_ago=9)
    # latest log much slower
    _add_boot_log(pc_id, 60, days_ago=1)

    r = _get("/api/stability/boot-analysis")
    assert r.status_code == 200
    items = json.loads(r.data)
    found = [x for x in items if x["pc_id"] == pc_id]
    assert len(found) == 1
    item = found[0]
    assert item["alert"] is True
    assert item["latest_seconds"] == 60
    assert item["baseline_seconds"] == 30.0
    assert item["increase_pct"] == 100.0


def test_boot_analysis_list_no_alert_when_normal():
    """PC with stable boot time should NOT appear in list."""
    pc_id = _make_pc("boot-stable")
    _add_boot_log(pc_id, 30, days_ago=5)
    _add_boot_log(pc_id, 32, days_ago=3)
    _add_boot_log(pc_id, 31, days_ago=1)

    r = _get("/api/stability/boot-analysis")
    assert r.status_code == 200
    items = json.loads(r.data)
    found = [x for x in items if x["pc_id"] == pc_id]
    assert len(found) == 0


# ─── Boot-analysis: detail ────────────────────────────────────────────────────

def test_boot_analysis_detail_not_found():
    r = _get("/api/stability/boot-analysis/999999")
    assert r.status_code == 404


def test_boot_analysis_detail_empty_history():
    pc_id = _make_pc("boot-detail-empty")
    r = _get(f"/api/stability/boot-analysis/{pc_id}")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["pc_id"] == pc_id
    assert data["sample_count"] == 0
    assert data["avg_seconds"] is None
    assert data["records"] == []


def test_boot_analysis_detail_with_records():
    pc_id = _make_pc("boot-detail-recs")
    _add_boot_log(pc_id, 20, days_ago=5)
    _add_boot_log(pc_id, 40, days_ago=2)

    r = _get(f"/api/stability/boot-analysis/{pc_id}")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["sample_count"] == 2
    assert data["min_seconds"] == 20
    assert data["max_seconds"] == 40
    assert data["avg_seconds"] == 30.0
    assert len(data["records"]) == 2


# ─── Boot-analysis: POST record ───────────────────────────────────────────────

def test_record_boot_time_not_found():
    r = _post("/api/stability/boot-analysis/999999", {"boot_duration_seconds": 30})
    assert r.status_code == 404


def test_record_boot_time_missing_duration():
    pc_id = _make_pc("boot-post-missing")
    r = _post(f"/api/stability/boot-analysis/{pc_id}", {})
    assert r.status_code == 400
    data = json.loads(r.data)
    assert "boot_duration_seconds" in data["error"]


def test_record_boot_time_invalid_duration():
    pc_id = _make_pc("boot-post-invalid")
    r = _post(f"/api/stability/boot-analysis/{pc_id}", {"boot_duration_seconds": -5})
    assert r.status_code == 400


def test_record_boot_time_success():
    pc_id = _make_pc("boot-post-ok")
    r = _post(f"/api/stability/boot-analysis/{pc_id}", {"boot_duration_seconds": 45})
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["pc_id"] == pc_id
    assert data["boot_duration_seconds"] == 45
    assert data["id"] is not None


def test_record_boot_time_with_timestamp():
    pc_id = _make_pc("boot-post-ts")
    ts = "2026-05-01T09:00:00Z"
    r = _post(f"/api/stability/boot-analysis/{pc_id}", {
        "boot_duration_seconds": 55,
        "boot_timestamp": ts,
    })
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["boot_duration_seconds"] == 55
    assert "2026-05-01" in data["boot_timestamp"]


def test_record_boot_time_invalid_timestamp():
    pc_id = _make_pc("boot-post-bad-ts")
    r = _post(f"/api/stability/boot-analysis/{pc_id}", {
        "boot_duration_seconds": 30,
        "boot_timestamp": "not-a-date",
    })
    assert r.status_code == 400


# ─── Network-status: unauthenticated ─────────────────────────────────────────

def test_network_status_get_requires_auth():
    r = client.open("/api/agents/1/network-status", method="GET")
    assert r.status_code == 401


def test_network_status_post_requires_auth():
    r = client.open("/api/agents/1/network-status", method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps({"check_type": "ping", "status": "ok"}))
    assert r.status_code == 401


# ─── Network-status: GET ─────────────────────────────────────────────────────

def test_network_status_get_not_found():
    r = _get("/api/agents/999999/network-status")
    assert r.status_code == 404


def test_network_status_get_empty():
    pc_id = _make_pc("net-get-empty")
    r = _get(f"/api/agents/{pc_id}/network-status")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["pc_id"] == pc_id
    assert data["records"] == []
    assert data["latest"] == {}
    assert data["summary"] == {}


def test_network_status_get_with_records():
    pc_id = _make_pc("net-get-recs")
    _add_ping_log(pc_id, "ping", "ok", latency_ms=5, hours_ago=2)
    _add_ping_log(pc_id, "ping", "timeout", hours_ago=1)
    _add_ping_log(pc_id, "dns", "ok", latency_ms=12, hours_ago=1)

    r = _get(f"/api/agents/{pc_id}/network-status")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert len(data["records"]) == 3
    # latest per type
    assert "ping" in data["latest"]
    assert "dns" in data["latest"]
    # summary
    ping_summary = data["summary"]["ping"]
    assert ping_summary["total"] == 2
    assert ping_summary["ok"] == 1
    assert ping_summary["error"] == 1


def test_network_status_get_filter_by_type():
    pc_id = _make_pc("net-get-filter")
    _add_ping_log(pc_id, "ping", "ok", hours_ago=1)
    _add_ping_log(pc_id, "dns", "ok", hours_ago=1)

    r = _get(f"/api/agents/{pc_id}/network-status?check_type=ping")
    assert r.status_code == 200
    data = json.loads(r.data)
    for rec in data["records"]:
        assert rec["check_type"] == "ping"


def test_network_status_get_invalid_type_ignored():
    """Invalid check_type filter should be ignored (returns all)."""
    pc_id = _make_pc("net-get-bad-type")
    _add_ping_log(pc_id, "ping", "ok", hours_ago=1)

    r = _get(f"/api/agents/{pc_id}/network-status?check_type=invalid")
    assert r.status_code == 200
    data = json.loads(r.data)
    # filter ignored → returns all records
    assert len(data["records"]) >= 1


# ─── Network-status: POST ────────────────────────────────────────────────────

def test_network_status_post_not_found():
    r = _post("/api/agents/999999/network-status", {"check_type": "ping", "status": "ok"})
    assert r.status_code == 404


def test_network_status_post_invalid_check_type():
    pc_id = _make_pc("net-post-bad-type")
    r = _post(f"/api/agents/{pc_id}/network-status", {
        "check_type": "invalid",
        "status": "ok",
    })
    assert r.status_code == 400
    data = json.loads(r.data)
    assert data["errors"]


def test_network_status_post_invalid_status():
    pc_id = _make_pc("net-post-bad-status")
    r = _post(f"/api/agents/{pc_id}/network-status", {
        "check_type": "ping",
        "status": "unknown",
    })
    assert r.status_code == 400


def test_network_status_post_single_record():
    pc_id = _make_pc("net-post-single")
    r = _post(f"/api/agents/{pc_id}/network-status", {
        "check_type": "ping",
        "status": "ok",
        "target": "8.8.8.8",
        "latency_ms": 15,
    })
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["created"] == 1
    assert data["errors"] == []


def test_network_status_post_batch_records():
    pc_id = _make_pc("net-post-batch")
    batch = [
        {"check_type": "ping", "status": "ok", "latency_ms": 10},
        {"check_type": "dns", "status": "ok", "latency_ms": 8},
        {"check_type": "vpn", "status": "timeout"},
        {"check_type": "wifi", "status": "ok"},
    ]
    r = _post(f"/api/agents/{pc_id}/network-status", batch)
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["created"] == 4
    assert data["errors"] == []


def test_network_status_post_partial_errors():
    """Batch with some valid and some invalid records → partial success."""
    pc_id = _make_pc("net-post-partial")
    batch = [
        {"check_type": "ping", "status": "ok"},
        {"check_type": "bad_type", "status": "ok"},  # invalid
        {"check_type": "dns", "status": "ok"},
    ]
    r = _post(f"/api/agents/{pc_id}/network-status", batch)
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["created"] == 2
    assert len(data["errors"]) == 1
    assert data["errors"][0]["index"] == 1


def test_network_status_post_all_invalid():
    """All invalid → 400."""
    pc_id = _make_pc("net-post-all-invalid")
    batch = [
        {"check_type": "bad1", "status": "ok"},
        {"check_type": "bad2", "status": "ok"},
    ]
    r = _post(f"/api/agents/{pc_id}/network-status", batch)
    assert r.status_code == 400


def test_network_status_post_with_timestamp():
    pc_id = _make_pc("net-post-ts")
    r = _post(f"/api/agents/{pc_id}/network-status", {
        "check_type": "ping",
        "status": "ok",
        "checked_at": "2026-05-01T10:00:00Z",
    })
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["created"] == 1


def test_network_status_post_invalid_timestamp():
    pc_id = _make_pc("net-post-bad-ts")
    r = _post(f"/api/agents/{pc_id}/network-status", {
        "check_type": "ping",
        "status": "ok",
        "checked_at": "not-a-date",
    })
    assert r.status_code == 400


def test_network_status_post_latency_string_coerced():
    """latency_ms provided as string should be coerced to int."""
    pc_id = _make_pc("net-post-lat-str")
    r = _post(f"/api/agents/{pc_id}/network-status", {
        "check_type": "ping",
        "status": "ok",
        "latency_ms": "25",
    })
    assert r.status_code == 201


# ─── Similar issues: os_version ───────────────────────────────────────────────

def test_similar_issues_os_version_requires_auth():
    r = client.open("/api/stability/similar-issues?group_by=os_version", method="GET")
    assert r.status_code == 401


def test_similar_issues_os_version_empty():
    r = _get("/api/stability/similar-issues?group_by=os_version")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert isinstance(data, list)


def test_similar_issues_os_version_groups():
    """3 unstable PCs on same OS version should appear as a group."""
    os_ver = f"Windows 10 21H2 Build 19044_{_unique}"
    for i in range(3):
        with app.app_context():
            pc = PC(
                pc_name=f"PE-OsGroup-{i}-{_unique}",
                os_version=os_ver,
                stability_score=50,  # below THRESHOLD_UNSTABLE=60
            )
            db.session.add(pc)
            db.session.commit()

    r = _get("/api/stability/similar-issues?group_by=os_version&min_pcs=2")
    assert r.status_code == 200
    data = json.loads(r.data)
    found = [x for x in data if x.get("os_version") == os_ver]
    assert len(found) == 1
    assert found[0]["unstable_pc_count"] >= 3
    assert found[0]["group_by"] == "os_version"


# ─── Similar issues: location ────────────────────────────────────────────────

def test_similar_issues_location_requires_auth():
    r = client.open("/api/stability/similar-issues?group_by=location", method="GET")
    assert r.status_code == 401


def test_similar_issues_location_empty():
    r = _get("/api/stability/similar-issues?group_by=location")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert isinstance(data, list)


def test_similar_issues_location_groups():
    """3 unstable PCs on same /24 subnet should appear as one location group."""
    subnet_prefix = f"192.168.{abs(hash(_unique)) % 200 + 10}"
    for i in range(3):
        with app.app_context():
            pc = PC(
                pc_name=f"PE-LocGroup-{i}-{_unique}",
                ip_address=f"{subnet_prefix}.{i + 10}",
                stability_score=45,  # below THRESHOLD_UNSTABLE=60
            )
            db.session.add(pc)
            db.session.commit()

    r = _get("/api/stability/similar-issues?group_by=location&min_pcs=2")
    assert r.status_code == 200
    data = json.loads(r.data)
    expected_subnet = f"{subnet_prefix}.0/24"
    found = [x for x in data if x.get("subnet") == expected_subnet]
    assert len(found) == 1
    assert found[0]["unstable_pc_count"] >= 3
    assert found[0]["group_by"] == "location"


def test_similar_issues_invalid_group_by():
    r = _get("/api/stability/similar-issues?group_by=unknown")
    assert r.status_code == 400

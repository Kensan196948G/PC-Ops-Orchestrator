"""Tests for Issue #274 — PC uptime / availability tracking."""

import json
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, UptimeLog, User

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin_up").first():
            db.session.add(
                User(
                    username="admin_up",
                    password_hash=hash_password("admin"),
                    role="admin",
                )
            )
            db.session.commit()


def _login():
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "admin_up", "password": "admin"}),
    )
    assert r.status_code == 200, r.data
    return json.loads(r.data)["token"]


def _req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _make_pc(name="UP-PC-01"):
    with app.app_context():
        existing = PC.query.filter_by(pc_name=name).first()
        if existing:
            return existing.id
        pc = PC(pc_name=name, ip_address="10.4.0.1", os_version="Windows 11")
        db.session.add(pc)
        db.session.commit()
        return pc.id


def _insert_logs(pc_id, statuses: list[str], base_minutes_ago: int = 60):
    """Insert UptimeLog rows spaced 5 minutes apart."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        for i, status in enumerate(statuses):
            db.session.add(
                UptimeLog(
                    pc_id=pc_id,
                    status=status,
                    recorded_at=now - timedelta(minutes=base_minutes_ago - i * 5),
                )
            )
        db.session.commit()


# ---------------------------------------------------------------------------
# GET /api/pcs/<id>/uptime
# ---------------------------------------------------------------------------


class TestPcUptime:
    def test_requires_auth(self):
        pc_id = _make_pc("AUTH-PC-UP")
        r = _req("GET", f"/api/pcs/{pc_id}/uptime")
        assert r.status_code == 401

    def test_no_logs_returns_null(self):
        token = _login()
        with app.app_context():
            pc = PC(pc_name="NOLOG-PC", ip_address="10.4.0.2", os_version="Win11")
            db.session.add(pc)
            db.session.commit()
            pc_id = pc.id
        r = _req("GET", f"/api/pcs/{pc_id}/uptime", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["uptime_pct"] is None
        assert data["sample_count"] == 0

    def test_all_online_returns_100(self):
        token = _login()
        pc_id = _make_pc("ALL-ONLINE-PC")
        _insert_logs(pc_id, ["online", "online", "online"])
        r = _req("GET", f"/api/pcs/{pc_id}/uptime", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["uptime_pct"] == 100.0
        assert data["downtime_minutes"] == 0

    def test_mixed_logs(self):
        token = _login()
        pc_id = _make_pc("MIXED-PC")
        _insert_logs(pc_id, ["online", "offline", "offline", "online"])
        r = _req("GET", f"/api/pcs/{pc_id}/uptime", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        # 2 online out of 4 → 50%
        assert data["uptime_pct"] == 50.0
        assert data["downtime_minutes"] > 0

    def test_history_returned(self):
        token = _login()
        pc_id = _make_pc("HIST-PC")
        _insert_logs(pc_id, ["online", "online"])
        r = _req("GET", f"/api/pcs/{pc_id}/uptime", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert isinstance(data["history"], list)

    def test_not_found(self):
        token = _login()
        r = _req("GET", "/api/pcs/999999/uptime", token=token)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/uptime/summary
# ---------------------------------------------------------------------------


class TestUptimeSummary:
    def test_requires_auth(self):
        r = _req("GET", "/api/uptime/summary")
        assert r.status_code == 401

    def test_returns_list(self):
        token = _login()
        r = _req("GET", "/api/uptime/summary", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "pcs" in data
        assert isinstance(data["pcs"], list)

    def test_sorted_lowest_first(self):
        token = _login()
        pc_a = _make_pc("SORT-PC-A")
        pc_b = _make_pc("SORT-PC-B")
        _insert_logs(pc_a, ["online", "online", "online"])  # 100%
        _insert_logs(pc_b, ["offline", "offline", "offline"])  # 0%
        r = _req("GET", "/api/uptime/summary", token=token)
        data = json.loads(r.data)
        pcts = [p["uptime_pct"] for p in data["pcs"] if p["uptime_pct"] is not None]
        assert pcts == sorted(pcts)


# ---------------------------------------------------------------------------
# POST /api/uptime/mark-offline
# ---------------------------------------------------------------------------


class TestMarkOffline:
    def test_requires_admin(self):
        r = _req("POST", "/api/uptime/mark-offline")
        assert r.status_code == 401

    def test_marks_silent_pc_offline(self):
        token = _login()
        with app.app_context():
            pc = PC(pc_name="SILENT-PC", ip_address="10.4.0.99", os_version="Win11")
            db.session.add(pc)
            db.session.commit()
            pc_id = pc.id
            # Insert a very old log (2 hours ago) — will be beyond 30m threshold
            old_time = datetime.now(timezone.utc) - timedelta(hours=2)
            db.session.add(
                UptimeLog(pc_id=pc_id, status="online", recorded_at=old_time)
            )
            db.session.commit()

        r = _req(
            "POST",
            "/api/uptime/mark-offline",
            token=token,
            data={"threshold_minutes": 30},
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["marked_offline"] >= 1

    def test_fresh_pc_not_marked(self):
        token = _login()
        pc_id = _make_pc("FRESH-PC")
        _insert_logs(pc_id, ["online"], base_minutes_ago=5)  # recent log (< threshold)
        before_r = _req("GET", f"/api/pcs/{pc_id}/uptime", token=token)
        before_count = json.loads(before_r.data)["sample_count"]

        r = _req(
            "POST",
            "/api/uptime/mark-offline",
            token=token,
            data={"threshold_minutes": 30},
        )
        assert r.status_code == 200

        after_r = _req("GET", f"/api/pcs/{pc_id}/uptime", token=token)
        after_count = json.loads(after_r.data)["sample_count"]
        # Fresh PC should NOT have gained an offline log
        assert after_count == before_count

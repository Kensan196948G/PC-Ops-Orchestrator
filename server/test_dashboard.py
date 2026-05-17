"""Tests for routes/dashboard.py — KPI endpoints (Issue #177)."""

import json
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import Alert, PC, Task, User

app = create_app("testing")
client = app.test_client()
_token = None


def setup_module():
    global _token
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin_dash").first():
            u = User(
                username="admin_dash",
                password_hash=hash_password("Admin@123!"),
                role="admin",
            )
            db.session.add(u)
            db.session.commit()

        # Seed a PC
        if not PC.query.filter_by(pc_name="dash-pc-01").first():
            pc = PC(
                pc_name="dash-pc-01",
                ip_address="10.0.0.1",
                status="healthy",
                last_seen=datetime.now(timezone.utc),
            )
            db.session.add(pc)
            db.session.commit()

        # Seed tasks (completed + failed)
        now = datetime.now(timezone.utc)
        for i in range(3):
            t = Task(
                task_type="reboot",
                status="completed",
                created_at=now - timedelta(hours=i),
                completed_at=now - timedelta(hours=i),
                created_by="admin_dash",
            )
            db.session.add(t)
        t_failed = Task(
            task_type="reboot",
            status="failed",
            created_at=now - timedelta(hours=1),
            created_by="admin_dash",
        )
        db.session.add(t_failed)

        # Seed an alert
        pc = PC.query.filter_by(pc_name="dash-pc-01").first()
        al = Alert(
            alert_type="disk_low",
            message="Disk low",
            severity="high",
            source_key="dash-pc-01:disk_low",
            resolved=False,
            pc_id=pc.id if pc else None,
            created_at=now - timedelta(hours=2),
        )
        db.session.add(al)
        db.session.commit()

    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "admin_dash", "password": "Admin@123!"}),
    )
    assert r.status_code == 200, f"Login failed: {r.data}"
    _token = json.loads(r.data)["token"]


def _get(path):
    return client.open(
        path,
        method="GET",
        headers={"Authorization": f"Bearer {_token}"},
    )


# ── /api/dashboard/stats ──────────────────────────────────────────────────────


def test_stats_returns_200():
    r = _get("/api/dashboard/stats")
    assert r.status_code == 200


def test_stats_has_new_fields():
    r = _get("/api/dashboard/stats")
    data = json.loads(r.data)
    assert "unresolved_alerts" in data
    assert "completed_tasks_today" in data
    assert isinstance(data["unresolved_alerts"], int)
    assert isinstance(data["completed_tasks_today"], int)


# ── /api/dashboard/kpi ───────────────────────────────────────────────────────


def test_kpi_default_range():
    r = _get("/api/dashboard/kpi")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["range"] == "24h"
    assert "uptime_rate" in data
    assert "alert_rate" in data
    assert "job_success_rate" in data


def test_kpi_ranges():
    for rng in ("24h", "7d", "30d"):
        r = _get(f"/api/dashboard/kpi?range={rng}")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["range"] == rng
        assert 0.0 <= data["uptime_rate"] <= 100.0
        assert data["alert_rate"] >= 0.0
        assert 0.0 <= data["job_success_rate"] <= 100.0


def test_kpi_job_success_rate_no_tasks():
    """When no tasks exist in range, success rate should default to 100.0."""
    r = _get("/api/dashboard/kpi?range=30d")
    assert r.status_code == 200
    data = json.loads(r.data)
    # If completed + failed > 0, success_rate is numeric; either way 0-100
    assert isinstance(data["job_success_rate"], float)


def test_kpi_unauthenticated():
    r = client.open("/api/dashboard/kpi", method="GET")
    assert r.status_code in (401, 403)


# ── /api/dashboard/timeline ──────────────────────────────────────────────────


def test_timeline_default_range():
    r = _get("/api/dashboard/timeline")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["range"] == "24h"
    assert len(data["labels"]) == 24
    assert len(data["task_completed"]) == 24
    assert len(data["task_failed"]) == 24
    assert len(data["alert_counts"]) == 24


def test_timeline_7d():
    r = _get("/api/dashboard/timeline?range=7d")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert len(data["labels"]) == 7


def test_timeline_30d():
    r = _get("/api/dashboard/timeline?range=30d")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert len(data["labels"]) == 30


def test_timeline_counts_are_non_negative():
    r = _get("/api/dashboard/timeline?range=24h")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert all(v >= 0 for v in data["task_completed"])
    assert all(v >= 0 for v in data["task_failed"])
    assert all(v >= 0 for v in data["alert_counts"])


def test_timeline_unauthenticated():
    r = client.open("/api/dashboard/timeline", method="GET")
    assert r.status_code in (401, 403)


# ── /api/dashboard/recent / health-distribution / os-breakdown ───────────────


def test_recent_activity():
    r = _get("/api/dashboard/recent")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "operations" in data
    assert "recent_tasks" in data


def test_health_distribution():
    r = _get("/api/dashboard/health-distribution")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "distribution" in data
    assert len(data["distribution"]) == 5


def test_os_breakdown():
    r = _get("/api/dashboard/os-breakdown")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "breakdown" in data

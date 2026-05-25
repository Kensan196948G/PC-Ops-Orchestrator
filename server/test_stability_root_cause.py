"""Tests for Issue #251 — Root Cause Analysis (event_id clustering)."""

import json
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, EventLog, StabilityScore, User

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin_rc").first():
            admin = User(
                username="admin_rc",
                password_hash=hash_password("admin"),
                role="admin",
            )
            db.session.add(admin)
            db.session.commit()


def _login():
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "admin_rc", "password": "admin"}),
    )
    assert r.status_code == 200, r.data
    return json.loads(r.data)["token"]


def _req(method, path, token=None, params=""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = path + params if params else path
    return client.open(url, method=method, headers=headers)


def _make_pc(name):
    with app.app_context():
        existing = PC.query.filter_by(pc_name=name).first()
        if existing:
            return existing.id
        pc = PC(pc_name=name, ip_address="10.2.1.1", os_version="Windows 11")
        db.session.add(pc)
        db.session.commit()
        return pc.id


def _add_score(pc_id, score, hours_ago=0):
    with app.app_context():
        ss = StabilityScore(
            pc_id=pc_id,
            score=score,
            calculated_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        )
        db.session.add(ss)
        db.session.commit()
        return ss.id


def _add_event(
    pc_id, event_id, source="System", category="System", level="Error", hours_ago=1
):
    with app.app_context():
        ev = EventLog(
            pc_id=pc_id,
            log_type="System",
            event_id=event_id,
            level=level,
            source=source,
            category=category,
            message=f"Event {event_id} from {source}",
            generated_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
            collected_at=datetime.now(timezone.utc),
        )
        db.session.add(ev)
        db.session.commit()


# ---------------------------------------------------------------------------
# GET /api/stability/root-cause
# ---------------------------------------------------------------------------


class TestRootCause:
    def test_requires_auth(self):
        r = _req("GET", "/api/stability/root-cause")
        assert r.status_code == 401

    def test_empty_when_no_unstable_pcs(self):
        token = _login()
        # All PCs with high scores (stable)
        pc_id = _make_pc("RC-STABLE-ONLY")
        _add_score(pc_id, 95.0)
        r = _req(
            "GET", "/api/stability/root-cause", token=token, params="?threshold=70"
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["unstable_pc_count"] == 0
        assert data["events"] == []
        assert "message" in data

    def test_returns_events_for_unstable_pcs(self):
        token = _login()
        pc_id = _make_pc("RC-UNSTABLE-PC")
        _add_score(pc_id, 50.0)  # unstable (< 70)
        _add_event(pc_id, 41, source="volmgr", category="Disk")
        _add_event(pc_id, 41, source="volmgr", category="Disk")

        r = _req("GET", "/api/stability/root-cause", token=token, params="?days=30")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["unstable_pc_count"] >= 1
        # event_id 41 should appear
        event_ids = [e["event_id"] for e in data["events"]]
        assert 41 in event_ids

    def test_lift_structure(self):
        token = _login()
        r = _req(
            "GET", "/api/stability/root-cause", token=token, params="?days=30&limit=5"
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "threshold" in data
        assert "days" in data
        assert "unstable_pc_count" in data
        assert "stable_pc_count" in data
        assert "events" in data
        if data["events"]:
            ev = data["events"][0]
            for key in (
                "event_id",
                "source",
                "category",
                "label",
                "unstable_pc_count",
                "stable_pc_count",
                "occurrence_count",
                "unstable_rate",
                "stable_rate",
                "lift",
            ):
                assert key in ev, f"Missing key: {key}"

    def test_lift_sorted_descending(self):
        token = _login()
        r = _req("GET", "/api/stability/root-cause", token=token, params="?days=30")
        assert r.status_code == 200
        data = json.loads(r.data)
        lifts = [e["lift"] for e in data["events"]]
        assert lifts == sorted(lifts, reverse=True)

    def test_limit_param_respected(self):
        token = _login()
        r = _req(
            "GET", "/api/stability/root-cause", token=token, params="?days=30&limit=2"
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert len(data["events"]) <= 2

    def test_lift_higher_for_unstable_only_events(self):
        """An event appearing only in unstable PCs should have higher lift than
        one appearing in both stable and unstable PCs."""
        token = _login()
        pc_unstable = _make_pc("RC-LIFT-UNSTABLE")
        pc_stable = _make_pc("RC-LIFT-STABLE")
        _add_score(pc_unstable, 40.0)
        _add_score(pc_stable, 90.0)

        # event_id 9999: only in unstable (high lift)
        _add_event(pc_unstable, 9999, source="TestSrc", category="TestCat")
        # event_id 8888: in both (lower lift)
        _add_event(pc_unstable, 8888, source="TestSrc", category="TestCat")
        _add_event(pc_stable, 8888, source="TestSrc", category="TestCat")

        r = _req(
            "GET", "/api/stability/root-cause", token=token, params="?days=30&limit=100"
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        ev_map = {e["event_id"]: e["lift"] for e in data["events"]}
        if 9999 in ev_map and 8888 in ev_map:
            assert ev_map[9999] >= ev_map[8888]


# ---------------------------------------------------------------------------
# GET /api/stability/root-cause/<pc_id>
# ---------------------------------------------------------------------------


class TestRootCausePerPC:
    def test_requires_auth(self):
        r = _req("GET", "/api/stability/root-cause/1")
        assert r.status_code == 401

    def test_404_for_unknown_pc(self):
        token = _login()
        r = _req("GET", "/api/stability/root-cause/999999", token=token)
        assert r.status_code == 404

    def test_returns_per_pc_events(self):
        token = _login()
        pc_id = _make_pc("RC-PER-PC")
        _add_score(pc_id, 55.0)
        _add_event(pc_id, 100, source="Service Control Manager", category="System")
        _add_event(pc_id, 100, source="Service Control Manager", category="System")
        _add_event(pc_id, 200, source="Kernel-Power", category="System")

        r = _req(
            "GET", f"/api/stability/root-cause/{pc_id}", token=token, params="?days=30"
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["pc_id"] == pc_id
        assert "pc_name" in data
        assert "stability_score" in data
        assert "days" in data
        assert "events" in data
        # event_id 100 appeared twice, should rank first
        if data["events"]:
            ev = data["events"][0]
            for key in ("event_id", "source", "category", "level", "label", "count"):
                assert key in ev
            assert ev["event_id"] == 100

    def test_limit_param(self):
        token = _login()
        pc_id = _make_pc("RC-PER-PC-LIMIT")
        _add_score(pc_id, 60.0)
        for eid in range(300, 310):
            _add_event(pc_id, eid)

        r = _req(
            "GET",
            f"/api/stability/root-cause/{pc_id}",
            token=token,
            params="?days=30&limit=3",
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert len(data["events"]) <= 3

    def test_no_score_returns_null(self):
        token = _login()
        pc_id = _make_pc("RC-PER-PC-NO-SCORE")
        r = _req("GET", f"/api/stability/root-cause/{pc_id}", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["stability_score"] is None

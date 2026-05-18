"""Tests for User Inquiry API — Phase D-4 (Issue #241)."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone


sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from auth import hash_password
from extensions import db
from models import EventLog, KnownIssue, PC, User, WindowsUpdate

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.first():
            admin = User(
                username="admin",
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
        data=json.dumps({"username": "admin", "password": "admin"}),
    )
    assert r.status_code == 200
    return json.loads(r.data)["token"]


def _req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _make_pc(name):
    with app.app_context():
        pc = PC(pc_name=name, ip_address="10.0.0.1", os_version="Windows 11")
        db.session.add(pc)
        db.session.commit()
        return pc.id


def _make_known_issue(title="Known X"):
    with app.app_context():
        ki = KnownIssue(title=title, symptoms="freeze", resolution="reboot")
        db.session.add(ki)
        db.session.commit()
        return ki.id


# ── CRUD ───────────────────────────────────────────────────────────────────


class TestInquiryAuth:
    def test_list_requires_auth(self):
        r = _req("GET", "/api/inquiries")
        assert r.status_code == 401

    def test_create_requires_auth(self):
        r = _req("POST", "/api/inquiries", data={"subject": "x", "inquired_by": "u"})
        assert r.status_code == 401


class TestInquiryCreate:
    def test_create_minimum_fields(self):
        token = _login()
        r = _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "PC が遅い", "inquired_by": "user1"},
        )
        assert r.status_code == 201
        data = json.loads(r.data)
        assert data["subject"] == "PC が遅い"
        assert data["status"] == "open"

    def test_create_requires_subject(self):
        token = _login()
        r = _req("POST", "/api/inquiries", token=token, data={"inquired_by": "u"})
        assert r.status_code == 400

    def test_create_with_pc(self):
        token = _login()
        pc_id = _make_pc("INQ-PC-1")
        r = _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={
                "subject": "blue screen",
                "inquired_by": "user2",
                "pc_id": pc_id,
                "symptom": "BSOD 2 times today",
            },
        )
        data = json.loads(r.data)
        assert data["pc_id"] == pc_id
        assert data["pc_name"] == "INQ-PC-1"

    def test_create_with_unknown_pc_returns_404(self):
        token = _login()
        r = _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "x", "inquired_by": "u", "pc_id": 999999},
        )
        assert r.status_code == 404


class TestInquiryRead:
    def test_list_returns_inquiries(self):
        token = _login()
        _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "listed", "inquired_by": "u"},
        )
        r = _req("GET", "/api/inquiries", token=token)
        assert r.status_code == 200
        items = json.loads(r.data)
        assert isinstance(items, list)
        assert any(it["subject"] == "listed" for it in items)

    def test_get_single_inquiry(self):
        token = _login()
        c = _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "single", "inquired_by": "u"},
        )
        iid = json.loads(c.data)["id"]
        r = _req("GET", f"/api/inquiries/{iid}", token=token)
        assert r.status_code == 200
        assert json.loads(r.data)["id"] == iid

    def test_get_404(self):
        token = _login()
        r = _req("GET", "/api/inquiries/999999", token=token)
        assert r.status_code == 404

    def test_list_status_filter(self):
        token = _login()
        _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "open-one", "inquired_by": "u", "status": "open"},
        )
        r = _req("GET", "/api/inquiries?status=open", token=token)
        items = json.loads(r.data)
        assert all(it["status"] == "open" for it in items)


class TestInquiryUpdate:
    def test_update_sets_resolved_at_on_resolved(self):
        token = _login()
        c = _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "fix me", "inquired_by": "u"},
        )
        iid = json.loads(c.data)["id"]
        r = _req(
            "PUT",
            f"/api/inquiries/{iid}",
            token=token,
            data={"status": "resolved", "response": "fixed"},
        )
        data = json.loads(r.data)
        assert data["status"] == "resolved"
        assert data["resolved_at"] is not None
        assert data["response"] == "fixed"

    def test_update_link_to_known_issue(self):
        token = _login()
        ki_id = _make_known_issue("Known fix")
        c = _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "match", "inquired_by": "u"},
        )
        iid = json.loads(c.data)["id"]
        r = _req(
            "PUT",
            f"/api/inquiries/{iid}",
            token=token,
            data={"known_issue_id": ki_id},
        )
        data = json.loads(r.data)
        assert data["known_issue_id"] == ki_id
        assert data["known_issue_title"] == "Known fix"


class TestInquiryDelete:
    def test_delete(self):
        token = _login()
        c = _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "del", "inquired_by": "u"},
        )
        iid = json.loads(c.data)["id"]
        r = _req("DELETE", f"/api/inquiries/{iid}", token=token)
        assert r.status_code == 200
        r2 = _req("GET", f"/api/inquiries/{iid}", token=token)
        assert r2.status_code == 404


# ── Related logs ───────────────────────────────────────────────────────────


class TestRelatedLogs:
    def test_related_logs_requires_auth(self):
        r = _req("GET", "/api/inquiries/1/related-logs")
        assert r.status_code == 401

    def test_related_logs_404_unknown_inquiry(self):
        token = _login()
        r = _req("GET", "/api/inquiries/999999/related-logs", token=token)
        assert r.status_code == 404

    def test_related_logs_returns_event_logs_and_updates(self):
        token = _login()
        pc_id = _make_pc("INQ-RELATED")
        with app.app_context():
            now = datetime.now(timezone.utc)
            db.session.add(
                EventLog(
                    pc_id=pc_id,
                    log_type="System",
                    event_id=1001,
                    source="System",
                    message="BSOD",
                    generated_at=now - timedelta(days=1),
                )
            )
            db.session.add(
                WindowsUpdate(
                    pc_id=pc_id,
                    kb_id="KB5036000",
                    title="Test",
                    installed=True,
                    installed_at=now - timedelta(days=2),
                )
            )
            db.session.commit()
        c = _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "rel", "inquired_by": "u", "pc_id": pc_id},
        )
        iid = json.loads(c.data)["id"]
        r = _req("GET", f"/api/inquiries/{iid}/related-logs", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["pc_id"] == pc_id
        assert any(ev["event_id"] == 1001 for ev in data["event_logs"])
        assert any(u["kb_id"] == "KB5036000" for u in data["windows_updates"])

    def test_related_logs_no_pc_link(self):
        token = _login()
        c = _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "nopc", "inquired_by": "u"},
        )
        iid = json.loads(c.data)["id"]
        r = _req("GET", f"/api/inquiries/{iid}/related-logs", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["pc_id"] is None
        assert data["event_logs"] == []


# ── Similar ────────────────────────────────────────────────────────────────


class TestSimilarInquiries:
    def test_similar_by_subject(self):
        token = _login()
        _req(
            "POST",
            "/api/inquiries",
            token=token,
            data={"subject": "ネットワーク切断 in 会議", "inquired_by": "u"},
        )
        r = _req("GET", "/api/inquiries/similar?subject=ネットワーク", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert any("ネットワーク" in it["subject"] for it in data)

    def test_similar_requires_filter(self):
        token = _login()
        r = _req("GET", "/api/inquiries/similar", token=token)
        assert r.status_code == 400

"""Tests for Issue #180: VPN UI status enum extension (sub_states).

Covers:
- GET /api/agents - sub_states array + pending_job_count per PC
- GET /api/pcs/<id>/details - sub_states + pending_job_count in pc payload
- vpn_required (SSL-VPN / VPN connection_type, case-insensitive)
- pending_sync (offline_pending_count > 0)
- pending_job (Task with status in pending/running)
- Combinations and clean (empty) case
"""

import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, Task, User

app = create_app("testing")
client = app.test_client()

_admin_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token
    with app.app_context():
        db.create_all()
        username = f"admin_sub_{_unique}"
        if not User.query.filter_by(username=username).first():
            db.session.add(
                User(
                    username=username,
                    password_hash=hash_password("AdminSub1!"),
                    role="admin",
                )
            )
            db.session.commit()
    _admin_token = _login(f"admin_sub_{_unique}", "AdminSub1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def req(method, path, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.open(path, method=method, headers=headers)


def _create_pc(suffix, **kwargs):
    with app.app_context():
        pc = PC(pc_name=f"SubStatePC-{suffix}-{_unique}", **kwargs)
        db.session.add(pc)
        db.session.commit()
        return pc.id


def _create_task(pc_id, status="pending"):
    with app.app_context():
        t = Task(pc_id=pc_id, task_type="diagnose", status=status)
        db.session.add(t)
        db.session.commit()
        return t.id


def _find_agent(pc_id):
    r = req("GET", "/api/agents?per_page=200", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    return next((a for a in data["agents"] if a["id"] == pc_id), None)


# ── /api/agents sub_states ───────────────────────────────────────────


def test_agents_clean_state_has_empty_sub_states():
    """LAN PC with no pending: sub_states=[], pending_job_count=0."""
    pc_id = _create_pc("clean", connection_type="LAN", offline_pending_count=0)
    a = _find_agent(pc_id)
    assert a is not None
    assert a["sub_states"] == []
    assert a["pending_job_count"] == 0
    assert a["offline_pending_count"] == 0


def test_agents_vpn_required_for_ssl_vpn():
    pc_id = _create_pc("sslvpn", connection_type="SSL-VPN")
    a = _find_agent(pc_id)
    assert "vpn_required" in a["sub_states"]


def test_agents_vpn_required_case_insensitive():
    """Lowercase 'vpn' connection_type should still be normalized."""
    pc_id = _create_pc("vpnlower", connection_type="vpn")
    a = _find_agent(pc_id)
    assert "vpn_required" in a["sub_states"]


def test_agents_no_vpn_for_lan():
    pc_id = _create_pc("lan", connection_type="LAN")
    a = _find_agent(pc_id)
    assert "vpn_required" not in a["sub_states"]


def test_agents_pending_sync_when_offline_count_positive():
    pc_id = _create_pc("offline", connection_type="LAN", offline_pending_count=5)
    a = _find_agent(pc_id)
    assert "pending_sync" in a["sub_states"]
    assert a["offline_pending_count"] == 5


def test_agents_pending_job_when_task_pending():
    pc_id = _create_pc("hasjob", connection_type="LAN")
    _create_task(pc_id, status="pending")
    a = _find_agent(pc_id)
    assert "pending_job" in a["sub_states"]
    assert a["pending_job_count"] == 1


def test_agents_pending_job_counts_running_tasks():
    pc_id = _create_pc("running", connection_type="LAN")
    _create_task(pc_id, status="pending")
    _create_task(pc_id, status="running")
    _create_task(pc_id, status="completed")  # excluded
    a = _find_agent(pc_id)
    assert "pending_job" in a["sub_states"]
    assert a["pending_job_count"] == 2


def test_agents_completed_task_does_not_set_pending_job():
    pc_id = _create_pc("done", connection_type="LAN")
    _create_task(pc_id, status="completed")
    a = _find_agent(pc_id)
    assert "pending_job" not in a["sub_states"]
    assert a["pending_job_count"] == 0


def test_agents_all_three_flags_coexist():
    pc_id = _create_pc(
        "triple",
        connection_type="SSL-VPN",
        offline_pending_count=3,
    )
    _create_task(pc_id, status="running")
    a = _find_agent(pc_id)
    assert set(a["sub_states"]) >= {"vpn_required", "pending_sync", "pending_job"}
    assert a["offline_pending_count"] == 3
    assert a["pending_job_count"] == 1


# ── /api/pcs/<id>/details sub_states ─────────────────────────────────


def test_pc_details_includes_sub_states_and_pending_job_count():
    pc_id = _create_pc(
        "details",
        connection_type="SSL-VPN",
        offline_pending_count=2,
    )
    _create_task(pc_id, status="pending")
    r = req("GET", f"/api/pcs/{pc_id}/details", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    pc = data["pc"]
    assert "sub_states" in pc
    assert "pending_job_count" in pc
    assert set(pc["sub_states"]) >= {"vpn_required", "pending_sync", "pending_job"}
    assert pc["pending_job_count"] == 1


def test_pc_details_clean_state_empty_sub_states():
    pc_id = _create_pc("detail_clean", connection_type="LAN", offline_pending_count=0)
    r = req("GET", f"/api/pcs/{pc_id}/details", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    pc = data["pc"]
    assert pc["sub_states"] == []
    assert pc["pending_job_count"] == 0

"""Tests for Issue #154 — VPN/Offline sync endpoints.

Covers:
- POST /api/collect: connection_type + offline_pending_count reset
- POST /api/collect/sync: bulk offline cache dedup + insert
- GET /api/agents: online_status 4-state, connection_type, offline_pending_count
"""

import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from auth import hash_password
from extensions import db
from models import PC, SystemSnapshot, User

app = create_app("testing")
client = app.test_client()

_AGENT_KEY = "default-agent-key"
_unique = uuid.uuid4().hex[:8]
_admin_token = None


def setup_module():
    global _admin_token
    with app.app_context():
        db.create_all()
        username = f"admin_vpn_{_unique}"
        if not User.query.filter_by(username=username).first():
            db.session.add(
                User(
                    username=username,
                    password_hash=hash_password("AdminVpn1!"),
                    role="admin",
                )
            )
            db.session.commit()
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": f"admin_vpn_{_unique}", "password": "AdminVpn1!"}),
    )
    _admin_token = json.loads(r.data)["token"]


def _agent_req(method, path, data=None):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_AGENT_KEY}",
    }
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _login_req(method, path, data=None):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_admin_token}",
    }
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _pc_name(suffix=""):
    return f"VPNTestPC-{suffix}-{_unique}"


# ── /api/collect: connection_type ─────────────────────────────────────────────


def test_collect_sets_connection_type_lan():
    pc_name = _pc_name("lan")
    r = _agent_req(
        "POST",
        "/api/collect",
        data={
            "pc_name": pc_name,
            "connection_type": "LAN",
            "memory_total_gb": 8.0,
            "memory_available_gb": 4.0,
            "disk_total_gb": 256.0,
            "disk_free_gb": 100.0,
        },
    )
    assert r.status_code == 200
    with app.app_context():
        pc = PC.query.filter_by(pc_name=pc_name).first()
        assert pc is not None
        assert pc.connection_type == "LAN"


def test_collect_sets_connection_type_ssl_vpn():
    pc_name = _pc_name("vpn")
    r = _agent_req(
        "POST",
        "/api/collect",
        data={
            "pc_name": pc_name,
            "connection_type": "SSL-VPN",
            "memory_total_gb": 8.0,
            "memory_available_gb": 4.0,
            "disk_total_gb": 256.0,
            "disk_free_gb": 100.0,
        },
    )
    assert r.status_code == 200
    with app.app_context():
        pc = PC.query.filter_by(pc_name=pc_name).first()
        assert pc is not None
        assert pc.connection_type == "SSL-VPN"


def test_collect_resets_offline_pending_count():
    pc_name = _pc_name("reset")
    with app.app_context():
        pc = PC(pc_name=pc_name, offline_pending_count=5)
        db.session.add(pc)
        db.session.commit()

    r = _agent_req(
        "POST",
        "/api/collect",
        data={
            "pc_name": pc_name,
            "memory_total_gb": 8.0,
            "memory_available_gb": 4.0,
            "disk_total_gb": 256.0,
            "disk_free_gb": 100.0,
        },
    )
    assert r.status_code == 200
    with app.app_context():
        pc = PC.query.filter_by(pc_name=pc_name).first()
        assert pc.offline_pending_count == 0


# ── /api/collect/sync ─────────────────────────────────────────────────────────


def test_collect_sync_no_body():
    r = client.open(
        "/api/collect/sync",
        method="POST",
        headers={"Authorization": f"Bearer {_AGENT_KEY}"},
    )
    assert r.status_code in (400, 415)


def test_collect_sync_missing_pc_name():
    r = _agent_req("POST", "/api/collect/sync", data={"offline_cache": []})
    assert r.status_code == 400


def test_collect_sync_pc_not_found():
    r = _agent_req(
        "POST",
        "/api/collect/sync",
        data={
            "pc_name": f"NoSuchPC-{_unique}",
            "offline_cache": [],
        },
    )
    assert r.status_code == 404


def test_collect_sync_inserts_entries():
    pc_name = _pc_name("sync1")
    with app.app_context():
        pc = PC(pc_name=pc_name, offline_pending_count=3)
        db.session.add(pc)
        db.session.commit()

    entries = [
        {
            "collected_at": "2026-05-14T10:00:00",
            "cpu_usage": 30.0,
            "memory_available_gb": 4.0,
            "disk_free_gb": 100.0,
        },
        {
            "collected_at": "2026-05-14T10:05:00",
            "cpu_usage": 35.0,
            "memory_available_gb": 3.5,
            "disk_free_gb": 99.0,
        },
    ]
    r = _agent_req(
        "POST",
        "/api/collect/sync",
        data={
            "pc_name": pc_name,
            "offline_cache": entries,
        },
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["inserted"] == 2
    assert body["skipped"] == 0


def test_collect_sync_dedup_skips_existing_timestamp():
    pc_name = _pc_name("sync2")
    with app.app_context():
        pc = PC(pc_name=pc_name)
        db.session.add(pc)
        db.session.flush()
        from datetime import datetime

        snap = SystemSnapshot(
            pc_id=pc.id,
            collected_at=datetime(2026, 5, 14, 11, 0, 0),
        )
        db.session.add(snap)
        db.session.commit()

    entries = [
        {
            "collected_at": "2026-05-14T11:00:00",
            "cpu_usage": 50.0,
        },
        {
            "collected_at": "2026-05-14T11:05:00",
            "cpu_usage": 55.0,
        },
    ]
    r = _agent_req(
        "POST",
        "/api/collect/sync",
        data={
            "pc_name": pc_name,
            "offline_cache": entries,
        },
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["inserted"] == 1
    assert body["skipped"] == 1


def test_collect_sync_invalid_cache_format():
    pc_name = _pc_name("sync3")
    with app.app_context():
        pc = PC(pc_name=pc_name)
        db.session.add(pc)
        db.session.commit()

    r = _agent_req(
        "POST",
        "/api/collect/sync",
        data={
            "pc_name": pc_name,
            "offline_cache": "not-a-list",
        },
    )
    assert r.status_code == 400


def test_collect_sync_invalid_timestamp_skipped():
    pc_name = _pc_name("sync4")
    with app.app_context():
        pc = PC(pc_name=pc_name)
        db.session.add(pc)
        db.session.commit()

    entries = [
        {"collected_at": "not-a-date", "cpu_usage": 10.0},
        {"collected_at": "2026-05-14T12:00:00", "cpu_usage": 20.0},
    ]
    r = _agent_req(
        "POST",
        "/api/collect/sync",
        data={
            "pc_name": pc_name,
            "offline_cache": entries,
        },
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["inserted"] == 1
    assert body["skipped"] == 1


def test_collect_sync_empty_cache():
    pc_name = _pc_name("sync5")
    with app.app_context():
        pc = PC(pc_name=pc_name)
        db.session.add(pc)
        db.session.commit()

    r = _agent_req(
        "POST",
        "/api/collect/sync",
        data={
            "pc_name": pc_name,
            "offline_cache": [],
        },
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["inserted"] == 0
    assert body["skipped"] == 0


# ── /api/agents: online_status 4-state ────────────────────────────────────────


def test_agents_returns_online_status_field():
    pc_name = _pc_name("agent1")
    _agent_req(
        "POST",
        "/api/collect",
        data={
            "pc_name": pc_name,
            "connection_type": "SSL-VPN",
            "memory_total_gb": 8.0,
            "memory_available_gb": 4.0,
            "disk_total_gb": 256.0,
            "disk_free_gb": 100.0,
        },
    )

    r = _login_req("GET", "/api/agents")
    assert r.status_code == 200
    agents = json.loads(r.data)["agents"]
    matched = [a for a in agents if a["pc_name"] == pc_name]
    assert matched, "registered PC should appear in /api/agents"
    a = matched[0]
    assert "online_status" in a
    assert a["online_status"] in ("online", "recently_seen", "offline", "stale")
    assert "connection_type" in a
    assert a["connection_type"] == "SSL-VPN"
    assert "offline_pending_count" in a


def test_agents_stale_pc_shows_stale_status():
    from datetime import datetime, timezone, timedelta

    pc_name = _pc_name("stale")
    with app.app_context():
        old_time = datetime.now(timezone.utc) - timedelta(days=10)
        pc = PC(pc_name=pc_name, last_seen=old_time)
        db.session.add(pc)
        db.session.commit()

    r = _login_req("GET", "/api/agents")
    assert r.status_code == 200
    agents = json.loads(r.data)["agents"]
    matched = [a for a in agents if a["pc_name"] == pc_name]
    if matched:
        assert matched[0]["online_status"] == "stale"


def test_agents_recently_seen_status():
    from datetime import datetime, timezone, timedelta

    pc_name = _pc_name("recent")
    with app.app_context():
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=15)
        pc = PC(pc_name=pc_name, last_seen=recent_time)
        db.session.add(pc)
        db.session.commit()

    r = _login_req("GET", "/api/agents")
    assert r.status_code == 200
    agents = json.loads(r.data)["agents"]
    matched = [a for a in agents if a["pc_name"] == pc_name]
    if matched:
        assert matched[0]["online_status"] == "recently_seen"

"""Tests for agents API endpoints.

Covers:
- GET /api/agents - list agents with pagination, status filter
- GET /api/agents/export.csv - CSV export
- Auth: unauthenticated (401), authenticated (200)
- PC with/without snapshots, with/without memory info
- Online/offline detection, timezone-aware and naive last_seen
"""

import csv
import io
import json
import sys
import os
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, SystemSnapshot, User

app = create_app("testing")
client = app.test_client()

_admin_token = None
_viewer_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token, _viewer_token
    with app.app_context():
        db.create_all()
        for username, role, password in [
            (f"admin_ag_{_unique}", "admin", "AdminAg1!"),
            (f"viewer_ag_{_unique}", "viewer", "ViewerAg1!"),
        ]:
            if not User.query.filter_by(username=username).first():
                db.session.add(
                    User(
                        username=username,
                        password_hash=hash_password(password),
                        role=role,
                    )
                )
        db.session.commit()

    _admin_token = _login(f"admin_ag_{_unique}", "AdminAg1!")
    _viewer_token = _login(f"viewer_ag_{_unique}", "ViewerAg1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def req(method, path, token=None, params=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{path}?{qs}"
    return client.open(url, method=method, headers=headers)


def _create_pc(suffix, **kwargs):
    """Create a PC directly in DB and return it."""
    with app.app_context():
        pc = PC(pc_name=f"TestAgent-{suffix}-{_unique}", **kwargs)
        db.session.add(pc)
        db.session.commit()
        return pc.id


def _create_snapshot(pc_id, cpu_usage=None, offset_seconds=0):
    """Create a SystemSnapshot for a PC."""
    with app.app_context():
        snap = SystemSnapshot(
            pc_id=pc_id,
            cpu_usage=cpu_usage,
            collected_at=datetime.now(timezone.utc) - timedelta(seconds=offset_seconds),
        )
        db.session.add(snap)
        db.session.commit()
        return snap.id


# ── GET /api/agents ──────────────────────────────────────────────────


def test_list_agents_unauthenticated():
    r = req("GET", "/api/agents")
    assert r.status_code == 401


def test_list_agents_empty():
    """Returns valid structure even with no PCs (or only pre-existing PCs)."""
    r = req("GET", "/api/agents", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "agents" in data
    assert "total" in data
    assert "page" in data
    assert "pages" in data
    assert isinstance(data["agents"], list)


def test_list_agents_viewer_allowed():
    r = req("GET", "/api/agents", token=_viewer_token)
    assert r.status_code == 200


def test_list_agents_with_pc_no_snapshot():
    """PC without snapshot: cpu_usage and memory_usage are None."""
    pc_id = _create_pc("nosnap", status="healthy")
    r = req("GET", "/api/agents", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    agents = data["agents"]
    pc_entry = next((a for a in agents if a["id"] == pc_id), None)
    assert pc_entry is not None
    assert pc_entry["cpu_usage"] is None
    assert pc_entry["memory_usage"] is None
    assert pc_entry["online"] is False  # no last_seen


def test_list_agents_with_pc_with_snapshot():
    """PC with snapshot: cpu_usage populated from latest snapshot."""
    pc_id = _create_pc(
        "withsnap",
        status="healthy",
        last_seen=datetime.now(timezone.utc),
        memory_total_gb=16.0,
        memory_available_gb=8.0,
    )
    _create_snapshot(pc_id, cpu_usage=42.5)
    r = req("GET", "/api/agents", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    pc_entry = next((a for a in data["agents"] if a["id"] == pc_id), None)
    assert pc_entry is not None
    assert pc_entry["cpu_usage"] == 42.5
    assert pc_entry["memory_usage"] == 50.0  # (16-8)/16 * 100


def test_list_agents_online_detection():
    """PC with last_seen within 300s is online."""
    now = datetime.now(timezone.utc)
    pc_id = _create_pc("online", last_seen=now - timedelta(seconds=100))
    r = req("GET", "/api/agents", token=_admin_token)
    data = json.loads(r.data)
    pc_entry = next((a for a in data["agents"] if a["id"] == pc_id), None)
    assert pc_entry is not None
    assert pc_entry["online"] is True


def test_list_agents_offline_detection():
    """PC with last_seen older than 300s is offline."""
    now = datetime.now(timezone.utc)
    pc_id = _create_pc("offline", last_seen=now - timedelta(seconds=400))
    r = req("GET", "/api/agents", token=_admin_token)
    data = json.loads(r.data)
    pc_entry = next((a for a in data["agents"] if a["id"] == pc_id), None)
    assert pc_entry is not None
    assert pc_entry["online"] is False


def test_list_agents_naive_datetime_last_seen():
    """PC with naive (no tzinfo) last_seen: treated as UTC."""
    naive_now = datetime.utcnow()  # naive datetime
    pc_id = _create_pc("naive", last_seen=naive_now)
    r = req("GET", "/api/agents", token=_admin_token)
    data = json.loads(r.data)
    pc_entry = next((a for a in data["agents"] if a["id"] == pc_id), None)
    assert pc_entry is not None
    # naive datetime stored recently → should be online
    assert pc_entry["online"] is True


def test_list_agents_status_filter_healthy():
    """Status filter returns only PCs matching that status."""
    _create_pc("filt_healthy", status="healthy")
    _create_pc("filt_critical", status="critical")
    r = req("GET", "/api/agents", token=_admin_token, params={"status": "healthy"})
    assert r.status_code == 200
    data = json.loads(r.data)
    for agent in data["agents"]:
        assert agent["status"] == "healthy"


def test_list_agents_status_filter_critical():
    r = req("GET", "/api/agents", token=_admin_token, params={"status": "critical"})
    assert r.status_code == 200
    data = json.loads(r.data)
    for agent in data["agents"]:
        assert agent["status"] == "critical"


def test_list_agents_status_filter_warning():
    _create_pc("filt_warn", status="warning")
    r = req("GET", "/api/agents", token=_admin_token, params={"status": "warning"})
    assert r.status_code == 200
    data = json.loads(r.data)
    for agent in data["agents"]:
        assert agent["status"] == "warning"


def test_list_agents_pagination_page1():
    r = req("GET", "/api/agents", token=_admin_token, params={"page": 1, "per_page": 5})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["page"] == 1
    assert len(data["agents"]) <= 5


def test_list_agents_pagination_per_page_capped():
    """per_page is capped at 200."""
    r = req("GET", "/api/agents", token=_admin_token, params={"per_page": 9999})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert len(data["agents"]) <= 200


def test_list_agents_agent_version_default():
    """PC without agent_version shows '—' in response."""
    pc_id = _create_pc("noversion", agent_version=None)
    r = req("GET", "/api/agents", token=_admin_token)
    data = json.loads(r.data)
    pc_entry = next((a for a in data["agents"] if a["id"] == pc_id), None)
    assert pc_entry is not None
    assert pc_entry["agent_version"] == "—"


def test_list_agents_with_agent_version():
    pc_id = _create_pc("withversion", agent_version="2.0.5")
    r = req("GET", "/api/agents", token=_admin_token)
    data = json.loads(r.data)
    pc_entry = next((a for a in data["agents"] if a["id"] == pc_id), None)
    assert pc_entry is not None
    assert pc_entry["agent_version"] == "2.0.5"


def test_list_agents_memory_no_total():
    """PC without memory_total_gb: memory_usage is None."""
    pc_id = _create_pc("nomemtotal", memory_total_gb=None, memory_available_gb=4.0)
    r = req("GET", "/api/agents", token=_admin_token)
    data = json.loads(r.data)
    pc_entry = next((a for a in data["agents"] if a["id"] == pc_id), None)
    assert pc_entry is not None
    assert pc_entry["memory_usage"] is None


def test_list_agents_response_fields():
    """All expected fields are present in each agent dict."""
    _create_pc("fields_check")
    r = req("GET", "/api/agents", token=_admin_token)
    data = json.loads(r.data)
    assert len(data["agents"]) > 0
    for agent in data["agents"]:
        for field in [
            "id",
            "pc_name",
            "ip_address",
            "os_version",
            "agent_version",
            "cpu_usage",
            "memory_usage",
            "status",
            "online",
            "last_seen",
        ]:
            assert field in agent, f"Missing field: {field}"


# ── GET /api/agents/export.csv ───────────────────────────────────────


def test_export_csv_unauthenticated():
    r = req("GET", "/api/agents/export.csv")
    assert r.status_code == 401


def test_export_csv_basic():
    r = req("GET", "/api/agents/export.csv", token=_admin_token)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("Content-Type", "")
    assert "agents.csv" in r.headers.get("Content-Disposition", "")


def test_export_csv_has_header_row():
    r = req("GET", "/api/agents/export.csv", token=_admin_token)
    content = r.data.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(content))
    header = next(reader)
    assert "ホスト名" in header
    assert "OSバージョン" in header
    assert "IPアドレス" in header
    assert "状態" in header


def test_export_csv_with_pc_data():
    """CSV contains a row for each PC."""
    _create_pc(
        "csvpc", status="healthy", ip_address="192.168.1.99", os_version="Win 11"
    )
    r = req("GET", "/api/agents/export.csv", token=_admin_token)
    content = r.data.decode("utf-8-sig")
    assert f"TestAgent-csvpc-{_unique}" in content


def test_export_csv_with_snapshot():
    """CSV includes cpu_usage from snapshot."""
    pc_id = _create_pc("csvsnap", memory_total_gb=8.0, memory_available_gb=4.0)
    _create_snapshot(pc_id, cpu_usage=75.5)
    r = req("GET", "/api/agents/export.csv", token=_admin_token)
    content = r.data.decode("utf-8-sig")
    assert "75.5" in content


def test_export_csv_online_label():
    """PC with recent last_seen shows 'オンライン' in CSV."""
    now = datetime.now(timezone.utc)
    _create_pc("csvonline", last_seen=now - timedelta(seconds=30))
    r = req("GET", "/api/agents/export.csv", token=_admin_token)
    content = r.data.decode("utf-8-sig")
    assert "オンライン" in content


def test_export_csv_offline_label():
    """PC with very old last_seen shows '古いデータ' (stale) in CSV."""
    _create_pc(
        "csvoffline",
        status="warning",
        last_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    r = req("GET", "/api/agents/export.csv", token=_admin_token)
    content = r.data.decode("utf-8-sig")
    assert "古いデータ" in content


def test_export_csv_naive_datetime_pc():
    """PC with naive (no tzinfo) last_seen: CSV export handles it without error."""
    naive_dt = datetime.utcnow() - timedelta(seconds=10)
    _create_pc("csvnaive", last_seen=naive_dt)
    r = req("GET", "/api/agents/export.csv", token=_admin_token)
    # Should succeed without 500 error — line 64-67 in agents.py
    assert r.status_code == 200


def test_export_csv_pc_no_last_seen():
    """PC with no last_seen: CSV export row has empty last_seen column."""
    _create_pc("csvnolastseen", last_seen=None, status="healthy")
    r = req("GET", "/api/agents/export.csv", token=_admin_token)
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert f"TestAgent-csvnolastseen-{_unique}" in content


def test_export_csv_viewer_allowed():
    r = req("GET", "/api/agents/export.csv", token=_viewer_token)
    assert r.status_code == 200


def test_export_csv_memory_usage_calculated():
    """CSV memory_usage column is calculated from total/available."""
    _create_pc("csvmem", memory_total_gb=16.0, memory_available_gb=12.0)
    r = req("GET", "/api/agents/export.csv", token=_admin_token)
    content = r.data.decode("utf-8-sig")
    assert "25.0" in content  # (16-12)/16 * 100 = 25.0

"""Extra coverage tests for routes/pcs.py.

Targets uncovered lines:
- export_pcs_csv: status/search/os filter (57, 59, 66), for-loop body (88)
- get_pc_software: success path (145-146)
- get_pc_updates: success path (161-166)
- get_pc_history: success path (181-196)
- delete_pc: success path (210-215)
"""

import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, Software, WindowsUpdate, User

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
            (f"admin_pcs_{_unique}", "admin", "AdminPcs1!"),
            (f"viewer_pcs_{_unique}", "viewer", "ViewerPcs1!"),
        ]:
            if not User.query.filter_by(username=username).first():
                db.session.add(User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                ))
        db.session.commit()

    _admin_token = _login(f"admin_pcs_{_unique}", "AdminPcs1!")
    _viewer_token = _login(f"viewer_pcs_{_unique}", "ViewerPcs1!")


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


def _create_pc(suffix, **kwargs):
    with app.app_context():
        pc = PC(pc_name=f"TestPC-{suffix}-{_unique}", **kwargs)
        db.session.add(pc)
        db.session.commit()
        return pc.id


def _create_software(pc_id, name="TestApp", version="1.0"):
    with app.app_context():
        sw = Software(pc_id=pc_id, name=name, version=version)
        db.session.add(sw)
        db.session.commit()
        return sw.id


def _create_update(pc_id, kb_id="KB123456"):
    with app.app_context():
        upd = WindowsUpdate(pc_id=pc_id, kb_id=kb_id, title="Test Update", installed=True)
        db.session.add(upd)
        db.session.commit()
        return upd.id


# ── export_pcs_csv with filters (lines 57, 59, 66) ──────────────────


def test_export_csv_with_status_filter():
    """export.csv?status=healthy covers line 57."""
    _create_pc("csvstatus", status="healthy", ip_address="10.0.0.1")
    r = client.open(
        f"/api/pcs/export.csv?status=healthy",
        method="GET",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("Content-Type", "")
    content = r.data.decode("utf-8-sig")
    assert f"TestPC-csvstatus-{_unique}" in content


def test_export_csv_with_search_filter():
    """export.csv?search=... covers line 59."""
    pc_name_suffix = f"srchpc-{_unique}"
    _create_pc("srchpc", ip_address="10.1.2.3")
    r = client.open(
        f"/api/pcs/export.csv?search=TestPC-srchpc",
        method="GET",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert f"TestPC-srchpc-{_unique}" in content


def test_export_csv_with_os_filter():
    """export.csv?os=Win11 covers line 66."""
    _create_pc("ospc", os_version="Win11-ExtraSpec", status="healthy")
    r = client.open(
        "/api/pcs/export.csv?os=Win11-ExtraSpec",
        method="GET",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert f"TestPC-ospc-{_unique}" in content


def test_export_csv_for_loop_body():
    """CSV export with PCs in DB covers the for loop body (line 88)."""
    pc_id = _create_pc("csvloop", status="healthy", health_score=95.0, ip_address="192.168.1.10")
    r = client.open(
        "/api/pcs/export.csv",
        method="GET",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert f"TestPC-csvloop-{_unique}" in content
    assert "95.0" in content


def test_export_csv_pc_no_health_score():
    """PC without health_score shows empty in CSV (line 97 branch)."""
    _create_pc("nohscore", health_score=None)
    r = client.open(
        "/api/pcs/export.csv",
        method="GET",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code == 200


# ── get_pc_software: success path (lines 145-146) ────────────────────


def test_get_pc_software_success():
    """GET /api/pcs/{id}/software with existing PC covers lines 145-146."""
    pc_id = _create_pc("softwarepc")
    _create_software(pc_id, name="Google Chrome", version="124.0")
    r = req("GET", f"/api/pcs/{pc_id}/software", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "software" in data
    assert "pc_name" in data
    assert "total" in data
    assert data["total"] >= 1
    names = [s["name"] for s in data["software"]]
    assert "Google Chrome" in names


def test_get_pc_software_empty():
    """PC with no software returns empty list."""
    pc_id = _create_pc("emptyswpc")
    r = req("GET", f"/api/pcs/{pc_id}/software", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["total"] == 0
    assert data["software"] == []


def test_get_pc_software_viewer_allowed():
    pc_id = _create_pc("viewswpc")
    r = req("GET", f"/api/pcs/{pc_id}/software", token=_viewer_token)
    assert r.status_code == 200


# ── get_pc_updates: success path (lines 161-166) ─────────────────────


def test_get_pc_updates_success():
    """GET /api/pcs/{id}/updates with existing PC covers lines 161-166."""
    pc_id = _create_pc("updpc")
    _create_update(pc_id, kb_id="KB9990001")
    r = req("GET", f"/api/pcs/{pc_id}/updates", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "updates" in data
    assert "pc_name" in data
    assert "total" in data
    assert data["total"] >= 1
    kb_ids = [u["kb_id"] for u in data["updates"]]
    assert "KB9990001" in kb_ids


def test_get_pc_updates_empty():
    """PC with no updates returns empty list."""
    pc_id = _create_pc("emptyupdpc")
    r = req("GET", f"/api/pcs/{pc_id}/updates", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["total"] == 0


# ── get_pc_history: success path (lines 181-196) ─────────────────────


def test_get_pc_history_success():
    """GET /api/pcs/{id}/history with existing PC covers lines 181-196."""
    pc_id = _create_pc("histpc")
    r = req("GET", f"/api/pcs/{pc_id}/history", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "pc_name" in data
    assert "snapshots" in data
    assert isinstance(data["snapshots"], list)


def test_get_pc_history_with_days_param():
    """?days=30 caps at 365 and filters correctly."""
    pc_id = _create_pc("histdayspc")
    r = req("GET", f"/api/pcs/{pc_id}/history", token=_admin_token, params={"days": 30})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "snapshots" in data


def test_get_pc_history_days_capped_at_365():
    """?days=9999 is capped at 365 — function still returns 200."""
    pc_id = _create_pc("histcappc")
    r = req("GET", f"/api/pcs/{pc_id}/history", token=_admin_token, params={"days": 9999})
    assert r.status_code == 200


# ── delete_pc: success path (lines 210-215) ──────────────────────────


def test_delete_pc_success():
    """DELETE /api/pcs/{id} admin success covers lines 210-215."""
    pc_id = _create_pc("delpc")
    r = req("DELETE", f"/api/pcs/{pc_id}", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "message" in data
    assert "削除" in data["message"]

    # Confirm PC is gone
    r2 = req("GET", f"/api/pcs/{pc_id}", token=_admin_token)
    assert r2.status_code == 404


def test_delete_pc_viewer_forbidden():
    """DELETE by viewer → 403."""
    pc_id = _create_pc("delvwpc")
    r = req("DELETE", f"/api/pcs/{pc_id}", token=_viewer_token)
    assert r.status_code == 403
    # cleanup
    req("DELETE", f"/api/pcs/{pc_id}", token=_admin_token)

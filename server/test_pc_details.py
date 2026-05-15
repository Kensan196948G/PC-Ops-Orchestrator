"""Phase A-3 (#176) — /api/pcs/<id>/details 統合エンドポイントテスト.

検証対象:
- 統合ペイロード (pc + snapshots + software + windows_updates +
  network_interfaces + recent_tasks + counts)
- 404 (存在しない PC)
- 401 (未認証)
- history_days のクランプ (max 90)
- counts 一致
- network_interfaces / software の並び順
"""

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import (
    PC,
    Software,
    WindowsUpdate,
    NetworkInterface,
    Task,
    User,
)

app = create_app("testing")
client = app.test_client()

_admin_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token
    with app.app_context():
        db.create_all()
        username = f"admin_details_{_unique}"
        if not User.query.filter_by(username=username).first():
            db.session.add(
                User(
                    username=username,
                    password_hash=hash_password("AdminDet1!"),
                    role="admin",
                )
            )
            db.session.commit()
    _admin_token = _login(f"admin_details_{_unique}", "AdminDet1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def _req(method, path, token=None, params=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{path}?{qs}"
    return client.open(url, method=method, headers=headers)


def _create_pc(suffix, **kwargs):
    with app.app_context():
        pc = PC(pc_name=f"DetailPC-{suffix}-{_unique}", **kwargs)
        db.session.add(pc)
        db.session.commit()
        return pc.id


def test_details_returns_404_for_missing_pc():
    r = _req("GET", "/api/pcs/999999/details", token=_admin_token)
    assert r.status_code == 404


def test_details_requires_authentication():
    pc_id = _create_pc("auth")
    r = client.open(f"/api/pcs/{pc_id}/details", method="GET")
    assert r.status_code == 401


def test_details_returns_consolidated_payload():
    pc_id = _create_pc(
        "consolidated",
        status="healthy",
        os_version="Windows 11",
        os_build="22631.3447",
        ip_address="10.0.0.10",
    )

    with app.app_context():
        db.session.add(Software(pc_id=pc_id, name="Google Chrome", version="124.0"))
        db.session.add(Software(pc_id=pc_id, name="7-Zip", version="23.01"))
        db.session.add(
            WindowsUpdate(
                pc_id=pc_id,
                kb_id="KB5034441",
                title="Cumulative Update",
                installed=True,
            )
        )
        db.session.add(
            NetworkInterface(
                pc_id=pc_id,
                interface_name="Ethernet0",
                ip_address="10.0.0.10",
                link_speed_mbps=1000,
                is_active=True,
            )
        )
        db.session.add(
            NetworkInterface(
                pc_id=pc_id,
                interface_name="Wi-Fi",
                ip_address="10.0.0.20",
                link_speed_mbps=866,
                is_active=True,
            )
        )
        db.session.add(Task(pc_id=pc_id, task_type="cleanup", status="completed"))
        db.session.commit()

    r = _req("GET", f"/api/pcs/{pc_id}/details", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)

    assert data["pc"]["id"] == pc_id
    assert data["pc"]["os_build"] == "22631.3447"

    assert isinstance(data["snapshots"], list)
    assert isinstance(data["software"], list)
    assert isinstance(data["windows_updates"], list)
    assert isinstance(data["network_interfaces"], list)
    assert isinstance(data["recent_tasks"], list)

    counts = data["counts"]
    assert counts["software"] == len(data["software"])
    assert counts["windows_updates"] == len(data["windows_updates"])
    assert counts["network_interfaces"] == len(data["network_interfaces"])
    assert counts["snapshots"] == len(data["snapshots"])

    assert counts["software"] == 2
    assert counts["windows_updates"] == 1
    assert counts["network_interfaces"] == 2


def test_details_software_ordered_by_name():
    pc_id = _create_pc("sworder")
    with app.app_context():
        db.session.add(Software(pc_id=pc_id, name="Zoom", version="5.0"))
        db.session.add(Software(pc_id=pc_id, name="Acrobat", version="2024"))
        db.session.add(Software(pc_id=pc_id, name="MikuMikuDance", version="9.32"))
        db.session.commit()

    r = _req("GET", f"/api/pcs/{pc_id}/details", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    names = [s["name"] for s in data["software"]]
    assert names == sorted(names)
    assert names[0] == "Acrobat"


def test_details_network_ordered_by_interface_name():
    pc_id = _create_pc("netorder")
    with app.app_context():
        db.session.add(
            NetworkInterface(
                pc_id=pc_id, interface_name="Wi-Fi", ip_address="10.0.0.20"
            )
        )
        db.session.add(
            NetworkInterface(
                pc_id=pc_id, interface_name="Ethernet0", ip_address="10.0.0.10"
            )
        )
        db.session.add(
            NetworkInterface(pc_id=pc_id, interface_name="Bluetooth", ip_address=None)
        )
        db.session.commit()

    r = _req("GET", f"/api/pcs/{pc_id}/details", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    names = [n["interface_name"] for n in data["network_interfaces"]]
    assert names == sorted(names)
    assert names[0] == "Bluetooth"


def test_details_history_days_query_param_accepted():
    pc_id = _create_pc("histdays")
    r = _req(
        "GET",
        f"/api/pcs/{pc_id}/details",
        token=_admin_token,
        params={"history_days": 30},
    )
    assert r.status_code == 200


def test_details_history_days_clamped_to_90():
    """history_days=9999 → サーバ側で 90 にクランプされる (200 を返す)."""
    pc_id = _create_pc("histclamp")
    r = _req(
        "GET",
        f"/api/pcs/{pc_id}/details",
        token=_admin_token,
        params={"history_days": 9999},
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "snapshots" in data


def test_details_empty_lists_for_pc_with_no_data():
    pc_id = _create_pc("empty")
    r = _req("GET", f"/api/pcs/{pc_id}/details", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["software"] == []
    assert data["windows_updates"] == []
    assert data["network_interfaces"] == []
    assert data["snapshots"] == []
    assert data["counts"]["software"] == 0
    assert data["counts"]["network_interfaces"] == 0

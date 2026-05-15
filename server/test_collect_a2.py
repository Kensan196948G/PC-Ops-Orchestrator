"""Phase A-2 (#175) — /api/collect 拡張テスト.

検証対象:
- os_build ingestion (フラットキー / hardware.os_build 双方)
- network 配列 → NetworkInterface upsert
- (pc_id, interface_name) 冪等性
- 後方互換 (v1 フラットペイロードは無傷)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models import PC, NetworkInterface


API_KEY = "default-agent-key"


@pytest.fixture(scope="module")
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


@pytest.fixture(autouse=True)
def _cleanup(app):
    """Drop test PCs/NICs between cases to keep upsert tests deterministic."""
    yield
    with app.app_context():
        for name in ("A2-OSBUILD-PC", "A2-NET-PC", "A2-HW-PC", "A2-COMPAT-PC"):
            pc = PC.query.filter_by(pc_name=name).first()
            if pc:
                NetworkInterface.query.filter_by(pc_id=pc.id).delete()
                db.session.delete(pc)
        db.session.commit()


def test_collect_ingests_os_build_flat_key(app, client, headers):
    res = client.post(
        "/api/collect",
        json={"pc_name": "A2-OSBUILD-PC", "os_build": "22631.3447"},
        headers=headers,
    )
    assert res.status_code == 200
    with app.app_context():
        pc = PC.query.filter_by(pc_name="A2-OSBUILD-PC").first()
        assert pc is not None
        assert pc.os_build == "22631.3447"


def test_collect_ingests_os_build_from_hardware_block(app, client, headers):
    res = client.post(
        "/api/collect",
        json={
            "pc_name": "A2-HW-PC",
            "hardware": {
                "os_build": "26100.1234",
                "cpu_name": "Intel(R) Core(TM) i7-13700",
                "cpu_cores": 16,
                "memory_total_gb": 32.0,
            },
        },
        headers=headers,
    )
    assert res.status_code == 200
    with app.app_context():
        pc = PC.query.filter_by(pc_name="A2-HW-PC").first()
        assert pc.os_build == "26100.1234"
        assert pc.cpu_name == "Intel(R) Core(TM) i7-13700"
        assert pc.cpu_cores == 16
        assert pc.memory_total_gb == 32.0


def test_collect_upserts_network_interfaces(app, client, headers):
    res = client.post(
        "/api/collect",
        json={
            "pc_name": "A2-NET-PC",
            "network": [
                {
                    "interface_name": "Ethernet0",
                    "description": "Intel I219-V",
                    "mac_address": "AA:BB:CC:DD:EE:00",
                    "ip_address": "10.0.0.10",
                    "subnet_mask": "255.255.255.0",
                    "gateway": "10.0.0.1",
                    "dns_servers": "8.8.8.8,1.1.1.1",
                    "link_speed_mbps": 1000,
                },
                {
                    "interface_name": "Wi-Fi",
                    "mac_address": "AA:BB:CC:DD:EE:01",
                    "ip_address": "10.0.0.20",
                    "link_speed_mbps": 866,
                },
            ],
        },
        headers=headers,
    )
    assert res.status_code == 200
    with app.app_context():
        pc = PC.query.filter_by(pc_name="A2-NET-PC").first()
        nics = NetworkInterface.query.filter_by(pc_id=pc.id).all()
        assert len(nics) == 2
        by_name = {n.interface_name: n for n in nics}
        assert by_name["Ethernet0"].ip_address == "10.0.0.10"
        assert by_name["Ethernet0"].link_speed_mbps == 1000
        assert by_name["Wi-Fi"].link_speed_mbps == 866
        assert by_name["Ethernet0"].is_active is True


def test_collect_network_upsert_is_idempotent(app, client, headers):
    payload = {
        "pc_name": "A2-NET-PC",
        "network": [
            {
                "interface_name": "Ethernet0",
                "ip_address": "10.0.0.10",
                "link_speed_mbps": 1000,
            }
        ],
    }
    client.post("/api/collect", json=payload, headers=headers)
    client.post("/api/collect", json=payload, headers=headers)

    with app.app_context():
        pc = PC.query.filter_by(pc_name="A2-NET-PC").first()
        nics = NetworkInterface.query.filter_by(pc_id=pc.id).all()
        assert len(nics) == 1
        assert nics[0].ip_address == "10.0.0.10"


def test_collect_network_upsert_updates_existing(app, client, headers):
    client.post(
        "/api/collect",
        json={
            "pc_name": "A2-NET-PC",
            "network": [{"interface_name": "Ethernet0", "ip_address": "10.0.0.10"}],
        },
        headers=headers,
    )
    client.post(
        "/api/collect",
        json={
            "pc_name": "A2-NET-PC",
            "network": [
                {
                    "interface_name": "Ethernet0",
                    "ip_address": "10.0.0.99",
                    "link_speed_mbps": 2500,
                }
            ],
        },
        headers=headers,
    )
    with app.app_context():
        pc = PC.query.filter_by(pc_name="A2-NET-PC").first()
        nic = NetworkInterface.query.filter_by(
            pc_id=pc.id, interface_name="Ethernet0"
        ).one()
        assert nic.ip_address == "10.0.0.99"
        assert nic.link_speed_mbps == 2500


def test_collect_network_missing_name_is_skipped(app, client, headers):
    res = client.post(
        "/api/collect",
        json={
            "pc_name": "A2-NET-PC",
            "network": [
                {"interface_name": "", "ip_address": "10.0.0.10"},
                {"ip_address": "10.0.0.11"},
                "garbage-non-dict",
            ],
        },
        headers=headers,
    )
    assert res.status_code == 200
    with app.app_context():
        pc = PC.query.filter_by(pc_name="A2-NET-PC").first()
        assert NetworkInterface.query.filter_by(pc_id=pc.id).count() == 0


def test_collect_network_is_active_explicit_false_persists(app, client, headers):
    """is_active=False from the agent must NOT be silently coerced back to True."""
    client.post(
        "/api/collect",
        json={
            "pc_name": "A2-NET-PC",
            "network": [{"interface_name": "Ethernet0", "ip_address": "10.0.0.10"}],
        },
        headers=headers,
    )
    client.post(
        "/api/collect",
        json={
            "pc_name": "A2-NET-PC",
            "network": [
                {
                    "interface_name": "Ethernet0",
                    "ip_address": "10.0.0.10",
                    "is_active": False,
                }
            ],
        },
        headers=headers,
    )
    with app.app_context():
        pc = PC.query.filter_by(pc_name="A2-NET-PC").first()
        nic = NetworkInterface.query.filter_by(
            pc_id=pc.id, interface_name="Ethernet0"
        ).one()
        assert nic.is_active is False


def test_collect_network_is_active_missing_preserves_existing(app, client, headers):
    """Subsequent payloads without is_active must NOT flip a disabled NIC back on."""
    client.post(
        "/api/collect",
        json={
            "pc_name": "A2-NET-PC",
            "network": [
                {
                    "interface_name": "Ethernet0",
                    "ip_address": "10.0.0.10",
                    "is_active": False,
                }
            ],
        },
        headers=headers,
    )
    client.post(
        "/api/collect",
        json={
            "pc_name": "A2-NET-PC",
            "network": [{"interface_name": "Ethernet0", "ip_address": "10.0.0.99"}],
        },
        headers=headers,
    )
    with app.app_context():
        pc = PC.query.filter_by(pc_name="A2-NET-PC").first()
        nic = NetworkInterface.query.filter_by(
            pc_id=pc.id, interface_name="Ethernet0"
        ).one()
        assert nic.is_active is False
        assert nic.ip_address == "10.0.0.99"


def test_collect_v1_payload_remains_backward_compatible(app, client, headers):
    res = client.post(
        "/api/collect",
        json={
            "pc_name": "A2-COMPAT-PC",
            "os_version": "Windows 10",
            "cpu_name": "AMD Ryzen 5",
            "memory_total_gb": 16.0,
            "memory_available_gb": 8.0,
            "disk_total_gb": 512.0,
            "disk_free_gb": 256.0,
            "ip_address": "192.168.0.5",
            "agent_version": "1.0.0",
        },
        headers=headers,
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] in ("healthy", "warning", "critical")
    with app.app_context():
        pc = PC.query.filter_by(pc_name="A2-COMPAT-PC").first()
        assert pc.os_build is None
        assert pc.cpu_name == "AMD Ryzen 5"
        assert NetworkInterface.query.filter_by(pc_id=pc.id).count() == 0

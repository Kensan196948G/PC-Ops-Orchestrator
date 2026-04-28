"""Integration test for PC-Ops Orchestrator API."""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import User

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


def request(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data else None
    return client.open(path, method=method, headers=headers, data=body)


def test_login():
    r = request(
        "POST", "/api/auth/login", data={"username": "admin", "password": "admin"}
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert "token" in data
    print(f"  [PASS] Login: token={data['token'][:20]}...")


def test_dashboard_stats(token):
    r = request("GET", "/api/dashboard/stats", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    print(f"  [PASS] Dashboard stats: {json.dumps(data)}")


def test_agent_collect():
    body = {
        "pc_name": "PC-TEST-001",
        "domain": "company.local",
        "os_version": "Windows 11 Pro",
        "os_architecture": "64-bit",
        "cpu_name": "Intel Core i7-12700H",
        "cpu_cores": 14,
        "cpu_logical_processors": 20,
        "memory_total_gb": 32.0,
        "memory_available_gb": 18.5,
        "disk_total_gb": 512.0,
        "disk_free_gb": 256.0,
        "ip_address": "192.168.1.100",
        "agent_version": "1.0.0",
        "cpu_usage": 23.5,
        "uptime_days": 5.2,
        "pending_reboot": False,
    }
    r = request("POST", "/api/collect", token="default-agent-key", data=body)
    assert r.status_code == 200, f"Collect failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert data["message"] == "ok"
    assert data["pc_id"] > 0
    print(
        f"  [PASS] Agent collect: pc_id={data['pc_id']}, score={data['health_score']}"
    )


def test_pc_list(token):
    r = request("GET", "/api/pcs", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["total"] >= 1
    assert len(data["pcs"]) >= 1
    print(f"  [PASS] PC list: {data['total']} PCs, first={data['pcs'][0]['pc_name']}")


def test_pc_detail(token):
    r = request("GET", "/api/pcs/1", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["pc"]["pc_name"] == "PC-TEST-001"
    print(f"  [PASS] PC detail: {data['pc']['pc_name']}")


def test_create_task(token):
    body = {"task_type": "cleanup", "pc_name": "PC-TEST-001", "priority": 1}
    r = request("POST", "/api/tasks", token=token, data=body)
    assert r.status_code == 201, f"Task create failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert data["task"]["status"] == "pending"
    print(
        f"  [PASS] Create task: id={data['task']['id']}, type={data['task']['task_type']}"
    )


def test_task_list(token):
    r = request("GET", "/api/tasks", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["total"] >= 1
    print(f"  [PASS] Task list: {data['total']} tasks")


def test_delete_task(token):
    body = {"task_type": "cleanup", "pc_name": "PC-TEST-001", "priority": 1}
    created = request("POST", "/api/tasks", token=token, data=body)
    assert created.status_code == 201
    task_id = json.loads(created.data)["task"]["id"]

    r = request("DELETE", f"/api/tasks/{task_id}", token=token)
    assert r.status_code == 200, f"Delete task failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert "message" in data
    print(f"  [PASS] Delete task: id={task_id}")


def test_agent_submit_result():
    body = {"task_id": 1, "status": "completed", "result": {"cleaned": True}}
    r = request("POST", "/api/result", token="default-agent-key", data=body)
    assert r.status_code == 200
    data = json.loads(r.data)
    print(f"  [PASS] Submit result: {data['message']}")


def test_alerts_sync(token):
    r = request("POST", "/api/alerts/sync", token=token)
    assert r.status_code == 200, f"Alerts sync failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert "created" in data
    assert "resolved" in data
    print(
        f"  [PASS] Alerts sync: created={data['created']}, resolved={data['resolved']}"
    )


def test_alerts_list(token):
    r = request("GET", "/api/alerts", token=token)
    assert r.status_code == 200, f"Alerts list failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert "alerts" in data
    assert "total" in data
    assert "unresolved_count" in data
    print(
        f"  [PASS] Alerts list: total={data['total']}, unresolved={data['unresolved_count']}"
    )


def test_alerts_acknowledge_and_resolve(token):
    sync = request("POST", "/api/alerts/sync", token=token)
    assert sync.status_code == 200

    r = request("GET", "/api/alerts", token=token)
    assert r.status_code == 200
    alerts = json.loads(r.data)["alerts"]

    if not alerts:
        print("  [SKIP] No active alerts to acknowledge/resolve")
        return

    alert_id = alerts[0]["id"]

    ack = request("POST", f"/api/alerts/{alert_id}/acknowledge", token=token)
    assert ack.status_code == 200, f"Acknowledge failed: {ack.status_code} {ack.data}"
    ack_data = json.loads(ack.data)
    assert ack_data["alert"]["acknowledged"] is True
    print(f"  [PASS] Alert acknowledge: id={alert_id}")

    resolve = request("POST", f"/api/alerts/{alert_id}/resolve", token=token)
    assert resolve.status_code == 200, (
        f"Resolve failed: {resolve.status_code} {resolve.data}"
    )
    print(f"  [PASS] Alert resolve: id={alert_id}")


def test_webui_pages(token):
    pages = [
        ("/", "Dashboard"),
        ("/pcs", "PC List"),
        ("/tasks", "Task Management"),
        ("/alerts", "Alert Management"),
    ]
    for path, name in pages:
        headers = {"Authorization": f"Bearer {token}"}
        r = client.get(path, headers=headers)
        assert r.status_code == 200, f"{name} failed: {r.status_code}"
        print(f"  [PASS] WebUI {name}: {r.status_code}")


def test_health_distribution(token):
    r = request("GET", "/api/dashboard/health-distribution", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    print(f"  [PASS] Health distribution: {json.dumps(data)}")


def test_os_breakdown(token):
    r = request("GET", "/api/dashboard/os-breakdown", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    print(f"  [PASS] OS breakdown: {json.dumps(data)}")


def test_create_task_invalid_type(token):
    r = request(
        "POST",
        "/api/tasks",
        token=token,
        data={"task_type": "evil_type", "priority": 1},
    )
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"
    data = json.loads(r.data)
    assert "error" in data
    print(f"  [PASS] Create task with invalid type rejected: {data['error'][:60]}")


def test_create_task_command_too_long(token):
    r = request(
        "POST",
        "/api/tasks",
        token=token,
        data={"task_type": "custom", "command": "x" * 513},
    )
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"
    data = json.loads(r.data)
    assert "error" in data
    print(f"  [PASS] Create task with long command rejected: {data['error'][:60]}")


def test_create_task_command_not_string(token):
    r = request(
        "POST",
        "/api/tasks",
        token=token,
        data={"task_type": "custom", "command": 12345},
    )
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"
    data = json.loads(r.data)
    assert "error" in data
    print(
        f"  [PASS] Create task with non-string command rejected: {data['error'][:60]}"
    )


def run_all():
    print("=== PC-Ops Orchestrator API Tests ===\n")
    setup_module()
    print("[Setup] Database initialized")

    r = request(
        "POST", "/api/auth/login", data={"username": "admin", "password": "admin"}
    )
    assert r.status_code == 200
    token = json.loads(r.data)["token"]
    print(f"  [PASS] Login: token={token[:20]}...")

    test_dashboard_stats(token)
    test_agent_collect()
    test_pc_list(token)
    test_pc_detail(token)
    test_create_task(token)
    test_task_list(token)
    test_delete_task(token)
    test_agent_submit_result()
    test_health_distribution(token)
    test_os_breakdown(token)
    test_create_task_invalid_type(token)
    test_create_task_command_too_long(token)
    test_create_task_command_not_string(token)
    test_alerts_sync(token)
    test_alerts_list(token)
    test_alerts_acknowledge_and_resolve(token)
    test_webui_pages(token)

    print("\n=== All tests PASSED ===")


if __name__ == "__main__":
    run_all()

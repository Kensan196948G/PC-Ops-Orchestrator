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


def test_pc_search_by_name(token):
    r = request("GET", "/api/pcs?search=PC-TEST", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["total"] >= 1
    assert all(
        "PC-TEST" in pc["pc_name"].upper() or (pc.get("ip_address") or "")
        for pc in data["pcs"]
    )
    print(f"  [PASS] PC search by name: {data['total']} results")


def test_pc_search_by_ip(token):
    r = request("GET", "/api/pcs?search=192.168", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["total"] >= 1
    assert all(
        "192.168" in (pc.get("ip_address") or "") or "192.168" in pc["pc_name"]
        for pc in data["pcs"]
    )
    print(f"  [PASS] PC search by IP: {data['total']} results")


def test_pc_search_no_match(token):
    r = request("GET", "/api/pcs?search=ZZZNOMATCH999", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["total"] == 0
    print(f"  [PASS] PC search no match: total={data['total']}")


def test_pc_filter_by_status(token):
    r = request("GET", "/api/pcs?status=healthy", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert all(pc["status"] == "healthy" for pc in data["pcs"])
    print(f"  [PASS] PC filter by status=healthy: {data['total']} results")


def test_pc_filter_by_os(token):
    r = request("GET", "/api/pcs?os=Windows", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert all("windows" in (pc.get("os_version") or "").lower() for pc in data["pcs"])
    print(f"  [PASS] PC filter by os=Windows: {data['total']} results")


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


def test_user_management(token):
    r = request("GET", "/api/auth/users", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "users" in data
    assert data["total"] >= 1
    print(f"  [PASS] User list: {data['total']} users")

    r2 = request(
        "POST",
        "/api/auth/users",
        token=token,
        data={"username": "testop", "password": "testpass1", "role": "operator"},
    )
    assert r2.status_code == 201, f"User create failed: {r2.status_code} {r2.data}"
    created = json.loads(r2.data)
    assert created["user"]["role"] == "operator"
    user_id = created["user"]["id"]
    print(f"  [PASS] User create: id={user_id}")

    r3 = request(
        "PATCH",
        f"/api/auth/users/{user_id}",
        token=token,
        data={"role": "admin", "is_active": False},
    )
    assert r3.status_code == 200
    updated = json.loads(r3.data)
    assert updated["user"]["role"] == "admin"
    assert updated["user"]["is_active"] is False
    print(f"  [PASS] User update: role={updated['user']['role']}")

    r4 = request("DELETE", f"/api/auth/users/{user_id}", token=token)
    assert r4.status_code == 200
    print(f"  [PASS] User delete: id={user_id}")


def test_user_management_forbidden(token):
    r = request(
        "POST",
        "/api/auth/users",
        token=token,
        data={"username": "x" * 200, "password": "short"},
    )
    assert r.status_code in (400, 409)
    print(f"  [PASS] User create invalid rejected: {r.status_code}")


def test_webui_pages(token):
    pages = [
        ("/", "Dashboard"),
        ("/pcs", "PC List"),
        ("/tasks", "Task Management"),
        ("/alerts", "Alert Management"),
        ("/users", "User Management"),
        ("/scheduled-tasks", "Scheduled Tasks"),
        ("/groups", "PC Groups"),
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


_st_id = None


def test_create_scheduled_task(token):
    global _st_id
    body = {
        "name": "Test Interval Task",
        "description": "pytest created",
        "task_type": "collect",
        "schedule_type": "interval",
        "interval_minutes": 30,
        "is_enabled": True,
    }
    r = request("POST", "/api/scheduled-tasks", token=token, data=body)
    assert r.status_code == 201, (
        f"Create scheduled task failed: {r.status_code} {r.data}"
    )
    data = json.loads(r.data)
    assert "scheduled_task" in data
    st = data["scheduled_task"]
    assert st["name"] == "Test Interval Task"
    assert st["schedule_type"] == "interval"
    assert st["interval_minutes"] == 30
    assert st["is_enabled"] is True
    assert st["next_run_at"] is not None
    _st_id = st["id"]
    print(
        f"  [PASS] Create scheduled task: id={_st_id}, next_run_at={st['next_run_at']}"
    )


def test_list_scheduled_tasks(token):
    r = request("GET", "/api/scheduled-tasks", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "scheduled_tasks" in data
    assert data["total"] >= 1
    print(f"  [PASS] List scheduled tasks: total={data['total']}")


def test_get_scheduled_task(token):
    r = request("GET", f"/api/scheduled-tasks/{_st_id}", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["scheduled_task"]["id"] == _st_id
    print(f"  [PASS] Get scheduled task: id={_st_id}")


def test_update_scheduled_task(token):
    body = {
        "name": "Test Daily Task",
        "task_type": "diagnose",
        "schedule_type": "daily",
        "daily_time": "03:00",
        "is_enabled": True,
    }
    r = request("PUT", f"/api/scheduled-tasks/{_st_id}", token=token, data=body)
    assert r.status_code == 200, f"Update failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    st = data["scheduled_task"]
    assert st["schedule_type"] == "daily"
    assert st["daily_time"] == "03:00"
    print(
        f"  [PASS] Update scheduled task: id={_st_id}, schedule_type={st['schedule_type']}"
    )


def test_toggle_scheduled_task(token):
    r = request("POST", f"/api/scheduled-tasks/{_st_id}/toggle", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["scheduled_task"]["is_enabled"] is False
    print(f"  [PASS] Toggle scheduled task (disabled): id={_st_id}")

    r2 = request("POST", f"/api/scheduled-tasks/{_st_id}/toggle", token=token)
    assert r2.status_code == 200
    data2 = json.loads(r2.data)
    assert data2["scheduled_task"]["is_enabled"] is True
    print(f"  [PASS] Toggle scheduled task (re-enabled): id={_st_id}")


def test_run_scheduled_task_now(token):
    r = request("POST", f"/api/scheduled-tasks/{_st_id}/run-now", token=token)
    assert r.status_code == 201, f"Run-now failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert "task" in data
    assert data["task"]["status"] == "pending"
    print(f"  [PASS] Run scheduled task now: task_id={data['task']['id']}")


def test_scheduled_task_invalid_payload(token):
    r = request(
        "POST",
        "/api/scheduled-tasks",
        token=token,
        data={
            "name": "bad",
            "task_type": "evil",
            "schedule_type": "interval",
            "interval_minutes": 1,
        },
    )
    assert r.status_code == 400
    data = json.loads(r.data)
    assert "error" in data
    print(f"  [PASS] Scheduled task invalid task_type rejected: {data['error'][:60]}")


def test_delete_scheduled_task(token):
    r = request("DELETE", f"/api/scheduled-tasks/{_st_id}", token=token)
    assert r.status_code == 200, f"Delete failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert "message" in data
    print(f"  [PASS] Delete scheduled task: id={_st_id}")

    r2 = request("GET", f"/api/scheduled-tasks/{_st_id}", token=token)
    assert r2.status_code == 404
    print(f"  [PASS] Deleted task not found: id={_st_id}")


_group_id = None


def test_create_group(token):
    global _group_id
    body = {"name": "TestGroup-Alpha", "description": "pytest group"}
    r = request("POST", "/api/groups", token=token, data=body)
    assert r.status_code == 201, f"Create group failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    g = data["group"]
    assert g["name"] == "TestGroup-Alpha"
    _group_id = g["id"]
    print(f"  [PASS] Create group: id={_group_id}")


def test_list_groups(token):
    r = request("GET", "/api/groups", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "groups" in data
    ids = [g["id"] for g in data["groups"]]
    assert _group_id in ids
    print(f"  [PASS] List groups: total={data['total']}")


def test_get_group(token):
    r = request("GET", f"/api/groups/{_group_id}", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["group"]["id"] == _group_id
    print(f"  [PASS] Get group: id={_group_id}")


def test_update_group(token):
    body = {"name": "TestGroup-Alpha-Updated", "description": "updated"}
    r = request("PUT", f"/api/groups/{_group_id}", token=token, data=body)
    assert r.status_code == 200, f"Update group failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert data["group"]["name"] == "TestGroup-Alpha-Updated"
    print(f"  [PASS] Update group: id={_group_id}")


def test_add_pc_to_group(token):
    body = {"pc_name": "PC-TEST-001"}
    r = request("POST", f"/api/groups/{_group_id}/pcs", token=token, data=body)
    assert r.status_code == 200, f"Add PC failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    pcs = data["group"]["pcs"]
    assert any(p["pc_name"] == "PC-TEST-001" for p in pcs)
    print(f"  [PASS] Add PC to group: group={_group_id}")


def test_create_group_task(token):
    body = {"task_type": "collect"}
    r = request("POST", f"/api/groups/{_group_id}/tasks", token=token, data=body)
    assert r.status_code == 201, f"Group task failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert len(data["tasks"]) >= 1
    print(f"  [PASS] Group task: {len(data['tasks'])} task(s) created")


def test_remove_pc_from_group(token):
    r = request("GET", f"/api/groups/{_group_id}", token=token)
    pcs = json.loads(r.data)["group"]["pcs"]
    pc_id = next(p["id"] for p in pcs if p["pc_name"] == "PC-TEST-001")
    r2 = request("DELETE", f"/api/groups/{_group_id}/pcs/{pc_id}", token=token)
    assert r2.status_code == 200, f"Remove PC failed: {r2.status_code} {r2.data}"
    print(f"  [PASS] Remove PC from group: pc_id={pc_id}")


def test_delete_group(token):
    r = request("DELETE", f"/api/groups/{_group_id}", token=token)
    assert r.status_code == 200, f"Delete group failed: {r.status_code} {r.data}"
    print(f"  [PASS] Delete group: id={_group_id}")

    r2 = request("GET", f"/api/groups/{_group_id}", token=token)
    assert r2.status_code == 404
    print(f"  [PASS] Deleted group not found: id={_group_id}")


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
    test_pc_search_by_name(token)
    test_pc_search_by_ip(token)
    test_pc_search_no_match(token)
    test_pc_filter_by_status(token)
    test_pc_filter_by_os(token)
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
    test_user_management(token)
    test_user_management_forbidden(token)
    test_webui_pages(token)
    test_create_scheduled_task(token)
    test_list_scheduled_tasks(token)
    test_get_scheduled_task(token)
    test_update_scheduled_task(token)
    test_toggle_scheduled_task(token)
    test_run_scheduled_task_now(token)
    test_scheduled_task_invalid_payload(token)
    test_delete_scheduled_task(token)
    test_create_group(token)
    test_list_groups(token)
    test_get_group(token)
    test_update_group(token)
    test_add_pc_to_group(token)
    test_create_group_task(token)
    test_remove_pc_from_group(token)
    test_delete_group(token)

    print("\n=== All tests PASSED ===")


if __name__ == "__main__":
    run_all()

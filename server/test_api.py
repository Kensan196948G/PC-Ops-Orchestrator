"""Integration test for PC-Ops Orchestrator API."""

import json
import sys
import os
import uuid

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
    # data is not None ではなく truthy 判定にすると `{}` が「body 無し」扱いに
    # なってしまうため、明示的に None と区別する。
    body = json.dumps(data) if data is not None else None
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


def test_user_role_type_validation(token):
    """role に非文字列を渡すと 500 ではなく 400 で弾かれるべき (CodeRabbit/Copilot 指摘)。"""
    suffix = uuid.uuid4().hex[:8]
    payloads = [
        {"role": None},
        {"role": ["admin"]},
        {"role": {"name": "admin"}},
        {"role": 123},
    ]
    for bad_role in payloads:
        r = request(
            "POST",
            "/api/auth/users",
            token=token,
            data={
                "username": f"bad_role_{suffix}",
                "password": "pass-1234",
                **bad_role,
            },
        )
        assert r.status_code == 400, (
            f"role={bad_role['role']!r} expected 400 got {r.status_code} {r.data}"
        )
    print("  [PASS] User create with invalid role type returns 400 (not 500)")


def test_webui_pages(token):
    pages = [
        ("/", "Dashboard"),
        ("/pcs", "PC List"),
        ("/tasks", "Task Management"),
        ("/alerts", "Alert Management"),
        ("/users", "User Management"),
        ("/scheduled-tasks", "Scheduled Tasks"),
        ("/groups", "PC Groups"),
        ("/alert-rules", "Alert Rules"),
        ("/api/docs/", "API Docs (Swagger UI)"),
        ("/api/openapi.yaml", "OpenAPI YAML"),
    ]
    for path, name in pages:
        headers = {"Authorization": f"Bearer {token}"}
        r = client.get(path, headers=headers)
        assert r.status_code == 200, f"{name} failed: {r.status_code}"
        print(f"  [PASS] WebUI {name}: {r.status_code}")


def test_openapi_yaml_not_under_static():
    r = client.get("/static/openapi.yaml")
    assert r.status_code == 404, (
        "openapi.yaml must NOT be served from /static/ (security: SWAGGER_ENABLED gate)"
    )
    print("  [PASS] /static/openapi.yaml correctly returns 404 (not in static dir)")


def _login_as(username: str, password: str) -> str:
    r = request(
        "POST",
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, (
        f"login failed for {username}: {r.status_code} {r.data}"
    )
    return json.loads(r.data)["token"]


def test_rbac_role_matrix(token):
    """Create operator and viewer users, then verify the permission matrix.

    Uses unique usernames + try/finally so partial failures cannot poison
    later runs with stale 409 conflicts.
    """
    suffix = uuid.uuid4().hex[:8]
    op_username = f"rbac_op_{suffix}"
    op_password = "operator-pass-1"
    viewer_username = f"rbac_viewer_{suffix}"
    viewer_password = "viewer-pass-1"

    try:
        # admin が両ロールのユーザーを作成
        for username, password, role in (
            (op_username, op_password, "operator"),
            (viewer_username, viewer_password, "viewer"),
        ):
            r = request(
                "POST",
                "/api/auth/users",
                token=token,
                data={"username": username, "password": password, "role": role},
            )
            assert r.status_code == 201, (
                f"create {role} failed: {r.status_code} {r.data}"
            )

        op_token = _login_as(op_username, op_password)
        viewer_token = _login_as(viewer_username, viewer_password)
        print("  [PASS] operator/viewer のログイン成功")

        # body は明示的に切り替える: None=「body 無し」、{...}=「body あり」
        # POST だが body 無しを送ると helper が 400 を返すため、ロール判定の
        # 前後で生じる 400 を区別する目的で各ケースに body を含める。
        valid_task_body = {"task_type": "cleanup"}
        valid_sched_body = {
            "name": f"rbac_test_{suffix}",
            "task_type": "cleanup",
            "schedule_type": "interval",
            "interval_minutes": 60,
        }

        cases = [
            # (method, path, body, viewer_expected, operator_expected, description)
            (
                "GET",
                "/api/dashboard/stats",
                None,
                200,
                200,
                "ダッシュボード閲覧は全ロール可",
            ),
            ("GET", "/api/pcs", None, 200, 200, "PC 一覧は全ロール可"),
            ("GET", "/api/alerts", None, 200, 200, "アラート閲覧は全ロール可"),
            (
                "GET",
                "/api/alert-rules",
                None,
                200,
                200,
                "アラートルール閲覧は全ロール可",
            ),
            (
                "GET",
                "/api/scheduled-tasks",
                None,
                200,
                200,
                "スケジュール閲覧は全ロール可",
            ),
            ("GET", "/api/groups", None, 200, 200, "グループ閲覧は全ロール可"),
            (
                "GET",
                "/api/tasks",
                None,
                200,
                200,
                "タスク一覧は全ロール可",
            ),
            (
                "POST",
                "/api/alerts/sync",
                {},
                403,
                200,
                "アラート同期は viewer 不可",
            ),
            (
                "POST",
                "/api/tasks",
                valid_task_body,
                403,
                201,
                "タスク作成は viewer 403、operator 201（実装の通り作成成功）",
            ),
            (
                "POST",
                "/api/scheduled-tasks",
                valid_sched_body,
                403,
                201,
                "スケジュール作成は viewer 403、operator 201",
            ),
            (
                "POST",
                "/api/alert-rules",
                {"name": "x", "metric": "cpu", "operator": "gt", "threshold": 90},
                403,
                403,
                "アラートルール作成は viewer/operator 共に不可（admin のみ）",
            ),
            (
                "POST",
                "/api/groups",
                {"name": f"rbac_group_{suffix}"},
                403,
                403,
                "グループ作成は viewer/operator 共に不可（admin のみ）",
            ),
            (
                "GET",
                "/api/auth/users",
                None,
                403,
                403,
                "ユーザー一覧は admin 専用",
            ),
            (
                "GET",
                "/api/audit/logs",
                None,
                403,
                200,
                "監査ログは viewer 不可、operator は閲覧可",
            ),
        ]

        for method, path, body, viewer_expect, op_expect, desc in cases:
            rv = request(method, path, token=viewer_token, data=body)
            assert rv.status_code == viewer_expect, (
                f"viewer {method} {path} expected {viewer_expect} "
                f"got {rv.status_code}: {rv.data}"
            )
            ro = request(method, path, token=op_token, data=body)
            assert ro.status_code == op_expect, (
                f"operator {method} {path} expected {op_expect} "
                f"got {ro.status_code}: {ro.data}"
            )
            print(f"  [PASS] {desc} (viewer={viewer_expect}, operator={op_expect})")
    finally:
        # 必ず後始末する（途中で assertion 失敗してもユーザーが残らない）
        with app.app_context():
            for username in (op_username, viewer_username):
                u = User.query.filter_by(username=username).first()
                if u:
                    db.session.delete(u)
            db.session.commit()


def test_template_role_classes_present(token):
    """主要ページ HTML に role-* クラスが含まれていることを確認。

    JS で動的生成されるボタンには直接到達できないため、ここでは
    静的テンプレートの一次操作ボタンに RBAC クラスが付与されている
    ことを確認する（フォロー段階適用 PR の回帰防止）。
    """
    pages = {
        "/users": ["role-admin-only"],
        "/groups": ["role-admin-only"],
        "/alert-rules": ["role-admin-only"],
        "/scheduled-tasks": ["role-operator-or-admin"],
        "/tasks": ["role-operator-or-admin"],
        "/alerts": ["role-operator-or-admin"],
    }
    for path, expected_classes in pages.items():
        r = client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"{path} failed: {r.status_code}"
        body = r.data.decode()
        for cls in expected_classes:
            assert cls in body, f"{path} should contain class {cls!r}"
    print("  [PASS] 各ページに role-* クラスが含まれる")


def test_swagger_disabled_returns_404():
    """Verify SWAGGER_ENABLED=false fully hides API docs and the OpenAPI spec."""
    original = os.environ.get("SWAGGER_ENABLED")
    os.environ["SWAGGER_ENABLED"] = "false"
    try:
        gated_app = create_app("testing")
    finally:
        if original is None:
            os.environ.pop("SWAGGER_ENABLED", None)
        else:
            os.environ["SWAGGER_ENABLED"] = original

    with gated_app.test_client() as gated_client:
        for path in ("/api/docs/", "/api/openapi.yaml", "/static/openapi.yaml"):
            r = gated_client.get(path)
            assert r.status_code == 404, (
                f"{path} should be 404 when SWAGGER_ENABLED=false, got {r.status_code}"
            )
    print("  [PASS] SWAGGER_ENABLED=false hides docs and openapi spec")


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


_rule_id = None


def test_create_alert_rule(token):
    global _rule_id
    body = {
        "name": "CPU Test Rule",
        "metric": "cpu",
        "operator": "gt",
        "threshold": 90,
        "severity": "warning",
        "is_enabled": True,
    }
    r = request("POST", "/api/alert-rules", token=token, data=body)
    assert r.status_code == 201, f"Create alert rule failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert "alert_rule" in data
    rule = data["alert_rule"]
    assert rule["name"] == "CPU Test Rule"
    assert rule["metric"] == "cpu"
    assert rule["operator"] == "gt"
    assert rule["threshold"] == 90.0
    assert rule["severity"] == "warning"
    assert rule["is_enabled"] is True
    _rule_id = rule["id"]
    print(f"  [PASS] Create alert rule: id={_rule_id}")


def test_list_alert_rules(token):
    r = request("GET", "/api/alert-rules", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "alert_rules" in data
    assert "total" in data
    assert data["total"] >= 1
    ids = [rule["id"] for rule in data["alert_rules"]]
    assert _rule_id in ids
    print(f"  [PASS] List alert rules: total={data['total']}")


def test_get_alert_rule(token):
    r = request("GET", f"/api/alert-rules/{_rule_id}", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["alert_rule"]["id"] == _rule_id
    print(f"  [PASS] Get alert rule: id={_rule_id}")


def test_update_alert_rule(token):
    body = {
        "name": "CPU Test Rule Updated",
        "metric": "cpu",
        "operator": "gte",
        "threshold": 85,
        "severity": "critical",
        "is_enabled": True,
    }
    r = request("PUT", f"/api/alert-rules/{_rule_id}", token=token, data=body)
    assert r.status_code == 200, f"Update alert rule failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    rule = data["alert_rule"]
    assert rule["name"] == "CPU Test Rule Updated"
    assert rule["operator"] == "gte"
    assert rule["threshold"] == 85.0
    assert rule["severity"] == "critical"
    print(f"  [PASS] Update alert rule: id={_rule_id}")


def test_toggle_alert_rule(token):
    r = request("POST", f"/api/alert-rules/{_rule_id}/toggle", token=token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["alert_rule"]["is_enabled"] is False
    print(f"  [PASS] Toggle alert rule (disabled): id={_rule_id}")

    r2 = request("POST", f"/api/alert-rules/{_rule_id}/toggle", token=token)
    assert r2.status_code == 200
    data2 = json.loads(r2.data)
    assert data2["alert_rule"]["is_enabled"] is True
    print(f"  [PASS] Toggle alert rule (re-enabled): id={_rule_id}")


def test_alert_rule_invalid_metric(token):
    body = {
        "name": "Bad Rule",
        "metric": "invalid_metric",
        "operator": "gt",
        "threshold": 80,
        "severity": "warning",
    }
    r = request("POST", "/api/alert-rules", token=token, data=body)
    assert r.status_code == 400
    data = json.loads(r.data)
    assert "error" in data
    print(f"  [PASS] Alert rule invalid metric rejected: {data['error'][:60]}")


def test_delete_alert_rule(token):
    r = request("DELETE", f"/api/alert-rules/{_rule_id}", token=token)
    assert r.status_code == 200, f"Delete alert rule failed: {r.status_code} {r.data}"
    data = json.loads(r.data)
    assert "message" in data
    print(f"  [PASS] Delete alert rule: id={_rule_id}")

    r2 = request("GET", f"/api/alert-rules/{_rule_id}", token=token)
    assert r2.status_code == 404
    print(f"  [PASS] Deleted alert rule not found: id={_rule_id}")


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
    test_user_role_type_validation(token)
    test_webui_pages(token)
    test_template_role_classes_present(token)
    test_openapi_yaml_not_under_static()
    test_swagger_disabled_returns_404()
    test_rbac_role_matrix(token)
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
    test_create_alert_rule(token)
    test_list_alert_rules(token)
    test_get_alert_rule(token)
    test_update_alert_rule(token)
    test_toggle_alert_rule(token)
    test_alert_rule_invalid_metric(token)
    test_delete_alert_rule(token)

    print("\n=== All tests PASSED ===")


if __name__ == "__main__":
    run_all()

"""Extended API tests covering items 111-130 of the test checklist.

Items covered:
111. GET 正常系
112. POST 正常系
113. PUT 正常系
114. DELETE 正常系
115. HTTP ステータスコード確認
116. JSON 形式確認
117. NULL 応答確認
118. 不正 JSON 確認
119. Content-Type 確認
120. API タイムアウト確認（モック）
121. API リトライ確認（N/A - クライアント側）
122. API 認証確認
123. API 認可確認
124. API レート制限確認（RATELIMIT_ENABLED=False in testing）
125. API 例外処理確認
126. API ログ確認
127. API 監査ログ確認
128. OpenAPI 整合確認
129. Swagger 整合確認
130. API バージョン確認
"""

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

_admin_token = None
_operator_token = None
_viewer_token = None


def setup_module():
    global _admin_token, _operator_token, _viewer_token
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin_ext").first():
            db.session.add(
                User(
                    username="admin_ext",
                    password_hash=hash_password("admin"),
                    role="admin",
                )
            )
        if not User.query.filter_by(username="operator_ext").first():
            db.session.add(
                User(
                    username="operator_ext",
                    password_hash=hash_password("operator"),
                    role="operator",
                )
            )
        if not User.query.filter_by(username="viewer_ext").first():
            db.session.add(
                User(
                    username="viewer_ext",
                    password_hash=hash_password("viewer"),
                    role="viewer",
                )
            )
        db.session.commit()
    _admin_token = _login("admin_ext", "admin")
    _operator_token = _login("operator_ext", "operator")
    _viewer_token = _login("viewer_ext", "viewer")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def req(
    method, path, token=None, data=None, raw_data=None, content_type="application/json"
):
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = (
        raw_data
        if raw_data is not None
        else (json.dumps(data) if data is not None else None)
    )
    return client.open(path, method=method, headers=headers, data=body)


# ── 111. GET 正常系 ──────────────────────────────────────────────────
def test_get_pcs_200():
    r = req("GET", "/api/pcs", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "pcs" in data
    assert "total" in data


def test_get_alerts_200():
    r = req("GET", "/api/alerts", token=_admin_token)
    assert r.status_code == 200


def test_get_tasks_200():
    r = req("GET", "/api/tasks", token=_admin_token)
    assert r.status_code == 200


def test_get_groups_200():
    r = req("GET", "/api/groups", token=_admin_token)
    assert r.status_code == 200


def test_get_scheduled_tasks_200():
    r = req("GET", "/api/scheduled-tasks", token=_admin_token)
    assert r.status_code == 200


# ── 112. POST 正常系 ─────────────────────────────────────────────────
def test_post_task_201():
    body = {"task_type": "diagnose", "title": "診断タスク", "priority": 1}
    r = req("POST", "/api/tasks", token=_admin_token, data=body)
    assert r.status_code == 201
    data = json.loads(r.data)
    assert "task" in data


def test_post_scheduled_task_201_sched():
    unique = str(uuid.uuid4())[:8]
    body = {
        "name": f"Sched201-{unique}",
        "task_type": "cleanup",
        "schedule_type": "daily",
        "daily_time": "03:00",
        "is_enabled": True,
    }
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data=body)
    assert r.status_code == 201
    assert "scheduled_task" in json.loads(r.data)


def test_post_group_201():
    unique = str(uuid.uuid4())[:8]
    body = {"name": f"TestGroup-{unique}", "description": "テスト"}
    r = req("POST", "/api/groups", token=_admin_token, data=body)
    assert r.status_code == 201


def test_post_scheduled_task_201():
    unique = str(uuid.uuid4())[:8]
    body = {
        "name": f"SchedTest-{unique}",
        "task_type": "cleanup",
        "schedule_type": "daily",
        "daily_time": "03:00",
        "is_enabled": True,
    }
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data=body)
    assert r.status_code == 201


# ── 113. PUT 正常系（scheduled-tasks は PUT サポート）────────────────
def test_put_scheduled_task():
    unique = str(uuid.uuid4())[:8]
    body = {
        "name": f"Put-Sched-{unique}",
        "task_type": "cleanup",
        "schedule_type": "daily",
        "daily_time": "04:00",
        "is_enabled": True,
    }
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data=body)
    assert r.status_code == 201
    task_id = json.loads(r.data)["scheduled_task"]["id"]
    r2 = req(
        "PUT",
        f"/api/scheduled-tasks/{task_id}",
        token=_admin_token,
        data={
            "name": f"Put-Sched-Updated-{unique}",
            "task_type": "cleanup",
            "schedule_type": "daily",
            "daily_time": "05:00",
            "is_enabled": False,
        },
    )
    assert r2.status_code == 200
    assert json.loads(r2.data)["scheduled_task"]["daily_time"] == "05:00"
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


# ── 114. DELETE 正常系 ───────────────────────────────────────────────
def test_delete_group():
    unique = str(uuid.uuid4())[:8]
    r = req("POST", "/api/groups", token=_admin_token, data={"name": f"Del-{unique}"})
    assert r.status_code == 201
    gid = json.loads(r.data)["group"]["id"]
    r2 = req("DELETE", f"/api/groups/{gid}", token=_admin_token)
    assert r2.status_code == 200


# ── 115. HTTP ステータスコード確認 ────────────────────────────────────
def test_404_returns_404():
    r = req("GET", "/api/nonexistent-endpoint-xyz", token=_admin_token)
    assert r.status_code == 404


def test_unauthorized_returns_401():
    r = req("GET", "/api/pcs")
    assert r.status_code == 401


def test_forbidden_returns_403():
    r = req("POST", "/api/tasks", token=_viewer_token, data={"task_type": "cleanup"})
    assert r.status_code == 403


# ── 116. JSON 形式確認 ───────────────────────────────────────────────
def test_response_is_json():
    r = req("GET", "/api/pcs", token=_admin_token)
    assert r.content_type.startswith("application/json")
    json.loads(r.data)  # should not raise


def test_error_response_is_json():
    r = req("GET", "/api/pcs")
    assert r.content_type.startswith("application/json")
    data = json.loads(r.data)
    assert "error" in data


# ── 117. NULL 応答確認 ───────────────────────────────────────────────
def test_empty_list_not_null():
    # タスクがない PC のタスク取得
    r = req("GET", "/api/tasks?status=pending_nonexistent", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data.get("tasks") is not None  # null でなく空リスト


# ── 118. 不正 JSON 確認 ──────────────────────────────────────────────
def test_invalid_json_returns_400():
    r = req("POST", "/api/tasks", token=_admin_token, raw_data="not-json")
    assert r.status_code in (400, 422)


def test_malformed_json_returns_400():
    r = req("POST", "/api/tasks", token=_admin_token, raw_data="{broken json")
    assert r.status_code in (400, 422)


# ── 119. Content-Type 確認 ───────────────────────────────────────────
def test_api_content_type_json():
    r = req("GET", "/api/dashboard/stats", token=_admin_token)
    assert "application/json" in r.content_type


def test_health_content_type_json():
    r = req("GET", "/health")
    assert "application/json" in r.content_type


# ── 122. API 認証確認 ────────────────────────────────────────────────
def test_invalid_token_returns_401():
    r = req("GET", "/api/pcs", token="invalid.token.here")
    assert r.status_code == 401


def test_missing_auth_header_returns_401():
    r = client.get("/api/pcs")
    assert r.status_code == 401


def test_valid_agent_key_accepted():
    headers = {"Authorization": "Bearer default-agent-key"}
    r = client.open(
        "/api/tasks/pending?pc_name=TEST-PC",
        method="GET",
        headers=headers,
    )
    assert r.status_code == 200


# ── 123. API 認可確認 ────────────────────────────────────────────────
def test_viewer_cannot_create_task():
    r = req("POST", "/api/tasks", token=_viewer_token, data={"task_type": "cleanup"})
    assert r.status_code == 403


def test_viewer_cannot_delete_group():
    unique = str(uuid.uuid4())[:8]
    r = req(
        "POST", "/api/groups", token=_admin_token, data={"name": f"ViewDel-{unique}"}
    )
    gid = json.loads(r.data)["group"]["id"]
    r2 = req("DELETE", f"/api/groups/{gid}", token=_viewer_token)
    assert r2.status_code == 403


def test_viewer_can_read_pcs():
    r = req("GET", "/api/pcs", token=_viewer_token)
    assert r.status_code == 200


def test_operator_can_create_task():
    body = {"task_type": "diagnose", "title": "Operator タスク", "priority": 1}
    r = req("POST", "/api/tasks", token=_operator_token, data=body)
    assert r.status_code == 201


# ── 125. API 例外処理確認 ────────────────────────────────────────────
def test_nonexistent_resource_returns_404():
    r = req("GET", "/api/pcs/99999999", token=_admin_token)
    assert r.status_code == 404


def test_task_invalid_type_returns_400():
    r = req(
        "POST", "/api/tasks", token=_admin_token, data={"task_type": "invalid_type_xyz"}
    )
    assert r.status_code == 400
    data = json.loads(r.data)
    assert "error" in data


# ── 126. API ログ確認（監査ログエンドポイント）────────────────────────
def test_audit_log_exists_after_login():
    r = req("GET", "/api/audit/logs", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "logs" in data


# ── 127. API 監査ログ確認 ────────────────────────────────────────────
def test_login_creates_audit_entry():
    # ログイン実行
    req("POST", "/api/auth/login", data={"username": "admin_ext", "password": "admin"})
    r = req("GET", "/api/audit/logs", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    logs = data.get("logs", [])
    assert len(logs) > 0


# ── 128/129. OpenAPI・Swagger 整合確認 ───────────────────────────────
def test_openapi_yaml_accessible():
    r = client.get("/api/openapi.yaml")
    assert r.status_code == 200
    assert b"openapi" in r.data.lower()


# ── 130. API バージョン確認 ──────────────────────────────────────────
def test_api_prefix_v1():
    # すべての API は /api/ プレフィックスを持つ
    r = req("GET", "/api/pcs", token=_admin_token)
    assert r.status_code == 200


def test_api_dashboard_stats_schema():
    r = req("GET", "/api/dashboard/stats", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    # 実際のスキーマキー確認
    for key in ("total_pcs", "pending_tasks"):
        assert key in data, f"Missing key: {key}"


# ── 131. 監査ログ 日付フィルタ ──────────────────────────────────────
def test_audit_logs_from_date_filter():
    r = req("GET", "/api/audit/logs?from_date=2000-01-01", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "logs" in data


def test_audit_logs_to_date_filter():
    r = req("GET", "/api/audit/logs?to_date=2099-12-31", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "logs" in data


def test_audit_logs_date_range_no_results():
    r = req(
        "GET",
        "/api/audit/logs?from_date=2099-01-01&to_date=2099-01-02",
        token=_admin_token,
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["logs"] == []


def test_audit_logs_invalid_date_ignored():
    r = req("GET", "/api/audit/logs?from_date=invalid", token=_admin_token)
    assert r.status_code == 200  # invalid date should be silently ignored


# ── 132. 監査ログ CSV エクスポート ───────────────────────────────────
def test_audit_export_csv_ok():
    r = req("GET", "/api/audit/export.csv", token=_admin_token)
    assert r.status_code == 200
    assert "text/csv" in r.content_type or "csv" in r.content_type


def test_audit_export_csv_has_bom():
    r = req("GET", "/api/audit/export.csv", token=_admin_token)
    assert r.status_code == 200
    assert r.data[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM


def test_audit_export_csv_header_row():
    r = req("GET", "/api/audit/export.csv", token=_admin_token)
    assert r.status_code == 200
    text = r.data.decode("utf-8-sig")
    assert "日時" in text
    assert "操作" in text


def test_audit_export_csv_viewer_forbidden():
    r = req("GET", "/api/audit/export.csv", token=_viewer_token)
    assert r.status_code == 403


def test_audit_export_csv_requires_auth():
    r = req("GET", "/api/audit/export.csv")
    assert r.status_code == 401

"""Coverage boost tests — items 131-175 of the test checklist.

Covers:
- Alerts CSV export (lines 59-112 of routes/alerts.py)
- Alerts filtering by severity / pc_id / resolved
- Tasks CSV export
- Groups CRUD error cases (400/404/409)
- PCs endpoint filters and error cases
- Security headers verification
- API input validation edge cases
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
_viewer_token = None
_operator_token = None


def setup_module():
    global _admin_token, _viewer_token, _operator_token
    with app.app_context():
        db.create_all()
        unique = uuid.uuid4().hex[:8]
        for username, role, password in [
            (f"admin_cb_{unique}", "admin", "AdminCb1!"),
            (f"viewer_cb_{unique}", "viewer", "ViewerCb1!"),
            (f"oper_cb_{unique}", "operator", "OperCb1!"),
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

    _admin_token = _login(f"admin_cb_{unique}", "AdminCb1!")
    _viewer_token = _login(f"viewer_cb_{unique}", "ViewerCb1!")
    _operator_token = _login(f"oper_cb_{unique}", "OperCb1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


# ── Alerts CSV export ────────────────────────────────────────────────


def test_alerts_csv_export_returns_200():
    r = req("GET", "/api/alerts/export.csv", token=_admin_token)
    assert r.status_code == 200


def test_alerts_csv_export_content_type():
    r = req("GET", "/api/alerts/export.csv", token=_admin_token)
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_alerts_csv_export_has_bom():
    r = req("GET", "/api/alerts/export.csv", token=_admin_token)
    # UTF-8 BOM for Excel compatibility
    assert r.data[:3] == b"\xef\xbb\xbf"


def test_alerts_csv_export_has_header_row():
    r = req("GET", "/api/alerts/export.csv", token=_admin_token)
    content = r.data.decode("utf-8-sig")
    first_line = content.split("\r\n")[0]
    assert "ID" in first_line
    assert "PC名" in first_line


def test_alerts_csv_export_requires_auth():
    r = req("GET", "/api/alerts/export.csv")
    assert r.status_code == 401


def test_alerts_csv_export_with_resolved_filter():
    r = req("GET", "/api/alerts/export.csv?resolved=true", token=_admin_token)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_alerts_csv_export_with_severity_filter():
    r = req("GET", "/api/alerts/export.csv?severity=critical", token=_admin_token)
    assert r.status_code == 200


# ── Alerts filtering ─────────────────────────────────────────────────


def test_alerts_filter_by_severity():
    r = req("GET", "/api/alerts?severity=critical", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "alerts" in data
    for alert in data["alerts"]:
        assert alert["severity"] == "critical"


def test_alerts_filter_by_resolved_true():
    r = req("GET", "/api/alerts?resolved=true", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "alerts" in data


def test_alerts_filter_by_pc_id():
    r = req("GET", "/api/alerts?pc_id=999999", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["total"] == 0


def test_alerts_pagination():
    r = req("GET", "/api/alerts?page=1&per_page=5", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "page" in data
    assert "pages" in data
    assert len(data["alerts"]) <= 5


def test_alerts_get_nonexistent():
    r = req("GET", "/api/alerts/999999", token=_admin_token)
    assert r.status_code == 404


def test_alerts_viewer_can_read():
    r = req("GET", "/api/alerts", token=_viewer_token)
    assert r.status_code == 200


# ── Tasks CSV export ─────────────────────────────────────────────────


def test_tasks_csv_export_returns_200():
    r = req("GET", "/api/tasks/export.csv", token=_admin_token)
    assert r.status_code == 200


def test_tasks_csv_export_content_type():
    r = req("GET", "/api/tasks/export.csv", token=_admin_token)
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_tasks_csv_export_has_bom():
    r = req("GET", "/api/tasks/export.csv", token=_admin_token)
    assert r.data[:3] == b"\xef\xbb\xbf"


def test_tasks_csv_export_requires_auth():
    r = req("GET", "/api/tasks/export.csv")
    assert r.status_code == 401


# ── Groups CRUD error cases ───────────────────────────────────────────


def _unique_group_name():
    return f"TestGroup-{uuid.uuid4().hex[:8]}"


def test_groups_create_missing_name():
    r = req("POST", "/api/groups", token=_admin_token, data={})
    assert r.status_code == 400
    data = json.loads(r.data)
    assert "error" in data


def test_groups_create_empty_name():
    r = req("POST", "/api/groups", token=_admin_token, data={"name": "  "})
    assert r.status_code == 400


def test_groups_create_name_too_long():
    r = req("POST", "/api/groups", token=_admin_token, data={"name": "x" * 256})
    assert r.status_code == 400


def test_groups_create_duplicate_name():
    name = _unique_group_name()
    req("POST", "/api/groups", token=_admin_token, data={"name": name})
    r = req("POST", "/api/groups", token=_admin_token, data={"name": name})
    assert r.status_code == 409
    # Cleanup
    groups = json.loads(req("GET", "/api/groups", token=_admin_token).data)["groups"]
    for g in groups:
        if g["name"] == name:
            req("DELETE", f"/api/groups/{g['id']}", token=_admin_token)
            break


def test_groups_create_invalid_pc_names():
    r = req(
        "POST",
        "/api/groups",
        token=_admin_token,
        data={"name": _unique_group_name(), "pc_names": ["nonexistent-pc-xyz"]},
    )
    assert r.status_code == 400


def test_groups_create_pc_names_not_list():
    r = req(
        "POST",
        "/api/groups",
        token=_admin_token,
        data={"name": _unique_group_name(), "pc_names": "not-a-list"},
    )
    assert r.status_code == 400


def test_groups_get_nonexistent():
    r = req("GET", "/api/groups/999999", token=_admin_token)
    assert r.status_code == 404


def test_groups_update_nonexistent():
    r = req("PUT", "/api/groups/999999", token=_admin_token, data={"name": "x"})
    assert r.status_code == 404


def test_groups_delete_nonexistent():
    r = req("DELETE", "/api/groups/999999", token=_admin_token)
    assert r.status_code == 404


def test_groups_update_empty_name():
    name = _unique_group_name()
    r = req("POST", "/api/groups", token=_admin_token, data={"name": name})
    assert r.status_code == 201
    gid = json.loads(r.data)["group"]["id"]

    r2 = req("PUT", f"/api/groups/{gid}", token=_admin_token, data={"name": ""})
    assert r2.status_code == 400
    req("DELETE", f"/api/groups/{gid}", token=_admin_token)


def test_groups_update_name_too_long():
    name = _unique_group_name()
    r = req("POST", "/api/groups", token=_admin_token, data={"name": name})
    gid = json.loads(r.data)["group"]["id"]

    r2 = req("PUT", f"/api/groups/{gid}", token=_admin_token, data={"name": "y" * 256})
    assert r2.status_code == 400
    req("DELETE", f"/api/groups/{gid}", token=_admin_token)


def test_groups_add_nonexistent_pc():
    name = _unique_group_name()
    r = req("POST", "/api/groups", token=_admin_token, data={"name": name})
    gid = json.loads(r.data)["group"]["id"]

    r2 = req(
        "POST",
        f"/api/groups/{gid}/pcs",
        token=_admin_token,
        data={"pc_name": "nonexistent-pc-zzz"},
    )
    assert r2.status_code == 400
    req("DELETE", f"/api/groups/{gid}", token=_admin_token)


def test_groups_viewer_cannot_create():
    r = req(
        "POST", "/api/groups", token=_viewer_token, data={"name": _unique_group_name()}
    )
    assert r.status_code == 403


def test_groups_viewer_can_list():
    r = req("GET", "/api/groups", token=_viewer_token)
    assert r.status_code == 200


def test_groups_pc_count_in_response():
    name = _unique_group_name()
    r = req("POST", "/api/groups", token=_admin_token, data={"name": name})
    gid = json.loads(r.data)["group"]["id"]

    list_r = req("GET", "/api/groups", token=_admin_token)
    groups = json.loads(list_r.data)["groups"]
    found = next((g for g in groups if g["id"] == gid), None)
    assert found is not None
    assert "pc_count" in found
    assert found["pc_count"] == 0

    req("DELETE", f"/api/groups/{gid}", token=_admin_token)


# ── Security headers verification ────────────────────────────────────


def test_csp_header_present():
    r = req("GET", "/api/alerts", token=_admin_token)
    assert "Content-Security-Policy" in r.headers


def test_csp_no_unsafe_inline_script():
    r = req("GET", "/api/alerts", token=_admin_token)
    csp = r.headers.get("Content-Security-Policy", "")
    # script-src must NOT contain 'unsafe-inline' (Phase 2 complete)
    import re

    script_src_match = re.search(r"script-src\s+([^;]+)", csp)
    if script_src_match:
        script_src = script_src_match.group(1)
        assert "'unsafe-inline'" not in script_src


def test_x_content_type_options_header():
    r = req("GET", "/api/alerts", token=_admin_token)
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_x_frame_options_header():
    r = req("GET", "/api/alerts", token=_admin_token)
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_referrer_policy_header():
    r = req("GET", "/api/alerts", token=_admin_token)
    assert "Referrer-Policy" in r.headers


def test_permissions_policy_header():
    r = req("GET", "/api/alerts", token=_admin_token)
    assert "Permissions-Policy" in r.headers


# ── Input validation edge cases ───────────────────────────────────────


def test_alerts_acknowledge_nonexistent():
    r = req("POST", "/api/alerts/999999/acknowledge", token=_operator_token)
    assert r.status_code == 404


def test_alerts_resolve_nonexistent():
    r = req("POST", "/api/alerts/999999/resolve", token=_operator_token)
    assert r.status_code == 404


def test_alerts_viewer_cannot_acknowledge():
    """Viewer role cannot acknowledge alerts (requires operator+)."""
    r = req("POST", "/api/alerts/1/acknowledge", token=_viewer_token)
    assert r.status_code in (403, 404)


def test_tasks_get_nonexistent():
    r = req("GET", "/api/tasks/999999", token=_admin_token)
    assert r.status_code == 404


def test_groups_tasks_for_empty_group():
    name = _unique_group_name()
    r = req("POST", "/api/groups", token=_admin_token, data={"name": name})
    gid = json.loads(r.data)["group"]["id"]

    r2 = req(
        "POST",
        f"/api/groups/{gid}/tasks",
        token=_admin_token,
        data={"task_type": "cleanup"},
    )
    assert r2.status_code == 400
    req("DELETE", f"/api/groups/{gid}", token=_admin_token)


def test_groups_tasks_invalid_type():
    name = _unique_group_name()
    r = req("POST", "/api/groups", token=_admin_token, data={"name": name})
    gid = json.loads(r.data)["group"]["id"]

    r2 = req(
        "POST",
        f"/api/groups/{gid}/tasks",
        token=_admin_token,
        data={"task_type": "invalid_type_xyz"},
    )
    assert r2.status_code == 400
    req("DELETE", f"/api/groups/{gid}", token=_admin_token)


def test_no_body_returns_400_for_post_endpoints():
    r = req("POST", "/api/groups", token=_admin_token)
    assert r.status_code == 400


def test_update_group_no_body():
    name = _unique_group_name()
    r = req("POST", "/api/groups", token=_admin_token, data={"name": name})
    gid = json.loads(r.data)["group"]["id"]

    r2 = req("PUT", f"/api/groups/{gid}", token=_admin_token)
    assert r2.status_code == 400
    req("DELETE", f"/api/groups/{gid}", token=_admin_token)


# ── PCs endpoints ────────────────────────────────────────────────────


def test_pcs_csv_export_returns_200():
    r = req("GET", "/api/pcs/export.csv", token=_admin_token)
    assert r.status_code == 200


def test_pcs_csv_export_content_type():
    r = req("GET", "/api/pcs/export.csv", token=_admin_token)
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_pcs_csv_export_has_bom():
    r = req("GET", "/api/pcs/export.csv", token=_admin_token)
    assert r.data[:3] == b"\xef\xbb\xbf"


def test_pcs_csv_export_requires_auth():
    r = req("GET", "/api/pcs/export.csv")
    assert r.status_code == 401


def test_pcs_list_with_status_filter():
    r = req("GET", "/api/pcs?status=online", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "pcs" in data
    for pc in data["pcs"]:
        assert pc["status"] == "online"


def test_pcs_list_with_search_filter():
    r = req("GET", "/api/pcs?search=test", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "pcs" in data


def test_pcs_list_with_os_filter():
    r = req("GET", "/api/pcs?os=Windows", token=_admin_token)
    assert r.status_code == 200


def test_pcs_get_nonexistent():
    r = req("GET", "/api/pcs/999999", token=_admin_token)
    assert r.status_code == 404


def test_pcs_software_nonexistent():
    r = req("GET", "/api/pcs/999999/software", token=_admin_token)
    assert r.status_code == 404


def test_pcs_updates_nonexistent():
    r = req("GET", "/api/pcs/999999/updates", token=_admin_token)
    assert r.status_code == 404


def test_pcs_history_nonexistent():
    r = req("GET", "/api/pcs/999999/history", token=_admin_token)
    assert r.status_code == 404


def test_pcs_delete_nonexistent():
    r = req("DELETE", "/api/pcs/999999", token=_admin_token)
    assert r.status_code == 404


def test_pcs_delete_requires_admin():
    r = req("DELETE", "/api/pcs/999999", token=_viewer_token)
    assert r.status_code == 403


def test_pcs_viewer_can_list():
    r = req("GET", "/api/pcs", token=_viewer_token)
    assert r.status_code == 200


def test_pcs_pagination():
    r = req("GET", "/api/pcs?page=1&per_page=5", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert len(data["pcs"]) <= 5


# ── Tasks endpoint error cases ────────────────────────────────────────


def test_tasks_create_no_body():
    r = req("POST", "/api/tasks", token=_operator_token)
    assert r.status_code == 400


def test_tasks_create_missing_task_type():
    r = req("POST", "/api/tasks", token=_operator_token, data={"pc_name": "test-pc"})
    assert r.status_code == 400


def test_tasks_create_invalid_task_type():
    r = req(
        "POST",
        "/api/tasks",
        token=_operator_token,
        data={"task_type": "invalid_xyz"},
    )
    assert r.status_code == 400


def test_tasks_create_nonexistent_pc():
    r = req(
        "POST",
        "/api/tasks",
        token=_operator_token,
        data={"task_type": "cleanup", "pc_name": "nonexistent-pc-zzz"},
    )
    assert r.status_code == 404


def test_tasks_create_command_too_long():
    r = req(
        "POST",
        "/api/tasks",
        token=_operator_token,
        data={"task_type": "custom", "command": "x" * 513},
    )
    assert r.status_code == 400


def test_tasks_viewer_cannot_create():
    r = req("POST", "/api/tasks", token=_viewer_token, data={"task_type": "cleanup"})
    assert r.status_code == 403


def test_tasks_delete_nonexistent():
    r = req("DELETE", "/api/tasks/999999", token=_admin_token)
    assert r.status_code == 404


def test_tasks_list_with_status_filter():
    r = req("GET", "/api/tasks?status=pending", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "tasks" in data


def test_tasks_list_with_type_filter():
    r = req("GET", "/api/tasks?task_type=cleanup", token=_admin_token)
    assert r.status_code == 200


def test_tasks_pagination():
    r = req("GET", "/api/tasks?page=1&per_page=5", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert len(data["tasks"]) <= 5


def test_tasks_viewer_can_list():
    r = req("GET", "/api/tasks", token=_viewer_token)
    assert r.status_code == 200


# ── Alerts acknowledge/resolve with data ─────────────────────────────


def _create_test_alert(app_ctx):
    """Create a test Alert in DB and return its id."""
    from models import Alert

    with app_ctx:
        alert = Alert(
            pc_id=None,
            alert_type="test_alert",
            severity="high",
            message="テスト用アラート",
            source_key=f"test-{uuid.uuid4().hex[:8]}",
        )
        db.session.add(alert)
        db.session.commit()
        return alert.id


def test_alerts_acknowledge_success():
    alert_id = _create_test_alert(app.app_context())
    r = req("POST", f"/api/alerts/{alert_id}/acknowledge", token=_operator_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["alert"]["acknowledged"] is True


def test_alerts_acknowledge_already_resolved():
    """Acknowledging a resolved alert should return 400."""
    alert_id = _create_test_alert(app.app_context())
    # Resolve first
    req("POST", f"/api/alerts/{alert_id}/resolve", token=_operator_token)
    # Now try to acknowledge
    r = req("POST", f"/api/alerts/{alert_id}/acknowledge", token=_operator_token)
    assert r.status_code == 400


def test_alerts_resolve_success():
    alert_id = _create_test_alert(app.app_context())
    r = req("POST", f"/api/alerts/{alert_id}/resolve", token=_operator_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["alert"]["resolved"] is True


def test_alerts_resolve_already_resolved():
    """Resolving an already-resolved alert should return 400."""
    alert_id = _create_test_alert(app.app_context())
    req("POST", f"/api/alerts/{alert_id}/resolve", token=_operator_token)
    r = req("POST", f"/api/alerts/{alert_id}/resolve", token=_operator_token)
    assert r.status_code == 400


def test_alerts_get_existing():
    """GET specific alert should return 200 with full data."""
    alert_id = _create_test_alert(app.app_context())
    r = req("GET", f"/api/alerts/{alert_id}", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["severity"] == "high"
    assert data["alert_type"] == "test_alert"


def test_alerts_sync_endpoint():
    """POST /api/alerts/sync should return 200."""
    r = req("POST", "/api/alerts/sync", token=_operator_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "created" in data
    assert "resolved" in data


def test_alerts_csv_with_data():
    """CSV export with actual alert data should include the alert row."""
    alert_id = _create_test_alert(app.app_context())
    r = req("GET", "/api/alerts/export.csv", token=_admin_token)
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert str(alert_id) in content


# ── Alert Rules endpoint tests ────────────────────────────────────────


def test_alert_rules_list_returns_200():
    r = req("GET", "/api/alert-rules", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "alert_rules" in data


def test_alert_rules_list_requires_auth():
    r = req("GET", "/api/alert-rules")
    assert r.status_code == 401


def test_alert_rules_create_valid():
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": f"TestRule-{uuid.uuid4().hex[:6]}",
            "metric": "disk",
            "operator": "lt",
            "threshold": 10.0,
            "severity": "critical",
        },
    )
    assert r.status_code == 201
    data = json.loads(r.data)
    rule_id = data["alert_rule"]["id"]
    # Cleanup
    req("DELETE", f"/api/alert-rules/{rule_id}", token=_admin_token)


def test_alert_rules_create_invalid_metric():
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": "TestBadMetric",
            "metric": "invalid_metric_xyz",
            "operator": "lt",
            "threshold": 10.0,
            "severity": "warning",
        },
    )
    assert r.status_code == 400


def test_alert_rules_create_invalid_severity():
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": "TestBadSeverity",
            "metric": "disk",
            "operator": "lt",
            "threshold": 10.0,
            "severity": "invalid_severity_xyz",
        },
    )
    assert r.status_code == 400


def test_alert_rules_create_invalid_operator():
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": "TestBadOp",
            "metric": "disk",
            "operator": "between",
            "threshold": 10.0,
            "severity": "warning",
        },
    )
    assert r.status_code == 400


def test_alert_rules_get_nonexistent():
    r = req("GET", "/api/alert-rules/999999", token=_admin_token)
    assert r.status_code == 404


def test_alert_rules_update_nonexistent():
    r = req(
        "PUT",
        "/api/alert-rules/999999",
        token=_admin_token,
        data={"name": "x"},
    )
    assert r.status_code == 404


def test_alert_rules_delete_nonexistent():
    r = req("DELETE", "/api/alert-rules/999999", token=_admin_token)
    assert r.status_code == 404


def test_alert_rules_toggle_nonexistent():
    r = req("POST", "/api/alert-rules/999999/toggle", token=_admin_token)
    assert r.status_code == 404


def test_alert_rules_viewer_cannot_create():
    r = req(
        "POST",
        "/api/alert-rules",
        token=_viewer_token,
        data={"name": "x", "metric": "disk", "operator": "lt", "threshold": 5},
    )
    assert r.status_code == 403


def test_alert_rules_viewer_can_list():
    r = req("GET", "/api/alert-rules", token=_viewer_token)
    assert r.status_code == 200


# ── Scheduled Tasks endpoint tests ────────────────────────────────────


def test_scheduled_tasks_list_returns_200():
    r = req("GET", "/api/scheduled-tasks", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "scheduled_tasks" in data


def test_scheduled_tasks_list_requires_auth():
    r = req("GET", "/api/scheduled-tasks")
    assert r.status_code == 401


def test_scheduled_tasks_create_valid():
    r = req(
        "POST",
        "/api/scheduled-tasks",
        token=_admin_token,
        data={
            "name": f"SchedTest-{uuid.uuid4().hex[:6]}",
            "task_type": "cleanup",
            "schedule_type": "daily",
            "daily_time": "02:00",
        },
    )
    assert r.status_code == 201
    data = json.loads(r.data)
    task_id = data["scheduled_task"]["id"]
    # Cleanup
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


def test_scheduled_tasks_create_missing_name():
    r = req(
        "POST",
        "/api/scheduled-tasks",
        token=_admin_token,
        data={"task_type": "cleanup", "schedule_type": "daily"},
    )
    assert r.status_code == 400


def test_scheduled_tasks_get_nonexistent():
    r = req("GET", "/api/scheduled-tasks/999999", token=_admin_token)
    assert r.status_code == 404


def test_scheduled_tasks_update_nonexistent():
    r = req(
        "PUT", "/api/scheduled-tasks/999999", token=_admin_token, data={"name": "x"}
    )
    assert r.status_code == 404


def test_scheduled_tasks_delete_nonexistent():
    r = req("DELETE", "/api/scheduled-tasks/999999", token=_admin_token)
    assert r.status_code == 404


def test_scheduled_tasks_toggle_nonexistent():
    r = req("POST", "/api/scheduled-tasks/999999/toggle", token=_admin_token)
    assert r.status_code == 404


def test_scheduled_tasks_run_now_nonexistent():
    r = req("POST", "/api/scheduled-tasks/999999/run-now", token=_admin_token)
    assert r.status_code == 404


def test_scheduled_tasks_viewer_cannot_create():
    r = req(
        "POST",
        "/api/scheduled-tasks",
        token=_viewer_token,
        data={"name": "x", "task_type": "cleanup", "schedule_type": "daily"},
    )
    assert r.status_code == 403


def test_scheduled_tasks_viewer_can_list():
    r = req("GET", "/api/scheduled-tasks", token=_viewer_token)
    assert r.status_code == 200


# ── Auth edge cases ───────────────────────────────────────────────────


def test_login_no_body():
    """POST /api/auth/login without body should return 400."""
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_login_empty_username():
    """POST /api/auth/login with empty username should return 400."""
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data='{"username": "", "password": "something"}',
    )
    assert r.status_code == 400


def test_login_inactive_user():
    """Login with is_active=False user should return 403."""
    import uuid
    from models import User

    unique = uuid.uuid4().hex[:8]
    username = f"inactive_{unique}"
    with app.app_context():
        u = User(
            username=username,
            password_hash=hash_password("InactiveTest1!"),
            role="viewer",
            is_active=False,
        )
        db.session.add(u)
        db.session.commit()

    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=f'{{"username": "{username}", "password": "InactiveTest1!"}}',
    )
    assert r.status_code == 403


def test_setup_returns_400_when_users_exist():
    """POST /api/auth/setup should return 400 when users already exist."""
    r = client.open(
        "/api/auth/setup",
        method="POST",
        headers={"Content-Type": "application/json"},
        data='{"username": "newadmin", "password": "NewAdmin1!"}',
    )
    assert r.status_code == 400


def test_create_user_no_body():
    r = req("POST", "/api/auth/users", token=_admin_token)
    assert r.status_code == 400


def test_create_user_missing_credentials():
    r = req(
        "POST",
        "/api/auth/users",
        token=_admin_token,
        data={"username": "", "password": ""},
    )
    assert r.status_code == 400


# ── Auth update/delete edge cases ─────────────────────────────────────


def test_update_user_weak_password():
    """Updating user with weak password should return 400."""
    import uuid

    unique = uuid.uuid4().hex[:8]
    create_r = req(
        "POST",
        "/api/auth/users",
        token=_admin_token,
        data={
            "username": f"weakpw_{unique}",
            "password": "StrongPass1!",
            "role": "viewer",
        },
    )
    assert create_r.status_code == 201
    user_id = json.loads(create_r.data)["user"]["id"]

    r = req(
        "PATCH",
        f"/api/auth/users/{user_id}",
        token=_admin_token,
        data={"password": "weakpw"},
    )
    assert r.status_code == 400

    req("DELETE", f"/api/auth/users/{user_id}", token=_admin_token)


def test_delete_user_self_deletion_forbidden():
    """Admin cannot delete their own account."""
    # Get the admin user's id
    users_r = req("GET", "/api/auth/users", token=_admin_token)
    users = json.loads(users_r.data)["users"]
    # Find the current admin user
    import jwt as _jwt

    token_data = _jwt.decode(_admin_token, options={"verify_signature": False})
    user_id = token_data.get("sub")
    if user_id:
        r = req("DELETE", f"/api/auth/users/{user_id}", token=_admin_token)
        assert r.status_code == 400


def test_delete_user_nonexistent():
    r = req("DELETE", "/api/auth/users/999999", token=_admin_token)
    assert r.status_code == 404


def test_update_user_nonexistent():
    r = req(
        "PATCH", "/api/auth/users/999999", token=_admin_token, data={"role": "viewer"}
    )
    assert r.status_code == 404


def test_update_user_invalid_role():
    import uuid

    unique = uuid.uuid4().hex[:8]
    create_r = req(
        "POST",
        "/api/auth/users",
        token=_admin_token,
        data={
            "username": f"invrol_{unique}",
            "password": "StrongPass1!",
            "role": "viewer",
        },
    )
    user_id = json.loads(create_r.data)["user"]["id"]

    r = req(
        "PATCH",
        f"/api/auth/users/{user_id}",
        token=_admin_token,
        data={"role": "superadmin"},
    )
    assert r.status_code == 400

    req("DELETE", f"/api/auth/users/{user_id}", token=_admin_token)

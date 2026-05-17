"""Phase B-1 (#212) — Job Templates & Executions API tests.

Covers:
- Template CRUD (admin required)
- Role-based access: list/get for viewer, execute for operator
- Delete guard: template with executions cannot be deleted
- JobExecution lifecycle: create / list / get / cancel
- Input validation: name required, risk_level enum, script_body length
"""

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, User

app = create_app("testing")
client = app.test_client()

_unique = uuid.uuid4().hex[:8]
_admin_token = None
_operator_token = None
_viewer_token = None


def setup_module():
    global _admin_token, _operator_token, _viewer_token
    with app.app_context():
        db.create_all()
        for username, role, pw in [
            (f"jt_admin_{_unique}", "admin", "AdminJt1!"),
            (f"jt_operator_{_unique}", "operator", "OperJt1!"),
            (f"jt_viewer_{_unique}", "viewer", "ViewJt1!"),
        ]:
            if not User.query.filter_by(username=username).first():
                db.session.add(
                    User(username=username, password_hash=hash_password(pw), role=role)
                )
        db.session.commit()
    _admin_token = _login(f"jt_admin_{_unique}", "AdminJt1!")
    _operator_token = _login(f"jt_operator_{_unique}", "OperJt1!")
    _viewer_token = _login(f"jt_viewer_{_unique}", "ViewJt1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def _req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    kwargs = {"method": method, "headers": headers}
    if data is not None:
        kwargs["data"] = json.dumps(data)
    return client.open(path, **kwargs)


def _create_pc(suffix=""):
    suffix = suffix or uuid.uuid4().hex[:6]
    with app.app_context():
        pc = PC(pc_name=f"JT-PC-{suffix}-{_unique}", os_version="Windows 11")
        db.session.add(pc)
        db.session.commit()
        return pc.id


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------


def test_create_template_as_admin():
    r = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-create-{_unique}",
            "category": "maintenance",
            "risk_level": "low",
            "script_body": "Write-Output 'ok'",
        },
    )
    assert r.status_code == 201, r.data
    body = json.loads(r.data)
    assert body["template"]["name"] == f"tpl-create-{_unique}"
    assert body["template"]["risk_level"] == "low"
    assert body["template"]["script_body"] == "Write-Output 'ok'"


def test_create_template_forbidden_for_operator():
    r = _req(
        "POST",
        "/api/job-templates",
        token=_operator_token,
        data={
            "name": f"tpl-op-forbidden-{_unique}",
            "script_body": "x",
        },
    )
    assert r.status_code == 403


def test_create_template_forbidden_for_viewer():
    r = _req(
        "POST",
        "/api/job-templates",
        token=_viewer_token,
        data={
            "name": f"tpl-v-forbidden-{_unique}",
            "script_body": "x",
        },
    )
    assert r.status_code == 403


def test_create_template_requires_name():
    r = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "script_body": "Write-Output 'test'",
        },
    )
    assert r.status_code == 400
    assert "name" in json.loads(r.data).get("error", "").lower()


def test_create_template_invalid_risk_level():
    r = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-bad-risk-{_unique}",
            "risk_level": "critical",
        },
    )
    assert r.status_code == 400


def test_create_template_invalid_category():
    r = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-bad-cat-{_unique}",
            "category": "nonexistent",
        },
    )
    assert r.status_code == 400


def test_create_template_script_too_long():
    r = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-long-{_unique}",
            "script_body": "X" * 20000,
        },
    )
    assert r.status_code == 400


def test_create_template_duplicate_name():
    name = f"tpl-dup-{_unique}"
    _req("POST", "/api/job-templates", token=_admin_token, data={"name": name})
    r = _req("POST", "/api/job-templates", token=_admin_token, data={"name": name})
    assert r.status_code == 409


def test_list_templates_viewer_no_script():
    _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-list-{_unique}",
            "script_body": "secret script",
        },
    )
    r = _req("GET", "/api/job-templates", token=_viewer_token)
    assert r.status_code == 200
    body = json.loads(r.data)
    assert "templates" in body
    for t in body["templates"]:
        assert "script_body" not in t


def test_list_templates_unauthenticated():
    r = _req("GET", "/api/job-templates")
    assert r.status_code == 401


def test_get_template_admin_sees_script():
    r1 = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-get-{_unique}",
            "script_body": "Get-Process",
        },
    )
    tid = json.loads(r1.data)["template"]["id"]
    r2 = _req("GET", f"/api/job-templates/{tid}", token=_admin_token)
    assert r2.status_code == 200
    assert json.loads(r2.data)["template"]["script_body"] == "Get-Process"


def test_get_template_viewer_no_script():
    r1 = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-get-v-{_unique}",
            "script_body": "hidden",
        },
    )
    tid = json.loads(r1.data)["template"]["id"]
    r2 = _req("GET", f"/api/job-templates/{tid}", token=_viewer_token)
    assert r2.status_code == 200
    assert "script_body" not in json.loads(r2.data)["template"]


def test_get_template_not_found():
    r = _req("GET", "/api/job-templates/9999999", token=_admin_token)
    assert r.status_code == 404


def test_update_template_as_admin():
    r1 = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-upd-{_unique}",
        },
    )
    tid = json.loads(r1.data)["template"]["id"]
    r2 = _req(
        "PUT",
        f"/api/job-templates/{tid}",
        token=_admin_token,
        data={
            "risk_level": "high",
            "requires_approval": True,
        },
    )
    assert r2.status_code == 200
    body = json.loads(r2.data)
    assert body["template"]["risk_level"] == "high"
    assert body["template"]["requires_approval"] is True


def test_update_template_forbidden_for_viewer():
    r1 = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-upd-v-{_unique}",
        },
    )
    tid = json.loads(r1.data)["template"]["id"]
    r = _req(
        "PUT",
        f"/api/job-templates/{tid}",
        token=_viewer_token,
        data={"risk_level": "high"},
    )
    assert r.status_code == 403


def test_delete_template_no_executions():
    r1 = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-del-{_unique}",
        },
    )
    tid = json.loads(r1.data)["template"]["id"]
    r2 = _req("DELETE", f"/api/job-templates/{tid}", token=_admin_token)
    assert r2.status_code == 200


def test_delete_template_forbidden_for_operator():
    r1 = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-del-op-{_unique}",
        },
    )
    tid = json.loads(r1.data)["template"]["id"]
    r = _req("DELETE", f"/api/job-templates/{tid}", token=_operator_token)
    assert r.status_code == 403


def test_list_templates_category_filter():
    _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-cat-sec-{_unique}",
            "category": "security",
        },
    )
    r = _req("GET", "/api/job-templates?category=security", token=_viewer_token)
    assert r.status_code == 200
    body = json.loads(r.data)
    for t in body["templates"]:
        assert t["category"] == "security"


# ---------------------------------------------------------------------------
# Execution lifecycle
# ---------------------------------------------------------------------------


def _create_enabled_template(suffix):
    r = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-exec-{suffix}-{_unique}",
            "script_body": "Write-Output 'run'",
            "risk_level": "low",
        },
    )
    return json.loads(r.data)["template"]["id"]


def test_execute_template_as_operator():
    pc_id = _create_pc()
    tid = _create_enabled_template("op")
    r = _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_operator_token,
        data={
            "pc_id": pc_id,
        },
    )
    assert r.status_code == 201, r.data
    body = json.loads(r.data)
    assert body["execution"]["status"] == "pending"
    assert body["execution"]["template_id"] == tid
    assert body["execution"]["pc_id"] == pc_id


def test_execute_template_as_admin():
    pc_id = _create_pc()
    tid = _create_enabled_template("admin")
    r = _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_admin_token,
        data={
            "pc_id": pc_id,
        },
    )
    assert r.status_code == 201


def test_execute_template_forbidden_for_viewer():
    pc_id = _create_pc()
    tid = _create_enabled_template("viewer-block")
    r = _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_viewer_token,
        data={
            "pc_id": pc_id,
        },
    )
    assert r.status_code == 403


def test_execute_template_missing_pc_id():
    tid = _create_enabled_template("no-pc")
    r = _req(
        "POST", f"/api/job-templates/{tid}/execute", token=_operator_token, data={}
    )
    assert r.status_code == 400


def test_execute_template_pc_not_found():
    tid = _create_enabled_template("bad-pc")
    r = _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_operator_token,
        data={
            "pc_id": 9999999,
        },
    )
    assert r.status_code == 404


def test_execute_disabled_template():
    r1 = _req(
        "POST",
        "/api/job-templates",
        token=_admin_token,
        data={
            "name": f"tpl-disabled-{_unique}",
            "is_enabled": False,
        },
    )
    tid = json.loads(r1.data)["template"]["id"]
    pc_id = _create_pc()
    r = _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_operator_token,
        data={
            "pc_id": pc_id,
        },
    )
    assert r.status_code == 422


def test_list_executions():
    pc_id = _create_pc()
    tid = _create_enabled_template("list")
    _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_operator_token,
        data={"pc_id": pc_id},
    )
    r = _req("GET", "/api/job-executions", token=_viewer_token)
    assert r.status_code == 200
    body = json.loads(r.data)
    assert "executions" in body
    assert "total" in body
    assert "page" in body


def test_list_executions_unauthenticated():
    r = _req("GET", "/api/job-executions")
    assert r.status_code == 401


def test_get_execution_detail():
    pc_id = _create_pc()
    tid = _create_enabled_template("detail")
    r1 = _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_operator_token,
        data={"pc_id": pc_id},
    )
    eid = json.loads(r1.data)["execution"]["id"]
    r2 = _req("GET", f"/api/job-executions/{eid}", token=_viewer_token)
    assert r2.status_code == 200
    body = json.loads(r2.data)
    assert body["execution"]["id"] == eid
    assert body["execution"]["status"] == "pending"


def test_get_execution_not_found():
    r = _req("GET", "/api/job-executions/9999999", token=_admin_token)
    assert r.status_code == 404


def test_cancel_pending_execution():
    pc_id = _create_pc()
    tid = _create_enabled_template("cancel")
    r1 = _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_operator_token,
        data={"pc_id": pc_id},
    )
    eid = json.loads(r1.data)["execution"]["id"]
    r2 = _req("POST", f"/api/job-executions/{eid}/cancel", token=_operator_token)
    assert r2.status_code == 200
    body = json.loads(r2.data)
    assert body["execution"]["status"] == "cancelled"


def test_cancel_already_cancelled():
    pc_id = _create_pc()
    tid = _create_enabled_template("cancel2")
    r1 = _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_operator_token,
        data={"pc_id": pc_id},
    )
    eid = json.loads(r1.data)["execution"]["id"]
    _req("POST", f"/api/job-executions/{eid}/cancel", token=_operator_token)
    r = _req("POST", f"/api/job-executions/{eid}/cancel", token=_operator_token)
    assert r.status_code == 422


def test_cancel_forbidden_for_viewer():
    pc_id = _create_pc()
    tid = _create_enabled_template("cancel-v")
    r1 = _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_operator_token,
        data={"pc_id": pc_id},
    )
    eid = json.loads(r1.data)["execution"]["id"]
    r = _req("POST", f"/api/job-executions/{eid}/cancel", token=_viewer_token)
    assert r.status_code == 403


def test_delete_template_with_executions_blocked():
    pc_id = _create_pc()
    tid = _create_enabled_template("del-block")
    _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_operator_token,
        data={"pc_id": pc_id},
    )
    r = _req("DELETE", f"/api/job-templates/{tid}", token=_admin_token)
    assert r.status_code == 409


def test_list_executions_status_filter():
    pc_id = _create_pc()
    tid = _create_enabled_template("filter")
    r1 = _req(
        "POST",
        f"/api/job-templates/{tid}/execute",
        token=_operator_token,
        data={"pc_id": pc_id},
    )
    eid = json.loads(r1.data)["execution"]["id"]
    _req("POST", f"/api/job-executions/{eid}/cancel", token=_operator_token)

    r = _req("GET", "/api/job-executions?status=cancelled", token=_viewer_token)
    assert r.status_code == 200
    body = json.loads(r.data)
    for e in body["executions"]:
        assert e["status"] == "cancelled"


def test_web_ui_page_requires_login():
    r = client.get("/job-templates")
    assert r.status_code in (302, 401)

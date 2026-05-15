"""Extra coverage tests for routes/tasks.py.

Targets uncovered lines:
- get_pending_tasks: no pc_name (30), success path with pending task (36-46)
- create_task: no body (55)
- bulk_create_tasks: no body (118), no task_type (122), command not str / too long (138-142),
  success loop body (154-165), commit+log (168-169)
- submit_result: no body (198), no task_id (202), task not found (206), bad status (211)
- get_task: success path (230)
- export_tasks_csv: status filter (241), task_type filter (243), for loop body (269-270)
- list_tasks: pc_name filter found (306-308), pc_name not found (309-310)
"""

import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, Task, User

app = create_app("testing")
client = app.test_client()

_admin_token = None
_viewer_token = None
_unique = uuid.uuid4().hex[:8]
_AGENT_KEY = "default-agent-key"


def setup_module():
    global _admin_token, _viewer_token
    with app.app_context():
        db.create_all()
        for username, role, password in [
            (f"admin_tk_{_unique}", "admin", "AdminTk1!"),
            (f"viewer_tk_{_unique}", "viewer", "ViewerTk1!"),
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

    _admin_token = _login(f"admin_tk_{_unique}", "AdminTk1!")
    _viewer_token = _login(f"viewer_tk_{_unique}", "ViewerTk1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def req(method, path, token=None, agent_key=None, params=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if agent_key:
        # agent_auth_required reads Authorization: Bearer <key>
        headers["Authorization"] = f"Bearer {agent_key}"
    url = path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{path}?{qs}"
    body = json.dumps(data) if data is not None else None
    return client.open(url, method=method, headers=headers, data=body)


def _create_pc(suffix, **kwargs):
    with app.app_context():
        pc = PC(pc_name=f"TestPC-tk-{suffix}-{_unique}", **kwargs)
        db.session.add(pc)
        db.session.commit()
        return pc.id, pc.pc_name


def _create_task(pc_id=None, task_type="cleanup", status="pending"):
    with app.app_context():
        t = Task(
            pc_id=pc_id,
            task_type=task_type,
            status=status,
            priority=0,
            created_by=f"admin_tk_{_unique}",
        )
        db.session.add(t)
        db.session.commit()
        return t.id


# ── get_pending_tasks (agent auth) ──────────────────────────────────


def test_get_pending_tasks_no_pc_name():
    """No pc_name → 400 (line 30)."""
    r = req("GET", "/api/tasks/pending", agent_key=_AGENT_KEY)
    assert r.status_code == 400
    assert "pc_name" in json.loads(r.data)["error"]


def test_get_pending_tasks_pc_not_found():
    """pc_name not in DB → empty tasks list."""
    r = req(
        "GET",
        "/api/tasks/pending",
        agent_key=_AGENT_KEY,
        params={"pc_name": f"NoSuchPC-{_unique}"},
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["tasks"] == []


def test_get_pending_tasks_success():
    """PC exists with pending task → returns task list (lines 36-46)."""
    pc_id, pc_name = _create_pc("pend")
    _create_task(pc_id=pc_id, task_type="cleanup", status="pending")
    r = req(
        "GET", "/api/tasks/pending", agent_key=_AGENT_KEY, params={"pc_name": pc_name}
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "tasks" in data
    assert len(data["tasks"]) >= 1
    assert data["tasks"][0]["task_type"] == "cleanup"


def test_get_pending_tasks_unauthenticated():
    """No agent key → 401."""
    r = req("GET", "/api/tasks/pending", params={"pc_name": "any"})
    assert r.status_code == 401


# ── create_task ──────────────────────────────────────────────────────


def test_create_task_no_body():
    """No body → 400 or 415 (line 55)."""
    r = client.open(
        "/api/tasks",
        method="POST",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code in (400, 415)


def test_create_task_success_minimal():
    """Minimal valid create_task → 201."""
    r = req(
        "POST",
        "/api/tasks",
        token=_admin_token,
        data={
            "task_type": "cleanup",
        },
    )
    assert r.status_code == 201
    data = json.loads(r.data)
    assert "task" in data
    task_id = data["task"]["id"]
    # cleanup
    req("DELETE", f"/api/tasks/{task_id}", token=_admin_token)


# ── bulk_create_tasks ────────────────────────────────────────────────


def test_bulk_create_tasks_no_body():
    """No body → 400 or 415 (line 118)."""
    r = client.open(
        "/api/tasks/bulk",
        method="POST",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code in (400, 415)


def test_bulk_create_tasks_no_task_type():
    """Empty task_type → 400 (line 122)."""
    r = req(
        "POST",
        "/api/tasks/bulk",
        token=_admin_token,
        data={
            "task_type": "",
            "pc_names": ["SomePC"],
        },
    )
    assert r.status_code == 400
    assert "task_type" in json.loads(r.data)["error"]


def test_bulk_create_tasks_command_not_str():
    """command is int (not str) → 400 (line 138-139)."""
    r = req(
        "POST",
        "/api/tasks/bulk",
        token=_admin_token,
        data={
            "task_type": "custom",
            "pc_names": ["SomePC"],
            "command": 12345,
        },
    )
    assert r.status_code == 400
    assert "command" in json.loads(r.data)["error"]


def test_bulk_create_tasks_command_too_long():
    """command > 512 chars → 400 (lines 140-142)."""
    r = req(
        "POST",
        "/api/tasks/bulk",
        token=_admin_token,
        data={
            "task_type": "custom",
            "pc_names": ["SomePC"],
            "command": "A" * 513,
        },
    )
    assert r.status_code == 400
    assert "command" in json.loads(r.data)["error"]


def test_bulk_create_tasks_all_pcs_not_found():
    """All pc_names not found → 400, successes=[] (lines 177-178)."""
    r = req(
        "POST",
        "/api/tasks/bulk",
        token=_admin_token,
        data={
            "task_type": "diagnose",
            "pc_names": [f"NoPC-{_unique}-1", f"NoPC-{_unique}-2"],
        },
    )
    assert r.status_code == 400
    data = json.loads(r.data)
    assert data["successes"] == []
    assert len(data["failures"]) == 2


def test_bulk_create_tasks_success():
    """PC exists → tasks created (lines 154-165, 168-169)."""
    pc_id1, pc_name1 = _create_pc("bulk1")
    pc_id2, pc_name2 = _create_pc("bulk2")
    r = req(
        "POST",
        "/api/tasks/bulk",
        token=_admin_token,
        data={
            "task_type": "diagnose",
            "pc_names": [pc_name1, pc_name2],
            "priority": 5,
        },
    )
    assert r.status_code == 201
    data = json.loads(r.data)
    assert len(data["successes"]) == 2
    assert data["failures"] == []
    # cleanup created tasks
    for s in data["successes"]:
        req("DELETE", f"/api/tasks/{s['task_id']}", token=_admin_token)


def test_bulk_create_tasks_mixed():
    """Mix of found/not-found PCs → partial success."""
    pc_id, pc_name = _create_pc("bulkmix")
    r = req(
        "POST",
        "/api/tasks/bulk",
        token=_admin_token,
        data={
            "task_type": "update",
            "pc_names": [pc_name, f"NoPC-{_unique}-mix"],
        },
    )
    assert r.status_code == 201
    data = json.loads(r.data)
    assert len(data["successes"]) == 1
    assert len(data["failures"]) == 1
    for s in data["successes"]:
        req("DELETE", f"/api/tasks/{s['task_id']}", token=_admin_token)


# ── submit_result (agent auth) ───────────────────────────────────────


def test_submit_result_no_body():
    """No body → 400 (line 198)."""
    r = client.open(
        "/api/result",
        method="POST",
        headers={"Authorization": f"Bearer {_AGENT_KEY}"},
    )
    assert r.status_code in (400, 415)


def test_submit_result_no_task_id():
    """No task_id → 400 (line 202)."""
    r = req("POST", "/api/result", agent_key=_AGENT_KEY, data={"status": "completed"})
    assert r.status_code == 400
    assert "task_id" in json.loads(r.data)["error"]


def test_submit_result_task_not_found():
    """task_id not in DB → 404 (line 206)."""
    r = req(
        "POST",
        "/api/result",
        agent_key=_AGENT_KEY,
        data={
            "task_id": 9999999,
            "status": "completed",
        },
    )
    assert r.status_code == 404


def test_submit_result_bad_status():
    """Invalid status value → 400 (line 211)."""
    task_id = _create_task()
    r = req(
        "POST",
        "/api/result",
        agent_key=_AGENT_KEY,
        data={
            "task_id": task_id,
            "status": "invalid_status",
        },
    )
    assert r.status_code == 400
    assert "status" in json.loads(r.data)["error"]
    # cleanup
    req("DELETE", f"/api/tasks/{task_id}", token=_admin_token)


def test_submit_result_success():
    """Valid submit → 200 (covers commit at line 219)."""
    task_id = _create_task()
    r = req(
        "POST",
        "/api/result",
        agent_key=_AGENT_KEY,
        data={
            "task_id": task_id,
            "status": "completed",
            "result": {"output": "done"},
        },
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "message" in data
    # cleanup
    req("DELETE", f"/api/tasks/{task_id}", token=_admin_token)


# ── get_task (login_required) ────────────────────────────────────────


def test_get_task_success():
    """GET /api/tasks/<id> with existing task → 200 with task dict (line 230)."""
    task_id = _create_task()
    r = req("GET", f"/api/tasks/{task_id}", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "task" in data
    assert data["task"]["id"] == task_id
    req("DELETE", f"/api/tasks/{task_id}", token=_admin_token)


def test_get_task_not_found():
    """GET /api/tasks/9999999 → 404."""
    r = req("GET", "/api/tasks/9999999", token=_admin_token)
    assert r.status_code == 404


def test_get_task_viewer_allowed():
    """Viewer can read task detail."""
    task_id = _create_task()
    r = req("GET", f"/api/tasks/{task_id}", token=_viewer_token)
    assert r.status_code == 200
    req("DELETE", f"/api/tasks/{task_id}", token=_admin_token)


# ── export_tasks_csv ─────────────────────────────────────────────────


def test_export_tasks_csv_basic():
    """GET /api/tasks/export.csv → 200 text/csv."""
    r = req("GET", "/api/tasks/export.csv", token=_admin_token)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("Content-Type", "")


def test_export_tasks_csv_status_filter():
    """export.csv?status=pending covers line 241."""
    r = req(
        "GET", "/api/tasks/export.csv", token=_admin_token, params={"status": "pending"}
    )
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert "ID" in content  # header row present


def test_export_tasks_csv_task_type_filter():
    """export.csv?task_type=cleanup covers line 243."""
    r = req(
        "GET",
        "/api/tasks/export.csv",
        token=_admin_token,
        params={"task_type": "cleanup"},
    )
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert "タスク種別" in content


def test_export_tasks_csv_for_loop_body():
    """Tasks in DB → CSV has data rows (lines 269-270)."""
    pc_id, pc_name = _create_pc("csvtask")
    task_id = _create_task(pc_id=pc_id, task_type="update", status="pending")
    r = req("GET", "/api/tasks/export.csv", token=_admin_token)
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert "update" in content
    assert pc_name in content
    # cleanup
    req("DELETE", f"/api/tasks/{task_id}", token=_admin_token)


def test_export_tasks_csv_task_no_pc():
    """Global task (pc_id=None) → pc_name column is empty string (line 269 branch)."""
    task_id = _create_task(pc_id=None, task_type="collect")
    r = req("GET", "/api/tasks/export.csv", token=_admin_token)
    assert r.status_code == 200
    content = r.data.decode("utf-8-sig")
    assert "collect" in content
    req("DELETE", f"/api/tasks/{task_id}", token=_admin_token)


# ── list_tasks with pc_name filter ───────────────────────────────────


def test_list_tasks_pc_name_found():
    """pc_name filter with existing PC → filters tasks (lines 306-308)."""
    pc_id, pc_name = _create_pc("listtask")
    task_id = _create_task(pc_id=pc_id)
    r = req("GET", "/api/tasks", token=_admin_token, params={"pc_name": pc_name})
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "tasks" in data
    assert "total" in data
    # cleanup
    req("DELETE", f"/api/tasks/{task_id}", token=_admin_token)


def test_list_tasks_pc_name_not_found():
    """pc_name filter with non-existent PC → empty result (lines 309-310)."""
    r = req(
        "GET",
        "/api/tasks",
        token=_admin_token,
        params={"pc_name": f"NonExistentPC-{_unique}"},
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["tasks"] == []
    assert data["total"] == 0


def test_list_tasks_basic():
    """GET /api/tasks without filters → paginated list."""
    r = req("GET", "/api/tasks", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "tasks" in data
    assert "total" in data
    assert "page" in data
    assert "pages" in data

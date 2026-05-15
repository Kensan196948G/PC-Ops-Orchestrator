"""Extra coverage tests for routes/scheduled_tasks.py.

Targets uncovered lines:
- _validate_payload: schedule_type invalid (34), interval_minutes < 1 (54-56),
  daily_time invalid format (62), weekly schedule (65-77),
  pc_name found/not-found (81-85)
- _is_valid_time: exception branch (97-98)
- list_scheduled_tasks: enabled filter (117)
- create_scheduled_task: no body (137)
- update_scheduled_task: no body (182), validation error (186)
"""

import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, User

app = create_app("testing")
client = app.test_client()

_admin_token = None
_operator_token = None
_viewer_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token, _operator_token, _viewer_token
    with app.app_context():
        db.create_all()
        for username, role, password in [
            (f"admin_st_{_unique}", "admin", "AdminSt1!"),
            (f"operator_st_{_unique}", "operator", "OperatorSt1!"),
            (f"viewer_st_{_unique}", "viewer", "ViewerSt1!"),
        ]:
            if not User.query.filter_by(username=username).first():
                db.session.add(User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                ))
        db.session.commit()

    _admin_token = _login(f"admin_st_{_unique}", "AdminSt1!")
    _operator_token = _login(f"operator_st_{_unique}", "OperatorSt1!")
    _viewer_token = _login(f"viewer_st_{_unique}", "ViewerSt1!")


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


def _create_pc(suffix):
    with app.app_context():
        pc = PC(pc_name=f"TestPC-st-{suffix}-{_unique}")
        db.session.add(pc)
        db.session.commit()
        return pc.id, pc.pc_name


def _create_scheduled_task(**kwargs):
    """Create a scheduled task via API and return its id."""
    payload = {
        "name": f"TestTask-{uuid.uuid4().hex[:6]}",
        "task_type": "cleanup",
        "schedule_type": "interval",
        "interval_minutes": 60,
    }
    payload.update(kwargs)
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data=payload)
    assert r.status_code == 201, f"create failed: {r.data}"
    return json.loads(r.data)["scheduled_task"]["id"]


# ── _validate_payload: invalid schedule_type (line 34) ───────────────


def test_create_invalid_schedule_type():
    """schedule_type not in allowed set → 400 (line 34)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"BadSched-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "hourly",  # not in allowed set
    })
    assert r.status_code == 400
    assert "schedule_type" in json.loads(r.data)["error"]


# ── _validate_payload: interval_minutes < 1 (lines 54-56) ───────────


def test_create_interval_minutes_zero():
    """interval_minutes = 0 → 400 (lines 54-56)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"ZeroInterval-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "interval",
        "interval_minutes": 0,
    })
    assert r.status_code == 400
    assert "interval_minutes" in json.loads(r.data)["error"]


def test_create_interval_minutes_negative():
    """interval_minutes = -5 → 400 (lines 54-56)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"NegInterval-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "interval",
        "interval_minutes": -5,
    })
    assert r.status_code == 400
    assert "interval_minutes" in json.loads(r.data)["error"]


def test_create_interval_minutes_not_int():
    """interval_minutes = 'abc' (non-integer) → 400 (lines 54-56)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"StrInterval-{_unique}",
        "task_type": "update",
        "schedule_type": "interval",
        "interval_minutes": "abc",
    })
    assert r.status_code == 400
    assert "interval_minutes" in json.loads(r.data)["error"]


# ── _validate_payload: daily_time invalid (line 62) ──────────────────


def test_create_daily_invalid_time():
    """daily_time with invalid format → 400 (line 62)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"BadDaily-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "daily",
        "daily_time": "25:00",  # invalid hour
    })
    assert r.status_code == 400
    assert "daily_time" in json.loads(r.data)["error"]


def test_create_daily_valid():
    """daily_time with valid format → 201 (covers lines 59-63)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"GoodDaily-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "daily",
        "daily_time": "03:00",
    })
    assert r.status_code == 201
    task_id = json.loads(r.data)["scheduled_task"]["id"]
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


# ── _validate_payload: weekly schedule (lines 65-77) ─────────────────


def test_create_weekly_invalid_time():
    """weekly_time with invalid format → 400 (line 67-68)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"BadWeeklyTime-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "weekly",
        "weekly_time": "not-a-time",
        "weekly_day": 1,
    })
    assert r.status_code == 400
    assert "weekly_time" in json.loads(r.data)["error"]


def test_create_weekly_invalid_day():
    """weekly_day out of range → 400 (lines 72-75)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"BadWeeklyDay-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "weekly",
        "weekly_time": "09:00",
        "weekly_day": 7,  # 0-6 only
    })
    assert r.status_code == 400
    assert "weekly_day" in json.loads(r.data)["error"]


def test_create_weekly_day_not_int():
    """weekly_day is not an integer → 400 (lines 72-75)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"BadWeeklyDayStr-{_unique}",
        "task_type": "diagnose",
        "schedule_type": "weekly",
        "weekly_time": "10:00",
        "weekly_day": "monday",  # not int
    })
    assert r.status_code == 400
    assert "weekly_day" in json.loads(r.data)["error"]


def test_create_weekly_valid():
    """Valid weekly schedule → 201 (covers lines 65-77)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"GoodWeekly-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "weekly",
        "weekly_time": "09:30",
        "weekly_day": 1,  # Tuesday
    })
    assert r.status_code == 201
    task_id = json.loads(r.data)["scheduled_task"]["id"]
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


# ── _validate_payload: pc_name lookup (lines 81-85) ──────────────────


def test_create_with_pc_name_found():
    """pc_name matches existing PC → 201, target_type='pc' (lines 80-85)."""
    _, pc_name = _create_pc("stpc1")
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"PCTask-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "interval",
        "interval_minutes": 30,
        "pc_name": pc_name,
    })
    assert r.status_code == 201
    data = json.loads(r.data)
    assert data["scheduled_task"]["target_type"] == "pc"
    task_id = data["scheduled_task"]["id"]
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


def test_create_with_pc_name_not_found():
    """pc_name not in DB → 400 (lines 82-83)."""
    r = req("POST", "/api/scheduled-tasks", token=_admin_token, data={
        "name": f"NoPCTask-{_unique}",
        "task_type": "update",
        "schedule_type": "interval",
        "interval_minutes": 60,
        "pc_name": f"NoSuchPC-{_unique}",
    })
    assert r.status_code == 400
    assert "見つかりません" in json.loads(r.data)["error"]


# ── list_scheduled_tasks: enabled filter (line 117) ──────────────────


def test_list_enabled_filter_true():
    """?enabled=true filters to only enabled tasks (line 117)."""
    r = req("GET", "/api/scheduled-tasks", token=_admin_token, params={"enabled": "true"})
    assert r.status_code == 200
    data = json.loads(r.data)
    for t in data["scheduled_tasks"]:
        assert t["is_enabled"] is True


def test_list_enabled_filter_false():
    """?enabled=false filters to only disabled tasks (line 117)."""
    task_id = _create_scheduled_task()
    # Disable the task
    req("POST", f"/api/scheduled-tasks/{task_id}/toggle", token=_admin_token)
    r = req("GET", "/api/scheduled-tasks", token=_admin_token, params={"enabled": "false"})
    assert r.status_code == 200
    data = json.loads(r.data)
    for t in data["scheduled_tasks"]:
        assert t["is_enabled"] is False
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


# ── create_scheduled_task: no body (line 137) ────────────────────────


def test_create_no_body():
    """POST without body → 400 or 415 (line 137)."""
    r = client.open(
        "/api/scheduled-tasks",
        method="POST",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code in (400, 415)


# ── update_scheduled_task: no body (182) / validation error (186) ────


def test_update_no_body():
    """PUT without body → 400 or 415 (line 182)."""
    task_id = _create_scheduled_task()
    r = client.open(
        f"/api/scheduled-tasks/{task_id}",
        method="PUT",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code in (400, 415)
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


def test_update_validation_error():
    """PUT with invalid payload → 400 (line 186)."""
    task_id = _create_scheduled_task()
    r = req("PUT", f"/api/scheduled-tasks/{task_id}", token=_admin_token, data={
        "name": "UpdatedName",
        "task_type": "cleanup",
        "schedule_type": "interval",
        "interval_minutes": -1,  # invalid
    })
    assert r.status_code == 400
    assert "interval_minutes" in json.loads(r.data)["error"]
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


def test_update_success():
    """PUT with valid payload → 200 (covers lines 188-200)."""
    task_id = _create_scheduled_task()
    r = req("PUT", f"/api/scheduled-tasks/{task_id}", token=_admin_token, data={
        "name": f"Updated-{_unique}",
        "task_type": "diagnose",
        "schedule_type": "interval",
        "interval_minutes": 120,
    })
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["scheduled_task"]["interval_minutes"] == 120
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


# ── run-now endpoint (lines 248-273) ────────────────────────────────


def test_run_now_success():
    """POST /run-now → 201 with task (covers lines 254-273)."""
    task_id = _create_scheduled_task()
    r = req("POST", f"/api/scheduled-tasks/{task_id}/run-now", token=_admin_token)
    assert r.status_code == 201
    data = json.loads(r.data)
    assert "task" in data
    assert data["task"]["status"] == "pending"
    # cleanup created task
    from models import Task
    with app.app_context():
        created_task_id = data["task"]["id"]
        t = db.session.get(Task, created_task_id)
        if t:
            db.session.delete(t)
            db.session.commit()
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


def test_run_now_not_found():
    """POST /run-now with non-existent task → 404."""
    r = req("POST", "/api/scheduled-tasks/9999999/run-now", token=_admin_token)
    assert r.status_code == 404


# ── toggle endpoint ──────────────────────────────────────────────────


def test_toggle_enables_then_disables():
    """Toggle switches is_enabled and recalculates next_run_at."""
    task_id = _create_scheduled_task()
    r1 = req("POST", f"/api/scheduled-tasks/{task_id}/toggle", token=_admin_token)
    assert r1.status_code == 200
    d1 = json.loads(r1.data)
    assert d1["scheduled_task"]["is_enabled"] is False

    r2 = req("POST", f"/api/scheduled-tasks/{task_id}/toggle", token=_admin_token)
    assert r2.status_code == 200
    d2 = json.loads(r2.data)
    assert d2["scheduled_task"]["is_enabled"] is True
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


# ── operator role access ─────────────────────────────────────────────


def test_operator_can_create():
    """Operator role can create scheduled tasks."""
    r = req("POST", "/api/scheduled-tasks", token=_operator_token, data={
        "name": f"OpTask-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "interval",
        "interval_minutes": 15,
    })
    assert r.status_code == 201
    task_id = json.loads(r.data)["scheduled_task"]["id"]
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


def test_viewer_cannot_create():
    """Viewer role cannot create scheduled tasks → 403."""
    r = req("POST", "/api/scheduled-tasks", token=_viewer_token, data={
        "name": f"ViewTask-{_unique}",
        "task_type": "cleanup",
        "schedule_type": "interval",
        "interval_minutes": 15,
    })
    assert r.status_code == 403

"""
test_misc_coverage.py — Miscellaneous coverage tests targeting remaining missed lines
across multiple route files.

Targets:
- routes/agents.py: lines 67, 142 (timezone-aware last_seen else branch)
- routes/alert_rules.py: lines 112, 149 (null trick for POST/PUT)
- routes/api_keys.py: line 22 (null trick for POST)
- routes/audit.py: lines 36-37 (invalid to_date → except ValueError: pass)
- routes/auth_routes.py: line 123 (null trick for POST /api/auth/users)
- routes/certificates.py: lines 42, 52, 105 (empty domain, long domain, null PUT)
- routes/collect.py: lines 24, 99, 179-187, 263 (null x2, _trim_snapshots, _matches unknown op)
- routes/dashboard.py: lines 57-68 (GET /api/dashboard/recent)
- routes/groups.py: lines 112, 241 (null trick PUT update_group, POST create_group_task)
- routes/licenses.py: lines 85, 154 (null trick POST/PUT)
- routes/notification_channels.py: lines 27, 84, 181-186 (null x2, unknown channel type)
- routes/scheduled_tasks.py: lines 137, 182 (null trick POST/PUT)
- routes/settings.py: lines 61, 70 (null trick PUT, unknown key)
- routes/tasks.py: lines 55, 118, 198 (null trick x3)
"""

import json
import sys
import os
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import PC, User, AlertRule, SystemSnapshot

app = create_app("testing")
client = app.test_client()

_admin_token = None
_unique = uuid.uuid4().hex[:8]
_AGENT_KEY = "default-agent-key"


def setup_module():
    global _admin_token
    with app.app_context():
        db.create_all()
        username = f"admin_misc_{_unique}"
        if not User.query.filter_by(username=username).first():
            db.session.add(
                User(
                    username=username,
                    password_hash=hash_password("AdminMisc1!"),
                    role="admin",
                )
            )
        db.session.commit()
    _admin_token = _login(f"admin_misc_{_unique}", "AdminMisc1!")


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
        headers["Authorization"] = f"Bearer {agent_key}"
    url = path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{path}?{qs}"
    body = json.dumps(data) if data is not None else None
    return client.open(url, method=method, headers=headers, data=body)


def _null_body(method, path, token=None, agent_key=None):
    """Send JSON null body → request.get_json() returns None → if not data: → 400."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if agent_key:
        headers["Authorization"] = f"Bearer {agent_key}"
    return client.open(path, method=method, headers=headers, data=b"null")


def _create_pc(suffix, **kwargs):
    with app.app_context():
        pc = PC(pc_name=f"MiscPC-{suffix}-{_unique}", **kwargs)
        db.session.add(pc)
        db.session.commit()
        return pc.id, pc.pc_name


# ── agents.py: lines 67, 142 (timezone-aware last_seen) ─────────────────────


def test_agents_timezone_aware_list():
    """GET /api/agents with timezone-aware last_seen → covers else branch (line 67)."""
    _create_pc("tzlist", last_seen=datetime.now(timezone.utc))
    r = req("GET", "/api/agents", token=_admin_token)
    assert r.status_code == 200
    assert "agents" in json.loads(r.data)


def test_agents_timezone_aware_csv_export():
    """GET /api/agents/export.csv with timezone-aware last_seen → covers else branch (line 142)."""
    _create_pc("tzcsv", last_seen=datetime.now(timezone.utc))
    r = req("GET", "/api/agents/export.csv", token=_admin_token)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("Content-Type", "")


# ── alert_rules.py: lines 112, 149 (null trick POST/PUT) ────────────────────


def test_alert_rules_create_null_body():
    """POST /api/alert-rules with null body → 400 (line 112)."""
    r = _null_body("POST", "/api/alert-rules", token=_admin_token)
    assert r.status_code == 400


def test_alert_rules_update_null_body():
    """PUT /api/alert-rules/<id> with null body → 400 (line 149)."""
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": f"TestRule-{_unique}",
            "metric": "cpu",
            "operator": "gt",
            "threshold": 90.0,
            "severity": "critical",
        },
    )
    assert r.status_code == 201
    rule_id = json.loads(r.data)["alert_rule"]["id"]
    r2 = _null_body("PUT", f"/api/alert-rules/{rule_id}", token=_admin_token)
    assert r2.status_code == 400
    req("DELETE", f"/api/alert-rules/{rule_id}", token=_admin_token)


# ── api_keys.py: line 22 (null trick POST) ──────────────────────────────────


def test_api_keys_create_null_body():
    """POST /api/api-keys with null body → 400 (line 22)."""
    r = _null_body("POST", "/api/api-keys", token=_admin_token)
    assert r.status_code == 400


# ── audit.py: lines 36-37 (invalid to_date → except ValueError: pass) ───────


def test_audit_invalid_to_date():
    """GET /api/audit/logs?to_date=notadate → ValueError suppressed, returns 200 (lines 36-37)."""
    r = req(
        "GET", "/api/audit/logs", token=_admin_token, params={"to_date": "notadate"}
    )
    assert r.status_code == 200
    assert "logs" in json.loads(r.data)


# ── auth_routes.py: line 123 (null trick POST /api/auth/users) ──────────────


def test_auth_users_create_null_body():
    """POST /api/auth/users with null body → 400 (line 123)."""
    r = _null_body("POST", "/api/auth/users", token=_admin_token)
    assert r.status_code == 400


# ── certificates.py: lines 42, 52, 105 ──────────────────────────────────────


def test_certificates_empty_domain():
    """POST /api/certificates with empty domain → 400 (line 42)."""
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={
            "domain": "",
            "expires_at": "2027-01-01",
        },
    )
    assert r.status_code == 400


def test_certificates_long_domain():
    """POST /api/certificates with domain > 200 chars → 400 (line 52)."""
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={
            "domain": "a" * 201,
            "expires_at": "2027-01-01",
        },
    )
    assert r.status_code == 400


def test_certificates_update_null_body():
    """PUT /api/certificates/<id> with null body → 400 (line 105)."""
    r = req(
        "POST",
        "/api/certificates",
        token=_admin_token,
        data={
            "domain": f"misc-cert-{_unique}.example.com",
            "expires_at": "2027-01-01",
        },
    )
    assert r.status_code == 201
    cert_id = json.loads(r.data)["certificate"]["id"]
    r2 = _null_body("PUT", f"/api/certificates/{cert_id}", token=_admin_token)
    assert r2.status_code == 400
    req("DELETE", f"/api/certificates/{cert_id}", token=_admin_token)


# ── collect.py: lines 24, 99 (null trick POST) ──────────────────────────────


def test_collect_null_body():
    """POST /api/collect with null body → 400 (line 24)."""
    r = _null_body("POST", "/api/collect", agent_key=_AGENT_KEY)
    assert r.status_code == 400


def test_collect_detail_null_body():
    """POST /api/collect/detail with null body → 400 (line 99)."""
    r = _null_body("POST", "/api/collect/detail", agent_key=_AGENT_KEY)
    assert r.status_code == 400


# ── collect.py: lines 179-187 (_trim_snapshots) ─────────────────────────────


def test_collect_trim_snapshots():
    """PC with >720 SystemSnapshot rows → _trim_snapshots called (lines 179-187)."""
    pc_id, pc_name = _create_pc("trimsnap")
    with app.app_context():
        base_time = datetime.now(timezone.utc) - timedelta(hours=721)
        rows = [
            SystemSnapshot(
                pc_id=pc_id,
                collected_at=base_time + timedelta(hours=i),
                cpu_usage=50.0,
            )
            for i in range(721)
        ]
        db.session.bulk_save_objects(rows)
        db.session.commit()
    r = req(
        "POST",
        "/api/collect",
        agent_key=_AGENT_KEY,
        data={
            "pc_name": pc_name,
            "cpu_usage": 45.0,
        },
    )
    assert r.status_code == 200
    with app.app_context():
        count = SystemSnapshot.query.filter_by(pc_id=pc_id).count()
        assert count <= 720


# ── collect.py: line 263 (_matches unknown operator) ────────────────────────


def test_collect_unknown_operator():
    """AlertRule with unknown operator → _matches returns False (line 263)."""
    pc_id, pc_name = _create_pc("unkop")
    with app.app_context():
        rule = AlertRule(
            name=f"UnknownOpRule-{_unique}",
            metric="cpu",
            operator="unknown_op",
            threshold=10.0,
            severity="warning",
            is_enabled=True,
        )
        db.session.add(rule)
        db.session.commit()
    r = req(
        "POST",
        "/api/collect",
        agent_key=_AGENT_KEY,
        data={
            "pc_name": pc_name,
            "cpu_usage": 50.0,
        },
    )
    assert r.status_code == 200
    with app.app_context():
        AlertRule.query.filter_by(name=f"UnknownOpRule-{_unique}").delete()
        db.session.commit()


# ── dashboard.py: lines 57-68 (GET /api/dashboard/recent) ───────────────────


def test_dashboard_recent_activity():
    """GET /api/dashboard/recent → 200 with operations and recent_tasks (lines 57-68)."""
    r = req("GET", "/api/dashboard/recent", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "operations" in data
    assert "recent_tasks" in data


# ── groups.py: lines 112, 241 (null trick PUT/POST) ─────────────────────────


def _create_group(suffix):
    r = req(
        "POST",
        "/api/groups",
        token=_admin_token,
        data={
            "name": f"MiscGroup-{suffix}-{_unique}",
        },
    )
    assert r.status_code == 201
    return json.loads(r.data)["group"]["id"]


def test_groups_update_null_body():
    """PUT /api/groups/<id> with null body → 400 or 415 (line 112)."""
    group_id = _create_group("upd")
    r = _null_body("PUT", f"/api/groups/{group_id}", token=_admin_token)
    assert r.status_code in (400, 415)
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


def test_groups_create_task_null_body():
    """POST /api/groups/<id>/tasks with null body → 400 or 415 (line 241)."""
    _, pc_name = _create_pc("gtask")
    group_id = _create_group("task")
    req(
        "POST",
        f"/api/groups/{group_id}/pcs",
        token=_admin_token,
        data={"pc_name": pc_name},
    )
    r = _null_body("POST", f"/api/groups/{group_id}/tasks", token=_admin_token)
    assert r.status_code in (400, 415)
    req("DELETE", f"/api/groups/{group_id}", token=_admin_token)


# ── licenses.py: lines 85, 154 (null trick POST/PUT) ────────────────────────


def test_licenses_create_null_body():
    """POST /api/licenses with null body → 400 (line 85)."""
    r = _null_body("POST", "/api/licenses", token=_admin_token)
    assert r.status_code == 400


def test_licenses_update_null_body():
    """PUT /api/licenses/<id> with null body → 400 (line 154)."""
    r = req(
        "POST",
        "/api/licenses",
        token=_admin_token,
        data={
            "product_name": f"TestSW-{_unique}",
        },
    )
    assert r.status_code == 201
    lic_id = json.loads(r.data)["license"]["id"]
    r2 = _null_body("PUT", f"/api/licenses/{lic_id}", token=_admin_token)
    assert r2.status_code == 400
    req("DELETE", f"/api/licenses/{lic_id}", token=_admin_token)


# ── notification_channels.py: lines 27, 84, 181-186 ─────────────────────────


def test_notification_channels_create_null_body():
    """POST /api/notification-channels with null body → 400 (line 27)."""
    r = _null_body("POST", "/api/notification-channels", token=_admin_token)
    assert r.status_code == 400


def test_notification_channels_update_null_body():
    """PUT /api/notification-channels/<id> with null body → 400 (line 84)."""
    r = req(
        "POST",
        "/api/notification-channels",
        token=_admin_token,
        data={
            "name": f"MiscChan-{_unique}",
            "channel_type": "slack",
            "target": "https://hooks.slack.com/test",
        },
    )
    assert r.status_code == 201
    chan_id = json.loads(r.data)["channel"]["id"]
    r2 = _null_body("PUT", f"/api/notification-channels/{chan_id}", token=_admin_token)
    assert r2.status_code == 400
    req("DELETE", f"/api/notification-channels/{chan_id}", token=_admin_token)


def test_notification_channel_unknown_type_test_send():
    """Test-send with unknown channel type → success without sending (lines 181-186)."""
    from models import NotificationChannel

    r = req(
        "POST",
        "/api/notification-channels",
        token=_admin_token,
        data={
            "name": f"UnknownChan-{_unique}",
            "channel_type": "slack",
            "target": "https://hooks.slack.com/test",
        },
    )
    assert r.status_code == 201
    chan_id = json.loads(r.data)["channel"]["id"]
    with app.app_context():
        chan = db.session.get(NotificationChannel, chan_id)
        chan.channel_type = "unknown_type"
        db.session.commit()
    r2 = req(
        "POST", f"/api/notification-channels/{chan_id}/test-send", token=_admin_token
    )
    assert r2.status_code == 200
    assert "message" in json.loads(r2.data)
    req("DELETE", f"/api/notification-channels/{chan_id}", token=_admin_token)


# ── scheduled_tasks.py: lines 137, 182 (null trick POST/PUT) ────────────────


def test_scheduled_tasks_create_null_body():
    """POST /api/scheduled-tasks with null body → 400 or 415 (line 137)."""
    r = _null_body("POST", "/api/scheduled-tasks", token=_admin_token)
    assert r.status_code in (400, 415)


def test_scheduled_tasks_update_null_body():
    """PUT /api/scheduled-tasks/<id> with null body → 400 or 415 (line 182)."""
    r = req(
        "POST",
        "/api/scheduled-tasks",
        token=_admin_token,
        data={
            "name": f"MiscSched-{_unique}",
            "task_type": "cleanup",
            "schedule_type": "interval",
            "interval_minutes": 60,
        },
    )
    assert r.status_code == 201
    task_id = json.loads(r.data)["scheduled_task"]["id"]
    r2 = _null_body("PUT", f"/api/scheduled-tasks/{task_id}", token=_admin_token)
    assert r2.status_code in (400, 415)
    req("DELETE", f"/api/scheduled-tasks/{task_id}", token=_admin_token)


# ── settings.py: lines 61, 70 (null trick PUT, unknown key) ─────────────────


def test_settings_update_null_body():
    """PUT /api/settings with null body → 400 (line 61)."""
    r = _null_body("PUT", "/api/settings", token=_admin_token)
    assert r.status_code == 400


def test_settings_update_unknown_key():
    """PUT /api/settings with unknown key → 400 (line 70)."""
    r = req(
        "PUT",
        "/api/settings",
        token=_admin_token,
        data={
            "some_unknown_key_xyz_abc": "value",
        },
    )
    assert r.status_code == 400
    assert "不明なキー" in json.loads(r.data)["error"]


# ── tasks.py: lines 55, 118, 198 (null trick x3) ────────────────────────────


def test_tasks_create_null_body():
    """POST /api/tasks with null body → 400 (line 55)."""
    r = _null_body("POST", "/api/tasks", token=_admin_token)
    assert r.status_code == 400


def test_tasks_bulk_create_null_body():
    """POST /api/tasks/bulk with null body → 400 or 415 (line 118)."""
    r = _null_body("POST", "/api/tasks/bulk", token=_admin_token)
    assert r.status_code in (400, 415)


def test_tasks_submit_result_null_body():
    """POST /api/result with null body → 400 (line 198)."""
    r = _null_body("POST", "/api/result", agent_key=_AGENT_KEY)
    assert r.status_code in (400, 415)

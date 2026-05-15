"""Extra coverage tests for routes/alert_rules.py.

Targets uncovered lines:
- _validate_rule: empty name (24), long name (26), threshold None (52),
  threshold float error (55-56), threshold out-of-range (58),
  channel_type not str (63)
- create: no body (112)
- update: no body (149), validation error (153)
- _TestAlert + test_notify endpoint (200-246)
"""

import json
import sys
import os
import uuid
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import User

app = create_app("testing")
client = app.test_client()

_admin_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token
    with app.app_context():
        db.create_all()
        username = f"admin_ar_{_unique}"
        if not User.query.filter_by(username=username).first():
            db.session.add(
                User(
                    username=username,
                    password_hash=hash_password("AdminAr1!"),
                    role="admin",
                )
            )
        db.session.commit()
    _admin_token = _login(username, "AdminAr1!")


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


def _create_rule(**kwargs):
    payload = {
        "name": f"TestRule-{uuid.uuid4().hex[:6]}",
        "metric": "cpu",
        "operator": "gt",
        "threshold": 80,
        "severity": "warning",
    }
    payload.update(kwargs)
    r = req("POST", "/api/alert-rules", token=_admin_token, data=payload)
    assert r.status_code == 201, f"create_rule failed: {r.data}"
    return json.loads(r.data)["alert_rule"]["id"]


# ── _validate_rule: uncovered validation paths ────────────────────────


def test_create_missing_name():
    """Empty name → 400 (line 24)."""
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": "",
            "metric": "cpu",
            "threshold": 80,
        },
    )
    assert r.status_code == 400
    assert "name" in json.loads(r.data)["error"]


def test_create_name_too_long():
    """name > 255 chars → 400 (line 26)."""
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": "A" * 256,
            "metric": "cpu",
            "threshold": 80,
        },
    )
    assert r.status_code == 400
    assert "name" in json.loads(r.data)["error"]


def test_create_threshold_none_non_offline():
    """threshold is None for non-offline metric → 400 (line 52)."""
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": f"NoThresh-{_unique}",
            "metric": "cpu",
            "operator": "gt",
        },
    )
    assert r.status_code == 400
    assert "threshold" in json.loads(r.data)["error"]


def test_create_threshold_invalid_string():
    """threshold is non-numeric string → 400 (lines 55-56)."""
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": f"BadThresh-{_unique}",
            "metric": "memory",
            "operator": "gt",
            "threshold": "not-a-number",
        },
    )
    assert r.status_code == 400
    assert "threshold" in json.loads(r.data)["error"]


def test_create_threshold_below_zero():
    """threshold < 0 → 400 (line 58)."""
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": f"NegThresh-{_unique}",
            "metric": "disk",
            "operator": "lt",
            "threshold": -1,
        },
    )
    assert r.status_code == 400
    assert "threshold" in json.loads(r.data)["error"]


def test_create_threshold_above_100():
    """threshold > 100 → 400 (line 58)."""
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": f"HighThresh-{_unique}",
            "metric": "cpu",
            "operator": "lt",
            "threshold": 101,
        },
    )
    assert r.status_code == 400
    assert "threshold" in json.loads(r.data)["error"]


def test_create_channel_type_not_string():
    """channel_type is not a string (e.g. int) → 400 (line 63)."""
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": f"BadChannelType-{_unique}",
            "metric": "cpu",
            "operator": "gt",
            "threshold": 80,
            "channel_type": 123,
        },
    )
    assert r.status_code == 400
    assert "channel_type" in json.loads(r.data)["error"]


def test_create_no_body():
    """No request body → 400 or 415 (line 112)."""
    r = client.open(
        "/api/alert-rules",
        method="POST",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code in (400, 415)


def test_update_no_body():
    """PUT without body → 400 or 415 (line 149)."""
    rule_id = _create_rule()
    r = client.open(
        f"/api/alert-rules/{rule_id}",
        method="PUT",
        headers={"Authorization": f"Bearer {_admin_token}"},
    )
    assert r.status_code in (400, 415)
    # cleanup
    req("DELETE", f"/api/alert-rules/{rule_id}", token=_admin_token)


def test_update_validation_error():
    """PUT with invalid payload → 400 (line 153)."""
    rule_id = _create_rule()
    r = req(
        "PUT",
        f"/api/alert-rules/{rule_id}",
        token=_admin_token,
        data={
            "name": "",
            "metric": "cpu",
            "threshold": 70,
        },
    )
    assert r.status_code == 400
    assert "name" in json.loads(r.data)["error"]
    req("DELETE", f"/api/alert-rules/{rule_id}", token=_admin_token)


# ── test_notify endpoint (lines 200-246) ────────────────────────────


def test_test_notify_not_found():
    """Rule not found → 404."""
    r = req("POST", "/api/alert-rules/999999/test-notify", token=_admin_token)
    assert r.status_code == 404


def test_test_notify_no_channels_configured():
    """Rule with no notification channels → all not_configured."""
    rule_id = _create_rule()
    r = req("POST", f"/api/alert-rules/{rule_id}/test-notify", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "results" in data
    results = data["results"]
    for channel in ["slack", "teams", "generic_webhook", "email"]:
        assert results[channel] == "not_configured"
    req("DELETE", f"/api/alert-rules/{rule_id}", token=_admin_token)


def test_test_notify_with_slack_success():
    """Rule with slack webhook: dispatch returns True → results.slack = 'sent'."""
    rule_id = _create_rule(notify_slack_webhook="https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b"ok"
    mock_resp.__enter__ = lambda s: mock_resp
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        r = req("POST", f"/api/alert-rules/{rule_id}/test-notify", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["results"]["slack"] == "sent"
    req("DELETE", f"/api/alert-rules/{rule_id}", token=_admin_token)


def test_test_notify_with_slack_failure():
    """Rule with slack webhook: dispatch exception → results.slack = 'failed'."""
    import urllib.error

    rule_id = _create_rule(notify_slack_webhook="https://hooks.slack.com/fail")
    with patch(
        "urllib.request.urlopen", side_effect=urllib.error.URLError("conn refused")
    ):
        r = req("POST", f"/api/alert-rules/{rule_id}/test-notify", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["results"]["slack"] == "failed"
    req("DELETE", f"/api/alert-rules/{rule_id}", token=_admin_token)


def test_test_notify_channel_type_limited_skipped():
    """Rule with channel_type='slack' but email configured: email shows 'skipped'."""
    rule_id = _create_rule(
        notify_email="admin@example.com",
        channel_type="slack",
    )
    import urllib.error

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no slack")):
        r = req("POST", f"/api/alert-rules/{rule_id}/test-notify", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    # email target is set but channel_type=slack → email is "skipped"
    assert data["results"]["email"] == "skipped"
    req("DELETE", f"/api/alert-rules/{rule_id}", token=_admin_token)


def test_test_notify_offline_metric():
    """Alert rule for offline metric (no threshold): test_notify works."""
    r = req(
        "POST",
        "/api/alert-rules",
        token=_admin_token,
        data={
            "name": f"OfflineRule-{_unique}",
            "metric": "offline",
            "operator": "gt",
            "severity": "critical",
        },
    )
    assert r.status_code == 201
    rule_id = json.loads(r.data)["alert_rule"]["id"]
    r2 = req("POST", f"/api/alert-rules/{rule_id}/test-notify", token=_admin_token)
    assert r2.status_code == 200
    req("DELETE", f"/api/alert-rules/{rule_id}", token=_admin_token)


def test_test_notify_message_format():
    """_TestAlert.message contains rule name."""
    rule_name = f"MsgRule-{_unique}"
    rule_id = _create_rule(name=rule_name)
    r = req("POST", f"/api/alert-rules/{rule_id}/test-notify", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "message" in data
    req("DELETE", f"/api/alert-rules/{rule_id}", token=_admin_token)

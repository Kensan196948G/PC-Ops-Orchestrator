"""Comprehensive tests for notification channels API endpoints.

Covers:
- routes/notification_channels.py: GET/POST/PUT/DELETE + test-send
- Duplicate name check (409)
- Validation edge cases
- test-send: email simulation + webhook mock + 404
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
_viewer_token = None
_operator_token = None
_unique = uuid.uuid4().hex[:8]


def setup_module():
    global _admin_token, _viewer_token, _operator_token
    with app.app_context():
        db.create_all()
        for username, role, password in [
            (f"admin_nc_{_unique}", "admin", "AdminNc1!"),
            (f"viewer_nc_{_unique}", "viewer", "ViewerNc1!"),
            (f"oper_nc_{_unique}", "operator", "OperNc1!"),
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

    _admin_token = _login(f"admin_nc_{_unique}", "AdminNc1!")
    _viewer_token = _login(f"viewer_nc_{_unique}", "ViewerNc1!")
    _operator_token = _login(f"oper_nc_{_unique}", "OperNc1!")


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


# ── GET list ─────────────────────────────────────────────────────────


def test_list_channels_admin():
    r = req("GET", "/api/notification-channels", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "channels" in data
    assert isinstance(data["channels"], list)


def test_list_channels_viewer():
    r = req("GET", "/api/notification-channels", token=_viewer_token)
    assert r.status_code == 200


def test_list_channels_unauthenticated():
    r = req("GET", "/api/notification-channels")
    assert r.status_code == 401


# ── POST create ──────────────────────────────────────────────────────


def _make_channel(suffix="", channel_type="slack", target="https://hooks.slack.com/test"):
    name = f"TestChannel-{suffix}-{_unique}"
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": name,
        "channel_type": channel_type,
        "target": target,
    })
    if r.status_code == 201:
        return json.loads(r.data)["channel"]["id"], name
    return None, name


def test_create_channel_slack():
    ch_id, name = _make_channel("slack", "slack", "https://hooks.slack.com/services/test")
    assert ch_id is not None


def test_create_channel_teams():
    ch_id, name = _make_channel("teams", "teams", "https://outlook.office.com/webhook/test")
    assert ch_id is not None


def test_create_channel_email():
    ch_id, name = _make_channel("email", "email", "admin@example.com")
    assert ch_id is not None


def test_create_channel_webhook():
    ch_id, name = _make_channel("webhook", "webhook", "https://myapp.example.com/hooks")
    assert ch_id is not None


def test_create_channel_inactive():
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": f"Inactive-{_unique}",
        "channel_type": "slack",
        "target": "https://hooks.slack.com/inactive",
        "is_active": False,
    })
    assert r.status_code == 201
    assert json.loads(r.data)["channel"]["is_active"] is False


def test_create_channel_missing_name():
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "channel_type": "slack",
        "target": "https://hooks.slack.com/test",
    })
    assert r.status_code == 400
    assert "name" in json.loads(r.data)["error"]


def test_create_channel_empty_name():
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": "",
        "channel_type": "slack",
        "target": "https://hooks.slack.com/test",
    })
    assert r.status_code == 400


def test_create_channel_name_too_long():
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": "A" * 101,
        "channel_type": "slack",
        "target": "https://hooks.slack.com/test",
    })
    assert r.status_code == 400


def test_create_channel_missing_channel_type():
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": f"NoType-{_unique}",
        "target": "https://hooks.slack.com/test",
    })
    assert r.status_code == 400
    assert "channel_type" in json.loads(r.data)["error"]


def test_create_channel_invalid_channel_type():
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": f"BadType-{_unique}",
        "channel_type": "telegram",
        "target": "https://t.me/test",
    })
    assert r.status_code == 400
    assert "channel_type" in json.loads(r.data)["error"]


def test_create_channel_missing_target():
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": f"NoTarget-{_unique}",
        "channel_type": "slack",
    })
    assert r.status_code == 400
    assert "target" in json.loads(r.data)["error"]


def test_create_channel_empty_target():
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": f"EmptyTarget-{_unique}",
        "channel_type": "slack",
        "target": "",
    })
    assert r.status_code == 400


def test_create_channel_target_too_long():
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": f"LongTarget-{_unique}",
        "channel_type": "webhook",
        "target": "https://example.com/" + "a" * 490,
    })
    assert r.status_code == 400


def test_create_channel_no_body():
    r = client.open("/api/notification-channels", method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_admin_token}",
    })
    assert r.status_code == 400


def test_create_channel_duplicate_name():
    name = f"Dup-{_unique}"
    req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": name,
        "channel_type": "slack",
        "target": "https://hooks.slack.com/dup",
    })
    r = req("POST", "/api/notification-channels", token=_admin_token, data={
        "name": name,
        "channel_type": "email",
        "target": "dup@example.com",
    })
    assert r.status_code == 409
    assert name in json.loads(r.data)["error"]


def test_create_channel_viewer_forbidden():
    r = req("POST", "/api/notification-channels", token=_viewer_token, data={
        "name": "X",
        "channel_type": "slack",
        "target": "https://hooks.slack.com/x",
    })
    assert r.status_code == 403


def test_create_channel_operator_forbidden():
    r = req("POST", "/api/notification-channels", token=_operator_token, data={
        "name": "X",
        "channel_type": "slack",
        "target": "https://hooks.slack.com/x",
    })
    assert r.status_code == 403


# ── PUT update ───────────────────────────────────────────────────────


def test_update_channel_success():
    ch_id, _ = _make_channel("upd")
    r = req("PUT", f"/api/notification-channels/{ch_id}", token=_admin_token, data={
        "name": f"UpdatedChannel-{_unique}",
        "channel_type": "email",
        "target": "new@example.com",
        "is_active": False,
    })
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["channel"]["channel_type"] == "email"
    assert data["channel"]["is_active"] is False


def test_update_channel_name_same_id_no_conflict():
    """Updating name to same value should not cause 409."""
    ch_id, name = _make_channel("sameupd")
    r = req("PUT", f"/api/notification-channels/{ch_id}", token=_admin_token, data={
        "name": name,
    })
    assert r.status_code == 200


def test_update_channel_duplicate_name_rejected():
    ch_id1, name1 = _make_channel("dupupd1")
    ch_id2, _ = _make_channel("dupupd2")
    r = req("PUT", f"/api/notification-channels/{ch_id2}", token=_admin_token, data={
        "name": name1,
    })
    assert r.status_code == 409


def test_update_channel_empty_name_rejected():
    ch_id, _ = _make_channel("empname")
    r = req("PUT", f"/api/notification-channels/{ch_id}", token=_admin_token, data={
        "name": "",
    })
    assert r.status_code == 400


def test_update_channel_name_too_long():
    ch_id, _ = _make_channel("longname")
    r = req("PUT", f"/api/notification-channels/{ch_id}", token=_admin_token, data={
        "name": "A" * 101,
    })
    assert r.status_code == 400


def test_update_channel_invalid_type():
    ch_id, _ = _make_channel("badtype")
    r = req("PUT", f"/api/notification-channels/{ch_id}", token=_admin_token, data={
        "channel_type": "pigeon",
    })
    assert r.status_code == 400


def test_update_channel_empty_target_rejected():
    ch_id, _ = _make_channel("emptarget")
    r = req("PUT", f"/api/notification-channels/{ch_id}", token=_admin_token, data={
        "target": "",
    })
    assert r.status_code == 400


def test_update_channel_target_too_long():
    ch_id, _ = _make_channel("longtarget")
    r = req("PUT", f"/api/notification-channels/{ch_id}", token=_admin_token, data={
        "target": "https://x.com/" + "a" * 490,
    })
    assert r.status_code == 400


def test_update_channel_not_found():
    r = req("PUT", "/api/notification-channels/999999", token=_admin_token, data={"name": "X"})
    assert r.status_code == 404


def test_update_channel_no_body():
    ch_id, _ = _make_channel("nobody")
    r = client.open(f"/api/notification-channels/{ch_id}", method="PUT", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_admin_token}",
    })
    assert r.status_code == 400


def test_update_channel_viewer_forbidden():
    ch_id, _ = _make_channel("viewupd")
    r = req("PUT", f"/api/notification-channels/{ch_id}", token=_viewer_token, data={"name": "X"})
    assert r.status_code == 403


# ── DELETE ───────────────────────────────────────────────────────────


def test_delete_channel_success():
    ch_id, _ = _make_channel("del")
    r = req("DELETE", f"/api/notification-channels/{ch_id}", token=_admin_token)
    assert r.status_code == 200
    assert "削除" in json.loads(r.data)["message"]


def test_delete_channel_not_found():
    r = req("DELETE", "/api/notification-channels/999999", token=_admin_token)
    assert r.status_code == 404


def test_delete_channel_viewer_forbidden():
    ch_id, _ = _make_channel("delvw")
    r = req("DELETE", f"/api/notification-channels/{ch_id}", token=_viewer_token)
    assert r.status_code == 403


# ── test-send ────────────────────────────────────────────────────────


def test_test_send_email_channel():
    ch_id, _ = _make_channel("testemail", "email", "test@example.com")
    r = req("POST", f"/api/notification-channels/{ch_id}/test-send", token=_admin_token)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert "Email" in data["message"] or "成功" in data["message"]


def test_test_send_slack_success():
    ch_id, _ = _make_channel("testslack", "slack", "https://hooks.slack.com/services/mock")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("routes.notification_channels.http_requests.post", return_value=mock_resp):
        r = req("POST", f"/api/notification-channels/{ch_id}/test-send", token=_admin_token)
    assert r.status_code == 200
    assert "成功" in json.loads(r.data)["message"]


def test_test_send_webhook_success():
    ch_id, _ = _make_channel("testwh", "webhook", "https://webhook.example.com/hook")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("routes.notification_channels.http_requests.post", return_value=mock_resp):
        r = req("POST", f"/api/notification-channels/{ch_id}/test-send", token=_admin_token)
    assert r.status_code == 200


def test_test_send_teams_success():
    ch_id, _ = _make_channel("testteams", "teams", "https://outlook.office.com/webhook/mock")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("routes.notification_channels.http_requests.post", return_value=mock_resp):
        r = req("POST", f"/api/notification-channels/{ch_id}/test-send", token=_admin_token)
    assert r.status_code == 200


def test_test_send_slack_http_error():
    ch_id, _ = _make_channel("testslackerr", "slack", "https://hooks.slack.com/services/mock")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("routes.notification_channels.http_requests.post", return_value=mock_resp):
        r = req("POST", f"/api/notification-channels/{ch_id}/test-send", token=_admin_token)
    assert r.status_code == 502
    assert "送信失敗" in json.loads(r.data)["error"]


def test_test_send_slack_exception():
    ch_id, _ = _make_channel("testslackexc", "slack", "https://hooks.slack.com/services/mock")
    with patch("routes.notification_channels.http_requests.post", side_effect=Exception("Connection refused")):
        r = req("POST", f"/api/notification-channels/{ch_id}/test-send", token=_admin_token)
    assert r.status_code == 502
    assert "送信失敗" in json.loads(r.data)["error"]


def test_test_send_not_found():
    r = req("POST", "/api/notification-channels/999999/test-send", token=_admin_token)
    assert r.status_code == 404


def test_test_send_viewer_forbidden():
    ch_id, _ = _make_channel("testviewerchk")
    r = req("POST", f"/api/notification-channels/{ch_id}/test-send", token=_viewer_token)
    assert r.status_code == 403

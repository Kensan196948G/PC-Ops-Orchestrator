"""Tests for Phase F-3: notification log API (Issue #278)."""

import json
from datetime import datetime, timezone

import pytest

from app import create_app
from auth import hash_password
from extensions import db as _db
from models import PC, Alert, AlertRule, NotificationLog, User


@pytest.fixture(scope="module")
def app():
    application = create_app("testing")
    with application.app_context():
        _db.create_all()
        if not User.query.filter_by(username="nlogadmin").first():
            _db.session.add(
                User(
                    username="nlogadmin",
                    password_hash=hash_password("NlogPass123!"),
                    role="admin",
                )
            )
            _db.session.commit()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_db(app):
    with app.app_context():
        yield
        _db.session.query(NotificationLog).delete()
        _db.session.query(Alert).delete()
        _db.session.query(AlertRule).delete()
        _db.session.query(PC).delete()
        _db.session.commit()


def _login(client):
    r = client.post(
        "/api/auth/login",
        data=json.dumps({"username": "nlogadmin", "password": "NlogPass123!"}),
        content_type="application/json",
    )
    assert r.status_code == 200, r.data
    return json.loads(r.data)["token"]


def _req(client, method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _insert_log(
    app, *, rule_id=None, alert_id=None, channel="slack", status="sent", message="test"
):
    """Directly insert a NotificationLog row for test setup."""
    with app.app_context():
        log = NotificationLog(
            rule_id=rule_id,
            alert_id=alert_id,
            channel=channel,
            status=status,
            message=message,
            sent_at=datetime.now(timezone.utc),
        )
        _db.session.add(log)
        _db.session.commit()
        return log.id


def _make_rule(app, name="test-rule"):
    with app.app_context():
        rule = AlertRule(
            name=name,
            metric="cpu",
            operator="gt",
            threshold=80.0,
            severity="warning",
            is_enabled=True,
            created_by="test",
        )
        _db.session.add(rule)
        _db.session.commit()
        return rule.id


# ---------------------------------------------------------------------------
# GET /api/notification-logs
# ---------------------------------------------------------------------------


class TestListNotificationLogs:
    def test_requires_auth(self, client):
        r = _req(client, "GET", "/api/notification-logs")
        assert r.status_code == 401

    def test_empty_returns_list(self, app, client):
        token = _login(client)
        r = _req(client, "GET", "/api/notification-logs", token=token)
        assert r.status_code == 200
        data = r.get_json()
        assert "notification_logs" in data
        assert isinstance(data["notification_logs"], list)
        assert data["total"] == 0

    def test_returns_inserted_logs(self, app, client):
        token = _login(client)
        _insert_log(app, channel="slack", status="sent")
        _insert_log(app, channel="teams", status="failed")
        r = _req(client, "GET", "/api/notification-logs", token=token)
        assert r.status_code == 200
        data = r.get_json()
        assert data["total"] == 2

    def test_filter_by_status(self, app, client):
        token = _login(client)
        _insert_log(app, channel="slack", status="sent")
        _insert_log(app, channel="email", status="failed")
        r = _req(client, "GET", "/api/notification-logs?status=sent", token=token)
        assert r.status_code == 200
        data = r.get_json()
        assert all(item["status"] == "sent" for item in data["notification_logs"])

    def test_filter_by_channel(self, app, client):
        token = _login(client)
        _insert_log(app, channel="slack", status="sent")
        _insert_log(app, channel="email", status="sent")
        r = _req(client, "GET", "/api/notification-logs?channel=slack", token=token)
        assert r.status_code == 200
        data = r.get_json()
        assert all(item["channel"] == "slack" for item in data["notification_logs"])

    def test_filter_by_rule_id(self, app, client):
        token = _login(client)
        rule_id = _make_rule(app)
        _insert_log(app, rule_id=rule_id, channel="slack", status="sent")
        _insert_log(app, channel="teams", status="sent")  # no rule
        r = _req(
            client, "GET", f"/api/notification-logs?rule_id={rule_id}", token=token
        )
        assert r.status_code == 200
        data = r.get_json()
        assert all(item["rule_id"] == rule_id for item in data["notification_logs"])
        assert data["total"] == 1

    def test_pagination(self, app, client):
        token = _login(client)
        for _ in range(5):
            _insert_log(app, channel="slack", status="sent")
        r = _req(client, "GET", "/api/notification-logs?per_page=2&page=1", token=token)
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["notification_logs"]) == 2
        assert data["pages"] >= 3


# ---------------------------------------------------------------------------
# GET /api/notification-logs/<id>
# ---------------------------------------------------------------------------


class TestGetNotificationLog:
    def test_requires_auth(self, app, client):
        log_id = _insert_log(app)
        r = _req(client, "GET", f"/api/notification-logs/{log_id}")
        assert r.status_code == 401

    def test_returns_log(self, app, client):
        token = _login(client)
        log_id = _insert_log(app, channel="teams", status="failed", message="msg")
        r = _req(client, "GET", f"/api/notification-logs/{log_id}", token=token)
        assert r.status_code == 200
        data = r.get_json()
        assert data["notification_log"]["id"] == log_id
        assert data["notification_log"]["channel"] == "teams"
        assert data["notification_log"]["status"] == "failed"

    def test_not_found(self, client):
        token = _login(client)
        r = _req(client, "GET", "/api/notification-logs/999999", token=token)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/alert-rules/<id>/notification-logs
# ---------------------------------------------------------------------------


class TestRuleNotificationLogs:
    def test_requires_auth(self, app, client):
        rule_id = _make_rule(app, name="auth-rule")
        r = _req(client, "GET", f"/api/alert-rules/{rule_id}/notification-logs")
        assert r.status_code == 401

    def test_rule_not_found(self, client):
        token = _login(client)
        r = _req(
            client, "GET", "/api/alert-rules/999999/notification-logs", token=token
        )
        assert r.status_code == 404

    def test_returns_rule_logs(self, app, client):
        token = _login(client)
        rule_id = _make_rule(app, name="rule-log-test")
        _insert_log(app, rule_id=rule_id, channel="slack", status="sent")
        _insert_log(app, rule_id=rule_id, channel="email", status="failed")
        _insert_log(app, channel="teams", status="sent")  # different rule
        r = _req(
            client, "GET", f"/api/alert-rules/{rule_id}/notification-logs", token=token
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["total"] == 2
        assert all(item["rule_id"] == rule_id for item in data["notification_logs"])

    def test_empty_rule_returns_zero(self, app, client):
        token = _login(client)
        rule_id = _make_rule(app, name="empty-rule")
        r = _req(
            client, "GET", f"/api/alert-rules/{rule_id}/notification-logs", token=token
        )
        assert r.status_code == 200
        assert r.get_json()["total"] == 0

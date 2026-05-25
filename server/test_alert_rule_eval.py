"""Tests for Phase F-2: alert rule evaluation loop (Issue #275).

Coverage:
  - evaluate_rules_once() logic (operator, metric, dedup)
  - POST /api/alert-rules/<id>/evaluate endpoint
"""

import json

import pytest

from app import create_app
from auth import hash_password
from extensions import db as _db
from models import Alert, AlertRule, PC, SystemSnapshot, User


@pytest.fixture(scope="module")
def app():
    application = create_app("testing")
    with application.app_context():
        _db.create_all()
        if not User.query.filter_by(username="evaladmin").first():
            _db.session.add(
                User(
                    username="evaladmin",
                    password_hash=hash_password("EvalPass123!"),
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
        _db.session.query(Alert).delete()
        _db.session.query(AlertRule).delete()
        _db.session.query(SystemSnapshot).delete()
        _db.session.query(PC).delete()
        _db.session.commit()


def _login(client):
    r = client.post(
        "/api/auth/login",
        data=json.dumps({"username": "evaladmin", "password": "EvalPass123!"}),
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


def _make_pc(app, name="EVPC01", cpu=80.0, memory_gb=4.0, disk_gb=10.0):
    with app.app_context():
        pc = PC(pc_name=name, memory_available_gb=memory_gb, disk_free_gb=disk_gb)
        _db.session.add(pc)
        _db.session.flush()
        if cpu is not None:
            snap = SystemSnapshot(pc_id=pc.id, cpu_usage=cpu)
            _db.session.add(snap)
        _db.session.commit()
        return pc.id


def _make_rule(app, metric="cpu", operator="gt", threshold=70.0, enabled=True):
    with app.app_context():
        rule = AlertRule(
            name=f"rule-{metric}-{operator}",
            metric=metric,
            operator=operator,
            threshold=threshold,
            severity="warning",
            is_enabled=enabled,
            created_by="test",
        )
        _db.session.add(rule)
        _db.session.commit()
        return rule.id


# ─── evaluate_rules_once() unit tests ────────────────────────────────────────


class TestEvaluateRulesOnce:
    def test_cpu_gt_triggers(self, app):
        pc_id = _make_pc(app, cpu=90.0)
        rule_id = _make_rule(app, metric="cpu", operator="gt", threshold=80.0)
        with app.app_context():
            from scheduler import evaluate_rules_once

            count = evaluate_rules_once(_db, Alert, AlertRule, SystemSnapshot, PC)
        assert count == 1
        with app.app_context():
            alert = Alert.query.filter_by(pc_id=pc_id, alert_rule_id=rule_id).first()
            assert alert is not None
            assert alert.alert_type == "rule_cpu"

    def test_cpu_below_threshold_no_alert(self, app):
        _make_pc(app, cpu=50.0)
        _make_rule(app, metric="cpu", operator="gt", threshold=80.0)
        with app.app_context():
            from scheduler import evaluate_rules_once

            count = evaluate_rules_once(_db, Alert, AlertRule, SystemSnapshot, PC)
        assert count == 0

    def test_memory_lte_triggers(self, app):
        _make_pc(app, memory_gb=1.0)
        _make_rule(app, metric="memory", operator="lte", threshold=2.0)
        with app.app_context():
            from scheduler import evaluate_rules_once

            count = evaluate_rules_once(_db, Alert, AlertRule, SystemSnapshot, PC)
        assert count == 1

    def test_disk_lte_triggers(self, app):
        _make_pc(app, disk_gb=3.0)
        _make_rule(app, metric="disk", operator="lte", threshold=5.0)
        with app.app_context():
            from scheduler import evaluate_rules_once

            count = evaluate_rules_once(_db, Alert, AlertRule, SystemSnapshot, PC)
        assert count == 1

    def test_deduplication_no_duplicate_alert(self, app):
        pc_id = _make_pc(app, cpu=95.0)
        rule_id = _make_rule(app, metric="cpu", operator="gt", threshold=80.0)
        with app.app_context():
            from scheduler import evaluate_rules_once

            count1 = evaluate_rules_once(_db, Alert, AlertRule, SystemSnapshot, PC)
            count2 = evaluate_rules_once(_db, Alert, AlertRule, SystemSnapshot, PC)
        assert count1 == 1
        assert count2 == 0  # already exists unresolved
        with app.app_context():
            assert (
                Alert.query.filter_by(pc_id=pc_id, alert_rule_id=rule_id).count() == 1
            )

    def test_disabled_rule_skipped(self, app):
        _make_pc(app, cpu=99.0)
        _make_rule(app, metric="cpu", operator="gt", threshold=50.0, enabled=False)
        with app.app_context():
            from scheduler import evaluate_rules_once

            count = evaluate_rules_once(_db, Alert, AlertRule, SystemSnapshot, PC)
        assert count == 0

    def test_no_cpu_snapshot_no_alert(self, app):
        _make_pc(app, cpu=None)
        _make_rule(app, metric="cpu", operator="gt", threshold=50.0)
        with app.app_context():
            from scheduler import evaluate_rules_once

            count = evaluate_rules_once(_db, Alert, AlertRule, SystemSnapshot, PC)
        assert count == 0


# ─── POST /api/alert-rules/<id>/evaluate endpoint tests ──────────────────────


class TestEvaluateEndpoint:
    def test_evaluate_creates_alert(self, app, client):
        token = _login(client)
        _make_pc(app, name="EVPC02", cpu=95.0)
        rule_id = _make_rule(app, metric="cpu", operator="gt", threshold=80.0)
        resp = _req(client, "POST", f"/api/alert-rules/{rule_id}/evaluate", token=token)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["alerts_created"] == 1
        assert data["rule_id"] == rule_id

    def test_evaluate_not_found(self, app, client):
        token = _login(client)
        resp = _req(client, "POST", "/api/alert-rules/999999/evaluate", token=token)
        assert resp.status_code == 404

    def test_evaluate_below_threshold_zero(self, app, client):
        token = _login(client)
        _make_pc(app, name="EVPC03", cpu=30.0)
        rule_id = _make_rule(app, metric="cpu", operator="gt", threshold=80.0)
        resp = _req(client, "POST", f"/api/alert-rules/{rule_id}/evaluate", token=token)
        assert resp.status_code == 200
        assert resp.get_json()["alerts_created"] == 0

    def test_evaluate_requires_auth(self, app):
        rule_id = _make_rule(app, metric="cpu", operator="gt", threshold=80.0)
        fresh_client = app.test_client()
        resp = fresh_client.post(f"/api/alert-rules/{rule_id}/evaluate")
        assert resp.status_code in (401, 403)

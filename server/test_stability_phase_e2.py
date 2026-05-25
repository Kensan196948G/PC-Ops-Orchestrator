"""Tests for Phase E-2 — AppResponseLog, Trends, Incidents (Issues #247, #252, #253)."""

import json
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import (
    PC,
    AppResponseLog,
    NotificationChannel,
    StabilityScore,
    User,
)

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.first():
            admin = User(
                username="admin_e2",
                password_hash=hash_password("admin"),
                role="admin",
            )
            db.session.add(admin)
            db.session.commit()


def _login():
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "admin_e2", "password": "admin"}),
    )
    assert r.status_code == 200, r.data
    return json.loads(r.data)["token"]


def _req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _make_pc(name):
    with app.app_context():
        existing = PC.query.filter_by(pc_name=name).first()
        if existing:
            return existing.id
        pc = PC(pc_name=name, ip_address="10.1.1.1", os_version="Windows 11")
        db.session.add(pc)
        db.session.commit()
        return pc.id


def _add_app_response(pc_id, app_name, ms, is_slow=False, hours_ago=1):
    with app.app_context():
        log = AppResponseLog(
            pc_id=pc_id,
            app_name=app_name,
            response_time_ms=ms,
            is_slow=is_slow,
            recorded_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        )
        db.session.add(log)
        db.session.commit()
        return log.id


def _add_stability_score(pc_id, score, hours_ago=0):
    with app.app_context():
        ss = StabilityScore(
            pc_id=pc_id,
            score=score,
            calculated_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        )
        db.session.add(ss)
        db.session.commit()
        return ss.id


def _add_notification_channel(name, ch_type, target):
    with app.app_context():
        existing = NotificationChannel.query.filter_by(name=name).first()
        if existing:
            return existing.id
        ch = NotificationChannel(name=name, channel_type=ch_type, target=target, is_active=True)
        db.session.add(ch)
        db.session.commit()
        return ch.id


# ---------------------------------------------------------------------------
# Issue #247 — App Response Monitoring
# ---------------------------------------------------------------------------


class TestAppResponseSummary:
    def test_get_summary_requires_auth(self):
        r = _req("GET", "/api/stability/app-response")
        assert r.status_code == 401

    def test_get_summary_empty(self):
        token = _login()
        r = _req("GET", "/api/stability/app-response", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "apps" in data
        assert "hours" in data

    def test_get_summary_with_records(self):
        token = _login()
        pc_id = _make_pc("APP-RESP-SUMMARY-PC")
        _add_app_response(pc_id, "chrome.exe", 200, is_slow=False)
        _add_app_response(pc_id, "chrome.exe", 3000, is_slow=True)
        _add_app_response(pc_id, "excel.exe", 500, is_slow=False)

        r = _req("GET", "/api/stability/app-response?hours=24", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        app_names = [a["app_name"] for a in data["apps"]]
        assert "chrome.exe" in app_names

    def test_get_summary_slow_count_and_rate(self):
        token = _login()
        pc_id = _make_pc("APP-RESP-RATE-PC")
        _add_app_response(pc_id, "slowapp.exe", 5000, is_slow=True)
        _add_app_response(pc_id, "slowapp.exe", 5500, is_slow=True)
        _add_app_response(pc_id, "slowapp.exe", 100, is_slow=False)

        r = _req("GET", "/api/stability/app-response?hours=24", token=token)
        data = json.loads(r.data)
        app = next((a for a in data["apps"] if a["app_name"] == "slowapp.exe"), None)
        assert app is not None
        assert app["slow_count"] == 2
        assert app["total_records"] == 3


class TestAppResponseByPC:
    def test_get_by_pc_not_found(self):
        token = _login()
        r = _req("GET", "/api/stability/app-response/99999", token=token)
        assert r.status_code == 404

    def test_get_by_pc_empty(self):
        token = _login()
        pc_id = _make_pc("APP-RESP-PC-EMPTY")
        r = _req("GET", f"/api/stability/app-response/{pc_id}", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["pc_id"] == pc_id
        assert "summary" in data
        assert "history" in data

    def test_get_by_pc_with_records(self):
        token = _login()
        pc_id = _make_pc("APP-RESP-PC-DATA")
        _add_app_response(pc_id, "word.exe", 400, hours_ago=1)
        _add_app_response(pc_id, "word.exe", 800, is_slow=True, hours_ago=2)

        r = _req("GET", f"/api/stability/app-response/{pc_id}?hours=24", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert len(data["history"]) >= 2
        assert len(data["summary"]) >= 1

    def test_get_by_pc_limit_history(self):
        token = _login()
        pc_id = _make_pc("APP-RESP-PC-LIMIT")
        for i in range(5):
            _add_app_response(pc_id, "testapp.exe", 100 * i, hours_ago=i)

        r = _req("GET", f"/api/stability/app-response/{pc_id}?limit=3", token=token)
        data = json.loads(r.data)
        assert len(data["history"]) <= 3


class TestAppResponseRecord:
    def test_post_single_record(self):
        token = _login()
        pc_id = _make_pc("APP-RESP-POST-SINGLE")
        payload = {"app_name": "notepad.exe", "response_time_ms": 150}
        r = _req("POST", f"/api/stability/app-response/{pc_id}", token=token, data=payload)
        assert r.status_code == 201
        data = json.loads(r.data)
        assert data["created"] == 1
        assert data["errors"] == []

    def test_post_batch_records(self):
        token = _login()
        pc_id = _make_pc("APP-RESP-POST-BATCH")
        payload = [
            {"app_name": "app1.exe", "response_time_ms": 200},
            {"app_name": "app2.exe", "response_time_ms": 3000, "threshold_ms": 2000},
        ]
        r = _req("POST", f"/api/stability/app-response/{pc_id}", token=token, data=payload)
        assert r.status_code == 201
        data = json.loads(r.data)
        assert data["created"] == 2

    def test_post_record_auto_is_slow_from_threshold(self):
        token = _login()
        pc_id = _make_pc("APP-RESP-THRESHOLD")
        payload = {"app_name": "myapp.exe", "response_time_ms": 5000, "threshold_ms": 2000}
        r = _req("POST", f"/api/stability/app-response/{pc_id}", token=token, data=payload)
        assert r.status_code == 201

        with app.app_context():
            log = AppResponseLog.query.filter_by(
                pc_id=pc_id, app_name="myapp.exe"
            ).order_by(AppResponseLog.id.desc()).first()
            assert log is not None
            assert log.is_slow is True

    def test_post_record_missing_app_name_returns_error(self):
        token = _login()
        pc_id = _make_pc("APP-RESP-MISSING-NAME")
        payload = {"response_time_ms": 100}
        r = _req("POST", f"/api/stability/app-response/{pc_id}", token=token, data=payload)
        assert r.status_code == 201
        data = json.loads(r.data)
        assert data["created"] == 0
        assert len(data["errors"]) == 1

    def test_post_to_nonexistent_pc(self):
        token = _login()
        payload = {"app_name": "test.exe", "response_time_ms": 100}
        r = _req("POST", "/api/stability/app-response/99998", token=token, data=payload)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Issue #253 — Trends detection
# ---------------------------------------------------------------------------


class TestStabilityTrends:
    def test_trends_requires_auth(self):
        r = _req("GET", "/api/stability/trends")
        assert r.status_code == 401

    def test_trends_empty_no_scores(self):
        token = _login()
        r = _req("GET", "/api/stability/trends", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "at_risk" in data
        assert "at_risk_count" in data

    def test_trends_detects_declining_pc(self):
        token = _login()
        pc_id = _make_pc("TREND-DECLINING-PC")
        # Add scores with declining trend (oldest → newest order within hours)
        _add_stability_score(pc_id, 90.0, hours_ago=4)
        _add_stability_score(pc_id, 75.0, hours_ago=3)
        _add_stability_score(pc_id, 60.0, hours_ago=2)
        _add_stability_score(pc_id, 45.0, hours_ago=1)
        _add_stability_score(pc_id, 30.0, hours_ago=0)

        r = _req("GET", "/api/stability/trends?snapshots=5&min_drop=10", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        pc_ids = [item["pc_id"] for item in data["at_risk"]]
        assert pc_id in pc_ids

    def test_trends_stable_pc_not_flagged(self):
        token = _login()
        pc_id = _make_pc("TREND-STABLE-PC")
        _add_stability_score(pc_id, 85.0, hours_ago=4)
        _add_stability_score(pc_id, 86.0, hours_ago=3)
        _add_stability_score(pc_id, 84.0, hours_ago=2)
        _add_stability_score(pc_id, 87.0, hours_ago=1)
        _add_stability_score(pc_id, 85.5, hours_ago=0)

        r = _req("GET", "/api/stability/trends?snapshots=5&min_drop=10", token=token)
        data = json.loads(r.data)
        pc_ids = [item["pc_id"] for item in data["at_risk"]]
        assert pc_id not in pc_ids

    def test_trends_min_drop_param(self):
        token = _login()
        r = _req("GET", "/api/stability/trends?min_drop=50", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["min_drop"] == 50.0

    def test_trends_response_has_required_fields(self):
        token = _login()
        pc_id = _make_pc("TREND-FIELDS-PC")
        _add_stability_score(pc_id, 80.0, hours_ago=2)
        _add_stability_score(pc_id, 50.0, hours_ago=1)

        r = _req("GET", "/api/stability/trends?snapshots=5&min_drop=10", token=token)
        data = json.loads(r.data)
        if data["at_risk"]:
            item = data["at_risk"][0]
            assert "pc_id" in item
            assert "pc_name" in item
            assert "first_score" in item
            assert "latest_score" in item
            assert "drop" in item


class TestTrendsNotify:
    def test_notify_requires_auth(self):
        r = _req("POST", "/api/stability/trends/notify")
        assert r.status_code == 401

    def test_notify_no_at_risk(self):
        token = _login()
        r = _req("POST", "/api/stability/trends/notify", token=token, data={})
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["sent"] == 0

    def test_notify_sends_to_active_channels(self):
        token = _login()
        pc_id = _make_pc("NOTIFY-DECLINING-PC")
        _add_stability_score(pc_id, 90.0, hours_ago=4)
        _add_stability_score(pc_id, 50.0, hours_ago=0)

        ch_id = _add_notification_channel(
            "test-slack-notify", "slack", "https://hooks.slack.com/test"
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("routes.stability.http_requests.post", return_value=mock_resp) as mock_post:
            r = _req(
                "POST",
                "/api/stability/trends/notify",
                token=token,
                data={"snapshots": 5, "min_drop": 10},
            )
            assert r.status_code == 200
            data = json.loads(r.data)
            assert "sent" in data
            assert "results" in data

    def test_notify_channel_ids_filter(self):
        token = _login()
        r = _req(
            "POST",
            "/api/stability/trends/notify",
            token=token,
            data={"channel_ids": [99999]},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Issue #252 — Auto Incident Filing
# ---------------------------------------------------------------------------


class TestStabilityIncidents:
    def test_incidents_requires_auth(self):
        r = _req("GET", "/api/stability/incidents")
        assert r.status_code == 401

    def test_incidents_empty(self):
        token = _login()
        r = _req("GET", "/api/stability/incidents", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "pcs" in data
        assert "threshold" in data

    def test_incidents_detects_critical_pc(self):
        token = _login()
        pc_id = _make_pc("INCIDENT-CRITICAL-PC")
        _add_stability_score(pc_id, 25.0, hours_ago=0)

        r = _req("GET", "/api/stability/incidents?threshold=40", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        pc_ids = [p["pc_id"] for p in data["pcs"]]
        assert pc_id in pc_ids

    def test_incidents_ignores_healthy_pc(self):
        token = _login()
        pc_id = _make_pc("INCIDENT-HEALTHY-PC")
        _add_stability_score(pc_id, 90.0, hours_ago=0)

        r = _req("GET", "/api/stability/incidents?threshold=40", token=token)
        data = json.loads(r.data)
        pc_ids = [p["pc_id"] for p in data["pcs"]]
        assert pc_id not in pc_ids

    def test_incidents_response_has_required_fields(self):
        token = _login()
        pc_id = _make_pc("INCIDENT-FIELDS-PC")
        _add_stability_score(pc_id, 10.0, hours_ago=0)

        r = _req("GET", "/api/stability/incidents", token=token)
        data = json.loads(r.data)
        if data["pcs"]:
            item = data["pcs"][0]
            assert "pc_id" in item
            assert "pc_name" in item
            assert "score" in item
            assert "calculated_at" in item


class TestIncidentsAutoFile:
    def test_auto_file_requires_auth(self):
        r = _req("POST", "/api/stability/incidents/auto-file")
        assert r.status_code == 401

    def test_auto_file_dry_run_no_critical(self):
        token = _login()
        r = _req(
            "POST",
            "/api/stability/incidents/auto-file",
            token=token,
            data={"dry_run": True, "threshold": 40},
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["dry_run"] is True

    def test_auto_file_dry_run_shows_candidates(self):
        token = _login()
        pc_id = _make_pc("AUTO-FILE-DRY-PC")
        _add_stability_score(pc_id, 15.0, hours_ago=0)

        r = _req(
            "POST",
            "/api/stability/incidents/auto-file",
            token=token,
            data={"dry_run": True, "threshold": 40},
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["dry_run"] is True
        assert data["would_file"] >= 1
        pc_ids = [c["pc_id"] for c in data["candidates"]]
        assert pc_id in pc_ids

    def test_auto_file_missing_repo_returns_error(self):
        token = _login()
        r = _req(
            "POST",
            "/api/stability/incidents/auto-file",
            token=token,
            data={"dry_run": False, "token": "ghp_fake"},
        )
        assert r.status_code == 400

    def test_auto_file_missing_token_returns_error(self):
        token = _login()
        r = _req(
            "POST",
            "/api/stability/incidents/auto-file",
            token=token,
            data={"dry_run": False, "repo": "owner/repo"},
        )
        assert r.status_code == 400

    def test_auto_file_calls_github_api(self):
        token = _login()
        pc_id = _make_pc("AUTO-FILE-GITHUB-PC")
        _add_stability_score(pc_id, 10.0, hours_ago=0)

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"html_url": "https://github.com/owner/repo/issues/1"}
        with patch("routes.stability.http_requests.post", return_value=mock_resp):
            r = _req(
                "POST",
                "/api/stability/incidents/auto-file",
                token=token,
                data={
                    "dry_run": False,
                    "repo": "owner/repo",
                    "token": "ghp_fake_token",
                    "threshold": 40,
                },
            )
            assert r.status_code == 200
            data = json.loads(r.data)
            assert data["filed"] >= 1
            assert data["dry_run"] is False

    def test_auto_file_github_api_error_handled(self):
        token = _login()
        pc_id = _make_pc("AUTO-FILE-ERR-PC")
        _add_stability_score(pc_id, 5.0, hours_ago=0)

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {}
        with patch("routes.stability.http_requests.post", return_value=mock_resp):
            r = _req(
                "POST",
                "/api/stability/incidents/auto-file",
                token=token,
                data={
                    "dry_run": False,
                    "repo": "owner/repo",
                    "token": "ghp_fake_token",
                    "threshold": 40,
                },
            )
            assert r.status_code == 200
            data = json.loads(r.data)
            assert data["filed"] == 0

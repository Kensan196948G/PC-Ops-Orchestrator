"""Tests for PC Stability Insight API — Phase D-1/D-2 (Issues #238, #239)."""

import json
import sys
import os
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import (
    PC,
    EventLog,
    KnownIssue,
    StabilityScore,
    WindowsUpdate,
    User,
)

app = create_app("testing")
client = app.test_client()


def setup_module():
    with app.app_context():
        db.create_all()
        if not User.query.first():
            admin = User(
                username="admin",
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
        data=json.dumps({"username": "admin", "password": "admin"}),
    )
    assert r.status_code == 200
    return json.loads(r.data)["token"]


def _req(method, path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _make_pc(name="STABLE-PC-001"):
    with app.app_context():
        pc = PC(pc_name=name, ip_address="10.0.0.1", os_version="Windows 11")
        db.session.add(pc)
        db.session.commit()
        return pc.id


def _make_event_log(pc_id, event_id, days_ago=1):
    with app.app_context():
        ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
        ev = EventLog(
            pc_id=pc_id,
            log_type="System",
            event_id=event_id,
            source="System",
            message="test",
            generated_at=ts,
            collected_at=ts,
        )
        db.session.add(ev)
        db.session.commit()
        return ev.id


def _make_update(pc_id, kb_id, installed=True, days_ago=5):
    with app.app_context():
        ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
        wu = WindowsUpdate(
            pc_id=pc_id,
            kb_id=kb_id,
            title=f"Update for {kb_id}",
            severity="Important",
            installed=installed,
            installed_at=ts if installed else None,
        )
        db.session.add(wu)
        db.session.commit()
        return wu.id


# ── Phase D-1: Score and calculate endpoints ────────────────────────────────

class TestScoresList:
    def test_list_scores_requires_auth(self):
        r = _req("GET", "/api/stability/scores")
        assert r.status_code == 401

    def test_list_scores_returns_list(self):
        token = _login()
        r = _req("GET", "/api/stability/scores", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert isinstance(data, list)

    def test_list_scores_has_expected_fields(self):
        token = _login()
        _make_pc("SCORE-PC-001")
        r = _req("GET", "/api/stability/scores", token=token)
        data = json.loads(r.data)
        if data:
            item = data[0]
            assert "pc_id" in item
            assert "pc_name" in item
            assert "stability_score" in item
            assert "status" in item


class TestGetScore:
    def test_get_score_requires_auth(self):
        pc_id = _make_pc("GET-SCORE-AUTH")
        r = _req("GET", f"/api/stability/scores/{pc_id}")
        assert r.status_code == 401

    def test_get_score_for_existing_pc(self):
        token = _login()
        pc_id = _make_pc("GET-SCORE-PC-OK")
        r = _req("GET", f"/api/stability/scores/{pc_id}", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["pc_id"] == pc_id
        assert "current_score" in data
        assert "status" in data
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_get_score_404_for_missing_pc(self):
        token = _login()
        r = _req("GET", "/api/stability/scores/999999", token=token)
        assert r.status_code == 404

    def test_get_score_shows_healthy_when_no_events(self):
        token = _login()
        pc_id = _make_pc("HEALTHY-PC")
        r = _req("GET", f"/api/stability/scores/{pc_id}", token=token)
        data = json.loads(r.data)
        assert data["current_score"] == 100.0
        assert data["status"] == "healthy"


class TestCalculateAll:
    def test_calculate_requires_auth(self):
        r = _req("POST", "/api/stability/calculate")
        assert r.status_code == 401

    def test_calculate_all_pcs(self):
        token = _login()
        _make_pc("CALC-PC-001")
        r = _req("POST", "/api/stability/calculate", token=token, data={})
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "calculated" in data
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_calculate_all_with_events_reduces_score(self):
        token = _login()
        pc_id = _make_pc("BSOD-PC")
        # BugCheck (event_id=1001) causes 30-point deduction
        _make_event_log(pc_id, 1001, days_ago=1)
        r = _req("POST", "/api/stability/calculate", token=token, data={"days": 7})
        assert r.status_code == 200
        data = json.loads(r.data)
        pc_result = next((x for x in data["results"] if x["pc_id"] == pc_id), None)
        assert pc_result is not None
        assert pc_result["score"] < 100.0


class TestCalculateOne:
    def test_calculate_one_requires_auth(self):
        pc_id = _make_pc("CALC1-AUTH")
        r = _req("POST", f"/api/stability/calculate/{pc_id}")
        assert r.status_code == 401

    def test_calculate_one_returns_201(self):
        token = _login()
        pc_id = _make_pc("CALC1-OK")
        r = _req("POST", f"/api/stability/calculate/{pc_id}", token=token, data={})
        assert r.status_code == 201
        data = json.loads(r.data)
        assert data["pc_id"] == pc_id
        assert "score" in data

    def test_calculate_one_404_for_missing(self):
        token = _login()
        r = _req("POST", "/api/stability/calculate/999999", token=token, data={})
        assert r.status_code == 404

    def test_calculate_one_score_decreases_with_events(self):
        token = _login()
        pc_id = _make_pc("UNSTABLE-CALC")
        # Kernel-Power (41) = 25 points; Disk Error (7) = 20 points
        _make_event_log(pc_id, 41, days_ago=2)
        _make_event_log(pc_id, 7, days_ago=3)
        r = _req("POST", f"/api/stability/calculate/{pc_id}", token=token, data={})
        data = json.loads(r.data)
        assert data["score"] <= 55.0  # 100 - 25 - 20

    def test_calculate_one_deductions_list(self):
        token = _login()
        pc_id = _make_pc("DEDUCT-PC")
        _make_event_log(pc_id, 1001, days_ago=1)  # BugCheck
        r = _req("POST", f"/api/stability/calculate/{pc_id}", token=token, data={})
        data = json.loads(r.data)
        assert isinstance(data["deductions"], list)
        assert len(data["deductions"]) > 0
        assert "reason" in data["deductions"][0]
        assert "points" in data["deductions"][0]


# ── Phase D-1: Unstable PCs ──────────────────────────────────────────────────

class TestUnstablePCs:
    def test_unstable_pcs_requires_auth(self):
        r = _req("GET", "/api/stability/unstable-pcs")
        assert r.status_code == 401

    def test_unstable_pcs_returns_list(self):
        token = _login()
        r = _req("GET", "/api/stability/unstable-pcs", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert isinstance(data, list)

    def test_unstable_pcs_only_below_threshold(self):
        token = _login()
        pc_id = _make_pc("REALLY-UNSTABLE")
        with app.app_context():
            pc = PC.query.get(pc_id)
            pc.stability_score = 30.0
            db.session.commit()

        r = _req("GET", "/api/stability/unstable-pcs", token=token)
        data = json.loads(r.data)
        ids = [x["pc_id"] for x in data]
        assert pc_id in ids

    def test_unstable_pcs_custom_threshold(self):
        token = _login()
        r = _req("GET", "/api/stability/unstable-pcs?threshold=90", token=token)
        assert r.status_code == 200


# ── Phase D-1: Event Ranking ─────────────────────────────────────────────────

class TestEventRanking:
    def test_event_ranking_requires_auth(self):
        r = _req("GET", "/api/stability/event-ranking")
        assert r.status_code == 401

    def test_event_ranking_returns_list(self):
        token = _login()
        r = _req("GET", "/api/stability/event-ranking", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert isinstance(data, list)

    def test_event_ranking_has_expected_fields(self):
        token = _login()
        pc_id = _make_pc("EVENT-RANK-PC")
        _make_event_log(pc_id, 1001, days_ago=1)
        r = _req("GET", "/api/stability/event-ranking?days=7", token=token)
        data = json.loads(r.data)
        if data:
            item = data[0]
            assert "event_id" in item
            assert "count" in item
            assert "days" in item

    def test_event_ranking_respects_days_param(self):
        token = _login()
        r = _req("GET", "/api/stability/event-ranking?days=1&limit=5", token=token)
        assert r.status_code == 200


# ── Phase D-2: KB Impact ─────────────────────────────────────────────────────

class TestKBImpact:
    def test_kb_impact_list_requires_auth(self):
        r = _req("GET", "/api/stability/kb-impact")
        assert r.status_code == 401

    def test_kb_impact_list_returns_list(self):
        token = _login()
        r = _req("GET", "/api/stability/kb-impact", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert isinstance(data, list)

    def test_kb_impact_detail_404_for_missing_kb(self):
        token = _login()
        r = _req("GET", "/api/stability/kb-impact/KB9999999", token=token)
        assert r.status_code == 404

    def test_kb_impact_detail_returns_pc_impacts(self):
        token = _login()
        pc_id = _make_pc("KB-IMPACT-PC")
        _make_update(pc_id, "KB1234567", installed=True, days_ago=3)
        # Simulate an error after install
        _make_event_log(pc_id, 1000, days_ago=2)

        r = _req("GET", "/api/stability/kb-impact/KB1234567", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["kb_id"] == "KB1234567"
        assert "pc_impacts" in data
        assert isinstance(data["pc_impacts"], list)
        assert "window_hours" in data

    def test_kb_impact_detail_has_error_fields(self):
        token = _login()
        pc_id = _make_pc("KB-DETAIL-PC2")
        _make_update(pc_id, "KB7654321", installed=True, days_ago=3)
        r = _req("GET", "/api/stability/kb-impact/KB7654321", token=token)
        data = json.loads(r.data)
        if data.get("pc_impacts"):
            item = data["pc_impacts"][0]
            assert "errors_before" in item
            assert "errors_after" in item
            assert "error_increase" in item


# ── Phase D-2: Similar Issues ────────────────────────────────────────────────

class TestSimilarIssues:
    def test_similar_issues_requires_auth(self):
        r = _req("GET", "/api/stability/similar-issues")
        assert r.status_code == 401

    def test_similar_issues_group_by_kb(self):
        token = _login()
        r = _req("GET", "/api/stability/similar-issues?group_by=kb", token=token)
        assert r.status_code == 200
        assert isinstance(json.loads(r.data), list)

    def test_similar_issues_group_by_model(self):
        token = _login()
        r = _req("GET", "/api/stability/similar-issues?group_by=model", token=token)
        assert r.status_code == 200
        assert isinstance(json.loads(r.data), list)

    def test_similar_issues_group_by_domain(self):
        token = _login()
        r = _req("GET", "/api/stability/similar-issues?group_by=domain", token=token)
        assert r.status_code == 200
        assert isinstance(json.loads(r.data), list)

    def test_similar_issues_invalid_group_by(self):
        token = _login()
        r = _req("GET", "/api/stability/similar-issues?group_by=invalid", token=token)
        assert r.status_code == 400


# ── Phase D-2: Disk Health ───────────────────────────────────────────────────

class TestDiskHealth:
    def test_disk_health_requires_auth(self):
        r = _req("GET", "/api/stability/disk-health")
        assert r.status_code == 401

    def test_disk_health_list_returns_list(self):
        token = _login()
        r = _req("GET", "/api/stability/disk-health", token=token)
        assert r.status_code == 200
        assert isinstance(json.loads(r.data), list)

    def test_disk_health_shows_disk_events(self):
        token = _login()
        pc_id = _make_pc("DISK-HEALTH-PC")
        _make_event_log(pc_id, 7, days_ago=1)   # Disk Error
        _make_event_log(pc_id, 51, days_ago=2)  # Disk Warning

        r = _req("GET", "/api/stability/disk-health?days=30", token=token)
        data = json.loads(r.data)
        ids = [x["pc_id"] for x in data]
        assert pc_id in ids

    def test_disk_health_detail_requires_auth(self):
        pc_id = _make_pc("DISK-AUTH-PC")
        r = _req("GET", f"/api/stability/disk-health/{pc_id}")
        assert r.status_code == 401

    def test_disk_health_detail_returns_events(self):
        token = _login()
        pc_id = _make_pc("DISK-DETAIL-PC")
        _make_event_log(pc_id, 55, days_ago=1)  # NTFS 異常

        r = _req("GET", f"/api/stability/disk-health/{pc_id}", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["pc_id"] == pc_id
        assert "total" in data
        assert "events" in data

    def test_disk_health_detail_404_missing_pc(self):
        token = _login()
        r = _req("GET", "/api/stability/disk-health/999999", token=token)
        assert r.status_code == 404

    def test_disk_health_list_has_risk_level(self):
        token = _login()
        pc_id = _make_pc("DISK-RISK-PC")
        # event_id=7 (Disk Error) should give critical risk
        for _ in range(11):
            _make_event_log(pc_id, 7, days_ago=1)

        r = _req("GET", "/api/stability/disk-health?days=30", token=token)
        data = json.loads(r.data)
        item = next((x for x in data if x["pc_id"] == pc_id), None)
        if item:
            assert item["risk_level"] in ("low", "medium", "high", "critical")

    def test_disk_health_flat_returns_per_event_rows(self):
        token = _login()
        pc_id = _make_pc("DISK-FLAT-PC")
        _make_event_log(pc_id, 7, days_ago=1)    # critical
        _make_event_log(pc_id, 51, days_ago=2)   # warning
        _make_event_log(pc_id, 153, days_ago=3)  # info

        r = _req("GET", "/api/stability/disk-health?flat=1&days=30", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "items" in data
        assert "total" in data
        items = [x for x in data["items"] if x["pc_id"] == pc_id]
        assert len(items) == 3
        # severity must be derived from DISK_EVENT_SEVERITY
        sev_by_eid = {x["event_id"]: x["severity"] for x in items}
        assert sev_by_eid[7] == "critical"
        assert sev_by_eid[51] == "warning"
        assert sev_by_eid[153] == "info"
        # required keys for JS rendering
        for it in items:
            assert "pc_name" in it
            assert "occurred_at" in it


# ── Phase D-2: Known Issues ──────────────────────────────────────────────────

class TestKnownIssues:
    def test_list_requires_auth(self):
        r = _req("GET", "/api/stability/known-issues")
        assert r.status_code == 401

    def test_create_requires_auth(self):
        r = _req("POST", "/api/stability/known-issues", data={"title": "test"})
        assert r.status_code == 401

    def test_list_known_issues_empty(self):
        token = _login()
        r = _req("GET", "/api/stability/known-issues", token=token)
        assert r.status_code == 200
        assert isinstance(json.loads(r.data), list)

    def test_create_known_issue_success(self):
        token = _login()
        r = _req(
            "POST",
            "/api/stability/known-issues",
            token=token,
            data={
                "title": "KB1234567 causes BSOD on Windows 11",
                "kb_id": "KB1234567",
                "event_ids": [1001, 41],
                "symptoms": "Blue screen after update",
                "resolution": "Uninstall KB1234567",
                "severity": "high",
            },
        )
        assert r.status_code == 201
        data = json.loads(r.data)
        assert data["title"] == "KB1234567 causes BSOD on Windows 11"
        assert data["kb_id"] == "KB1234567"
        assert data["severity"] == "high"
        assert isinstance(data["event_ids"], list)

    def test_create_known_issue_missing_title(self):
        token = _login()
        r = _req("POST", "/api/stability/known-issues", token=token, data={"kb_id": "KB123"})
        assert r.status_code == 400

    def test_update_known_issue(self):
        token = _login()
        r = _req(
            "POST",
            "/api/stability/known-issues",
            token=token,
            data={"title": "Issue to update"},
        )
        issue_id = json.loads(r.data)["id"]

        r = _req(
            "PUT",
            f"/api/stability/known-issues/{issue_id}",
            token=token,
            data={"severity": "critical", "symptoms": "Updated symptoms"},
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["severity"] == "critical"
        assert data["symptoms"] == "Updated symptoms"

    def test_update_known_issue_404(self):
        token = _login()
        r = _req(
            "PUT",
            "/api/stability/known-issues/999999",
            token=token,
            data={"title": "X"},
        )
        assert r.status_code == 404

    def test_match_known_issues_requires_auth(self):
        pc_id = _make_pc("MATCH-AUTH-PC")
        r = _req("GET", f"/api/stability/known-issues/match/{pc_id}")
        assert r.status_code == 401

    def test_match_known_issues_for_pc(self):
        token = _login()
        pc_id = _make_pc("MATCH-PC-001")
        _make_event_log(pc_id, 1001, days_ago=1)
        _make_update(pc_id, "KB5678901", installed=True, days_ago=3)

        # Create a known issue matching KB
        _req(
            "POST",
            "/api/stability/known-issues",
            token=token,
            data={
                "title": "KB5678901 issue",
                "kb_id": "KB5678901",
                "event_ids": [1001],
                "severity": "high",
            },
        )

        r = _req("GET", f"/api/stability/known-issues/match/{pc_id}", token=token)
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["pc_id"] == pc_id
        assert "matched_issues" in data
        assert isinstance(data["matched_issues"], list)
        assert len(data["matched_issues"]) > 0

    def test_match_known_issues_404_missing_pc(self):
        token = _login()
        r = _req("GET", "/api/stability/known-issues/match/999999", token=token)
        assert r.status_code == 404


# ── Score helper tests ────────────────────────────────────────────────────────

class TestScoreLogic:
    def test_score_floor_is_zero(self):
        """Score should not go below 0 even with many deductions."""
        token = _login()
        pc_id = _make_pc("FLOOR-PC")
        # Add multiple high-impact events
        for event_id in [1001, 41, 6008, 7, 55, 1000, 1002]:
            _make_event_log(pc_id, event_id, days_ago=1)

        r = _req("POST", f"/api/stability/calculate/{pc_id}", token=token, data={})
        data = json.loads(r.data)
        assert data["score"] >= 0.0

    def test_score_status_critical_below_40(self):
        token = _login()
        pc_id = _make_pc("CRITICAL-STATUS-PC")
        with app.app_context():
            pc = PC.query.get(pc_id)
            pc.stability_score = 30.0
            db.session.commit()

        r = _req("GET", f"/api/stability/scores/{pc_id}", token=token)
        data = json.loads(r.data)
        assert data["status"] == "critical"

    def test_score_status_unstable_40_to_60(self):
        token = _login()
        pc_id = _make_pc("UNSTABLE-STATUS-PC")
        with app.app_context():
            pc = PC.query.get(pc_id)
            pc.stability_score = 50.0
            db.session.commit()

        r = _req("GET", f"/api/stability/scores/{pc_id}", token=token)
        data = json.loads(r.data)
        assert data["status"] == "unstable"

    def test_score_status_warning_60_to_80(self):
        token = _login()
        pc_id = _make_pc("WARNING-STATUS-PC")
        with app.app_context():
            pc = PC.query.get(pc_id)
            pc.stability_score = 70.0
            db.session.commit()

        r = _req("GET", f"/api/stability/scores/{pc_id}", token=token)
        data = json.loads(r.data)
        assert data["status"] == "warning"

    def test_score_history_stored_after_calculate(self):
        token = _login()
        pc_id = _make_pc("HISTORY-PC")
        _req("POST", f"/api/stability/calculate/{pc_id}", token=token, data={})
        _req("POST", f"/api/stability/calculate/{pc_id}", token=token, data={})

        r = _req("GET", f"/api/stability/scores/{pc_id}", token=token)
        data = json.loads(r.data)
        assert len(data["history"]) >= 2

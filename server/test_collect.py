"""Tests for /api/collect and /api/collect/detail endpoints.

Covers:
- POST /collect: create/update PC, snapshot, health score, alert rules
- POST /collect/detail: software, windows_updates, event_logs
- _calculate_health_score branches (memory/disk thresholds)
- _evaluate_alert_rules (cpu/memory/disk rules, existing alert dedup)
- Edge cases: missing body, missing pc_name, invalid last_boot_time
"""

import json
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models import PC, AlertRule, Alert

app = create_app("testing")
client = app.test_client()

_AGENT_KEY = "default-agent-key"
_unique = uuid.uuid4().hex[:8]


def setup_module():
    with app.app_context():
        db.create_all()


def _agent_req(method, path, data=None):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_AGENT_KEY}",
    }
    body = json.dumps(data) if data is not None else None
    return client.open(path, method=method, headers=headers, data=body)


def _pc_payload(suffix="", **kwargs):
    base = {
        "pc_name": f"TestPC-{suffix}-{_unique}",
        "domain": "TESTDOMAIN",
        "os_version": "Windows 11",
        "os_architecture": "x86_64",
        "cpu_name": "Intel Core i7",
        "cpu_cores": 8,
        "cpu_logical_processors": 16,
        "memory_total_gb": 16.0,
        "memory_available_gb": 8.0,
        "disk_total_gb": 500.0,
        "disk_free_gb": 200.0,
        "ip_address": "192.168.1.100",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "agent_version": "1.0.0",
        "cpu_usage": 25.0,
        "uptime_days": 3,
        "pending_reboot": False,
        "windows_update_pending": False,
    }
    base.update(kwargs)
    return base


# ── auth ──────────────────────────────────────────────────────────────────────


def test_collect_no_auth():
    r = client.open("/api/collect", method="POST", headers={"Content-Type": "application/json"}, data="{}")
    assert r.status_code == 401


def test_collect_invalid_token():
    headers = {"Content-Type": "application/json", "Authorization": "Bearer badtoken"}
    r = client.open("/api/collect", method="POST", headers=headers, data=json.dumps({"pc_name": "x"}))
    assert r.status_code == 401


# ── validation ────────────────────────────────────────────────────────────────


def test_collect_no_body():
    r = client.open("/api/collect", method="POST", headers={"Authorization": f"Bearer {_AGENT_KEY}"})
    assert r.status_code in (400, 415)


def test_collect_missing_pc_name():
    r = _agent_req("POST", "/api/collect", data={"os_version": "Windows 10"})
    assert r.status_code == 400
    assert "pc_name" in json.loads(r.data)["error"]


def test_collect_empty_pc_name():
    r = _agent_req("POST", "/api/collect", data={"pc_name": "   "})
    assert r.status_code == 400
    assert "pc_name" in json.loads(r.data)["error"]


# ── create new PC via collect ─────────────────────────────────────────────────


def test_collect_creates_new_pc():
    payload = _pc_payload("new")
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["message"] == "ok"
    assert "pc_id" in data
    assert "health_score" in data
    assert "status" in data
    assert "pending_tasks" in data


def test_collect_updates_existing_pc():
    name = f"ExistPC-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name, memory_available_gb=8.0))
    r = _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name, memory_available_gb=4.0, os_version="Windows 11 Update"))
    assert r.status_code == 200


# ── health score branches ─────────────────────────────────────────────────────


def test_collect_health_score_memory_critical():
    """Memory usage > 90% → score drops 30."""
    name = f"MemCrit-{_unique}"
    payload = _pc_payload(pc_name=name, memory_total_gb=16.0, memory_available_gb=0.5)
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["health_score"] <= 70.0


def test_collect_health_score_memory_high():
    """Memory usage > 75% → score drops 15."""
    name = f"MemHigh-{_unique}"
    payload = _pc_payload(pc_name=name, memory_total_gb=16.0, memory_available_gb=2.0)
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["health_score"] <= 85.0


def test_collect_health_score_memory_moderate():
    """Memory usage > 60% → score drops 5."""
    name = f"MemMod-{_unique}"
    payload = _pc_payload(pc_name=name, memory_total_gb=16.0, memory_available_gb=5.0)
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["health_score"] <= 95.0


def test_collect_health_score_disk_critical():
    """Disk usage > 95% → score drops 30."""
    name = f"DiskCrit-{_unique}"
    payload = _pc_payload(pc_name=name, disk_total_gb=100.0, disk_free_gb=2.0)
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["health_score"] <= 70.0


def test_collect_health_score_disk_high():
    """Disk usage > 85% → score drops 15."""
    name = f"DiskHigh-{_unique}"
    payload = _pc_payload(pc_name=name, disk_total_gb=100.0, disk_free_gb=12.0)
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["health_score"] <= 85.0


def test_collect_health_score_disk_moderate():
    """Disk usage > 75% → score drops 5."""
    name = f"DiskMod-{_unique}"
    payload = _pc_payload(pc_name=name, disk_total_gb=100.0, disk_free_gb=22.0)
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["health_score"] <= 95.0


def test_collect_health_score_perfect():
    """Low resource usage → health_score = 100."""
    name = f"Perfect-{_unique}"
    payload = _pc_payload(pc_name=name, memory_total_gb=32.0, memory_available_gb=20.0,
                          disk_total_gb=1000.0, disk_free_gb=700.0)
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["health_score"] == 100.0


# ── status determination ──────────────────────────────────────────────────────


def test_collect_status_healthy():
    """health_score >= 80 → status = healthy."""
    name = f"Healthy-{_unique}"
    payload = _pc_payload(pc_name=name, memory_total_gb=16.0, memory_available_gb=12.0,
                          disk_total_gb=500.0, disk_free_gb=400.0)
    r = _agent_req("POST", "/api/collect", data=payload)
    assert json.loads(r.data)["status"] == "healthy"


def test_collect_status_warning():
    """health_score between 50 and 79 → status = warning."""
    name = f"Warn-{_unique}"
    payload = _pc_payload(pc_name=name, memory_total_gb=16.0, memory_available_gb=0.5,
                          disk_total_gb=100.0, disk_free_gb=12.0)
    r = _agent_req("POST", "/api/collect", data=payload)
    data = json.loads(r.data)
    assert data["status"] in ("warning", "critical")


def test_collect_status_critical():
    """Very low health_score → status = critical."""
    name = f"Critical-{_unique}"
    payload = _pc_payload(pc_name=name, memory_total_gb=16.0, memory_available_gb=0.1,
                          disk_total_gb=100.0, disk_free_gb=1.0)
    r = _agent_req("POST", "/api/collect", data=payload)
    data = json.loads(r.data)
    assert data["status"] == "critical"


# ── last_boot_time parsing ────────────────────────────────────────────────────


def test_collect_valid_last_boot_time():
    name = f"BootTime-{_unique}"
    payload = _pc_payload(pc_name=name, last_boot_time="2026-05-01T08:00:00")
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200


def test_collect_invalid_last_boot_time():
    """Invalid ISO format is silently ignored (no 400 error)."""
    name = f"BadBoot-{_unique}"
    payload = _pc_payload(pc_name=name, last_boot_time="not-a-date")
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200


# ── alert rule evaluation ─────────────────────────────────────────────────────


def test_collect_alert_rule_cpu_gt_triggered():
    """CPU > 50% alert rule fires when cpu_usage=80."""
    name = f"AlertCPU-{_unique}"
    with app.app_context():
        rule = AlertRule(
            name=f"CPU High {_unique}",
            metric="cpu",
            operator="gt",
            threshold=50.0,
            severity="warning",
            is_enabled=True,
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id

    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name, cpu_usage=80.0))

    with app.app_context():
        alert = Alert.query.filter_by(source_key=f"rule:{rule_id}:pc:{PC.query.filter_by(pc_name=name).first().id}", resolved=False).first()
        assert alert is not None
        assert "cpu" in alert.alert_type


def test_collect_alert_rule_not_triggered():
    """CPU > 90% rule does NOT fire when cpu_usage=30."""
    name = f"NoAlert-{_unique}"
    with app.app_context():
        rule = AlertRule(
            name=f"CPU Strict {_unique}",
            metric="cpu",
            operator="gt",
            threshold=90.0,
            severity="critical",
            is_enabled=True,
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id

    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name, cpu_usage=30.0))

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        alert = Alert.query.filter_by(source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False).first()
        assert alert is None


def test_collect_alert_rule_dedup():
    """Same alert rule does not create duplicate alerts."""
    name = f"Dedup-{_unique}"
    with app.app_context():
        rule = AlertRule(
            name=f"Dedup Rule {_unique}",
            metric="cpu",
            operator="gt",
            threshold=10.0,
            severity="warning",
            is_enabled=True,
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id

    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name, cpu_usage=80.0))
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name, cpu_usage=80.0))

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        count = Alert.query.filter_by(source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False).count()
        assert count == 1


def test_collect_alert_rule_disabled():
    """Disabled rule does not fire."""
    name = f"Disabled-{_unique}"
    with app.app_context():
        rule = AlertRule(
            name=f"Disabled Rule {_unique}",
            metric="cpu",
            operator="gt",
            threshold=1.0,
            severity="warning",
            is_enabled=False,
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id

    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name, cpu_usage=80.0))

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        alert = Alert.query.filter_by(source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False).first()
        assert alert is None


def test_collect_alert_rule_memory_gte():
    """Memory >= 80% rule fires."""
    name = f"MemAlert-{_unique}"
    with app.app_context():
        rule = AlertRule(
            name=f"Mem Alert {_unique}",
            metric="memory",
            operator="gte",
            threshold=80.0,
            severity="warning",
            is_enabled=True,
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id

    payload = _pc_payload(pc_name=name, memory_total_gb=16.0, memory_available_gb=2.0)
    _agent_req("POST", "/api/collect", data=payload)

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        alert = Alert.query.filter_by(source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False).first()
        assert alert is not None


def test_collect_alert_rule_disk_lt():
    """Disk free% < 10 rule fires when disk is nearly full."""
    name = f"DiskAlert-{_unique}"
    with app.app_context():
        rule = AlertRule(
            name=f"Disk Low {_unique}",
            metric="disk",
            operator="lt",
            threshold=10.0,
            severity="critical",
            is_enabled=True,
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id

    # disk_usage = (100-2)/100 = 98% → disk rule "lt 10" → not triggered
    # Actually "disk" metric in collect.py is disk USAGE (not free), so disk_usage=98%
    # "lt 10" means disk_usage < 10%, so 98% does NOT trigger
    # To trigger: disk_usage < 10 → e.g. disk_total=100, disk_free=95 → usage=5%
    payload = _pc_payload(pc_name=name, disk_total_gb=100.0, disk_free_gb=95.0)
    _agent_req("POST", "/api/collect", data=payload)

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        alert = Alert.query.filter_by(source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False).first()
        assert alert is not None


def test_collect_alert_rule_lte():
    """lte operator fires when value <= threshold."""
    name = f"LTEAlert-{_unique}"
    with app.app_context():
        rule = AlertRule(
            name=f"CPU LTE {_unique}",
            metric="cpu",
            operator="lte",
            threshold=30.0,
            severity="warning",
            is_enabled=True,
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id

    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name, cpu_usage=30.0))

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        alert = Alert.query.filter_by(source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False).first()
        assert alert is not None


def test_collect_alert_rule_offline_skipped():
    """offline metric rules are skipped during collect."""
    name = f"Offline-{_unique}"
    with app.app_context():
        rule = AlertRule(
            name=f"Offline Rule {_unique}",
            metric="offline",
            operator="gt",
            threshold=0.0,
            severity="critical",
            is_enabled=True,
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id

    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        alert = Alert.query.filter_by(source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False).first()
        assert alert is None


# ── collect_detail ────────────────────────────────────────────────────────────


def test_collect_detail_no_body():
    r = client.open("/api/collect/detail", method="POST",
                    headers={"Authorization": f"Bearer {_AGENT_KEY}"})
    assert r.status_code in (400, 415)


def test_collect_detail_missing_pc_name():
    r = _agent_req("POST", "/api/collect/detail", data={"software": []})
    assert r.status_code == 400
    assert "pc_name" in json.loads(r.data)["error"]


def test_collect_detail_pc_not_found():
    r = _agent_req("POST", "/api/collect/detail", data={
        "pc_name": f"NonExistPC-{_unique}",
        "software": [],
    })
    assert r.status_code == 404


def test_collect_detail_software():
    """collect_detail stores software list."""
    name = f"SWDetail-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req("POST", "/api/collect/detail", data={
        "pc_name": name,
        "software": [
            {"name": "Microsoft Office", "version": "2021", "publisher": "Microsoft", "install_date": "2024-01-15"},
            {"name": "Chrome", "version": "120.0", "publisher": "Google"},
        ],
    })
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["message"] == "詳細情報を受信しました"
    assert "pc_id" in data


def test_collect_detail_windows_updates():
    """collect_detail stores windows_updates list."""
    name = f"WinUpd-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req("POST", "/api/collect/detail", data={
        "pc_name": name,
        "windows_updates": [
            {"kb_id": "KB5001234", "title": "Security Update", "severity": "Critical",
             "installed": True, "installed_at": "2026-04-01T12:00:00"},
            {"kb_id": "KB5005678", "title": "Cumulative Update", "severity": "Important",
             "installed": False},
        ],
    })
    assert r.status_code == 200


def test_collect_detail_event_logs():
    """collect_detail stores event_logs list."""
    name = f"EvtLog-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req("POST", "/api/collect/detail", data={
        "pc_name": name,
        "event_logs": [
            {"log_type": "system", "event_id": 6006, "level": "Information",
             "source": "EventLog", "message": "System shutdown", "generated_at": "2026-05-01T08:00:00"},
            {"log_type": "application", "event_id": 1001, "level": "Error",
             "source": "MyApp", "message": "App crashed"},
        ],
    })
    assert r.status_code == 200


def test_collect_detail_invalid_dates_ignored():
    """Invalid ISO dates in detail data are silently ignored."""
    name = f"BadDate-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req("POST", "/api/collect/detail", data={
        "pc_name": name,
        "software": [{"name": "BadApp", "install_date": "not-a-date"}],
        "windows_updates": [{"kb_id": "KB999", "installed_at": "INVALID"}],
        "event_logs": [{"log_type": "system", "generated_at": "INVALID"}],
    })
    assert r.status_code == 200


def test_collect_detail_all_together():
    """collect_detail with all three lists at once."""
    name = f"AllDetail-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req("POST", "/api/collect/detail", data={
        "pc_name": name,
        "software": [{"name": "VSCode", "version": "1.88"}],
        "windows_updates": [{"kb_id": "KB1234", "installed": True}],
        "event_logs": [{"log_type": "system", "event_id": 100, "level": "Info"}],
    })
    assert r.status_code == 200


def test_collect_detail_empty_lists():
    """Empty lists in collect_detail are valid (no-ops)."""
    name = f"EmptyLists-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req("POST", "/api/collect/detail", data={
        "pc_name": name,
        "software": [],
        "windows_updates": [],
        "event_logs": [],
    })
    assert r.status_code == 200


def test_collect_no_memory_info():
    """collect with no memory info still works (health_score fallback)."""
    name = f"NoMem-{_unique}"
    payload = {"pc_name": name, "os_version": "Windows 10"}
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    assert json.loads(r.data)["health_score"] == 100.0

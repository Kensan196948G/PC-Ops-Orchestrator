"""Tests for /api/collect and /api/collect/detail endpoints.

Covers:
- POST /collect: create/update PC, snapshot, health score, alert rules
- POST /collect/detail: software, windows_updates, event_logs
- _calculate_health_score branches (memory/disk thresholds)
- _evaluate_alert_rules (cpu/memory/disk rules, existing alert dedup)
- Edge cases: missing body, missing pc_name, invalid last_boot_time
- HMAC-SHA256 pending_tasks signing (Issue #188 part 4)
"""

import hashlib
import hmac
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
    r = client.open(
        "/api/collect",
        method="POST",
        headers={"Content-Type": "application/json"},
        data="{}",
    )
    assert r.status_code == 401


def test_collect_invalid_token():
    headers = {"Content-Type": "application/json", "Authorization": "Bearer badtoken"}
    r = client.open(
        "/api/collect",
        method="POST",
        headers=headers,
        data=json.dumps({"pc_name": "x"}),
    )
    assert r.status_code == 401


# ── validation ────────────────────────────────────────────────────────────────


def test_collect_no_body():
    r = client.open(
        "/api/collect", method="POST", headers={"Authorization": f"Bearer {_AGENT_KEY}"}
    )
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
    _agent_req(
        "POST", "/api/collect", data=_pc_payload(pc_name=name, memory_available_gb=8.0)
    )
    r = _agent_req(
        "POST",
        "/api/collect",
        data=_pc_payload(
            pc_name=name, memory_available_gb=4.0, os_version="Windows 11 Update"
        ),
    )
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
    payload = _pc_payload(
        pc_name=name,
        memory_total_gb=32.0,
        memory_available_gb=20.0,
        disk_total_gb=1000.0,
        disk_free_gb=700.0,
    )
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["health_score"] == 100.0


# ── status determination ──────────────────────────────────────────────────────


def test_collect_status_healthy():
    """health_score >= 80 → status = healthy."""
    name = f"Healthy-{_unique}"
    payload = _pc_payload(
        pc_name=name,
        memory_total_gb=16.0,
        memory_available_gb=12.0,
        disk_total_gb=500.0,
        disk_free_gb=400.0,
    )
    r = _agent_req("POST", "/api/collect", data=payload)
    assert json.loads(r.data)["status"] == "healthy"


def test_collect_status_warning():
    """health_score between 50 and 79 → status = warning."""
    name = f"Warn-{_unique}"
    payload = _pc_payload(
        pc_name=name,
        memory_total_gb=16.0,
        memory_available_gb=0.5,
        disk_total_gb=100.0,
        disk_free_gb=12.0,
    )
    r = _agent_req("POST", "/api/collect", data=payload)
    data = json.loads(r.data)
    assert data["status"] in ("warning", "critical")


def test_collect_status_critical():
    """Very low health_score → status = critical."""
    name = f"Critical-{_unique}"
    payload = _pc_payload(
        pc_name=name,
        memory_total_gb=16.0,
        memory_available_gb=0.1,
        disk_total_gb=100.0,
        disk_free_gb=1.0,
    )
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
        alert = Alert.query.filter_by(
            source_key=f"rule:{rule_id}:pc:{PC.query.filter_by(pc_name=name).first().id}",
            resolved=False,
        ).first()
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
        alert = Alert.query.filter_by(
            source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False
        ).first()
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
        count = Alert.query.filter_by(
            source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False
        ).count()
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
        alert = Alert.query.filter_by(
            source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False
        ).first()
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
        alert = Alert.query.filter_by(
            source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False
        ).first()
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
        alert = Alert.query.filter_by(
            source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False
        ).first()
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
        alert = Alert.query.filter_by(
            source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False
        ).first()
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
        alert = Alert.query.filter_by(
            source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False
        ).first()
        assert alert is None


# ── collect_detail ────────────────────────────────────────────────────────────


def test_collect_detail_no_body():
    r = client.open(
        "/api/collect/detail",
        method="POST",
        headers={"Authorization": f"Bearer {_AGENT_KEY}"},
    )
    assert r.status_code in (400, 415)


def test_collect_detail_missing_pc_name():
    r = _agent_req("POST", "/api/collect/detail", data={"software": []})
    assert r.status_code == 400
    assert "pc_name" in json.loads(r.data)["error"]


def test_collect_detail_pc_not_found():
    r = _agent_req(
        "POST",
        "/api/collect/detail",
        data={
            "pc_name": f"NonExistPC-{_unique}",
            "software": [],
        },
    )
    assert r.status_code == 404


def test_collect_detail_software():
    """collect_detail stores software list."""
    name = f"SWDetail-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req(
        "POST",
        "/api/collect/detail",
        data={
            "pc_name": name,
            "software": [
                {
                    "name": "Microsoft Office",
                    "version": "2021",
                    "publisher": "Microsoft",
                    "install_date": "2024-01-15",
                },
                {"name": "Chrome", "version": "120.0", "publisher": "Google"},
            ],
        },
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["message"] == "詳細情報を受信しました"
    assert "pc_id" in data


def test_collect_detail_windows_updates():
    """collect_detail stores windows_updates list."""
    name = f"WinUpd-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req(
        "POST",
        "/api/collect/detail",
        data={
            "pc_name": name,
            "windows_updates": [
                {
                    "kb_id": "KB5001234",
                    "title": "Security Update",
                    "severity": "Critical",
                    "installed": True,
                    "installed_at": "2026-04-01T12:00:00",
                },
                {
                    "kb_id": "KB5005678",
                    "title": "Cumulative Update",
                    "severity": "Important",
                    "installed": False,
                },
            ],
        },
    )
    assert r.status_code == 200


def test_collect_detail_event_logs():
    """collect_detail stores event_logs list."""
    name = f"EvtLog-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req(
        "POST",
        "/api/collect/detail",
        data={
            "pc_name": name,
            "event_logs": [
                {
                    "log_type": "system",
                    "event_id": 6006,
                    "level": "Information",
                    "source": "EventLog",
                    "message": "System shutdown",
                    "generated_at": "2026-05-01T08:00:00",
                },
                {
                    "log_type": "application",
                    "event_id": 1001,
                    "level": "Error",
                    "source": "MyApp",
                    "message": "App crashed",
                },
            ],
        },
    )
    assert r.status_code == 200


def test_collect_detail_invalid_dates_ignored():
    """Invalid ISO dates in detail data are silently ignored."""
    name = f"BadDate-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req(
        "POST",
        "/api/collect/detail",
        data={
            "pc_name": name,
            "software": [{"name": "BadApp", "install_date": "not-a-date"}],
            "windows_updates": [{"kb_id": "KB999", "installed_at": "INVALID"}],
            "event_logs": [{"log_type": "system", "generated_at": "INVALID"}],
        },
    )
    assert r.status_code == 200


def test_collect_detail_all_together():
    """collect_detail with all three lists at once."""
    name = f"AllDetail-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req(
        "POST",
        "/api/collect/detail",
        data={
            "pc_name": name,
            "software": [{"name": "VSCode", "version": "1.88"}],
            "windows_updates": [{"kb_id": "KB1234", "installed": True}],
            "event_logs": [{"log_type": "system", "event_id": 100, "level": "Info"}],
        },
    )
    assert r.status_code == 200


def test_collect_detail_empty_lists():
    """Empty lists in collect_detail are valid (no-ops)."""
    name = f"EmptyLists-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    r = _agent_req(
        "POST",
        "/api/collect/detail",
        data={
            "pc_name": name,
            "software": [],
            "windows_updates": [],
            "event_logs": [],
        },
    )
    assert r.status_code == 200


def test_collect_no_memory_info():
    """collect with no memory info still works (health_score fallback)."""
    name = f"NoMem-{_unique}"
    payload = {"pc_name": name, "os_version": "Windows 10"}
    r = _agent_req("POST", "/api/collect", data=payload)
    assert r.status_code == 200
    assert json.loads(r.data)["health_score"] == 100.0


# ── additional coverage: no-body with JSON Content-Type (lines 24 & 104) ─────


def test_collect_no_body_json_content_type():
    """Empty JSON object {} is falsy → get_json() returns {} → if not data → line 24."""
    r = _agent_req("POST", "/api/collect", data={})
    assert r.status_code == 400
    assert "リクエストボディ" in json.loads(r.data)["error"]


def test_collect_detail_no_body_json_content_type():
    """Same pattern for collect_detail — hits line 104."""
    r = _agent_req("POST", "/api/collect/detail", data={})
    assert r.status_code == 400
    assert "リクエストボディ" in json.loads(r.data)["error"]


# ── connection_type coverage (line 54) ───────────────────────────────────────


def test_collect_sets_connection_type_lan():
    """connection_type LAN stored via line 54."""
    name = f"CT-LAN-{_unique}"
    r = _agent_req(
        "POST", "/api/collect", data=_pc_payload(pc_name=name, connection_type="LAN")
    )
    assert r.status_code == 200
    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        assert pc is not None
        assert pc.connection_type == "LAN"


def test_collect_sets_connection_type_ssl_vpn():
    """connection_type SSL-VPN stored via line 54."""
    name = f"CT-VPN-{_unique}"
    r = _agent_req(
        "POST",
        "/api/collect",
        data=_pc_payload(pc_name=name, connection_type="SSL-VPN"),
    )
    assert r.status_code == 200
    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        assert pc.connection_type == "SSL-VPN"


# ── _evaluate_alert_rules unknown operator (line 348) ────────────────────────


def test_collect_alert_rule_unknown_operator_no_alert():
    """Unknown operator in AlertRule → _matches() returns False → no alert created."""
    name = f"UnknOp-{_unique}"
    with app.app_context():
        rule = AlertRule(
            name=f"Unknown Op {_unique}",
            metric="cpu",
            operator="eq",
            threshold=25.0,
            severity="warning",
            is_enabled=True,
        )
        db.session.add(rule)
        db.session.commit()
        rule_id = rule.id

    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name, cpu_usage=25.0))

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        alert = Alert.query.filter_by(
            source_key=f"rule:{rule_id}:pc:{pc.id}", resolved=False
        ).first()
        assert alert is None


# ── collect_sync endpoint (lines 185-250) ────────────────────────────────────


def test_collect_sync_no_body():
    """No Content-Type + no body → 400 or 415."""
    r = client.open(
        "/api/collect/sync",
        method="POST",
        headers={"Authorization": f"Bearer {_AGENT_KEY}"},
    )
    assert r.status_code in (400, 415)


def test_collect_sync_no_body_json():
    """Empty JSON object {} is falsy → get_json() returns {} → if not data → line 187."""
    r = _agent_req("POST", "/api/collect/sync", data={})
    assert r.status_code == 400
    assert "リクエストボディ" in json.loads(r.data)["error"]


def test_collect_sync_missing_pc_name():
    r = _agent_req("POST", "/api/collect/sync", data={"offline_cache": []})
    assert r.status_code == 400
    assert "pc_name" in json.loads(r.data)["error"]


def test_collect_sync_pc_not_found():
    r = _agent_req(
        "POST",
        "/api/collect/sync",
        data={"pc_name": f"NoSuchPC-sync-{_unique}", "offline_cache": []},
    )
    assert r.status_code == 404


def test_collect_sync_invalid_cache_format():
    """offline_cache must be a list."""
    name = f"SyncFmt-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    r = _agent_req(
        "POST",
        "/api/collect/sync",
        data={"pc_name": name, "offline_cache": "not-a-list"},
    )
    assert r.status_code == 400
    assert "リスト形式" in json.loads(r.data)["error"]


def test_collect_sync_inserts_entries():
    """Offline cache entries are inserted into DB."""
    name = f"SyncIns-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    entries = [
        {
            "collected_at": "2026-05-10T10:00:00",
            "cpu_usage": 30.0,
            "memory_available_gb": 4.0,
            "disk_free_gb": 100.0,
        },
        {
            "collected_at": "2026-05-10T10:05:00",
            "cpu_usage": 35.0,
            "memory_available_gb": 3.5,
            "disk_free_gb": 99.0,
        },
    ]
    r = _agent_req(
        "POST", "/api/collect/sync", data={"pc_name": name, "offline_cache": entries}
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["inserted"] == 2
    assert body["skipped"] == 0


def test_collect_sync_dedup_skips_existing_timestamp():
    """Duplicate timestamps are skipped."""
    from datetime import datetime
    from models import SystemSnapshot

    name = f"SyncDup-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        snap = SystemSnapshot(pc_id=pc.id, collected_at=datetime(2026, 5, 11, 11, 0, 0))
        db.session.add(snap)
        db.session.commit()

    entries = [
        {"collected_at": "2026-05-11T11:00:00", "cpu_usage": 50.0},
        {"collected_at": "2026-05-11T11:05:00", "cpu_usage": 55.0},
    ]
    r = _agent_req(
        "POST", "/api/collect/sync", data={"pc_name": name, "offline_cache": entries}
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["inserted"] == 1
    assert body["skipped"] == 1


def test_collect_sync_invalid_timestamp_skipped():
    """Invalid timestamp strings are counted as skipped."""
    name = f"SyncBadTs-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    entries = [
        {"collected_at": "not-a-date", "cpu_usage": 10.0},
        {"collected_at": "2026-05-10T12:00:00", "cpu_usage": 20.0},
    ]
    r = _agent_req(
        "POST", "/api/collect/sync", data={"pc_name": name, "offline_cache": entries}
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["inserted"] == 1
    assert body["skipped"] == 1


def test_collect_sync_empty_cache():
    """Empty offline_cache list → 200 with inserted=0."""
    name = f"SyncEmpty-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    r = _agent_req(
        "POST", "/api/collect/sync", data={"pc_name": name, "offline_cache": []}
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["inserted"] == 0
    assert body["skipped"] == 0


def test_collect_sync_no_collected_at():
    """Entry without collected_at is inserted (no dedup key)."""
    name = f"SyncNoTs-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    entries = [{"cpu_usage": 42.0, "memory_available_gb": 3.0}]
    r = _agent_req(
        "POST", "/api/collect/sync", data={"pc_name": name, "offline_cache": entries}
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["inserted"] == 1


def test_collect_sync_with_last_boot_time():
    """Entry with last_boot_time triggers the fromisoformat branch (lines 234-239)."""
    name = f"SyncBoot-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    entries = [
        {
            "collected_at": "2026-05-13T08:00:00",
            "last_boot_time": "2026-05-12T06:00:00",
            "cpu_usage": 20.0,
            "memory_available_gb": 6.0,
        },
        {
            "collected_at": "2026-05-13T08:05:00",
            "last_boot_time": "invalid-boot-time",
            "cpu_usage": 22.0,
        },
    ]
    r = _agent_req(
        "POST", "/api/collect/sync", data={"pc_name": name, "offline_cache": entries}
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["inserted"] == 2


def test_collect_sync_reduces_offline_pending_count():
    """offline_pending_count decreases by inserted count after sync."""
    name = f"SyncPend-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        pc.offline_pending_count = 5
        db.session.commit()

    entries = [
        {"collected_at": "2026-05-12T10:00:00", "cpu_usage": 30.0},
        {"collected_at": "2026-05-12T10:05:00", "cpu_usage": 35.0},
    ]
    r = _agent_req(
        "POST", "/api/collect/sync", data={"pc_name": name, "offline_cache": entries}
    )
    assert r.status_code == 200
    assert json.loads(r.data)["inserted"] == 2

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        assert pc.offline_pending_count == 3


# ── _trim_snapshots delete path (lines 264-272) ──────────────────────────────


def test_trim_snapshots_deletes_oldest_beyond_limit():
    """Creating 721+ snapshots triggers _trim_snapshots() delete path."""
    from models import SystemSnapshot
    from datetime import datetime, timezone, timedelta

    name = f"Trim721-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        pc_id = pc.id
        base_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        snapshots = [
            SystemSnapshot(
                pc_id=pc_id,
                collected_at=base_time + timedelta(minutes=i),
                cpu_usage=float(i % 100),
            )
            for i in range(722)
        ]
        db.session.bulk_save_objects(snapshots)
        db.session.commit()

    # Trigger another collect → _trim_snapshots(keep=720) fires in collect()
    r = _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    assert r.status_code == 200

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        count = SystemSnapshot.query.filter_by(pc_id=pc.id).count()
        assert count <= 720


# ── HMAC-SHA256 pending_tasks signing (Issue #188 part 4) ────────────────────


def _compute_expected_sig(key: str, tasks):
    """Replicate the server-side canonical-JSON + HMAC-SHA256 algorithm."""
    canonical = json.dumps(tasks, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def test_collect_first_call_issues_signing_key():
    """First /api/collect for a new PC returns agent_signing_key + signed pending_tasks."""
    name = f"SignFirst-{_unique}"
    r = _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    assert r.status_code == 200
    data = json.loads(r.data)

    assert "agent_signing_key" in data
    assert isinstance(data["agent_signing_key"], str)
    assert len(data["agent_signing_key"]) >= 64
    assert data["pending_tasks_sig_alg"] == "HMAC-SHA256"
    assert "pending_tasks_sig" in data
    assert len(data["pending_tasks_sig"]) == 64  # SHA-256 hex = 64 chars

    expected = _compute_expected_sig(data["agent_signing_key"], data["pending_tasks"])
    assert hmac.compare_digest(expected, data["pending_tasks_sig"])


def test_collect_second_call_omits_key_but_signs():
    """Second /api/collect for the same PC: no agent_signing_key returned, but sig still valid."""
    name = f"SignSecond-{_unique}"
    r1 = _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    issued_key = json.loads(r1.data)["agent_signing_key"]

    r2 = _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    assert r2.status_code == 200
    data2 = json.loads(r2.data)

    # Second response must NOT redeliver the key
    assert "agent_signing_key" not in data2
    assert data2["pending_tasks_sig_alg"] == "HMAC-SHA256"

    # Recomputing with the originally issued key still verifies
    expected = _compute_expected_sig(issued_key, data2["pending_tasks"])
    assert hmac.compare_digest(expected, data2["pending_tasks_sig"])


def test_collect_signing_key_persisted_on_pc():
    """Issued signing key is stored on the PC row (non-empty, stable across calls)."""
    name = f"SignPersist-{_unique}"
    r1 = _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    issued_key = json.loads(r1.data)["agent_signing_key"]

    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        assert pc.agent_signing_key == issued_key

    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        assert pc.agent_signing_key == issued_key  # unchanged on subsequent calls


def test_collect_signature_detects_tampering():
    """Tampering with pending_tasks invalidates the signature."""
    name = f"SignTamper-{_unique}"
    r = _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    data = json.loads(r.data)
    key = data["agent_signing_key"]

    tampered = list(data["pending_tasks"]) + [{"id": 999, "task_type": "evil"}]
    bad_sig = _compute_expected_sig(key, tampered)
    assert not hmac.compare_digest(bad_sig, data["pending_tasks_sig"])


def test_collect_signing_key_not_in_to_dict():
    """PC.to_dict() must never leak agent_signing_key (server-internal secret)."""
    name = f"SignNoLeak-{_unique}"
    _agent_req("POST", "/api/collect", data=_pc_payload(pc_name=name))
    with app.app_context():
        pc = PC.query.filter_by(pc_name=name).first()
        d = pc.to_dict()
        assert "agent_signing_key" not in d

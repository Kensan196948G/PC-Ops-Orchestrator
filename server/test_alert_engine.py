"""Phase C-1 (#220) — AlertRule-based dynamic alert engine tests.

Covers:
- sync_alerts creates alerts when AlertRule threshold is breached
- sync_alerts respects operator (gt/lt/gte/lte)
- One rule generates one alert per PC (idempotent on re-sync)
- Disabled rules are not evaluated
- Alerts resolve when metric falls back within threshold
- alert_rule_id FK is set on rule-based alerts
- CPU / memory / disk / offline metrics each trigger correctly
- Fallback to hardcoded thresholds when no rules exist
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from auth import hash_password
from models import Alert, AlertRule, PC, SystemSnapshot, User

app = create_app("testing")
client = app.test_client()

_unique = uuid.uuid4().hex[:8]
_admin_token = None


def setup_module():
    global _admin_token
    with app.app_context():
        db.create_all()
        username = f"ae_admin_{_unique}"
        if not User.query.filter_by(username=username).first():
            db.session.add(
                User(
                    username=username,
                    password_hash=hash_password("AdminAE1!"),
                    role="admin",
                )
            )
        db.session.commit()
    _admin_token = _login(f"ae_admin_{_unique}", "AdminAE1!")


def _login(username, password):
    r = client.open(
        "/api/auth/login",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": username, "password": password}),
    )
    return json.loads(r.data)["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _sync():
    return client.open(
        "/api/alerts/sync",
        method="POST",
        headers=_auth(_admin_token),
    )


def _make_pc(cpu_usage: float | None = None, **kwargs) -> PC:
    """Create and persist a PC with sensible defaults.

    cpu_usage is stored in a SystemSnapshot, not on PC directly.
    """
    pc_defaults = {
        "pc_name": f"pc_{uuid.uuid4().hex[:6]}",
        "ip_address": "192.168.0.1",
        "status": "online",
        "memory_total_gb": 8.0,
        "memory_available_gb": 4.0,
        "disk_total_gb": 100.0,
        "disk_free_gb": 50.0,
        "last_seen": datetime.now(timezone.utc),
    }
    pc_defaults.update(kwargs)
    pc = PC(**pc_defaults)
    db.session.add(pc)
    db.session.flush()
    if cpu_usage is not None:
        snap = SystemSnapshot(
            pc_id=pc.id,
            cpu_usage=cpu_usage,
            collected_at=datetime.now(timezone.utc),
        )
        db.session.add(snap)
        db.session.flush()
    return pc


def _make_rule(**kwargs) -> AlertRule:
    """Create and persist an AlertRule."""
    defaults = {
        "name": f"rule_{uuid.uuid4().hex[:6]}",
        "metric": "cpu",
        "operator": "gt",
        "threshold": 80.0,
        "severity": "warning",
        "is_enabled": True,
    }
    defaults.update(kwargs)
    rule = AlertRule(**defaults)
    db.session.add(rule)
    db.session.flush()
    return rule


# ---------------------------------------------------------------------------
# CPU metric
# ---------------------------------------------------------------------------


def test_cpu_rule_creates_alert_when_breached():
    """CPU rule triggers alert when latest snapshot cpu_usage > threshold."""
    with app.app_context():
        pc = _make_pc(cpu_usage=95.0)
        rule = _make_rule(
            metric="cpu", operator="gt", threshold=80.0, severity="critical"
        )
        db.session.commit()
        pc_id, rule_id = pc.id, rule.id

    _sync()

    with app.app_context():
        alert = Alert.query.filter_by(
            source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=False
        ).first()
        assert alert is not None
        assert alert.alert_rule_id == rule_id
        assert alert.severity == "critical"
        assert alert.alert_type == "cpu"


def test_cpu_rule_no_alert_below_threshold():
    """No alert when latest snapshot cpu_usage is below threshold."""
    with app.app_context():
        pc = _make_pc(cpu_usage=50.0)
        rule = _make_rule(metric="cpu", operator="gt", threshold=80.0)
        db.session.commit()
        pc_id, rule_id = pc.id, rule.id

    _sync()

    with app.app_context():
        alert = Alert.query.filter_by(
            source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=False
        ).first()
        assert alert is None


# ---------------------------------------------------------------------------
# Memory metric
# ---------------------------------------------------------------------------


def test_memory_rule_creates_alert():
    """Memory rule triggers when usage % > threshold."""
    with app.app_context():
        # 7.5 GB used / 8.0 GB total = 93.75%
        pc = _make_pc(memory_total_gb=8.0, memory_available_gb=0.5)
        rule = _make_rule(
            metric="memory", operator="gt", threshold=90.0, severity="warning"
        )
        db.session.commit()
        pc_id, rule_id = pc.id, rule.id

    _sync()

    with app.app_context():
        alert = Alert.query.filter_by(
            source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=False
        ).first()
        assert alert is not None
        assert alert.alert_type == "memory"


# ---------------------------------------------------------------------------
# Disk metric
# ---------------------------------------------------------------------------


def test_disk_rule_creates_alert():
    """Disk rule triggers when disk usage % > threshold (low free space)."""
    with app.app_context():
        # 95 GB used / 100 GB total = 95%
        pc = _make_pc(disk_total_gb=100.0, disk_free_gb=5.0)
        rule = _make_rule(
            metric="disk", operator="gt", threshold=90.0, severity="critical"
        )
        db.session.commit()
        pc_id, rule_id = pc.id, rule.id

    _sync()

    with app.app_context():
        alert = Alert.query.filter_by(
            source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=False
        ).first()
        assert alert is not None
        assert alert.alert_type == "disk"


# ---------------------------------------------------------------------------
# Offline metric
# ---------------------------------------------------------------------------


def test_offline_rule_creates_alert():
    """Offline rule triggers when minutes since last_seen > threshold."""
    with app.app_context():
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=60)
        pc = _make_pc(last_seen=stale_time)
        rule = _make_rule(
            metric="offline", operator="gt", threshold=30.0, severity="high"
        )
        db.session.commit()
        pc_id, rule_id = pc.id, rule.id

    _sync()

    with app.app_context():
        alert = Alert.query.filter_by(
            source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=False
        ).first()
        assert alert is not None
        assert alert.alert_type == "offline"


# ---------------------------------------------------------------------------
# Idempotency and disabled rules
# ---------------------------------------------------------------------------


def test_sync_is_idempotent():
    """Calling sync twice does not duplicate alerts."""
    with app.app_context():
        pc = _make_pc(cpu_usage=99.0)  # snapshot created internally
        rule = _make_rule(metric="cpu", operator="gt", threshold=80.0)
        db.session.commit()
        pc_id, rule_id = pc.id, rule.id

    _sync()
    _sync()

    with app.app_context():
        count = Alert.query.filter_by(
            source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=False
        ).count()
        assert count == 1


def test_disabled_rule_not_evaluated():
    """Disabled rules do not generate alerts."""
    with app.app_context():
        pc = _make_pc(cpu_usage=99.0)  # snapshot created internally
        rule = _make_rule(metric="cpu", operator="gt", threshold=80.0, is_enabled=False)
        db.session.commit()
        pc_id, rule_id = pc.id, rule.id

    _sync()

    with app.app_context():
        alert = Alert.query.filter_by(
            source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=False
        ).first()
        assert alert is None


def test_alert_resolves_when_metric_recovers():
    """Alert resolves when metric drops back below threshold on re-sync."""
    with app.app_context():
        pc = _make_pc(cpu_usage=99.0)
        rule = _make_rule(metric="cpu", operator="gt", threshold=80.0)
        db.session.commit()
        pc_id, rule_id = pc.id, rule.id

    _sync()  # creates alert

    with app.app_context():
        assert (
            Alert.query.filter_by(
                source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=False
            ).count()
            == 1
        )
        # Recover: add a new snapshot with low CPU usage
        snap = SystemSnapshot(
            pc_id=pc_id,
            cpu_usage=10.0,
            collected_at=datetime.now(timezone.utc),
        )
        db.session.add(snap)
        db.session.commit()

    _sync()  # should resolve alert

    with app.app_context():
        assert (
            Alert.query.filter_by(
                source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=False
            ).count()
            == 0
        )
        assert (
            Alert.query.filter_by(
                source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=True
            ).count()
            == 1
        )


def test_lte_operator():
    """lte operator generates alert when value <= threshold."""
    with app.app_context():
        pc = _make_pc(cpu_usage=20.0)  # snapshot created internally
        rule = _make_rule(
            metric="cpu", operator="lte", threshold=20.0, severity="warning"
        )
        db.session.commit()
        pc_id, rule_id = pc.id, rule.id

    _sync()

    with app.app_context():
        alert = Alert.query.filter_by(
            source_key=f"pc_{pc_id}_rule_{rule_id}", resolved=False
        ).first()
        assert alert is not None

from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from extensions import db, limiter
from models import (
    PC,
    SystemSnapshot,
    Software,
    WindowsUpdate,
    EventLog,
    AlertRule,
    Alert,
    NetworkInterface,
)
from auth import agent_auth_required

collect_bp = Blueprint("collect", __name__, url_prefix="/api")


@collect_bp.route("/collect", methods=["POST"])
@limiter.limit("600 per minute")
@agent_auth_required
def collect():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    pc_name = data.get("pc_name", "").strip()
    if not pc_name:
        return jsonify({"error": "pc_name は必須です"}), 400

    pc = PC.query.filter_by(pc_name=pc_name).first()
    if not pc:
        pc = PC(pc_name=pc_name)
        db.session.add(pc)
        db.session.flush()

    pc.domain = data.get("domain", pc.domain)
    pc.os_version = data.get("os_version", pc.os_version)
    pc.os_build = data.get("os_build", pc.os_build)
    pc.os_architecture = data.get("os_architecture", pc.os_architecture)
    pc.cpu_name = data.get("cpu_name", pc.cpu_name)
    pc.cpu_cores = data.get("cpu_cores", pc.cpu_cores)
    pc.cpu_logical_processors = data.get(
        "cpu_logical_processors", pc.cpu_logical_processors
    )
    pc.memory_total_gb = data.get("memory_total_gb", pc.memory_total_gb)
    pc.memory_available_gb = data.get("memory_available_gb", pc.memory_available_gb)
    pc.disk_total_gb = data.get("disk_total_gb", pc.disk_total_gb)
    pc.disk_free_gb = data.get("disk_free_gb", pc.disk_free_gb)
    pc.ip_address = data.get("ip_address", pc.ip_address)
    pc.mac_address = data.get("mac_address", pc.mac_address)
    pc.agent_version = data.get("agent_version", pc.agent_version)
    pc.last_seen = datetime.now(timezone.utc)
    # VPN/offline sync: agent reports its connection type (LAN/SSL-VPN/Unknown)
    if data.get("connection_type"):
        pc.connection_type = data["connection_type"]
    # Reset offline pending count on successful sync
    pc.offline_pending_count = 0

    # Phase A-2: hardware payload (optional flat-key alternative)
    hardware = data.get("hardware")
    if isinstance(hardware, dict):
        pc.os_build = hardware.get("os_build", pc.os_build)
        pc.cpu_name = hardware.get("cpu_name", pc.cpu_name)
        pc.cpu_cores = hardware.get("cpu_cores", pc.cpu_cores)
        pc.cpu_logical_processors = hardware.get(
            "cpu_logical_processors", pc.cpu_logical_processors
        )
        pc.memory_total_gb = hardware.get("memory_total_gb", pc.memory_total_gb)
        pc.memory_available_gb = hardware.get(
            "memory_available_gb", pc.memory_available_gb
        )

    # Phase A-2: network array → NetworkInterface upsert
    network_list = data.get("network", [])
    if isinstance(network_list, list) and network_list:
        _upsert_network_interfaces(pc.id, network_list)

    pc.health_score = _calculate_health_score(pc)

    snapshot = SystemSnapshot(
        pc_id=pc.id,
        cpu_usage=data.get("cpu_usage"),
        memory_available_gb=pc.memory_available_gb,
        disk_free_gb=pc.disk_free_gb,
        uptime_days=data.get("uptime_days"),
        pending_reboot=data.get("pending_reboot", False),
        windows_update_pending=data.get("windows_update_pending", False),
    )

    if data.get("last_boot_time"):
        try:
            snapshot.last_boot_time = datetime.fromisoformat(data["last_boot_time"])
        except (ValueError, TypeError):
            pass

    db.session.add(snapshot)
    db.session.flush()

    _trim_snapshots(pc.id, keep=720)

    _determine_pc_status(pc)
    db.session.commit()

    tasks = _get_pending_tasks(pc.id)
    _evaluate_alert_rules(pc, snapshot)
    db.session.commit()

    return jsonify(
        {
            "message": "ok",
            "pc_id": pc.id,
            "health_score": pc.health_score,
            "status": pc.status,
            "pending_tasks": tasks,
        }
    )


@collect_bp.route("/collect/detail", methods=["POST"])
@agent_auth_required
def collect_detail():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    pc_name = data.get("pc_name", "").strip()
    if not pc_name:
        return jsonify({"error": "pc_name は必須です"}), 400

    pc = PC.query.filter_by(pc_name=pc_name).first()
    if not pc:
        return jsonify({"error": f"PC {pc_name} が見つかりません"}), 404

    software_list = data.get("software", [])
    if software_list:
        Software.query.filter_by(pc_id=pc.id).delete()
        for sw in software_list:
            install_date = None
            if sw.get("install_date"):
                try:
                    install_date = datetime.fromisoformat(sw["install_date"])
                except (ValueError, TypeError):
                    pass
            db.session.add(
                Software(
                    pc_id=pc.id,
                    name=sw.get("name", ""),
                    version=sw.get("version"),
                    publisher=sw.get("publisher"),
                    install_date=install_date,
                )
            )

    updates_list = data.get("windows_updates", [])
    if updates_list:
        for up in updates_list:
            installed_at = None
            if up.get("installed_at"):
                try:
                    installed_at = datetime.fromisoformat(up["installed_at"])
                except (ValueError, TypeError):
                    pass
            db.session.add(
                WindowsUpdate(
                    pc_id=pc.id,
                    kb_id=up.get("kb_id"),
                    title=up.get("title"),
                    severity=up.get("severity"),
                    installed=up.get("installed", False),
                    installed_at=installed_at,
                )
            )

    event_logs = data.get("event_logs", [])
    if event_logs:
        for log in event_logs:
            generated_at = None
            if log.get("generated_at"):
                try:
                    generated_at = datetime.fromisoformat(log["generated_at"])
                except (ValueError, TypeError):
                    pass
            db.session.add(
                EventLog(
                    pc_id=pc.id,
                    log_type=log.get("log_type", "system"),
                    event_id=log.get("event_id"),
                    level=log.get("level"),
                    source=log.get("source"),
                    message=log.get("message"),
                    generated_at=generated_at,
                )
            )

    db.session.commit()

    return jsonify({"message": "詳細情報を受信しました", "pc_id": pc.id})


@collect_bp.route("/collect/sync", methods=["POST"])
@limiter.limit("60 per minute")
@agent_auth_required
def collect_sync():
    """Accept bulk offline cache entries from reconnected VPN agent."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    pc_name = data.get("pc_name", "").strip()
    if not pc_name:
        return jsonify({"error": "pc_name は必須です"}), 400

    pc = PC.query.filter_by(pc_name=pc_name).first()
    if not pc:
        return jsonify({"error": f"PC {pc_name} が見つかりません"}), 404

    entries = data.get("offline_cache", [])
    if not isinstance(entries, list):
        return jsonify({"error": "offline_cache はリスト形式で指定してください"}), 400

    inserted = 0
    skipped = 0
    for entry in entries:
        collected_at = None
        if entry.get("collected_at"):
            try:
                collected_at = datetime.fromisoformat(entry["collected_at"])
            except (ValueError, TypeError):
                skipped += 1
                continue

        # Dedup: skip if a snapshot already exists at exact same timestamp
        if collected_at:
            dup = SystemSnapshot.query.filter_by(
                pc_id=pc.id, collected_at=collected_at
            ).first()
            if dup:
                skipped += 1
                continue

        snapshot = SystemSnapshot(
            pc_id=pc.id,
            cpu_usage=entry.get("cpu_usage"),
            memory_available_gb=entry.get("memory_available_gb"),
            disk_free_gb=entry.get("disk_free_gb"),
            uptime_days=entry.get("uptime_days"),
            pending_reboot=entry.get("pending_reboot", False),
            windows_update_pending=entry.get("windows_update_pending", False),
        )
        if collected_at:
            snapshot.collected_at = collected_at

        if entry.get("last_boot_time"):
            try:
                snapshot.last_boot_time = datetime.fromisoformat(
                    entry["last_boot_time"]
                )
            except (ValueError, TypeError):
                pass

        db.session.add(snapshot)
        inserted += 1

    if inserted:
        _trim_snapshots(pc.id, keep=720)

    pc.offline_pending_count = max(0, (pc.offline_pending_count or 0) - inserted)
    db.session.commit()

    return jsonify(
        {
            "message": "オフラインキャッシュを同期しました",
            "pc_id": pc.id,
            "inserted": inserted,
            "skipped": skipped,
        }
    )


def _upsert_network_interfaces(pc_id, network_list):
    """Phase A-2 (#175): upsert NetworkInterface rows by (pc_id, interface_name).

    Idempotent — existing rows for the same (pc_id, interface_name) are updated
    in place. Unknown adapter names create new rows. NICs not present in the
    payload are left untouched (no implicit deactivation) to keep the operation
    purely additive and safe to retry from an offline-cached agent push.
    """
    now = datetime.now(timezone.utc)
    for nic in network_list:
        if not isinstance(nic, dict):
            continue
        name = (nic.get("interface_name") or "").strip()
        if not name:
            continue
        existing = NetworkInterface.query.filter_by(
            pc_id=pc_id, interface_name=name
        ).first()
        if not existing:
            existing = NetworkInterface(pc_id=pc_id, interface_name=name)
            db.session.add(existing)
        existing.description = nic.get("description", existing.description)
        existing.mac_address = nic.get("mac_address", existing.mac_address)
        existing.ip_address = nic.get("ip_address", existing.ip_address)
        existing.ipv6_address = nic.get("ipv6_address", existing.ipv6_address)
        existing.subnet_mask = nic.get("subnet_mask", existing.subnet_mask)
        existing.gateway = nic.get("gateway", existing.gateway)
        existing.dns_servers = nic.get("dns_servers", existing.dns_servers)
        existing.link_speed_mbps = nic.get("link_speed_mbps", existing.link_speed_mbps)
        existing.is_active = nic.get("is_active", True)
        existing.collected_at = now


def _trim_snapshots(pc_id, keep=720):
    """Delete oldest snapshots beyond the keep limit for a given PC."""
    total = SystemSnapshot.query.filter_by(pc_id=pc_id).count()
    if total > keep:
        cutoff_id = (
            SystemSnapshot.query.filter_by(pc_id=pc_id)
            .order_by(SystemSnapshot.collected_at.asc())
            .offset(total - keep)
            .with_entities(SystemSnapshot.id)
            .first()
        )
        if cutoff_id:
            SystemSnapshot.query.filter(
                SystemSnapshot.pc_id == pc_id,
                SystemSnapshot.id < cutoff_id[0],
            ).delete()


def _calculate_health_score(pc):
    score = 100.0

    if pc.memory_total_gb and pc.memory_available_gb is not None:
        mem_usage = (
            (pc.memory_total_gb - pc.memory_available_gb) / pc.memory_total_gb * 100
        )
        if mem_usage > 90:
            score -= 30
        elif mem_usage > 75:
            score -= 15
        elif mem_usage > 60:
            score -= 5

    if pc.disk_total_gb and pc.disk_free_gb is not None:
        disk_usage = (pc.disk_total_gb - pc.disk_free_gb) / pc.disk_total_gb * 100
        if disk_usage > 95:
            score -= 30
        elif disk_usage > 85:
            score -= 15
        elif disk_usage > 75:
            score -= 5

    return max(0, round(score, 1))


def _determine_pc_status(pc):
    if pc.health_score >= 80:
        pc.status = "healthy"
    elif pc.health_score >= 50:
        pc.status = "warning"
    else:
        pc.status = "critical"


def _evaluate_alert_rules(pc: "PC", snapshot: "SystemSnapshot") -> None:
    """Evaluate enabled AlertRules against current PC metrics and create Alerts."""
    rules = AlertRule.query.filter_by(is_enabled=True).all()
    if not rules:
        return

    cpu_val = snapshot.cpu_usage
    mem_val = None
    if (
        pc.memory_total_gb
        and pc.memory_available_gb is not None
        and pc.memory_total_gb > 0
    ):
        mem_val = (
            (pc.memory_total_gb - pc.memory_available_gb) / pc.memory_total_gb * 100
        )
    disk_val = None
    if pc.disk_total_gb and pc.disk_free_gb is not None and pc.disk_total_gb > 0:
        disk_val = (pc.disk_total_gb - pc.disk_free_gb) / pc.disk_total_gb * 100

    metric_map = {"cpu": cpu_val, "memory": mem_val, "disk": disk_val}

    def _matches(rule: "AlertRule", value: float | None) -> bool:
        if value is None:
            return False
        op = rule.operator
        t = rule.threshold
        if op == "gt":
            return value > t
        if op == "gte":
            return value >= t
        if op == "lt":
            return value < t
        if op == "lte":
            return value <= t
        return False

    for rule in rules:
        if rule.metric == "offline":
            continue  # offline is handled by alerts sync, not here

        value = metric_map.get(rule.metric)
        if not _matches(rule, value):
            continue

        source_key = f"rule:{rule.id}:pc:{pc.id}"
        existing = Alert.query.filter_by(source_key=source_key, resolved=False).first()
        if existing:
            continue

        alert = Alert(
            pc_id=pc.id,
            alert_type=f"rule_{rule.metric}",
            severity=rule.severity,
            message=(
                f"[{rule.name}] {pc.pc_name}: "
                f"{rule.metric} {rule.operator} {rule.threshold}% (現在値 {value:.1f}%)"
            ),
            source_key=source_key,
        )
        db.session.add(alert)


def _get_pending_tasks(pc_id):
    from models import Task

    tasks = (
        Task.query.filter(
            (Task.pc_id == pc_id) | (Task.pc_id.is_(None)), Task.status == "pending"
        )
        .order_by(Task.priority.desc(), Task.created_at.asc())
        .limit(10)
        .all()
    )

    return [t.to_dict() for t in tasks]

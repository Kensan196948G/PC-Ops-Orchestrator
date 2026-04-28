from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from extensions import db
from models import PC, SystemSnapshot, Software, WindowsUpdate, EventLog
from auth import agent_auth_required

collect_bp = Blueprint("collect", __name__, url_prefix="/api")


@collect_bp.route("/collect", methods=["POST"])
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

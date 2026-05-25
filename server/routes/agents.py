import csv
import io
from datetime import datetime, timedelta, timezone
from flask import Blueprint, jsonify, make_response, request
from sqlalchemy import case
from auth import login_required
from extensions import db
from models import PC, NetworkPingLog, SystemSnapshot, Task

VALID_CHECK_TYPES = {"ping", "dns", "vpn", "wifi"}
VALID_STATUSES = {"ok", "timeout", "error", "unreachable"}

agents_bp = Blueprint("agents", __name__, url_prefix="/api")


@agents_bp.route("/agents/export.csv", methods=["GET"])
@login_required
def export_agents_csv():
    """Export all PCs as agent entries in CSV format."""
    now = datetime.now(timezone.utc)
    pcs = (
        PC.query.order_by(
            case((PC.last_seen.is_(None), 1), else_=0), PC.last_seen.desc()
        )
        .limit(5000)
        .all()
    )

    # Fetch latest snapshot per PC to avoid N+1
    pc_ids = [pc.id for pc in pcs]
    latest_snaps: dict = {}
    if pc_ids:
        subq = (
            db.session.query(
                SystemSnapshot.pc_id,
                db.func.max(SystemSnapshot.collected_at).label("max_at"),
            )
            .filter(SystemSnapshot.pc_id.in_(pc_ids))
            .group_by(SystemSnapshot.pc_id)
            .subquery()
        )
        for snap in db.session.query(SystemSnapshot).join(
            subq,
            (SystemSnapshot.pc_id == subq.c.pc_id)
            & (SystemSnapshot.collected_at == subq.c.max_at),
        ):
            latest_snaps[snap.pc_id] = snap

    buf = io.StringIO()
    buf.write("﻿")  # BOM for Excel (utf-8-sig)
    writer = csv.writer(buf)
    writer.writerow(
        [
            "ホスト名",
            "OSバージョン",
            "IPアドレス",
            "CPU使用率",
            "メモリ使用率",
            "Agentバージョン",
            "最終heartbeat",
            "状態",
        ]
    )
    for pc in pcs:
        last_seen_dt = None
        if pc.last_seen:
            if pc.last_seen.tzinfo is None:
                last_seen_dt = pc.last_seen.replace(tzinfo=timezone.utc)
            else:  # pragma: no cover - SQLite strips tzinfo; reachable only on PostgreSQL
                last_seen_dt = pc.last_seen

        elapsed = (now - last_seen_dt).total_seconds() if last_seen_dt else float("inf")
        if elapsed < 300:
            status_label = "オンライン"
        elif elapsed < 1800:
            status_label = "最近接続"
        elif elapsed < 604800:
            status_label = "オフライン"
        else:
            status_label = "古いデータ"

        snap = latest_snaps.get(pc.id)
        cpu_usage = snap.cpu_usage if snap else None

        memory_usage = None
        if pc.memory_total_gb and pc.memory_available_gb is not None:
            used = pc.memory_total_gb - pc.memory_available_gb
            memory_usage = round(used / pc.memory_total_gb * 100, 1)

        writer.writerow(
            [
                pc.pc_name or "",
                pc.os_version or "",
                pc.ip_address or "",
                f"{cpu_usage:.1f}" if cpu_usage is not None else "",
                f"{memory_usage:.1f}" if memory_usage is not None else "",
                pc.agent_version or "",
                pc.last_seen.isoformat() if pc.last_seen else "",
                status_label,
            ]
        )

    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    response.headers["Content-Disposition"] = 'attachment; filename="agents.csv"'
    return response


@agents_bp.route("/agents", methods=["GET"])
@login_required
def list_agents():
    """List all PCs as agent entries with CPU/memory/version/heartbeat."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    status = request.args.get("status", "")

    q = PC.query
    if status:
        q = q.filter(PC.status == status)
    # Sort: last_seen DESC, NULLs last (SQLite-compatible via CASE)
    q = q.order_by(case((PC.last_seen.is_(None), 1), else_=0), PC.last_seen.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    now = datetime.now(timezone.utc)

    pc_ids = [pc.id for pc in pagination.items]
    # Fetch latest snapshot per PC in one query to avoid N+1
    latest_snaps = {}
    if pc_ids:
        subq = (
            db.session.query(
                SystemSnapshot.pc_id,
                db.func.max(SystemSnapshot.collected_at).label("max_at"),
            )
            .filter(SystemSnapshot.pc_id.in_(pc_ids))
            .group_by(SystemSnapshot.pc_id)
            .subquery()
        )
        for snap in db.session.query(SystemSnapshot).join(
            subq,
            (SystemSnapshot.pc_id == subq.c.pc_id)
            & (SystemSnapshot.collected_at == subq.c.max_at),
        ):
            latest_snaps[snap.pc_id] = snap

    # Aggregate pending/running task count per PC in one query to avoid N+1
    pending_job_counts: dict[int, int] = {}
    if pc_ids:
        rows = (
            db.session.query(Task.pc_id, db.func.count(Task.id))
            .filter(Task.pc_id.in_(pc_ids))
            .filter(Task.status.in_(("pending", "running")))
            .group_by(Task.pc_id)
            .all()
        )
        pending_job_counts = {pc_id: cnt for pc_id, cnt in rows if pc_id is not None}

    def _online_status(last_seen_dt):
        """Return 4-state online status based on last_seen age."""
        if last_seen_dt is None:
            return "stale"
        elapsed = (now - last_seen_dt).total_seconds()
        if elapsed < 300:
            return "online"
        if elapsed < 1800:
            return "recently_seen"
        if elapsed < 604800:
            return "offline"
        return "stale"

    def _sub_states(pc, pending_job_count):
        """Derive Issue #180 sub-state flags (orthogonal to base online_status).

        - vpn_required: PC is currently reaching the server via SSL-VPN
        - pending_sync: agent has offline cache rows waiting to be flushed
        - pending_job: server has pending/running tasks queued for this PC
        """
        flags = []
        if (pc.connection_type or "").upper() in ("SSL-VPN", "VPN"):
            flags.append("vpn_required")
        if (pc.offline_pending_count or 0) > 0:
            flags.append("pending_sync")
        if pending_job_count > 0:
            flags.append("pending_job")
        return flags

    def agent_dict(pc):
        last_seen_dt = None
        if pc.last_seen:
            if pc.last_seen.tzinfo is None:
                last_seen_dt = pc.last_seen.replace(tzinfo=timezone.utc)
            else:  # pragma: no cover - SQLite strips tzinfo; reachable only on PostgreSQL
                last_seen_dt = pc.last_seen
        online_status = _online_status(last_seen_dt)
        snap = latest_snaps.get(pc.id)
        cpu_usage = snap.cpu_usage if snap else None
        memory_usage = None
        if pc.memory_total_gb and pc.memory_available_gb is not None:
            used = pc.memory_total_gb - pc.memory_available_gb
            memory_usage = round(used / pc.memory_total_gb * 100, 1)
        pending_job_count = pending_job_counts.get(pc.id, 0)
        return {
            "id": pc.id,
            "pc_name": pc.pc_name,
            "ip_address": pc.ip_address,
            "os_version": pc.os_version,
            "agent_version": pc.agent_version or "—",
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "status": pc.status,
            "online": online_status == "online",
            "online_status": online_status,
            "connection_type": pc.connection_type or "Unknown",
            "offline_pending_count": pc.offline_pending_count or 0,
            "pending_job_count": pending_job_count,
            "sub_states": _sub_states(pc, pending_job_count),
            "last_seen": pc.last_seen.isoformat() if pc.last_seen else None,
        }

    return jsonify(
        {
            "agents": [agent_dict(pc) for pc in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
        }
    )


@agents_bp.route("/agents/<int:pc_id>/network-status", methods=["GET"])
@login_required
def get_network_status(pc_id):
    """GET /api/agents/<pc_id>/network-status — latest connectivity checks (Issue #246)."""
    pc = db.session.get(PC, pc_id)
    if pc is None:
        return jsonify({"error": "PC not found"}), 404

    hours = request.args.get("hours", 24, type=int)
    check_type = request.args.get("check_type", "")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    q = NetworkPingLog.query.filter(
        NetworkPingLog.pc_id == pc_id,
        NetworkPingLog.checked_at >= cutoff,
    )
    if check_type and check_type in VALID_CHECK_TYPES:
        q = q.filter(NetworkPingLog.check_type == check_type)
    logs = q.order_by(NetworkPingLog.checked_at.desc()).limit(200).all()

    # Latest record per check_type
    latest: dict[str, dict] = {}
    for log in reversed(logs):
        latest[log.check_type] = log.to_dict()

    # Summary: count ok/error per type
    summary: dict[str, dict] = {}
    for log in logs:
        s = summary.setdefault(log.check_type, {"ok": 0, "error": 0, "total": 0})
        s["total"] += 1
        if log.status == "ok":
            s["ok"] += 1
        else:
            s["error"] += 1

    return jsonify(
        {
            "pc_id": pc.id,
            "pc_name": pc.pc_name,
            "hours": hours,
            "latest": latest,
            "summary": summary,
            "records": [log.to_dict() for log in logs],
        }
    )


@agents_bp.route("/agents/<int:pc_id>/network-status", methods=["POST"])
@login_required
def record_network_status(pc_id):
    """POST /api/agents/<pc_id>/network-status — submit connectivity check results."""
    pc = db.session.get(PC, pc_id)
    if pc is None:
        return jsonify({"error": "PC not found"}), 404

    data = request.get_json(force=True) or {}

    # Support both single record and batch (list)
    records = data if isinstance(data, list) else [data]
    created = []
    errors = []

    for idx, item in enumerate(records):
        check_type = item.get("check_type", "")
        status = item.get("status", "")
        if check_type not in VALID_CHECK_TYPES:
            errors.append({"index": idx, "error": f"invalid check_type: {check_type}"})
            continue
        if status not in VALID_STATUSES:
            errors.append({"index": idx, "error": f"invalid status: {status}"})
            continue

        latency = item.get("latency_ms")
        if latency is not None:
            try:
                latency = int(latency)
            except (TypeError, ValueError):
                latency = None

        ts_raw = item.get("checked_at")
        if ts_raw:
            try:
                checked_at = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                errors.append({"index": idx, "error": "invalid checked_at format"})
                continue
        else:
            checked_at = datetime.now(timezone.utc)

        log = NetworkPingLog(
            pc_id=pc.id,
            check_type=check_type,
            target=item.get("target"),
            status=status,
            latency_ms=latency,
            checked_at=checked_at,
        )
        db.session.add(log)
        created.append(log)

    if created:
        db.session.commit()

    result = {"created": len(created), "errors": errors}
    if errors and not created:
        return jsonify(result), 400
    return jsonify(result), 201

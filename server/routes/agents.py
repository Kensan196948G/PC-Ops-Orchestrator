from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from sqlalchemy import case
from auth import login_required
from extensions import db
from models import PC, SystemSnapshot

agents_bp = Blueprint("agents", __name__, url_prefix="/api")


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

    def agent_dict(pc):
        last_seen_dt = None
        if pc.last_seen:
            if pc.last_seen.tzinfo is None:
                last_seen_dt = pc.last_seen.replace(tzinfo=timezone.utc)
            else:
                last_seen_dt = pc.last_seen
        online = last_seen_dt is not None and (now - last_seen_dt).total_seconds() < 300
        snap = latest_snaps.get(pc.id)
        cpu_usage = snap.cpu_usage if snap else None
        memory_usage = None
        if pc.memory_total_gb and pc.memory_available_gb is not None:
            used = pc.memory_total_gb - pc.memory_available_gb
            memory_usage = round(used / pc.memory_total_gb * 100, 1)
        return {
            "id": pc.id,
            "pc_name": pc.pc_name,
            "ip_address": pc.ip_address,
            "os_version": pc.os_version,
            "agent_version": pc.agent_version or "—",
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "status": pc.status,
            "online": online,
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

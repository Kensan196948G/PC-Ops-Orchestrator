from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from auth import login_required
from models import PC

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
    q = q.order_by(PC.last_seen.desc().nullslast())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    now = datetime.now(timezone.utc)

    def agent_dict(pc):
        last_seen_dt = None
        if pc.last_seen:
            if pc.last_seen.tzinfo is None:
                last_seen_dt = pc.last_seen.replace(tzinfo=timezone.utc)
            else:
                last_seen_dt = pc.last_seen
        online = last_seen_dt is not None and (now - last_seen_dt).total_seconds() < 300
        return {
            "id": pc.id,
            "pc_name": pc.pc_name,
            "ip_address": pc.ip_address,
            "os_version": pc.os_version,
            "agent_version": pc.agent_version or "—",
            "cpu_usage": pc.cpu_usage,
            "memory_usage": pc.memory_usage,
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

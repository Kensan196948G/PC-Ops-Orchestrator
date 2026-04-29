from flask import Blueprint, request, jsonify
from models import OperationLog
from auth import require_role

audit_bp = Blueprint("audit", __name__, url_prefix="/api/audit")


@audit_bp.route("/logs", methods=["GET"])
@require_role("admin", "operator")
def list_logs():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    created_by = request.args.get("created_by", "").strip()
    action = request.args.get("action", "").strip()

    query = OperationLog.query
    if created_by:
        query = query.filter(OperationLog.created_by.ilike(f"%{created_by}%"))
    if action:
        query = query.filter(OperationLog.action.ilike(f"%{action}%"))

    query = query.order_by(OperationLog.created_at.desc())
    total = query.count()
    logs = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify(
        {
            "logs": [lo.to_dict() for lo in logs],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }
    )

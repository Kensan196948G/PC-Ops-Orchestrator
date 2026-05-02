import csv
import io
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, make_response
from models import OperationLog
from auth import require_role

audit_bp = Blueprint("audit", __name__, url_prefix="/api/audit")


def _build_query():
    """Build OperationLog query from shared request parameters."""
    created_by = request.args.get("created_by", "").strip()
    action = request.args.get("action", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()

    query = OperationLog.query
    if created_by:
        query = query.filter(OperationLog.created_by.ilike(f"%{created_by}%"))
    if action:
        query = query.filter(OperationLog.action.ilike(f"%{action}%"))
    if from_date:
        try:
            dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            query = query.filter(OperationLog.created_at >= dt)
        except ValueError:
            pass
    if to_date:
        try:
            dt = datetime.strptime(to_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            query = query.filter(OperationLog.created_at <= dt)
        except ValueError:
            pass

    return query.order_by(OperationLog.created_at.desc())


@audit_bp.route("/logs", methods=["GET"])
@require_role("admin", "operator")
def list_logs():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)

    query = _build_query()
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


@audit_bp.route("/export.csv", methods=["GET"])
@require_role("admin", "operator")
def export_csv():
    """Export audit logs matching current filters as UTF-8 BOM CSV."""
    logs = _build_query().limit(10000).all()

    buf = io.StringIO()
    buf.write("﻿")  # BOM for Excel Japanese compatibility
    writer = csv.writer(buf)
    writer.writerow(["日時", "操作", "対象", "実行者", "IPアドレス"])
    for lo in logs:
        writer.writerow(
            [
                lo.created_at.strftime("%Y/%m/%d %H:%M:%S") if lo.created_at else "",
                lo.action or "",
                lo.target or "",
                lo.created_by or "",
                lo.ip_address or "",
            ]
        )

    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    resp.headers["Content-Disposition"] = "attachment; filename=audit_logs.csv"
    return resp

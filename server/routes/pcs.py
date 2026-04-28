import csv
import io
from flask import Blueprint, request, jsonify, make_response
from extensions import db
from models import PC, SystemSnapshot, Software, Task, WindowsUpdate
from auth import login_required, admin_required, log_operation

pcs_bp = Blueprint("pcs", __name__, url_prefix="/api/pcs")


@pcs_bp.route("", methods=["GET"])
@login_required
def list_pcs():
    status_filter = request.args.get("status")
    search = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)

    os_filter = request.args.get("os", "").strip()

    query = PC.query

    if status_filter:
        query = query.filter(PC.status == status_filter)
    if search:
        query = query.filter(
            db.or_(
                PC.pc_name.ilike(f"%{search}%"),
                PC.ip_address.ilike(f"%{search}%"),
            )
        )
    if os_filter:
        query = query.filter(PC.os_version.ilike(f"%{os_filter}%"))

    query = query.order_by(PC.last_seen.desc().nullslast())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify(
        {
            "pcs": [pc.to_dict() for pc in pagination.items],
            "total": pagination.total,
            "page": page,
            "pages": pagination.pages,
        }
    )


@pcs_bp.route("/export.csv", methods=["GET"])
@login_required
def export_pcs_csv():
    status_filter = request.args.get("status")
    search = request.args.get("search", "").strip()
    os_filter = request.args.get("os", "").strip()

    query = PC.query
    if status_filter:
        query = query.filter(PC.status == status_filter)
    if search:
        query = query.filter(
            db.or_(
                PC.pc_name.ilike(f"%{search}%"),
                PC.ip_address.ilike(f"%{search}%"),
            )
        )
    if os_filter:
        query = query.filter(PC.os_version.ilike(f"%{os_filter}%"))

    pcs = query.order_by(PC.last_seen.desc().nullslast()).limit(5000).all()

    buf = io.StringIO()
    buf.write("﻿")  # BOM for Excel
    writer = csv.writer(buf)
    writer.writerow(
        [
            "ID",
            "PC名",
            "ドメイン",
            "OS",
            "IPアドレス",
            "MACアドレス",
            "状態",
            "ヘルススコア",
            "最終更新",
            "Agentバージョン",
        ]
    )
    for pc in pcs:
        writer.writerow(
            [
                pc.id,
                pc.pc_name or "",
                pc.domain or "",
                pc.os_version or "",
                pc.ip_address or "",
                pc.mac_address or "",
                pc.status or "",
                pc.health_score if pc.health_score is not None else "",
                pc.last_seen.isoformat() if pc.last_seen else "",
                pc.agent_version or "",
            ]
        )

    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=pcs.csv"
    return response


@pcs_bp.route("/<int:pc_id>", methods=["GET"])
@login_required
def get_pc(pc_id):
    pc = db.session.get(PC, pc_id)
    if not pc:
        return jsonify({"error": f"PC {pc_id} が見つかりません"}), 404

    snapshots = (
        SystemSnapshot.query.filter_by(pc_id=pc_id)
        .order_by(SystemSnapshot.collected_at.asc())
        .limit(48)
        .all()
    )

    recent_tasks = (
        Task.query.filter((Task.pc_id == pc_id) | (Task.pc_id.is_(None)))
        .order_by(Task.created_at.desc())
        .limit(20)
        .all()
    )

    return jsonify(
        {
            "pc": pc.to_dict(),
            "snapshots": [s.to_dict() for s in snapshots],
            "recent_tasks": [t.to_dict() for t in recent_tasks],
        }
    )


@pcs_bp.route("/<int:pc_id>/software", methods=["GET"])
@login_required
def get_pc_software(pc_id):
    pc = db.session.get(PC, pc_id)
    if not pc:
        return jsonify({"error": f"PC {pc_id} が見つかりません"}), 404
    software = Software.query.filter_by(pc_id=pc_id).order_by(Software.name).all()
    return jsonify(
        {
            "pc_name": pc.pc_name,
            "software": [s.to_dict() for s in software],
            "total": len(software),
        }
    )


@pcs_bp.route("/<int:pc_id>/updates", methods=["GET"])
@login_required
def get_pc_updates(pc_id):
    pc = db.session.get(PC, pc_id)
    if not pc:
        return jsonify({"error": f"PC {pc_id} が見つかりません"}), 404
    updates = (
        WindowsUpdate.query.filter_by(pc_id=pc_id)
        .order_by(WindowsUpdate.installed_at.desc().nullslast())
        .all()
    )
    return jsonify(
        {
            "pc_name": pc.pc_name,
            "updates": [u.to_dict() for u in updates],
            "total": len(updates),
        }
    )


@pcs_bp.route("/<int:pc_id>/history", methods=["GET"])
@login_required
def get_pc_history(pc_id):
    pc = db.session.get(PC, pc_id)
    if not pc:
        return jsonify({"error": f"PC {pc_id} が見つかりません"}), 404
    days = min(request.args.get("days", 7, type=int), 365)

    from datetime import datetime, timezone, timedelta

    since = datetime.now(timezone.utc) - timedelta(days=days)

    snapshots = (
        SystemSnapshot.query.filter(
            SystemSnapshot.pc_id == pc_id,
            SystemSnapshot.collected_at >= since,
        )
        .order_by(SystemSnapshot.collected_at.asc())
        .all()
    )

    return jsonify(
        {
            "pc_name": pc.pc_name,
            "snapshots": [s.to_dict() for s in snapshots],
        }
    )


@pcs_bp.route("/<int:pc_id>", methods=["DELETE"])
@admin_required
def delete_pc(pc_id):
    pc = db.session.get(PC, pc_id)
    if not pc:
        return jsonify({"error": f"PC {pc_id} が見つかりません"}), 404
    pc_name = pc.pc_name
    db.session.delete(pc)
    db.session.commit()

    log_operation("delete_pc", f"pc:{pc_name}", "PC情報削除")
    return jsonify({"message": f"PC {pc_name} を削除しました"})

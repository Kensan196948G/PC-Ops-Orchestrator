"""User Inquiry routes — Phase D-4 (Issue #241)."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from auth import login_required

from extensions import db
from models import EventLog, Inquiry, KnownIssue, PC, StabilityScore, WindowsUpdate

bp = Blueprint("inquiries", __name__, url_prefix="/api/inquiries")


# ── CRUD ────────────────────────────────────────────────────────────────────


@bp.route("", methods=["GET"])
@login_required
def list_inquiries():
    """GET /api/inquiries — list inquiries, optional status filter."""
    status = request.args.get("status")
    pc_id = request.args.get("pc_id", type=int)
    q = Inquiry.query
    if status:
        q = q.filter(Inquiry.status == status)
    if pc_id:
        q = q.filter(Inquiry.pc_id == pc_id)
    items = q.order_by(Inquiry.created_at.desc()).limit(500).all()
    return jsonify([i.to_dict() for i in items])


@bp.route("", methods=["POST"])
@login_required
def create_inquiry():
    """POST /api/inquiries — register a new inquiry."""
    data = request.get_json() or {}
    if not data.get("subject") or not data.get("inquired_by"):
        return jsonify({"error": "subject and inquired_by are required"}), 400
    pc_id = data.get("pc_id")
    if pc_id and not PC.query.get(pc_id):
        return jsonify({"error": "pc_id not found"}), 404
    known_issue_id = data.get("known_issue_id")
    if known_issue_id and not KnownIssue.query.get(known_issue_id):
        return jsonify({"error": "known_issue_id not found"}), 404
    inquiry = Inquiry(
        pc_id=pc_id,
        inquired_by=data["inquired_by"],
        subject=data["subject"],
        symptom=data.get("symptom"),
        status=data.get("status", "open"),
        known_issue_id=known_issue_id,
        response=data.get("response"),
    )
    db.session.add(inquiry)
    db.session.commit()
    return jsonify(inquiry.to_dict()), 201


@bp.route("/<int:inquiry_id>", methods=["GET"])
@login_required
def get_inquiry(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)
    return jsonify(inquiry.to_dict())


@bp.route("/<int:inquiry_id>", methods=["PUT"])
@login_required
def update_inquiry(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)
    data = request.get_json() or {}
    for field in (
        "subject",
        "symptom",
        "status",
        "known_issue_id",
        "response",
        "pc_id",
    ):
        if field in data:
            setattr(inquiry, field, data[field])
    if data.get("status") == "resolved" and not inquiry.resolved_at:
        inquiry.resolved_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(inquiry.to_dict())


@bp.route("/<int:inquiry_id>", methods=["DELETE"])
@login_required
def delete_inquiry(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)
    db.session.delete(inquiry)
    db.session.commit()
    return jsonify({"deleted": inquiry_id})


# ── Related logs ────────────────────────────────────────────────────────────


@bp.route("/<int:inquiry_id>/related-logs", methods=["GET"])
@login_required
def related_logs(inquiry_id):
    """GET /api/inquiries/<id>/related-logs — correlate inquiry with PC telemetry.

    Returns recent EventLog entries, the latest StabilityScore, and recently
    installed Windows Updates for the inquired PC, within a configurable window
    (default 14 days before the inquiry was created).
    """
    inquiry = Inquiry.query.get_or_404(inquiry_id)
    if not inquiry.pc_id:
        return jsonify(
            {
                "inquiry_id": inquiry_id,
                "pc_id": None,
                "note": "PC が紐付いていないため相関情報なし",
                "event_logs": [],
                "windows_updates": [],
                "stability_score": None,
            }
        )

    days = int(request.args.get("days", 14))
    base = inquiry.created_at or datetime.now(timezone.utc)
    cutoff = base - timedelta(days=days)

    events = (
        EventLog.query.filter(
            EventLog.pc_id == inquiry.pc_id,
            EventLog.generated_at >= cutoff,
            EventLog.generated_at <= base,
        )
        .order_by(EventLog.generated_at.desc())
        .limit(200)
        .all()
    )
    updates = (
        WindowsUpdate.query.filter(
            WindowsUpdate.pc_id == inquiry.pc_id,
            WindowsUpdate.installed.is_(True),
            WindowsUpdate.installed_at.isnot(None),
            WindowsUpdate.installed_at >= cutoff,
            WindowsUpdate.installed_at <= base,
        )
        .order_by(WindowsUpdate.installed_at.desc())
        .all()
    )
    latest_score = (
        StabilityScore.query.filter_by(pc_id=inquiry.pc_id)
        .order_by(StabilityScore.calculated_at.desc())
        .first()
    )

    return jsonify(
        {
            "inquiry_id": inquiry_id,
            "pc_id": inquiry.pc_id,
            "pc_name": inquiry.pc.pc_name if inquiry.pc else None,
            "window_days": days,
            "window_from": cutoff.isoformat(),
            "window_to": base.isoformat(),
            "event_logs": [e.to_dict() for e in events],
            "windows_updates": [u.to_dict() for u in updates],
            "stability_score": latest_score.to_dict() if latest_score else None,
        }
    )


# ── Similar inquiries ───────────────────────────────────────────────────────


@bp.route("/similar", methods=["GET"])
@login_required
def similar_inquiries():
    """GET /api/inquiries/similar?subject=...&known_issue_id=...

    Lightweight similarity: case-insensitive LIKE on subject and/or filter by
    known_issue_id. Returns at most 50 matches sorted by created_at desc.
    """
    subject = (request.args.get("subject") or "").strip()
    known_issue_id = request.args.get("known_issue_id", type=int)

    q = Inquiry.query
    if subject:
        q = q.filter(Inquiry.subject.ilike(f"%{subject}%"))
    if known_issue_id:
        q = q.filter(Inquiry.known_issue_id == known_issue_id)
    if not subject and not known_issue_id:
        return jsonify({"error": "subject or known_issue_id is required"}), 400

    items = q.order_by(Inquiry.created_at.desc()).limit(50).all()
    return jsonify([i.to_dict() for i in items])

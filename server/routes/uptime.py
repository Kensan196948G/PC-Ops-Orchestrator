"""PC uptime / availability tracking endpoints (Issue #274).

Endpoints:
  GET /api/pcs/<id>/uptime   — uptime % + downtime minutes for one PC
  GET /api/uptime/summary    — all-PC uptime ranking (lowest first)
  POST /api/uptime/mark-offline  — scheduler hook to mark offline PCs (admin)
"""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from auth import admin_required, login_required
from extensions import db
from models import PC, UptimeLog

bp = Blueprint("uptime", __name__)

_DEFAULT_DAYS = 30
_OFFLINE_THRESHOLD_MINUTES = 30


def _calc_uptime(pc_id: int, days: int) -> dict:
    """Return uptime statistics for a single PC over the last *days* days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    logs = (
        UptimeLog.query.filter(
            UptimeLog.pc_id == pc_id,
            UptimeLog.recorded_at >= cutoff,
        )
        .order_by(UptimeLog.recorded_at.asc())
        .all()
    )
    total = len(logs)
    if total == 0:
        return {"uptime_pct": None, "downtime_minutes": None, "sample_count": 0}

    online_count = sum(1 for log in logs if log.status == "online")
    uptime_pct = round(online_count / total * 100, 2)

    # Approximate downtime as consecutive offline windows
    downtime_minutes = 0
    for i in range(1, len(logs)):
        if logs[i - 1].status != "online" and logs[i].status != "online":
            delta = (logs[i].recorded_at - logs[i - 1].recorded_at).total_seconds() / 60
            downtime_minutes += delta

    return {
        "uptime_pct": uptime_pct,
        "downtime_minutes": round(downtime_minutes, 1),
        "sample_count": total,
    }


@bp.route("/api/pcs/<int:pc_id>/uptime", methods=["GET"])
@login_required
def pc_uptime(pc_id: int):
    """GET /api/pcs/<id>/uptime — uptime stats for one PC."""
    days = int(request.args.get("days", _DEFAULT_DAYS))
    pc = PC.query.get_or_404(pc_id)
    stats = _calc_uptime(pc_id, days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    history = (
        UptimeLog.query.filter(
            UptimeLog.pc_id == pc_id,
            UptimeLog.recorded_at >= cutoff,
        )
        .order_by(UptimeLog.recorded_at.desc())
        .limit(100)
        .all()
    )
    return jsonify(
        {
            "pc_id": pc_id,
            "pc_name": pc.pc_name,
            "days": days,
            **stats,
            "history": [log.to_dict() for log in history],
        }
    )


@bp.route("/api/uptime/summary", methods=["GET"])
@login_required
def uptime_summary():
    """GET /api/uptime/summary — all-PC uptime ranking (lowest first, top 50)."""
    days = int(request.args.get("days", _DEFAULT_DAYS))
    limit = int(request.args.get("limit", 50))
    pcs = PC.query.all()
    results = []
    for pc in pcs:
        stats = _calc_uptime(pc.id, days)
        results.append(
            {
                "pc_id": pc.id,
                "pc_name": pc.pc_name,
                **stats,
            }
        )
    # Sort: PCs with data first (lowest uptime_pct first), then unknown
    results.sort(
        key=lambda x: (
            x["uptime_pct"] is None,
            x["uptime_pct"] if x["uptime_pct"] is not None else 100,
        )
    )
    return jsonify({"days": days, "pcs": results[:limit]})


@bp.route("/api/uptime/mark-offline", methods=["POST"])
@admin_required
def mark_offline():
    """POST /api/uptime/mark-offline — mark PCs silent for >=threshold minutes as offline.

    Called by the scheduler to detect PCs that have stopped reporting.
    """
    threshold_minutes = int(
        request.get_json(silent=True, force=True).get(
            "threshold_minutes", _OFFLINE_THRESHOLD_MINUTES
        )
        if request.get_json(silent=True, force=True)
        else _OFFLINE_THRESHOLD_MINUTES
    )
    # SQLite stores datetimes without tz info; use naive UTC for Python comparison
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now_naive - timedelta(minutes=threshold_minutes)
    pcs = PC.query.all()
    marked = 0
    for pc in pcs:
        last_log = (
            UptimeLog.query.filter_by(pc_id=pc.id)
            .order_by(UptimeLog.recorded_at.desc())
            .first()
        )
        if last_log is None or last_log.recorded_at < cutoff:
            db.session.add(
                UptimeLog(pc_id=pc.id, status="offline", recorded_at=now_naive)
            )
            marked += 1
    db.session.commit()
    return jsonify({"marked_offline": marked, "threshold_minutes": threshold_minutes})

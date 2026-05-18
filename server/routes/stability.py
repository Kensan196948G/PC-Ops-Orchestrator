"""PC Stability Insight routes — Phase D-1/D-2 (Issue #238, #239)."""

import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from auth import login_required

from extensions import db
from models import (
    PC,
    EventLog,
    KnownIssue,
    StabilityScore,
    WindowsUpdate,
    STABILITY_EVENT_RULES,
)

bp = Blueprint("stability", __name__, url_prefix="/api/stability")

# Event IDs that indicate disk problems
DISK_EVENT_IDS = {7, 51, 55, 129, 153}

# Severity mapping per disk event id (used by /disk-health?flat=1)
DISK_EVENT_SEVERITY = {
    7: "critical",  # Bad block
    55: "critical",  # NTFS corruption
    51: "warning",  # Generic disk warning
    129: "warning",  # Disk timeout
    153: "info",  # Disk retry succeeded
}

# Score thresholds
THRESHOLD_CRITICAL = 40
THRESHOLD_UNSTABLE = 60
THRESHOLD_WARNING = 80


def _calculate_score(pc_id: int, days: int = 7) -> tuple[float, list]:
    """Compute stability score for a single PC over the given analysis window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    score = 100.0
    deductions = []

    for event_id, category, max_deduction, label in STABILITY_EVENT_RULES:
        count = EventLog.query.filter(
            EventLog.pc_id == pc_id,
            EventLog.event_id == event_id,
            EventLog.generated_at >= cutoff,
        ).count()
        if count > 0:
            points = min(max_deduction, count * max_deduction)
            score -= points
            deductions.append(
                {
                    "reason": label,
                    "event_id": event_id,
                    "category": category,
                    "count": count,
                    "points": points,
                }
            )

    score = max(0.0, score)
    return score, deductions


def _persist_score(pc: PC, score: float, deductions: list, days: int) -> StabilityScore:
    """Save a new StabilityScore record and update PC.stability_score."""
    entry = StabilityScore(
        pc_id=pc.id,
        score=score,
        deductions=json.dumps(deductions, ensure_ascii=False),
        analysis_days=days,
    )
    db.session.add(entry)
    pc.stability_score = score
    pc.last_stability_calc_at = datetime.now(timezone.utc)
    db.session.commit()
    return entry


@bp.route("/scores", methods=["GET"])
@login_required
def list_scores():
    """GET /api/stability/scores — latest stability score for every PC."""
    pcs = PC.query.order_by(PC.stability_score.asc()).all()
    result = []
    for pc in pcs:
        result.append(
            {
                "pc_id": pc.id,
                "pc_name": pc.pc_name,
                "stability_score": pc.stability_score
                if pc.stability_score is not None
                else 100.0,
                "last_stability_calc_at": pc.last_stability_calc_at.isoformat()
                if pc.last_stability_calc_at
                else None,
                "status": _score_to_status(pc.stability_score),
            }
        )
    return jsonify(result)


@bp.route("/scores/<int:pc_id>", methods=["GET"])
@login_required
def get_score(pc_id):
    """GET /api/stability/scores/<pc_id> — score + deduction breakdown for one PC."""
    pc = PC.query.get_or_404(pc_id)
    days = int(request.args.get("days", 7))

    latest = (
        StabilityScore.query.filter_by(pc_id=pc_id)
        .order_by(StabilityScore.calculated_at.desc())
        .first()
    )
    history = (
        StabilityScore.query.filter_by(pc_id=pc_id)
        .order_by(StabilityScore.calculated_at.desc())
        .limit(30)
        .all()
    )

    return jsonify(
        {
            "pc_id": pc.id,
            "pc_name": pc.pc_name,
            "current_score": pc.stability_score
            if pc.stability_score is not None
            else 100.0,
            "last_stability_calc_at": pc.last_stability_calc_at.isoformat()
            if pc.last_stability_calc_at
            else None,
            "status": _score_to_status(pc.stability_score),
            "latest": latest.to_dict() if latest else None,
            "history": [s.to_dict() for s in history],
            "analysis_days": days,
        }
    )


@bp.route("/calculate", methods=["POST"])
@login_required
def calculate_all():
    """POST /api/stability/calculate — recalculate scores for all PCs."""
    days = int(request.json.get("days", 7)) if request.json else 7
    pcs = PC.query.all()
    results = []
    for pc in pcs:
        score, deductions = _calculate_score(pc.id, days)
        _persist_score(pc, score, deductions, days)
        results.append(
            {
                "pc_id": pc.id,
                "pc_name": pc.pc_name,
                "score": score,
                "status": _score_to_status(score),
                "deductions_count": len(deductions),
            }
        )
    return jsonify({"calculated": len(results), "results": results})


@bp.route("/calculate/<int:pc_id>", methods=["POST"])
@login_required
def calculate_one(pc_id):
    """POST /api/stability/calculate/<pc_id> — recalculate score for one PC."""
    pc = PC.query.get_or_404(pc_id)
    days = int(request.json.get("days", 7)) if request.json else 7
    score, deductions = _calculate_score(pc.id, days)
    entry = _persist_score(pc, score, deductions, days)
    return jsonify(entry.to_dict()), 201


@bp.route("/unstable-pcs", methods=["GET"])
@login_required
def unstable_pcs():
    """GET /api/stability/unstable-pcs — PCs with stability_score < threshold."""
    threshold = float(request.args.get("threshold", THRESHOLD_UNSTABLE))
    pcs = (
        PC.query.filter(PC.stability_score < threshold)
        .order_by(PC.stability_score.asc())
        .all()
    )
    return jsonify(
        [
            {
                "pc_id": pc.id,
                "pc_name": pc.pc_name,
                "stability_score": pc.stability_score,
                "status": _score_to_status(pc.stability_score),
                "last_seen": pc.last_seen.isoformat() if pc.last_seen else None,
                "last_stability_calc_at": pc.last_stability_calc_at.isoformat()
                if pc.last_stability_calc_at
                else None,
            }
            for pc in pcs
        ]
    )


@bp.route("/event-ranking", methods=["GET"])
@login_required
def event_ranking():
    """GET /api/stability/event-ranking — top Event IDs by occurrence count."""
    days = int(request.args.get("days", 7))
    limit = int(request.args.get("limit", 20))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        db.session.query(
            EventLog.event_id,
            EventLog.source,
            func.count(EventLog.id).label("count"),
        )
        .filter(EventLog.generated_at >= cutoff, EventLog.event_id.isnot(None))
        .group_by(EventLog.event_id, EventLog.source)
        .order_by(func.count(EventLog.id).desc())
        .limit(limit)
        .all()
    )

    rule_map = {r[0]: r[3] for r in STABILITY_EVENT_RULES}
    return jsonify(
        [
            {
                "event_id": row.event_id,
                "source": row.source,
                "count": row.count,
                "label": rule_map.get(row.event_id, ""),
                "days": days,
            }
            for row in rows
        ]
    )


@bp.route("/kb-impact", methods=["GET"])
@login_required
def kb_impact_list():
    """GET /api/stability/kb-impact — ranking of KBs by post-install error increase."""
    days = int(request.args.get("days", 30))
    limit = int(request.args.get("limit", 20))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    window_hours = 72

    kb_rows = (
        db.session.query(
            WindowsUpdate.kb_id,
            WindowsUpdate.title,
            func.count(WindowsUpdate.id).label("affected_pcs"),
            func.min(WindowsUpdate.installed_at).label("first_installed"),
        )
        .filter(
            WindowsUpdate.installed.is_(True),
            WindowsUpdate.installed_at >= cutoff,
            WindowsUpdate.kb_id.isnot(None),
        )
        .group_by(WindowsUpdate.kb_id, WindowsUpdate.title)
        .order_by(func.count(WindowsUpdate.id).desc())
        .limit(limit)
        .all()
    )

    results = []
    for row in kb_rows:
        error_increase = _count_post_kb_errors(row.kb_id, window_hours)
        results.append(
            {
                "kb_id": row.kb_id,
                "title": row.title,
                "affected_pcs": row.affected_pcs,
                "first_installed": row.first_installed.isoformat()
                if row.first_installed
                else None,
                "post_install_errors": error_increase,
                "risk_level": _kb_risk_level(error_increase, row.affected_pcs),
            }
        )
    results.sort(key=lambda x: x["post_install_errors"], reverse=True)
    return jsonify(results)


@bp.route("/kb-impact/<kb_id>", methods=["GET"])
@login_required
def kb_impact_detail(kb_id):
    """GET /api/stability/kb-impact/<kb_id> — per-PC impact analysis for one KB."""
    window_hours = int(request.args.get("window_hours", 72))

    updates = WindowsUpdate.query.filter(
        WindowsUpdate.kb_id == kb_id,
        WindowsUpdate.installed.is_(True),
    ).all()

    if not updates:
        return jsonify({"error": "KB not found", "kb_id": kb_id}), 404

    pc_impacts = []
    for upd in updates:
        if not upd.installed_at:
            continue
        pc = PC.query.get(upd.pc_id)
        if not pc:
            continue
        before_cutoff = upd.installed_at - timedelta(hours=window_hours)
        after_cutoff = upd.installed_at + timedelta(hours=window_hours)

        errors_before = EventLog.query.filter(
            EventLog.pc_id == upd.pc_id,
            EventLog.generated_at >= before_cutoff,
            EventLog.generated_at < upd.installed_at,
        ).count()
        errors_after = EventLog.query.filter(
            EventLog.pc_id == upd.pc_id,
            EventLog.generated_at > upd.installed_at,
            EventLog.generated_at <= after_cutoff,
        ).count()

        pc_impacts.append(
            {
                "pc_id": pc.id,
                "pc_name": pc.pc_name,
                "installed_at": upd.installed_at.isoformat(),
                "reboot_at": upd.reboot_at.isoformat() if upd.reboot_at else None,
                "errors_before": errors_before,
                "errors_after": errors_after,
                "error_increase": errors_after - errors_before,
                "cpu_name": pc.cpu_name,
                "os_version": pc.os_version,
            }
        )

    return jsonify(
        {
            "kb_id": kb_id,
            "title": updates[0].title if updates else "",
            "severity": updates[0].severity if updates else "",
            "affected_pcs": len(pc_impacts),
            "window_hours": window_hours,
            "pc_impacts": sorted(
                pc_impacts, key=lambda x: x["error_increase"], reverse=True
            ),
        }
    )


@bp.route("/similar-issues", methods=["GET"])
@login_required
def similar_issues():
    """GET /api/stability/similar-issues — group PCs with similar instability patterns."""
    days = int(request.args.get("days", 7))
    group_by = request.args.get("group_by", "kb")  # kb | model | domain
    min_pcs = int(request.args.get("min_pcs", 2))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    if group_by == "kb":
        return jsonify(_similar_by_kb(cutoff, min_pcs))
    elif group_by == "model":
        return jsonify(_similar_by_model(cutoff, min_pcs))
    elif group_by == "domain":
        return jsonify(_similar_by_domain(cutoff, min_pcs))
    else:
        return jsonify({"error": "group_by must be kb, model, or domain"}), 400


@bp.route("/disk-health", methods=["GET"])
@login_required
def disk_health_list():
    """GET /api/stability/disk-health — PCs with disk-related events.

    Default: PC-aggregated view (used by the dashboard summary table).
    ?flat=1: returns per-event rows used by the WebUI disk-health page.
    """
    days = int(request.args.get("days", 30))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    if request.args.get("flat") in ("1", "true", "True"):
        events = (
            EventLog.query.filter(
                EventLog.event_id.in_(list(DISK_EVENT_IDS)),
                EventLog.generated_at >= cutoff,
            )
            .order_by(EventLog.generated_at.desc())
            .limit(1000)
            .all()
        )
        pc_map = {
            pc.id: pc.pc_name
            for pc in PC.query.filter(PC.id.in_({e.pc_id for e in events})).all()
        }
        items = []
        for e in events:
            items.append(
                {
                    "pc_id": e.pc_id,
                    "pc_name": pc_map.get(e.pc_id, f"PC#{e.pc_id}"),
                    "event_id": e.event_id,
                    "source": e.source,
                    "disk": None,
                    "severity": DISK_EVENT_SEVERITY.get(e.event_id, "info"),
                    "message": e.message,
                    "occurred_at": e.generated_at.isoformat()
                    if e.generated_at
                    else None,
                    "collected_at": e.collected_at.isoformat()
                    if e.collected_at
                    else None,
                }
            )
        return jsonify({"items": items, "days": days, "total": len(items)})

    rows = (
        db.session.query(
            EventLog.pc_id,
            EventLog.event_id,
            func.count(EventLog.id).label("count"),
            func.max(EventLog.generated_at).label("latest"),
        )
        .filter(
            EventLog.event_id.in_(list(DISK_EVENT_IDS)),
            EventLog.generated_at >= cutoff,
        )
        .group_by(EventLog.pc_id, EventLog.event_id)
        .all()
    )

    pc_ids = list({r.pc_id for r in rows})
    pcs = {pc.id: pc for pc in PC.query.filter(PC.id.in_(pc_ids)).all()}

    aggregated = {}
    for row in rows:
        pid = row.pc_id
        if pid not in aggregated:
            aggregated[pid] = {
                "pc_id": pid,
                "pc_name": pcs[pid].pc_name if pid in pcs else str(pid),
                "total_disk_events": 0,
                "events": [],
                "latest_event_at": None,
                "risk_level": "low",
            }
        aggregated[pid]["total_disk_events"] += row.count
        aggregated[pid]["events"].append(
            {
                "event_id": row.event_id,
                "count": row.count,
                "latest": row.latest.isoformat() if row.latest else None,
            }
        )
        if row.latest and (
            aggregated[pid]["latest_event_at"] is None
            or row.latest > datetime.fromisoformat(aggregated[pid]["latest_event_at"])
        ):
            aggregated[pid]["latest_event_at"] = row.latest.isoformat()

    result = list(aggregated.values())
    for item in result:
        item["risk_level"] = _disk_risk_level(item["total_disk_events"], item["events"])
    result.sort(key=lambda x: x["total_disk_events"], reverse=True)
    return jsonify(result)


@bp.route("/disk-health/<int:pc_id>", methods=["GET"])
@login_required
def disk_health_detail(pc_id):
    """GET /api/stability/disk-health/<pc_id> — disk events for one PC."""
    pc = PC.query.get_or_404(pc_id)
    days = int(request.args.get("days", 30))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    events = (
        EventLog.query.filter(
            EventLog.pc_id == pc_id,
            EventLog.event_id.in_(list(DISK_EVENT_IDS)),
            EventLog.generated_at >= cutoff,
        )
        .order_by(EventLog.generated_at.desc())
        .all()
    )
    return jsonify(
        {
            "pc_id": pc.id,
            "pc_name": pc.pc_name,
            "days": days,
            "total": len(events),
            "events": [e.to_dict() for e in events],
        }
    )


@bp.route("/known-issues", methods=["GET"])
@login_required
def list_known_issues():
    """GET /api/stability/known-issues — list all known issues."""
    issues = (
        KnownIssue.query.filter_by(is_active=True)
        .order_by(KnownIssue.created_at.desc())
        .all()
    )
    return jsonify([i.to_dict() for i in issues])


@bp.route("/known-issues", methods=["POST"])
@login_required
def create_known_issue():
    """POST /api/stability/known-issues — create a new known issue."""
    data = request.json or {}
    if not data.get("title"):
        return jsonify({"error": "title is required"}), 400
    issue = KnownIssue(
        title=data["title"],
        kb_id=data.get("kb_id"),
        event_ids=json.dumps(data.get("event_ids", []), ensure_ascii=False),
        symptoms=data.get("symptoms"),
        resolution=data.get("resolution"),
        affected_os=data.get("affected_os"),
        affected_models=json.dumps(data.get("affected_models", []), ensure_ascii=False),
        severity=data.get("severity", "medium"),
    )
    db.session.add(issue)
    db.session.commit()
    return jsonify(issue.to_dict()), 201


@bp.route("/known-issues/<int:issue_id>", methods=["PUT"])
@login_required
def update_known_issue(issue_id):
    """PUT /api/stability/known-issues/<issue_id>."""
    issue = KnownIssue.query.get_or_404(issue_id)
    data = request.json or {}
    for field in (
        "title",
        "kb_id",
        "symptoms",
        "resolution",
        "affected_os",
        "severity",
    ):
        if field in data:
            setattr(issue, field, data[field])
    if "event_ids" in data:
        issue.event_ids = json.dumps(data["event_ids"], ensure_ascii=False)
    if "affected_models" in data:
        issue.affected_models = json.dumps(data["affected_models"], ensure_ascii=False)
    if "is_active" in data:
        issue.is_active = data["is_active"]
    db.session.commit()
    return jsonify(issue.to_dict())


@bp.route("/known-issues/match/<int:pc_id>", methods=["GET"])
@login_required
def match_known_issues(pc_id):
    """GET /api/stability/known-issues/match/<pc_id> — issues matching this PC."""
    pc = PC.query.get_or_404(pc_id)
    days = int(request.args.get("days", 7))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    recent_event_ids = {
        row[0]
        for row in db.session.query(EventLog.event_id)
        .filter(EventLog.pc_id == pc_id, EventLog.generated_at >= cutoff)
        .distinct()
        .all()
        if row[0] is not None
    }
    recent_kbs = {
        row[0]
        for row in db.session.query(WindowsUpdate.kb_id)
        .filter(WindowsUpdate.pc_id == pc_id, WindowsUpdate.installed.is_(True))
        .all()
        if row[0] is not None
    }

    all_issues = KnownIssue.query.filter_by(is_active=True).all()
    matched = []
    for issue in all_issues:
        issue_event_ids = set(json.loads(issue.event_ids) if issue.event_ids else [])
        match_reasons = []
        if issue.kb_id and issue.kb_id in recent_kbs:
            match_reasons.append(f"KB {issue.kb_id} applied")
        if issue_event_ids & recent_event_ids:
            match_reasons.append(f"Event IDs: {issue_event_ids & recent_event_ids}")
        if match_reasons:
            d = issue.to_dict()
            d["match_reasons"] = match_reasons
            matched.append(d)

    return jsonify({"pc_id": pc.id, "pc_name": pc.pc_name, "matched_issues": matched})


# ── helpers ──────────────────────────────────────────────────────────────────


def _score_to_status(score) -> str:
    if score is None:
        return "unknown"
    score = float(score)
    if score >= THRESHOLD_WARNING:
        return "healthy"
    if score >= THRESHOLD_UNSTABLE:
        return "warning"
    if score >= THRESHOLD_CRITICAL:
        return "unstable"
    return "critical"


def _kb_risk_level(error_increase: int, affected_pcs: int) -> str:
    if error_increase >= 10 or affected_pcs >= 5:
        return "high"
    if error_increase >= 3 or affected_pcs >= 2:
        return "medium"
    return "low"


def _disk_risk_level(total: int, events: list) -> str:
    critical_ids = {7, 55}
    has_critical = any(e["event_id"] in critical_ids for e in events)
    if has_critical or total >= 10:
        return "critical"
    if total >= 5:
        return "high"
    if total >= 2:
        return "medium"
    return "low"


def _count_post_kb_errors(kb_id: str, window_hours: int) -> int:
    updates = WindowsUpdate.query.filter(
        WindowsUpdate.kb_id == kb_id,
        WindowsUpdate.installed.is_(True),
        WindowsUpdate.installed_at.isnot(None),
    ).all()
    total = 0
    for upd in updates:
        after_cutoff = upd.installed_at + timedelta(hours=window_hours)
        total += EventLog.query.filter(
            EventLog.pc_id == upd.pc_id,
            EventLog.generated_at > upd.installed_at,
            EventLog.generated_at <= after_cutoff,
        ).count()
    return total


def _similar_by_kb(cutoff, min_pcs: int) -> list:
    unstable_pc_ids = [
        pc.id for pc in PC.query.filter(PC.stability_score < THRESHOLD_UNSTABLE).all()
    ]
    if not unstable_pc_ids:
        return []
    rows = (
        db.session.query(
            WindowsUpdate.kb_id,
            WindowsUpdate.title,
            func.count(WindowsUpdate.pc_id.distinct()).label("pc_count"),
        )
        .filter(
            WindowsUpdate.pc_id.in_(unstable_pc_ids),
            WindowsUpdate.installed.is_(True),
            WindowsUpdate.installed_at >= cutoff,
        )
        .group_by(WindowsUpdate.kb_id, WindowsUpdate.title)
        .having(func.count(WindowsUpdate.pc_id.distinct()) >= min_pcs)
        .order_by(func.count(WindowsUpdate.pc_id.distinct()).desc())
        .all()
    )
    return [
        {
            "group_by": "kb",
            "kb_id": r.kb_id,
            "title": r.title,
            "unstable_pc_count": r.pc_count,
        }
        for r in rows
    ]


def _similar_by_model(cutoff, min_pcs: int) -> list:
    rows = (
        db.session.query(
            PC.cpu_name,
            func.count(PC.id.distinct()).label("pc_count"),
        )
        .filter(PC.stability_score < THRESHOLD_UNSTABLE, PC.cpu_name.isnot(None))
        .group_by(PC.cpu_name)
        .having(func.count(PC.id.distinct()) >= min_pcs)
        .order_by(func.count(PC.id.distinct()).desc())
        .all()
    )
    return [
        {"group_by": "model", "cpu_name": r.cpu_name, "unstable_pc_count": r.pc_count}
        for r in rows
    ]


def _similar_by_domain(cutoff, min_pcs: int) -> list:
    rows = (
        db.session.query(
            PC.domain,
            func.count(PC.id.distinct()).label("pc_count"),
        )
        .filter(PC.stability_score < THRESHOLD_UNSTABLE, PC.domain.isnot(None))
        .group_by(PC.domain)
        .having(func.count(PC.id.distinct()) >= min_pcs)
        .order_by(func.count(PC.id.distinct()).desc())
        .all()
    )
    return [
        {"group_by": "domain", "domain": r.domain, "unstable_pc_count": r.pc_count}
        for r in rows
    ]

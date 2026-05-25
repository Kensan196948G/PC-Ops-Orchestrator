"""PC Stability Insight routes — Phase D-1/D-2 (Issue #238, #239), Phase E (Issue #244-#247, #252, #253)."""

import json
import os
from datetime import datetime, timedelta, timezone

import requests as http_requests
from flask import Blueprint, jsonify, request
from sqlalchemy import func

from auth import login_required

from extensions import db
from models import (
    PC,
    AppResponseLog,
    BootTimeLog,
    EventLog,
    KnownIssue,
    NotificationChannel,
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
    """GET /api/stability/similar-issues — group PCs with similar instability patterns.

    group_by: kb | model | domain | os_version | location
    """
    days = int(request.args.get("days", 7))
    group_by = request.args.get("group_by", "kb")
    min_pcs = int(request.args.get("min_pcs", 2))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    if group_by == "kb":
        return jsonify(_similar_by_kb(cutoff, min_pcs))
    elif group_by == "model":
        return jsonify(_similar_by_model(cutoff, min_pcs))
    elif group_by == "domain":
        return jsonify(_similar_by_domain(cutoff, min_pcs))
    elif group_by == "os_version":
        return jsonify(_similar_by_os_version(min_pcs))
    elif group_by == "location":
        return jsonify(_similar_by_location(min_pcs))
    else:
        return jsonify(
            {"error": "group_by must be kb, model, domain, os_version, or location"}
        ), 400


@bp.route("/boot-analysis", methods=["GET"])
@login_required
def boot_analysis_list():
    """GET /api/stability/boot-analysis — list PCs with slow boot times (Issue #245)."""
    days = int(request.args.get("days", 14))
    threshold_pct = float(request.args.get("threshold_pct", 150))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    pc_counts = (
        db.session.query(
            BootTimeLog.pc_id,
            func.count(BootTimeLog.id).label("cnt"),
        )
        .filter(BootTimeLog.collected_at >= cutoff)
        .group_by(BootTimeLog.pc_id)
        .having(func.count(BootTimeLog.id) >= 2)
        .all()
    )

    results = []
    for row in pc_counts:
        pc = db.session.get(PC, row.pc_id)
        if not pc:
            continue
        logs = (
            BootTimeLog.query.filter(
                BootTimeLog.pc_id == row.pc_id,
                BootTimeLog.collected_at >= cutoff,
            )
            .order_by(BootTimeLog.boot_timestamp.asc())
            .all()
        )
        if len(logs) < 2:
            continue
        durations = [log.boot_duration_seconds for log in logs]
        baseline_count = max(1, len(durations) // 2)
        baseline = sum(durations[:baseline_count]) / baseline_count
        latest = durations[-1]
        increase_pct = round((latest / baseline - 1) * 100, 1) if baseline > 0 else 0
        if baseline > 0 and latest > baseline * (threshold_pct / 100):
            results.append(
                {
                    "pc_id": pc.id,
                    "pc_name": pc.pc_name,
                    "baseline_seconds": round(baseline, 1),
                    "latest_seconds": latest,
                    "increase_pct": increase_pct,
                    "sample_count": len(durations),
                    "alert": True,
                }
            )

    return jsonify(results)


@bp.route("/boot-analysis/<int:pc_id>", methods=["GET"])
@login_required
def boot_analysis_detail(pc_id):
    """GET /api/stability/boot-analysis/<pc_id> — boot time history for one PC."""
    pc = db.session.get(PC, pc_id)
    if pc is None:
        return jsonify({"error": "PC not found"}), 404
    days = int(request.args.get("days", 30))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    logs = (
        BootTimeLog.query.filter(
            BootTimeLog.pc_id == pc_id,
            BootTimeLog.collected_at >= cutoff,
        )
        .order_by(BootTimeLog.boot_timestamp.asc())
        .all()
    )
    durations = [log.boot_duration_seconds for log in logs]
    avg = sum(durations) / len(durations) if durations else None

    return jsonify(
        {
            "pc_id": pc.id,
            "pc_name": pc.pc_name,
            "days": days,
            "sample_count": len(logs),
            "avg_seconds": round(avg, 1) if avg is not None else None,
            "min_seconds": min(durations) if durations else None,
            "max_seconds": max(durations) if durations else None,
            "records": [log.to_dict() for log in logs],
        }
    )


@bp.route("/boot-analysis/<int:pc_id>", methods=["POST"])
@login_required
def record_boot_time(pc_id):
    """POST /api/stability/boot-analysis/<pc_id> — record a new boot duration entry."""
    pc = db.session.get(PC, pc_id)
    if pc is None:
        return jsonify({"error": "PC not found"}), 404
    data = request.get_json(force=True) or {}

    duration = data.get("boot_duration_seconds")
    if not isinstance(duration, (int, float)) or duration <= 0:
        return jsonify(
            {"error": "boot_duration_seconds required (positive number)"}
        ), 400

    ts_raw = data.get("boot_timestamp")
    if ts_raw:
        try:
            boot_ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            return jsonify({"error": "invalid boot_timestamp format"}), 400
    else:
        boot_ts = datetime.now(timezone.utc)

    log = BootTimeLog(
        pc_id=pc.id,
        boot_duration_seconds=int(duration),
        boot_timestamp=boot_ts,
    )
    db.session.add(log)
    db.session.commit()
    return jsonify(log.to_dict()), 201


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


def _similar_by_os_version(min_pcs: int) -> list:
    """Group unstable PCs by OS version string (Issue #244)."""
    rows = (
        db.session.query(
            PC.os_version,
            func.count(PC.id.distinct()).label("pc_count"),
        )
        .filter(PC.stability_score < THRESHOLD_UNSTABLE, PC.os_version.isnot(None))
        .group_by(PC.os_version)
        .having(func.count(PC.id.distinct()) >= min_pcs)
        .order_by(func.count(PC.id.distinct()).desc())
        .all()
    )
    return [
        {
            "group_by": "os_version",
            "os_version": r.os_version,
            "unstable_pc_count": r.pc_count,
        }
        for r in rows
    ]


def _similar_by_location(min_pcs: int) -> list:
    """Group unstable PCs by IP subnet (/24 prefix) as a location proxy (Issue #244)."""
    pcs = PC.query.filter(
        PC.stability_score < THRESHOLD_UNSTABLE, PC.ip_address.isnot(None)
    ).all()
    subnet_counts: dict[str, int] = {}
    for pc in pcs:
        parts = pc.ip_address.split(".")
        if len(parts) == 4:
            subnet = ".".join(parts[:3]) + ".0/24"
            subnet_counts[subnet] = subnet_counts.get(subnet, 0) + 1
    return sorted(
        [
            {
                "group_by": "location",
                "subnet": subnet,
                "unstable_pc_count": count,
            }
            for subnet, count in subnet_counts.items()
            if count >= min_pcs
        ],
        key=lambda x: x["unstable_pc_count"],
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Issue #247 — App Response Monitoring
# ---------------------------------------------------------------------------


@bp.route("/app-response", methods=["GET"])
@login_required
def app_response_summary():
    """Slow-app summary across all PCs in the last N hours."""
    hours = min(int(request.args.get("hours", 24)), 168)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows = (
        db.session.query(
            AppResponseLog.app_name,
            func.count(AppResponseLog.id).label("total"),
            func.sum(db.cast(AppResponseLog.is_slow, db.Integer)).label("slow_count"),
            func.avg(AppResponseLog.response_time_ms).label("avg_ms"),
            func.max(AppResponseLog.response_time_ms).label("max_ms"),
        )
        .filter(AppResponseLog.recorded_at >= cutoff)
        .group_by(AppResponseLog.app_name)
        .order_by(func.sum(db.cast(AppResponseLog.is_slow, db.Integer)).desc())
        .all()
    )

    return jsonify(
        {
            "hours": hours,
            "apps": [
                {
                    "app_name": r.app_name,
                    "total_records": r.total,
                    "slow_count": int(r.slow_count or 0),
                    "slow_rate": round((r.slow_count or 0) / r.total, 4)
                    if r.total
                    else 0,
                    "avg_ms": round(r.avg_ms or 0, 1),
                    "max_ms": r.max_ms or 0,
                }
                for r in rows
            ],
        }
    )


@bp.route("/app-response/<int:pc_id>", methods=["GET"])
@login_required
def app_response_by_pc(pc_id):
    """Per-PC app response summary + recent history."""
    pc = db.session.get(PC, pc_id)
    if pc is None:
        return jsonify({"error": "PC not found"}), 404

    hours = min(int(request.args.get("hours", 24)), 168)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    limit = min(int(request.args.get("limit", 100)), 500)

    summary = (
        db.session.query(
            AppResponseLog.app_name,
            func.count(AppResponseLog.id).label("total"),
            func.sum(db.cast(AppResponseLog.is_slow, db.Integer)).label("slow_count"),
            func.avg(AppResponseLog.response_time_ms).label("avg_ms"),
            func.max(AppResponseLog.response_time_ms).label("max_ms"),
        )
        .filter(
            AppResponseLog.pc_id == pc_id,
            AppResponseLog.recorded_at >= cutoff,
        )
        .group_by(AppResponseLog.app_name)
        .order_by(func.avg(AppResponseLog.response_time_ms).desc())
        .all()
    )

    history = (
        AppResponseLog.query.filter(
            AppResponseLog.pc_id == pc_id,
            AppResponseLog.recorded_at >= cutoff,
        )
        .order_by(AppResponseLog.recorded_at.desc())
        .limit(limit)
        .all()
    )

    return jsonify(
        {
            "pc_id": pc_id,
            "pc_name": pc.pc_name,
            "hours": hours,
            "summary": [
                {
                    "app_name": r.app_name,
                    "total_records": r.total,
                    "slow_count": int(r.slow_count or 0),
                    "slow_rate": round((r.slow_count or 0) / r.total, 4)
                    if r.total
                    else 0,
                    "avg_ms": round(r.avg_ms or 0, 1),
                    "max_ms": r.max_ms or 0,
                }
                for r in summary
            ],
            "history": [r.to_dict() for r in history],
        }
    )


@bp.route("/app-response/<int:pc_id>", methods=["POST"])
@login_required
def app_response_record(pc_id):
    """Accept single or batch app-response records from agents."""
    pc = db.session.get(PC, pc_id)
    if pc is None:
        return jsonify({"error": "PC not found"}), 404

    body = request.get_json(silent=True) or {}
    items = body if isinstance(body, list) else [body]
    if not items:
        return jsonify({"error": "empty payload"}), 400

    created = []
    errors = []
    for idx, item in enumerate(items):
        app_name = item.get("app_name", "").strip()
        response_time_ms = item.get("response_time_ms")
        if not app_name or response_time_ms is None:
            errors.append(
                {"index": idx, "error": "app_name and response_time_ms required"}
            )
            continue
        try:
            response_time_ms = int(response_time_ms)
        except (TypeError, ValueError):
            errors.append({"index": idx, "error": "response_time_ms must be integer"})
            continue

        threshold_ms = item.get("threshold_ms")
        if threshold_ms is not None:
            try:
                threshold_ms = int(threshold_ms)
            except (TypeError, ValueError):
                threshold_ms = None

        is_slow = bool(
            item.get(
                "is_slow", threshold_ms is not None and response_time_ms > threshold_ms
            )
        )

        recorded_at_raw = item.get("recorded_at")
        if recorded_at_raw:
            try:
                recorded_at = datetime.fromisoformat(
                    recorded_at_raw.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                recorded_at = datetime.now(timezone.utc)
        else:
            recorded_at = datetime.now(timezone.utc)

        log = AppResponseLog(
            pc_id=pc_id,
            app_name=app_name,
            response_time_ms=response_time_ms,
            threshold_ms=threshold_ms,
            is_slow=is_slow,
            recorded_at=recorded_at,
        )
        db.session.add(log)
        created.append(idx)

    db.session.commit()
    return jsonify({"created": len(created), "errors": errors}), 201


# ---------------------------------------------------------------------------
# Issue #253 — Early Warning Trends + Slack/Teams Notifications
# ---------------------------------------------------------------------------


@bp.route("/trends", methods=["GET"])
@login_required
def stability_trends():
    """Detect PCs with a declining score trend over recent N snapshots."""
    snapshots = min(int(request.args.get("snapshots", 5)), 20)
    min_drop = float(request.args.get("min_drop", 10.0))

    pcs = PC.query.all()
    at_risk = []

    for pc in pcs:
        recent = (
            StabilityScore.query.filter_by(pc_id=pc.id)
            .order_by(StabilityScore.calculated_at.desc())
            .limit(snapshots)
            .all()
        )
        if len(recent) < 2:
            continue

        scores = [r.score for r in reversed(recent)]  # oldest → newest
        first_score = scores[0]
        last_score = scores[-1]
        drop = first_score - last_score

        if drop >= min_drop:
            at_risk.append(
                {
                    "pc_id": pc.id,
                    "pc_name": pc.pc_name,
                    "first_score": round(first_score, 1),
                    "latest_score": round(last_score, 1),
                    "drop": round(drop, 1),
                    "snapshots_analyzed": len(recent),
                    "latest_calculated_at": recent[0].calculated_at.isoformat()
                    if recent[0].calculated_at
                    else None,
                }
            )

    at_risk.sort(key=lambda x: x["drop"], reverse=True)
    return jsonify(
        {
            "snapshots": snapshots,
            "min_drop": min_drop,
            "at_risk_count": len(at_risk),
            "at_risk": at_risk,
        }
    )


@bp.route("/trends/notify", methods=["POST"])
@login_required
def trends_notify():
    """Send alert to active NotificationChannels for at-risk PCs."""
    body = request.get_json(silent=True) or {}
    snapshots = min(int(body.get("snapshots", 5)), 20)
    min_drop = float(body.get("min_drop", 10.0))
    channel_ids = body.get("channel_ids")  # None = all active channels

    pcs = PC.query.all()
    at_risk = []

    for pc in pcs:
        recent = (
            StabilityScore.query.filter_by(pc_id=pc.id)
            .order_by(StabilityScore.calculated_at.desc())
            .limit(snapshots)
            .all()
        )
        if len(recent) < 2:
            continue
        scores = [r.score for r in reversed(recent)]
        drop = scores[0] - scores[-1]
        if drop >= min_drop:
            at_risk.append(
                {
                    "pc_id": pc.id,
                    "pc_name": pc.pc_name,
                    "drop": round(drop, 1),
                    "latest_score": round(scores[-1], 1),
                }
            )

    if not at_risk:
        return jsonify({"sent": 0, "message": "No at-risk PCs detected"}), 200

    channels_q = NotificationChannel.query.filter_by(is_active=True)
    if channel_ids:
        channels_q = channels_q.filter(NotificationChannel.id.in_(channel_ids))
    channels = channels_q.all()

    message_text = (
        f"[PC-Ops Stability Alert] {len(at_risk)} PC(s) show score decline:\n"
        + "\n".join(
            f"  - {r['pc_name']} (id={r['pc_id']}): score={r['latest_score']}, drop={r['drop']}"
            for r in at_risk
        )
    )

    results = []
    for ch in channels:
        try:
            if ch.channel_type in ("slack", "teams", "webhook"):
                payload = {"text": message_text}
                resp = http_requests.post(ch.target, json=payload, timeout=10)
                results.append(
                    {
                        "channel_id": ch.id,
                        "channel_name": ch.name,
                        "status": "ok" if resp.status_code < 400 else "error",
                        "http_status": resp.status_code,
                    }
                )
            else:
                results.append(
                    {
                        "channel_id": ch.id,
                        "channel_name": ch.name,
                        "status": "skipped",
                        "reason": f"unsupported channel_type: {ch.channel_type}",
                    }
                )
        except Exception as exc:
            results.append(
                {
                    "channel_id": ch.id,
                    "channel_name": ch.name,
                    "status": "error",
                    "reason": str(exc),
                }
            )

    sent_ok = sum(1 for r in results if r.get("status") == "ok")
    return jsonify(
        {
            "at_risk_count": len(at_risk),
            "channels_attempted": len(results),
            "sent": sent_ok,
            "results": results,
        }
    )


# ---------------------------------------------------------------------------
# Issue #252 — Auto Incident Filing for Score < 40
# ---------------------------------------------------------------------------


@bp.route("/incidents", methods=["GET"])
@login_required
def stability_incidents():
    """List PCs whose latest score is below THRESHOLD_CRITICAL (40)."""
    threshold = float(request.args.get("threshold", THRESHOLD_CRITICAL))

    pcs = PC.query.all()
    critical = []

    for pc in pcs:
        latest = (
            StabilityScore.query.filter_by(pc_id=pc.id)
            .order_by(StabilityScore.calculated_at.desc())
            .first()
        )
        if latest is None:
            continue
        if latest.score < threshold:
            critical.append(
                {
                    "pc_id": pc.id,
                    "pc_name": pc.pc_name,
                    "score": round(latest.score, 1),
                    "threshold": threshold,
                    "calculated_at": latest.calculated_at.isoformat()
                    if latest.calculated_at
                    else None,
                }
            )

    critical.sort(key=lambda x: x["score"])
    return jsonify(
        {
            "threshold": threshold,
            "critical_count": len(critical),
            "pcs": critical,
        }
    )


@bp.route("/incidents/auto-file", methods=["POST"])
@login_required
def incidents_auto_file():
    """Create GitHub Issues for each PC with score < threshold (dry_run=true to preview)."""
    body = request.get_json(silent=True) or {}
    threshold = float(body.get("threshold", THRESHOLD_CRITICAL))
    dry_run = bool(body.get("dry_run", False))
    repo = body.get("repo") or os.environ.get("GITHUB_REPO", "")
    token = body.get("token") or os.environ.get("GITHUB_TOKEN", "")

    if not dry_run and not repo:
        return jsonify({"error": "repo is required (e.g. owner/repo)"}), 400
    if not dry_run and not token:
        return jsonify(
            {"error": "GITHUB_TOKEN env var or token body field is required"}
        ), 400

    pcs = PC.query.all()
    candidates = []
    for pc in pcs:
        latest = (
            StabilityScore.query.filter_by(pc_id=pc.id)
            .order_by(StabilityScore.calculated_at.desc())
            .first()
        )
        if latest and latest.score < threshold:
            candidates.append(
                {
                    "pc_id": pc.id,
                    "pc_name": pc.pc_name,
                    "score": round(latest.score, 1),
                    "calculated_at": latest.calculated_at.isoformat()
                    if latest.calculated_at
                    else None,
                }
            )

    if not candidates:
        return jsonify({"filed": 0, "message": "No critical PCs found"}), 200

    if dry_run:
        return jsonify(
            {
                "dry_run": True,
                "would_file": len(candidates),
                "candidates": candidates,
            }
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    api_url = f"https://api.github.com/repos/{repo}/issues"

    results = []
    for pc in candidates:
        title = f"[Stability] Critical score on {pc['pc_name']} (score={pc['score']})"
        body_text = (
            f"## Stability Incident\n\n"
            f"- **PC**: {pc['pc_name']} (id={pc['pc_id']})\n"
            f"- **Score**: {pc['score']} (threshold={threshold})\n"
            f"- **Recorded**: {pc['calculated_at']}\n\n"
            f"Automatically filed by PC-Ops-Orchestrator `/api/stability/incidents/auto-file`.\n"
        )
        try:
            resp = http_requests.post(
                api_url,
                json={
                    "title": title,
                    "body": body_text,
                    "labels": ["stability", "incident"],
                },
                headers=headers,
                timeout=15,
            )
            results.append(
                {
                    "pc_id": pc["pc_id"],
                    "pc_name": pc["pc_name"],
                    "status": "filed" if resp.status_code == 201 else "error",
                    "http_status": resp.status_code,
                    "issue_url": resp.json().get("html_url")
                    if resp.status_code == 201
                    else None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "pc_id": pc["pc_id"],
                    "pc_name": pc["pc_name"],
                    "status": "error",
                    "reason": str(exc),
                }
            )

    filed_ok = sum(1 for r in results if r.get("status") == "filed")
    return jsonify(
        {
            "dry_run": False,
            "filed": filed_ok,
            "total_candidates": len(candidates),
            "results": results,
        }
    )


# Issue #251 — Root Cause Analysis (event_id clustering)
_UNSTABLE_THRESHOLD = 70.0
_STABLE_THRESHOLD = 80.0


@bp.route("/root-cause", methods=["GET"])
@login_required
def root_cause():
    """GET /api/stability/root-cause — rank event IDs by lift vs stable PCs."""
    days = int(request.args.get("days", 14))
    limit = int(request.args.get("limit", 20))
    threshold = float(request.args.get("threshold", _UNSTABLE_THRESHOLD))
    stable_floor = float(request.args.get("stable_threshold", _STABLE_THRESHOLD))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Latest stability score per PC (subquery)
    latest_sq = (
        db.session.query(
            StabilityScore.pc_id,
            func.max(StabilityScore.calculated_at).label("max_at"),
        )
        .group_by(StabilityScore.pc_id)
        .subquery()
    )
    all_scores = (
        db.session.query(StabilityScore)
        .join(
            latest_sq,
            (StabilityScore.pc_id == latest_sq.c.pc_id)
            & (StabilityScore.calculated_at == latest_sq.c.max_at),
        )
        .all()
    )

    unstable_pc_ids = {s.pc_id for s in all_scores if s.score < threshold}
    stable_pc_ids = {s.pc_id for s in all_scores if s.score >= stable_floor}
    total_unstable = len(unstable_pc_ids)
    total_stable = len(stable_pc_ids)

    if total_unstable == 0:
        return jsonify(
            {
                "threshold": threshold,
                "days": days,
                "unstable_pc_count": 0,
                "stable_pc_count": total_stable,
                "events": [],
                "message": "No unstable PCs found",
            }
        )

    unstable_rows = (
        db.session.query(
            EventLog.event_id,
            EventLog.source,
            EventLog.category,
            func.count(func.distinct(EventLog.pc_id)).label("unstable_pc_count"),
            func.count(EventLog.id).label("occurrence_count"),
        )
        .filter(
            EventLog.pc_id.in_(unstable_pc_ids),
            EventLog.generated_at >= cutoff,
            EventLog.event_id.isnot(None),
        )
        .group_by(EventLog.event_id, EventLog.source, EventLog.category)
        .all()
    )

    stable_event_pc_counts: dict = {}
    if total_stable > 0:
        stable_rows = (
            db.session.query(
                EventLog.event_id,
                func.count(func.distinct(EventLog.pc_id)).label("stable_pc_count"),
            )
            .filter(
                EventLog.pc_id.in_(stable_pc_ids),
                EventLog.generated_at >= cutoff,
                EventLog.event_id.isnot(None),
            )
            .group_by(EventLog.event_id)
            .all()
        )
        stable_event_pc_counts = {r.event_id: r.stable_pc_count for r in stable_rows}

    rule_map = {r[0]: r[3] for r in STABILITY_EVENT_RULES}

    event_results = []
    for row in unstable_rows:
        unstable_rate = row.unstable_pc_count / total_unstable
        stable_pc_cnt = stable_event_pc_counts.get(row.event_id, 0)
        stable_rate = stable_pc_cnt / total_stable if total_stable > 0 else 0.0
        lift = unstable_rate / stable_rate if stable_rate > 0 else unstable_rate * 10
        event_results.append(
            {
                "event_id": row.event_id,
                "source": row.source,
                "category": row.category,
                "label": rule_map.get(row.event_id, ""),
                "unstable_pc_count": row.unstable_pc_count,
                "stable_pc_count": stable_pc_cnt,
                "occurrence_count": row.occurrence_count,
                "unstable_rate": round(unstable_rate, 4),
                "stable_rate": round(stable_rate, 4),
                "lift": round(lift, 2),
            }
        )

    event_results.sort(key=lambda x: (-x["lift"], -x["occurrence_count"]))
    event_results = event_results[:limit]

    return jsonify(
        {
            "threshold": threshold,
            "days": days,
            "unstable_pc_count": total_unstable,
            "stable_pc_count": total_stable,
            "events": event_results,
        }
    )


@bp.route("/root-cause/<int:pc_id>", methods=["GET"])
@login_required
def root_cause_pc(pc_id: int):
    """GET /api/stability/root-cause/<pc_id> — per-PC top contributing event IDs."""
    days = int(request.args.get("days", 14))
    limit = int(request.args.get("limit", 10))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    pc = PC.query.get_or_404(pc_id)
    latest_score = (
        StabilityScore.query.filter_by(pc_id=pc_id)
        .order_by(StabilityScore.calculated_at.desc())
        .first()
    )
    rows = (
        db.session.query(
            EventLog.event_id,
            EventLog.source,
            EventLog.category,
            EventLog.level,
            func.count(EventLog.id).label("count"),
        )
        .filter(
            EventLog.pc_id == pc_id,
            EventLog.generated_at >= cutoff,
            EventLog.event_id.isnot(None),
        )
        .group_by(EventLog.event_id, EventLog.source, EventLog.category, EventLog.level)
        .order_by(func.count(EventLog.id).desc())
        .limit(limit)
        .all()
    )
    rule_map = {r[0]: r[3] for r in STABILITY_EVENT_RULES}
    return jsonify(
        {
            "pc_id": pc_id,
            "pc_name": pc.pc_name,
            "stability_score": latest_score.score if latest_score else None,
            "days": days,
            "events": [
                {
                    "event_id": row.event_id,
                    "source": row.source,
                    "category": row.category,
                    "level": row.level,
                    "label": rule_map.get(row.event_id, ""),
                    "count": row.count,
                }
                for row in rows
            ],
        }
    )

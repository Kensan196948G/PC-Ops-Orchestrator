from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request
from sqlalchemy import func
from extensions import db
from models import PC, Task, OperationLog, Alert
from auth import login_required

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")

_RANGE_HOURS = {"24h": 24, "7d": 168, "30d": 720}


def _range_start(range_str: str) -> datetime:
    hours = _RANGE_HOURS.get(range_str, 24)
    return datetime.now(timezone.utc) - timedelta(hours=hours)


@dashboard_bp.route("/stats", methods=["GET"])
@login_required
def stats():
    total_pcs = PC.query.count()
    healthy = PC.query.filter_by(status="healthy").count()
    warning = PC.query.filter_by(status="warning").count()
    critical = PC.query.filter_by(status="critical").count()
    offline = PC.query.filter_by(status="unknown").count()

    five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
    online_count = PC.query.filter(PC.last_seen >= five_min_ago).count()

    pending_tasks = Task.query.filter_by(status="pending").count()
    running_tasks = Task.query.filter_by(status="running").count()

    low_disk = PC.query.filter(
        PC.disk_free_gb.isnot(None),
        PC.disk_total_gb.isnot(None),
        (PC.disk_free_gb / PC.disk_total_gb * 100) < 10,
    ).count()

    high_mem = PC.query.filter(
        PC.memory_available_gb.isnot(None),
        PC.memory_total_gb.isnot(None),
        ((PC.memory_total_gb - PC.memory_available_gb) / PC.memory_total_gb * 100) > 90,
    ).count()

    unresolved_alerts = Alert.query.filter_by(resolved=False).count()

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    completed_today = Task.query.filter(
        Task.status == "completed",
        Task.completed_at >= today_start,
    ).count()

    return jsonify(
        {
            "total_pcs": total_pcs,
            "healthy": healthy,
            "warning": warning,
            "critical": critical,
            "offline": offline,
            "online_count": online_count,
            "pending_tasks": pending_tasks,
            "running_tasks": running_tasks,
            "low_disk_count": low_disk,
            "high_memory_count": high_mem,
            "unresolved_alerts": unresolved_alerts,
            "completed_tasks_today": completed_today,
        }
    )


@dashboard_bp.route("/recent", methods=["GET"])
@login_required
def recent_activity():
    recent_ops = (
        OperationLog.query.order_by(OperationLog.created_at.desc()).limit(20).all()
    )

    recent_tasks = (
        Task.query.filter(Task.status.in_(["completed", "failed"]))
        .order_by(Task.completed_at.desc().nullslast())
        .limit(10)
        .all()
    )

    return jsonify(
        {
            "operations": [op.to_dict() for op in recent_ops],
            "recent_tasks": [t.to_dict() for t in recent_tasks],
        }
    )


@dashboard_bp.route("/health-distribution", methods=["GET"])
@login_required
def health_distribution():
    ranges = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]
    distribution = []
    for low, high in ranges:
        count = PC.query.filter(
            PC.health_score >= low,
            PC.health_score < high,
        ).count()
        distribution.append(
            {
                "range": f"{low}-{high}",
                "count": count,
            }
        )

    return jsonify({"distribution": distribution})


@dashboard_bp.route("/os-breakdown", methods=["GET"])
@login_required
def os_breakdown():
    results = (
        db.session.query(PC.os_version, func.count(PC.id))
        .filter(PC.os_version.isnot(None))
        .group_by(PC.os_version)
        .all()
    )

    return jsonify({"breakdown": [{"os": r[0], "count": r[1]} for r in results]})


@dashboard_bp.route("/kpi", methods=["GET"])
@login_required
def kpi():
    """KPI rates for a given time range (24h / 7d / 30d)."""
    range_str = request.args.get("range", "24h")
    since = _range_start(range_str)

    total_pcs = PC.query.count()

    # Uptime rate: PCs seen within the range / total
    seen_in_range = PC.query.filter(PC.last_seen >= since).count() if total_pcs else 0
    uptime_rate = round(seen_in_range / total_pcs * 100, 1) if total_pcs else 0.0

    # Alert rate: alerts created in range / total PCs (alerts-per-PC ratio as %)
    alerts_in_range = Alert.query.filter(Alert.created_at >= since).count()
    alert_rate = round(alerts_in_range / total_pcs * 100, 1) if total_pcs else 0.0

    # Job success rate: completed / (completed + failed) in range
    completed = Task.query.filter(
        Task.status == "completed",
        Task.created_at >= since,
    ).count()
    failed = Task.query.filter(
        Task.status == "failed",
        Task.created_at >= since,
    ).count()
    total_finished = completed + failed
    job_success_rate = (
        round(completed / total_finished * 100, 1) if total_finished else 100.0
    )

    return jsonify(
        {
            "range": range_str,
            "uptime_rate": uptime_rate,
            "alert_rate": alert_rate,
            "job_success_rate": job_success_rate,
            "pcs_seen": seen_in_range,
            "total_pcs": total_pcs,
            "alerts_in_range": alerts_in_range,
            "completed_jobs": completed,
            "failed_jobs": failed,
        }
    )


@dashboard_bp.route("/timeline", methods=["GET"])
@login_required
def timeline():
    """Time-series data for Chart.js trend charts."""
    range_str = request.args.get("range", "24h")
    since = _range_start(range_str)

    # Determine bucket size and labels
    if range_str == "24h":
        bucket_hours = 1
        num_buckets = 24
    elif range_str == "7d":
        bucket_hours = 24
        num_buckets = 7
    else:  # 30d
        bucket_hours = 24
        num_buckets = 30

    labels = []
    task_completed = []
    task_failed = []
    alert_counts = []

    # Fetch all tasks and alerts in range once, then group in Python
    all_tasks = Task.query.filter(Task.created_at >= since).all()
    all_alerts = Alert.query.filter(Alert.created_at >= since).all()

    for i in range(num_buckets):
        bucket_start = since + timedelta(hours=i * bucket_hours)
        bucket_end = since + timedelta(hours=(i + 1) * bucket_hours)

        if range_str == "24h":
            label = bucket_start.strftime("%H:%M")
        else:
            label = bucket_start.strftime("%m/%d")
        labels.append(label)

        c = sum(
            1
            for t in all_tasks
            if t.created_at is not None
            and bucket_start <= t.created_at.replace(tzinfo=timezone.utc) < bucket_end
            and t.status == "completed"
        )
        f = sum(
            1
            for t in all_tasks
            if t.created_at is not None
            and bucket_start <= t.created_at.replace(tzinfo=timezone.utc) < bucket_end
            and t.status == "failed"
        )
        a = sum(
            1
            for al in all_alerts
            if al.created_at is not None
            and bucket_start <= al.created_at.replace(tzinfo=timezone.utc) < bucket_end
        )

        task_completed.append(c)
        task_failed.append(f)
        alert_counts.append(a)

    return jsonify(
        {
            "range": range_str,
            "labels": labels,
            "task_completed": task_completed,
            "task_failed": task_failed,
            "alert_counts": alert_counts,
        }
    )

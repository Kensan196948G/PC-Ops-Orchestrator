"""Background scheduler that dispatches ScheduledTask entries into Task records."""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="UTC")


def _calc_next_run(scheduled_task, from_dt: datetime) -> datetime | None:
    """Return the next run datetime after `from_dt` for the given ScheduledTask."""
    stype = scheduled_task.schedule_type
    if stype == "interval":
        minutes = scheduled_task.interval_minutes or 60
        return from_dt + timedelta(minutes=minutes)
    if stype == "daily":
        time_str = scheduled_task.daily_time or "00:00"
        h, m = (int(x) for x in time_str.split(":"))
        candidate = from_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= from_dt:
            candidate += timedelta(days=1)
        return candidate
    if stype == "weekly":
        time_str = scheduled_task.weekly_time or "00:00"
        h, m = (int(x) for x in time_str.split(":"))
        target_weekday = scheduled_task.weekly_day or 0
        days_ahead = (target_weekday - from_dt.weekday()) % 7
        candidate = from_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        candidate += timedelta(days=days_ahead)
        if candidate <= from_dt:
            candidate += timedelta(weeks=1)
        return candidate
    return None


def _dispatch_due_tasks(app):
    """Check for due ScheduledTasks and create Task records for each."""
    with app.app_context():
        from extensions import db
        from models import ScheduledTask, Task

        now = datetime.now(timezone.utc)
        # Strip timezone info for naive datetime comparison in SQLite
        now_naive = now.replace(tzinfo=None)

        due = ScheduledTask.query.filter(
            ScheduledTask.is_enabled.is_(True),
            ScheduledTask.next_run_at <= now_naive,
        ).all()

        for st in due:
            try:
                if st.target_type == "pc" and st.pc_id:
                    pc_ids = [st.pc_id]
                else:
                    pc_ids = [None]  # None means "broadcast to all agents"

                for pc_id in pc_ids:
                    task = Task(
                        pc_id=pc_id,
                        task_type=st.task_type,
                        command=st.command,
                        parameters=st.parameters or "{}",
                        status="pending",
                        priority=0,
                        created_by=f"scheduler:{st.id}",
                    )
                    db.session.add(task)

                st.last_run_at = now_naive
                st.run_count = (st.run_count or 0) + 1
                st.last_status = "dispatched"
                next_dt = _calc_next_run(st, now_naive)
                st.next_run_at = next_dt
                db.session.commit()

                logger.info("Scheduled task %s dispatched (id=%s)", st.name, st.id)
            except Exception:
                db.session.rollback()
                logger.exception("Failed to dispatch scheduled task id=%s", st.id)


_OPERATOR_FNS = {
    "gt": lambda v, t: v > t,
    "lt": lambda v, t: v < t,
    "gte": lambda v, t: v >= t,
    "lte": lambda v, t: v <= t,
    "eq": lambda v, t: v == t,
}

_OFFLINE_THRESHOLD_MINUTES = 30


def _get_metric_value(pc, metric: str, SystemSnapshot) -> float | None:
    """Return current metric value for *pc*, or None if data is unavailable."""
    if metric == "cpu":
        snap = (
            SystemSnapshot.query.filter_by(pc_id=pc.id)
            .order_by(SystemSnapshot.collected_at.desc())
            .first()
        )
        return snap.cpu_usage if snap and snap.cpu_usage is not None else None
    if metric == "memory":
        return pc.memory_available_gb
    if metric == "disk":
        return pc.disk_free_gb
    if metric == "offline":
        if pc.last_seen is None:
            return float(_OFFLINE_THRESHOLD_MINUTES + 1)
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        last = (
            pc.last_seen
            if pc.last_seen.tzinfo is None
            else pc.last_seen.replace(tzinfo=None)
        )
        return (now_naive - last).total_seconds() / 60
    return None


def evaluate_rules_once(db, Alert, AlertRule, SystemSnapshot, PC) -> int:
    """Evaluate all enabled AlertRules against all PCs. Return number of alerts created.

    Callable from both the scheduler and the /evaluate API endpoint.
    Deduplication: skips rules where an unresolved Alert with the same source_key exists.
    """
    rules = AlertRule.query.filter_by(is_enabled=True).all()
    if not rules:
        return 0

    pcs = PC.query.all()
    total = 0
    for pc in pcs:
        for rule in rules:
            fn = _OPERATOR_FNS.get(rule.operator)
            if fn is None:
                continue
            value = _get_metric_value(pc, rule.metric, SystemSnapshot)
            if value is None:
                continue
            threshold = (
                rule.threshold
                if rule.threshold is not None
                else _OFFLINE_THRESHOLD_MINUTES
            )
            if not fn(value, threshold):
                continue
            source_key = f"rule:{rule.id}:pc:{pc.id}"
            if Alert.query.filter_by(source_key=source_key, resolved=False).first():
                continue
            db.session.add(
                Alert(
                    pc_id=pc.id,
                    alert_rule_id=rule.id,
                    alert_type=f"rule_{rule.metric}",
                    severity=rule.severity or "warning",
                    message=(
                        f"[自動評価] {pc.pc_name}: {rule.metric} "
                        f"{rule.operator} {threshold} (現在値: {round(value, 2)})"
                    ),
                    source_key=source_key,
                )
            )
            total += 1
    if total:
        db.session.commit()
    return total


def _evaluate_alert_rules(app):
    """Scheduler job: evaluate enabled AlertRules every 5 minutes."""
    with app.app_context():
        from extensions import db
        from models import Alert, AlertRule, PC, SystemSnapshot

        try:
            count = evaluate_rules_once(db, Alert, AlertRule, SystemSnapshot, PC)
            if count:
                logger.info("Alert rule evaluation: %d alert(s) created", count)
        except Exception:
            db.session.rollback()
            logger.exception("Alert rule evaluation job failed")


def init_scheduler(app):
    """Register the dispatch job and start the scheduler."""
    _scheduler.add_job(
        _dispatch_due_tasks,
        "interval",
        minutes=1,
        args=[app],
        id="dispatch_scheduled_tasks",
        replace_existing=True,
        misfire_grace_time=60,
    )
    _scheduler.add_job(
        _evaluate_alert_rules,
        "interval",
        minutes=5,
        args=[app],
        id="evaluate_alert_rules",
        replace_existing=True,
        misfire_grace_time=120,
    )
    _scheduler.start()
    logger.info("Scheduler started")

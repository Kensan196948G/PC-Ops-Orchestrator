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
    _scheduler.start()
    logger.info("Scheduler started")

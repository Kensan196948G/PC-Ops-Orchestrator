"""scheduler.py カバレッジ拡充 — _calc_next_run / _dispatch_due_tasks / init_scheduler.

scheduler.py の未カバー行:
- L34, L36 : _calc_next_run の weekly 同時刻分岐 + None フォールバック
- L41-83   : _dispatch_due_tasks 全体 (broadcast / pc 指定 / 例外時 rollback)
- L88-98   : init_scheduler の add_job + start
"""

import sys
import os
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models import PC, ScheduledTask, Task
import scheduler as scheduler_mod

app = create_app("testing")
_unique = uuid.uuid4().hex[:8]


def setup_module():
    with app.app_context():
        db.create_all()


# ── _calc_next_run ───────────────────────────────────────────────────────


def _make_st(**kwargs):
    """Build a transient (unpersisted) ScheduledTask for _calc_next_run tests."""
    defaults = {
        "name": "n",
        "task_type": "shell",
        "command": "echo",
        "schedule_type": "interval",
        "interval_minutes": 60,
    }
    defaults.update(kwargs)
    return ScheduledTask(**defaults)


def test_calc_next_run_interval():
    st = _make_st(schedule_type="interval", interval_minutes=30)
    base = datetime(2026, 5, 15, 12, 0, 0)
    assert scheduler_mod._calc_next_run(st, base) == base + timedelta(minutes=30)


def test_calc_next_run_interval_default_60_when_none():
    """interval_minutes が None なら 60 がフォールバック."""
    st = _make_st(schedule_type="interval", interval_minutes=None)
    base = datetime(2026, 5, 15, 12, 0, 0)
    assert scheduler_mod._calc_next_run(st, base) == base + timedelta(minutes=60)


def test_calc_next_run_daily_future_today():
    """daily_time が現在より後 → 今日のその時刻."""
    st = _make_st(schedule_type="daily", daily_time="23:00")
    base = datetime(2026, 5, 15, 12, 0, 0)
    result = scheduler_mod._calc_next_run(st, base)
    assert result == datetime(2026, 5, 15, 23, 0, 0)


def test_calc_next_run_daily_past_today_rolls_over():
    """daily_time が現在より前 → 翌日のその時刻."""
    st = _make_st(schedule_type="daily", daily_time="08:00")
    base = datetime(2026, 5, 15, 12, 0, 0)
    result = scheduler_mod._calc_next_run(st, base)
    assert result == datetime(2026, 5, 16, 8, 0, 0)


def test_calc_next_run_daily_default_midnight():
    """daily_time=None なら 00:00 が使われ翌日になる."""
    st = _make_st(schedule_type="daily", daily_time=None)
    base = datetime(2026, 5, 15, 12, 0, 0)
    result = scheduler_mod._calc_next_run(st, base)
    assert result == datetime(2026, 5, 16, 0, 0, 0)


def test_calc_next_run_weekly_future_this_week():
    """weekly_day が未来 → 今週の該当曜日."""
    # 2026-05-15 is Friday (weekday=4); target weekday=5 (Sat)
    st = _make_st(schedule_type="weekly", weekly_day=5, weekly_time="10:00")
    base = datetime(2026, 5, 15, 12, 0, 0)
    result = scheduler_mod._calc_next_run(st, base)
    assert result == datetime(2026, 5, 16, 10, 0, 0)


def test_calc_next_run_weekly_same_day_past_time_rolls_one_week():
    """L33-34: 同曜日かつ過去時刻 → 翌週へ."""
    # base = Friday 12:00, weekly_day=4 (Friday), weekly_time=08:00 → past → +1 week
    st = _make_st(schedule_type="weekly", weekly_day=4, weekly_time="08:00")
    base = datetime(2026, 5, 15, 12, 0, 0)
    result = scheduler_mod._calc_next_run(st, base)
    assert result == datetime(2026, 5, 22, 8, 0, 0)


def test_calc_next_run_weekly_defaults():
    """weekly_time=None / weekly_day=None → "00:00" / 0(Mon) フォールバック."""
    st = _make_st(schedule_type="weekly", weekly_day=None, weekly_time=None)
    base = datetime(2026, 5, 15, 12, 0, 0)  # Friday
    result = scheduler_mod._calc_next_run(st, base)
    # Next Monday 00:00 = 2026-05-18
    assert result == datetime(2026, 5, 18, 0, 0, 0)


def test_calc_next_run_unknown_type_returns_none():
    """L36: schedule_type が unknown → None."""
    st = _make_st(schedule_type="cron")
    base = datetime(2026, 5, 15, 12, 0, 0)
    assert scheduler_mod._calc_next_run(st, base) is None


# ── _dispatch_due_tasks ──────────────────────────────────────────────────


def _create_due_st(name_suffix, target_type="all", pc_id=None, past_minutes=5):
    """Persist a due ScheduledTask via app context."""
    with app.app_context():
        st = ScheduledTask(
            name=f"sched-{name_suffix}-{_unique}",
            task_type="shell",
            command="echo dispatch",
            parameters='{"a":1}',
            target_type=target_type,
            pc_id=pc_id,
            schedule_type="interval",
            interval_minutes=10,
            is_enabled=True,
            next_run_at=datetime.utcnow() - timedelta(minutes=past_minutes),
            run_count=0,
        )
        db.session.add(st)
        db.session.commit()
        return st.id


def test_dispatch_broadcast_creates_task_with_none_pc():
    """target_type=all → pc_id=None の Task が 1 件作成され、ScheduledTask が更新される."""
    st_id = _create_due_st("broadcast")
    scheduler_mod._dispatch_due_tasks(app)
    with app.app_context():
        st = db.session.get(ScheduledTask, st_id)
        assert st.run_count == 1
        assert st.last_status == "dispatched"
        assert st.last_run_at is not None
        assert st.next_run_at > st.last_run_at
        tasks = Task.query.filter_by(created_by=f"scheduler:{st_id}").all()
        assert len(tasks) == 1
        assert tasks[0].pc_id is None
        assert tasks[0].task_type == "shell"
        assert tasks[0].command == "echo dispatch"
        assert tasks[0].status == "pending"


def test_dispatch_pc_target_creates_task_with_pc_id():
    """target_type=pc & pc_id 指定 → 該当 pc 向け Task が 1 件."""
    with app.app_context():
        pc = PC(pc_name=f"sched-pc-{_unique}")
        db.session.add(pc)
        db.session.commit()
        pc_id_val = pc.id
    st_id = _create_due_st("pctarget", target_type="pc", pc_id=pc_id_val)
    scheduler_mod._dispatch_due_tasks(app)
    with app.app_context():
        tasks = Task.query.filter_by(created_by=f"scheduler:{st_id}").all()
        assert len(tasks) == 1
        assert tasks[0].pc_id == pc_id_val


def test_dispatch_disabled_not_picked_up():
    """is_enabled=False の ScheduledTask は dispatch されない."""
    with app.app_context():
        st = ScheduledTask(
            name=f"sched-disabled-{_unique}",
            task_type="shell",
            command="echo",
            schedule_type="interval",
            interval_minutes=10,
            is_enabled=False,
            next_run_at=datetime.utcnow() - timedelta(minutes=5),
        )
        db.session.add(st)
        db.session.commit()
        st_id = st.id
    scheduler_mod._dispatch_due_tasks(app)
    with app.app_context():
        tasks = Task.query.filter_by(created_by=f"scheduler:{st_id}").all()
        assert tasks == []
        # run_count should remain 0
        assert db.session.get(ScheduledTask, st_id).run_count == 0


def test_dispatch_future_not_picked_up():
    """next_run_at が未来の ScheduledTask は dispatch されない."""
    with app.app_context():
        st = ScheduledTask(
            name=f"sched-future-{_unique}",
            task_type="shell",
            command="echo",
            schedule_type="interval",
            interval_minutes=10,
            is_enabled=True,
            next_run_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.session.add(st)
        db.session.commit()
        st_id = st.id
    scheduler_mod._dispatch_due_tasks(app)
    with app.app_context():
        tasks = Task.query.filter_by(created_by=f"scheduler:{st_id}").all()
        assert tasks == []


def test_dispatch_exception_rolls_back():
    """L82-83: dispatch 中の例外 → rollback されつつ次の ScheduledTask は処理継続."""
    bad_id = _create_due_st("baddispatch")
    good_id = _create_due_st("gooddispatch")

    original_commit = db.session.commit
    call_count = {"n": 0}

    def commit_side_effect():
        # First call (bad_id) raises; subsequent calls succeed
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("forced commit failure")
        return original_commit()

    with patch("extensions.db.session.commit", side_effect=commit_side_effect):
        scheduler_mod._dispatch_due_tasks(app)

    with app.app_context():
        bad = db.session.get(ScheduledTask, bad_id)
        good = db.session.get(ScheduledTask, good_id)
        # Bad one: commit failed → run_count untouched
        assert bad.run_count == 0
        # Good one still updated
        assert good.run_count == 1


# ── init_scheduler ───────────────────────────────────────────────────────


def test_init_scheduler_registers_job_and_starts():
    """L88-98: init_scheduler が add_job + start を呼ぶ.

    現在は 2 ジョブを登録する:
    - dispatch_scheduled_tasks (interval=1min)
    - evaluate_alert_rules (interval=5min)
    """
    mock_sched = MagicMock()
    with patch.object(scheduler_mod, "_scheduler", mock_sched):
        scheduler_mod.init_scheduler(app)
    assert mock_sched.add_job.call_count == 2
    calls = mock_sched.add_job.call_args_list

    dispatch_args, dispatch_kwargs = calls[0]
    assert dispatch_args[0] is scheduler_mod._dispatch_due_tasks
    assert dispatch_kwargs["id"] == "dispatch_scheduled_tasks"
    assert dispatch_kwargs["replace_existing"] is True
    assert dispatch_kwargs["args"] == [app]

    eval_args, eval_kwargs = calls[1]
    assert eval_args[0] is scheduler_mod._evaluate_alert_rules
    assert eval_kwargs["id"] == "evaluate_alert_rules"
    assert eval_kwargs["replace_existing"] is True
    assert eval_kwargs["args"] == [app]

    mock_sched.start.assert_called_once()

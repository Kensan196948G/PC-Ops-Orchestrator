import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from auth import admin_required, log_operation, login_required, require_role
from extensions import db
from models import PC, ScheduledTask
from scheduler import _calc_next_run

scheduled_tasks_bp = Blueprint("scheduled_tasks", __name__, url_prefix="/api")

_ALLOWED_TASK_TYPES: frozenset[str] = frozenset(
    {"cleanup", "update", "diagnose", "custom", "collect"}
)
_ALLOWED_SCHEDULE_TYPES: frozenset[str] = frozenset({"interval", "daily", "weekly"})


def _validate_payload(data: dict) -> tuple[dict | None, str | None]:
    """Validate and normalise a ScheduledTask payload. Returns (cleaned, error)."""
    name = data.get("name", "").strip()
    if not name:
        return None, "name は必須です"

    task_type = data.get("task_type", "").strip()
    if task_type not in _ALLOWED_TASK_TYPES:
        return (
            None,
            f"task_type は {sorted(_ALLOWED_TASK_TYPES)} のいずれかで指定してください",
        )

    schedule_type = data.get("schedule_type", "").strip()
    if schedule_type not in _ALLOWED_SCHEDULE_TYPES:
        return (
            None,
            f"schedule_type は {sorted(_ALLOWED_SCHEDULE_TYPES)} のいずれかで指定してください",
        )

    cleaned = {
        "name": name,
        "description": data.get("description", ""),
        "task_type": task_type,
        "command": data.get("command"),
        "parameters": json.dumps(data.get("parameters", {}), ensure_ascii=False),
        "schedule_type": schedule_type,
        "is_enabled": bool(data.get("is_enabled", True)),
    }

    if schedule_type == "interval":
        minutes = data.get("interval_minutes")
        try:
            minutes = int(minutes)
            if minutes < 1:
                raise ValueError
        except (TypeError, ValueError):
            return None, "interval_minutes は 1 以上の整数で指定してください"
        cleaned["interval_minutes"] = minutes

    elif schedule_type == "daily":
        t = data.get("daily_time", "")
        if not _is_valid_time(t):
            return None, "daily_time は HH:MM 形式で指定してください"
        cleaned["daily_time"] = t

    elif schedule_type == "weekly":
        t = data.get("weekly_time", "")
        if not _is_valid_time(t):
            return None, "weekly_time は HH:MM 形式で指定してください"
        day = data.get("weekly_day")
        try:
            day = int(day)
            if not 0 <= day <= 6:
                raise ValueError
        except (TypeError, ValueError):
            return None, "weekly_day は 0(月) 〜 6(日) の整数で指定してください"
        cleaned["weekly_day"] = day
        cleaned["weekly_time"] = t

    pc_name = data.get("pc_name", "").strip()
    if pc_name:
        pc = PC.query.filter_by(pc_name=pc_name).first()
        if not pc:
            return None, f"PC {pc_name} が見つかりません"
        cleaned["pc_id"] = pc.id
        cleaned["target_type"] = "pc"
    else:
        cleaned["pc_id"] = None
        cleaned["target_type"] = "all"

    return cleaned, None


def _is_valid_time(t: str) -> bool:
    try:
        h, m = t.split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except Exception:
        return False


def _compute_initial_next_run(st: ScheduledTask) -> datetime:
    """Calculate the first next_run_at right after creation."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = _calc_next_run(st, now)
    return result if result else now


@scheduled_tasks_bp.route("/scheduled-tasks", methods=["GET"])
@login_required
def list_scheduled_tasks():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    enabled_filter = request.args.get("enabled")

    query = ScheduledTask.query
    if enabled_filter is not None:
        query = query.filter(ScheduledTask.is_enabled == (enabled_filter == "true"))

    pagination = query.order_by(ScheduledTask.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify(
        {
            "scheduled_tasks": [t.to_dict() for t in pagination.items],
            "total": pagination.total,
            "page": page,
            "pages": pagination.pages,
        }
    )


@scheduled_tasks_bp.route("/scheduled-tasks", methods=["POST"])
@require_role("admin", "operator")
def create_scheduled_task():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    cleaned, error = _validate_payload(data)
    if error:
        return jsonify({"error": error}), 400

    st = ScheduledTask(
        **cleaned,
        created_by=request.current_user.username,
    )
    db.session.add(st)
    db.session.flush()
    st.next_run_at = _compute_initial_next_run(st)
    db.session.commit()

    log_operation(
        "create_scheduled_task",
        f"scheduled_task:{st.id}",
        json.dumps(
            {"name": st.name, "schedule_type": st.schedule_type}, ensure_ascii=False
        ),
    )
    return jsonify(
        {"message": "スケジュールタスクを作成しました", "scheduled_task": st.to_dict()}
    ), 201


@scheduled_tasks_bp.route("/scheduled-tasks/<int:task_id>", methods=["GET"])
@login_required
def get_scheduled_task(task_id):
    st = db.session.get(ScheduledTask, task_id)
    if not st:
        return jsonify({"error": f"スケジュールタスク {task_id} が見つかりません"}), 404
    return jsonify({"scheduled_task": st.to_dict()})


@scheduled_tasks_bp.route("/scheduled-tasks/<int:task_id>", methods=["PUT"])
@require_role("admin", "operator")
def update_scheduled_task(task_id):
    st = db.session.get(ScheduledTask, task_id)
    if not st:
        return jsonify({"error": f"スケジュールタスク {task_id} が見つかりません"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    cleaned, error = _validate_payload(data)
    if error:
        return jsonify({"error": error}), 400

    for key, value in cleaned.items():
        setattr(st, key, value)

    st.next_run_at = _compute_initial_next_run(st)
    db.session.commit()

    log_operation(
        "update_scheduled_task",
        f"scheduled_task:{task_id}",
        json.dumps({"name": st.name}, ensure_ascii=False),
    )
    return jsonify(
        {"message": "スケジュールタスクを更新しました", "scheduled_task": st.to_dict()}
    )


@scheduled_tasks_bp.route("/scheduled-tasks/<int:task_id>", methods=["DELETE"])
@admin_required
def delete_scheduled_task(task_id):
    st = db.session.get(ScheduledTask, task_id)
    if not st:
        return jsonify({"error": f"スケジュールタスク {task_id} が見つかりません"}), 404
    db.session.delete(st)
    db.session.commit()

    log_operation(
        "delete_scheduled_task", f"scheduled_task:{task_id}", "スケジュールタスク削除"
    )
    return jsonify({"message": "スケジュールタスクを削除しました"})


@scheduled_tasks_bp.route("/scheduled-tasks/<int:task_id>/toggle", methods=["POST"])
@require_role("admin", "operator")
def toggle_scheduled_task(task_id):
    st = db.session.get(ScheduledTask, task_id)
    if not st:
        return jsonify({"error": f"スケジュールタスク {task_id} が見つかりません"}), 404

    st.is_enabled = not st.is_enabled
    if st.is_enabled:
        st.next_run_at = _compute_initial_next_run(st)
    db.session.commit()

    state = "有効" if st.is_enabled else "無効"
    log_operation(
        "toggle_scheduled_task",
        f"scheduled_task:{task_id}",
        json.dumps({"name": st.name, "is_enabled": st.is_enabled}, ensure_ascii=False),
    )
    return jsonify(
        {
            "message": f"スケジュールタスクを{state}にしました",
            "scheduled_task": st.to_dict(),
        }
    )


@scheduled_tasks_bp.route("/scheduled-tasks/<int:task_id>/run-now", methods=["POST"])
@require_role("admin", "operator")
def run_scheduled_task_now(task_id):
    from models import Task

    st = db.session.get(ScheduledTask, task_id)
    if not st:
        return jsonify({"error": f"スケジュールタスク {task_id} が見つかりません"}), 404

    task = Task(
        pc_id=st.pc_id,
        task_type=st.task_type,
        command=st.command,
        parameters=st.parameters or "{}",
        status="pending",
        priority=1,
        created_by=f"manual:{request.current_user.username}",
    )
    db.session.add(task)
    db.session.commit()

    log_operation(
        "run_scheduled_task_now",
        f"scheduled_task:{task_id}",
        json.dumps({"name": st.name, "task_id": task.id}, ensure_ascii=False),
    )
    return jsonify(
        {"message": "タスクを即時実行キューに追加しました", "task": task.to_dict()}
    ), 201

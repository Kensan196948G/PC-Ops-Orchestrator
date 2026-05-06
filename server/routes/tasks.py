import csv
import io
import json
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, make_response
from sqlalchemy.orm import joinedload
from extensions import db, limiter
from models import Task, PC
from auth import (
    agent_auth_required,
    login_required,
    admin_required,
    log_operation,
    require_role,
)

tasks_bp = Blueprint("tasks", __name__, url_prefix="/api")

_ALLOWED_TASK_TYPES: frozenset[str] = frozenset(
    {"cleanup", "update", "diagnose", "custom", "collect"}
)
_MAX_COMMAND_LEN = 512


@tasks_bp.route("/tasks/pending", methods=["GET"])
@agent_auth_required
def get_pending_tasks():
    pc_name = request.args.get("pc_name", "").strip()
    if not pc_name:
        return jsonify({"error": "pc_name パラメータが必要です"}), 400

    pc = PC.query.filter_by(pc_name=pc_name).first()
    if not pc:
        return jsonify({"tasks": []})

    tasks = (
        Task.query.filter(
            Task.status == "pending",
            (Task.pc_id == pc.id) | (Task.pc_id.is_(None)),
        )
        .order_by(Task.priority.desc(), Task.created_at.asc())
        .limit(5)
        .all()
    )

    return jsonify({"tasks": [t.to_dict() for t in tasks]})


@tasks_bp.route("/tasks", methods=["POST"])
@limiter.limit("60 per minute")
@require_role("admin", "operator")
def create_task():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    task_type = data.get("task_type", "").strip()
    if not task_type:
        return jsonify({"error": "task_type は必須です"}), 400
    if task_type not in _ALLOWED_TASK_TYPES:
        allowed = sorted(_ALLOWED_TASK_TYPES)
        return jsonify(
            {"error": f"task_type は {allowed} のいずれかで指定してください"}
        ), 400

    command = data.get("command")
    if command is not None:
        if not isinstance(command, str):
            return jsonify({"error": "command は文字列で指定してください"}), 400
        if len(command) > _MAX_COMMAND_LEN:
            return jsonify(
                {"error": f"command は {_MAX_COMMAND_LEN} 文字以内にしてください"}
            ), 400

    pc_id = None
    pc_name = data.get("pc_name", "").strip()
    if pc_name:
        pc = PC.query.filter_by(pc_name=pc_name).first()
        if not pc:
            return jsonify({"error": f"PC {pc_name} が見つかりません"}), 404
        pc_id = pc.id

    task = Task(
        pc_id=pc_id,
        task_type=task_type,
        command=command,
        parameters=json.dumps(data.get("parameters", {}), ensure_ascii=False),
        status="pending",
        priority=data.get("priority", 0),
        created_by=request.current_user.username,
    )
    db.session.add(task)
    db.session.commit()

    log_operation(
        "create_task",
        f"task:{task.id} type:{task_type}",
        json.dumps({"pc_name": pc_name, "task_type": task_type}, ensure_ascii=False),
    )

    return jsonify({"message": "タスクを作成しました", "task": task.to_dict()}), 201


@tasks_bp.route("/tasks/bulk", methods=["POST"])
@limiter.limit("20 per minute")
@require_role("admin", "operator")
def bulk_create_tasks():
    """Create the same task for multiple PCs at once.

    Request body:
        task_type: str (required)
        pc_names: list[str] (required, 1-50 items)
        command: str (optional, for custom tasks)
        priority: int (optional)
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    task_type = data.get("task_type", "").strip()
    if not task_type:
        return jsonify({"error": "task_type は必須です"}), 400
    if task_type not in _ALLOWED_TASK_TYPES:
        allowed = sorted(_ALLOWED_TASK_TYPES)
        return (
            jsonify({"error": f"task_type は {allowed} のいずれかで指定してください"}),
            400,
        )

    pc_names = data.get("pc_names", [])
    if not isinstance(pc_names, list) or not pc_names:
        return jsonify({"error": "pc_names は空でないリストで指定してください"}), 400
    if len(pc_names) > 50:
        return jsonify({"error": "一括実行は最大 50 台までです"}), 400

    command = data.get("command")
    if command is not None:
        if not isinstance(command, str):
            return jsonify({"error": "command は文字列で指定してください"}), 400
        if len(command) > _MAX_COMMAND_LEN:
            msg = f"command は {_MAX_COMMAND_LEN} 文字以内にしてください"
            return jsonify({"error": msg}), 400

    priority = data.get("priority", 0)
    successes = []
    failures = []

    for pc_name in pc_names:
        pc_name = str(pc_name).strip()
        pc = PC.query.filter_by(pc_name=pc_name).first()
        if not pc:
            failures.append({"pc_name": pc_name, "error": "PC が見つかりません"})
            continue
        task = Task(
            pc_id=pc.id,
            task_type=task_type,
            command=command,
            parameters=json.dumps(data.get("parameters", {}), ensure_ascii=False),
            status="pending",
            priority=priority,
            created_by=request.current_user.username,
        )
        db.session.add(task)
        db.session.flush()
        successes.append({"pc_name": pc_name, "task_id": task.id})

    if successes:
        db.session.commit()
        log_operation(
            "bulk_create_task",
            f"count:{len(successes)} type:{task_type}",
            json.dumps(
                {"pc_names": [s["pc_name"] for s in successes], "task_type": task_type},
                ensure_ascii=False,
            ),
        )
    else:
        db.session.rollback()

    status_code = 201 if successes else 400
    return (
        jsonify(
            {
                "message": f"{len(successes)} 件のタスクを作成しました",
                "successes": successes,
                "failures": failures,
            }
        ),
        status_code,
    )


@tasks_bp.route("/result", methods=["POST"])
@agent_auth_required
def submit_result():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"error": "task_id は必須です"}), 400

    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({"error": f"タスク {task_id} が見つかりません"}), 404

    _allowed_statuses = {"completed", "failed", "running"}
    new_status = data.get("status", "completed")
    if new_status not in _allowed_statuses:
        return jsonify(
            {"error": f"status は {_allowed_statuses} のいずれかで指定してください"}
        ), 400
    task.status = new_status
    task.result = json.dumps(data.get("result", {}), ensure_ascii=False)
    task.error_message = data.get("error_message")
    task.completed_at = datetime.now(timezone.utc)

    db.session.commit()

    return jsonify({"message": "結果を受信しました"})


@tasks_bp.route("/tasks/<int:task_id>", methods=["GET"])
@login_required
def get_task(task_id):
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({"error": f"タスク {task_id} が見つかりません"}), 404
    return jsonify({"task": task.to_dict()})


@tasks_bp.route("/tasks/export.csv", methods=["GET"])
@login_required
def export_tasks_csv():
    status_filter = request.args.get("status")
    task_type_filter = request.args.get("task_type")

    query = Task.query
    if status_filter:
        query = query.filter(Task.status == status_filter)
    if task_type_filter:
        query = query.filter(Task.task_type == task_type_filter)

    tasks = (
        query.options(joinedload(Task.pc))
        .order_by(Task.created_at.desc())
        .limit(5000)
        .all()
    )

    buf = io.StringIO()
    buf.write("﻿")  # BOM for Excel
    writer = csv.writer(buf)
    writer.writerow(
        [
            "ID",
            "タスク種別",
            "PC名",
            "状態",
            "優先度",
            "作成者",
            "作成日時",
            "完了日時",
            "エラー",
        ]
    )
    for t in tasks:
        pc_name = t.pc.pc_name if t.pc else ""
        writer.writerow(
            [
                t.id,
                t.task_type or "",
                pc_name,
                t.status or "",
                t.priority if t.priority is not None else "",
                t.created_by or "",
                t.created_at.isoformat() if t.created_at else "",
                t.completed_at.isoformat() if t.completed_at else "",
                t.error_message or "",
            ]
        )

    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=tasks.csv"
    return response


@tasks_bp.route("/tasks", methods=["GET"])
@login_required
def list_tasks():
    status_filter = request.args.get("status")
    task_type = request.args.get("task_type")
    pc_name = request.args.get("pc_name")
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)

    query = Task.query

    if status_filter:
        query = query.filter(Task.status == status_filter)
    if task_type:
        query = query.filter(Task.task_type == task_type)
    if pc_name:
        pc = PC.query.filter_by(pc_name=pc_name).first()
        if pc:
            query = query.filter((Task.pc_id == pc.id) | (Task.pc_id.is_(None)))
        else:
            return jsonify({"tasks": [], "total": 0, "page": page})

    query = query.order_by(Task.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify(
        {
            "tasks": [t.to_dict() for t in pagination.items],
            "total": pagination.total,
            "page": page,
            "pages": pagination.pages,
        }
    )


@tasks_bp.route("/tasks/<int:task_id>", methods=["DELETE"])
@admin_required
def delete_task(task_id):
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({"error": f"タスク {task_id} が見つかりません"}), 404
    db.session.delete(task)
    db.session.commit()

    log_operation("delete_task", f"task:{task_id}", "タスク削除")
    return jsonify({"message": "タスクを削除しました"})

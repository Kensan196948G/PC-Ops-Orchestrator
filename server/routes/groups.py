import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from auth import admin_required, log_operation, login_required
from extensions import db
from models import PC, PCGroup, Task

groups_bp = Blueprint("groups", __name__, url_prefix="/api")


@groups_bp.route("/groups", methods=["GET"])
@login_required
def list_groups():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    groups = PCGroup.query.order_by(PCGroup.name).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify(
        {
            "groups": [g.to_dict() for g in groups.items],
            "total": groups.total,
            "page": page,
            "pages": groups.pages,
        }
    )


@groups_bp.route("/groups", methods=["POST"])
@admin_required
def create_group():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name は必須です"}), 400
    if len(name) > 255:
        return jsonify({"error": "name は255文字以内で指定してください"}), 400

    if PCGroup.query.filter_by(name=name).first():
        return jsonify({"error": f"グループ '{name}' は既に存在します"}), 409

    group = PCGroup(
        name=name,
        description=data.get("description", ""),
        created_by=request.current_user.username,
    )

    pc_names = data.get("pc_names", [])
    if not isinstance(pc_names, list):
        return jsonify({"error": "pc_names はリスト形式で指定してください"}), 400
    for pc_name in pc_names:
        pc = PC.query.filter_by(pc_name=pc_name).first()
        if not pc:
            return jsonify({"error": f"PC '{pc_name}' が見つかりません"}), 400
        group.pcs.append(pc)

    db.session.add(group)
    db.session.commit()

    log_operation(
        "create_group",
        f"group:{group.id}",
        json.dumps(
            {"name": group.name, "pc_count": group.pcs.count()}, ensure_ascii=False
        ),
    )
    return jsonify(
        {"message": "グループを作成しました", "group": group.to_dict(include_pcs=True)}
    ), 201


@groups_bp.route("/groups/<int:group_id>", methods=["GET"])
@login_required
def get_group(group_id):
    group = db.session.get(PCGroup, group_id)
    if not group:
        return jsonify({"error": f"グループ {group_id} が見つかりません"}), 404
    return jsonify({"group": group.to_dict(include_pcs=True)})


@groups_bp.route("/groups/<int:group_id>", methods=["PUT"])
@admin_required
def update_group(group_id):
    group = db.session.get(PCGroup, group_id)
    if not group:
        return jsonify({"error": f"グループ {group_id} が見つかりません"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return jsonify({"error": "name は必須です"}), 400
        if len(name) > 255:
            return jsonify({"error": "name は255文字以内で指定してください"}), 400
        existing = PCGroup.query.filter_by(name=name).first()
        if existing and existing.id != group_id:
            return jsonify({"error": f"グループ '{name}' は既に存在します"}), 409
        group.name = name

    if "description" in data:
        group.description = data["description"]

    if "pc_names" in data:
        pc_names = data["pc_names"]
        if not isinstance(pc_names, list):
            return jsonify({"error": "pc_names はリスト形式で指定してください"}), 400
        new_pcs = []
        for pc_name in pc_names:
            pc = PC.query.filter_by(pc_name=pc_name).first()
            if not pc:
                return jsonify({"error": f"PC '{pc_name}' が見つかりません"}), 400
            new_pcs.append(pc)
        # replace membership
        for pc in list(group.pcs):
            group.pcs.remove(pc)
        for pc in new_pcs:
            group.pcs.append(pc)

    group.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    log_operation(
        "update_group",
        f"group:{group_id}",
        json.dumps({"name": group.name}, ensure_ascii=False),
    )
    return jsonify(
        {"message": "グループを更新しました", "group": group.to_dict(include_pcs=True)}
    )


@groups_bp.route("/groups/<int:group_id>", methods=["DELETE"])
@admin_required
def delete_group(group_id):
    group = db.session.get(PCGroup, group_id)
    if not group:
        return jsonify({"error": f"グループ {group_id} が見つかりません"}), 404
    db.session.delete(group)
    db.session.commit()
    log_operation("delete_group", f"group:{group_id}", "グループ削除")
    return jsonify({"message": "グループを削除しました"})


@groups_bp.route("/groups/<int:group_id>/pcs", methods=["POST"])
@admin_required
def add_pc_to_group(group_id):
    group = db.session.get(PCGroup, group_id)
    if not group:
        return jsonify({"error": f"グループ {group_id} が見つかりません"}), 404

    data = request.get_json()
    pc_name = (data or {}).get("pc_name", "").strip()
    if not pc_name:
        return jsonify({"error": "pc_name は必須です"}), 400

    pc = PC.query.filter_by(pc_name=pc_name).first()
    if not pc:
        return jsonify({"error": f"PC '{pc_name}' が見つかりません"}), 400

    if group.pcs.filter_by(id=pc.id).first():
        return jsonify(
            {"error": f"PC '{pc_name}' は既にこのグループに所属しています"}
        ), 409

    group.pcs.append(pc)
    db.session.commit()
    log_operation(
        "add_pc_to_group",
        f"group:{group_id}",
        json.dumps({"pc_name": pc_name}, ensure_ascii=False),
    )
    return jsonify(
        {
            "message": f"PC '{pc_name}' をグループに追加しました",
            "group": group.to_dict(include_pcs=True),
        }
    )


@groups_bp.route("/groups/<int:group_id>/pcs/<int:pc_id>", methods=["DELETE"])
@admin_required
def remove_pc_from_group(group_id, pc_id):
    group = db.session.get(PCGroup, group_id)
    if not group:
        return jsonify({"error": f"グループ {group_id} が見つかりません"}), 404

    pc = db.session.get(PC, pc_id)
    if not pc or not group.pcs.filter_by(id=pc_id).first():
        return jsonify({"error": f"PC {pc_id} はこのグループに所属していません"}), 404

    group.pcs.remove(pc)
    db.session.commit()
    log_operation(
        "remove_pc_from_group",
        f"group:{group_id}",
        json.dumps({"pc_id": pc_id}, ensure_ascii=False),
    )
    return jsonify(
        {
            "message": "グループから PC を削除しました",
            "group": group.to_dict(include_pcs=True),
        }
    )


@groups_bp.route("/groups/<int:group_id>/tasks", methods=["POST"])
@admin_required
def create_group_task(group_id):
    """Create tasks for all PCs in a group."""
    group = db.session.get(PCGroup, group_id)
    if not group:
        return jsonify({"error": f"グループ {group_id} が見つかりません"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    _ALLOWED_TASK_TYPES = frozenset(
        {"cleanup", "update", "diagnose", "custom", "collect"}
    )
    task_type = (data.get("task_type") or "").strip()
    if task_type not in _ALLOWED_TASK_TYPES:
        return jsonify(
            {
                "error": f"task_type は {sorted(_ALLOWED_TASK_TYPES)} のいずれかで指定してください"
            }
        ), 400

    command = data.get("command")
    if command is not None:
        if not isinstance(command, str):
            return jsonify({"error": "command は文字列で指定してください"}), 400
        if len(command) > 512:
            return jsonify({"error": "command は512文字以内で指定してください"}), 400

    pcs = list(group.pcs)
    if not pcs:
        return jsonify({"error": "グループに PC が登録されていません"}), 400

    tasks = []
    for pc in pcs:
        task = Task(
            pc_id=pc.id,
            task_type=task_type,
            command=command,
            parameters=json.dumps(data.get("parameters", {}), ensure_ascii=False),
            status="pending",
            priority=data.get("priority", 0),
            created_by=f"group:{group_id}:{request.current_user.username}",
        )
        db.session.add(task)
        tasks.append(task)

    db.session.flush()
    db.session.commit()

    log_operation(
        "create_group_task",
        f"group:{group_id}",
        json.dumps(
            {"task_type": task_type, "pc_count": len(tasks)}, ensure_ascii=False
        ),
    )
    return jsonify(
        {
            "message": f"{len(tasks)} 台の PC にタスクを作成しました",
            "tasks": [t.to_dict() for t in tasks],
        }
    ), 201

import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, render_template

from auth import admin_required, log_operation, login_required, require_role
from extensions import db, limiter
from models import JobExecution, JobTemplate, PC

job_templates_bp = Blueprint("job_templates", __name__)

_VALID_RISK_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})
_VALID_CATEGORIES: frozenset[str] = frozenset(
    {"general", "maintenance", "security", "diagnostics", "update"}
)
_MAX_SCRIPT_LEN = 16384  # 16 KB limit for script_body


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------


@job_templates_bp.route("/job-templates")
@login_required
def job_templates_page():
    return render_template("job_templates.html")


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------


@job_templates_bp.route("/api/job-templates", methods=["GET"])
@login_required
def list_job_templates():
    category = request.args.get("category", "").strip()
    risk_level = request.args.get("risk_level", "").strip()
    enabled_only = request.args.get("enabled_only", "true").lower() != "false"

    query = JobTemplate.query
    if enabled_only:
        query = query.filter(JobTemplate.is_enabled.is_(True))
    if category:
        query = query.filter(JobTemplate.category == category)
    if risk_level:
        if risk_level not in _VALID_RISK_LEVELS:
            return jsonify(
                {"error": f"risk_level は {sorted(_VALID_RISK_LEVELS)} のいずれかです"}
            ), 400
        query = query.filter(JobTemplate.risk_level == risk_level)

    templates = query.order_by(JobTemplate.name).all()
    return jsonify(
        {"templates": [t.to_dict() for t in templates], "total": len(templates)}
    )


@job_templates_bp.route("/api/job-templates/<int:template_id>", methods=["GET"])
@login_required
def get_job_template(template_id: int):
    template = db.session.get(JobTemplate, template_id)
    if not template:
        return jsonify({"error": f"テンプレート {template_id} が見つかりません"}), 404
    is_admin = getattr(request.current_user, "role", "") == "admin"
    return jsonify({"template": template.to_dict(include_script=is_admin)})


@job_templates_bp.route("/api/job-templates", methods=["POST"])
@limiter.limit("30 per minute")
@admin_required
def create_job_template():
    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name は必須です"}), 400
    if JobTemplate.query.filter_by(name=name).first():
        return jsonify(
            {"error": f"テンプレート名 '{name}' は既に使用されています"}
        ), 409

    risk_level = data.get("risk_level", "low")
    if risk_level not in _VALID_RISK_LEVELS:
        return jsonify(
            {"error": f"risk_level は {sorted(_VALID_RISK_LEVELS)} のいずれかです"}
        ), 400

    category = data.get("category", "general")
    if category not in _VALID_CATEGORIES:
        return jsonify(
            {"error": f"category は {sorted(_VALID_CATEGORIES)} のいずれかです"}
        ), 400

    script_body = data.get("script_body", "")
    if len(script_body) > _MAX_SCRIPT_LEN:
        return jsonify(
            {"error": f"script_body は {_MAX_SCRIPT_LEN} 文字以内にしてください"}
        ), 400

    params_schema = data.get("parameters_schema")
    if params_schema is not None and not isinstance(params_schema, str):
        params_schema = json.dumps(params_schema, ensure_ascii=False)

    template = JobTemplate(
        name=name,
        description=data.get("description", ""),
        category=category,
        script_body=script_body,
        parameters_schema=params_schema,
        risk_level=risk_level,
        requires_approval=bool(
            data.get("requires_approval", risk_level in ("medium", "high"))
        ),
        is_enabled=bool(data.get("is_enabled", True)),
        created_by=request.current_user.username,
    )
    db.session.add(template)
    db.session.commit()

    log_operation(
        "create_job_template",
        f"template:{template.id} name:{name} risk:{risk_level}",
        json.dumps({"name": name, "risk_level": risk_level}, ensure_ascii=False),
    )
    return jsonify(
        {
            "message": "テンプレートを作成しました",
            "template": template.to_dict(include_script=True),
        }
    ), 201


@job_templates_bp.route("/api/job-templates/<int:template_id>", methods=["PUT"])
@limiter.limit("30 per minute")
@admin_required
def update_job_template(template_id: int):
    template = db.session.get(JobTemplate, template_id)
    if not template:
        return jsonify({"error": f"テンプレート {template_id} が見つかりません"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "リクエストボディが必要です"}), 400

    if "name" in data:
        new_name = data["name"].strip()
        if not new_name:
            return jsonify({"error": "name は空にできません"}), 400
        existing = JobTemplate.query.filter_by(name=new_name).first()
        if existing and existing.id != template_id:
            return jsonify(
                {"error": f"テンプレート名 '{new_name}' は既に使用されています"}
            ), 409
        template.name = new_name

    if "description" in data:
        template.description = data["description"]
    if "category" in data:
        cat = data["category"]
        if cat not in _VALID_CATEGORIES:
            return jsonify(
                {"error": f"category は {sorted(_VALID_CATEGORIES)} のいずれかです"}
            ), 400
        template.category = cat
    if "risk_level" in data:
        rl = data["risk_level"]
        if rl not in _VALID_RISK_LEVELS:
            return jsonify(
                {"error": f"risk_level は {sorted(_VALID_RISK_LEVELS)} のいずれかです"}
            ), 400
        template.risk_level = rl
    if "script_body" in data:
        sb = data["script_body"]
        if len(sb) > _MAX_SCRIPT_LEN:
            return jsonify(
                {"error": f"script_body は {_MAX_SCRIPT_LEN} 文字以内にしてください"}
            ), 400
        template.script_body = sb
    if "parameters_schema" in data:
        ps = data["parameters_schema"]
        if ps is not None and not isinstance(ps, str):
            ps = json.dumps(ps, ensure_ascii=False)
        template.parameters_schema = ps
    if "requires_approval" in data:
        template.requires_approval = bool(data["requires_approval"])
    if "is_enabled" in data:
        template.is_enabled = bool(data["is_enabled"])

    db.session.commit()
    log_operation(
        "update_job_template",
        f"template:{template_id}",
        json.dumps({"fields": list(data.keys())}, ensure_ascii=False),
    )
    return jsonify(
        {
            "message": "テンプレートを更新しました",
            "template": template.to_dict(include_script=True),
        }
    )


@job_templates_bp.route("/api/job-templates/<int:template_id>", methods=["DELETE"])
@admin_required
def delete_job_template(template_id: int):
    template = db.session.get(JobTemplate, template_id)
    if not template:
        return jsonify({"error": f"テンプレート {template_id} が見つかりません"}), 404

    if template.executions.count() > 0:
        return jsonify(
            {
                "error": "実行履歴があるテンプレートは削除できません。無効化 (is_enabled=false) を使用してください"
            }
        ), 409

    db.session.delete(template)
    db.session.commit()
    log_operation("delete_job_template", f"template:{template_id}", template.name)
    return jsonify({"message": "テンプレートを削除しました"})


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@job_templates_bp.route(
    "/api/job-templates/<int:template_id>/execute", methods=["POST"]
)
@limiter.limit("20 per minute")
@require_role("admin", "operator")
def execute_job_template(template_id: int):
    template = db.session.get(JobTemplate, template_id)
    if not template:
        return jsonify({"error": f"テンプレート {template_id} が見つかりません"}), 404
    if not template.is_enabled:
        return jsonify({"error": "このテンプレートは無効化されています"}), 422

    data = request.get_json() or {}
    pc_id = data.get("pc_id")
    if not pc_id:
        return jsonify({"error": "pc_id は必須です"}), 400

    pc = db.session.get(PC, pc_id)
    if not pc:
        return jsonify({"error": f"PC {pc_id} が見つかりません"}), 404

    params = data.get("parameters")
    if params is not None and not isinstance(params, str):
        params = json.dumps(params, ensure_ascii=False)

    execution = JobExecution(
        template_id=template_id,
        pc_id=pc_id,
        status="pending",
        parameters=params,
        requested_by=request.current_user.username,
    )
    db.session.add(execution)
    db.session.commit()

    log_operation(
        "execute_job_template",
        f"execution:{execution.id} template:{template_id} pc:{pc_id}",
        json.dumps(
            {
                "template_name": template.name,
                "pc_name": pc.pc_name,
                "risk_level": template.risk_level,
            },
            ensure_ascii=False,
        ),
    )
    return jsonify(
        {"message": "実行リクエストを作成しました", "execution": execution.to_dict()}
    ), 201


@job_templates_bp.route("/api/job-executions", methods=["GET"])
@login_required
def list_job_executions():
    status = request.args.get("status", "").strip()
    template_id = request.args.get("template_id", type=int)
    pc_id = request.args.get("pc_id", type=int)
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)

    query = JobExecution.query
    if status:
        query = query.filter(JobExecution.status == status)
    if template_id:
        query = query.filter(JobExecution.template_id == template_id)
    if pc_id:
        query = query.filter(JobExecution.pc_id == pc_id)

    query = query.order_by(JobExecution.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify(
        {
            "executions": [e.to_dict() for e in pagination.items],
            "total": pagination.total,
            "page": page,
            "pages": pagination.pages,
        }
    )


@job_templates_bp.route("/api/job-executions/<int:execution_id>", methods=["GET"])
@login_required
def get_job_execution(execution_id: int):
    execution = db.session.get(JobExecution, execution_id)
    if not execution:
        return jsonify({"error": f"実行 {execution_id} が見つかりません"}), 404
    return jsonify({"execution": execution.to_dict()})


@job_templates_bp.route(
    "/api/job-executions/<int:execution_id>/cancel", methods=["POST"]
)
@require_role("admin", "operator")
def cancel_job_execution(execution_id: int):
    execution = db.session.get(JobExecution, execution_id)
    if not execution:
        return jsonify({"error": f"実行 {execution_id} が見つかりません"}), 404
    if execution.status not in ("pending",):
        return jsonify(
            {
                "error": f"status={execution.status} の実行はキャンセルできません (pending のみ可)"
            }
        ), 422

    execution.status = "cancelled"
    execution.completed_at = datetime.now(timezone.utc)
    db.session.commit()
    log_operation("cancel_job_execution", f"execution:{execution_id}", "キャンセル")
    return jsonify(
        {"message": "実行をキャンセルしました", "execution": execution.to_dict()}
    )

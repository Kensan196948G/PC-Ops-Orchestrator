from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify
from sqlalchemy import func
from extensions import db
from models import PC, Task, SystemSnapshot, OperationLog
from auth import login_required

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')


@dashboard_bp.route('/stats', methods=['GET'])
@login_required
def stats():
    total_pcs = PC.query.count()
    healthy = PC.query.filter_by(status='healthy').count()
    warning = PC.query.filter_by(status='warning').count()
    critical = PC.query.filter_by(status='critical').count()
    offline = PC.query.filter_by(status='unknown').count()

    five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
    online_count = PC.query.filter(PC.last_seen >= five_min_ago).count()

    pending_tasks = Task.query.filter_by(status='pending').count()
    running_tasks = Task.query.filter_by(status='running').count()

    low_disk = PC.query.filter(
        PC.disk_free_gb.isnot(None),
        PC.disk_total_gb.isnot(None),
        (PC.disk_free_gb / PC.disk_total_gb * 100) < 10
    ).count()

    high_mem = PC.query.filter(
        PC.memory_available_gb.isnot(None),
        PC.memory_total_gb.isnot(None),
        ((PC.memory_total_gb - PC.memory_available_gb) / PC.memory_total_gb * 100) > 90
    ).count()

    return jsonify({
        'total_pcs': total_pcs,
        'healthy': healthy,
        'warning': warning,
        'critical': critical,
        'offline': offline,
        'online_count': online_count,
        'pending_tasks': pending_tasks,
        'running_tasks': running_tasks,
        'low_disk_count': low_disk,
        'high_memory_count': high_mem,
    })


@dashboard_bp.route('/recent', methods=['GET'])
@login_required
def recent_activity():
    recent_ops = OperationLog.query.order_by(
        OperationLog.created_at.desc()
    ).limit(20).all()

    recent_tasks = Task.query.filter(
        Task.status.in_(['completed', 'failed'])
    ).order_by(Task.completed_at.desc().nullslast()).limit(10).all()

    return jsonify({
        'operations': [op.to_dict() for op in recent_ops],
        'recent_tasks': [t.to_dict() for t in recent_tasks],
    })


@dashboard_bp.route('/health-distribution', methods=['GET'])
@login_required
def health_distribution():
    ranges = [
        (0, 20), (20, 40), (40, 60), (60, 80), (80, 100)
    ]
    distribution = []
    for low, high in ranges:
        count = PC.query.filter(
            PC.health_score >= low,
            PC.health_score < high,
        ).count()
        distribution.append({
            'range': f'{low}-{high}',
            'count': count,
        })

    return jsonify({'distribution': distribution})


@dashboard_bp.route('/os-breakdown', methods=['GET'])
@login_required
def os_breakdown():
    results = db.session.query(
        PC.os_version, func.count(PC.id)
    ).filter(
        PC.os_version.isnot(None)
    ).group_by(PC.os_version).all()

    return jsonify({
        'breakdown': [{'os': r[0], 'count': r[1]} for r in results]
    })

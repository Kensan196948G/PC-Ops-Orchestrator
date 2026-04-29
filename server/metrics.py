"""In-process metrics collector + Prometheus text exposition format.

Designed to be stdlib-only so we don't pull in `prometheus_client`. The
exposition format is the simple version 0.0.4 text format documented at
https://prometheus.io/docs/instrumenting/exposition_formats/

The module is **process-local** (no shared state across workers): the
``ratelimit_hits_total`` counter resets at process restart and isn't
aggregated across gunicorn workers. That's intentional — Prometheus is
expected to scrape every replica separately, and we sidestep the IPC
complexity of a shared counter for an M4 baseline.
"""

from __future__ import annotations

from threading import Lock
from typing import Iterable

from sqlalchemy import func

from extensions import db
from models import PC, Alert, ScheduledTask, Task, User

# ---------------------------------------------------------------------------
# Process-local counters
# ---------------------------------------------------------------------------

_counters_lock = Lock()
_counters: dict[str, int] = {
    "ratelimit_hits_total": 0,
}


def bump_counter(name: str, amount: int = 1) -> None:
    """Increment a process-local counter by ``amount`` (thread-safe)."""
    with _counters_lock:
        _counters[name] = _counters.get(name, 0) + amount


def counter_value(name: str) -> int:
    with _counters_lock:
        return _counters.get(name, 0)


def reset_counters_for_test() -> None:
    """Test helper — wipes counters so tests can assert exact values."""
    with _counters_lock:
        for key in list(_counters):
            _counters[key] = 0


# ---------------------------------------------------------------------------
# Prometheus exposition format
# ---------------------------------------------------------------------------

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

_VALID_LABEL_VALUE = str.maketrans({"\\": r"\\", '"': r"\"", "\n": r"\n"})


def _escape_label_value(value: str) -> str:
    return value.translate(_VALID_LABEL_VALUE)


def _format_metric_line(name: str, labels: dict[str, str] | None, value: float) -> str:
    if not labels:
        return f"{name} {value}"
    label_str = ",".join(
        f'{k}="{_escape_label_value(str(v))}"' for k, v in sorted(labels.items())
    )
    return f"{name}{{{label_str}}} {value}"


def _emit(
    name: str,
    metric_type: str,
    help_text: str,
    samples: Iterable[tuple[dict[str, str] | None, float]],
) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} {metric_type}"]
    for labels, value in samples:
        lines.append(_format_metric_line(name, labels, value))
    return lines


# ---------------------------------------------------------------------------
# Sample collectors (DB-backed gauges)
# ---------------------------------------------------------------------------


def _collect_pcs_total() -> list[tuple[dict[str, str] | None, float]]:
    rows = db.session.query(PC.status, func.count(PC.id)).group_by(PC.status).all()
    return [({"status": (status or "unknown")}, int(count)) for status, count in rows]


def _collect_alerts_unresolved_total() -> list[tuple[dict[str, str] | None, float]]:
    rows = (
        db.session.query(Alert.severity, func.count(Alert.id))
        .filter(Alert.resolved == False)  # noqa: E712 (SQLAlchemy idiom)
        .group_by(Alert.severity)
        .all()
    )
    return [
        ({"severity": (severity or "unknown")}, int(count)) for severity, count in rows
    ]


def _collect_tasks_pending_total() -> list[tuple[dict[str, str] | None, float]]:
    count = (
        db.session.query(func.count(Task.id)).filter(Task.status == "pending").scalar()
        or 0
    )
    return [(None, int(count))]


def _collect_scheduled_tasks_enabled_total() -> list[
    tuple[dict[str, str] | None, float]
]:
    count = (
        db.session.query(func.count(ScheduledTask.id))
        .filter(ScheduledTask.is_enabled == True)  # noqa: E712
        .scalar()
        or 0
    )
    return [(None, int(count))]


def _collect_users_total() -> list[tuple[dict[str, str] | None, float]]:
    rows = (
        db.session.query(User.role, func.count(User.id))
        .filter(User.is_active == True)  # noqa: E712
        .group_by(User.role)
        .all()
    )
    return [({"role": (role or "unknown")}, int(count)) for role, count in rows]


def render_metrics() -> str:
    """Return the full Prometheus exposition body as a string."""
    lines: list[str] = []

    lines.extend(
        _emit(
            "pcs_total",
            "gauge",
            "Number of registered PCs by status.",
            _collect_pcs_total(),
        )
    )
    lines.extend(
        _emit(
            "alerts_unresolved_total",
            "gauge",
            "Number of unresolved alerts by severity.",
            _collect_alerts_unresolved_total(),
        )
    )
    lines.extend(
        _emit(
            "tasks_pending_total",
            "gauge",
            "Number of tasks currently in 'pending' status.",
            _collect_tasks_pending_total(),
        )
    )
    lines.extend(
        _emit(
            "scheduled_tasks_enabled_total",
            "gauge",
            "Number of scheduled tasks with is_enabled=true.",
            _collect_scheduled_tasks_enabled_total(),
        )
    )
    lines.extend(
        _emit(
            "users_total",
            "gauge",
            "Number of active users by role.",
            _collect_users_total(),
        )
    )

    # Process-local counters (reset on restart; scrape per-worker).
    lines.extend(
        _emit(
            "ratelimit_hits_total",
            "counter",
            "Cumulative HTTP 429 responses returned by the rate limiter since process start.",
            [(None, counter_value("ratelimit_hits_total"))],
        )
    )

    # Liveness gauge — always emits 1 if the endpoint is reachable.
    lines.extend(
        _emit(
            "up",
            "gauge",
            "1 if the metrics endpoint is reachable.",
            [(None, 1)],
        )
    )

    # Trailing newline is recommended by the spec.
    return "\n".join(lines) + "\n"

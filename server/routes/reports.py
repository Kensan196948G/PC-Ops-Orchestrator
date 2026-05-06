"""Monthly report API – JSON / CSV / PDF endpoints (M5-3, Issue #76)."""

import calendar
import csv
import io
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, make_response

from auth import require_role
from models import PC, Task, Alert, OperationLog

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")

_IPA_FONT = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _month_range(year: int, month: int):
    """Return (start, end) datetime range for the given year/month (UTC)."""
    _, last_day = calendar.monthrange(year, month)
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def _aggregate(year: int, month: int) -> dict:
    """Compute monthly KPI metrics from the database."""
    start, end = _month_range(year, month)

    # PC counts (current snapshot, not historical)
    pc_total = PC.query.count()
    pc_online = PC.query.filter(PC.status == "online").count()
    pc_offline = pc_total - pc_online

    # Task stats for the period
    task_q = Task.query.filter(Task.created_at >= start, Task.created_at <= end)
    task_total = task_q.count()
    task_success = task_q.filter(Task.status == "completed").count()
    task_failed = task_q.filter(Task.status == "failed").count()
    task_pending = task_total - task_success - task_failed
    task_rate = round(task_success / task_total * 100, 1) if task_total else 0.0

    # Alert stats for the period
    alert_q = Alert.query.filter(Alert.created_at >= start, Alert.created_at <= end)
    alert_total = alert_q.count()
    alert_critical = alert_q.filter(Alert.severity == "critical").count()
    alert_high = alert_q.filter(Alert.severity == "high").count()
    alert_medium = alert_q.filter(Alert.severity == "medium").count()
    alert_low = alert_q.filter(Alert.severity == "low").count()

    # Operation logs for the period
    op_total = OperationLog.query.filter(
        OperationLog.created_at >= start,
        OperationLog.created_at <= end,
    ).count()

    # Simple SLA: base 100 % minus penalty per critical/high alert
    sla = max(0.0, round(100.0 - alert_critical * 0.5 - alert_high * 0.1, 1))
    health_rate = round(pc_online / pc_total * 100, 1) if pc_total else 0.0

    return {
        "period": f"{year:04d}-{month:02d}",
        "pc": {
            "total": pc_total,
            "online": pc_online,
            "offline": pc_offline,
            "health_rate": health_rate,
        },
        "tasks": {
            "total": task_total,
            "completed": task_success,
            "failed": task_failed,
            "pending": task_pending,
            "success_rate": task_rate,
        },
        "alerts": {
            "total": alert_total,
            "critical": alert_critical,
            "high": alert_high,
            "medium": alert_medium,
            "low": alert_low,
        },
        "operations": {"total": op_total},
        "sla": sla,
    }


def _recent_months(n: int = 12) -> list[dict]:
    """Return aggregates for the most recent n months."""
    now = datetime.now(timezone.utc)
    results = []
    y, m = now.year, now.month
    for _ in range(n):
        results.append(_aggregate(y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return results


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────


@reports_bp.route("/monthly", methods=["GET"])
@require_role("admin", "operator", "viewer")
def monthly_report():
    """Return KPI aggregates for a given year/month."""
    now = datetime.now(timezone.utc)
    year = request.args.get("year", now.year, type=int)
    month = request.args.get("month", now.month, type=int)
    if not (1 <= month <= 12):
        return jsonify({"error": "month must be 1-12"}), 400
    if year < 2000 or year > 2100:
        return jsonify({"error": "year out of range"}), 400
    return jsonify(_aggregate(year, month))


@reports_bp.route("/monthly/list", methods=["GET"])
@require_role("admin", "operator", "viewer")
def monthly_list():
    """Return last N months of report summaries for the archive table."""
    n = min(request.args.get("months", 12, type=int), 36)
    rows = _recent_months(n)
    return jsonify({"reports": rows, "count": len(rows)})


@reports_bp.route("/monthly/export.csv", methods=["GET"])
@require_role("admin", "operator")
def export_csv():
    """Download monthly report as CSV (UTF-8 BOM for Excel compatibility)."""
    now = datetime.now(timezone.utc)
    year = request.args.get("year", now.year, type=int)
    month = request.args.get("month", now.month, type=int)
    data = _aggregate(year, month)

    buf = io.StringIO()
    buf.write("﻿")  # BOM
    writer = csv.writer(buf)
    writer.writerow(["項目", "値"])
    writer.writerow(["対象月", data["period"]])
    writer.writerow(["総 PC 数", data["pc"]["total"]])
    writer.writerow(["オンライン PC", data["pc"]["online"]])
    writer.writerow(["オフライン PC", data["pc"]["offline"]])
    writer.writerow(["健全率 (%)", data["pc"]["health_rate"]])
    writer.writerow(["タスク総数", data["tasks"]["total"]])
    writer.writerow(["タスク完了", data["tasks"]["completed"]])
    writer.writerow(["タスク失敗", data["tasks"]["failed"]])
    writer.writerow(["タスク成功率 (%)", data["tasks"]["success_rate"]])
    writer.writerow(["アラート総数", data["alerts"]["total"]])
    writer.writerow(["Critical アラート", data["alerts"]["critical"]])
    writer.writerow(["High アラート", data["alerts"]["high"]])
    writer.writerow(["Medium アラート", data["alerts"]["medium"]])
    writer.writerow(["Low アラート", data["alerts"]["low"]])
    writer.writerow(["操作ログ件数", data["operations"]["total"]])
    writer.writerow(["SLA (%)", data["sla"]])

    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    resp.headers["Content-Disposition"] = (
        f"attachment; filename=monthly_report_{data['period']}.csv"
    )
    return resp


@reports_bp.route("/monthly/export.pdf", methods=["GET"])
@require_role("admin", "operator")
def export_pdf():
    """Download monthly report as PDF (Japanese IPA Gothic font)."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        return jsonify({"error": "reportlab not installed"}), 500

    now = datetime.now(timezone.utc)
    year = request.args.get("year", now.year, type=int)
    month = request.args.get("month", now.month, type=int)
    data = _aggregate(year, month)

    # Register Japanese font
    try:
        pdfmetrics.registerFont(TTFont("IPAGothic", _IPA_FONT))
        jp_font = "IPAGothic"
    except Exception:
        jp_font = "Helvetica"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    title_style = ParagraphStyle(
        "title_jp",
        fontName=jp_font,
        fontSize=16,
        spaceAfter=12,
        textColor=colors.HexColor("#1e40af"),
    )
    body_style = ParagraphStyle(
        "body_jp",
        fontName=jp_font,
        fontSize=10,
        spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "section_jp",
        fontName=jp_font,
        fontSize=12,
        spaceBefore=12,
        spaceAfter=6,
        textColor=colors.HexColor("#374151"),
    )

    story = []
    story.append(Paragraph(f"月次レポート — {data['period']}", title_style))
    story.append(
        Paragraph(
            f"作成日時: {now.strftime('%Y-%m-%d %H:%M')} UTC",
            body_style,
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    def kv_table(rows):
        tbl = Table(rows, colWidths=[8 * cm, 6 * cm])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e7ff")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                    ("FONTNAME", (0, 0), (-1, -1), jp_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f9fafb")],
                    ),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return tbl

    story.append(Paragraph("PC 稼働状況", section_style))
    story.append(
        kv_table(
            [
                ["項目", "値"],
                ["総 PC 数", str(data["pc"]["total"])],
                ["オンライン", str(data["pc"]["online"])],
                ["オフライン", str(data["pc"]["offline"])],
                ["健全率", f"{data['pc']['health_rate']}%"],
            ]
        )
    )

    story.append(Paragraph("タスク実行状況", section_style))
    story.append(
        kv_table(
            [
                ["項目", "値"],
                ["総タスク数", str(data["tasks"]["total"])],
                ["完了", str(data["tasks"]["completed"])],
                ["失敗", str(data["tasks"]["failed"])],
                ["成功率", f"{data['tasks']['success_rate']}%"],
            ]
        )
    )

    story.append(Paragraph("アラート状況", section_style))
    story.append(
        kv_table(
            [
                ["項目", "値"],
                ["総アラート数", str(data["alerts"]["total"])],
                ["Critical", str(data["alerts"]["critical"])],
                ["High", str(data["alerts"]["high"])],
                ["Medium", str(data["alerts"]["medium"])],
                ["Low", str(data["alerts"]["low"])],
            ]
        )
    )

    story.append(Paragraph("SLA・操作ログ", section_style))
    story.append(
        kv_table(
            [
                ["項目", "値"],
                ["SLA", f"{data['sla']}%"],
                ["操作ログ件数", str(data["operations"]["total"])],
            ]
        )
    )

    doc.build(story)

    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = (
        f"attachment; filename=monthly_report_{data['period']}.pdf"
    )
    return resp

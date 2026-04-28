"""Alert notification module: email (SMTP) and Slack webhook."""

import json
import logging
import os
import smtplib
import urllib.request
from email.mime.text import MIMEText
from email.utils import formatdate

logger = logging.getLogger(__name__)

# Severity levels that trigger a notification
_NOTIFY_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})


def _should_notify(alert) -> bool:
    return alert.severity in _NOTIFY_SEVERITIES


def send_email(alert) -> None:
    """Send an alert notification via SMTP.

    Reads configuration from environment variables:
      SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
      ALERT_EMAIL_FROM, ALERT_EMAIL_TO (comma-separated list).
    """
    smtp_host = os.environ.get("SMTP_HOST", "")
    if not smtp_host:
        return

    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    from_addr = os.environ.get("ALERT_EMAIL_FROM", smtp_user)
    to_addrs_raw = os.environ.get("ALERT_EMAIL_TO", "")
    to_addrs = [a.strip() for a in to_addrs_raw.split(",") if a.strip()]

    if not to_addrs:
        return

    subject = f"[PC-Ops] [{alert.severity.upper()}] {alert.alert_type}"
    body = (
        f"アラートが発生しました。\n\n"
        f"種別: {alert.alert_type}\n"
        f"重大度: {alert.severity}\n"
        f"対象PC ID: {alert.pc_id}\n"
        f"メッセージ: {alert.message}\n"
        f"発生時刻: {alert.created_at}\n"
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Date"] = formatdate(localtime=True)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
        server.starttls()
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.sendmail(from_addr, to_addrs, msg.as_string())

    logger.info("Alert email sent: %s", subject)


def send_slack(alert) -> None:
    """Send an alert notification via Slack Incoming Webhook.

    Reads SLACK_WEBHOOK_URL from environment variables.
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        return

    severity_emoji = {"critical": ":red_circle:", "high": ":orange_circle:"}.get(
        alert.severity, ":white_circle:"
    )
    text = (
        f"{severity_emoji} *[{alert.severity.upper()}] {alert.alert_type}*\n"
        f"PC ID: {alert.pc_id} | {alert.message}"
    )
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        if resp.status != 200:
            logger.warning("Slack notification returned HTTP %s", resp.status)
        else:
            logger.info("Slack notification sent for alert %s", alert.source_key)


def notify_alert(alert) -> None:
    """Dispatch notifications for a new alert (fire-and-forget, errors logged only).

    Only notifies for severity levels in _NOTIFY_SEVERITIES.
    """
    if not _should_notify(alert):
        return

    try:
        send_email(alert)
    except Exception:
        logger.exception("Failed to send alert email for %s", alert.source_key)

    try:
        send_slack(alert)
    except Exception:
        logger.exception("Failed to send Slack notification for %s", alert.source_key)

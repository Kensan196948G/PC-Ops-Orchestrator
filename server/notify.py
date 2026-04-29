"""Alert notification module.

Supports four channel types — slack / teams / email / generic_webhook.
Designed so that **payload assembly is a pure function** (easy to unit-test)
while the **HTTP / SMTP send paths** are isolated side-effects.
"""

import json
import logging
import os
import smtplib
import time
import urllib.error
import urllib.request
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import Any, Optional

logger = logging.getLogger(__name__)

CHANNEL_SLACK = "slack"
CHANNEL_TEAMS = "teams"
CHANNEL_EMAIL = "email"
CHANNEL_GENERIC = "generic_webhook"

ALLOWED_CHANNEL_TYPES: frozenset[str] = frozenset(
    {CHANNEL_SLACK, CHANNEL_TEAMS, CHANNEL_EMAIL, CHANNEL_GENERIC}
)

# Severity levels that trigger the auto-dispatcher (sync_alerts path).
_NOTIFY_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})

_DEFAULT_TIMEOUT = 5
_DEFAULT_RETRIES = 3
_RETRY_INTERVAL_SEC = 1.0


# ---------------------------------------------------------------------------
# Pure payload builders
# ---------------------------------------------------------------------------


def build_slack_payload(alert) -> dict[str, Any]:
    """Slack Incoming Webhook payload."""
    severity_emoji = {
        "critical": ":red_circle:",
        "high": ":orange_circle:",
        "medium": ":large_yellow_circle:",
        "warning": ":large_yellow_circle:",
    }.get(alert.severity, ":white_circle:")
    text = (
        f"{severity_emoji} *[{alert.severity.upper()}] {alert.alert_type}*\n"
        f"PC ID: {alert.pc_id} | {alert.message}"
    )
    return {"text": text}


def build_teams_payload(alert) -> dict[str, Any]:
    """Microsoft Teams MessageCard payload (legacy connector format)."""
    severity_color = {
        "critical": "FF0000",
        "high": "FFA500",
        "medium": "FFCC00",
        "warning": "FFCC00",
    }.get(alert.severity, "808080")
    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": severity_color,
        "summary": f"[{alert.severity.upper()}] {alert.alert_type}",
        "title": f"[{alert.severity.upper()}] {alert.alert_type}",
        "text": alert.message,
        "sections": [
            {
                "facts": [
                    {"name": "PC ID", "value": str(alert.pc_id)},
                    {"name": "Severity", "value": alert.severity},
                    {"name": "Source Key", "value": getattr(alert, "source_key", "-")},
                ],
            }
        ],
    }


def build_generic_payload(alert) -> dict[str, Any]:
    """Generic JSON payload usable by any webhook receiver."""
    payload: dict[str, Any] = {
        "id": getattr(alert, "id", None),
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "message": alert.message,
        "pc_id": alert.pc_id,
        "source_key": getattr(alert, "source_key", None),
    }
    created_at = getattr(alert, "created_at", None)
    if created_at is not None:
        try:
            payload["created_at"] = created_at.isoformat()
        except AttributeError:
            payload["created_at"] = str(created_at)
    return payload


def build_email_message(alert) -> tuple[str, str]:
    """Return (subject, body) for an email notification."""
    subject = f"[PC-Ops] [{alert.severity.upper()}] {alert.alert_type}"
    body = (
        f"アラートが発生しました。\n\n"
        f"種別: {alert.alert_type}\n"
        f"重大度: {alert.severity}\n"
        f"対象PC ID: {alert.pc_id}\n"
        f"メッセージ: {alert.message}\n"
        f"発生時刻: {alert.created_at}\n"
    )
    return subject, body


def build_payload_for_channel(channel_type: str, alert) -> Any:
    """Dispatch payload assembly based on channel type."""
    if channel_type == CHANNEL_SLACK:
        return build_slack_payload(alert)
    if channel_type == CHANNEL_TEAMS:
        return build_teams_payload(alert)
    if channel_type == CHANNEL_GENERIC:
        return build_generic_payload(alert)
    if channel_type == CHANNEL_EMAIL:
        return build_email_message(alert)
    raise ValueError(f"Unknown channel_type: {channel_type!r}")


# ---------------------------------------------------------------------------
# Side-effect senders
# ---------------------------------------------------------------------------


def send_webhook(
    url: str,
    payload: dict[str, Any],
    *,
    retries: int = _DEFAULT_RETRIES,
    timeout: int = _DEFAULT_TIMEOUT,
) -> bool:
    """POST a JSON payload to a webhook URL with retry.

    Returns True if any attempt succeeded with a 2xx status.
    """
    if not url:
        return False
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                if 200 <= resp.status < 300:
                    return True
                logger.warning(
                    "Webhook POST returned HTTP %s (attempt %d/%d)",
                    resp.status,
                    attempt,
                    retries,
                )
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            logger.warning(
                "Webhook POST failed (attempt %d/%d): %s", attempt, retries, exc
            )
        if attempt < retries:
            time.sleep(_RETRY_INTERVAL_SEC)
    if last_error is not None:
        logger.warning(
            "Webhook POST gave up after %d attempts: %s", retries, last_error
        )
    return False


def send_email_via_smtp(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    from_addr: str,
    to_addrs: list[str],
    subject: str,
    body: str,
    timeout: int = 10,
) -> bool:
    """Send a plain-text email via SMTP STARTTLS. Returns True on success."""
    if not host or not to_addrs:
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Date"] = formatdate(localtime=True)

    try:
        with smtplib.SMTP(host, port, timeout=timeout) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
        logger.info("Alert email sent: %s", subject)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("SMTP send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Backward-compatible high-level helpers (used by the existing sync path)
# ---------------------------------------------------------------------------


def send_email(alert, *, override_to_addrs: Optional[list[str]] = None) -> bool:
    """Send the default alert email using SMTP_* environment variables.

    ``override_to_addrs`` lets callers (e.g. ``dispatch_via_rule``) supply a
    rule-specific recipient list instead of falling back to ``ALERT_EMAIL_TO``.
    Returns False (rather than raising) when the SMTP_PORT env var is unparsable
    or when host/recipients are missing — keeps `/test-notify` from 500-ing on
    misconfigured environments.
    """
    smtp_host = os.environ.get("SMTP_HOST", "")
    if not smtp_host:
        return False
    try:
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError:
        logger.warning("SMTP_PORT is not a valid integer; skipping email notification")
        return False
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    from_addr = os.environ.get("ALERT_EMAIL_FROM", smtp_user)

    if override_to_addrs:
        to_addrs = [a.strip() for a in override_to_addrs if a and a.strip()]
    else:
        to_addrs_raw = os.environ.get("ALERT_EMAIL_TO", "")
        to_addrs = [a.strip() for a in to_addrs_raw.split(",") if a.strip()]
    if not to_addrs:
        return False

    subject, body = build_email_message(alert)
    return send_email_via_smtp(
        host=smtp_host,
        port=smtp_port,
        user=smtp_user,
        password=smtp_password,
        from_addr=from_addr,
        to_addrs=to_addrs,
        subject=subject,
        body=body,
    )


def _parse_email_targets(raw: Optional[str]) -> list[str]:
    """Parse a rule.notify_email value (comma/semicolon/whitespace) into addresses."""
    if not raw:
        return []
    # Allow ',', ';', whitespace as separators.
    pieces: list[str] = []
    for chunk in raw.replace(";", ",").split(","):
        for piece in chunk.split():
            cleaned = piece.strip()
            if cleaned:
                pieces.append(cleaned)
    return pieces


def send_slack(alert) -> bool:
    """Send via the global SLACK_WEBHOOK_URL env var if configured."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        return False
    return send_webhook(webhook_url, build_slack_payload(alert))


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


def _should_notify(alert) -> bool:
    return alert.severity in _NOTIFY_SEVERITIES


def notify_alert(alert) -> None:
    """Dispatch notifications for a new alert (fire-and-forget, errors logged only).

    Only notifies for severity levels in _NOTIFY_SEVERITIES.
    Honors environment-level fallbacks (SMTP_HOST / SLACK_WEBHOOK_URL).
    """
    if not _should_notify(alert):
        return

    try:
        send_email(alert)
    except Exception:
        logger.exception(
            "Failed to send alert email for %s",
            getattr(alert, "source_key", "?"),
        )

    try:
        send_slack(alert)
    except Exception:
        logger.exception(
            "Failed to send Slack notification for %s",
            getattr(alert, "source_key", "?"),
        )


def dispatch_via_rule(alert, rule) -> dict[str, bool]:
    """Send notifications for ``alert`` using the channel(s) in ``rule``.

    Returns a per-channel success map. Designed for /test-notify and for any
    future scheduler hooks that want explicit per-rule routing rather than
    the env-fallback path used by ``notify_alert``.
    """
    results: dict[str, bool] = {}
    if rule is None:
        return results

    channel_type = (getattr(rule, "channel_type", None) or "").strip() or None

    rule_email_targets = _parse_email_targets(getattr(rule, "notify_email", None))

    # If explicit channel_type set, honor it strictly.
    if channel_type:
        if channel_type == CHANNEL_SLACK and rule.notify_slack_webhook:
            results[CHANNEL_SLACK] = send_webhook(
                rule.notify_slack_webhook, build_slack_payload(alert)
            )
        elif channel_type == CHANNEL_TEAMS and rule.notify_teams_webhook:
            results[CHANNEL_TEAMS] = send_webhook(
                rule.notify_teams_webhook, build_teams_payload(alert)
            )
        elif channel_type == CHANNEL_GENERIC and rule.notify_webhook_url:
            results[CHANNEL_GENERIC] = send_webhook(
                rule.notify_webhook_url, build_generic_payload(alert)
            )
        elif channel_type == CHANNEL_EMAIL and rule_email_targets:
            results[CHANNEL_EMAIL] = send_email(
                alert, override_to_addrs=rule_email_targets
            )
        return results

    # Legacy path: send to whichever notify_* columns are populated.
    if rule.notify_slack_webhook:
        results[CHANNEL_SLACK] = send_webhook(
            rule.notify_slack_webhook, build_slack_payload(alert)
        )
    if rule.notify_teams_webhook:
        results[CHANNEL_TEAMS] = send_webhook(
            rule.notify_teams_webhook, build_teams_payload(alert)
        )
    if rule.notify_webhook_url:
        results[CHANNEL_GENERIC] = send_webhook(
            rule.notify_webhook_url, build_generic_payload(alert)
        )
    if rule_email_targets:
        results[CHANNEL_EMAIL] = send_email(alert, override_to_addrs=rule_email_targets)
    return results

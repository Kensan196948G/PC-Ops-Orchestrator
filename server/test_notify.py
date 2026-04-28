"""Tests for notify.py — alert notification dispatch."""

import json
import os
import unittest
import urllib.request
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from notify import notify_alert, send_email, send_slack


def _alert(severity="critical", resolved=False):
    return SimpleNamespace(
        id=1,
        pc_id=10,
        alert_type="pc_offline",
        severity=severity,
        message="PC-001 がオフラインです",
        source_key="pc_10_offline",
        created_at="2026-04-28T10:00:00+00:00",
        resolved=resolved,
    )


class TestSendEmail(unittest.TestCase):
    def test_no_smtp_host_skips(self):
        with patch.dict(os.environ, {}, clear=True):
            send_email(_alert())  # should not raise

    def test_no_recipients_skips(self):
        env = {"SMTP_HOST": "smtp.example.com", "ALERT_EMAIL_TO": ""}
        with patch.dict(os.environ, env, clear=True):
            send_email(_alert())  # should not raise

    def test_sends_with_valid_config(self):
        env = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "user@example.com",
            "SMTP_PASSWORD": "secret",
            "ALERT_EMAIL_FROM": "noreply@example.com",
            "ALERT_EMAIL_TO": "admin@example.com,ops@example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            mock_server = MagicMock()
            mock_smtp_cls = MagicMock(return_value=mock_server)
            mock_server.__enter__ = lambda s: mock_server
            mock_server.__exit__ = MagicMock(return_value=False)

            with patch("smtplib.SMTP", mock_smtp_cls):
                send_email(_alert())

            mock_smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=10)
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("user@example.com", "secret")
            assert mock_server.sendmail.call_count == 1
            positional = mock_server.sendmail.call_args[0]
            to_arg = positional[1]
            assert "admin@example.com" in to_arg
            assert "ops@example.com" in to_arg

    def test_subject_contains_severity_and_type(self):
        env = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "u",
            "SMTP_PASSWORD": "p",
            "ALERT_EMAIL_FROM": "from@x.com",
            "ALERT_EMAIL_TO": "to@x.com",
        }
        captured_msg = []

        def fake_sendmail(from_addr, to_addrs, msg_str):
            captured_msg.append(msg_str)

        with patch.dict(os.environ, env, clear=True):
            mock_server = MagicMock()
            mock_server.__enter__ = lambda s: mock_server
            mock_server.__exit__ = MagicMock(return_value=False)
            mock_server.sendmail.side_effect = fake_sendmail

            with patch("smtplib.SMTP", MagicMock(return_value=mock_server)):
                send_email(_alert(severity="high"))

        assert captured_msg, "sendmail was not called"
        assert "HIGH" in captured_msg[0]
        assert "pc_offline" in captured_msg[0]


class TestSendSlack(unittest.TestCase):
    def test_no_webhook_url_skips(self):
        with patch.dict(os.environ, {}, clear=True):
            send_slack(_alert())  # should not raise

    def test_posts_to_webhook(self):
        env = {"SLACK_WEBHOOK_URL": "https://hooks.slack.example.com/T00/B00/xxx"}
        with patch.dict(os.environ, env, clear=True):
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.status = 200

            captured_reqs = []

            def fake_req_cls(url, data, headers, method):
                req = MagicMock()
                req.data = data
                captured_reqs.append({"url": url, "data": data})
                return req

            with patch("urllib.request.urlopen", return_value=mock_resp):
                with patch("urllib.request.Request", fake_req_cls):
                    send_slack(_alert())

            assert captured_reqs, "Request was not called"
            assert (
                captured_reqs[0]["url"] == "https://hooks.slack.example.com/T00/B00/xxx"
            )
            payload = json.loads(captured_reqs[0]["data"].decode())
            assert "text" in payload
            assert "CRITICAL" in payload["text"]

    def test_slack_text_contains_severity_emoji(self):
        env = {"SLACK_WEBHOOK_URL": "https://hooks.slack.example.com/T00/B00/xxx"}
        with patch.dict(os.environ, env, clear=True):
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.status = 200

            payloads = []

            def fake_urlopen(req, timeout):
                payloads.append(json.loads(req.data.decode()))
                return mock_resp

            with patch("urllib.request.urlopen", fake_urlopen):
                with patch("urllib.request.Request", urllib.request.Request):
                    send_slack(_alert(severity="high"))

            assert payloads, "urlopen not called"
            assert ":orange_circle:" in payloads[0]["text"]


class TestNotifyAlert(unittest.TestCase):
    def test_notifies_critical(self):
        with (
            patch("notify.send_email") as m_email,
            patch("notify.send_slack") as m_slack,
        ):
            notify_alert(_alert(severity="critical"))
            m_email.assert_called_once()
            m_slack.assert_called_once()

    def test_notifies_high(self):
        with (
            patch("notify.send_email") as m_email,
            patch("notify.send_slack") as m_slack,
        ):
            notify_alert(_alert(severity="high"))
            m_email.assert_called_once()
            m_slack.assert_called_once()

    def test_skips_medium(self):
        with (
            patch("notify.send_email") as m_email,
            patch("notify.send_slack") as m_slack,
        ):
            notify_alert(_alert(severity="medium"))
            m_email.assert_not_called()
            m_slack.assert_not_called()

    def test_skips_low(self):
        with (
            patch("notify.send_email") as m_email,
            patch("notify.send_slack") as m_slack,
        ):
            notify_alert(_alert(severity="low"))
            m_email.assert_not_called()
            m_slack.assert_not_called()

    def test_email_failure_does_not_prevent_slack(self):
        with patch("notify.send_email", side_effect=Exception("SMTP error")):
            with patch("notify.send_slack") as m_slack:
                notify_alert(_alert(severity="critical"))  # must not raise
                m_slack.assert_called_once()

    def test_slack_failure_does_not_raise(self):
        with patch("notify.send_email"):
            with patch("notify.send_slack", side_effect=Exception("Slack error")):
                notify_alert(_alert(severity="critical"))  # must not raise


def run_all():
    print("\n=== test_notify.py ===")
    tests = [
        TestSendEmail("test_no_smtp_host_skips"),
        TestSendEmail("test_no_recipients_skips"),
        TestSendEmail("test_sends_with_valid_config"),
        TestSendEmail("test_subject_contains_severity_and_type"),
        TestSendSlack("test_no_webhook_url_skips"),
        TestSendSlack("test_posts_to_webhook"),
        TestSendSlack("test_slack_text_contains_severity_emoji"),
        TestNotifyAlert("test_notifies_critical"),
        TestNotifyAlert("test_notifies_high"),
        TestNotifyAlert("test_skips_medium"),
        TestNotifyAlert("test_skips_low"),
        TestNotifyAlert("test_email_failure_does_not_prevent_slack"),
        TestNotifyAlert("test_slack_failure_does_not_raise"),
    ]
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.TestSuite(tests)
    result = runner.run(suite)
    return result


if __name__ == "__main__":
    run_all()

"""
Pluggable alert notifier — stdlib only.

Sends alert notifications to external channels when configured via environment
variables, and is a no-op otherwise (so CI/tests never send):

  ALERT_WEBHOOK_URL   Slack-compatible incoming webhook; receives {"text": ...}
  ALERT_SMTP_HOST     SMTP server host (email disabled if unset)
  ALERT_SMTP_PORT     SMTP server port (default 25)
  ALERT_SMTP_USER     SMTP username (optional; enables login if set)
  ALERT_SMTP_PASSWORD SMTP password (optional)
  ALERT_EMAIL_FROM    From address (default alerts@priis.local)
  ALERT_EMAIL_TO      Comma-separated recipient list (email disabled if unset)

`send_alert` returns the list of channel names it delivered to, which makes the
behaviour easy to assert in tests without real network access.
"""
from __future__ import annotations

import json
import os
import smtplib
import urllib.request
from email.message import EmailMessage
from typing import Any, Callable, Dict, List, Optional

# Injectable transports so tests can capture payloads without real I/O.
WebhookTransport = Callable[[str, bytes], None]
EmailTransport = Callable[[EmailMessage], None]


def _default_webhook_transport(url: str, payload: bytes) -> None:
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=10)  # noqa: S310 — url comes from env config


def _default_email_transport(msg: EmailMessage) -> None:
    host = os.environ["ALERT_SMTP_HOST"]
    port = int(os.environ.get("ALERT_SMTP_PORT", "25"))
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        user = os.environ.get("ALERT_SMTP_USER")
        password = os.environ.get("ALERT_SMTP_PASSWORD")
        if user and password:
            smtp.starttls()
            smtp.login(user, password)
        smtp.send_message(msg)


def _format_text(alert: Dict[str, Any]) -> str:
    reg = alert.get("registration")
    prefix = f"[{alert.get('tier', '')}] " if alert.get("tier") else ""
    suffix = f" — {reg}" if reg else ""
    return f"{prefix}{alert.get('title', 'Alert')}{suffix}"


def send_alert(
    alert: Dict[str, Any],
    *,
    webhook_transport: Optional[WebhookTransport] = None,
    email_transport: Optional[EmailTransport] = None,
    env: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Deliver one alert to every configured channel. Returns channel names used."""
    env = env if env is not None else dict(os.environ)
    delivered: List[str] = []
    text = _format_text(alert)

    webhook_url = env.get("ALERT_WEBHOOK_URL")
    if webhook_url:
        payload = json.dumps({"text": text}).encode("utf-8")
        transport = webhook_transport or _default_webhook_transport
        try:
            transport(webhook_url, payload)
            delivered.append("webhook")
        except Exception as exc:  # noqa: BLE001 — notification must never break ingest
            print(f"  [notify] webhook failed: {exc}")

    email_to = env.get("ALERT_EMAIL_TO")
    if email_to and (env.get("ALERT_SMTP_HOST") or email_transport):
        msg = EmailMessage()
        msg["Subject"] = text
        msg["From"] = env.get("ALERT_EMAIL_FROM", "alerts@priis.local")
        msg["To"] = email_to
        msg.set_content(
            f"{text}\n\n"
            f"id: {alert.get('id', '')}\n"
            f"at: {alert.get('at', '')}\n"
            f"kind: {alert.get('kind', '')}\n"
        )
        transport = email_transport or _default_email_transport
        try:
            transport(msg)
            delivered.append("email")
        except Exception as exc:  # noqa: BLE001
            print(f"  [notify] email failed: {exc}")

    return delivered


def is_configured(env: Optional[Dict[str, str]] = None) -> bool:
    """True if any external notification channel is configured."""
    env = env if env is not None else dict(os.environ)
    return bool(env.get("ALERT_WEBHOOK_URL") or env.get("ALERT_EMAIL_TO"))

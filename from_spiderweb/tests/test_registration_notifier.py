"""External notifier: fake transports, and no-op when unconfigured."""

from email.message import EmailMessage

from server.notifications.notifier import is_configured, send_alert

ALERT = {
    "id": "REG-SEEN-N5854Z-2026-06-01",
    "at": "2026-06-01T12:00:00",
    "kind": "aircraft",
    "title": "Watchlisted aircraft N5854Z seen",
    "tier": "T3",
    "registration": "N5854Z",
}


def test_noop_when_unconfigured():
    assert is_configured({}) is False
    assert send_alert(ALERT, env={}) == []


def test_webhook_transport_invoked():
    captured = {}

    def fake_webhook(url, payload):
        captured["url"] = url
        captured["payload"] = payload

    channels = send_alert(
        ALERT,
        webhook_transport=fake_webhook,
        env={"ALERT_WEBHOOK_URL": "https://hooks.example/abc"},
    )
    assert channels == ["webhook"]
    assert captured["url"] == "https://hooks.example/abc"
    assert b"N5854Z" in captured["payload"]


def test_email_transport_invoked():
    sent = {}

    def fake_email(msg: EmailMessage):
        sent["subject"] = msg["Subject"]
        sent["to"] = msg["To"]

    channels = send_alert(
        ALERT,
        email_transport=fake_email,
        env={"ALERT_EMAIL_TO": "ops@example.com"},
    )
    assert channels == ["email"]
    assert "N5854Z" in sent["subject"]
    assert sent["to"] == "ops@example.com"


def test_both_channels():
    calls = []
    channels = send_alert(
        ALERT,
        webhook_transport=lambda u, p: calls.append("w"),
        email_transport=lambda m: calls.append("e"),
        env={"ALERT_WEBHOOK_URL": "https://x", "ALERT_EMAIL_TO": "a@b.c"},
    )
    assert set(channels) == {"webhook", "email"}
    assert set(calls) == {"w", "e"}

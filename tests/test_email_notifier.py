"""
邮件通知测试
"""
from email.message import EmailMessage

from config import NotificationConfig
from notification.email_notifier import EmailNotifier


class FakeSMTP:
    def __init__(self, host, port, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.logged_in = None
        self.messages: list[EmailMessage] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg: EmailMessage):
        self.messages.append(msg)


def test_email_notifier_sends_message_via_smtp_ssl(monkeypatch):
    fake = FakeSMTP("smtp.example.com", 465)
    monkeypatch.setattr("smtplib.SMTP_SSL", lambda host, port, timeout=10: fake)

    notifier = EmailNotifier(
        smtp_server="smtp.example.com",
        smtp_port=465,
        sender="sender@example.com",
        password="app-password",
        receiver="receiver@example.com",
    )
    notifier.notify("Test Subject", "Hello Apex")

    assert fake.logged_in == ("sender@example.com", "app-password")
    assert len(fake.messages) == 1
    msg = fake.messages[0]
    assert msg["Subject"] == "Test Subject"
    assert msg["From"] == "sender@example.com"
    assert msg["To"] == "receiver@example.com"
    assert "Hello Apex" in msg.get_content()


def test_email_notifier_from_config_returns_none_when_disabled():
    original = NotificationConfig.email_enabled
    NotificationConfig.email_enabled = False
    try:
        assert EmailNotifier.from_config() is None
    finally:
        NotificationConfig.email_enabled = original

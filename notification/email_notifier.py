"""
邮件通知模块
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from config import NotificationConfig


class Notifier(Protocol):
    def notify(self, subject: str, body: str) -> None:
        ...


class EmailNotifier:
    def __init__(
        self,
        smtp_server: str,
        smtp_port: int,
        sender: str,
        password: str,
        receiver: str,
    ):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender = sender
        self.password = password
        self.receiver = receiver

    @classmethod
    def from_config(cls) -> "EmailNotifier | None":
        if not NotificationConfig.email_enabled:
            return None
        required = [
            NotificationConfig.email_smtp_server,
            NotificationConfig.email_sender,
            NotificationConfig.email_password,
            NotificationConfig.email_receiver,
        ]
        if not all(required):
            raise ValueError("邮件通知已启用，但 notification.email 配置不完整")
        return cls(
            smtp_server=NotificationConfig.email_smtp_server,
            smtp_port=NotificationConfig.email_smtp_port,
            sender=NotificationConfig.email_sender,
            password=NotificationConfig.email_password,
            receiver=NotificationConfig.email_receiver,
        )

    def notify(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = self.receiver
        msg.set_content(body)

        if self.smtp_port == 465:
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=10) as smtp:
                smtp.login(self.sender, self.password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(self.sender, self.password)
                smtp.send_message(msg)

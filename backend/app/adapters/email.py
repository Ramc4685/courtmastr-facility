"""Email adapters: SMTP (Mailpit in development) and an in-memory outbox for tests."""

import logging
import re
import smtplib
from email.message import EmailMessage as MimeMessage

from app.core.settings import Email
from app.ports.email import EmailMessage

log = logging.getLogger(__name__)


class SmtpEmail:
    def __init__(self, cfg: Email) -> None:
        self.cfg = cfg

    def send(self, message: EmailMessage) -> None:
        mime = MimeMessage()
        mime["From"], mime["To"], mime["Subject"] = self.cfg.from_address, message.to, message.subject
        mime.set_content(message.body)
        with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=5) as smtp:
            smtp.send_message(mime)
        if self.cfg.log_links:  # development only: links are bearer credentials
            for link in re.findall(r"https?://\S+", message.body):
                log.info("emailed link: %s", link)


class MemoryEmail:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)

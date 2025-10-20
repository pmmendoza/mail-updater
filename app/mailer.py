"""Simple mail delivery helpers supporting dry-run output."""

from __future__ import annotations

import json
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

from .config import Settings
from .email_renderer import RenderedEmail


class MailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_outbox()

    def send(
        self,
        rendered: RenderedEmail,
        recipient: str,
        *,
        user_did: str,
        dry_run_override: Optional[bool] = None,
    ) -> None:
        dry_run = (
            self.settings.smtp_dry_run if dry_run_override is None else dry_run_override
        )
        message = self._build_message(rendered, recipient)
        if dry_run:
            self._write_eml(message, user_did)
            self._log_attempt(recipient, rendered.subject, user_did, "dry-run")
        else:
            self._deliver(message)
            self._log_attempt(recipient, rendered.subject, user_did, "sent")

    def _build_message(self, rendered: RenderedEmail, recipient: str) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = rendered.subject
        msg["From"] = self.settings.smtp_from
        msg["To"] = recipient
        if self.settings.smtp_reply_to:
            msg["Reply-To"] = self.settings.smtp_reply_to

        msg.set_content(rendered.text_body)
        if rendered.html_body:
            msg.add_alternative(rendered.html_body, subtype="html")
        return msg

    def _write_eml(self, message: EmailMessage, user_did: str) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = user_did.replace(":", "_")
        filename = f"{timestamp}_{slug}.eml"
        path = self.settings.outbox_dir / filename
        with path.open("w", encoding="utf-8") as handle:
            handle.write(message.as_string())

    def _deliver(self, message: EmailMessage) -> None:
        if self.settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                self.settings.smtp_host, self.settings.smtp_port
            ) as smtp:
                self._authenticate_if_needed(smtp)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                self._authenticate_if_needed(smtp)
                smtp.send_message(message)

    def _authenticate_if_needed(self, smtp: smtplib.SMTP) -> None:
        if self.settings.smtp_username and self.settings.smtp_password:
            smtp.login(self.settings.smtp_username, self.settings.smtp_password)

    def _log_attempt(
        self, recipient: str, subject: str, user_did: str, status: str
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_did": user_did,
            "recipient": recipient,
            "subject": subject,
            "status": status,
            "dry_run": status == "dry-run",
        }
        with self.settings.send_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

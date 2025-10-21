"""Simple mail delivery helpers supporting dry-run output."""

from __future__ import annotations

import json
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

from .config import Settings
from .email_renderer import RenderedEmail
from .mail_db.operations import (
    ParticipantNotFoundError,
    record_send_attempt,
    update_send_attempt,
)


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
        message_type: str = "generic",
        template_version: Optional[str] = None,
    ) -> None:
        dry_run = (
            self.settings.smtp_dry_run if dry_run_override is None else dry_run_override
        )
        mode = "dry-run" if dry_run else "live"
        message = self._build_message(rendered, recipient)
        attempt_id: Optional[int] = None
        try:
            attempt = record_send_attempt(
                self.settings.mail_db_path,
                user_did=user_did,
                message_type=message_type,
                mode=mode,
                status="queued",
                template_version=template_version,
            )
            attempt_id = attempt.attempt_id
        except ParticipantNotFoundError:
            attempt_id = None

        def _finalise(
            status: str,
            smtp_response: Optional[str] = None,
            *,
            log_status: Optional[str] = None,
        ) -> None:
            if attempt_id is not None:
                update_send_attempt(
                    self.settings.mail_db_path,
                    attempt_id=attempt_id,
                    status=status,
                    smtp_response=smtp_response,
                )
            self._log_attempt(
                recipient,
                rendered.subject,
                user_did,
                log_status or status,
            )

        if dry_run:
            eml_path = self._write_eml(message, user_did)
            _finalise(
                "sent",
                smtp_response=f"dry-run:{eml_path}",
                log_status="dry-run",
            )
            return

        try:
            response = self._deliver(message)
            smtp_response = "OK" if not response else str(response)
            _finalise("sent", smtp_response=smtp_response)
        except Exception as exc:  # pragma: no cover - network errors are rare
            _finalise("failed", smtp_response=str(exc))
            raise

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

    def _write_eml(self, message: EmailMessage, user_did: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = user_did.replace(":", "_")
        filename = f"{timestamp}_{slug}.eml"
        path = self.settings.outbox_dir / filename
        with path.open("w", encoding="utf-8") as handle:
            handle.write(message.as_string())
        return str(path)

    def _deliver(self, message: EmailMessage) -> Optional[dict[str, tuple[int, bytes]]]:
        if self.settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                self.settings.smtp_host, self.settings.smtp_port
            ) as smtp:
                self._authenticate_if_needed(smtp)
                return smtp.send_message(message)
        else:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                self._authenticate_if_needed(smtp)
                return smtp.send_message(message)

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

"""IMAP bounce processing helpers."""

from __future__ import annotations

import imaplib
import re
from dataclasses import dataclass
from email import message_from_bytes
from email.message import Message
from typing import List, Optional

from .config import Settings
from .mail_db.operations import (
    ParticipantNotFoundError,
    find_participant_by_email,
    mark_send_attempt_bounced,
)

FINAL_RECIPIENT_RE = re.compile(r"Final-Recipient:\s*rfc822;\s*([^\s]+)", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


@dataclass
class BounceOutcome:
    """Summary of a bounce scanning run."""

    messages_seen: int
    participants_updated: List[str]
    unmatched_recipients: List[str]


class BounceScannerError(RuntimeError):
    """Raised when bounce scanning cannot proceed."""


def _extract_recipients(message: Message) -> List[str]:
    recipients: List[str] = []

    for part in message.walk():
        payload = part.get_payload(decode=True)
        text = None
        if isinstance(payload, bytes):
            text = payload.decode(errors="ignore")
        elif isinstance(payload, str):
            text = payload
        if text:
            recipients.extend(FINAL_RECIPIENT_RE.findall(text))
    if not recipients:
        body = message.as_string()
        recipients.extend(FINAL_RECIPIENT_RE.findall(body))
        if not recipients:
            recipients.extend(EMAIL_RE.findall(body))

    # normalise lowercase unique
    return list({addr.strip().lower() for addr in recipients if "@" in addr})


def scan_bounces(
    settings: Settings,
    *,
    mark_seen: bool = True,
    imap_factory: Optional[type] = None,
) -> BounceOutcome:
    """Connect to the IMAP bounce mailbox and flag participants for suppression."""

    if (
        not settings.imap_host
        or not settings.imap_username
        or not settings.imap_password
    ):
        raise BounceScannerError(
            "IMAP settings missing (IMAP_HOST/IMAP_USERNAME/IMAP_PASSWORD)."
        )

    factory = imap_factory
    if factory is None:
        factory = imaplib.IMAP4_SSL if settings.imap_use_ssl else imaplib.IMAP4

    participants_updated: List[str] = []
    unmatched: List[str] = []
    messages_seen = 0

    connection = factory(settings.imap_host, settings.imap_port)
    try:
        connection.login(settings.imap_username, settings.imap_password)
        status, _ = connection.select(settings.imap_mailbox)
        if status != "OK":
            raise BounceScannerError(
                f"Unable to select mailbox {settings.imap_mailbox!r}"
            )

        status, data = connection.search(None, "UNSEEN")
        if status != "OK":
            raise BounceScannerError("IMAP search failed")

        ids = data[0].split()
        for msg_id in ids:
            fetch_status, payload = connection.fetch(msg_id, "(RFC822)")
            if fetch_status != "OK" or not payload:
                continue
            raw_message = payload[0][1]
            if not raw_message:
                continue
            messages_seen += 1
            message = message_from_bytes(raw_message)
            recipients = _extract_recipients(message)
            if not recipients:
                continue
            for recipient in recipients:
                mapping = find_participant_by_email(settings.mail_db_path, recipient)
                if not mapping:
                    unmatched.append(recipient)
                    continue
                participant_id, user_did = mapping
                try:
                    mark_send_attempt_bounced(
                        settings.mail_db_path,
                        user_did=user_did,
                        reason=f"bounced for {recipient}",
                        changed_by="bounce-scanner",
                    )
                    participants_updated.append(user_did)
                except ParticipantNotFoundError:
                    unmatched.append(recipient)

            if mark_seen:
                connection.store(msg_id, "+FLAGS", "(\\Seen)")
    finally:
        try:
            connection.close()
        except Exception:
            pass
        connection.logout()

    return BounceOutcome(
        messages_seen=messages_seen,
        participants_updated=participants_updated,
        unmatched_recipients=unmatched,
    )

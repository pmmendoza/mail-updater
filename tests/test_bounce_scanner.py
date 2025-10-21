from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from app.bounce_scanner import BounceScannerError, scan_bounces  # noqa: E402
from app.config import Settings  # noqa: E402
from app.mail_db.migrations import apply_migrations  # noqa: E402
from app.mail_db.operations import (  # noqa: E402
    get_mail_db_engine,
    record_send_attempt,
)
from app.mail_db.schema import participants, send_attempts  # noqa: E402


class FakeIMAP:
    def __init__(self, host, port, *, messages=None):
        self.host = host
        self.port = port
        self.messages = messages or {}
        self.logged_in = False
        self.selected = None
        self.flags = {}

    def login(self, username, password):
        if not username or not password:
            raise ValueError("missing creds")
        self.logged_in = True

    def select(self, mailbox):
        self.selected = mailbox
        return "OK", []

    def search(self, charset, criteria):
        ids = b" ".join(sorted(self.messages.keys()))
        return "OK", [ids]

    def fetch(self, msg_id, spec):
        payload = self.messages.get(msg_id)
        if payload is None:
            return "NO", []
        return "OK", [(msg_id, payload)]

    def store(self, msg_id, op, flags):
        self.flags[msg_id] = flags
        return "OK", []

    def close(self):
        return "OK", []

    def logout(self):
        self.logged_in = False


@pytest.fixture
def settings_with_imap(tmp_path):
    db_path = tmp_path / "mail.sqlite"
    csv_path = tmp_path / "participants.csv"
    apply_migrations(db_path)
    settings = Settings().with_overrides(
        mail_db_path=db_path,
        participants_csv_path=csv_path,
        imap_host="imap.example.com",
        imap_username="user",
        imap_password="pass",
        imap_mailbox="INBOX",
    )
    return settings


def _seed_participant_and_attempt(
    settings: Settings, *, email: str, user_did: str
) -> None:
    engine = get_mail_db_engine(settings.mail_db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert().values(
                user_did=user_did,
                email=email,
                status="active",
                type="pilot",
                language="en",
                feed_url="https://feeds.example.com/bounce",
            )
        )
    record_send_attempt(
        settings.mail_db_path,
        user_did=user_did,
        message_type="daily_update",
        mode="live",
        status="sent",
    )


def test_scan_bounces_marks_participant(settings_with_imap, monkeypatch):
    settings = settings_with_imap
    _seed_participant_and_attempt(
        settings, email="bounce@example.com", user_did="did:bounce"
    )

    msg = EmailMessage()
    msg["Subject"] = "Mail delivery failed"
    msg.set_content(
        "Final-Recipient: rfc822; bounce@example.com\nDiagnostic-Code: smtp; 550 Mailbox unavailable"
    )

    fake_imap = FakeIMAP(
        settings.imap_host,
        settings.imap_port,
        messages={b"1": msg.as_bytes()},
    )

    monkeypatch.setattr(
        "app.bounce_scanner.imaplib.IMAP4_SSL", lambda host, port: fake_imap
    )

    outcome = scan_bounces(settings)

    assert outcome.messages_seen == 1
    assert outcome.participants_updated == ["did:bounce"]
    engine = get_mail_db_engine(settings.mail_db_path)
    with engine.connect() as conn:
        status = conn.execute(
            send_attempts.select().with_only_columns(send_attempts.c.status)
        ).scalar_one()
        participant_status = conn.execute(
            participants.select().with_only_columns(participants.c.status)
        ).scalar_one()
    assert status == "failed"
    assert participant_status == "inactive"


def test_scan_bounces_requires_credentials(settings_with_imap):
    settings = settings_with_imap.with_overrides(imap_host=None)
    with pytest.raises(BounceScannerError):
        scan_bounces(settings)


def test_scan_bounces_unmatched(settings_with_imap, monkeypatch):
    settings = settings_with_imap
    msg = EmailMessage()
    msg.set_content("Final-Recipient: rfc822; unknown@example.com")
    fake_imap = FakeIMAP(
        settings.imap_host,
        settings.imap_port,
        messages={b"1": msg.as_bytes()},
    )
    monkeypatch.setattr(
        "app.bounce_scanner.imaplib.IMAP4_SSL", lambda host, port: fake_imap
    )
    outcome = scan_bounces(settings)
    assert outcome.unmatched_recipients == ["unknown@example.com"]

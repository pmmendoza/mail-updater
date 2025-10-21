from __future__ import annotations

from pathlib import Path
import json

from app.config import Settings
from app.mail_db.migrations import apply_migrations
from app.mail_db.operations import get_mail_db_engine
from app.mail_db.schema import participants, send_attempts
from app.mailer import MailSender
from app.email_renderer import RenderedEmail


def _make_settings(tmp_path: Path, mail_db_path: Path) -> Settings:
    outbox_dir = tmp_path / "outbox"
    send_log_path = outbox_dir / "send_log.jsonl"
    return Settings().with_overrides(
        outbox_dir=outbox_dir,
        send_log_path=send_log_path,
        mail_db_path=mail_db_path,
        smtp_dry_run=True,
    )


def test_mail_sender_records_send_attempt(tmp_path: Path) -> None:
    mail_db_path = tmp_path / "mail.sqlite"
    apply_migrations(mail_db_path)
    engine = get_mail_db_engine(mail_db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert().values(
                user_did="did:example:mailer",
                email="person@example.com",
                status="active",
                type="pilot",
                language="en",
            )
        )

    settings = _make_settings(tmp_path, mail_db_path)
    sender = MailSender(settings)

    rendered = RenderedEmail(subject="Test", text_body="Hello")
    sender.send(
        rendered,
        "recipient@example.com",
        user_did="did:example:mailer",
        message_type="daily_update",
        template_version="daily_progress_v1",
    )

    with engine.connect() as conn:
        rows = (
            conn.execute(
                send_attempts.select().where(
                    send_attempts.c.message_type == "daily_update"
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    attempt = rows[0]
    assert attempt["status"] == "sent"
    assert attempt["mode"] == "dry-run"
    assert attempt["template_version"] == "daily_progress_v1"
    assert attempt["smtp_response"].startswith("dry-run:")

    send_log_path = Path(settings.send_log_path)
    assert send_log_path.exists()
    lines = send_log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["status"] == "dry-run"
    assert record["dry_run"] is True
    assert record["user_did"] == "did:example:mailer"

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.mail_db.migrations import apply_migrations
from app.mail_db.operations import (
    InvalidStatusError,
    ParticipantNotFoundError,
    RosterUpsertResult,
    SendAttemptRecord,
    SendAttemptNotFoundError,
    StatusChangeResult,
    fetch_recent_send_attempts,
    get_mail_db_engine,
    list_participants,
    mark_send_attempt_bounced,
    record_send_attempt,
    set_participant_status,
    update_send_attempt,
    upsert_participants,
)
from app.mail_db.schema import participant_status_history, participants, send_attempts


def _seed_participant(
    db_path: Path,
    *,
    status: str = "active",
    email: str = "user@example.com",
    feed_url: str = "https://feeds.example.com/default",
) -> None:
    engine = get_mail_db_engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert().values(
                user_did="did:example:123",
                email=email,
                status=status,
                type="pilot",
                language="en",
                feed_url=feed_url,
            )
        )


def test_set_participant_status_updates_row_and_history(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path)

    result = set_participant_status(
        db_path,
        user_did="did:example:123",
        new_status="inactive",
        reason="manual hold",
        changed_by="ops@example.com",
    )

    assert isinstance(result, StatusChangeResult)
    assert result.changed is True
    assert result.old_status == "active"
    assert result.new_status == "inactive"
    assert result.reason == "manual hold"
    assert result.changed_by == "ops@example.com"

    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        updated_status = conn.execute(
            select(participants.c.status).where(
                participants.c.user_did == "did:example:123"
            )
        ).scalar_one()
        assert updated_status == "inactive"

        history_rows = conn.execute(
            select(
                participant_status_history.c.old_status,
                participant_status_history.c.new_status,
                participant_status_history.c.reason,
                participant_status_history.c.changed_by,
            )
        ).all()
        assert history_rows == [
            ("active", "inactive", "manual hold", "ops@example.com")
        ]


def test_set_participant_status_invalid_value(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path)

    with pytest.raises(InvalidStatusError):
        set_participant_status(
            db_path,
            user_did="did:example:123",
            new_status="paused",
        )


def test_set_participant_status_missing_participant(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)

    with pytest.raises(ParticipantNotFoundError):
        set_participant_status(
            db_path,
            user_did="did:example:missing",
            new_status="inactive",
        )


def test_set_participant_status_no_change_skips_history(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path, status="inactive")

    result = set_participant_status(
        db_path,
        user_did="did:example:123",
        new_status="inactive",
        reason="already inactive",
        changed_by="ops@example.com",
    )

    assert result.changed is False
    assert result.old_status == "inactive"
    assert result.new_status == "inactive"
    assert result.reason is None
    assert result.changed_by is None

    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        history_count = conn.execute(
            select(participant_status_history.c.history_id)
        ).fetchall()
        assert history_count == []


def test_upsert_participants_inserts_records(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)

    summary = upsert_participants(
        db_path,
        [
            {
                "did": "did:new",
                "email": "new@example.com",
                "status": "active",
                "type": "pilot",
                "feed_url": "https://feeds.example.com/new",
            },
            {
                "did": "did:second",
                "email": "second@example.com",
                "status": "inactive",
                "type": "admin",
                "feed_url": "https://feeds.example.com/second",
            },
        ],
    )

    assert isinstance(summary, RosterUpsertResult)
    assert summary.inserted == 2
    assert summary.updated == 0
    assert summary.total == 2

    roster = list_participants(db_path)
    roster_by_did = {row["did"]: row for row in roster}
    assert roster_by_did["did:new"]["status"] == "active"
    assert roster_by_did["did:second"]["status"] == "inactive"
    assert roster_by_did["did:new"].get("feed_url") == "https://feeds.example.com/new"


def test_upsert_participants_preserves_existing_status(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path, status="inactive")

    summary = upsert_participants(
        db_path,
        [
            {
                "did": "did:example:123",
                "email": "updated@example.com",
                "status": "active",  # should be ignored for existing participant
                "type": "prolific",
                "language": "nl",
                "feed_url": "https://feeds.example.com/updated",
            }
        ],
    )

    assert summary.inserted == 0
    assert summary.updated == 1
    assert summary.total == 1

    roster = list_participants(db_path)
    assert roster == [
        {
            "did": "did:example:123",
            "email": "updated@example.com",
            "status": "inactive",
            "type": "prolific",
            "language": "nl",
            "feed_url": "https://feeds.example.com/updated",
        }
    ]


def test_record_and_update_send_attempt(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path, status="inactive")

    record = record_send_attempt(
        db_path,
        user_did="did:example:123",
        message_type="daily_update",
        mode="dry-run",
        status="queued",
        template_version="daily_progress_v1",
        smtp_response="dry-run:/tmp/example.eml",
    )

    assert isinstance(record, SendAttemptRecord)
    assert record.status == "queued"

    update_send_attempt(
        db_path,
        attempt_id=record.attempt_id,
        status="sent",
        smtp_response="OK",
    )

    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                send_attempts.c.status,
                send_attempts.c.mode,
                send_attempts.c.template_version,
                send_attempts.c.smtp_response,
            )
        ).all()
        assert rows == [("sent", "dry-run", "daily_progress_v1", "OK")]


def test_update_send_attempt_missing_id_raises(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)

    with pytest.raises(SendAttemptNotFoundError):
        update_send_attempt(
            db_path,
            attempt_id=999,
            status="failed",
            smtp_response="error",
        )


def test_fetch_recent_send_attempts(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path)

    ids = []
    for idx in range(3):
        record = record_send_attempt(
            db_path,
            user_did="did:example:123",
            message_type="daily_update",
            mode="dry-run",
            status="queued",
            template_version=f"v{idx}",
        )
        ids.append(record.attempt_id)

    engine = get_mail_db_engine(db_path)
    base = datetime(2025, 10, 20, 10, 0, 0)
    with engine.begin() as conn:
        for offset, attempt_id in enumerate(ids):
            conn.execute(
                update(send_attempts)
                .where(send_attempts.c.attempt_id == attempt_id)
                .values(created_at=base + timedelta(days=offset))
            )

    attempts = fetch_recent_send_attempts(db_path, limit=2)
    assert len(attempts) == 2
    assert attempts[0]["template_version"] == "v2"
    assert attempts[1]["template_version"] == "v1"


def test_mark_send_attempt_bounced_updates_status_and_participant(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path, status="active")

    record = record_send_attempt(
        db_path,
        user_did="did:example:123",
        message_type="daily_update",
        mode="live",
        status="sent",
    )

    mark_send_attempt_bounced(
        db_path,
        user_did="did:example:123",
        reason="550 mailbox unavailable",
        changed_by="bounce-bot",
    )

    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        attempt_row = conn.execute(
            select(send_attempts.c.status, send_attempts.c.smtp_response).where(
                send_attempts.c.attempt_id == record.attempt_id
            )
        ).one()
        assert attempt_row.status == "failed"
        assert attempt_row.smtp_response == "550 mailbox unavailable"

        participant_row = conn.execute(
            select(participants.c.status).where(
                participants.c.user_did == "did:example:123"
            )
        ).one()
        assert participant_row.status == "inactive"

        history = conn.execute(
            select(
                participant_status_history.c.new_status,
                participant_status_history.c.reason,
            )
        ).all()
        assert ("inactive", "550 mailbox unavailable") in history

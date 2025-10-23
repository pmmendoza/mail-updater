import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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
    export_participants_to_csv,
    seed_survey_completion,
    upsert_compliance_monitoring_rows,
    fetch_recent_send_attempts,
    get_mail_db_engine,
    list_participants,
    mark_send_attempt_bounced,
    record_send_attempt,
    set_participant_status,
    update_send_attempt,
    upsert_participants,
)
from app.mail_db.schema import (
    compliance_monitoring,
    participant_status_history,
    participants,
    send_attempts,
)


def _seed_participant(
    db_path: Path,
    *,
    status: str = "active",
    email: str = "user@example.com",
    feed_url: str = "https://feeds.example.com/default",
    prolific_id: Optional[str] = None,
    study_type: Optional[str] = None,
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
                prolific_id=prolific_id,
                study_type=study_type,
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
                "prolific_id": "123",
                "study_type": "pilot",
            },
            {
                "did": "did:second",
                "email": "second@example.com",
                "status": "inactive",
                "type": "admin",
                "feed_url": "https://feeds.example.com/second",
                "study_type": "admin",
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
    assert roster_by_did["did:new"].get("prolific_id") == "123"
    assert roster_by_did["did:second"].get("study_type") == "admin"


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
    assert len(roster) == 1
    single = roster[0]
    assert single["did"] == "did:example:123"
    assert single["email"] == "updated@example.com"
    assert single["status"] == "inactive"
    assert single["type"] == "prolific"
    assert single["language"] == "nl"
    assert single["feed_url"] == "https://feeds.example.com/updated"
    assert single["survey_completed_at"] == ""
    assert single["prolific_id"] == ""
    assert single["study_type"] == ""


def test_export_participants_to_csv_appends_new_rows(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert().values(
                user_did="did:alpha",
                email="alpha@example.com",
                status="active",
                type="pilot",
                language="en",
                feed_url="https://feeds.example.com/alpha",
            )
        )
        conn.execute(
            participants.insert().values(
                user_did="did:beta",
                email="beta@example.com",
                status="active",
                type="prolific",
                language="en",
                feed_url="https://feeds.example.com/beta",
                prolific_id="999",
            )
        )

    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url,survey_completed_at,prolific_id,study_type,audit_timestamp\n"
        "alpha@example.com,did:alpha,active,pilot,https://feeds.example.com/alpha,,,,\n",
        encoding="utf-8",
    )

    export_participants_to_csv(db_path, csv_path)

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert len(rows) == 2
    appended = {row["did"]: row for row in rows}
    assert appended["did:alpha"]["audit_timestamp"] == ""
    beta_row = appended["did:beta"]
    assert beta_row["email"] == "beta@example.com"
    assert beta_row["prolific_id"] == "999"
    assert beta_row["audit_timestamp"].strip()

    # second export should not duplicate rows
    export_participants_to_csv(db_path, csv_path)
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows_again = list(reader)

    assert len(rows_again) == 2


def test_seed_survey_completion_updates_selected_types(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert(),
            [
                {
                    "user_did": "did:admin",
                    "email": "admin@example.com",
                    "status": "active",
                    "type": "admin",
                    "language": "en",
                },
                {
                    "user_did": "did:test",
                    "email": "test@example.com",
                    "status": "active",
                    "type": "test",
                    "language": "en",
                },
                {
                    "user_did": "did:pilot",
                    "email": "pilot@example.com",
                    "status": "active",
                    "type": "pilot",
                    "language": "en",
                },
            ],
        )

    timestamp = datetime(2025, 10, 1, 9, 0, tzinfo=timezone.utc)
    updated = seed_survey_completion(
        db_path,
        participant_types=["admin", "test"],
        completed_at=timestamp,
    )

    assert set(updated) == {"did:admin", "did:test"}

    with engine.connect() as conn:
        rows = conn.execute(
            select(
                participants.c.user_did,
                participants.c.survey_completed_at,
            )
        ).mappings()
        data = {row["user_did"]: row["survey_completed_at"] for row in rows}

    assert data["did:admin"] is not None
    assert data["did:test"] is not None
    assert data["did:pilot"] is None

    second_run = seed_survey_completion(
        db_path,
        participant_types=["admin", "test"],
        completed_at=timestamp,
    )
    assert second_run == []


def test_upsert_compliance_monitoring_rows(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)

    first_rows = [
        {
            "snapshot_date": datetime(2025, 10, 1).date(),
            "user_did": "did:one",
            "study_label": "pilot",
            "retrievals": 2,
            "engagements": 3,
            "engagement_breakdown": {"like": 2, "reply": 1},
            "active_day": 1,
            "cumulative_active": 1,
            "cumulative_skip": 0,
            "computed_at": datetime(2025, 10, 2, tzinfo=timezone.utc),
        },
        {
            "snapshot_date": datetime(2025, 10, 2).date(),
            "user_did": "did:one",
            "study_label": "pilot",
            "retrievals": 0,
            "engagements": 0,
            "engagement_breakdown": {},
            "active_day": 0,
            "cumulative_active": 1,
            "cumulative_skip": 1,
            "computed_at": datetime(2025, 10, 2, tzinfo=timezone.utc),
        },
    ]

    inserted = upsert_compliance_monitoring_rows(db_path, first_rows)
    assert inserted == 2

    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        stored = conn.execute(
            select(
                compliance_monitoring.c.snapshot_date,
                compliance_monitoring.c.user_did,
                compliance_monitoring.c.retrievals,
                compliance_monitoring.c.engagements,
            ).order_by(compliance_monitoring.c.snapshot_date)
        ).all()

    assert stored[0].retrievals == 2
    assert stored[1].engagements == 0

    updated_rows = [
        {
            "snapshot_date": datetime(2025, 10, 1).date(),
            "user_did": "did:one",
            "study_label": "pilot",
            "retrievals": 3,
            "engagements": 4,
            "engagement_breakdown": {"like": 3, "reply": 1},
            "active_day": 1,
            "cumulative_active": 1,
            "cumulative_skip": 0,
            "computed_at": datetime(2025, 10, 3, tzinfo=timezone.utc),
        }
    ]

    inserted_again = upsert_compliance_monitoring_rows(db_path, updated_rows)
    assert inserted_again == 1

    with engine.connect() as conn:
        refreshed = conn.execute(
            select(
                compliance_monitoring.c.retrievals,
                compliance_monitoring.c.engagements,
                compliance_monitoring.c.engagement_breakdown,
            ).where(
                compliance_monitoring.c.user_did == "did:one",
                compliance_monitoring.c.snapshot_date == datetime(2025, 10, 1).date(),
            )
        ).mappings().first()

    assert refreshed["retrievals"] == 3
    assert refreshed["engagements"] == 4
    assert refreshed["engagement_breakdown"] == '{"like": 3, "reply": 1}'


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

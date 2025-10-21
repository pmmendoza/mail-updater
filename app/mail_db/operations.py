"""Operational helpers for interacting with the mail.db SQLite store."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple
import csv

from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import Engine, Row
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import func

from .migrations import apply_migrations
from .schema import participant_status_history, participants, send_attempts

ALLOWED_STATUSES = {"active", "inactive", "unsubscribed"}
DEFAULT_STATUS = "active"
DEFAULT_TYPE = "pilot"
DEFAULT_LANGUAGE = "en"


class InvalidStatusError(ValueError):
    """Raised when an unsupported participant status is provided."""


class ParticipantNotFoundError(LookupError):
    """Raised when a participant entry cannot be found in mail.db."""


class SendAttemptNotFoundError(LookupError):
    """Raised when a send attempt entry cannot be found in mail.db."""


@lru_cache(maxsize=None)
def get_mail_db_engine(db_path: Path) -> Engine:
    """Return a cached SQLAlchemy engine for the mail.db path."""
    normalized = Path(db_path)
    return create_engine(f"sqlite:///{normalized}", future=True)


@dataclass(frozen=True)
class StatusChangeResult:
    """Result metadata describing a participant status update."""

    user_did: str
    old_status: str
    new_status: str
    reason: Optional[str]
    changed_by: Optional[str]
    changed: bool


def _normalize_status(value: str) -> str:
    return value.strip().lower()


@dataclass(frozen=True)
class RosterUpsertResult:
    """Summary of participant roster upsert operations."""

    inserted: int
    updated: int
    total: int


@dataclass(frozen=True)
class SendAttemptRecord:
    """Metadata describing a recorded send attempt."""

    attempt_id: int
    participant_id: int
    status: str


def list_participants(db_path: Path) -> List[dict[str, str]]:
    """Return the current participant roster as dictionaries."""

    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        rows = conn.execute(select(participants)).mappings().all()

    roster: List[dict[str, str]] = []
    for row in rows:
        roster.append(
            {
                "did": row["user_did"],
                "email": row.get("email", ""),
                "status": row.get("status", DEFAULT_STATUS),
                "type": row.get("type", DEFAULT_TYPE),
                "language": row.get("language", DEFAULT_LANGUAGE),
            }
        )

    roster.sort(key=lambda item: (item["email"], item["did"]))
    return roster


def find_participant_by_email(db_path: Path, email: str) -> Optional[Tuple[int, str]]:
    """Return participant_id and user_did for the given email address."""

    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)
    normalized = email.strip().lower()
    with engine.connect() as conn:
        row = conn.execute(
            select(
                participants.c.participant_id,
                participants.c.user_did,
                participants.c.email,
            )
            .where(func.lower(participants.c.email) == normalized)
            .limit(1)
        ).first()
    if row is None:
        return None
    return row.participant_id, row.user_did


def export_participants_to_csv(db_path: Path, csv_path: Path) -> None:
    """Write the participants roster from mail.db to a CSV file."""

    rows = list_participants(db_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["email", "did", "status", "type"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "email": row.get("email", ""),
                    "did": row.get("did", ""),
                    "status": row.get("status", DEFAULT_STATUS),
                    "type": row.get("type", DEFAULT_TYPE),
                }
            )


def upsert_participants(
    db_path: Path, records: Iterable[dict[str, str]]
) -> RosterUpsertResult:
    """Upsert participant records, preserving manual status overrides."""

    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)

    inserted = 0
    updated = 0

    record_list = [record for record in records if record.get("did")]
    if not record_list:
        with engine.connect() as conn:
            total = conn.execute(
                select(func.count()).select_from(participants)
            ).scalar()
        return RosterUpsertResult(inserted=0, updated=0, total=total or 0)

    with engine.begin() as conn:
        existing_rows = conn.execute(select(participants)).mappings().all()
        existing_map = {row["user_did"]: row for row in existing_rows}

        for record in record_list:
            user_did = record.get("did", "").strip()
            if not user_did:
                continue

            new_email = (record.get("email") or "").strip()
            new_type = (record.get("type") or DEFAULT_TYPE).strip() or DEFAULT_TYPE
            new_language = (
                record.get("language") or DEFAULT_LANGUAGE
            ).strip() or DEFAULT_LANGUAGE
            status_value = (
                record.get("status") or DEFAULT_STATUS
            ).strip() or DEFAULT_STATUS

            existing = existing_map.get(user_did)
            if existing:
                update_values: dict[str, Any] = {}

                if new_email and new_email != (existing.get("email") or ""):
                    update_values["email"] = new_email

                if new_type and new_type != (existing.get("type") or DEFAULT_TYPE):
                    update_values["type"] = new_type

                if new_language and new_language != (
                    existing.get("language") or DEFAULT_LANGUAGE
                ):
                    update_values["language"] = new_language

                if update_values:
                    update_values["updated_at"] = func.now()
                    conn.execute(
                        update(participants)
                        .where(
                            participants.c.participant_id == existing["participant_id"]
                        )
                        .values(**update_values)
                    )
                    updated += 1
            else:
                if not new_email:
                    continue
                conn.execute(
                    participants.insert().values(
                        user_did=user_did,
                        email=new_email,
                        status=status_value,
                        type=new_type,
                        language=new_language,
                    )
                )
                inserted += 1

        total = conn.execute(select(func.count()).select_from(participants)).scalar()

    return RosterUpsertResult(inserted=inserted, updated=updated, total=total or 0)


def record_send_attempt(
    db_path: Path,
    *,
    user_did: str,
    message_type: str,
    mode: str,
    status: str,
    template_version: Optional[str] = None,
    smtp_response: Optional[str] = None,
) -> SendAttemptRecord:
    """Insert a new row into send_attempts for the given participant."""

    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)

    with engine.begin() as conn:
        participant_row = conn.execute(
            select(participants.c.participant_id, participants.c.status).where(
                participants.c.user_did == user_did
            )
        ).first()
        if participant_row is None:
            raise ParticipantNotFoundError(
                f"Participant with DID {user_did!r} not found in mail.db"
            )

        result = conn.execute(
            send_attempts.insert().values(
                participant_id=participant_row.participant_id,
                message_type=message_type,
                mode=mode,
                status=status,
                smtp_response=smtp_response,
                template_version=template_version,
            )
        )
        attempt_id = result.inserted_primary_key[0]

    return SendAttemptRecord(
        attempt_id=attempt_id,
        participant_id=participant_row.participant_id,
        status=status,
    )


def update_send_attempt(
    db_path: Path,
    *,
    attempt_id: int,
    status: str,
    smtp_response: Optional[str] = None,
) -> None:
    """Update the status/response of an existing send attempt."""

    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)

    with engine.begin() as conn:
        result = conn.execute(
            update(send_attempts)
            .where(send_attempts.c.attempt_id == attempt_id)
            .values(status=status, smtp_response=smtp_response)
        )
        if result.rowcount == 0:
            raise SendAttemptNotFoundError(
                f"Send attempt with id {attempt_id} not found in mail.db"
            )


def fetch_recent_send_attempts(
    db_path: Path,
    *,
    limit: int = 20,
    user_did: Optional[str] = None,
    message_type: Optional[str] = None,
) -> List[dict[str, Any]]:
    """Return recent send attempts ordered by newest first."""

    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)

    stmt = (
        select(
            send_attempts.c.attempt_id,
            participants.c.user_did,
            send_attempts.c.message_type,
            send_attempts.c.mode,
            send_attempts.c.status,
            send_attempts.c.smtp_response,
            send_attempts.c.template_version,
            send_attempts.c.created_at,
        )
        .join(
            participants,
            send_attempts.c.participant_id == participants.c.participant_id,
        )
        .order_by(send_attempts.c.created_at.desc(), send_attempts.c.attempt_id.desc())
        .limit(limit)
    )

    if user_did:
        stmt = stmt.where(participants.c.user_did == user_did)
    if message_type:
        stmt = stmt.where(send_attempts.c.message_type == message_type)

    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()

    return [dict(row) for row in rows]


def mark_send_attempt_bounced(
    db_path: Path,
    *,
    user_did: str,
    reason: Optional[str] = None,
    changed_by: Optional[str] = None,
) -> None:
    """Mark the latest send attempt as bounced and set participant inactive."""

    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)

    latest_attempt_id: Optional[int] = None

    with engine.begin() as conn:
        participant_row = conn.execute(
            select(participants.c.participant_id, participants.c.status).where(
                participants.c.user_did == user_did
            )
        ).first()
        if participant_row is None:
            raise ParticipantNotFoundError(
                f"Participant with DID {user_did!r} not found in mail.db"
            )

        attempt_row = conn.execute(
            select(send_attempts.c.attempt_id)
            .where(send_attempts.c.participant_id == participant_row.participant_id)
            .order_by(
                send_attempts.c.created_at.desc(), send_attempts.c.attempt_id.desc()
            )
            .limit(1)
        ).first()

        if attempt_row is not None:
            conn.execute(
                update(send_attempts)
                .where(send_attempts.c.attempt_id == attempt_row.attempt_id)
                .values(
                    status="failed",
                    smtp_response=reason or "bounced",
                )
            )
            latest_attempt_id = attempt_row.attempt_id

    # Ensure participant marked inactive (captures history)
    set_participant_status(
        db_path,
        user_did=user_did,
        new_status="inactive",
        reason=reason or "hard bounce",
        changed_by=changed_by or "bounce-handler",
    )

    if latest_attempt_id is None:
        raise SendAttemptNotFoundError(
            f"No send attempts found for participant {user_did!r}"
        )


def set_participant_status(
    db_path: Path,
    *,
    user_did: str,
    new_status: str,
    reason: Optional[str] = None,
    changed_by: Optional[str] = None,
) -> StatusChangeResult:
    """Update a participant status and append an audit trail entry.

    The mail.db schema will be migrated automatically prior to the update.
    """

    normalized_status = _normalize_status(new_status)
    if normalized_status not in ALLOWED_STATUSES:
        raise InvalidStatusError(
            f"Unsupported status {normalized_status!r}. "
            f"Expected one of: {', '.join(sorted(ALLOWED_STATUSES))}."
        )

    # Ensure schema exists; idempotent if already current.
    apply_migrations(db_path)

    engine = get_mail_db_engine(db_path)
    reason_text = reason.strip() if reason else None
    changed_by_text = changed_by.strip() if changed_by else None

    try:
        with engine.begin() as conn:
            row: Optional[Row] = conn.execute(
                select(
                    participants.c.participant_id,
                    participants.c.status,
                    participants.c.user_did,
                ).where(participants.c.user_did == user_did)
            ).first()
            if row is None:
                raise ParticipantNotFoundError(
                    f"Participant with DID {user_did!r} not found in mail.db"
                )

            old_status: str = row.status
            participant_id = row.participant_id

            if old_status == normalized_status:
                return StatusChangeResult(
                    user_did=user_did,
                    old_status=old_status,
                    new_status=normalized_status,
                    reason=None,
                    changed_by=None,
                    changed=False,
                )

            conn.execute(
                update(participants)
                .where(participants.c.participant_id == participant_id)
                .values(status=normalized_status, updated_at=func.now())
            )
            conn.execute(
                participant_status_history.insert().values(
                    participant_id=participant_id,
                    old_status=old_status,
                    new_status=normalized_status,
                    reason=reason_text,
                    changed_by=changed_by_text,
                )
            )
    except SQLAlchemyError as exc:  # pragma: no cover - defensive logging hook
        raise RuntimeError("Failed to update participant status") from exc

    return StatusChangeResult(
        user_did=user_did,
        old_status=old_status,
        new_status=normalized_status,
        reason=reason_text,
        changed_by=changed_by_text,
        changed=True,
    )


__all__ = [
    "ALLOWED_STATUSES",
    "DEFAULT_STATUS",
    "DEFAULT_TYPE",
    "DEFAULT_LANGUAGE",
    "InvalidStatusError",
    "ParticipantNotFoundError",
    "SendAttemptNotFoundError",
    "StatusChangeResult",
    "RosterUpsertResult",
    "SendAttemptRecord",
    "get_mail_db_engine",
    "list_participants",
    "find_participant_by_email",
    "export_participants_to_csv",
    "set_participant_status",
    "upsert_participants",
    "record_send_attempt",
    "update_send_attempt",
    "fetch_recent_send_attempts",
    "mark_send_attempt_bounced",
]

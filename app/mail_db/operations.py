"""Operational helpers for interacting with the mail.db SQLite store."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

from dateutil import parser as date_parser

from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import Engine, Row
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.sql import func

from .migrations import apply_migrations
from .schema import (
    compliance_monitoring,
    participant_status_history,
    participants,
    send_attempts,
)

ALLOWED_STATUSES = {"active", "inactive", "unsubscribed"}
DEFAULT_STATUS = "active"
DEFAULT_TYPE = "pilot"
DEFAULT_LANGUAGE = "en"
CSV_FIELDNAMES = [
    "email",
    "did",
    "status",
    "type",
    "feed_url",
    "survey_completed_at",
    "prolific_id",
    "study_type",
    "audit_timestamp",
]


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


def seed_survey_completion(
    db_path: Path, *, participant_types: Iterable[str], completed_at: datetime
) -> List[str]:
    """Populate survey_completed_at for participants of selected types.

    Returns the list of participant DIDs that were updated.
    """

    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)
    normalized_types = [
        value.strip()
        for value in participant_types
        if value and value.strip()
    ]
    if not normalized_types:
        return []

    completed_ts = completed_at.astimezone(timezone.utc)

    with engine.begin() as conn:
        target_dids = conn.execute(
            select(participants.c.user_did)
            .where(participants.c.type.in_(normalized_types))
            .where(participants.c.survey_completed_at.is_(None))
        ).scalars().all()

        if not target_dids:
            return []

        conn.execute(
            update(participants)
            .where(participants.c.type.in_(normalized_types))
            .where(participants.c.survey_completed_at.is_(None))
            .values(
                survey_completed_at=completed_ts,
                updated_at=func.now(),
            )
        )

    return target_dids


def upsert_compliance_monitoring_rows(
    db_path: Path, rows: Iterable[dict[str, Any]]
) -> int:
    """Upsert compliance monitoring cache rows into mail.db."""

    records: List[dict[str, Any]] = []
    for row in rows:
        breakdown = row.get("engagement_breakdown", {})
        if isinstance(breakdown, str):
            breakdown_json = breakdown
        else:
            breakdown_json = json.dumps(breakdown, sort_keys=True)

        records.append(
            {
                "snapshot_date": row["snapshot_date"],
                "user_did": row["user_did"],
                "study_label": row["study_label"],
                "retrievals": int(row.get("retrievals", 0)),
                "engagements": int(row.get("engagements", 0)),
                "engagement_breakdown": breakdown_json,
                "active_day": int(bool(row.get("active_day"))),
                "cumulative_active": int(row.get("cumulative_active", 0)),
                "cumulative_skip": int(row.get("cumulative_skip", 0)),
                "computed_at": row.get("computed_at", datetime.now(timezone.utc)),
            }
        )

    if not records:
        return 0

    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)

    stmt = sqlite_insert(compliance_monitoring).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            compliance_monitoring.c.snapshot_date,
            compliance_monitoring.c.user_did,
            compliance_monitoring.c.study_label,
        ],
        set_={
            "retrievals": stmt.excluded.retrievals,
            "engagements": stmt.excluded.engagements,
            "engagement_breakdown": stmt.excluded.engagement_breakdown,
            "active_day": stmt.excluded.active_day,
            "cumulative_active": stmt.excluded.cumulative_active,
            "cumulative_skip": stmt.excluded.cumulative_skip,
            "computed_at": stmt.excluded.computed_at,
        },
    )

    with engine.begin() as conn:
        conn.execute(stmt)

    return len(records)


def list_participants(db_path: Path) -> List[dict[str, str]]:
    """Return the current participant roster as dictionaries."""

    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        rows = conn.execute(select(participants)).mappings().all()

    roster: List[dict[str, str]] = []
    for row in rows:
        completed_value = row.get("survey_completed_at")
        if isinstance(completed_value, str):
            completed_iso = completed_value.strip()
        elif completed_value is not None:
            completed_iso = completed_value.astimezone(timezone.utc).isoformat()
        else:
            completed_iso = ""

        roster.append(
            {
                "did": row["user_did"],
                "email": row.get("email", ""),
                "status": row.get("status", DEFAULT_STATUS),
                "type": row.get("type", DEFAULT_TYPE),
                "language": row.get("language", DEFAULT_LANGUAGE),
                "feed_url": row.get("feed_url", ""),
                "survey_completed_at": completed_iso,
                "prolific_id": row.get("prolific_id") or "",
                "study_type": row.get("study_type") or "",
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
    """Append new participants from mail.db to the audit CSV without rewriting history."""

    rows = list_participants(db_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    existing_fieldnames: List[str] = []
    existing_rows: List[dict[str, str]] = []
    existing_dids: set[str] = set()

    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            existing_fieldnames = list(reader.fieldnames or [])
            for row in reader:
                record = {key: value for key, value in row.items()}
                existing_rows.append(record)
                did = (record.get("did") or "").strip()
                if did:
                    existing_dids.add(did)

    if not existing_fieldnames:
        existing_fieldnames = list(CSV_FIELDNAMES)

    missing_fields = [field for field in CSV_FIELDNAMES if field not in existing_fieldnames]
    if missing_fields or not csv_path.exists():
        for field in missing_fields:
            existing_fieldnames.append(field)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=existing_fieldnames,
                extrasaction="ignore",
            )
            writer.writeheader()
            for row in existing_rows:
                sanitized = {field: row.get(field, "") for field in existing_fieldnames}
                writer.writerow(sanitized)

    new_records: List[dict[str, str]] = []
    for row in rows:
        did = (row.get("did") or "").strip()
        if not did or did in existing_dids:
            continue
        record = {
            "email": row.get("email", ""),
            "did": did,
            "status": row.get("status", DEFAULT_STATUS),
            "type": row.get("type", DEFAULT_TYPE),
            "feed_url": row.get("feed_url", ""),
            "survey_completed_at": row.get("survey_completed_at", ""),
            "prolific_id": row.get("prolific_id", ""),
            "study_type": row.get("study_type", ""),
            "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        new_records.append(record)
        existing_dids.add(did)

    if not new_records:
        return

    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=existing_fieldnames,
            extrasaction="ignore",
        )
        for record in new_records:
            sanitized = {field: record.get(field, "") for field in existing_fieldnames}
            writer.writerow(sanitized)


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
            new_feed_url = (record.get("feed_url") or "").strip()
            new_prolific_id = (record.get("prolific_id") or "").strip()
            new_study_type = (record.get("study_type") or "").strip()
            completed_raw = (record.get("survey_completed_at") or "").strip()
            completed_dt: Optional[datetime] = None
            if completed_raw:
                try:
                    parsed_dt = date_parser.parse(completed_raw)
                    if not parsed_dt.tzinfo:
                        parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                    completed_dt = parsed_dt.astimezone(timezone.utc)
                except (ValueError, TypeError):
                    completed_dt = None

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

                if new_feed_url and new_feed_url != (existing.get("feed_url") or ""):
                    update_values["feed_url"] = new_feed_url

                if new_prolific_id and new_prolific_id != (
                    existing.get("prolific_id") or ""
                ):
                    update_values["prolific_id"] = new_prolific_id

                if new_study_type and new_study_type != (
                    existing.get("study_type") or ""
                ):
                    update_values["study_type"] = new_study_type

                if completed_dt and not existing.get("survey_completed_at"):
                    update_values["survey_completed_at"] = completed_dt

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
                        feed_url=new_feed_url or None,
                        prolific_id=new_prolific_id or None,
                        study_type=new_study_type or None,
                        survey_completed_at=completed_dt,
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

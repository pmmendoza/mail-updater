"""SQLAlchemy schema definitions for the mail.db SQLite database."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

metadata = MetaData()

SCHEMA_VERSION = 3

participants = Table(
    "participants",
    metadata,
    Column("participant_id", Integer, primary_key=True, autoincrement=True),
    Column("user_did", String, nullable=False, unique=True),
    Column("email", String, nullable=False),
    Column("type", String, nullable=False, server_default=text("'pilot'")),
    Column("status", String, nullable=False, server_default=text("'active'")),
    Column("language", String, nullable=False, server_default=text("'en'")),
    Column("feed_url", String),
    Column("survey_completed_at", DateTime),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
)
Index("idx_participants_status", participants.c.status)

participant_status_history = Table(
    "participant_status_history",
    metadata,
    Column("history_id", Integer, primary_key=True, autoincrement=True),
    Column(
        "participant_id",
        Integer,
        ForeignKey("participants.participant_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("old_status", String),
    Column("new_status", String),
    Column("reason", Text),
    Column("changed_by", String),
    Column("changed_at", DateTime, nullable=False, server_default=func.now()),
)

daily_snapshots = Table(
    "daily_snapshots",
    metadata,
    Column("snapshot_id", Integer, primary_key=True, autoincrement=True),
    Column(
        "participant_id",
        Integer,
        ForeignKey("participants.participant_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("study_day", Date, nullable=False),
    Column("retrievals", Integer, nullable=False, server_default=text("0")),
    Column("engagements", Integer, nullable=False, server_default=text("0")),
    Column("active_day", Integer, nullable=False, server_default=text("0")),
    Column("cumulative_active", Integer, nullable=False, server_default=text("0")),
    Column("on_track", Integer, nullable=False, server_default=text("0")),
    Column("computed_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint(
        "participant_id",
        "study_day",
        name="uq_daily_snapshots_participant_day",
    ),
)
Index("idx_daily_snapshots_day", daily_snapshots.c.study_day)

send_attempts = Table(
    "send_attempts",
    metadata,
    Column("attempt_id", Integer, primary_key=True, autoincrement=True),
    Column(
        "participant_id",
        Integer,
        ForeignKey("participants.participant_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("message_type", String, nullable=False),
    Column("mode", String, nullable=False),
    Column("status", String, nullable=False),
    Column("smtp_response", Text),
    Column("template_version", String),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)
Index("idx_send_attempts_status", send_attempts.c.status)

metadata_table = Table(
    "metadata",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String, nullable=False),
)

ALL_TABLES = (
    participants,
    participant_status_history,
    daily_snapshots,
    send_attempts,
    metadata_table,
)

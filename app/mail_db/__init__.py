"""Helpers and metadata for the mail.db schema."""

from .migrations import apply_migrations
from .schema import (
    SCHEMA_VERSION,
    ALL_TABLES,
    metadata,
    daily_snapshots,
    metadata_table,
    participant_status_history,
    participants,
    send_attempts,
)

__all__ = [
    "SCHEMA_VERSION",
    "ALL_TABLES",
    "metadata",
    "participants",
    "participant_status_history",
    "daily_snapshots",
    "send_attempts",
    "metadata_table",
    "apply_migrations",
]

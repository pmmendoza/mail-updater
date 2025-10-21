"""Migration helpers for the mail.db schema."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from .schema import SCHEMA_VERSION, metadata, metadata_table


MigrationFn = Callable[[Connection], None]


def _migration_001(conn: Connection) -> None:
    """Initial migration creating all tables in the schema."""
    metadata.create_all(conn)


def _migration_002(conn: Connection) -> None:
    """Add feed_url column to participants table."""
    existing_cols = {
        row[1]
        for row in conn.exec_driver_sql("PRAGMA table_info(participants)").fetchall()
    }
    if "feed_url" not in existing_cols:
        conn.execute(text("ALTER TABLE participants ADD COLUMN feed_url TEXT"))


MIGRATIONS: Dict[int, MigrationFn] = {
    1: _migration_001,
    2: _migration_002,
}


def _get_current_version(conn: Connection) -> int:
    """Return the applied schema version for the open connection."""
    inspector = inspect(conn)
    if metadata_table.name not in inspector.get_table_names():
        return 0

    result = conn.execute(
        select(metadata_table.c.value).where(metadata_table.c.key == "schema_version")
    ).scalar_one_or_none()
    if result is None:
        return 0
    try:
        return int(result)
    except ValueError as exc:
        raise RuntimeError("Invalid schema_version value in metadata table") from exc


def _set_version(conn: Connection, version: int) -> None:
    """Persist the schema version using an upsert on the metadata table."""
    stmt = sqlite_insert(metadata_table).values(
        key="schema_version", value=str(version)
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[metadata_table.c.key],
        set_={"value": str(version)},
    )
    conn.execute(stmt)


def apply_migrations(db_path: Path) -> int:
    """Apply pending migrations for mail.db and return the current schema version."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        current_version = _get_current_version(conn)
        if current_version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {current_version} is newer than "
                f"supported version {SCHEMA_VERSION}."
            )
        for version in range(current_version + 1, SCHEMA_VERSION + 1):
            migration = MIGRATIONS.get(version)
            if migration is None:
                raise RuntimeError(f"No migration registered for version {version}.")
            migration(conn)
            _set_version(conn, version)
        return SCHEMA_VERSION

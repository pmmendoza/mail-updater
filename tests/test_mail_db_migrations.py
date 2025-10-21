"""Tests for the mail.db migration helpers."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.mail_db import SCHEMA_VERSION, apply_migrations


def test_apply_migrations_creates_schema(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"

    version = apply_migrations(db_path)
    assert version == SCHEMA_VERSION

    engine = create_engine(f"sqlite:///{db_path}", future=True)
    with engine.connect() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        expected_tables = {
            "participants",
            "participant_status_history",
            "daily_snapshots",
            "send_attempts",
            "metadata",
        }
        assert expected_tables <= tables

        participant_columns = {
            column["name"] for column in inspector.get_columns("participants")
        }
        assert {
            "participant_id",
            "user_did",
            "email",
            "status",
            "type",
            "language",
            "created_at",
            "updated_at",
        } <= participant_columns

        schema_version = conn.execute(
            text("SELECT value FROM metadata WHERE key = 'schema_version'")
        ).scalar_one()
        assert schema_version == str(SCHEMA_VERSION)


def test_apply_migrations_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    second_run = apply_migrations(db_path)
    assert second_run == SCHEMA_VERSION

#!/usr/bin/env python3
"""Generate a small compliance.db fixture for local MVP testing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    fixture_dir = root / "data" / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixture_dir / "compliance_fixture.db"

    if fixture_path.exists():
        fixture_path.unlink()

    conn = sqlite3.connect(fixture_path)
    try:
        conn.executescript(
            """
            CREATE TABLE feed_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                requester_did TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE TABLE engagements (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                did_engagement TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            """
        )

        base = datetime(2025, 1, 1, 9, tzinfo=timezone.utc)
        active_days = (0, 2, 4, 6)
        inactive_days = (1, 3, 5)

        for offset in active_days:
            ts = base + timedelta(days=offset)
            conn.execute(
                "INSERT INTO feed_requests (requester_did, timestamp) VALUES (?, ?)",
                ("did:ontrack", _iso(ts)),
            )
            for _ in range(3):
                conn.execute(
                    "INSERT INTO engagements (did_engagement, timestamp) VALUES (?, ?)",
                    ("did:ontrack", _iso(ts + timedelta(minutes=5))),
                )

        for offset in inactive_days:
            ts = base + timedelta(days=offset)
            conn.execute(
                "INSERT INTO feed_requests (requester_did, timestamp) VALUES (?, ?)",
                ("did:offtrack", _iso(ts)),
            )
            conn.execute(
                "INSERT INTO engagements (did_engagement, timestamp) VALUES (?, ?)",
                ("did:offtrack", _iso(ts + timedelta(minutes=5))),
            )

        admin_did = "did:plc:3vomhawgkjhtvw4euuxbll3r"
        admin_ts = base + timedelta(days=1)
        conn.execute(
            "INSERT INTO feed_requests (requester_did, timestamp) VALUES (?, ?)",
            (admin_did, _iso(admin_ts)),
        )
        for _ in range(3):
            conn.execute(
                "INSERT INTO engagements (did_engagement, timestamp) VALUES (?, ?)",
                (admin_did, _iso(admin_ts + timedelta(minutes=10))),
            )

        conn.commit()
    finally:
        conn.close()

    print(f"Wrote fixture database to {fixture_path}")


if __name__ == "__main__":
    main()

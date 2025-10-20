from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.compliance_snapshot import compute_window_summary  # noqa: E402
from app.config import Settings  # noqa: E402


def _make_engine():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE feed_requests (
                    requester_did TEXT,
                    timestamp TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE engagements (
                    did_engagement TEXT,
                    timestamp TEXT
                )
                """
            )
        )
    return engine


def _insert_activity(
    engine, *, did: str, day_offset: int, retrievals: int, engagements: int
) -> None:
    base = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    with engine.begin() as conn:
        for _ in range(retrievals):
            ts = base + timedelta(days=day_offset)
            conn.execute(
                text(
                    "INSERT INTO feed_requests (requester_did, timestamp) VALUES (:did, :ts)"
                ),
                {"did": did, "ts": ts.isoformat()},
            )
        for _ in range(engagements):
            ts = base + timedelta(days=day_offset, minutes=5)
            conn.execute(
                text(
                    "INSERT INTO engagements (did_engagement, timestamp) VALUES (:did, :ts)"
                ),
                {"did": did, "ts": ts.isoformat()},
            )


def test_compute_window_summary_on_track() -> None:
    engine = _make_engine()
    did = "did:ontrack"
    _insert_activity(engine, did=did, day_offset=0, retrievals=1, engagements=3)
    _insert_activity(engine, did=did, day_offset=2, retrievals=1, engagements=3)
    _insert_activity(engine, did=did, day_offset=3, retrievals=1, engagements=3)

    settings = Settings().with_overrides(
        tz="UTC",
        window_days=4,
        required_active_days=3,
        cutoff_hour_local=0,
    )
    now = datetime(2025, 1, 4, 18, 0, tzinfo=timezone.utc)

    summary = compute_window_summary(engine, did, settings, now=now)
    assert summary is not None
    assert summary.active_days == 3
    assert summary.on_track is True
    assert summary.snapshots[-1].active_day is True


def test_compute_window_summary_off_track() -> None:
    engine = _make_engine()
    did = "did:offtrack"
    _insert_activity(engine, did=did, day_offset=0, retrievals=1, engagements=3)

    settings = Settings().with_overrides(
        tz="UTC",
        window_days=4,
        required_active_days=3,
        cutoff_hour_local=0,
    )
    now = datetime(2025, 1, 4, 18, 0, tzinfo=timezone.utc)

    summary = compute_window_summary(engine, did, settings, now=now)
    assert summary is not None
    assert summary.active_days == 1
    assert summary.on_track is False


def test_compute_window_summary_returns_none_when_no_activity() -> None:
    engine = _make_engine()
    did = "did:none"

    settings = Settings().with_overrides(
        tz="UTC",
        window_days=3,
        required_active_days=2,
        cutoff_hour_local=0,
    )
    now = datetime(2025, 1, 3, 18, 0, tzinfo=timezone.utc)

    summary = compute_window_summary(engine, did, settings, now=now)
    assert summary is None

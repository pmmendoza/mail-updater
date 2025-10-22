"""Compliance snapshot calculation for the mail updater MVP."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence

from dateutil import parser as date_parser
import pytz
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .config import Settings


@dataclass
class DailySnapshot:
    study_day: date
    retrievals: int
    engagements: int
    active_day: bool
    cumulative_active: int
    on_track: bool
    engagement_breakdown: Dict[str, int] = field(default_factory=dict)


@dataclass
class WindowSummary:
    user_did: str
    snapshots: List[DailySnapshot]
    active_days: int
    required_active_days: int
    window_days: int
    on_track: bool
    computed_at: datetime


def compute_window_summary(
    engine: Engine, user_did: str, settings: Settings, now: Optional[datetime] = None
) -> Optional[WindowSummary]:
    """Compute the rolling window summary for a participant."""
    tz = pytz.timezone(settings.tz)
    now = now or datetime.now(timezone.utc)
    now_local = now.astimezone(tz)
    current_study_day = _study_day_for_local(now_local, settings.cutoff_hour_local)

    first_request_ts = _fetch_single_timestamp(
        engine,
        "SELECT MIN(timestamp) FROM feed_requests WHERE requester_did = :did",
        user_did,
    )
    if first_request_ts is None:
        return None

    first_study_day = _study_day_for_utc(
        first_request_ts, tz, settings.cutoff_hour_local
    )
    window_start_day = max(
        first_study_day, current_study_day - timedelta(days=settings.window_days - 1)
    )

    # Query bounds inclusive of start day and exclusive of the day after current day.
    window_start_ts = _study_day_start(window_start_day, tz, settings.cutoff_hour_local)
    window_end_ts = _study_day_start(
        current_study_day + timedelta(days=1), tz, settings.cutoff_hour_local
    )

    feed_timestamps = _fetch_timestamps(
        engine,
        """
        SELECT timestamp FROM feed_requests
        WHERE requester_did = :did AND timestamp >= :start AND timestamp < :end
        """,
        user_did,
        window_start_ts,
        window_end_ts,
    )
    engagement_records = _fetch_engagement_records(
        engine,
        user_did,
        window_start_ts,
        window_end_ts,
    )

    day_range = _generate_day_range(window_start_day, current_study_day)
    retrieval_counts = _aggregate_counts(
        day_range, feed_timestamps, tz, settings.cutoff_hour_local
    )
    engagement_counts, engagement_breakdowns = _aggregate_engagement_counts(
        day_range, engagement_records, tz, settings.cutoff_hour_local
    )

    snapshots = _build_snapshots(
        day_range,
        retrieval_counts,
        engagement_counts,
        engagement_breakdowns,
        settings.window_days,
        settings.required_active_days,
    )

    if not snapshots:
        return None

    active_days_total = snapshots[-1].cumulative_active
    on_track = snapshots[-1].on_track
    return WindowSummary(
        user_did=user_did,
        snapshots=snapshots,
        active_days=active_days_total,
        required_active_days=settings.required_active_days,
        window_days=settings.window_days,
        on_track=on_track,
        computed_at=now.astimezone(timezone.utc),
    )


def _fetch_single_timestamp(
    engine: Engine, query: str, user_did: str
) -> Optional[datetime]:
    with engine.connect() as conn:
        result = conn.execute(text(query), {"did": user_did})
        value = result.scalar()
    if value is None:
        return None
    return _parse_timestamp(value)


def _fetch_timestamps(
    engine: Engine, query: str, user_did: str, start: datetime, end: datetime
) -> List[datetime]:
    start_iso = start.astimezone(timezone.utc).isoformat()
    end_iso = end.astimezone(timezone.utc).isoformat()
    with engine.connect() as conn:
        rows = conn.execute(
            text(query),
            {"did": user_did, "start": start_iso, "end": end_iso},
        )
        values = [row[0] for row in rows if row[0] is not None]
    return [_parse_timestamp(value) for value in values]


def _fetch_engagement_records(
    engine: Engine, user_did: str, start: datetime, end: datetime
) -> List[tuple[datetime, str]]:
    start_iso = start.astimezone(timezone.utc).isoformat()
    end_iso = end.astimezone(timezone.utc).isoformat()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT timestamp, engagement_type FROM engagements
                WHERE did_engagement = :did
                  AND timestamp >= :start AND timestamp < :end
                """
            ),
            {"did": user_did, "start": start_iso, "end": end_iso},
        )
        values = [
            (row[0], row[1])
            for row in rows
            if row[0] is not None and row[1] is not None
        ]
    return [(_parse_timestamp(ts), str(et)) for ts, et in values]


def _parse_timestamp(value: str) -> datetime:
    dt = date_parser.isoparse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _study_day_for_utc(dt: datetime, tz, cutoff_hour: int) -> date:
    local_dt = dt.astimezone(tz)
    return _study_day_for_local(local_dt, cutoff_hour)


def _study_day_for_local(local_dt: datetime, cutoff_hour: int) -> date:
    cutoff = time(hour=cutoff_hour)
    day = local_dt.date()
    if local_dt.timetz().replace(tzinfo=None) < cutoff:
        day -= timedelta(days=1)
    return day


def _study_day_start(day: date, tz, cutoff_hour: int) -> datetime:
    """Return the UTC datetime representing the start of the study day."""
    local_start = datetime.combine(day, time(hour=cutoff_hour), tzinfo=tz)
    return local_start.astimezone(timezone.utc)


def _generate_day_range(start_day: date, end_day: date) -> List[date]:
    days = []
    current = start_day
    while current <= end_day:
        days.append(current)
        current += timedelta(days=1)
    return days


def _aggregate_counts(
    day_range: Sequence[date],
    timestamps: Iterable[datetime],
    tz,
    cutoff_hour: int,
) -> Dict[date, int]:
    counts: Dict[date, int] = defaultdict(int)
    for ts in timestamps:
        day = _study_day_for_utc(ts, tz, cutoff_hour)
        if day in day_range:
            counts[day] += 1
    # Ensure keys exist for all days.
    for day in day_range:
        counts.setdefault(day, 0)
    return counts


def _aggregate_engagement_counts(
    day_range: Sequence[date],
    records: Iterable[tuple[datetime, str]],
    tz,
    cutoff_hour: int,
) -> tuple[Dict[date, int], Dict[date, Dict[str, int]]]:
    total_counts: Dict[date, int] = defaultdict(int)
    breakdown: Dict[date, Dict[str, int]] = {day: defaultdict(int) for day in day_range}

    for ts, engagement_type in records:
        day = _study_day_for_utc(ts, tz, cutoff_hour)
        if day not in breakdown:
            continue
        total_counts[day] += 1
        breakdown[day][engagement_type] += 1

    for day in day_range:
        total_counts.setdefault(day, 0)
        # Convert defaultdict to regular dict
        breakdown[day] = dict(breakdown[day])

    return total_counts, breakdown


def get_daily_engagement_breakdown(
    engine: Engine,
    user_did: str,
    settings: Settings,
    *,
    start_day: Optional[date] = None,
    end_day: Optional[date] = None,
    now: Optional[datetime] = None,
) -> List[DailySnapshot]:
    """Return per-day retrieval and engagement breakdown for a participant."""

    tz = pytz.timezone(settings.tz)
    now = now or datetime.now(timezone.utc)
    now_local = now.astimezone(tz)
    default_end_day = _study_day_for_local(now_local, settings.cutoff_hour_local)
    end_day = end_day or default_end_day
    start_day = start_day or (end_day - timedelta(days=settings.window_days - 1))

    if start_day > end_day:
        raise ValueError("start_day must be on or before end_day")

    window_start_ts = _study_day_start(start_day, tz, settings.cutoff_hour_local)
    window_end_ts = _study_day_start(
        end_day + timedelta(days=1), tz, settings.cutoff_hour_local
    )

    retrieval_timestamps = _fetch_timestamps(
        engine,
        """
        SELECT timestamp FROM feed_requests
        WHERE requester_did = :did AND timestamp >= :start AND timestamp < :end
        """,
        user_did,
        window_start_ts,
        window_end_ts,
    )
    engagement_records = _fetch_engagement_records(
        engine,
        user_did,
        window_start_ts,
        window_end_ts,
    )

    day_range = _generate_day_range(start_day, end_day)
    retrieval_counts = _aggregate_counts(
        day_range, retrieval_timestamps, tz, settings.cutoff_hour_local
    )
    engagement_counts, engagement_breakdowns = _aggregate_engagement_counts(
        day_range, engagement_records, tz, settings.cutoff_hour_local
    )

    snapshots = _build_snapshots(
        day_range,
        retrieval_counts,
        engagement_counts,
        engagement_breakdowns,
        settings.window_days,
        settings.required_active_days,
    )
    return snapshots


def _build_snapshots(
    day_range: Sequence[date],
    retrieval_counts: Dict[date, int],
    engagement_counts: Dict[date, int],
    engagement_breakdowns: Dict[date, Dict[str, int]],
    window_days: int,
    required_active_days: int,
) -> List[DailySnapshot]:
    snapshots: List[DailySnapshot] = []
    cumulative_active = 0
    for index, day in enumerate(day_range):
        retrievals = retrieval_counts.get(day, 0)
        engagements = engagement_counts.get(day, 0)
        active = retrievals >= 1 and engagements >= 3
        if active:
            cumulative_active += 1
        days_passed = index + 1
        remaining = max(window_days - days_passed, 0)
        potential = cumulative_active + remaining
        if not active:
            potential += 1  # current day can still become active before cutoff
        on_track = potential >= required_active_days
        snapshots.append(
            DailySnapshot(
                study_day=day,
                retrievals=retrievals,
                engagements=engagements,
                active_day=active,
                cumulative_active=cumulative_active,
                on_track=on_track,
                engagement_breakdown=engagement_breakdowns.get(day, {}),
            )
        )
    return snapshots

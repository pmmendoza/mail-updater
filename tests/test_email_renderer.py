from __future__ import annotations

from datetime import date, datetime, timezone

from app.compliance_snapshot import DailySnapshot, WindowSummary
from app.email_renderer import render_daily_progress
from app.participants import Participant


def _build_summary(retrievals: int, engagements: int, active: bool) -> WindowSummary:
    snapshot = DailySnapshot(
        study_day=date(2025, 10, 20),
        retrievals=retrievals,
        engagements=engagements,
        active_day=active,
        cumulative_active=1 if active else 0,
        on_track=active,
    )
    return WindowSummary(
        user_did="did:example:123",
        snapshots=[snapshot],
        active_days=snapshot.cumulative_active,
        required_active_days=10,
        window_days=14,
        on_track=active,
        computed_at=datetime(2025, 10, 21, 9, 0, tzinfo=timezone.utc),
    )


def test_render_daily_progress_default_template(tmp_path, monkeypatch):
    summary = _build_summary(retrievals=2, engagements=4, active=True)
    participant = Participant(user_did="did:example:123", email="user@example.com")
    email = render_daily_progress(summary, participant, subject="Test Subject")
    assert "Daily Progress Update" in email.text_body
    assert "Action Needed" not in email.text_body


def test_render_daily_progress_non_compliant_template(tmp_path, monkeypatch):
    summary = _build_summary(retrievals=0, engagements=0, active=False)
    participant = Participant(user_did="did:example:123", email="user@example.com")
    email = render_daily_progress(summary, participant, subject="Test Subject")
    assert "Action Needed" in email.text_body
    assert "We did not detect any feed retrievals" in email.text_body

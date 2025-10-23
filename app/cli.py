"""CLI entry point for the mail updater MVP."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
import csv

import click
from sqlalchemy import text
from dateutil import parser as date_parser

from .config import Settings
from .compliance_snapshot import (
    WindowSummary,
    compute_window_summary,
    get_daily_engagement_breakdown,
)
from .db import get_engine
from .email_renderer import render_daily_progress
from .bounce_scanner import BounceScannerError, scan_bounces
from .mail_db import apply_migrations
from .mail_db.operations import (
    ALLOWED_STATUSES,
    DEFAULT_STATUS,
    DEFAULT_TYPE,
    InvalidStatusError,
    ParticipantNotFoundError,
    export_participants_to_csv,
    fetch_recent_send_attempts,
    find_participant_by_email,
    seed_survey_completion,
    list_participants,
    set_participant_status,
    upsert_compliance_monitoring_rows,
    upsert_participants,
)
from .mailer import MailSender
from .participants import Participant, filter_active, load_participants
from .qualtrics_sync import QualtricsSyncError, sync_participants_from_qualtrics

DEFAULT_STATUS_CHANGED_BY = "mail-updater-cli"


def _load_settings() -> Settings:
    return Settings()


def _merge_study_requirements(settings: Settings, study_label: str) -> dict[str, Any]:
    requirements = settings.requirements or {}
    defaults = requirements.get("defaults", {}) or {}
    study_config = requirements.get(study_label)
    if study_config is None:
        available = [key for key in requirements.keys() if key != "defaults"]
        raise click.ClickException(
            f"Study {study_label!r} not found in requirements (available: {', '.join(available) or 'none'})."
        )
    merged = dict(defaults)
    merged.update(study_config or {})
    return merged


def _parse_date_option(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:  # pragma: no cover - invalid user input
        raise click.ClickException(f"Invalid date {value!r}; expected YYYY-MM-DD.") from exc


def _parse_cutoff_hour(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    clock = raw.strip()
    if not clock:
        return None
    hour_part = clock.split(":", 1)[0]
    try:
        hour = int(hour_part)
    except ValueError as exc:  # pragma: no cover
        raise click.ClickException(f"Invalid cutoff hour value {raw!r}.") from exc
    if hour < 0 or hour > 23:
        raise click.ClickException(f"Cutoff hour must be between 0 and 23 (got {hour}).")
    return hour


def _load_participant_map(csv_path: Path, mail_db_path: Path) -> dict[str, Participant]:
    try:
        participants = load_participants(csv_path, mail_db_path=mail_db_path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    return {p.user_did: p for p in participants}


def _participant_has_activity(engine, user_did: str) -> bool:
    """Return True when the participant appears in feed_requests or engagements."""
    queries = (
        text("SELECT 1 FROM feed_requests WHERE requester_did = :did LIMIT 1"),
        text("SELECT 1 FROM engagements WHERE did_engagement = :did LIMIT 1"),
    )
    with engine.connect() as conn:
        for query in queries:
            if conn.execute(query, {"did": user_did}).first():
                return True
    return False


def _summaries_for_participants(
    settings: Settings, participants: list[Participant]
) -> dict[str, WindowSummary]:
    engine = get_engine(settings.compliance_db_path)
    summaries: dict[str, WindowSummary] = {}
    for participant in participants:
        summary = compute_window_summary(engine, participant.user_did, settings)
        if summary:
            summaries[participant.user_did] = summary
    return summaries


@click.group()
def cli() -> None:
    """Mail updater CLI."""


@cli.command("aggregate")
def aggregate_command() -> None:
    """Compute window summaries for all participants and print a quick overview."""
    settings = _load_settings()
    participant_map = _load_participant_map(
        settings.participants_csv_path, settings.mail_db_path
    )
    active_participants = filter_active(participant_map.values())
    summaries = _summaries_for_participants(settings, active_participants)

    if not summaries:
        click.echo("No participant summaries computed. Check data availability.")
        return

    click.echo("Participant progress snapshot:")
    for participant in active_participants:
        summary = summaries.get(participant.user_did)
        if not summary:
            click.echo(f"- {participant.user_did}: no activity recorded in the window")
            continue
        status = "on-track" if summary.on_track else "off-track"
        click.echo(
            f"- {participant.user_did}: {summary.active_days}/{summary.required_active_days} active days ({status})"
        )


@cli.command("preview")
@click.option(
    "--user-did", "user_did", required=True, help="Participant DID to preview."
)
def preview_command(user_did: str) -> None:
    """Render a single participant's email to stdout."""
    settings = _load_settings()
    participant_map = _load_participant_map(
        settings.participants_csv_path, settings.mail_db_path
    )
    participant = participant_map.get(user_did)
    if not participant:
        raise click.ClickException(
            f"No participant with DID {user_did} found in roster (CSV/mail.db)."
        )

    engine = get_engine(settings.compliance_db_path)
    summary = compute_window_summary(engine, participant.user_did, settings)
    if not summary:
        raise click.ClickException("No compliance data available for that participant.")

    rendered = render_daily_progress(
        summary, participant, subject=settings.mail_subject
    )
    click.echo(rendered.text_body)


@cli.command("send-daily")
@click.option(
    "--dry-run/--no-dry-run",
    default=None,
    help="Override dry-run behaviour defined in .env.",
)
def send_daily_command(dry_run: Optional[bool]) -> None:
    """Send (or dry-run) daily emails for all include-in-emails participants."""
    settings = _load_settings()
    if dry_run is not None:
        settings.smtp_dry_run = dry_run

    sender = MailSender(settings)
    participant_map = _load_participant_map(
        settings.participants_csv_path, settings.mail_db_path
    )
    active_participants = filter_active(participant_map.values())

    summaries = _summaries_for_participants(settings, active_participants)
    if not summaries:
        click.echo("No participant summaries computed. Nothing to send.")
        return

    total = 0
    sent = 0
    for participant in active_participants:
        total += 1
        summary = summaries.get(participant.user_did)
        if not summary:
            click.echo(f"[skip] {participant.user_did}: no data in window.")
            continue

        rendered = render_daily_progress(
            summary, participant, subject=settings.mail_subject
        )
        sender.send(
            rendered,
            participant.email,
            user_did=participant.user_did,
            message_type="daily_update",
            template_version="daily_progress_v1",
        )
        sent += 1
        mode = "dry-run" if settings.smtp_dry_run else "sent"
        click.echo(f"[{mode}] {participant.user_did} -> {participant.email}")

    click.echo(
        f"Completed send loop. Participants processed: {total}; messages prepared: {sent}."
    )


@cli.command("sync-participants")
@click.option(
    "--survey-id",
    "survey_ids",
    multiple=True,
    help="Specific Qualtrics survey ID to include (may be passed multiple times).",
)
@click.option(
    "--survey-filter",
    default=None,
    help="Optional regex pattern to select Qualtrics surveys to include when no explicit IDs are provided.",
)
def sync_participants_command(
    survey_ids: tuple[str, ...], survey_filter: Optional[str]
) -> None:
    """Refresh the participant roster from Qualtrics via the REST API."""
    settings = _load_settings()
    survey_ids_list = [sid for sid in survey_ids if sid]
    if survey_ids_list and survey_filter:
        click.echo(
            "Ignoring --survey-filter because explicit --survey-id values were provided.",
            err=True,
        )
        survey_filter = None
    try:
        result = sync_participants_from_qualtrics(
            settings,
            survey_ids=survey_ids_list if survey_ids_list else None,
            survey_filter=survey_filter,
        )
    except QualtricsSyncError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        "Participants roster synced from Qualtrics: "
        f"{result.added_participants} new / {result.total_participants} total entries "
        f"across {result.surveys_considered} surveys."
    )
    if result.quarantined_dids:
        quarantine_msg = f"Quarantined {len(result.quarantined_dids)} unique DID(s)."
        if result.quarantine_path:
            quarantine_msg += f" Details saved to {result.quarantine_path}."
        click.echo(quarantine_msg)


@cli.command("validate-participants")
def validate_participants_command() -> None:
    """Verify participant roster entries are unique and present in compliance data."""
    settings = _load_settings()
    participants = load_participants(
        settings.participants_csv_path, mail_db_path=settings.mail_db_path
    )
    if not participants:
        raise click.ClickException("No participants found in mail.db or CSV roster.")

    participant_map = {p.user_did: p for p in participants}
    engine = get_engine(settings.compliance_db_path)

    duplicates: list[str] = []
    seen: set[str] = set()

    missing_activity: list[Participant] = []
    for participant in participants:
        if participant.user_did in seen:
            duplicates.append(participant.user_did)
            continue
        seen.add(participant.user_did)
        if not _participant_has_activity(engine, participant.user_did):
            missing_activity.append(participant)

    click.echo(f"Participants in roster: {len(participant_map)}")
    if duplicates:
        click.echo(f"Duplicate DIDs detected: {len(duplicates)}")
        for did in duplicates:
            click.echo(f"  - {did}")
        raise click.ClickException("Duplicate participant DIDs detected in roster.")
    else:
        click.echo("No duplicate DIDs detected.")

    if missing_activity:
        click.echo(f"Participants without compliance activity: {len(missing_activity)}")
        for participant in missing_activity:
            click.echo(f"  - {participant.user_did} ({participant.email})")
        raise click.ClickException(
            "Participant roster contains entries without compliance activity."
        )

    click.echo("Roster validation successful: all participants have activity.")


@cli.command("cache-daily-snapshots")
@click.option(
    "--study",
    "study_label",
    required=True,
    help="Study label from config requirements.",
)
@click.option(
    "--from-date",
    "from_date",
    default=None,
    help="Optional start date (YYYY-MM-DD) for snapshot window.",
)
@click.option(
    "--to-date",
    "to_date",
    default=None,
    help="Optional end date (YYYY-MM-DD) for snapshot window.",
)
def cache_daily_snapshots_command(
    study_label: str, from_date: Optional[str], to_date: Optional[str]
) -> None:
    """Cache per-day compliance metrics into mail.db."""

    settings = _load_settings()
    requirements = _merge_study_requirements(settings, study_label)

    cutoff_hour = _parse_cutoff_hour(requirements.get("day_cut_off"))
    min_retrievals = int(requirements.get("min_retrievals", 1) or 1)
    min_engagement = int(requirements.get("min_engagement", 3) or 3)

    study_settings = settings
    if "min_active_days" in requirements:
        study_settings = study_settings.with_overrides(
            required_active_days=int(requirements["min_active_days"])
        )
    if cutoff_hour is not None:
        study_settings = study_settings.with_overrides(cutoff_hour_local=cutoff_hour)

    start_day = _parse_date_option(from_date)
    end_day = _parse_date_option(to_date)
    if start_day and end_day and start_day > end_day:
        raise click.ClickException("from-date must be on or before to-date.")

    roster = list_participants(study_settings.mail_db_path)
    if not roster:
        raise click.ClickException("No participants found in mail.db; run sync-participants first.")

    engagement_engine = get_engine(study_settings.compliance_db_path)
    computed_at = datetime.now(timezone.utc)
    rows_to_insert: List[dict[str, Any]] = []

    for participant in roster:
        user_did = participant.get("did")
        if not user_did:
            continue

        snapshots = get_daily_engagement_breakdown(
            engagement_engine,
            user_did,
            study_settings,
            start_day=start_day,
            end_day=end_day,
        )

        cumulative_active = 0
        skip_streak = 0
        for snap in snapshots:
            is_active = snap.retrievals >= min_retrievals and snap.engagements >= min_engagement
            if is_active:
                cumulative_active += 1
                skip_streak = 0
            else:
                skip_streak += 1

            rows_to_insert.append(
                {
                    "snapshot_date": snap.study_day,
                    "user_did": user_did,
                    "study_label": study_label,
                    "retrievals": snap.retrievals,
                    "engagements": snap.engagements,
                    "engagement_breakdown": snap.engagement_breakdown,
                    "active_day": 1 if is_active else 0,
                    "cumulative_active": cumulative_active,
                    "cumulative_skip": skip_streak,
                    "computed_at": computed_at,
                }
            )

    inserted = upsert_compliance_monitoring_rows(
        study_settings.mail_db_path, rows_to_insert
    )
    click.echo(
        f"Cached {inserted} compliance_monitoring rows for study '{study_label}'."
    )


@cli.group("participant")
def participant_group() -> None:
    """Manage participant roster entries stored in mail.db."""


@participant_group.command("set-status")
@click.option(
    "--user-did",
    "user_did",
    required=True,
    help="Participant DID to update in mail.db.",
)
@click.option(
    "--status",
    "status",
    required=True,
    type=click.Choice(sorted(ALLOWED_STATUSES)),
    help="New status value (active, inactive, or unsubscribed).",
)
@click.option(
    "--reason",
    "reason",
    default=None,
    help="Optional reason for the status change (stored in history).",
)
@click.option(
    "--changed-by",
    "changed_by",
    default=None,
    help="Optional actor identifier recorded in history (defaults to mail-updater-cli).",
)
def participant_set_status_command(
    user_did: str, status: str, reason: Optional[str], changed_by: Optional[str]
) -> None:
    """Update a participant status and record the change in mail.db."""
    settings = _load_settings()
    settings.ensure_mail_db_parent()
    actor = changed_by or DEFAULT_STATUS_CHANGED_BY
    try:
        result = set_participant_status(
            settings.mail_db_path,
            user_did=user_did,
            new_status=status,
            reason=reason,
            changed_by=actor,
        )
    except (InvalidStatusError, ParticipantNotFoundError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc

    if result.changed:
        click.echo(
            f"Status for {result.user_did} updated: {result.old_status} -> {result.new_status}."
        )
        if result.reason:
            click.echo(f"Reason: {result.reason}")
        if result.changed_by:
            click.echo(f"Changed by: {result.changed_by}")
        try:
            export_participants_to_csv(
                settings.mail_db_path, settings.participants_csv_path
            )
        except Exception as exc:  # pragma: no cover - filesystem edge case
            raise click.ClickException(
                f"Failed to update participants CSV: {exc}"
            ) from exc
    else:
        click.echo(
            f"No change: participant {result.user_did} already has status {result.new_status}."
        )


@participant_group.command("import-csv")
def participant_import_csv_command() -> None:
    """Import rows from participants CSV into mail.db (upsert)."""
    settings = _load_settings()
    if not settings.participants_csv_path.exists():
        raise click.ClickException(
            f"Participants CSV not found at {settings.participants_csv_path}"
        )

    rows: list[dict[str, str]] = []
    with settings.participants_csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise click.ClickException("Participants CSV has no header row.")
        for raw in reader:
            email = (raw.get("email") or "").strip()
            did = (raw.get("did") or raw.get("user_did") or "").strip()
            if not email or not did:
                continue
            rows.append(
                {
                    "email": email,
                    "did": did,
                    "status": (raw.get("status") or "active").strip(),
                    "type": (raw.get("type") or "pilot").strip(),
                    "language": (raw.get("language") or "en").strip() or "en",
                    "feed_url": (raw.get("feed_url") or "").strip(),
                    "survey_completed_at": (raw.get("survey_completed_at") or "").strip(),
                    "prolific_id": (raw.get("prolific_id") or "").strip(),
                    "study_type": (raw.get("study_type") or "").strip(),
                }
            )

    if not rows:
        raise click.ClickException("No valid rows found in participants CSV to import.")

    result = upsert_participants(settings.mail_db_path, rows)
    export_participants_to_csv(settings.mail_db_path, settings.participants_csv_path)
    click.echo(
        "Participants imported into mail.db "
        f"({result.inserted} inserted, {result.updated} updated, {result.total} total)."
    )


@participant_group.command("add")
@click.option("--email", required=True, help="Email address for the participant.")
@click.option("--did", required=True, help="Bluesky DID (e.g., did:plc:abc123).")
@click.option(
    "--status",
    default=DEFAULT_STATUS,
    show_default=True,
    help="Initial participant status.",
)
@click.option(
    "--type",
    "participant_type",
    default=DEFAULT_TYPE,
    show_default=True,
    help="Participant type tag.",
)
@click.option(
    "--language",
    default="en",
    show_default=True,
    help="Preferred language code.",
)
@click.option("--feed-url", default=None, help="Assigned feed URL.")
@click.option("--prolific-id", default=None, help="Optional Prolific ID.")
@click.option("--study-type", default=None, help="Optional study label.")
@click.option(
    "--survey-completed-at",
    default=None,
    help="ISO timestamp for survey completion (UTC).",
)
def participant_add_command(
    email: str,
    did: str,
    status: str,
    participant_type: str,
    language: str,
    feed_url: Optional[str],
    prolific_id: Optional[str],
    study_type: Optional[str],
    survey_completed_at: Optional[str],
) -> None:
    """Insert a single participant row into mail.db for manual testing."""

    email = email.strip()
    did = did.strip()
    if not email:
        raise click.ClickException("Email must not be empty.")
    if not did:
        raise click.ClickException("DID must not be empty.")

    normalized_status = status.strip().lower() or DEFAULT_STATUS
    if normalized_status not in ALLOWED_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_STATUSES))
        raise click.ClickException(
            f"Invalid status {status!r}. Allowed values: {allowed}."
        )

    participant_type = participant_type.strip() or DEFAULT_TYPE
    language = language.strip() or "en"
    feed_url = (feed_url or "").strip() or None
    prolific_id = (prolific_id or "").strip() or None
    study_type = (study_type or "").strip() or None
    completion_raw = (survey_completed_at or "").strip() or None

    settings = _load_settings()
    existing = {row["did"]: row for row in list_participants(settings.mail_db_path)}
    if did in existing:
        raise click.ClickException(
            f"Participant with DID {did!r} already exists in mail.db."
        )

    email_lookup = find_participant_by_email(settings.mail_db_path, email)
    if email_lookup:
        existing_did = email_lookup[1]
        raise click.ClickException(
            f"Email {email!r} already present for participant {existing_did}."
        )

    result = upsert_participants(
        settings.mail_db_path,
        [
            {
                "email": email,
                "did": did,
                "status": normalized_status,
                "type": participant_type,
                "language": language,
                "feed_url": feed_url or "",
                "prolific_id": prolific_id or "",
                "study_type": study_type or "",
                "survey_completed_at": completion_raw or "",
            }
        ],
    )

    if result.inserted != 1:
        raise click.ClickException("Failed to insert participant; no rows were added.")

    export_participants_to_csv(settings.mail_db_path, settings.participants_csv_path)
    click.echo(f"Participant {did} added with email {email}.")


@participant_group.command("seed-completion")
@click.option(
    "--timestamp",
    "timestamp",
    required=True,
    help="UTC timestamp (ISO 8601) to assign to survey_completed_at.",
)
@click.option(
    "--type",
    "participant_types",
    multiple=True,
    help="Participant type to include (pass multiple times). Defaults to admin,test.",
)
def participant_seed_completion_command(
    timestamp: str, participant_types: tuple[str, ...]
) -> None:
    """Seed survey_completed_at for admin/test accounts."""

    try:
        parsed = date_parser.parse(timestamp)
    except (ValueError, TypeError) as exc:  # pragma: no cover - defensive
        raise click.ClickException(f"Invalid timestamp {timestamp!r}: {exc}") from exc

    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)

    types = participant_types or ("admin", "test")
    settings = _load_settings()
    updated_dids = seed_survey_completion(
        settings.mail_db_path,
        participant_types=types,
        completed_at=parsed,
    )

    if not updated_dids:
        click.echo("No participants required seeding.")
        return

    sorted_dids = ", ".join(sorted(updated_dids))
    click.echo(
        f"Seeded survey_completed_at for {len(updated_dids)} participants: {sorted_dids}."
    )


@cli.command("status")
@click.option(
    "--limit", type=int, default=20, help="Number of recent send attempts to show."
)
@click.option("--user-did", "user_did", default=None, help="Filter by participant DID.")
@click.option(
    "--message-type",
    "message_type",
    default=None,
    help="Filter by message type (e.g., daily_update).",
)
def status_command(
    limit: int, user_did: Optional[str], message_type: Optional[str]
) -> None:
    """Display recent send attempts captured in mail.db."""

    settings = _load_settings()
    attempts = fetch_recent_send_attempts(
        settings.mail_db_path,
        limit=limit,
        user_did=user_did,
        message_type=message_type,
    )

    if not attempts:
        click.echo("No send attempts recorded.")
        return

    header = f"Recent send attempts (limit {limit})"
    if user_did:
        header += f" — user {user_did}"
    if message_type:
        header += f" — type {message_type}"
    click.echo(header)

    columns = [
        "created_at",
        "user_did",
        "message_type",
        "mode",
        "status",
        "smtp_response",
    ]
    click.echo(" | ".join(columns))
    click.echo("-" * 80)

    for attempt in attempts:
        row = []
        for column in columns:
            value = attempt.get(column)
            if column == "created_at" and value is not None:
                value = getattr(value, "isoformat", lambda: str(value))()
            row.append(str(value or ""))
        click.echo(" | ".join(row))


@cli.command("bounces-scan")
@click.option(
    "--keep-unseen",
    is_flag=True,
    default=False,
    help="Leave bounce messages unread instead of marking them as seen.",
)
def bounces_scan_command(keep_unseen: bool) -> None:
    """Poll the IMAP bounce mailbox and suppress participants with hard bounces."""

    settings = _load_settings()
    try:
        outcome = scan_bounces(settings, mark_seen=not keep_unseen)
    except BounceScannerError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f"Bounce scan completed: {outcome.messages_seen} messages, "
        f"{len(outcome.participants_updated)} participants updated."
    )
    if outcome.participants_updated:
        click.echo(
            "Participants suppressed: "
            + ", ".join(sorted(set(outcome.participants_updated)))
        )
    if outcome.unmatched_recipients:
        click.echo(
            "Unmatched recipients: "
            + ", ".join(sorted(set(outcome.unmatched_recipients)))
        )


@cli.command("migrate-mail-db")
def migrate_mail_db_command() -> None:
    """Apply mail.db migrations to ensure the schema is up to date."""
    settings = _load_settings()
    settings.ensure_mail_db_parent()
    version = apply_migrations(settings.mail_db_path)
    click.echo(
        f"mail.db migrated to schema version {version} at {settings.mail_db_path}"
    )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

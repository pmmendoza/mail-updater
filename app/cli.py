"""CLI entry point for the mail updater MVP."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
from sqlalchemy import text

from .config import Settings
from .compliance_snapshot import WindowSummary, compute_window_summary
from .db import get_engine
from .email_renderer import render_daily_progress
from .bounce_scanner import BounceScannerError, scan_bounces
from .mail_db import apply_migrations
from .mail_db.operations import (
    ALLOWED_STATUSES,
    InvalidStatusError,
    ParticipantNotFoundError,
    export_participants_to_csv,
    fetch_recent_send_attempts,
    set_participant_status,
)
from .mailer import MailSender
from .participants import Participant, filter_active, load_participants
from .qualtrics_sync import QualtricsSyncError, sync_participants_from_qualtrics

DEFAULT_STATUS_CHANGED_BY = "mail-updater-cli"


def _load_settings() -> Settings:
    return Settings()


def _load_participant_map(csv_path: Path) -> dict[str, Participant]:
    participants = load_participants(csv_path)
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
    participant_map = _load_participant_map(settings.participants_csv_path)
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
    participant_map = _load_participant_map(settings.participants_csv_path)
    participant = participant_map.get(user_did)
    if not participant:
        raise click.ClickException(f"No participant with DID {user_did} found in CSV.")

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
    participant_map = _load_participant_map(settings.participants_csv_path)
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
    "--survey-filter",
    default=None,
    help="Optional regex pattern to select Qualtrics surveys to include.",
)
def sync_participants_command(survey_filter: Optional[str]) -> None:
    """Refresh the participant roster from Qualtrics via the REST API."""
    settings = _load_settings()
    try:
        result = sync_participants_from_qualtrics(settings, survey_filter=survey_filter)
    except QualtricsSyncError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        "Participants roster synced from Qualtrics: "
        f"{result.added_participants} new / {result.total_participants} total entries "
        f"across {result.surveys_considered} surveys."
    )


@cli.command("validate-participants")
def validate_participants_command() -> None:
    """Verify participant roster entries are unique and present in compliance data."""
    settings = _load_settings()
    participants = load_participants(settings.participants_csv_path)
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

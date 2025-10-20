"""CLI entry point for the mail updater MVP."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from .config import Settings
from .compliance_snapshot import WindowSummary, compute_window_summary
from .db import get_engine
from .email_renderer import render_daily_progress
from .mailer import MailSender
from .participants import Participant, filter_active, load_participants
from .qualtrics_sync import QualtricsSyncError, sync_participants_from_qualtrics


def _load_settings() -> Settings:
    return Settings()


def _load_participant_map(csv_path: Path) -> dict[str, Participant]:
    participants = load_participants(csv_path)
    return {p.user_did: p for p in participants}


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
        sender.send(rendered, participant.email, user_did=participant.user_did)
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


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

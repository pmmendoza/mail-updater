"""Email rendering utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .compliance_snapshot import WindowSummary
from .participants import Participant

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates" / "email"


@dataclass
class RenderedEmail:
    subject: str
    text_body: str
    html_body: Optional[str] = None


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_daily_progress(
    summary: WindowSummary,
    participant: Participant,
    *,
    subject: str,
) -> RenderedEmail:
    """Render subject and bodies for the daily progress email."""
    env = _environment()
    latest_snapshot = summary.snapshots[-1] if summary.snapshots else None
    non_compliant = False
    if latest_snapshot is not None:
        non_compliant = (
            latest_snapshot.retrievals == 0 and latest_snapshot.engagements == 0
        )

    base_template = "daily_progress"
    if (
        non_compliant
        and (TEMPLATES_DIR / "daily_progress_noncompliant.txt.j2").exists()
    ):
        base_template = "daily_progress_noncompliant"

    context = {
        "participant": participant,
        "summary": summary,
        "snapshots": summary.snapshots,
        "latest_snapshot": latest_snapshot,
        "non_compliant": non_compliant,
    }
    text_template = env.get_template(f"{base_template}.txt.j2")
    text_body = text_template.render(context)

    html_body = None
    html_template_path = TEMPLATES_DIR / f"{base_template}.html.j2"
    if html_template_path.exists():
        html_template = env.get_template(f"{base_template}.html.j2")
        html_body = html_template.render(context)

    return RenderedEmail(subject=subject, text_body=text_body, html_body=html_body)

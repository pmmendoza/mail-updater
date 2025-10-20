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
    context = {
        "participant": participant,
        "summary": summary,
        "snapshots": summary.snapshots,
        "latest_snapshot": summary.snapshots[-1] if summary.snapshots else None,
    }
    text_template = env.get_template("daily_progress.txt.j2")
    text_body = text_template.render(context)

    html_body = None
    if (TEMPLATES_DIR / "daily_progress.html.j2").exists():
        html_template = env.get_template("daily_progress.html.j2")
        html_body = html_template.render(context)

    return RenderedEmail(subject=subject, text_body=text_body, html_body=html_body)

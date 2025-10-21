"""Participant loading utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from .mail_db.operations import list_participants


@dataclass
class Participant:
    user_did: str
    email: str
    language: str = "en"
    include_in_emails: bool = True
    feed_url: Optional[str] = None


def _to_bool(value: str) -> bool:
    if value is None:
        return True
    value = value.strip().lower()
    if value in {"", "1", "true", "yes", "y"}:
        return True
    if value in {"0", "false", "no", "n"}:
        return False
    return True


def _normalize_language(raw: Optional[str]) -> str:
    if not raw:
        return "en"
    value = raw.strip()
    return value or "en"


def _status_to_bool(status: Optional[str]) -> bool:
    if status is None:
        return True
    return status.strip().lower() == "active"


def load_participants(
    csv_path: Path, *, mail_db_path: Optional[Path] = None
) -> List[Participant]:
    """Load participants roster, preferring mail.db when available."""
    if mail_db_path and mail_db_path.exists():
        db_participants = list_participants(mail_db_path)
        if db_participants:
            roster: List[Participant] = []
            for row in db_participants:
                user_did = (row.get("did") or "").strip()
                email = (row.get("email") or "").strip()
                if not user_did or not email:
                    continue
                language = (row.get("language") or "en").strip() or "en"
                status = (row.get("status") or "active").strip().lower()
                include_flag = status == "active"
                feed_url = (row.get("feed_url") or "").strip() or None
                roster.append(
                    Participant(
                        user_did=user_did,
                        email=email,
                        language=language,
                        include_in_emails=include_flag,
                        feed_url=feed_url,
                    )
                )
            if roster:
                return roster

    raise FileNotFoundError(
        "No participants found in mail.db. Run `participant import-csv` or "
        "`sync-participants` to seed the roster."
    )


def filter_active(participants: Iterable[Participant]) -> List[Participant]:
    """Return participants flagged for inclusion in emails."""
    return [p for p in participants if p.include_in_emails]

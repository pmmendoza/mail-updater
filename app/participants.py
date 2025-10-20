"""Participant loading utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List
import csv


@dataclass
class Participant:
    user_did: str
    email: str
    language: str = "en"
    include_in_emails: bool = True


def _to_bool(value: str) -> bool:
    if value is None:
        return True
    value = value.strip().lower()
    if value in {"", "1", "true", "yes", "y"}:
        return True
    if value in {"0", "false", "no", "n"}:
        return False
    return True


def load_participants(csv_path: Path) -> List[Participant]:
    """Load participants from CSV. Raises FileNotFoundError if missing."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Participants CSV not found at {csv_path}. "
            "Create the file with columns user_did,email,language,include_in_emails."
        )

    participants: List[Participant] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required_fields = {"user_did", "email"}
        missing = required_fields - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Participants CSV missing required columns: {', '.join(sorted(missing))}"
            )

        for row in reader:
            user_did = (row.get("user_did") or "").strip()
            email = (row.get("email") or "").strip()
            if not user_did or not email:
                continue
            language = (row.get("language") or "en").strip() or "en"
            include_flag = _to_bool(row.get("include_in_emails", "1"))
            participants.append(
                Participant(
                    user_did=user_did,
                    email=email,
                    language=language,
                    include_in_emails=include_flag,
                )
            )
    return participants


def filter_active(participants: Iterable[Participant]) -> List[Participant]:
    """Return participants flagged for inclusion in emails."""
    return [p for p in participants if p.include_in_emails]

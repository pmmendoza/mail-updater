"""Participant loading utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
import csv

from .mail_db.operations import list_participants


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
                roster.append(
                    Participant(
                        user_did=user_did,
                        email=email,
                        language=language,
                        include_in_emails=include_flag,
                    )
                )
            if roster:
                return roster

    if not csv_path.exists():
        raise FileNotFoundError(
            f"Participants CSV not found at {csv_path}. "
            "Create the file with columns email,did,status,type."
        )

    participants: List[Participant] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)

        fieldnames = set(reader.fieldnames or [])
        if {"email", "did"} <= fieldnames and "status" in fieldnames:
            required_fields = {"email", "did", "status", "type"}
            schema = "new"
        else:
            required_fields = {"user_did", "email"}
            schema = "legacy"

        missing = required_fields - fieldnames
        if missing:
            raise ValueError(
                f"Participants CSV missing required columns: {', '.join(sorted(missing))}"
            )

        for row in reader:
            if schema == "new":
                user_did = (row.get("did") or "").strip()
                email = (row.get("email") or "").strip()
                if not user_did or not email:
                    continue
                include_flag = _status_to_bool(row.get("status"))
                language = _normalize_language(row.get("language"))
            else:
                user_did = (row.get("user_did") or "").strip()
                email = (row.get("email") or "").strip()
                if not user_did or not email:
                    continue
                language = _normalize_language(row.get("language"))
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

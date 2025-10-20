"""Qualtrics API integration for refreshing participants."""

from __future__ import annotations

import csv
import io
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests
from requests import Response, Session

from .config import Settings

REQUIRED_HEADERS = ["email", "did", "status", "type"]
DEFAULT_STATUS = "active"
DEFAULT_TYPE = "pilot"
PROLIFIC_TYPE = "prolific"


class QualtricsSyncError(RuntimeError):
    """Raised when the Qualtrics sync process cannot complete successfully."""


def _normalize_base_url(raw: str) -> str:
    value = raw.strip()
    if value.startswith("https://"):
        value = value[len("https://") :]
    if value.startswith("http://"):
        value = value[len("http://") :]
    return value.rstrip("/")


@dataclass
class Survey:
    survey_id: str
    name: str


@dataclass
class SyncResult:
    """Summary of a Qualtrics participant synchronisation run."""

    surveys_considered: int
    responses_processed: int
    total_participants: int
    added_participants: int


class QualtricsClient:
    """Thin Qualtrics v3 API client."""

    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        session: Optional[Session] = None,
        poll_interval: float = 2.0,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.api_token = api_token
        self.session = session or requests.Session()
        self.poll_interval = poll_interval
        self.headers = {
            "X-API-TOKEN": self.api_token,
            "Content-Type": "application/json",
        }

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return f"https://{self.base_url}{path_or_url}"

    def list_surveys(self) -> List[Survey]:
        surveys: List[Survey] = []
        next_url: Optional[str] = "/API/v3/surveys"

        while next_url:
            response = self.session.get(
                self._url(next_url), headers=self.headers, timeout=30
            )
            _raise_for_status(response)
            payload = response.json()
            result = payload.get("result", {})
            for item in result.get("elements", []):
                surveys.append(
                    Survey(
                        survey_id=item.get("id", ""),
                        name=item.get("name", ""),
                    )
                )
            next_url = result.get("nextPage")

        return surveys

    def fetch_responses(self, survey_id: str) -> List[Dict[str, str]]:
        """Download all responses for a survey as dictionaries."""
        start_resp = self.session.post(
            self._url(f"/API/v3/surveys/{survey_id}/export-responses"),
            headers=self.headers,
            json={"format": "csv"},
            timeout=30,
        )
        _raise_for_status(start_resp)
        progress_id = start_resp.json().get("result", {}).get("progressId")
        if not progress_id:
            raise QualtricsSyncError("Qualtrics export did not return a progressId.")

        file_id = self._wait_for_export(survey_id, progress_id)
        export_resp = self.session.get(
            self._url(f"/API/v3/surveys/{survey_id}/export-responses/{file_id}/file"),
            headers=self.headers,
            timeout=60,
            stream=True,
        )
        _raise_for_status(export_resp)
        buffer = io.BytesIO(export_resp.content)

        with zipfile.ZipFile(buffer) as archive:
            for info in archive.infolist():
                if info.filename.lower().endswith(".csv"):
                    with archive.open(info) as handle:
                        text = io.TextIOWrapper(handle, encoding="utf-8-sig")
                        reader = csv.DictReader(text)
                        return list(reader)

        return []

    def _wait_for_export(self, survey_id: str, progress_id: str) -> str:
        status_url = f"/API/v3/surveys/{survey_id}/export-responses/{progress_id}"
        while True:
            response = self.session.get(
                self._url(status_url), headers=self.headers, timeout=30
            )
            _raise_for_status(response)
            result = response.json().get("result", {})
            status = (result.get("status") or "").lower()
            if status == "complete":
                file_id = result.get("fileId")
                if not file_id:
                    raise QualtricsSyncError("Export completed without a fileId.")
                return file_id
            if status == "failed":
                raise QualtricsSyncError("Qualtrics export failed.")
            time.sleep(self.poll_interval)


def _raise_for_status(response: Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise QualtricsSyncError(f"Qualtrics API error: {exc}") from exc


def _read_existing(csv_path: Path) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _write_csv(csv_path: Path, rows: Iterable[Dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "email": row.get("email", "").strip(),
                    "did": row.get("did", "").strip(),
                    "status": (row.get("status") or DEFAULT_STATUS).strip()
                    or DEFAULT_STATUS,
                    "type": (row.get("type") or DEFAULT_TYPE).strip() or DEFAULT_TYPE,
                }
            )


def _first_nonempty(row: Dict[str, str], *keys: str) -> Optional[str]:
    for key in keys:
        value = row.get(key)
        if value:
            text = str(value).strip()
            if text:
                return text
    return None


def _rows_from_responses(responses: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    participants: Dict[str, Dict[str, str]] = {}
    for response in responses:
        did = _first_nonempty(response, "did", "bs_did", "user_did", "DID")
        if not did:
            continue

        email = _first_nonempty(response, "email", "Email", "EmailAddress")
        prolific_id = _first_nonempty(response, "PROLIFIC_ID", "prolific_id")
        if not email and prolific_id:
            email = f"{prolific_id}@email.prolific.com"

        if not email:
            continue

        participant_type = PROLIFIC_TYPE if prolific_id else DEFAULT_TYPE

        existing = participants.get(did)
        if existing:
            if not existing.get("email") and email:
                existing["email"] = email
            if (
                existing.get("type") == DEFAULT_TYPE
                and participant_type == PROLIFIC_TYPE
            ):
                existing["type"] = participant_type
            continue

        participants[did] = {
            "email": email,
            "did": did,
            "status": DEFAULT_STATUS,
            "type": participant_type,
        }

    return list(participants.values())


def _merge_participants(
    existing: Iterable[Dict[str, str]], new_rows: Iterable[Dict[str, str]]
) -> List[Dict[str, str]]:
    merged: Dict[str, Dict[str, str]] = {}
    for row in existing:
        did = row.get("did")
        if not did:
            continue
        merged[did] = {
            "email": row.get("email", "").strip(),
            "did": did.strip(),
            "status": (row.get("status") or DEFAULT_STATUS).strip() or DEFAULT_STATUS,
            "type": (row.get("type") or DEFAULT_TYPE).strip() or DEFAULT_TYPE,
        }

    for row in new_rows:
        did = row.get("did")
        if not did:
            continue
        record = merged.get(did)
        if record:
            if not record.get("email") and row.get("email"):
                record["email"] = row["email"].strip()
            if not record.get("status"):
                record["status"] = row.get("status", DEFAULT_STATUS)
            new_type = (row.get("type") or DEFAULT_TYPE).strip() or DEFAULT_TYPE
            if record.get("type") in ("", None):
                record["type"] = new_type
            elif record.get("type") == DEFAULT_TYPE and new_type == PROLIFIC_TYPE:
                record["type"] = new_type
        else:
            merged[did] = {
                "email": row.get("email", "").strip(),
                "did": did.strip(),
                "status": (row.get("status") or DEFAULT_STATUS).strip()
                or DEFAULT_STATUS,
                "type": (row.get("type") or DEFAULT_TYPE).strip() or DEFAULT_TYPE,
            }

    return sorted(merged.values(), key=lambda item: item["email"])


def sync_participants_from_qualtrics(
    settings: Settings,
    *,
    survey_filter: Optional[str] = None,
    client: Optional[QualtricsClient] = None,
) -> SyncResult:
    """Refresh the participant roster from Qualtrics using the public API."""
    if not settings.qualtrics_base_url or not settings.qualtrics_api_token:
        raise QualtricsSyncError(
            "Qualtrics credentials missing (QUALTRICS_BASE_URL / QUALTRICS_API_TOKEN)."
        )

    csv_path = settings.participants_csv_path
    existing_rows = _read_existing(csv_path)
    existing_dids = {
        row.get("did", "").strip() for row in existing_rows if row.get("did")
    }

    client = client or QualtricsClient(
        base_url=settings.qualtrics_base_url,
        api_token=settings.qualtrics_api_token,
    )

    pattern: Optional[re.Pattern[str]] = None
    filter_value = survey_filter or settings.qualtrics_survey_filter
    if filter_value:
        pattern = re.compile(filter_value)

    surveys = client.list_surveys()
    if pattern:
        surveys = [survey for survey in surveys if pattern.search(survey.name)]

    if not surveys:
        # Nothing to do; keep the current roster.
        _write_csv(csv_path, existing_rows or [])
        return SyncResult(
            surveys_considered=0,
            responses_processed=0,
            total_participants=len(existing_dids),
            added_participants=0,
        )

    responses: List[Dict[str, str]] = []
    for survey in surveys:
        responses.extend(client.fetch_responses(survey.survey_id))

    new_rows = _rows_from_responses(responses)
    if not new_rows:
        _write_csv(csv_path, existing_rows or [])
        return SyncResult(
            surveys_considered=len(surveys),
            responses_processed=len(responses),
            total_participants=len(existing_dids),
            added_participants=0,
        )

    merged = _merge_participants(existing_rows, new_rows)
    _write_csv(csv_path, merged)
    merged_dids = {row.get("did") for row in merged if row.get("did")}
    added = len(merged_dids - existing_dids)

    return SyncResult(
        surveys_considered=len(surveys),
        responses_processed=len(responses),
        total_participants=len(merged_dids),
        added_participants=added,
    )

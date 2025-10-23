"""Qualtrics API integration for refreshing participants."""

from __future__ import annotations

import csv
import functools
import io
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests
from requests import Response, Session

from dateutil import parser as date_parser

from .config import Settings
from .mail_db.operations import (
    DEFAULT_STATUS,
    DEFAULT_TYPE,
    export_participants_to_csv,
    list_participants,
    upsert_participants,
)

PROLIFIC_TYPE = "prolific"
FIELD_MAPPING_PATH = Path(__file__).resolve().parents[1] / "qualtrics_field_mapping.csv"


class QualtricsSyncError(RuntimeError):
    """Raised when the Qualtrics sync process cannot complete successfully."""


@functools.lru_cache(maxsize=1)
def _load_field_mapping() -> Dict[str, str]:
    if not FIELD_MAPPING_PATH.exists():
        return {}

    mapping: Dict[str, str] = {}
    with FIELD_MAPPING_PATH.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            field = (row.get("field") or "").strip().lower()
            key = (row.get("qualtrics_key") or "").strip()
            if field and key:
                mapping[field] = key
    return mapping


def _format_completion(value: Optional[Any]) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if hasattr(value, "astimezone"):
        try:
            return value.astimezone(timezone.utc).isoformat()
        except Exception:
            return str(value)
    return str(value)


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
    quarantined_dids: List[str]
    quarantine_path: Optional[Path]


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



def _first_nonempty(row: Dict[str, str], *keys: str) -> Optional[str]:
    for key in keys:
        value = row.get(key)
        if value:
            text = str(value).strip()
            if text:
                return text
    return None


def _rows_from_responses(
    responses: Iterable[Dict[str, str]],
) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    field_mapping = _load_field_mapping()

    participants: Dict[str, Dict[str, str]] = {}
    quarantine: List[Dict[str, str]] = []
    for response in responses:
        status_value = (response.get("Status") or "").strip()
        if status_value and not status_value.isdigit():
            # Drop Qualtrics header rows where Status contains labels/ImportIds.
            continue

        dist_channel = (response.get("DistributionChannel") or "").strip().lower()
        preview_flag = (response.get("Preview") or "").strip().lower()
        preview_mode = (response.get("PreviewMode") or "").strip().lower()
        if "preview" in {dist_channel, preview_flag, preview_mode}:
            continue

        did_candidates = []
        if mapping_key := field_mapping.get("did"):
            did_candidates.append(mapping_key)
        did_candidates.extend(
            [
                "did",
                "bs_did",
                "user_did",
                "DID",
                "QID_DID",
            ]
        )
        did = _first_nonempty(response, *did_candidates)

        email_candidates = []
        if mapping_key := field_mapping.get("email"):
            email_candidates.append(mapping_key)
        email_candidates.extend(
            [
                "email",
                "Email",
                "EmailAddress",
                "RecipientEmail",
                "email_pilot",
            ]
        )
        email = _first_nonempty(response, *email_candidates)

        prolific_candidates = []
        if mapping_key := field_mapping.get("prolific_id"):
            prolific_candidates.append(mapping_key)
        prolific_candidates.extend(["PROLIFIC_ID", "prolific_id"])
        prolific_id = _first_nonempty(response, *prolific_candidates)

        study_type_candidates = []
        if mapping_key := field_mapping.get("study_type"):
            study_type_candidates.append(mapping_key)
        study_type_candidates.extend(["STUDY_TYPE", "study_type"])
        study_type = _first_nonempty(response, *study_type_candidates)

        feed_candidates = []
        if mapping_key := field_mapping.get("feed_url"):
            feed_candidates.append(mapping_key)
        feed_candidates.extend(
            [
                "feed_url",
                "Feed URL",
                "feedUrl",
                "assigned_feed_url",
                "Assigned Feed URL",
            ]
        )
        feed_url = _first_nonempty(response, *feed_candidates)

        completed_candidates = []
        if mapping_key := field_mapping.get("survey_completed_at"):
            completed_candidates.append(mapping_key)
        completed_candidates.extend(["RecordedDate", "EndDate"])
        completed_raw = _first_nonempty(response, *completed_candidates)
        completed_at: Optional[str] = None
        if completed_raw:
            try:
                completed_dt = date_parser.parse(completed_raw)
                if not completed_dt.tzinfo:
                    completed_dt = completed_dt.replace(tzinfo=timezone.utc)
                completed_at = completed_dt.astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError):
                completed_at = None

        if not email and prolific_id:
            email = f"{prolific_id}@email.prolific.com"

        if not did or not email or not feed_url:
            quarantine.append(
                {
                    "did": did or "",
                    "email": email or "",
                    "feed_url": feed_url or "",
                }
            )
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
            if feed_url:
                existing["feed_url"] = feed_url
            if completed_at and not existing.get("survey_completed_at"):
                existing["survey_completed_at"] = completed_at
            continue

        participants[did] = {
            "email": email,
            "did": did,
            "status": DEFAULT_STATUS,
            "type": participant_type,
            "feed_url": feed_url,
            "survey_completed_at": completed_at or "",
            "prolific_id": prolific_id or "",
            "study_type": study_type or "",
        }

    return list(participants.values()), quarantine


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
            "feed_url": (row.get("feed_url") or "").strip(),
            "survey_completed_at": _format_completion(
                row.get("survey_completed_at")
            ),
            "prolific_id": (row.get("prolific_id") or "").strip(),
            "study_type": (row.get("study_type") or "").strip(),
        }

    for row in new_rows:
        did = row.get("did")
        if not did:
            continue
        record = merged.get(did)
        if record:
            new_email = (row.get("email") or "").strip()
            if new_email and new_email != record.get("email"):
                record["email"] = new_email
            if not record.get("email") and row.get("email"):
                record["email"] = row["email"].strip()
            if not record.get("status"):
                record["status"] = row.get("status", DEFAULT_STATUS)
            new_type = (row.get("type") or DEFAULT_TYPE).strip() or DEFAULT_TYPE
            if record.get("type") in ("", None):
                record["type"] = new_type
            elif record.get("type") == DEFAULT_TYPE and new_type == PROLIFIC_TYPE:
                record["type"] = new_type
            new_feed_url = (row.get("feed_url") or "").strip()
            if new_feed_url and new_feed_url != record.get("feed_url"):
                record["feed_url"] = new_feed_url
            new_completed = _format_completion(row.get("survey_completed_at"))
            if new_completed and not record.get("survey_completed_at"):
                record["survey_completed_at"] = new_completed
            new_prolific = (row.get("prolific_id") or "").strip()
            if new_prolific and not record.get("prolific_id"):
                record["prolific_id"] = new_prolific
            new_study_type = (row.get("study_type") or "").strip()
            if new_study_type and not record.get("study_type"):
                record["study_type"] = new_study_type
        else:
            merged[did] = {
                "email": row.get("email", "").strip(),
                "did": did.strip(),
                "status": (row.get("status") or DEFAULT_STATUS).strip()
                or DEFAULT_STATUS,
                "type": (row.get("type") or DEFAULT_TYPE).strip() or DEFAULT_TYPE,
                "feed_url": (row.get("feed_url") or "").strip(),
                "survey_completed_at": _format_completion(
                    row.get("survey_completed_at")
                ),
                "prolific_id": (row.get("prolific_id") or "").strip(),
                "study_type": (row.get("study_type") or "").strip(),
            }

    return sorted(merged.values(), key=lambda item: item["email"])


def sync_participants_from_qualtrics(
    settings: Settings,
    *,
    survey_ids: Optional[Iterable[str]] = None,
    survey_filter: Optional[str] = None,
    client: Optional[QualtricsClient] = None,
) -> SyncResult:
    """Refresh the participant roster from Qualtrics using the public API."""
    if not settings.qualtrics_base_url or not settings.qualtrics_api_token:
        raise QualtricsSyncError(
            "Qualtrics credentials missing (QUALTRICS_BASE_URL / QUALTRICS_API_TOKEN)."
        )

    csv_path = settings.participants_csv_path
    settings.ensure_mail_db_parent()
    db_path = settings.mail_db_path

    existing_db_rows = list_participants(db_path)
    if existing_db_rows:
        existing_rows = existing_db_rows
    else:
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

    provided_ids = [sid for sid in (survey_ids or []) if sid]
    if not provided_ids and settings.qualtrics_survey_ids:
        provided_ids = list(settings.qualtrics_survey_ids)

    surveys: List[Survey]
    responses: List[Dict[str, str]] = []
    responses_processed = 0

    if provided_ids:
        requested_ids = list(dict.fromkeys(provided_ids))
        survey_lookup = {survey.survey_id: survey for survey in client.list_surveys()}
        surveys = []
        for sid in requested_ids:
            surveys.append(survey_lookup.get(sid, Survey(survey_id=sid, name=sid)))
            responses.extend(client.fetch_responses(sid))
        responses_processed = len(responses)
    else:
        surveys = client.list_surveys()
        if pattern:
            surveys = [survey for survey in surveys if pattern.search(survey.name)]

        if not surveys:
            if existing_db_rows:
                total_participants = len(existing_db_rows)
                export_participants_to_csv(db_path, csv_path)
            else:
                total_participants = len(existing_dids)
                if not csv_path.exists():
                    export_participants_to_csv(db_path, csv_path)
            return SyncResult(
                surveys_considered=0,
                responses_processed=0,
                total_participants=total_participants,
                added_participants=0,
                quarantined_dids=[],
                quarantine_path=None,
            )

        for survey in surveys:
            survey_responses = client.fetch_responses(survey.survey_id)
            responses.extend(survey_responses)
            responses_processed += len(survey_responses)

    new_rows, quarantined = _rows_from_responses(responses)
    quarantine_path: Optional[Path] = None
    if quarantined:
        quarantine_path = csv_path.parent / "qualtrics_quarantine.csv"
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        with quarantine_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["email", "did", "feed_url"])
            writer.writeheader()
            for row in quarantined:
                writer.writerow(row)

    if not new_rows:
        if existing_db_rows:
            total_participants = len(existing_db_rows)
        else:
            total_participants = len(existing_dids)
        export_participants_to_csv(db_path, csv_path)
        return SyncResult(
            surveys_considered=len(surveys),
            responses_processed=responses_processed,
            total_participants=total_participants,
            added_participants=0,
            quarantined_dids=sorted(
                {row.get("did", "") for row in quarantined if row.get("did")}
            ),
            quarantine_path=quarantine_path,
        )

    merged = _merge_participants(existing_rows, new_rows)

    upsert_result = upsert_participants(db_path, merged)
    export_participants_to_csv(db_path, csv_path)

    return SyncResult(
        surveys_considered=len(surveys),
        responses_processed=responses_processed,
        total_participants=upsert_result.total,
        added_participants=upsert_result.inserted,
        quarantined_dids=sorted(
            {row.get("did", "") for row in quarantined if row.get("did")}
        ),
        quarantine_path=quarantine_path,
    )

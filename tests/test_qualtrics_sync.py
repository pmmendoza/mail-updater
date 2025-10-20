from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.qualtrics_sync import (  # noqa: E402
    QualtricsSyncError,
    Survey,
    _merge_participants,
    _rows_from_responses,
    sync_participants_from_qualtrics,
)


class StubClient:
    def __init__(
        self, surveys: Iterable[Survey], responses: Dict[str, List[Dict[str, str]]]
    ) -> None:
        self._surveys = list(surveys)
        self._responses = responses

    def list_surveys(self) -> List[Survey]:
        return list(self._surveys)

    def fetch_responses(self, survey_id: str) -> List[Dict[str, str]]:
        return list(self._responses.get(survey_id, []))


def test_rows_from_responses_extracts_unique_participants() -> None:
    responses = [
        {"email": "a@example.com", "bs_did": "did:one", "PROLIFIC_ID": "123"},
        {"email": "", "bs_did": "did:one", "PROLIFIC_ID": "123"},
        {"email": "b@example.com", "did": "did:two"},
        {"prolific_id": "789", "did": "did:three"},
    ]

    rows = _rows_from_responses(responses)
    assert rows == [
        {
            "email": "a@example.com",
            "did": "did:one",
            "status": "active",
            "type": "prolific",
        },
        {
            "email": "b@example.com",
            "did": "did:two",
            "status": "active",
            "type": "pilot",
        },
        {
            "email": "789@email.prolific.com",
            "did": "did:three",
            "status": "active",
            "type": "prolific",
        },
    ]


def test_merge_participants_preserves_existing_metadata() -> None:
    existing = [
        {
            "email": "admin@example.com",
            "did": "did:admin",
            "status": "active",
            "type": "admin",
        },
        {
            "email": "old@example.com",
            "did": "did:old",
            "status": "inactive",
            "type": "pilot",
        },
    ]
    new_rows = [
        {
            "email": "new@example.com",
            "did": "did:new",
            "status": "active",
            "type": "prolific",
        },
        {
            "email": "updated@example.com",
            "did": "did:old",
            "status": "active",
            "type": "prolific",
        },
    ]

    merged = _merge_participants(existing, new_rows)
    merged_by_did = {row["did"]: row for row in merged}
    assert merged_by_did["did:admin"]["type"] == "admin"
    assert merged_by_did["did:old"]["email"] == "old@example.com"
    assert merged_by_did["did:old"]["status"] == "inactive"
    assert merged_by_did["did:old"]["type"] == "prolific"
    assert merged_by_did["did:new"]["type"] == "prolific"


def test_sync_participants_from_qualtrics_updates_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type\n"
        "philipp.m.mendoza@gmail.com,did:plc:admin,active,admin\n",
        encoding="utf-8",
    )

    surveys = [Survey(survey_id="SV_1", name="NEWSFLOWS_pretreat_v1.0")]
    responses = {
        "SV_1": [
            {"email": "person@example.com", "bs_did": "did:new", "PROLIFIC_ID": "123"},
            {"email": "philipp@example.com", "bs_did": "did:plc:admin"},
        ]
    }

    settings = Settings().with_overrides(
        participants_csv_path=csv_path,
        qualtrics_base_url="eu.qualtrics.com",
        qualtrics_api_token="token",
        qualtrics_survey_filter="NEWSFLOWS",
    )

    stub = StubClient(surveys, responses)
    result = sync_participants_from_qualtrics(settings, client=stub)

    output = csv_path.read_text(encoding="utf-8")
    assert "person@example.com" in output
    assert "philipp.m.mendoza@gmail.com" in output
    # type/admin preserved
    assert "admin" in output
    assert result.added_participants == 1
    assert result.total_participants == 2
    assert result.surveys_considered == 1
    assert result.responses_processed == 2


def test_sync_participants_requires_credentials(tmp_path: Path) -> None:
    settings = Settings().with_overrides(
        participants_csv_path=tmp_path / "participants.csv",
        qualtrics_base_url=None,
        qualtrics_api_token=None,
    )

    with pytest.raises(QualtricsSyncError):
        sync_participants_from_qualtrics(settings)


def test_sync_participants_keeps_existing_when_no_surveys(tmp_path: Path) -> None:
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type\n" "person@example.com,did:123,active,pilot\n",
        encoding="utf-8",
    )

    settings = Settings().with_overrides(
        participants_csv_path=csv_path,
        qualtrics_base_url="eu.qualtrics.com",
        qualtrics_api_token="token",
        qualtrics_survey_filter="NEWSFLOWS",
    )

    stub = StubClient([], {})
    result = sync_participants_from_qualtrics(settings, client=stub)

    assert csv_path.read_text(encoding="utf-8").count("person@example.com") == 1
    assert result.added_participants == 0
    assert result.total_participants == 1
    assert result.surveys_considered == 0
    assert result.responses_processed == 0

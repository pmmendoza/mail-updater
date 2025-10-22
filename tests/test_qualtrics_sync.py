from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.mail_db.migrations import apply_migrations  # noqa: E402
from app.mail_db.operations import get_mail_db_engine, list_participants  # noqa: E402
from app.mail_db.schema import participants  # noqa: E402
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
        {
            "email": "a@example.com",
            "bs_did": "did:one",
            "PROLIFIC_ID": "123",
            "feed_url": "https://feeds.example.com/one",
        },
        {"email": "", "bs_did": "did:one", "PROLIFIC_ID": "123"},
        {
            "email": "b@example.com",
            "did": "did:two",
            "feed_url": "https://feeds.example.com/two",
        },
        {"prolific_id": "789", "did": "did:three"},
    ]

    rows, quarantine = _rows_from_responses(responses)
    assert rows == [
        {
            "email": "a@example.com",
            "did": "did:one",
            "status": "active",
            "type": "prolific",
            "feed_url": "https://feeds.example.com/one",
        },
        {
            "email": "b@example.com",
            "did": "did:two",
            "status": "active",
            "type": "pilot",
            "feed_url": "https://feeds.example.com/two",
        },
    ]
    assert quarantine == [
        {
            "did": "did:one",
            "email": "123@email.prolific.com",
            "feed_url": "",
        },
        {
            "email": "789@email.prolific.com",
            "did": "did:three",
            "feed_url": "",
        },
    ]


def test_merge_participants_preserves_existing_metadata() -> None:
    existing = [
        {
            "email": "admin@example.com",
            "did": "did:admin",
            "status": "active",
            "type": "admin",
            "feed_url": "https://feeds.example.com/admin",
        },
        {
            "email": "old@example.com",
            "did": "did:old",
            "status": "inactive",
            "type": "pilot",
            "feed_url": "https://feeds.example.com/old",
        },
    ]
    new_rows = [
        {
            "email": "new@example.com",
            "did": "did:new",
            "status": "active",
            "type": "prolific",
            "feed_url": "https://feeds.example.com/new",
        },
        {
            "email": "updated@example.com",
            "did": "did:old",
            "status": "active",
            "type": "prolific",
            "feed_url": "https://feeds.example.com/updated",
        },
    ]

    merged = _merge_participants(existing, new_rows)
    merged_by_did = {row["did"]: row for row in merged}
    assert merged_by_did["did:admin"]["type"] == "admin"
    assert merged_by_did["did:old"]["email"] == "updated@example.com"
    assert merged_by_did["did:old"]["status"] == "inactive"
    assert merged_by_did["did:old"]["type"] == "prolific"
    assert merged_by_did["did:new"]["type"] == "prolific"
    assert merged_by_did["did:old"]["feed_url"] == "https://feeds.example.com/updated"


def test_sync_participants_from_qualtrics_updates_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url\n"
        "philipp.m.mendoza@gmail.com,did:plc:admin,active,admin,https://feeds.example.com/admin\n",
        encoding="utf-8",
    )
    mail_db_path = tmp_path / "mail.sqlite"
    apply_migrations(mail_db_path)
    engine = get_mail_db_engine(mail_db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert().values(
                user_did="did:plc:admin",
                email="philipp.m.mendoza@gmail.com",
                status="inactive",
                type="admin",
                language="en",
                feed_url="https://feeds.example.com/admin",
            )
        )

    surveys = [Survey(survey_id="SV_1", name="NEWSFLOWS_pretreat_v1.0")]
    responses = {
        "SV_1": [
            {
                "email": "person@example.com",
                "bs_did": "did:new",
                "PROLIFIC_ID": "123",
                "feed_url": "https://feeds.example.com/new",
            },
            {
                "email": "philipp@example.com",
                "bs_did": "did:plc:admin",
                "feed_url": "https://feeds.example.com/admin",
            },
        ]
    }

    settings = Settings().with_overrides(
        participants_csv_path=csv_path,
        mail_db_path=mail_db_path,
        qualtrics_base_url="eu.qualtrics.com",
        qualtrics_api_token="token",
        qualtrics_survey_filter="NEWSFLOWS",
    )

    stub = StubClient(surveys, responses)
    result = sync_participants_from_qualtrics(settings, client=stub)

    roster = list_participants(mail_db_path)
    roster_by_did = {row["did"]: row for row in roster}
    assert roster_by_did["did:plc:admin"]["status"] == "inactive"
    assert roster_by_did["did:plc:admin"]["email"] == "philipp@example.com"
    assert roster_by_did["did:new"]["email"] == "person@example.com"
    assert roster_by_did["did:new"]["status"] == "active"
    assert roster_by_did["did:new"].get("feed_url") == "https://feeds.example.com/new"

    output = csv_path.read_text(encoding="utf-8")
    expected_csv = (
        "email,did,status,type,feed_url\n"
        "person@example.com,did:new,active,prolific,https://feeds.example.com/new\n"
        "philipp@example.com,did:plc:admin,inactive,admin,https://feeds.example.com/admin\n"
    )
    assert output == expected_csv
    assert result.added_participants == 1
    assert result.total_participants == 2
    assert result.surveys_considered == 1
    assert result.responses_processed == 2
    assert result.quarantined_dids == []
    assert result.quarantine_path is None


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
        "email,did,status,type,feed_url\n"
        "person@example.com,did:123,active,pilot,https://feeds.example.com/123\n",
        encoding="utf-8",
    )
    mail_db_path = tmp_path / "mail.sqlite"
    apply_migrations(mail_db_path)
    engine = get_mail_db_engine(mail_db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert().values(
                user_did="did:123",
                email="person@example.com",
                status="inactive",
                type="pilot",
                language="en",
                feed_url="https://feeds.example.com/123",
            )
        )

    settings = Settings().with_overrides(
        participants_csv_path=csv_path,
        mail_db_path=mail_db_path,
        qualtrics_base_url="eu.qualtrics.com",
        qualtrics_api_token="token",
        qualtrics_survey_filter="NEWSFLOWS",
    )

    stub = StubClient([], {})
    result = sync_participants_from_qualtrics(settings, client=stub)

    output = csv_path.read_text(encoding="utf-8")
    assert output.count("person@example.com") == 1
    assert "inactive" in output
    roster = list_participants(mail_db_path)
    assert roster == [
        {
            "did": "did:123",
            "email": "person@example.com",
            "status": "inactive",
            "type": "pilot",
            "language": "en",
            "feed_url": "https://feeds.example.com/123",
        }
    ]
    assert result.added_participants == 0
    assert result.total_participants == 1
    assert result.surveys_considered == 0
    assert result.responses_processed == 0
    assert result.quarantined_dids == []
    assert result.quarantine_path is None


def test_sync_participants_writes_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url\n",
        encoding="utf-8",
    )
    mail_db_path = tmp_path / "mail.sqlite"
    apply_migrations(mail_db_path)

    surveys = [Survey(survey_id="SV_1", name="NEWSFLOWS_pretreat_v1.0")]
    responses = {
        "SV_1": [
            {
                "email": "valid@example.com",
                "did": "did:valid",
                "feed_url": "https://feeds.example.com/valid",
            },
            {
                "email": "invalid@example.com",
                "did": "",
                "feed_url": "",
            },
        ]
    }

    settings = Settings().with_overrides(
        participants_csv_path=csv_path,
        mail_db_path=mail_db_path,
        qualtrics_base_url="eu.qualtrics.com",
        qualtrics_api_token="token",
    )

    stub = StubClient(surveys, responses)
    result = sync_participants_from_qualtrics(settings, client=stub)

    assert result.quarantined_dids == []  # missing DID so excluded from set
    assert result.quarantine_path is not None
    assert result.quarantine_path.exists()
    quarantine_contents = result.quarantine_path.read_text(encoding="utf-8")
    expected_quarantine = "email,did,feed_url\n" "invalid@example.com,,\n"
    assert quarantine_contents == expected_quarantine
    roster = list_participants(mail_db_path)
    assert any(row["did"] == "did:valid" for row in roster)

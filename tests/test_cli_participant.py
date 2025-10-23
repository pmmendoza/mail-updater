import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from click.testing import CliRunner  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.cli import cli  # noqa: E402
from app.config import Settings  # noqa: E402
from app.mail_db.migrations import apply_migrations  # noqa: E402
from app.mail_db.operations import get_mail_db_engine  # noqa: E402
from app.mail_db.schema import participant_status_history, participants  # noqa: E402


def _seed_participant(
    db_path: Path,
    *,
    status: str = "active",
    feed_url: str = "https://feeds.example.com/default"
) -> None:
    engine = get_mail_db_engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert().values(
                user_did="did:example:cli",
                email="cli@example.com",
                status=status,
                type="pilot",
                language="en",
                feed_url=feed_url,
            )
        )


def test_cli_participant_set_status_updates_db(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path, feed_url="https://feeds.example.com/cli")
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url,survey_completed_at,prolific_id,study_type,audit_timestamp\n"
        "cli@example.com,did:example:cli,active,pilot,https://feeds.example.com/cli,,,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.cli._load_settings",
        lambda: Settings().with_overrides(
            mail_db_path=db_path,
            participants_csv_path=csv_path,
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "participant",
            "set-status",
            "--user-did",
            "did:example:cli",
            "--status",
            "inactive",
            "--reason",
            "manual hold",
            "--changed-by",
            "ops@example.com",
        ],
    )

    assert result.exit_code == 0
    assert "Status for did:example:cli updated: active -> inactive." in result.output
    assert "Reason: manual hold" in result.output
    assert "Changed by: ops@example.com" in result.output

    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        status = conn.execute(
            select(participants.c.status).where(
                participants.c.user_did == "did:example:cli"
            )
        ).scalar_one()
        assert status == "inactive"

        history_rows = conn.execute(
            select(
                participant_status_history.c.old_status,
                participant_status_history.c.new_status,
            )
        ).all()
        assert history_rows == [("active", "inactive")]

    contents = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 2
    assert (
        contents[1]
        == "cli@example.com,did:example:cli,active,pilot,https://feeds.example.com/cli,,,,"
    )


def test_cli_participant_set_status_no_change(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(
        db_path,
        status="inactive",
        feed_url="https://feeds.example.com/cli",
    )
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url,survey_completed_at,prolific_id,study_type,audit_timestamp\n"
        "cli@example.com,did:example:cli,inactive,pilot,https://feeds.example.com/cli,,,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.cli._load_settings",
        lambda: Settings().with_overrides(
            mail_db_path=db_path,
            participants_csv_path=csv_path,
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "participant",
            "set-status",
            "--user-did",
            "did:example:cli",
            "--status",
            "inactive",
        ],
    )

    assert result.exit_code == 0
    assert (
        "No change: participant did:example:cli already has status inactive."
        in result.output
    )

    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        history_rows = conn.execute(
            select(participant_status_history.c.history_id)
        ).fetchall()
        assert history_rows == []

    contents = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 2
    assert (
        contents[1]
        == "cli@example.com,did:example:cli,inactive,pilot,https://feeds.example.com/cli,,,,"
    )


def test_cli_participant_set_status_missing_user(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(
        db_path,
        status="active",
        feed_url="https://feeds.example.com/other",
    )
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url,survey_completed_at,prolific_id,study_type,audit_timestamp\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.cli._load_settings",
        lambda: Settings().with_overrides(
            mail_db_path=db_path,
            participants_csv_path=csv_path,
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "participant",
            "set-status",
            "--user-did",
            "did:example:missing",
            "--status",
            "inactive",
        ],
    )

    assert result.exit_code != 0
    assert "Participant with DID 'did:example:missing' not found" in result.output


def test_cli_participant_import_csv(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url,survey_completed_at,prolific_id,study_type,audit_timestamp\n"
        "user1@example.com,did:example:one,active,pilot,https://feeds.example.com/one,,,,\n"
        "user2@example.com,did:example:two,inactive,admin,https://feeds.example.com/two,,,,\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.cli._load_settings",
        lambda: Settings().with_overrides(
            mail_db_path=db_path,
            participants_csv_path=csv_path,
        ),
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["participant", "import-csv"])

    assert result.exit_code == 0
    assert "Participants imported" in result.output

    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        rows = conn.execute(
            participants.select().order_by(participants.c.user_did)
        ).fetchall()
        assert [row.user_did for row in rows] == [
            "did:example:one",
            "did:example:two",
        ]
        statuses = {row.user_did: row.status for row in rows}
    assert statuses["did:example:one"] == "active"
    assert statuses["did:example:two"] == "inactive"
    urls = {row.user_did: row.feed_url for row in rows}
    assert urls["did:example:one"] == "https://feeds.example.com/one"


def test_cli_participant_add_inserts_new_participant(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url,survey_completed_at,prolific_id,study_type,audit_timestamp\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.cli._load_settings",
        lambda: Settings().with_overrides(
            mail_db_path=db_path,
            participants_csv_path=csv_path,
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "participant",
            "add",
            "--email",
            "new@example.com",
            "--did",
            "did:new",
            "--status",
            "active",
            "--type",
            "prolific",
            "--language",
            "nl",
            "--feed-url",
            "https://feeds.example.com/new",
            "--prolific-id",
            "12345",
            "--study-type",
            "pilot",
            "--survey-completed-at",
            "2025-10-01T12:00:00Z",
        ],
    )

    assert result.exit_code == 0
    assert "Participant did:new added" in result.output

    engine = get_mail_db_engine(db_path)
    with engine.connect() as conn:
        row = conn.execute(
            participants.select().where(participants.c.user_did == "did:new")
        ).mappings().first()
    assert row is not None
    assert row["email"] == "new@example.com"
    assert row["type"] == "prolific"
    assert row["language"] == "nl"
    assert row["feed_url"] == "https://feeds.example.com/new"
    assert row["prolific_id"] == "12345"
    assert row["study_type"] == "pilot"

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        records = list(reader)

    assert len(records) == 1
    record = records[0]
    assert record["did"] == "did:new"
    assert record["prolific_id"] == "12345"
    assert record["audit_timestamp"].strip()


def test_cli_participant_add_rejects_duplicates(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path, feed_url="https://feeds.example.com/dup")
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url,survey_completed_at,prolific_id,study_type,audit_timestamp\n"
        "cli@example.com,did:example:cli,active,pilot,https://feeds.example.com/dup,,,,\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.cli._load_settings",
        lambda: Settings().with_overrides(
            mail_db_path=db_path,
            participants_csv_path=csv_path,
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "participant",
            "add",
            "--email",
            "duplicate@example.com",
            "--did",
            "did:example:cli",
        ],
    )

    assert result.exit_code != 0
    assert "already exists" in result.output

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    # No new rows appended
    assert len(rows) == 1


def test_cli_participant_seed_completion(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert(),
            [
                {
                    "user_did": "did:admin",
                    "email": "admin@example.com",
                    "status": "active",
                    "type": "admin",
                    "language": "en",
                },
                {
                    "user_did": "did:test",
                    "email": "test@example.com",
                    "status": "active",
                    "type": "test",
                    "language": "en",
                },
                {
                    "user_did": "did:pilot",
                    "email": "pilot@example.com",
                    "status": "active",
                    "type": "pilot",
                    "language": "en",
                },
            ],
        )

    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url,survey_completed_at,prolific_id,study_type,audit_timestamp\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.cli._load_settings",
        lambda: Settings().with_overrides(
            mail_db_path=db_path,
            participants_csv_path=csv_path,
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "participant",
            "seed-completion",
            "--timestamp",
            "2025-10-01T09:00:00Z",
        ],
    )

    assert result.exit_code == 0
    assert "Seeded survey_completed_at for 2 participants" in result.output

    with engine.connect() as conn:
        rows = conn.execute(
            select(
                participants.c.user_did,
                participants.c.survey_completed_at,
            )
        ).mappings()
        data = {row["user_did"]: row["survey_completed_at"] for row in rows}

    assert data["did:admin"] is not None
    assert data["did:test"] is not None
    assert data["did:pilot"] is None

    repeat = runner.invoke(
        cli,
        [
            "participant",
            "seed-completion",
            "--timestamp",
            "2025-10-02T09:00:00Z",
        ],
    )
    assert repeat.exit_code == 0
    assert "No participants required seeding" in repeat.output

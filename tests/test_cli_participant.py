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


def _seed_participant(db_path: Path, *, status: str = "active") -> None:
    engine = get_mail_db_engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert().values(
                user_did="did:example:cli",
                email="cli@example.com",
                status=status,
                type="pilot",
                language="en",
            )
        )


def test_cli_participant_set_status_updates_db(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path)
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type\n" "cli@example.com,did:example:cli,active,pilot\n",
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
    assert contents[1] == "cli@example.com,did:example:cli,inactive,pilot"


def test_cli_participant_set_status_no_change(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    _seed_participant(db_path, status="inactive")
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type\n" "cli@example.com,did:example:cli,inactive,pilot\n",
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
    assert contents[1] == "cli@example.com,did:example:cli,inactive,pilot"


def test_cli_participant_set_status_missing_user(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text("email,did,status,type\n", encoding="utf-8")
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
        "email,did,status,type\n"
        "user1@example.com,did:example:one,active,pilot\n"
        "user2@example.com,did:example:two,inactive,admin\n",
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

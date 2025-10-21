from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from click.testing import CliRunner  # noqa: E402

from app.cli import cli  # noqa: E402
from app.config import Settings  # noqa: E402
from app.mail_db.migrations import apply_migrations  # noqa: E402
from app.mail_db.operations import (  # noqa: E402
    get_mail_db_engine,
    record_send_attempt,
)
from app.mail_db.schema import participants  # noqa: E402


def _seed_participant(db_path: Path, *, user_did: str, email: str) -> None:
    engine = get_mail_db_engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert().values(
                user_did=user_did,
                email=email,
                status="active",
                type="pilot",
                language="en",
                feed_url=f"https://feeds.example.com/{user_did.split(':')[-1]}",
            )
        )


def test_cli_status_lists_recent_attempts(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    csv_path = tmp_path / "participants.csv"
    apply_migrations(db_path)
    _seed_participant(db_path, user_did="did:one", email="one@example.com")
    _seed_participant(db_path, user_did="did:two", email="two@example.com")

    record_send_attempt(
        db_path,
        user_did="did:one",
        message_type="daily_update",
        mode="dry-run",
        status="sent",
        smtp_response="dry-run:/tmp/one.eml",
    )
    record_send_attempt(
        db_path,
        user_did="did:two",
        message_type="daily_update",
        mode="live",
        status="failed",
        smtp_response="550",
    )

    # ensure CSV exists so status can export if needed
    csv_path.write_text(
        "email,did,status,type,feed_url\n"
        "one@example.com,did:one,active,pilot,https://feeds.example.com/one\n"
        "two@example.com,did:two,active,pilot,https://feeds.example.com/two\n",
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
    result = runner.invoke(cli, ["status", "--limit", "5"])

    assert result.exit_code == 0
    output = result.output
    assert "Recent send attempts" in output
    assert "did:one" in output
    assert "dry-run" in output
    assert "did:two" in output
    assert "failed" in output


def test_cli_status_with_filters(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    csv_path = tmp_path / "participants.csv"
    apply_migrations(db_path)
    _seed_participant(db_path, user_did="did:three", email="three@example.com")

    record_send_attempt(
        db_path,
        user_did="did:three",
        message_type="daily_update",
        mode="live",
        status="sent",
    )
    record_send_attempt(
        db_path,
        user_did="did:three",
        message_type="reminder",
        mode="dry-run",
        status="queued",
    )

    csv_path.write_text(
        "email,did,status,type,feed_url\n"
        "three@example.com,did:three,active,pilot,https://feeds.example.com/three\n",
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
            "status",
            "--limit",
            "10",
            "--user-did",
            "did:three",
            "--message-type",
            "reminder",
        ],
    )

    assert result.exit_code == 0
    output = result.output
    assert "did:three" in output
    assert "reminder" in output
    assert "daily_update" not in output

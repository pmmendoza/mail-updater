import csv
from pathlib import Path

from app.mail_db.migrations import apply_migrations
from app.mail_db.operations import get_mail_db_engine
from app.mail_db.schema import participants as participants_table
from app.participants import load_participants


def test_participants_csv_integrity() -> None:
    """Ensure participant roster has expected structure and values."""
    csv_path = Path(__file__).resolve().parents[1] / "data" / "participants.csv"
    assert csv_path.exists(), "missing data/participants.csv"

    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["email", "did", "status", "type", "feed_url"]
        rows = list(reader)

    assert rows, "participants.csv must include at least one participant"

    allowed_status = {"active", "inactive"}
    allowed_types = {"prolific", "pilot", "admin", "tests"}

    seen_dids = set()
    for row in rows:
        assert row["email"], "email is required"
        assert row["did"].startswith("did:"), "did must include the did: prefix"
        assert row["status"] in allowed_status, f"unexpected status {row['status']!r}"
        assert row["type"] in allowed_types, f"unexpected type {row['type']!r}"
        assert row["did"] not in seen_dids, f"duplicate did {row['did']!r}"
        seen_dids.add(row["did"])

    assert any(
        row["email"] == "philipp.m.mendoza@gmail.com"
        and row["did"] == "did:plc:3vomhawgkjhtvw4euuxbll3r"
        and row["status"] == "active"
        and row["type"] == "admin"
        for row in rows
    ), "seed admin participant row missing"


def test_load_participants_prefers_mail_db(tmp_path: Path) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            participants_table.insert().values(
                user_did="did:db:1",
                email="db@example.com",
                status="inactive",
                type="pilot",
                language="nl",
                feed_url="https://feeds.example.com/db",
            )
        )

    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "email,did,status,type,feed_url\n"
        "csv@example.com,did:csv:1,active,pilot,https://feeds.example.com/csv\n",
        encoding="utf-8",
    )

    participants = load_participants(csv_path, mail_db_path=db_path)
    assert [p.user_did for p in participants] == ["did:db:1"]
    participant = participants[0]
    assert participant.email == "db@example.com"
    assert participant.language == "nl"
    assert participant.include_in_emails is False
    assert participant.feed_url == "https://feeds.example.com/db"

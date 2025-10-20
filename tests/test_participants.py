import csv
from pathlib import Path


def test_participants_csv_integrity() -> None:
    """Ensure participant roster has expected structure and values."""
    csv_path = Path(__file__).resolve().parents[1] / "data" / "participants.csv"
    assert csv_path.exists(), "missing data/participants.csv"

    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["email", "did", "status", "type"]
        rows = list(reader)

    assert rows, "participants.csv must include at least one participant"

    allowed_status = {"active", "inactive"}
    allowed_types = {"prolific", "pilot", "admin", "tests"}

    for row in rows:
        assert row["email"], "email is required"
        assert row["did"].startswith("did:"), "did must include the did: prefix"
        assert row["status"] in allowed_status, f"unexpected status {row['status']!r}"
        assert row["type"] in allowed_types, f"unexpected type {row['type']!r}"

    sample = rows[0]
    assert sample["email"] == "philipp.m.mendoza@gmail.com"
    assert sample["did"] == "did:plc:3vomhawgkjhtvw4euuxbll3r"
    assert sample["status"] == "active"
    assert sample["type"] == "admin"

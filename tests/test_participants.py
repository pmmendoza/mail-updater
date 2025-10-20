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

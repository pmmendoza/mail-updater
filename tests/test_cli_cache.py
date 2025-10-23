import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from click.testing import CliRunner  # noqa: E402

from app.cli import cli  # noqa: E402
from app.compliance_snapshot import DailySnapshot  # noqa: E402
from app.config import Settings  # noqa: E402
from app.mail_db.migrations import apply_migrations  # noqa: E402
from app.mail_db.operations import get_mail_db_engine  # noqa: E402
from app.mail_db.schema import compliance_monitoring, participants  # noqa: E402


def test_cache_daily_snapshots_writes_rows(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mail.sqlite"
    apply_migrations(db_path)
    engine = get_mail_db_engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            participants.insert().values(
                user_did="did:one",
                email="one@example.com",
                status="active",
                type="pilot",
                language="en",
            )
        )

    settings = Settings().with_overrides(
        mail_db_path=db_path,
        compliance_db_path=tmp_path / "compliance.sqlite",
    )
    settings.requirements = {
        "defaults": {"min_engagement": 2, "min_retrievals": 1},
        "pilot": {},
    }

    settings.compliance_db_path.touch()

    monkeypatch.setattr("app.cli._load_settings", lambda: settings)

    snapshots = [
        DailySnapshot(
            study_day=datetime(2025, 10, 1).date(),
            retrievals=1,
            engagements=2,
            active_day=True,
            cumulative_active=1,
            on_track=True,
            engagement_breakdown={"like": 2},
        ),
        DailySnapshot(
            study_day=datetime(2025, 10, 2).date(),
            retrievals=0,
            engagements=0,
            active_day=False,
            cumulative_active=1,
            on_track=False,
            engagement_breakdown={},
        ),
    ]

    monkeypatch.setattr(
        "app.cli.get_daily_engagement_breakdown",
        lambda *args, **kwargs: snapshots,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["cache-daily-snapshots", "--study", "pilot"])

    assert result.exit_code == 0
    assert "Cached 2 compliance_monitoring rows" in result.output

    with engine.connect() as conn:
        stored = conn.execute(
            compliance_monitoring.select().order_by(
                compliance_monitoring.c.snapshot_date
            )
        ).mappings().all()

    assert len(stored) == 2
    assert stored[0]["active_day"] == 1
    assert stored[0]["cumulative_active"] == 1
    assert stored[1]["cumulative_skip"] == 1

"""Initialize or migrate the mail.db SQLite database."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.mail_db.migrations import apply_migrations


def main() -> None:
    settings = Settings()
    settings.ensure_mail_db_parent()
    target = apply_migrations(settings.mail_db_path)
    path: Path = settings.mail_db_path
    print(f"mail.db migrated to schema version {target} at {path}")


if __name__ == "__main__":
    main()

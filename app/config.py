"""Configuration helpers for the mail updater MVP."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Optional
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"

# Load environment variables if a .env file exists.
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


def _str_to_bool(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _default_path(env_var: str, fallback: Path) -> Path:
    value = os.getenv(env_var)
    if value:
        return Path(value).expanduser().resolve()
    return fallback.resolve()


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    tz: str = os.getenv("TZ", "Europe/Amsterdam")
    compliance_db_path: Path = _default_path(
        "COMPLIANCE_DB_PATH", BASE_DIR.parent / "compliance-tracker" / "compliance.db"
    )
    mail_db_path: Path = _default_path(
        "MAIL_DB_PATH", BASE_DIR / "mail.db" / "mail.sqlite"
    )
    participants_csv_path: Path = _default_path(
        "PARTICIPANTS_CSV_PATH", BASE_DIR.parent / "data" / "participants.csv"
    )
    window_days: int = int(os.getenv("WINDOW_DAYS", "14"))
    required_active_days: int = int(os.getenv("REQUIRED_ACTIVE_DAYS", "10"))
    cutoff_hour_local: int = int(os.getenv("CUTOFF_HOUR_LOCAL", "5"))
    send_hour_local: int = int(os.getenv("SEND_HOUR_LOCAL", "9"))

    smtp_host: str = os.getenv("SMTP_HOST", "localhost")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: Optional[str] = os.getenv("SMTP_USERNAME")
    smtp_password: Optional[str] = os.getenv("SMTP_PASSWORD")
    smtp_use_ssl: bool = _str_to_bool(os.getenv("SMTP_USE_SSL"), default=False)
    smtp_from: str = os.getenv(
        "SMTP_FROM", "Bluesky Feed Project <noreply@example.com>"
    )
    smtp_reply_to: Optional[str] = os.getenv("SMTP_REPLY_TO")
    smtp_dry_run: bool = _str_to_bool(os.getenv("SMTP_DRY_RUN"), default=True)

    outbox_dir: Path = _default_path("OUTBOX_DIR", BASE_DIR / "outbox")
    send_log_path: Path = _default_path(
        "SEND_LOG_PATH", BASE_DIR / "outbox" / "send_log.jsonl"
    )
    mail_subject: str = os.getenv(
        "MAIL_SUBJECT", "Bluesky Feed Project: daily progress update"
    )
    qualtrics_base_url: Optional[str] = os.getenv("QUALTRICS_BASE_URL")
    qualtrics_api_token: Optional[str] = os.getenv("QUALTRICS_API_TOKEN")
    qualtrics_survey_filter: Optional[str] = os.getenv("QUALTRICS_SURVEY_FILTER")

    def ensure_outbox(self) -> None:
        """Create directories used by the mailer if missing."""
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.send_log_path.parent.mkdir(parents=True, exist_ok=True)

    def ensure_mail_db_parent(self) -> None:
        """Create the parent directory for mail.db if missing."""
        self.mail_db_path.parent.mkdir(parents=True, exist_ok=True)

    def with_overrides(self, **overrides: Any) -> "Settings":
        """Return a copy of the settings with specified attributes replaced."""
        return replace(self, **overrides)

    def to_dict(self) -> Dict[str, Any]:
        """Expose a dict representation for debugging/logging."""
        return {
            "tz": self.tz,
            "compliance_db_path": str(self.compliance_db_path),
            "mail_db_path": str(self.mail_db_path),
            "participants_csv_path": str(self.participants_csv_path),
            "window_days": self.window_days,
            "required_active_days": self.required_active_days,
            "cutoff_hour_local": self.cutoff_hour_local,
            "send_hour_local": self.send_hour_local,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_username": self.smtp_username,
            "smtp_use_ssl": self.smtp_use_ssl,
            "smtp_from": self.smtp_from,
            "smtp_reply_to": self.smtp_reply_to,
            "smtp_dry_run": self.smtp_dry_run,
            "outbox_dir": str(self.outbox_dir),
            "send_log_path": str(self.send_log_path),
            "mail_subject": self.mail_subject,
            "qualtrics_base_url": self.qualtrics_base_url,
            "qualtrics_api_token": bool(self.qualtrics_api_token),
            "qualtrics_survey_filter": self.qualtrics_survey_filter,
        }

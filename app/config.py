"""Configuration helpers for the mail updater MVP."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Optional
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"
DEFAULT_CONFIG_PATH = BASE_DIR / "app" / "default_config.yml"
USER_CONFIG_PATH = BASE_DIR / "user_config.yml"

# Load environment variables if a .env file exists.
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


def _convert_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"", "~", "null", "Null", "NULL"}:
        return None
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "yes", "y", "on", "1"}:
        return True
    if lowered in {"false", "no", "n", "off", "0"}:
        return False
    try:
        if value.startswith("0") and value != "0":
            int(value, 10)
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    root: Dict[str, Any] = {}
    stack: list[tuple[int, Dict[str, Any]]] = [(0, root)]
    with path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.rstrip()
            if not line:
                continue
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(line) - len(stripped)
            if indent % 2 != 0:
                raise ValueError(f"Invalid indentation in {path}: '{line}'")

            while stack and indent < stack[-1][0]:
                stack.pop()
            current = stack[-1][1] if stack else root

            key, sep, value = stripped.partition(":")
            key = key.strip()
            if not sep:
                raise ValueError(f"Missing ':' in config line: '{line}'")

            value = value.strip()
            if not value:
                new_section: Dict[str, Any] = {}
                current[key] = new_section
                stack.append((indent + 2, new_section))
            else:
                current[key] = _convert_scalar(value)

    return root


def _merge_config(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_config(dict(base[key]), value)
        else:
            base[key] = value
    return base


CONFIG: Dict[str, Any] = {}
CONFIG = _merge_config(CONFIG, _load_yaml(DEFAULT_CONFIG_PATH))
CONFIG = _merge_config(CONFIG, _load_yaml(USER_CONFIG_PATH))


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


def _config_get(path: str, default: Any = None) -> Any:
    current: Any = CONFIG
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _config_path(config_path: str, env_var: str, fallback: Path) -> Path:
    value = _config_get(config_path)
    if value:
        return Path(value).expanduser().resolve()
    return _default_path(env_var, fallback)


def _config_int(config_path: str, env_var: str, default: int) -> int:
    value = _config_get(config_path)
    if value is not None:
        return int(value)
    env_value = os.getenv(env_var)
    if env_value is not None:
        return int(env_value)
    return default


def _config_bool(config_path: str, env_var: str, default: bool) -> bool:
    value = _config_get(config_path)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _str_to_bool(value, default=default)
    env_value = os.getenv(env_var)
    return _str_to_bool(env_value, default=default)


def _config_optional_str(
    config_path: str, env_var: str, default: Optional[str] = None
) -> Optional[str]:
    value = _config_get(config_path)
    if value is not None:
        return str(value)
    env_value = os.getenv(env_var)
    if env_value is not None:
        return env_value
    return default


def _config_dict(path: str) -> Dict[str, Any]:
    value = _config_get(path, {})
    if isinstance(value, dict):
        return deepcopy(value)
    return {}


def _config_str(config_path: str, env_var: str, default: str) -> str:
    value = _config_optional_str(config_path, env_var, default)
    if value is None:
        raise ValueError(f"Missing configuration for {config_path}")
    return value


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    tz: str = _config_str("general.tz", "TZ", "Europe/Amsterdam")
    compliance_db_path: Path = _config_path(
        "paths.compliance_db_path",
        "COMPLIANCE_DB_PATH",
        BASE_DIR.parent / "compliance-tracker" / "compliance.db",
    )
    mail_db_path: Path = _config_path(
        "paths.mail_db_path",
        "MAIL_DB_PATH",
        BASE_DIR / "mail.db" / "mail.sqlite",
    )
    participants_csv_path: Path = _config_path(
        "paths.participants_csv_path",
        "PARTICIPANTS_CSV_PATH",
        BASE_DIR.parent / "data" / "participants.csv",
    )
    window_days: int = _config_int("general.window_days", "WINDOW_DAYS", 14)
    required_active_days: int = _config_int(
        "general.required_active_days", "REQUIRED_ACTIVE_DAYS", 10
    )
    cutoff_hour_local: int = _config_int(
        "general.cutoff_hour_local", "CUTOFF_HOUR_LOCAL", 5
    )
    send_hour_local: int = _config_int("general.send_hour_local", "SEND_HOUR_LOCAL", 9)

    smtp_host: str = _config_str("mailer.host", "SMTP_HOST", "localhost")
    smtp_port: int = _config_int("mailer.port", "SMTP_PORT", 587)
    smtp_username: Optional[str] = _config_optional_str(
        "mailer.username", "SMTP_USERNAME"
    )
    smtp_password: Optional[str] = os.getenv("SMTP_PASSWORD")
    smtp_use_ssl: bool = _config_bool("mailer.use_ssl", "SMTP_USE_SSL", False)
    smtp_from: str = _config_str(
        "mailer.from", "SMTP_FROM", "Bluesky Feed Project <noreply@example.com>"
    )
    smtp_reply_to: Optional[str] = _config_optional_str(
        "mailer.reply_to", "SMTP_REPLY_TO"
    )
    smtp_dry_run: bool = _config_bool("mailer.dry_run", "SMTP_DRY_RUN", True)

    outbox_dir: Path = _config_path(
        "paths.outbox_dir", "OUTBOX_DIR", BASE_DIR / "outbox"
    )
    send_log_path: Path = _config_path(
        "paths.send_log_path", "SEND_LOG_PATH", BASE_DIR / "outbox" / "send_log.jsonl"
    )
    mail_subject: str = _config_str(
        "mailer.subject", "MAIL_SUBJECT", "Bluesky Feed Project: daily progress update"
    )
    qualtrics_base_url: Optional[str] = _config_optional_str(
        "qualtrics.base_url", "QUALTRICS_BASE_URL"
    )
    qualtrics_api_token: Optional[str] = os.getenv("QUALTRICS_API_TOKEN")
    qualtrics_survey_filter: Optional[str] = _config_optional_str(
        "qualtrics.survey_filter", "QUALTRICS_SURVEY_FILTER"
    )
    qualtrics_survey_id: Optional[str] = _config_optional_str(
        "qualtrics.survey_id", "QUALTRICS_SURVEY_ID"
    )

    imap_host: Optional[str] = _config_optional_str("imap.host", "IMAP_HOST")
    imap_port: int = _config_int("imap.port", "IMAP_PORT", 993)
    imap_username: Optional[str] = _config_optional_str(
        "imap.username", "IMAP_USERNAME"
    )
    imap_password: Optional[str] = os.getenv("IMAP_PASSWORD")
    imap_mailbox: str = _config_str("imap.mailbox", "IMAP_MAILBOX", "INBOX")
    imap_use_ssl: bool = _config_bool("imap.use_ssl", "IMAP_USE_SSL", True)

    feedgen_hostname: Optional[str] = _config_optional_str(
        "services.feedgen_hostname", "FEEDGEN_HOSTNAME"
    )
    feedgen_listenhost: Optional[str] = _config_optional_str(
        "services.feedgen_listenhost", "FEEDGEN_LISTENHOST"
    )

    requirements: Dict[str, Any] = field(
        default_factory=lambda: _config_dict("requirements")
    )

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
            "qualtrics_survey_id": self.qualtrics_survey_id,
            "imap_host": self.imap_host,
            "imap_port": self.imap_port,
            "imap_username": self.imap_username,
            "imap_mailbox": self.imap_mailbox,
            "imap_use_ssl": self.imap_use_ssl,
            "feedgen_hostname": self.feedgen_hostname,
            "feedgen_listenhost": self.feedgen_listenhost,
            "requirements": deepcopy(self.requirements),
        }

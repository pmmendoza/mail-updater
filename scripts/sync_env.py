#!/usr/bin/env python3
"""
Add any missing key-value pairs from .env.template into .env without overwriting existing values.
"""

from __future__ import annotations

import sys
from pathlib import Path


def load_keys(path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE lines, ignoring comments and blanks."""
    keys: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        keys[key.strip()] = value.strip()
    return keys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    template_path = root / ".env.template"
    env_path = root / ".env"

    if not template_path.exists():
        print("Missing .env.template; nothing to sync.", file=sys.stderr)
        return 0

    env_path.touch(exist_ok=True)
    env_content = env_path.read_text()

    if not env_content.strip():
        env_path.write_text(template_path.read_text())
        print("Initialized .env from .env.template")
        return 0

    template_keys = load_keys(template_path)
    env_keys = load_keys(env_path)

    missing_items = {
        key: value for key, value in template_keys.items() if key not in env_keys
    }

    if not missing_items:
        print(".env already contains all keys from .env.template")
        return 0

    lines_to_append = [f"{key}={value}" for key, value in missing_items.items()]

    with env_path.open("a", encoding="utf-8") as handle:
        if env_content and not env_content.endswith("\n"):
            handle.write("\n")
        handle.write("\n# Added by sync_env.py to match .env.template\n")
        for line in lines_to_append:
            handle.write(f"{line}\n")

    added_keys = ", ".join(sorted(missing_items))
    print(f"Appended missing keys to .env: {added_keys}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

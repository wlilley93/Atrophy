#!/usr/bin/env python3
"""Migrate non-secret settings from .env to ~/.atrophy/config.json.

Reads the project .env file, identifies settings vs secrets, moves settings
into config.json, and leaves only secrets in .env.

Safe to run multiple times — only migrates keys not already in config.json.
"""
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
CONFIG_PATH = Path.home() / ".atrophy" / "config.json"

# Keys that are secrets and should STAY in .env
SECRET_KEYS = {
    "ELEVENLABS_API_KEY",
    "FAL_KEY",
    "TELEGRAM_BOT_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
}

# Keys that look like secrets (heuristic)
SECRET_PATTERNS = [
    re.compile(r".*_KEY$"),
    re.compile(r".*_SECRET$"),
    re.compile(r".*_TOKEN$"),
    re.compile(r".*_PASSWORD$"),
]


def is_secret(key: str) -> bool:
    if key in SECRET_KEYS:
        return True
    return any(p.match(key) for p in SECRET_PATTERNS)


def parse_env(path: Path) -> list[tuple[str, str, str]]:
    """Parse .env file. Returns list of (key, value, raw_line)."""
    entries = []
    if not path.exists():
        return entries
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            entries.append(("", "", line))
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", stripped)
        if match:
            entries.append((match.group(1), match.group(2), line))
        else:
            entries.append(("", "", line))
    return entries


def main():
    if not ENV_PATH.exists():
        print("No .env file found — nothing to migrate.")
        return

    entries = parse_env(ENV_PATH)
    if not entries:
        print(".env is empty — nothing to migrate.")
        return

    # Load existing config.json
    config = {}
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            config = {}

    migrated = []
    secrets_kept = []
    remaining_lines = []

    for key, value, raw_line in entries:
        if not key:
            remaining_lines.append(raw_line)
            continue

        if is_secret(key):
            secrets_kept.append(key)
            remaining_lines.append(raw_line)
            continue

        # Non-secret setting — migrate to config.json if not already there
        if key not in config:
            config[key] = value
            migrated.append(key)
            print(f"  Migrated: {key}={value}")
        else:
            print(f"  Skipped (already in config.json): {key}")

    if migrated:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
        print(f"\nWrote {len(migrated)} setting(s) to {CONFIG_PATH}")

        # Rewrite .env with only secrets
        ENV_PATH.write_text("\n".join(remaining_lines).strip() + "\n")
        print(f"Updated .env — {len(secrets_kept)} secret(s) remain.")
    else:
        print("\nNothing to migrate — all .env entries are secrets (or already in config.json).")

    if secrets_kept:
        print(f"\nSecrets kept in .env: {', '.join(secrets_kept)}")


if __name__ == "__main__":
    main()

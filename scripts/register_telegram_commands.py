#!/usr/bin/env python3
"""Register Telegram bot commands with BotFather via the Bot API.

Scans all enabled agents and registers /agent_name commands so users
get autocomplete in the Telegram command menu. Also registers utility
commands like /status and /mute.

Usage:
    python scripts/register_telegram_commands.py           # register all
    python scripts/register_telegram_commands.py --clear   # remove all commands
"""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from config import TELEGRAM_BOT_TOKEN, USER_DATA, BUNDLE_ROOT
from core.agent_manager import discover_agents


def _api_post(method: str, payload: dict) -> dict | None:
    """POST to Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result if result.get("ok") else None
    except Exception as e:
        print(f"API error: {e}")
        return None


def _build_commands() -> list[dict]:
    """Build command list from agent registry."""
    commands = []

    for agent in discover_agents():
        name = agent["name"]

        # Load manifest for description
        manifest = {}
        for base in [USER_DATA / "agents" / name, BUNDLE_ROOT / "agents" / name]:
            mpath = base / "data" / "agent.json"
            if mpath.exists():
                try:
                    manifest = json.loads(mpath.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
                break

        desc = manifest.get("description", f"Talk to {name.replace('_', ' ').title()}")
        # Telegram limits command descriptions to 256 chars
        if len(desc) > 256:
            desc = desc[:253] + "..."

        commands.append({
            "command": name,
            "description": desc[:256],
        })

    # Utility commands
    commands.extend([
        {"command": "status", "description": "Show which agents are active"},
        {"command": "mute", "description": "Mute/unmute the current agent"},
    ])

    return commands


def register():
    """Register commands with the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not configured")
        sys.exit(1)

    commands = _build_commands()
    print(f"Registering {len(commands)} commands:")
    for cmd in commands:
        print(f"  /{cmd['command']} — {cmd['description'][:60]}")

    result = _api_post("setMyCommands", {"commands": commands})
    if result:
        print("Done — commands registered.")
    else:
        print("Failed to register commands.")
        sys.exit(1)


def clear():
    """Remove all bot commands."""
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not configured")
        sys.exit(1)

    result = _api_post("deleteMyCommands", {})
    if result:
        print("Done — all commands cleared.")
    else:
        print("Failed to clear commands.")
        sys.exit(1)


if __name__ == "__main__":
    if "--clear" in sys.argv:
        clear()
    else:
        register()

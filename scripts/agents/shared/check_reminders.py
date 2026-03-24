#!/usr/bin/env python3
"""Check and fire due reminders.

Runs every minute via launchd. Reads reminders from the agent's
reminder store, fires notifications + queues messages for any
that are due, then removes them.

Reminders are stored in agents/<name>/data/.reminders.json:
[
  {
    "id": "uuid",
    "time": "2024-03-10T14:30:00",
    "message": "Take out the bins",
    "source": "will",
    "created_at": "2024-03-10T12:00:00"
  }
]
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(Path.home() / ".atrophy" / ".env")

from config import DATA_DIR, MESSAGE_QUEUE, AGENT_DISPLAY_NAME
from core.queue import queue_message

REMINDERS_FILE = DATA_DIR / ".reminders.json"


def _load_reminders() -> list[dict]:
    if not REMINDERS_FILE.exists():
        return []
    try:
        return json.loads(REMINDERS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_reminders(reminders: list[dict]):
    REMINDERS_FILE.write_text(json.dumps(reminders, indent=2) + "\n")


def _notify(title: str, body: str):
    """macOS notification + sound."""
    body_escaped = body.replace('"', '\\"').replace('\n', ' ')
    title_escaped = title.replace('"', '\\"')
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{body_escaped}" with title "{title_escaped}" sound name "Glass"'],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def check_reminders():
    reminders = _load_reminders()
    if not reminders:
        return

    now = datetime.now()
    due = []
    remaining = []

    for r in reminders:
        try:
            remind_time = datetime.fromisoformat(r["time"])
        except (ValueError, KeyError):
            remaining.append(r)
            continue

        if remind_time <= now:
            due.append(r)
        else:
            remaining.append(r)

    if not due:
        return

    # Fire due reminders
    for r in due:
        msg = r.get("message", "Reminder")
        print(f"[reminder] Firing: {msg}")

        # macOS notification with sound
        _notify(f"Reminder - {AGENT_DISPLAY_NAME}", msg)

        # Queue for next app interaction
        queue_message(MESSAGE_QUEUE, f"Reminder: {msg}", source="reminder")

        # Send via Telegram if configured
        try:
            from channels.telegram import send_message
            send_message(f"⏰ Reminder: {msg}")
        except Exception:
            pass

    # Save remaining
    _save_reminders(remaining)
    print(f"[reminder] Fired {len(due)}, {len(remaining)} remaining.")


if __name__ == "__main__":
    check_reminders()

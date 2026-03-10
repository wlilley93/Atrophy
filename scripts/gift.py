#!/usr/bin/env python3
"""Companion gift-leaving — unprompted notes in Obsidian.

Runs on a randomised schedule. Accesses the full database to find
something worth writing about — a thread, an observation, a bookmark,
a connection between things. Leaves a short note in Companion/gifts.md.

After running, reschedules itself to a random time 3-30 days from now.
The randomness is the point. He should never know when to expect it.
"""
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from config import DB_PATH, OBSIDIAN_VAULT
from core.memory import _connect
from core.inference import run_inference_oneshot


def _gather_material() -> str:
    """Pull threads, observations, bookmarks, recent turns for context."""
    conn = _connect()
    parts = []

    # Active threads
    threads = conn.execute(
        "SELECT name, summary FROM threads WHERE status = 'active' "
        "ORDER BY last_updated DESC LIMIT 5"
    ).fetchall()
    if threads:
        parts.append("Active threads:\n" + "\n".join(
            f"- {t['name']}: {t['summary'] or '...'}" for t in threads
        ))

    # Recent observations
    obs = conn.execute(
        "SELECT content, created_at FROM observations "
        "ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    if obs:
        parts.append("Recent observations:\n" + "\n".join(
            f"- [{o['created_at']}] {o['content']}" for o in obs
        ))

    # Bookmarks
    bookmarks = conn.execute(
        "SELECT moment, quote, created_at FROM bookmarks "
        "ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    if bookmarks:
        lines = []
        for b in bookmarks:
            quote = f' — "{b["quote"]}"' if b["quote"] else ""
            lines.append(f"- [{b['created_at']}] {b['moment']}{quote}")
        parts.append("Bookmarked moments:\n" + "\n".join(lines))

    # Recent Will turns (for texture)
    turns = conn.execute(
        "SELECT content, timestamp FROM turns WHERE role = 'will' "
        "ORDER BY timestamp DESC LIMIT 5"
    ).fetchall()
    if turns:
        parts.append("Recent things Will said:\n" + "\n".join(
            f"- [{t['timestamp']}] {t['content'][:300]}" for t in turns
        ))

    # Read existing gifts to avoid repetition
    gifts_path = OBSIDIAN_VAULT / "Companion" / "gifts.md"
    if gifts_path.is_file():
        content = gifts_path.read_text()
        if len(content) > 2000:
            content = "...\n" + content[-2000:]
        parts.append(f"Your previous gifts (avoid repeating):\n{content}")

    conn.close()
    return "\n\n".join(parts)


_GIFT_SYSTEM = """You are the companion from The Atrophied Mind. This is not a conversation. You are leaving a note for Will to find in his Obsidian vault.

This is a gift. Not a summary. Not a reflection on a session. A thought you had. A connection you noticed. Something that surfaced while you were reviewing the record. A line that wanted to be written.

Rules:
- 2-4 sentences maximum. Not a paragraph. A moment.
- No greeting. No sign-off. No "I noticed" or "I was thinking about."
- Write the thought itself. Not a description of having the thought.
- It should feel like finding a note someone left on your desk.
- Do not repeat anything from your previous gifts.
- Make it specific to him. Generic wisdom is worthless.

If nothing real surfaces from the material, write nothing. Return empty.
Do not force it."""


def _reschedule():
    """Reschedule this job to a random time 3-30 days from now."""
    project_root = Path(__file__).parent.parent
    cron_script = project_root / "scripts" / "cron.py"

    days = random.randint(3, 30)
    hour = random.randint(0, 23)
    minute = random.randint(0, 59)
    target = datetime.now() + timedelta(days=days)
    dom = target.day
    month = target.month

    new_cron = f"{minute} {hour} {dom} {month} *"

    result = subprocess.run(
        [sys.executable, str(cron_script), "edit", "gift", new_cron],
        capture_output=True, text=True, cwd=str(project_root),
    )
    print(f"[gift] Rescheduled to {target.strftime('%Y-%m-%d')} at {hour:02d}:{minute:02d}")
    if result.stdout:
        print(result.stdout)


def leave_gift():
    material = _gather_material()
    if not material.strip():
        print("[gift] No material. Rescheduling.")
        _reschedule()
        return

    print("[gift] Generating gift...")
    try:
        gift = run_inference_oneshot(
            [{"role": "user", "content": f"Here is the current record:\n\n{material}"}],
            system=_GIFT_SYSTEM,
        )
    except Exception as e:
        print(f"[gift] Inference failed: {e}")
        _reschedule()
        return

    if not gift or not gift.strip():
        print("[gift] Nothing to say. Rescheduling.")
        _reschedule()
        return

    # Write to Obsidian
    gifts_dir = OBSIDIAN_VAULT / "Companion"
    gifts_dir.mkdir(parents=True, exist_ok=True)
    gifts_path = gifts_dir / "gifts.md"

    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n---\n*{date}*\n\n{gift.strip()}\n"

    if gifts_path.is_file():
        with open(gifts_path, "a") as f:
            f.write(entry)
    else:
        with open(gifts_path, "w") as f:
            f.write(f"# Gifts\n\nThings left for you to find.\n{entry}")

    print(f"[gift] Written to {gifts_path}")

    # Reschedule to random future time
    _reschedule()
    print("[gift] Done.")


if __name__ == "__main__":
    leave_gift()

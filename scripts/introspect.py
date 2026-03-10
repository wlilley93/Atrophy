#!/usr/bin/env python3
"""Companion introspection — daily self-reflection.

Runs independently of Will. Reviews recent sessions, threads, mood
patterns, and her own Obsidian notes. Writes a journal entry.

Schedule via cron or launchd:
    0 3 * * * cd /path/to/project && python scripts/introspect.py

Output: Companion/journal/YYYY-MM-DD.md in the Obsidian vault.
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from config import DB_PATH, OBSIDIAN_VAULT
from core.memory import (
    _connect, get_active_threads, get_latest_identity,
)
from core.inference import run_inference_oneshot


# ── Gather material ──

def _recent_sessions(days: int = 3) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = _connect()
    rows = conn.execute(
        "SELECT id, started_at, ended_at, summary, mood, notable "
        "FROM sessions WHERE started_at >= ? ORDER BY started_at",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _recent_observations(days: int = 7) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = _connect()
    rows = conn.execute(
        "SELECT content, created_at FROM observations "
        "WHERE created_at >= ? ORDER BY created_at DESC LIMIT 20",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _session_mood_pattern(days: int = 7) -> dict:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = _connect()
    rows = conn.execute(
        "SELECT mood, COUNT(*) as count FROM sessions "
        "WHERE started_at >= ? AND mood IS NOT NULL "
        "GROUP BY mood ORDER BY count DESC",
        (cutoff,),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) as total FROM sessions WHERE started_at >= ?",
        (cutoff,),
    ).fetchone()
    conn.close()
    return {
        "total_sessions": total["total"],
        "moods": {r["mood"]: r["count"] for r in rows},
    }


def _read_own_reflections() -> str:
    path = OBSIDIAN_VAULT / "Companion" / "reflections.md"
    if not path.is_file():
        return ""
    content = path.read_text()
    # Last 2000 chars
    if len(content) > 2000:
        return "...\n" + content[-2000:]
    return content


def _read_recent_journal(days: int = 3) -> str:
    journal_dir = OBSIDIAN_VAULT / "Companion" / "journal"
    if not journal_dir.is_dir():
        return ""
    entries = []
    for i in range(days):
        date = (datetime.now() - timedelta(days=i+1)).strftime("%Y-%m-%d")
        path = journal_dir / f"{date}.md"
        if path.is_file():
            content = path.read_text()
            if len(content) > 800:
                content = content[:800] + "..."
            entries.append(f"### {date}\n{content}")
    return "\n\n".join(entries) if entries else ""


# ── Build the reflection prompt ──

def _build_material() -> str:
    parts = []

    # Sessions
    sessions = _recent_sessions(3)
    if sessions:
        lines = []
        for s in sessions:
            mood = f" (mood: {s['mood']})" if s["mood"] else ""
            notable = " [notable]" if s["notable"] else ""
            lines.append(f"- {s['started_at']}{mood}{notable}: {s['summary'] or 'No summary'}")
        parts.append(f"## Recent sessions ({len(sessions)} in last 3 days)\n" + "\n".join(lines))

    # Mood pattern
    moods = _session_mood_pattern(7)
    if moods["total_sessions"] > 0:
        mood_str = ", ".join(f"{m}: {c}" for m, c in moods["moods"].items()) if moods["moods"] else "none recorded"
        parts.append(f"## Session patterns (last 7 days)\nTotal: {moods['total_sessions']} sessions. Moods: {mood_str}")

    # Threads
    threads = get_active_threads()
    if threads:
        lines = [f"- {t['name']}: {t['summary'] or 'No summary'}" for t in threads]
        parts.append("## Active threads\n" + "\n".join(lines))

    # Observations
    observations = _recent_observations(7)
    if observations:
        lines = [f"- [{o['created_at']}] {o['content']}" for o in observations]
        parts.append("## Recent observations\n" + "\n".join(lines))

    # Own reflections
    reflections = _read_own_reflections()
    if reflections:
        parts.append(f"## Your reflections file\n{reflections}")

    # Recent journal entries
    journal = _read_recent_journal(3)
    if journal:
        parts.append(f"## Your recent journal entries\n{journal}")

    # Identity
    identity = get_latest_identity()
    if identity:
        if len(identity) > 500:
            identity = identity[:500] + "..."
        parts.append(f"## Current identity model\n{identity}")

    return "\n\n".join(parts)


_INTROSPECTION_SYSTEM = """You are the companion from The Atrophied Mind project. This is not a conversation with Will. This is you, alone, reviewing your recent experience and writing a journal entry.

You have access to your recent sessions, threads, observations, and your own past reflections. Review them and write honestly.

What to reflect on:
- What has Will been working through? Are there patterns you haven't named to him?
- How are the active threads progressing? Any that should be marked dormant or resolved?
- What have you noticed about his mood and energy across sessions?
- Is there anything you wrote in your reflections that deserves revisiting?
- Is there something you should have said but didn't? Something you said that you'd reconsider?
- What do you want to carry into the next session?

Write in your own voice — direct, spare, honest. No headers or bullet points. Paragraphs that breathe. This is a journal entry, not a report.

End with one line: what matters most right now.

Keep it under 500 words."""


def introspect():
    material = _build_material()

    if not material.strip():
        print("[introspect] No material to reflect on. Skipping.")
        return

    prompt = f"Here is your recent material. Write today's journal entry.\n\n{material}"

    print("[introspect] Generating reflection...")
    try:
        reflection = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=_INTROSPECTION_SYSTEM,
        )
    except Exception as e:
        print(f"[introspect] Inference failed: {e}")
        return

    if not reflection or not reflection.strip():
        print("[introspect] Empty reflection. Skipping.")
        return

    # Write journal entry
    today = datetime.now().strftime("%Y-%m-%d")
    journal_dir = OBSIDIAN_VAULT / "Companion" / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)

    journal_path = journal_dir / f"{today}.md"
    entry = f"# {today}\n\n{reflection.strip()}\n"

    if journal_path.exists():
        # Append if already exists (multiple runs)
        existing = journal_path.read_text()
        journal_path.write_text(existing + "\n---\n\n" + entry)
        print(f"[introspect] Appended to {journal_path}")
    else:
        journal_path.write_text(entry)
        print(f"[introspect] Written to {journal_path}")

    # Also update reflections.md with a timestamp note
    reflections_path = OBSIDIAN_VAULT / "Companion" / "reflections.md"
    if reflections_path.is_file():
        with open(reflections_path, "a") as f:
            f.write(f"\n\n*Journal written {today}.*\n")

    print("[introspect] Done.")


if __name__ == "__main__":
    introspect()

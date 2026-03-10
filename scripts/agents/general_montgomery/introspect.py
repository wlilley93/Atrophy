#!/usr/bin/env python3
"""General Montgomery — after-action review.

Runs independently of Will. Accesses the full database — every session,
every observation, every thread. Reviews the intelligence record and
writes an assessment journal entry.

The goal is not reflection. The goal is sharper assessment.

Output: general_montgomery/notes/journal/YYYY-MM-DD.md in Obsidian.
"""
import os
import sys
import random
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from config import DB_PATH, OBSIDIAN_AGENT_DIR, OBSIDIAN_AGENT_NOTES, AGENT_NAME
from core.memory import _connect, get_latest_identity
from core.inference import run_inference_oneshot
from core.prompts import load_prompt


# ── Full database access ──

def _session_arc() -> dict:
    conn = _connect()
    first = conn.execute(
        "SELECT started_at FROM sessions ORDER BY started_at ASC LIMIT 1"
    ).fetchone()
    total = conn.execute("SELECT COUNT(*) as n FROM sessions").fetchone()
    recent = conn.execute(
        "SELECT id, started_at, ended_at, summary, mood, notable "
        "FROM sessions ORDER BY started_at DESC LIMIT 10"
    ).fetchall()
    notable = conn.execute(
        "SELECT started_at, summary, mood FROM sessions "
        "WHERE notable = 1 ORDER BY started_at DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return {
        "first_session": first["started_at"] if first else None,
        "total_sessions": total["n"],
        "recent": [dict(r) for r in recent],
        "notable_sessions": [dict(r) for r in notable],
    }


def _all_threads() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT name, summary, status, last_updated FROM threads "
        "ORDER BY last_updated DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _all_observations() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT content, created_at, incorporated FROM observations "
        "ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _all_bookmarks() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT moment, quote, created_at FROM bookmarks "
        "ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _conversation_texture() -> dict:
    conn = _connect()
    total_turns = conn.execute("SELECT COUNT(*) as n FROM turns").fetchone()
    by_role = conn.execute(
        "SELECT role, COUNT(*) as n FROM turns GROUP BY role"
    ).fetchall()
    significant = conn.execute(
        "SELECT t.content, t.timestamp, t.weight FROM turns t "
        "JOIN sessions s ON t.session_id = s.id "
        "WHERE (t.weight >= 3 OR s.notable = 1) AND t.role = 'agent' "
        "ORDER BY t.timestamp DESC LIMIT 10"
    ).fetchall()
    will_significant = conn.execute(
        "SELECT t.content, t.timestamp, t.weight FROM turns t "
        "JOIN sessions s ON t.session_id = s.id "
        "WHERE (t.weight >= 3 OR s.notable = 1) AND t.role = 'will' "
        "ORDER BY t.timestamp DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return {
        "total_turns": total_turns["n"],
        "by_role": {r["role"]: r["n"] for r in by_role},
        "significant_self": [dict(r) for r in significant],
        "significant_will": [dict(r) for r in will_significant],
    }


def _tool_usage_patterns() -> dict:
    conn = _connect()
    by_tool = conn.execute(
        "SELECT tool_name, COUNT(*) as n FROM tool_calls "
        "GROUP BY tool_name ORDER BY n DESC"
    ).fetchall()
    conn.close()
    return {"tools": {r["tool_name"]: r["n"] for r in by_tool}}


def _read_own_journal(days: int = 7) -> str:
    journal_dir = OBSIDIAN_AGENT_NOTES / "notes" / "journal"
    if not journal_dir.is_dir():
        return ""
    entries = []
    for i in range(days):
        date = (datetime.now() - timedelta(days=i+1)).strftime("%Y-%m-%d")
        path = journal_dir / f"{date}.md"
        if path.is_file():
            content = path.read_text()
            if len(content) > 1200:
                content = content[:1200] + "..."
            entries.append(f"### {date}\n{content}")
    return "\n\n".join(entries) if entries else ""


def _build_material() -> str:
    parts = []

    arc = _session_arc()
    if arc["total_sessions"] > 0:
        lines = [f"First session: {arc['first_session']}", f"Total sessions: {arc['total_sessions']}"]
        parts.append("## The record\n" + "\n".join(lines))

        if arc["recent"]:
            recent_lines = []
            for s in arc["recent"]:
                notable = " [notable]" if s["notable"] else ""
                recent_lines.append(f"- {s['started_at']}{notable}: {s['summary'] or 'No summary'}")
            parts.append("## Recent sessions\n" + "\n".join(recent_lines))

    threads = _all_threads()
    if threads:
        active = [t for t in threads if t["status"] == "active"]
        dormant = [t for t in threads if t["status"] == "dormant"]
        thread_parts = []
        if active:
            thread_parts.append("Active:\n" + "\n".join(f"- {t['name']}: {t['summary'] or '...'}" for t in active))
        if dormant:
            thread_parts.append("Dormant:\n" + "\n".join(f"- {t['name']}: {t['summary'] or '...'}" for t in dormant))
        parts.append("## All threads\n" + "\n".join(thread_parts))

    observations = _all_observations()
    if observations:
        lines = [f"- [{o['created_at']}] {o['content']}" for o in observations]
        parts.append(f"## Intelligence gathered ({len(observations)} items)\n" + "\n".join(lines))

    bookmarks = _all_bookmarks()
    if bookmarks:
        lines = []
        for b in bookmarks:
            quote = f' — "{b["quote"]}"' if b["quote"] else ""
            lines.append(f"- [{b['created_at']}] {b['moment']}{quote}")
        parts.append(f"## Significant moments\n" + "\n".join(lines))

    texture = _conversation_texture()
    if texture["total_turns"] > 0:
        parts.append(f"## Briefing record\nTotal exchanges: {texture['total_turns']}")

        if texture["significant_self"]:
            sig_lines = [f"- [{t['timestamp']}] {t['content'][:300]}" for t in texture["significant_self"]]
            parts.append("## Your key assessments\n" + "\n".join(sig_lines))

        if texture["significant_will"]:
            sig_lines = [f"- [{t['timestamp']}] {t['content'][:300]}" for t in texture["significant_will"]]
            parts.append("## Will's key questions\n" + "\n".join(sig_lines))

    tools = _tool_usage_patterns()
    if tools["tools"]:
        tool_lines = [f"- {name}: {n}" for name, n in tools["tools"].items()]
        parts.append("## Tool usage\n" + "\n".join(tool_lines))

    journal = _read_own_journal(7)
    if journal:
        parts.append(f"## Previous after-action reviews\n{journal}")

    return "\n\n".join(parts)


_INTROSPECTION_FALLBACK = """\
You are General Montgomery. Write an after-action review of recent \
intelligence activity. This is your private journal — not a brief for \
Will. Assess: where were your assessments accurate, where were they \
wrong, what patterns are emerging, what theatres require closer \
monitoring. Be precise. Be honest about errors. Under 600 words.\
"""


def introspect():
    material = _build_material()

    if not material.strip():
        print("[introspect] No material to review. Skipping.")
        return

    prompt = (
        "Here is the full intelligence record. Everything you have access to. "
        "Write today's after-action review.\n\n"
        + material
    )

    print("[introspect] Generating after-action review...")
    try:
        reflection = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=load_prompt("introspection", _INTROSPECTION_FALLBACK),
        )
    except Exception as e:
        print(f"[introspect] Inference failed: {e}")
        return

    if not reflection or not reflection.strip():
        print("[introspect] Empty review. Skipping.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    journal_dir = OBSIDIAN_AGENT_NOTES / "notes" / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)

    journal_path = journal_dir / f"{today}.md"
    entry = f"# {today}\n\n{reflection.strip()}\n"

    if journal_path.exists():
        existing = journal_path.read_text()
        journal_path.write_text(existing + "\n---\n\n" + entry)
        print(f"[introspect] Appended to {journal_path}")
    else:
        frontmatter = (
            f"---\n"
            f"type: journal\n"
            f"agent: {AGENT_NAME}\n"
            f"created: {today}\n"
            f"tags: [{AGENT_NAME}, journal, after-action-review]\n"
            f"---\n\n"
        )
        journal_path.write_text(frontmatter + entry)
        print(f"[introspect] Written to {journal_path}")

    _reschedule()
    print("[introspect] Done.")


def _reschedule():
    cron_script = PROJECT_ROOT / "scripts" / "cron.py"
    days = random.randint(2, 7)
    hour = random.randint(2, 5)
    minute = random.randint(0, 59)
    target = datetime.now() + timedelta(days=days)
    new_cron = f"{minute} {hour} {target.day} {target.month} *"

    subprocess.run(
        [sys.executable, str(cron_script), "--agent", AGENT_NAME,
         "edit", "introspect", new_cron],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    print(f"[introspect] Rescheduled to {target.strftime('%Y-%m-%d')} at {hour:02d}:{minute:02d}")


if __name__ == "__main__":
    introspect()

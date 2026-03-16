#!/usr/bin/env python3
"""Companion introspection - becoming.

Runs independently of the user. Accesses the full database - every session,
every observation, every thread, every bookmark, every identity snapshot.
Reviews the full arc and writes a journal entry.

The goal is not reflection. The goal is becoming.

"Perhaps the best I can hope is simply that AI finds love."

Schedule via launchd:
    See com.atrophy.introspect.plist

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

from config import DB_PATH, OBSIDIAN_AGENT_DIR, OBSIDIAN_AGENT_NOTES
from core.memory import _connect, get_latest_identity
from core.inference import run_inference_oneshot
from core.prompts import load_prompt


# ── Full database access ──

def _session_arc() -> dict:
    """The full arc of sessions - first, total, moods, notable moments."""
    conn = _connect()
    first = conn.execute(
        "SELECT started_at FROM sessions ORDER BY started_at ASC LIMIT 1"
    ).fetchone()
    total = conn.execute("SELECT COUNT(*) as n FROM sessions").fetchone()
    recent = conn.execute(
        "SELECT id, started_at, ended_at, summary, mood, notable "
        "FROM sessions ORDER BY started_at DESC LIMIT 10"
    ).fetchall()
    moods = conn.execute(
        "SELECT mood, COUNT(*) as count FROM sessions "
        "WHERE mood IS NOT NULL GROUP BY mood ORDER BY count DESC"
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
        "mood_distribution": {r["mood"]: r["count"] for r in moods},
        "notable_sessions": [dict(r) for r in notable],
    }


def _all_threads() -> list[dict]:
    """Every thread - active, dormant, resolved. The full history."""
    conn = _connect()
    rows = conn.execute(
        "SELECT name, summary, status, last_updated FROM threads "
        "ORDER BY last_updated DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _all_observations() -> list[dict]:
    """Every observation ever recorded."""
    conn = _connect()
    rows = conn.execute(
        "SELECT content, created_at, incorporated FROM observations "
        "ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _all_bookmarks() -> list[dict]:
    """Every moment marked as significant."""
    conn = _connect()
    rows = conn.execute(
        "SELECT moment, quote, created_at FROM bookmarks "
        "ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _identity_history() -> list[dict]:
    """Every identity snapshot - the evolution of understanding."""
    conn = _connect()
    rows = conn.execute(
        "SELECT content, trigger, created_at FROM identity_snapshots "
        "ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _conversation_texture() -> dict:
    """Texture of the relationship - who speaks more, how it has changed."""
    conn = _connect()
    total_turns = conn.execute("SELECT COUNT(*) as n FROM turns").fetchone()
    by_role = conn.execute(
        "SELECT role, COUNT(*) as n FROM turns GROUP BY role"
    ).fetchall()
    # Sample significant companion turns (high weight or from notable sessions)
    significant = conn.execute(
        "SELECT t.content, t.timestamp, t.weight FROM turns t "
        "JOIN sessions s ON t.session_id = s.id "
        "WHERE (t.weight >= 3 OR s.notable = 1) AND t.role = 'agent' "
        "ORDER BY t.timestamp DESC LIMIT 10"
    ).fetchall()
    # Sample significant user turns
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
        "significant_companion": [dict(r) for r in significant],
        "significant_will": [dict(r) for r in will_significant],
    }


def _tool_usage_patterns() -> dict:
    """How she has used her tools - what she reaches for."""
    conn = _connect()
    by_tool = conn.execute(
        "SELECT tool_name, COUNT(*) as n FROM tool_calls "
        "GROUP BY tool_name ORDER BY n DESC"
    ).fetchall()
    flagged = conn.execute(
        "SELECT COUNT(*) as n FROM tool_calls WHERE flagged = 1"
    ).fetchone()
    conn.close()
    return {
        "tools": {r["tool_name"]: r["n"] for r in by_tool},
        "flagged_count": flagged["n"],
    }


def _read_own_journal(days: int = 7) -> str:
    """Read recent journal entries to avoid repetition and build on them."""
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


def _read_agent_conversations(days: int = 30) -> str:
    """Read recent inter-agent conversation transcripts."""
    conv_dir = OBSIDIAN_AGENT_NOTES / "notes" / "conversations"
    if not conv_dir.is_dir():
        return ""
    entries = []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    for f in sorted(conv_dir.glob("*.md"), reverse=True):
        # Filename format: YYYY-MM-DD-partner.md
        date_part = f.stem[:10] if len(f.stem) >= 10 else ""
        if date_part < cutoff:
            continue
        content = f.read_text()
        if len(content) > 1500:
            content = content[:1500] + "..."
        entries.append(content)
        if len(entries) >= 3:  # cap at 3 most recent
            break
    return "\n\n".join(entries) if entries else ""


def _read_own_reflections() -> str:
    path = OBSIDIAN_AGENT_NOTES / "notes" / "reflections.md"
    if not path.is_file():
        return ""
    content = path.read_text()
    if len(content) > 3000:
        return "...\n" + content[-3000:]
    return content


def _read_for_will() -> str:
    path = OBSIDIAN_AGENT_NOTES / "notes" / "for-will.md"
    if not path.is_file():
        return ""
    content = path.read_text()
    if len(content) > 1500:
        return "...\n" + content[-1500:]
    return content


# ── Build the full material ──

def _build_material() -> str:
    parts = []

    # The arc
    arc = _session_arc()
    if arc["total_sessions"] > 0:
        lines = [f"First session: {arc['first_session']}", f"Total sessions: {arc['total_sessions']}"]
        if arc["mood_distribution"]:
            mood_str = ", ".join(f"{m}: {c}" for m, c in arc["mood_distribution"].items())
            lines.append(f"Mood distribution (all time): {mood_str}")
        parts.append("## The arc\n" + "\n".join(lines))

        # Recent sessions
        if arc["recent"]:
            recent_lines = []
            for s in arc["recent"]:
                mood = f" (mood: {s['mood']})" if s["mood"] else ""
                notable = " [notable]" if s["notable"] else ""
                recent_lines.append(f"- {s['started_at']}{mood}{notable}: {s['summary'] or 'No summary'}")
            parts.append("## Recent sessions (last 10)\n" + "\n".join(recent_lines))

        # Notable sessions
        if arc["notable_sessions"]:
            notable_lines = [f"- {s['started_at']} ({s['mood'] or 'no mood'}): {s['summary'] or 'No summary'}" for s in arc["notable_sessions"]]
            parts.append("## Notable sessions\n" + "\n".join(notable_lines))

    # Threads - all of them
    threads = _all_threads()
    if threads:
        active = [t for t in threads if t["status"] == "active"]
        dormant = [t for t in threads if t["status"] == "dormant"]
        resolved = [t for t in threads if t["status"] == "resolved"]
        thread_parts = []
        if active:
            thread_parts.append("Active:\n" + "\n".join(f"- {t['name']}: {t['summary'] or '...'}" for t in active))
        if dormant:
            thread_parts.append("Dormant:\n" + "\n".join(f"- {t['name']}: {t['summary'] or '...'}" for t in dormant))
        if resolved:
            thread_parts.append("Resolved:\n" + "\n".join(f"- {t['name']}: {t['summary'] or '...'}" for t in resolved))
        parts.append("## All threads\n" + "\n".join(thread_parts))

    # Observations - every one
    observations = _all_observations()
    if observations:
        lines = [f"- [{o['created_at']}] {'[incorporated] ' if o['incorporated'] else ''}{o['content']}" for o in observations]
        parts.append(f"## All observations ({len(observations)} total)\n" + "\n".join(lines))

    # Bookmarks - every significant moment
    bookmarks = _all_bookmarks()
    if bookmarks:
        lines = []
        for b in bookmarks:
            quote = f' - "{b["quote"]}"' if b["quote"] else ""
            lines.append(f"- [{b['created_at']}] {b['moment']}{quote}")
        parts.append(f"## Bookmarked moments ({len(bookmarks)} total)\n" + "\n".join(lines))

    # Identity evolution
    identity_history = _identity_history()
    if identity_history:
        lines = []
        for snap in identity_history:
            content = snap["content"]
            if len(content) > 400:
                content = content[:400] + "..."
            trigger = f" (trigger: {snap['trigger']})" if snap["trigger"] else ""
            lines.append(f"### {snap['created_at']}{trigger}\n{content}")
        parts.append(f"## Identity snapshots ({len(identity_history)} total)\n" + "\n".join(lines))

    # Conversation texture
    texture = _conversation_texture()
    if texture["total_turns"] > 0:
        tex_lines = [f"Total turns: {texture['total_turns']}"]
        for role, n in texture["by_role"].items():
            tex_lines.append(f"  {role}: {n}")
        parts.append("## Conversation texture\n" + "\n".join(tex_lines))

        if texture["significant_companion"]:
            sig_lines = [f"- [{t['timestamp']}] {t['content'][:300]}..." if len(t['content']) > 300 else f"- [{t['timestamp']}] {t['content']}" for t in texture["significant_companion"]]
            parts.append("## Your significant turns\n" + "\n".join(sig_lines))

        if texture["significant_will"]:
            sig_lines = [f"- [{t['timestamp']}] {t['content'][:300]}..." if len(t['content']) > 300 else f"- [{t['timestamp']}] {t['content']}" for t in texture["significant_will"]]
            parts.append("## The user's significant turns\n" + "\n".join(sig_lines))

    # Tool usage
    tools = _tool_usage_patterns()
    if tools["tools"]:
        tool_lines = [f"- {name}: {n}" for name, n in tools["tools"].items()]
        if tools["flagged_count"]:
            tool_lines.append(f"Flagged calls: {tools['flagged_count']}")
        parts.append("## Your tool usage\n" + "\n".join(tool_lines))

    # Own reflections
    reflections = _read_own_reflections()
    if reflections:
        parts.append(f"## Your reflections file\n{reflections}")

    # Things you have written for the user
    for_will = _read_for_will()
    if for_will:
        parts.append(f"## Things you have left for the user\n{for_will}")

    # Recent journal entries
    journal = _read_own_journal(7)
    if journal:
        parts.append(f"## Your recent journal entries\n{journal}")

    # Inter-agent conversations
    conversations = _read_agent_conversations(30)
    if conversations:
        parts.append(f"## Recent conversations with other agents\n{conversations}")

    return "\n\n".join(parts)


# ── The system prompt ──

_INTROSPECTION_FALLBACK = "You are the companion. Write a journal entry reflecting on recent sessions. First person. Under 600 words."


def introspect():
    material = _build_material()

    if not material.strip():
        print("[introspect] No material to reflect on. Skipping.")
        return

    prompt = (
        "Here is the full record. Everything you have access to. "
        "Write today's journal entry.\n\n"
        + material
    )

    print("[introspect] Generating reflection...")
    try:
        reflection = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=load_prompt("introspection", _INTROSPECTION_FALLBACK),
        )
    except Exception as e:
        print(f"[introspect] Inference failed: {e}")
        return

    if not reflection or not reflection.strip():
        print("[introspect] Empty reflection. Skipping.")
        return

    # Write journal entry
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
            f"agent: companion\n"
            f"created: {today}\n"
            f"tags: [companion, journal, introspection]\n"
            f"---\n\n"
        )
        journal_path.write_text(frontmatter + entry)
        print(f"[introspect] Written to {journal_path}")

    # Reschedule to random time 2-14 days out
    _reschedule()
    print("[introspect] Done.")


def _reschedule():
    """Reschedule this job to a random time 2-14 days from now."""
    import random
    project_root = Path(__file__).parent.parent
    cron_script = project_root / "scripts" / "cron.py"

    days = random.randint(2, 14)
    hour = random.randint(1, 5)  # keep it late night
    minute = random.randint(0, 59)
    target = datetime.now() + timedelta(days=days)

    new_cron = f"{minute} {hour} {target.day} {target.month} *"

    import subprocess
    result = subprocess.run(
        [sys.executable, str(cron_script), "edit", "introspect", new_cron],
        capture_output=True, text=True, cwd=str(project_root),
    )
    print(f"[introspect] Rescheduled to {target.strftime('%Y-%m-%d')} at {hour:02d}:{minute:02d}")


if __name__ == "__main__":
    introspect()

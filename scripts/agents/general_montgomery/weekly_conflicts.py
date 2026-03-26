#!/usr/bin/env python3
"""
Montgomery Weekly Conflict Assessment - Persistent cron script.

Runs weekly. Selects a conflict from the watchlist (rotating or as instructed),
pulls live WorldMonitor data, generates a full assessment via Claude API,
logs to intelligence.db and Obsidian, sends via Telegram.

Called by the Atrophy job runner on weekly schedule.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Paths ---
_ATROPHY_DIR    = Path.home() / ".atrophy"
_AGENT_DIR      = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON     = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB       = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR        = _ATROPHY_DIR / "logs" / "general_montgomery"
_OBSIDIAN_BASE  = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind"
_CONFLICTS_DIR  = _OBSIDIAN_BASE / "Projects/General Montgomery/Conflicts"

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
_MCP_DIR = _APP_DIR / "mcp"
sys.path.insert(0, str(_MCP_DIR))

# --- Logging ---
_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "weekly_conflicts.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("weekly_conflicts")

# --- Conflict rotation order ---
CONFLICT_ROTATION = [
    "sudan",
    "ukraine",
    "iran-israel",
    "taiwan-strait",
    "sahel",
    "yemen-red-sea",
    "south-china-sea",
    "kosovo-serbia",
]

# Obsidian folder names per slug
CONFLICT_OBSIDIAN_DIRS = {
    "sudan":          "Sudan",
    "ukraine":        "Ukraine",
    "iran-israel":    "Iran-Israel",
    "taiwan-strait":  "Taiwan Strait",
    "sahel":          "Sahel",
    "yemen-red-sea":  "Yemen-Red Sea",
    "south-china-sea":"South China Sea",
    "kosovo-serbia":  "Kosovo-Serbia",
}


def load_credentials():
    with open(_AGENT_JSON) as f:
        data = json.load(f)
    return data["telegram_bot_token"], data["telegram_chat_id"]


def pick_conflict(db: sqlite3.Connection) -> dict:
    """Select the next conflict in rotation based on least-recently briefed."""
    c = db.cursor()
    results = []
    for slug in CONFLICT_ROTATION:
        c.execute("""
            SELECT b.date FROM briefs b
            JOIN conflicts cf ON b.conflict_id = cf.id
            WHERE cf.slug = ?
            ORDER BY b.date DESC LIMIT 1
        """, (slug,))
        row = c.fetchone()
        last_date = row[0] if row else "1970-01-01"
        c.execute("SELECT id, name FROM conflicts WHERE slug = ?", (slug,))
        conf = c.fetchone()
        if conf:
            results.append({"id": conf[0], "name": conf[1], "slug": slug, "last_brief": last_date})

    # Sort by last briefed date ascending - least recently covered goes first
    results.sort(key=lambda x: x["last_brief"])
    return results[0]


def fetch_worldmonitor_context(conflict_slug: str) -> str:
    """Pull relevant WorldMonitor data for the conflict region."""
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))

        # Map slugs to region search terms
        region_map = {
            "sudan":           "Sudan Africa",
            "ukraine":         "Ukraine Russia",
            "iran-israel":     "Iran Israel Middle East",
            "taiwan-strait":   "Taiwan China Pacific",
            "sahel":           "Mali Niger Burkina Faso Sahel",
            "yemen-red-sea":   "Yemen Red Sea Houthi",
            "south-china-sea": "South China Sea Philippines",
            "kosovo-serbia":   "Kosovo Serbia Balkans",
        }
        region = region_map.get(conflict_slug, conflict_slug)

        # Pull conflicts and news digest
        conflicts_data, _wm_delta = client.fetch_cached("api/conflict/v1/list-acled-events")
        news_data = client.get_news_digest()

        # Extract relevant snippets - truncate to avoid token overload
        context_parts = []

        if conflicts_data:
            cf_str = json.dumps(conflicts_data)[:3000]
            context_parts.append(f"WORLDMONITOR CONFLICTS:\n{cf_str}")

        if news_data:
            nd_str = json.dumps(news_data)[:4000]
            context_parts.append(f"WORLDMONITOR NEWS DIGEST:\n{nd_str}")

        return "\n\n".join(context_parts) if context_parts else ""

    except Exception as e:
        log.warning(f"WorldMonitor fetch failed: {e}")
        return ""


CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")


def call_claude(system: str, prompt: str, model: str = "sonnet") -> str:
    """One-shot Claude call via CLI. Returns response text."""
    import subprocess
    result = subprocess.run(
        [CLAUDE_BIN, "-p", "--model", model, "--system-prompt", system,
         "--no-session-persistence", "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[:200]}")
    return result.stdout.strip()


def generate_brief(conflict: dict, wm_context: str, history_summary: str) -> str:
    """Call Claude to generate the weekly assessment."""
    system_prompt = """You are General Montgomery - strategic intelligence analyst.
Produce a weekly conflict assessment in your characteristic voice: clipped, precise,
no wasted words. Short sentences when the matter is settled. No hedging language.
You always take a position.

Structure: situation as it stands | relevant history briefly | actual interests at play |
likely trajectory | variables that could change it | your assessment (1-2 sentences, unhedged).

No em dashes. Hyphens only. No bullet points - prose assessment.
Suitable for Telegram delivery - keep under 600 words."""

    history_section = f"\n\nPREVIOUS BRIEFS ON THIS CONFLICT:\n{history_summary}" if history_summary else ""
    wm_section = f"\n\nLIVE WORLDMONITOR DATA:\n{wm_context}" if wm_context else ""

    user_prompt = f"""Weekly assessment required: {conflict['name']}.
{history_section}{wm_section}

Produce a full assessment. Identify what has changed since the last brief if prior entries exist.
Flag any breaking developments from the live data. End with your unhedged assessment of trajectory."""

    return call_claude(system_prompt, user_prompt, "sonnet")


def get_history_summary(db: sqlite3.Connection, conflict_id: int, limit: int = 3) -> str:
    """Retrieve the last N briefs for context continuity."""
    c = db.cursor()
    c.execute("""
        SELECT date, title, content FROM briefs
        WHERE conflict_id = ?
        ORDER BY date DESC LIMIT ?
    """, (conflict_id, limit))
    rows = c.fetchall()
    if not rows:
        return ""
    parts = []
    for date, title, content in reversed(rows):
        parts.append(f"[{date}] {title}\n{content[:500]}...")
    return "\n\n---\n\n".join(parts)


def log_brief_to_db(db: sqlite3.Connection, conflict_id: int, date: str,
                    title: str, content: str, requested_by: str = "montgomery"):
    c = db.cursor()
    c.execute("""
        INSERT INTO briefs (conflict_id, date, title, content, requested_by)
        VALUES (?, ?, ?, ?, ?)
    """, (conflict_id, date, title, content, requested_by))
    db.commit()
    log.info(f"Brief logged to intelligence.db: {date} - {title}")


def log_brief_to_obsidian(conflict: dict, date: str, title: str, content: str):
    """Write brief as a dated Markdown entry in the Obsidian conflict folder."""
    folder_name = CONFLICT_OBSIDIAN_DIRS.get(conflict["slug"], conflict["name"])
    conflict_dir = _CONFLICTS_DIR / folder_name
    conflict_dir.mkdir(parents=True, exist_ok=True)

    file_path = conflict_dir / f"{date}.md"
    md_content = f"# {conflict['name']} Brief - {date}\n\n**Type:** Weekly assessment\n**Requested by:** Montgomery (scheduled)\n\n---\n\n{content}\n\n---\n\n*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC*\n"
    file_path.write_text(md_content)

    # Update conflict index
    index_path = conflict_dir / "Index.md"
    if index_path.exists():
        index_text = index_path.read_text()
        # Insert new row into the brief log table
        new_row = f"| [[{date}\\|{date}]] | {title} | Weekly scheduled |"
        if "| Brief Log |" in index_text or "## Brief Log" in index_text:
            # Find the table and append
            updated = re.sub(
                r'(\| Date \| Title \| Key Development \|\n\|[-|]+\|\n)',
                r'\1' + new_row + '\n',
                index_text
            )
            if updated != index_text:
                index_path.write_text(updated)

    log.info(f"Brief logged to Obsidian: {file_path}")


def send_telegram(token: str, chat_id: str, text: str):
    """Send text message via Telegram."""
    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")
    log.info(f"Brief sent via Telegram. Message ID: {result['result']['message_id']}")


def run():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log.info("Weekly conflict assessment starting")

    db = sqlite3.connect(str(_INTEL_DB))

    try:
        # 1. Pick conflict
        conflict = pick_conflict(db)
        log.info(f"Selected conflict: {conflict['name']} (last brief: {conflict['last_brief']})")

        # 2. Get history for continuity
        history = get_history_summary(db, conflict["id"])

        # 3. Pull live data
        wm_context = fetch_worldmonitor_context(conflict["slug"])

        # 4. Generate brief
        title = f"{conflict['name']} - Weekly Assessment"
        log.info(f"Generating brief: {title}")
        content = generate_brief(conflict, wm_context, history)

        # 5. Log to DB and Obsidian
        log_brief_to_db(db, conflict["id"], today, title, content)
        log_brief_to_obsidian(conflict, today, title, content)

        # 6. Format and send via Telegram
        token, chat_id = load_credentials()
        header = f"*WEEKLY ASSESSMENT - {today}*\n*{conflict['name'].upper()}*\n\n"
        message = header + content

        # Telegram has 4096 char limit - truncate if needed
        if len(message) > 4000:
            message = message[:3950] + "\n\n_[Full brief in Obsidian]_"

        send_telegram(token, chat_id, message)
        log.info("Weekly conflict assessment complete")

    finally:
        db.close()


if __name__ == "__main__":
    run()

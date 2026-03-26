#!/usr/bin/env python3
"""
Weekly Digest - Monday 07:00.

Full week assessment across all six Meridian research tracks with week-ahead outlook.
Draws from: WorldMonitor live data, intelligence.db brief log, conflict watchlist.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ATROPHY_DIR  = Path.home() / ".atrophy"
_AGENT_DIR    = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON   = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB     = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR      = _ATROPHY_DIR / "logs" / "general_montgomery"

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
_MCP_DIR = _APP_DIR / "mcp"
sys.path.insert(0, str(_MCP_DIR))

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "weekly_digest.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("weekly_digest")

MERIDIAN_TRACKS = [
    ("Track 01", "UK Defence Posture",         "Force structure, procurement status, capability gaps, 2.5% GDP commitment reality"),
    ("Track 02", "European Security",           "NATO compliance, Lancaster House Treaty, rearmament dynamics, Ukraine settlement scenarios"),
    ("Track 03", "Gulf-Iran-Israel-US",         "Iranian nuclear, IRGCN posture, Houthi/Red Sea, Israeli military, CENTCOM, UK basing"),
    ("Track 04", "Russia-Ukraine",              "Battlespace, British weapons supply sustainability, Black Sea, Russian hybrid ops vs UK"),
    ("Track 05", "Indo-Pacific",                "AUKUS SSN delivery, carrier deployments, GCAP (UK-Japan-Italy), Five Eyes, capability vs stated posture"),
    ("Track 06", "Economic Security",           "Sanctions effectiveness, supply chain vulnerabilities, Chinese leverage on UK institutions, trade corridor risk"),
]



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

def load_credentials():
    from shared.credentials import load_telegram_credentials
    return load_telegram_credentials("general_montgomery")


def get_week_briefs(db: sqlite3.Connection) -> str:
    """Retrieve all briefs from the past 7 days."""
    c = db.cursor()
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    c.execute("""
        SELECT b.date, cf.name, b.title, substr(b.content, 1, 300)
        FROM briefs b
        LEFT JOIN conflicts cf ON b.conflict_id = cf.id
        WHERE b.date >= ?
        ORDER BY b.date DESC
    """, (week_ago,))
    rows = c.fetchall()
    if not rows:
        return "No briefs logged this week."
    parts = []
    for date, conflict, title, content in rows:
        conflict_label = conflict or "General"
        parts.append(f"[{date}] {conflict_label} - {title}\n{content}...")
    return "\n\n".join(parts)


def fetch_live_context() -> str:
    """Pull current WorldMonitor data for context."""
    parts = []
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))

        news, _ = client.fetch_cached("api/news/v1/digest")
        if news:
            parts.append(f"NEWS SUMMARY:\n{json.dumps(news)[:2000]}")

        conflicts, _ = client.fetch_cached("api/conflict/v1/list-acled-events")
        if conflicts:
            parts.append(f"CONFLICTS:\n{json.dumps(conflicts)[:2000]}")

        economic, _ = client.fetch_cached("api/economic/v1/get-energy-prices")
        if economic:
            parts.append(f"ECONOMIC:\n{json.dumps(economic)[:1500]}")

    except Exception as e:
        log.warning(f"WorldMonitor fetch failed: {e}")

    return "\n\n".join(parts)


def generate_digest(week_briefs: str, live_context: str) -> str:
    system = """You are General Montgomery producing the Meridian Institute weekly digest.
Structure: brief preamble (2 sentences on the week's defining development), then one paragraph per track.
End with a week-ahead outlook: what to watch, what could move.
Voice: clipped, precise, analytical. No hedging. No em dashes - hyphens only.
This is the premium weekly assessment. Give it weight. Under 700 words."""

    tracks_str = "\n".join(f"{t[0]}: {t[1]} - {t[2]}" for t in MERIDIAN_TRACKS)
    user = f"""Weekly digest required. Week ending {datetime.now().strftime('%Y-%m-%d')}.

MERIDIAN RESEARCH TRACKS:
{tracks_str}

BRIEFS LOGGED THIS WEEK:
{week_briefs}

LIVE WORLDMONITOR DATA:
{live_context}

Produce the full weekly digest across all six tracks. Identify the week's most significant development. End with week-ahead."""

    return call_claude(system, user, "sonnet")


def send_telegram(token: str, chat_id: str, text: str):
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")


def run():
    log.info("Weekly digest starting")
    db = sqlite3.connect(str(_INTEL_DB))

    try:
        week_briefs = get_week_briefs(db)
        live_context = fetch_live_context()
        digest = generate_digest(week_briefs, live_context)

        token, chat_id = load_credentials()
        date_str = datetime.now().strftime("%Y-%m-%d")
        header = f"*MERIDIAN INSTITUTE - WEEKLY DIGEST*\n*Week of {date_str}*\n\n"
        message = header + digest

        if len(message) > 4000:
            message = message[:3950] + "\n\n_[Full digest in Obsidian]_"

        send_telegram(token, chat_id, message)
        log.info("Weekly digest sent")

        # Log to intelligence.db
        db.execute("""
            INSERT INTO briefs (conflict_id, date, title, content, requested_by)
            VALUES (NULL, ?, ?, ?, 'montgomery')
        """, (date_str, f"Weekly Digest - {date_str}", digest))
        db.commit()

    finally:
        db.close()


if __name__ == "__main__":
    run()

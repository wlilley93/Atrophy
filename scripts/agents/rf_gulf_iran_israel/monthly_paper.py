#!/usr/bin/env python3
"""
Research Fellow Gulf/Iran/Israel - Monthly deep-dive paper.
Runs first of month 09:00. Draws from prior briefs + live data.
Reports to Montgomery for editorial review.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_INTEL_DB    = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"
_AGENT_JSON  = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "agent.json"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "rf_gulf_iran_israel"
_OBSIDIAN    = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind"

_APP_DIR = Path("/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron")
sys.path.insert(0, str(_APP_DIR / "mcp"))

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RF-Gulf] %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "monthly_paper.log"), logging.StreamHandler(sys.stderr)]
)
log = logging.getLogger("monthly_paper")



CLAUDE_BIN = "/Users/williamlilley/.local/bin/claude"


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

def get_prior_briefs(db: sqlite3.Connection) -> str:
    c = db.cursor()
    c.execute("""
        SELECT b.date, b.title, substr(b.content, 1, 400)
        FROM briefs b
        LEFT JOIN conflicts cf ON b.conflict_id = cf.id
        WHERE cf.slug = 'iran-israel' OR b.title LIKE '%Iran%' OR b.title LIKE '%Gulf%'
        ORDER BY b.date DESC LIMIT 6
    """)
    rows = c.fetchall()
    if not rows:
        return "No prior briefs on file."
    return "\n\n".join(f"[{d}] {t}\n{c}..." for d, t, c in reversed(rows))


def fetch_gulf_data() -> str:
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))
        parts = []
        conflicts, _wm_delta = client.fetch_cached("api/conflict/v1/list-acled-events")
        if conflicts:
            parts.append(f"CONFLICTS:\n{json.dumps(conflicts)[:2000]}")
        maritime, _wm_delta = client.fetch_cached("api/ais-snapshot", params={"candidates": "true"})
        if maritime:
            parts.append(f"MARITIME (Hormuz/Gulf):\n{json.dumps(maritime)[:2000]}")
        return "\n\n".join(parts)
    except Exception as e:
        log.warning(f"WorldMonitor fetch failed: {e}")
        return ""


def generate_paper(prior_briefs: str, live_data: str, month_str: str) -> str:
    system = """You are a Research Fellow at the Meridian Institute specialising in the Gulf-Iran-Israel-US theatre.
Produce a monthly deep-dive paper structured as: Executive Summary | Iranian Nuclear & Missile Programme |
IRGCN Maritime Posture | Houthi/Red Sea Dimension | Israeli Military Posture | US CENTCOM Disposition |
UK Interests (Bahrain, Duqm, Hormuz) | Outlook for the Month Ahead.
Analytical register. No hedging. No em dashes - hyphens only. 600-800 words."""
    return call_claude(system, f"Monthly paper: {month_str}\n\nPRIOR BRIEFS:\n{prior_briefs}\n\nLIVE DATA:\n{live_data}", "sonnet")


def run():
    log.info("Monthly Gulf/Iran/Israel paper starting")
    db = sqlite3.connect(str(_INTEL_DB))
    month_str = datetime.now().strftime("%B %Y")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        prior = get_prior_briefs(db)
        live = fetch_gulf_data()
        paper = generate_paper(prior, live, month_str)

        c = db.cursor()
        c.execute("SELECT id FROM conflicts WHERE slug = 'iran-israel'")
        row = c.fetchone()
        conflict_id = row[0] if row else None

        db.execute("""
            INSERT INTO briefs (conflict_id, date, title, content, requested_by)
            VALUES (?, ?, ?, ?, 'rf_gulf_iran_israel')
        """, (conflict_id, date_str, f"Gulf-Iran-Israel Monthly Paper - {month_str}", paper))
        db.commit()

        # Save to Obsidian
        paper_dir = _OBSIDIAN / "Projects/General Montgomery/Conflicts/Iran-Israel"
        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / f"{date_str}.md").write_text(
            f"# Gulf-Iran-Israel Monthly Paper - {month_str}\n\n**Author:** Research Fellow\n**Date:** {date_str}\n\n---\n\n{paper}\n"
        )
        log.info(f"Monthly paper logged: {month_str}")

    finally:
        db.close()


if __name__ == "__main__":
    run()

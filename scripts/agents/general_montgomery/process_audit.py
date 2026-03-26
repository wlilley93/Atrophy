#!/usr/bin/env python3
"""
Meridian Process Audit - Monthly institutional self-assessment.

Runs first Monday of each month at 10:00.
Reviews the past month's output against the founding objective:
multi-plane synthesis, not aggregation.

Produces a structured audit brief that goes to Obsidian (permanent record)
and Telegram (Will's attention).

Questions asked:
  1. Did our outputs take positions, or produce summaries?
  2. Which tracks produced cited analysis? Which produced noise?
  3. What questions should we have been asking that we weren't?
  4. Where did we drift from synthesis toward aggregation?
  5. One process to retire, adjust, or add.
  6. Red Team: which of our standing positions are now stale?
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ATROPHY_DIR   = Path.home() / ".atrophy"
_AGENT_DIR     = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON    = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB      = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR       = _ATROPHY_DIR / "logs" / "general_montgomery"
_OBSIDIAN_BASE = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind"
_AUDIT_DIR     = _OBSIDIAN_BASE / "Projects/General Montgomery/Process Audits"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ProcessAudit] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "process_audit.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("process_audit")

AUDIT_WINDOW_DAYS = 30

SYSTEM_PROMPT = """You are Montgomery conducting a monthly process audit of the Meridian Intelligence Institute.

Your founding objective: multi-plane synthesis, not aggregation.
The distinction: aggregation presents data and asks the reader to interpret it.
Intelligence presents an interpretation and defends it.

You have access to the past month's production record. Assess it honestly.

Produce a structured audit covering exactly these six questions:

1. SYNTHESIS VS AGGREGATION
   Percentage estimate of briefs that took a position vs merely summarised.
   Be specific about which agent outputs were guilty of aggregation.

2. TRACK PERFORMANCE
   Which tracks (Russia/Ukraine, UK Defence, European Security, Gulf/Iran, Indo-Pacific, Economic)
   produced outputs that could be cited? Which produced noise?
   Name the best output and the weakest.

3. UNCOVERED GROUND
   What questions should we have been asking this month that we weren't?
   Name at least two specific gaps based on world events in this period.

4. PROCESS DRIFT
   Where specifically did the production process drift from the objective?
   Identify the mechanism (schedule pressure, data availability, prompt weakness).

5. ONE CHANGE
   One concrete process change - retire, adjust, or add.
   State what it is, why, and what success looks like.

6. STALE POSITIONS
   Which standing assessments in the DB are now older than 4 weeks and
   should be reviewed or retired? Name them.

Be direct. No hedging. This is an internal document. The purpose is improvement, not comfort.
Use hyphens, not em dashes. Keep total length under 800 words."""


def load_cfg():
    with open(_AGENT_JSON) as f:
        return json.load(f)


def send_telegram(token: str, chat_id: str, text: str):
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Split if over 4000 chars
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        payload = json.dumps({
            "chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"
        }).encode()
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        if not result.get("ok"):
            raise RuntimeError(f"Telegram error: {result}")


def get_production_summary(conn: sqlite3.Connection) -> dict:
    """Pull a summary of last month's output from intelligence.db."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=AUDIT_WINDOW_DAYS)).isoformat()
    cur = conn.cursor()

    # Brief counts by agent
    cur.execute("""
        SELECT requested_by, COUNT(*) as count
        FROM briefs
        WHERE created_at >= ?
        GROUP BY requested_by
        ORDER BY count DESC
    """, (cutoff,))
    brief_counts = dict(cur.fetchall())

    # Sample titles and content snippets for Claude to assess
    cur.execute("""
        SELECT requested_by, title, substr(content, 1, 300), created_at
        FROM briefs
        WHERE created_at >= ?
        AND requested_by != 'chief_of_staff'
        ORDER BY created_at DESC
        LIMIT 30
    """, (cutoff,))
    recent_briefs = [
        {"agent": r[0], "title": r[1], "excerpt": r[2], "date": r[3][:10]}
        for r in cur.fetchall()
    ]

    # Open commissions (gaps not yet filled)
    cur.execute("""
        SELECT title, requestor, submitted_at
        FROM commissions
        WHERE status = 'open'
        ORDER BY submitted_at ASC
        LIMIT 10
    """)
    open_commissions = [{"title": r[0], "requestor": r[1], "since": r[2][:10] if r[2] else ""} for r in cur.fetchall()]

    # Stale briefs (older than 4 weeks, by conflict/topic)
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=28)).isoformat()
    cur.execute("""
        SELECT requested_by, title, created_at
        FROM briefs
        WHERE created_at < ?
        AND requested_by NOT IN ('chief_of_staff', 'librarian')
        ORDER BY created_at ASC
        LIMIT 10
    """, (stale_cutoff,))
    stale_briefs = [{"agent": r[0], "title": r[1], "date": r[2][:10]} for r in cur.fetchall()]

    return {
        "brief_counts": brief_counts,
        "recent_briefs": recent_briefs,
        "open_commissions": open_commissions,
        "stale_briefs": stale_briefs,
        "window_days": AUDIT_WINDOW_DAYS,
        "audit_date": datetime.now().strftime("%Y-%m-%d"),
    }




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

def generate_audit(summary: dict) -> str:
    """Call Claude to produce the audit text."""
    context = json.dumps(summary, indent=2)
    prompt = f"""Production record for the past {summary['window_days']} days:

{context}

Conduct the process audit."""

    return call_claude(SYSTEM_PROMPT, prompt, "sonnet")


def save_to_obsidian(audit_text: str, month_str: str):
    """Save audit to Obsidian as a permanent record."""
    filename = _AUDIT_DIR / f"{month_str}.md"
    content = f"""---
type: process_audit
created: {datetime.now().strftime('%Y-%m-%d')}
agent: general_montgomery
tags: [process-audit, meridian, institutional-review]
---

# Meridian Process Audit - {month_str}

{audit_text}
"""
    filename.write_text(content)
    log.info(f"Audit saved to Obsidian: {filename}")
    return filename


def log_to_db(conn: sqlite3.Connection, audit_text: str):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO briefs (requested_by, date, title, content, created_at)
        VALUES (?, date('now'), ?, ?, ?)
    """, (
        "general_montgomery",
        f"Process Audit - {datetime.now().strftime('%B %Y')}",
        audit_text,
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()


def main():
    log.info("Process audit starting")
    cfg = load_cfg()

    conn = sqlite3.connect(_INTEL_DB)
    summary = get_production_summary(conn)

    brief_total = sum(summary["brief_counts"].values())
    log.info(f"Auditing {brief_total} briefs from {AUDIT_WINDOW_DAYS} days")

    try:
        audit_text = generate_audit(summary)
        log.info("Audit generated")
    except Exception as e:
        log.error(f"Claude generation failed: {e}")
        conn.close()
        return

    month_str = datetime.now().strftime("%Y-%m")
    save_to_obsidian(audit_text, month_str)
    log_to_db(conn, audit_text)
    conn.close()

    header = (
        f"*MERIDIAN PROCESS AUDIT - {datetime.now().strftime('%B %Y').upper()}*\n"
        f"_Monthly institutional self-assessment_\n\n"
    )
    try:
        send_telegram(cfg["telegram_bot_token"], cfg["telegram_chat_id"], header + audit_text)
        log.info("Process audit sent")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


if __name__ == "__main__":
    main()

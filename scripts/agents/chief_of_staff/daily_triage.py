#!/usr/bin/env python3
"""
Chief of Staff - Daily Triage
Runs 05:30 daily. Checks which agents ran overnight, which failed or are overdue,
flags contradictions in intelligence.db, logs triage report.
Routes summary to general_montgomery via DB.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.credentials import load_telegram_credentials

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "chief_of_staff"
_INTEL_DB    = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"
_AGENT_JSON  = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "agent.json"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "chief_of_staff"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CoS-Triage] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "daily_triage.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("daily_triage")

# Expected agent runs - (agent_name, expected_window_hours)
EXPECTED_AGENTS = [
    ("general_montgomery", 0.5),   # heartbeat every 30m
    ("sigint_analyst",     24),
    ("economic_io",        168),   # weekly
    ("rf_russia_ukraine",  24),
    ("rf_gulf_iran_israel", 24),
    ("rf_uk_defence",      168),
    ("rf_european_security", 168),
    ("rf_indo_pacific",    168),
    ("librarian",          1),
]


def load_cfg():
    with open(_AGENT_JSON) as f:
        return json.load(f)


def send_telegram(token: str, chat_id: str, text: str):
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def check_recent_briefs(conn: sqlite3.Connection, window_hours: float) -> list[dict]:
    """Return briefs filed within the window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    cur = conn.cursor()
    cur.execute("""
        SELECT requested_by, title, created_at
        FROM briefs
        WHERE created_at >= ?
        ORDER BY created_at DESC
    """, (cutoff,))
    return [{"agent": r[0], "title": r[1], "ts": r[2]} for r in cur.fetchall()]


def check_agent_activity(conn: sqlite3.Connection) -> dict[str, str]:
    """For each expected agent, find last brief and flag if overdue."""
    status = {}
    cur = conn.cursor()
    for agent, window_h in EXPECTED_AGENTS:
        cur.execute("""
            SELECT created_at FROM briefs
            WHERE requested_by = ?
            ORDER BY created_at DESC LIMIT 1
        """, (agent,))
        row = cur.fetchone()
        if not row:
            status[agent] = "NO_DATA"
        else:
            last = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            if age_h > window_h * 1.5:
                status[agent] = f"OVERDUE ({age_h:.0f}h)"
            else:
                status[agent] = f"OK ({age_h:.0f}h ago)"
    return status


def count_recent_signals(conn: sqlite3.Connection) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM signals WHERE created_at >= ?", (cutoff,))
    return cur.fetchone()[0]


def log_triage_brief(conn: sqlite3.Connection, content: str):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO briefs (requested_by, date, title, content, created_at)
        VALUES (?, date('now'), ?, ?, ?)
    """, (
        "chief_of_staff",
        f"Daily Triage - {datetime.now().strftime('%Y-%m-%d')}",
        content,
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()


def main():
    log.info("Daily triage starting")
    cfg = load_cfg()

    try:
        conn = sqlite3.connect(_INTEL_DB)
    except Exception as e:
        log.error(f"Cannot open intelligence.db: {e}")
        sys.exit(1)

    # Agent activity check
    agent_status = check_agent_activity(conn)
    overdue = {k: v for k, v in agent_status.items() if "OVERDUE" in v or "NO_DATA" in v}
    ok = {k: v for k, v in agent_status.items() if k not in overdue}

    # Recent activity summary
    recent = check_recent_briefs(conn, 24)
    signal_count = count_recent_signals(conn)

    # Build report
    now_str = datetime.now().strftime("%d %b %Y %H:%M")
    lines = [f"*CHIEF OF STAFF - DAILY TRIAGE*", f"_{now_str}_", ""]

    if overdue:
        lines.append("*OVERDUE / NO DATA:*")
        for agent, state in overdue.items():
            lines.append(f"  - {agent}: {state}")
        lines.append("")

    lines.append(f"*24h activity:* {len(recent)} briefs filed | {signal_count} signals")
    lines.append("")
    lines.append("*Agent status:*")
    for agent, state in ok.items():
        lines.append(f"  - {agent}: {state}")

    if overdue:
        lines.append("")
        lines.append(f"*ACTION REQUIRED:* {len(overdue)} agent(s) overdue. Manual catch-up may be needed.")

    report = "\n".join(lines)
    log.info(f"Triage complete. {len(overdue)} overdue, {len(recent)} briefs in 24h")

    log_triage_brief(conn, report)
    conn.close()

    # Only Telegram if there are problems or it's Monday (weekly summary)
    is_monday = datetime.now().weekday() == 0
    if overdue or is_monday:
        try:
            send_telegram(*load_telegram_credentials("chief_of_staff"), report)
            log.info("Triage report sent to Telegram")
        except Exception as e:
            log.error(f"Telegram send failed: {e}")


if __name__ == "__main__":
    main()

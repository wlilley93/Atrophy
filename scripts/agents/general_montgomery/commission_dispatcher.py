#!/usr/bin/env python3
"""
Commission Dispatcher - routes open commissions to Research Fellows.

Runs every 4 hours. For each open commission:
  1. Pulls context from intelligence.db relevant to the assigned domain
  2. Calls Claude with the commission brief + domain context
  3. Stores the investigation output
  4. Creates a brief record in the briefs table
  5. Marks the commission complete
  6. Sends summary to Telegram

Usage:
    python3 commission_dispatcher.py           # process all open commissions
    python3 commission_dispatcher.py --dry-run  # show what would be dispatched
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON  = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB    = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "general_montgomery"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Shared utility
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from claude_cli import call_claude  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CommDispatch] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "commission_dispatcher.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("commission_dispatcher")

# Map agent names to their domain expertise for prompt context
AGENT_DOMAINS = {
    "rf_gulf_iran_israel": {
        "name": "Research Fellow - Gulf, Iran & Israel",
        "keywords": ["iran", "israel", "gulf", "hormuz", "houthi", "centcom",
                      "hezbollah", "irgc", "jcpoa", "yemen", "red sea"],
        "focus": "Gulf security, Iranian nuclear programme, Israel-Iran confrontation, "
                 "Houthi maritime disruption, and broader Middle East escalation dynamics.",
    },
    "rf_russia_ukraine": {
        "name": "Research Fellow - Russia & Ukraine",
        "keywords": ["ukraine", "russia", "black sea", "nato east", "crimea",
                      "donbas", "zaporizhzhia", "kursk"],
        "focus": "Russia-Ukraine war trajectory, frontline dynamics, sanctions impact, "
                 "NATO eastern flank posture, and Black Sea security.",
    },
    "rf_uk_defence": {
        "name": "Research Fellow - UK Defence",
        "keywords": ["uk defence", "type 26", "f-35", "gcap", "aukus", "mod",
                      "british military", "tempest", "dreadnought"],
        "focus": "UK defence procurement, force structure, AUKUS implementation, "
                 "GCAP/Tempest, and Anglo-French defence cooperation.",
    },
    "rf_european_security": {
        "name": "Research Fellow - European Security",
        "keywords": ["nato", "europe", "european", "lancaster house", "germany",
                      "france", "baltic", "nordic"],
        "focus": "European defence integration, NATO burden-sharing, EU strategic autonomy, "
                 "Nordic-Baltic security, and Franco-German defence coordination.",
    },
    "rf_indo_pacific": {
        "name": "Research Fellow - Indo-Pacific",
        "keywords": ["taiwan", "china", "pacific", "indo-pacific", "japan",
                      "south china sea", "quad", "asean"],
        "focus": "Taiwan contingency planning, PLA modernisation, South China Sea tensions, "
                 "AUKUS Pillar II, Quad coordination, and US alliance network in Asia.",
    },
    "economic_io": {
        "name": "Economic Intelligence Officer",
        "keywords": ["sanctions", "economic", "trade", "supply chain", "energy",
                      "commodities", "swift", "semiconductor"],
        "focus": "Sanctions effectiveness, economic warfare, energy security, "
                 "supply chain vulnerabilities, and trade-as-leverage dynamics.",
    },
    "sigint_analyst": {
        "name": "SIGINT Analyst",
        "keywords": ["maritime", "ship", "vessel", "ais", "fleet", "naval",
                      "chokepoint", "strait"],
        "focus": "Maritime domain awareness, AIS pattern analysis, fleet movements, "
                 "chokepoint monitoring, and naval force disposition.",
    },
    "general_montgomery": {
        "name": "General Montgomery (self-assigned)",
        "keywords": [],
        "focus": "Cross-domain strategic assessment and synthesis.",
    },
}

INVESTIGATION_SYSTEM = """You are {agent_name} at the Meridian Institute.

You have been commissioned to investigate a specific intelligence gap.
Your domain: {focus}

Write a focused analytical brief addressing the commission. Structure:

1. CONTEXT - What we currently know (from prior assessments provided)
2. FINDING - Your assessment of the gap, with evidence and reasoning
3. IMPLICATIONS - What this means for Meridian's broader picture
4. CONFIDENCE - State your confidence level and key uncertainties

Requirements:
- Be direct and analytical, not descriptive
- Cite specific evidence where possible
- Under 500 words
- Use hyphens, not em dashes
- If the prior assessments are thin, say so and explain what primary sources would be needed"""

MAX_COMMISSIONS_PER_RUN = 5


def load_credentials() -> tuple[str, str]:
    with open(_AGENT_JSON) as f:
        d = json.load(f)
    return d["telegram_bot_token"], d["telegram_chat_id"]


def send_telegram(token: str, chat_id: str, text: str):
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")


def get_open_commissions(conn: sqlite3.Connection) -> list[dict]:
    """Fetch open commissions ordered by priority."""
    priority_order = "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 WHEN 'low' THEN 3 ELSE 4 END"
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, title, brief, requestor, priority, assigned_to, submitted_at
        FROM commissions
        WHERE status = 'open'
        ORDER BY {priority_order}, submitted_at ASC
        LIMIT ?
    """, (MAX_COMMISSIONS_PER_RUN,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_domain_context(conn: sqlite3.Connection, agent_name: str,
                       commission_text: str) -> str:
    """Pull recent briefs relevant to the assigned agent's domain."""
    domain = AGENT_DOMAINS.get(agent_name, AGENT_DOMAINS["general_montgomery"])
    keywords = domain["keywords"]

    if not keywords:
        # General Montgomery - pull most recent briefs
        cur = conn.cursor()
        cur.execute("""
            SELECT title, content, created_at FROM briefs
            ORDER BY created_at DESC LIMIT 5
        """)
        rows = cur.fetchall()
    else:
        # Find briefs matching domain keywords
        rows = []
        cur = conn.cursor()
        for kw in keywords[:4]:
            cur.execute("""
                SELECT title, content, created_at FROM briefs
                WHERE lower(content) LIKE ? OR lower(title) LIKE ?
                ORDER BY created_at DESC LIMIT 3
            """, (f"%{kw}%", f"%{kw}%"))
            rows.extend(cur.fetchall())

    # Deduplicate
    seen = set()
    lines = []
    for title, content, created_at in rows:
        if title not in seen:
            seen.add(title)
            date_str = (created_at or "")[:10]
            lines.append(f"[{date_str}] {title}")
            lines.append((content or "")[:400])
            lines.append("")

    if not lines:
        return "No prior assessments found in this domain."

    return "\n".join(lines[:3000])


def dispatch_commission(conn: sqlite3.Connection, commission: dict) -> str:
    """Investigate a commission and return the output text."""
    agent_name = commission["assigned_to"] or "general_montgomery"
    domain = AGENT_DOMAINS.get(agent_name, AGENT_DOMAINS["general_montgomery"])

    # Build context
    context = get_domain_context(conn, agent_name, commission["brief"] or "")

    system = INVESTIGATION_SYSTEM.format(
        agent_name=domain["name"],
        focus=domain["focus"],
    )

    prompt = (
        f"COMMISSION: {commission['title']}\n"
        f"BRIEF: {commission['brief'] or 'No additional detail provided.'}\n"
        f"PRIORITY: {commission['priority']}\n"
        f"REQUESTED BY: {commission['requestor']}\n\n"
        f"PRIOR ASSESSMENTS:\n{context}"
    )

    return call_claude(system, prompt, model="sonnet", timeout=180)


def complete_commission(conn: sqlite3.Connection, commission_id: int,
                        output: str, title: str):
    """Mark commission complete and create a brief."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        UPDATE commissions SET status = 'complete', output = ?, completed_at = ?
        WHERE id = ?
    """, (output, now, commission_id))

    conn.execute("""
        INSERT INTO briefs (conflict_id, date, title, content, requested_by)
        VALUES (NULL, ?, ?, ?, 'commission_dispatcher')
    """, (datetime.now(timezone.utc).strftime("%Y-%m-%d"),
          f"[Commissioned] {title}", output))

    conn.commit()


def run(dry_run: bool = False):
    log.info("Commission dispatcher starting")
    conn = sqlite3.connect(str(_INTEL_DB))

    try:
        commissions = get_open_commissions(conn)
        if not commissions:
            log.info("No open commissions to dispatch")
            return

        log.info(f"Found {len(commissions)} open commission(s)")

        if dry_run:
            for c in commissions:
                print(f"  [{c['id']}] [{c['priority']}] {c['title']} -> {c['assigned_to']}")
            return

        completed = []

        for c in commissions:
            log.info(f"Dispatching commission {c['id']}: {c['title'][:60]}")

            # Mark in-progress
            conn.execute("UPDATE commissions SET status = 'in_progress' WHERE id = ?",
                         (c["id"],))
            conn.commit()

            try:
                output = dispatch_commission(conn, c)
                complete_commission(conn, c["id"], output, c["title"])
                completed.append(c)
                log.info(f"Commission {c['id']} complete ({len(output)} chars)")
            except Exception as e:
                log.error(f"Commission {c['id']} failed: {e}")
                # Revert to open so it can be retried
                conn.execute("UPDATE commissions SET status = 'open' WHERE id = ?",
                             (c["id"],))
                conn.commit()

        # Send summary to Telegram
        if completed:
            try:
                token, chat_id = load_credentials()
                lines = [f"*COMMISSIONS DISPATCHED - {len(completed)} completed*\n"]
                for c in completed:
                    lines.append(f"[{c['priority'].upper()}] {c['title'][:60]}")
                    lines.append(f"  Assigned: {c['assigned_to']}")
                send_telegram(token, chat_id, "\n".join(lines))
            except (KeyError, Exception) as e:
                log.warning(f"Telegram summary skipped: {e}")

    finally:
        conn.close()

    log.info("Commission dispatcher finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be dispatched without running")
    args = parser.parse_args()
    run(dry_run=args.dry_run)

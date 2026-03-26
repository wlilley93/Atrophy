#!/usr/bin/env python3
"""
Chief of Staff - Contradiction Check
Runs 12:00 daily. Scans recent briefs for contradictory assessments of the same
entity or conflict across different agents. Flags to Montgomery for adjudication.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.credentials import load_telegram_credentials

_ATROPHY_DIR = Path.home() / ".atrophy"
_INTEL_DB    = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"
_AGENT_JSON  = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "agent.json"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "chief_of_staff"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CoS-ContradCheck] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "contradiction_check.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("contradiction_check")

WINDOW_DAYS = 7

# Sentiment/position keywords - opposing pairs
OPPOSITIONS = [
    (["escalating", "escalation", "imminent", "critical", "surge"], ["de-escalating", "stable", "declining", "contained"]),
    (["advancing", "gaining", "offensive", "breakthrough"], ["retreating", "losing", "defensive", "stalled"]),
    (["strengthening", "consolidating"], ["weakening", "collapsing", "fragmenting"]),
    (["backed", "supported", "allied"], ["opposed", "sanctioned", "isolated"]),
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


def get_recent_briefs(conn: sqlite3.Connection) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, requested_by, title, content, created_at
        FROM briefs
        WHERE created_at >= ?
        AND requested_by != 'chief_of_staff'
        ORDER BY created_at DESC
    """, (cutoff,))
    return [
        {"id": r[0], "agent": r[1], "title": r[2],
         "content": (r[3] or "").lower(), "region": "", "ts": r[4]}
        for r in cur.fetchall()
    ]


def get_entities(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.cursor()
    cur.execute("SELECT id, name, type FROM entities LIMIT 200")
    return [{"id": r[0], "name": r[1].lower(), "type": r[2]} for r in cur.fetchall()]


def find_contradictions(briefs: list[dict], entities: list[dict]) -> list[dict]:
    """
    For each entity mentioned in 2+ briefs from different agents,
    check whether opposing sentiment terms appear.
    """
    contradictions = []
    entity_mentions: dict[str, list[dict]] = {}

    for brief in briefs:
        for entity in entities:
            if entity["name"] in brief["content"]:
                entity_mentions.setdefault(entity["name"], []).append(brief)

    for entity_name, mentioning_briefs in entity_mentions.items():
        if len(mentioning_briefs) < 2:
            continue

        # Group by agent to avoid intra-agent contradictions
        by_agent: dict[str, list[dict]] = {}
        for b in mentioning_briefs:
            by_agent.setdefault(b["agent"], []).append(b)
        if len(by_agent) < 2:
            continue

        # Check opposition pairs across agents
        for pos_terms, neg_terms in OPPOSITIONS:
            agents_positive = []
            agents_negative = []
            for agent, agent_briefs in by_agent.items():
                combined = " ".join(b["content"] for b in agent_briefs)
                has_pos = any(t in combined for t in pos_terms)
                has_neg = any(t in combined for t in neg_terms)
                if has_pos:
                    agents_positive.append(agent)
                if has_neg:
                    agents_negative.append(agent)

            if agents_positive and agents_negative:
                contradictions.append({
                    "entity": entity_name,
                    "positive_agents": agents_positive,
                    "negative_agents": agents_negative,
                    "positive_terms": [t for t in pos_terms
                                       if any(t in b["content"]
                                              for b in mentioning_briefs)],
                    "negative_terms": [t for t in neg_terms
                                       if any(t in b["content"]
                                              for b in mentioning_briefs)],
                })
                break  # one contradiction flag per entity is enough

    return contradictions


def log_contradiction_brief(conn: sqlite3.Connection, content: str):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO briefs (requested_by, date, title, content, created_at)
        VALUES (?, date('now'), ?, ?, ?)
    """, (
        "chief_of_staff",
        f"Contradiction Check - {datetime.now().strftime('%Y-%m-%d')}",
        content,
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()


def main():
    log.info("Contradiction check starting")
    cfg = load_cfg()

    conn = sqlite3.connect(_INTEL_DB)
    briefs = get_recent_briefs(conn)
    entities = get_entities(conn)
    log.info(f"Loaded {len(briefs)} briefs, {len(entities)} entities")

    contradictions = find_contradictions(briefs, entities)
    log.info(f"Found {len(contradictions)} potential contradictions")

    now_str = datetime.now().strftime("%d %b %Y %H:%M")
    lines = [f"*CONTRADICTION CHECK - {now_str}*",
             f"_Scan window: {WINDOW_DAYS} days | Briefs scanned: {len(briefs)}_", ""]

    if not contradictions:
        lines.append("No significant contradictions detected.")
        log.info("Clean - no contradictions")
    else:
        lines.append(f"*{len(contradictions)} contradiction(s) flagged for adjudication:*")
        lines.append("")
        for i, c in enumerate(contradictions, 1):
            lines.append(f"*{i}. {c['entity'].title()}*")
            lines.append(f"  Assessed positively by: {', '.join(c['positive_agents'])}")
            lines.append(f"  Terms: {', '.join(c['positive_terms'])}")
            lines.append(f"  Assessed negatively by: {', '.join(c['negative_agents'])}")
            lines.append(f"  Terms: {', '.join(c['negative_terms'])}")
            lines.append("")
        lines.append("_Recommend: Red Team review or Montgomery adjudication._")

    report = "\n".join(lines)
    log_contradiction_brief(conn, report)
    conn.close()

    if contradictions:
        try:
            send_telegram(*load_telegram_credentials("chief_of_staff"), report)
            log.info("Contradiction report sent to Telegram")
        except Exception as e:
            log.error(f"Telegram send failed: {e}")


if __name__ == "__main__":
    main()

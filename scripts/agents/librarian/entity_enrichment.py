#!/usr/bin/env python3
"""
Librarian - Entity Enrichment
Runs 03:00 daily. Reviews entities in intelligence.db marked for enrichment
(missing aliases, subtype, parent_id, or description). Attempts to fill from
recent briefs and signals in the DB. Updates entities table.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "general_montgomery"
_INTEL_DB    = _AGENT_DIR / "data" / "intelligence.db"
_AGENT_JSON  = _AGENT_DIR / "data" / "agent.json"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "librarian"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Librarian-Enrich] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "entity_enrichment.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("entity_enrichment")

# Subtype inference patterns
SUBTYPE_PATTERNS = {
    "person": [
        (r"\bpresident\b", "head_of_state"),
        (r"\bprime minister\b", "head_of_government"),
        (r"\bminister\b|\bsecretary\b", "minister"),
        (r"\bgeneral\b|\badmiral\b|\bmarshal\b", "military_commander"),
        (r"\bambassador\b", "diplomat"),
        (r"\bintelligence\b|\bspy\b|\bcia\b|\bmi6\b|\bmossad\b", "intelligence_officer"),
    ],
    "organization": [
        (r"\bmilitary\b|\barmy\b|\bforce\b|\bnavy\b|\bair force\b", "military"),
        (r"\bintelligence\b|\bspy\b", "intelligence_agency"),
        (r"\bparliament\b|\bcongress\b|\bsenate\b", "legislature"),
        (r"\bbank\b|\bfund\b|\bfinance\b", "financial"),
        (r"\btreaty\b|\bpact\b|\balliance\b", "alliance"),
    ],
    "faction": [
        (r"\bmilitia\b|\barmed\b|\bfighters\b", "armed_group"),
        (r"\bparty\b|\bmovement\b|\bpolitical\b", "political_movement"),
        (r"\bterror\b|\bjihad\b", "designated_terrorist"),
    ],
}

STATUS_KEYWORDS = {
    "active": ["active", "current", "ongoing", "operational"],
    "inactive": ["former", "dissolved", "disbanded", "defunct", "dead", "killed"],
    "unknown": [],
}


def load_cfg():
    with open(_AGENT_JSON) as f:
        return json.load(f)


def get_entities_needing_enrichment(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, type, subtype, description, status, aliases
        FROM entities
        WHERE subtype IS NULL OR description IS NULL OR status IS NULL
        ORDER BY updated_at ASC NULLS FIRST
        LIMIT 50
    """)
    return [
        {"id": r[0], "name": r[1], "type": r[2], "subtype": r[3],
         "description": r[4], "status": r[5], "aliases": r[6]}
        for r in cur.fetchall()
    ]


def get_recent_content(conn: sqlite3.Connection, entity_name: str) -> str:
    """Pull all brief/signal content mentioning this entity."""
    cur = conn.cursor()
    name_lower = entity_name.lower()

    cur.execute("""
        SELECT content FROM briefs
        WHERE lower(content) LIKE ?
        ORDER BY created_at DESC LIMIT 10
    """, (f"%{name_lower}%",))
    brief_content = " ".join(r[0] for r in cur.fetchall() if r[0])

    cur.execute("""
        SELECT content FROM signals
        WHERE lower(content) LIKE ?
        ORDER BY created_at DESC LIMIT 10
    """, (f"%{name_lower}%",))
    signal_content = " ".join(r[0] for r in cur.fetchall() if r[0])

    return (brief_content + " " + signal_content).lower()


def infer_subtype(entity_type: str, content: str) -> str | None:
    patterns = SUBTYPE_PATTERNS.get(entity_type, [])
    for pattern, subtype in patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return subtype
    return None


def infer_status(content: str) -> str:
    for status, keywords in STATUS_KEYWORDS.items():
        if any(kw in content for kw in keywords):
            return status
    return "unknown"


def extract_short_description(entity_name: str, entity_type: str, content: str) -> str | None:
    """
    Extract the first sentence from brief content that mentions the entity.
    Fallback to a generic description if nothing useful found.
    """
    sentences = re.split(r'[.!?]', content)
    name_lower = entity_name.lower()
    for sentence in sentences:
        s = sentence.strip()
        if name_lower in s and len(s) > 30:
            # Clean and cap
            clean = re.sub(r'\s+', ' ', s).strip().capitalize()
            return clean[:300] if len(clean) > 300 else clean
    return None


def enrich_entity(conn: sqlite3.Connection, entity: dict) -> bool:
    content = get_recent_content(conn, entity["name"])
    if not content.strip():
        return False

    updates = {}

    if not entity["subtype"]:
        subtype = infer_subtype(entity["type"], content)
        if subtype:
            updates["subtype"] = subtype

    if not entity["status"] or entity["status"] == "unknown":
        status = infer_status(content)
        if status != "unknown":
            updates["status"] = status

    if not entity["description"]:
        desc = extract_short_description(entity["name"], entity["type"], content)
        if desc:
            updates["description"] = desc

    if not updates:
        return False

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [datetime.now(timezone.utc).isoformat(), entity["id"]]
    conn.execute(
        f"UPDATE entities SET {set_clause}, updated_at = ? WHERE id = ?",
        values
    )
    conn.commit()
    log.info(f"Enriched '{entity['name']}': {list(updates.keys())}")
    return True


def log_enrichment_run(conn: sqlite3.Connection, enriched: int, skipped: int):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO briefs (requested_by, date, title, content, created_at)
        VALUES (?, date('now'), ?, ?, ?)
    """, (
        "librarian",
        f"Entity Enrichment Run - {datetime.now().strftime('%Y-%m-%d')}",
        f"Enrichment complete. Enriched: {enriched}. Skipped (no content): {skipped}.",
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()


def main():
    log.info("Entity enrichment starting")
    conn = sqlite3.connect(_INTEL_DB)

    entities = get_entities_needing_enrichment(conn)
    log.info(f"{len(entities)} entities require enrichment")

    enriched = 0
    skipped = 0
    for entity in entities:
        try:
            result = enrich_entity(conn, entity)
            if result:
                enriched += 1
            else:
                skipped += 1
        except Exception as e:
            log.warning(f"Failed to enrich '{entity['name']}': {e}")
            skipped += 1

    log.info(f"Enrichment complete. Enriched: {enriched}, Skipped: {skipped}")
    log_enrichment_run(conn, enriched, skipped)
    conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Horizon Extract - Parse RF '## Next 7 Days' sections into horizon_events.

Scans recent briefs from RF agents, extracts structured horizon entries,
deduplicates, and writes to intelligence.db.

Runs nightly at 04:00, after RF agents have produced their outputs.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from horizon_schema import ensure_table, _INTEL_DB

_ATROPHY_DIR = Path.home() / ".atrophy"
_LOG_DIR = _ATROPHY_DIR / "logs" / "general_montgomery"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [HorizonExtract] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "horizon_extract.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("horizon_extract")

# RF agents whose briefs we scan
RF_AGENTS = [
    "rf_russia_ukraine", "rf_uk_defence", "rf_european_security",
    "rf_gulf_iran_israel", "rf_indo_pacific", "rf_eu_nordic_monitor",
]

# Regex for the structured line format:
# - YYYY-MM-DD | CONFIDENCE | description
LINE_RE = re.compile(
    r"^-\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(CONFIRMED|HIGH|MEDIUM|SPECULATIVE)\s*\|\s*(.+)$",
    re.MULTILINE,
)

# Map keywords to event types
TYPE_KEYWORDS = {
    "diplomatic": ["summit", "visit", "negotiat", "talks", "diplomat", "ambassador",
                    "UN ", "NATO", "treaty", "ceasefire", "peace"],
    "economic": ["central bank", "rate", "ECB", "FOMC", "BoE", "sanction", "trade",
                 "tariff", "GDP", "inflation", "IMF", "World Bank"],
    "security": ["military", "exercise", "deploy", "strike", "shell", "offensive",
                 "missile", "drone", "naval", "airspace", "threat", "attack"],
    "political": ["election", "vote", "parliament", "speech", "legislation",
                  "referendum", "inaugurat", "resign", "cabinet"],
}


def classify_event_type(title: str) -> str:
    """Classify event type from title keywords."""
    title_lower = title.lower()
    scores = {t: 0 for t in TYPE_KEYWORDS}
    for event_type, keywords in TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                scores[event_type] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "political"  # default


def extract_horizon_from_brief(content: str, agent: str, brief_id: int) -> list[dict]:
    """Extract horizon events from a brief's ## Next 7 Days section."""
    # Find the section
    section_match = re.search(r"## Next 7 Days\s*\n(.*?)(?:\n##|\Z)", content, re.DOTALL)
    if not section_match:
        return []

    section_text = section_match.group(1)
    events = []
    for match in LINE_RE.finditer(section_text):
        date_str, confidence, description = match.groups()
        events.append({
            "event_date": date_str,
            "event_type": classify_event_type(description),
            "title": description.strip(),
            "confidence": confidence,
            "source": f"rf:{agent}",
            "brief_id": brief_id,
            "significance": "HIGH" if confidence in ("CONFIRMED", "HIGH") else "MEDIUM",
        })

    return events


def run():
    log.info("Horizon extraction starting")
    ensure_table()

    db = sqlite3.connect(str(_INTEL_DB))
    today = datetime.now(timezone.utc)
    lookback = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")

    # Get recent briefs from RF agents
    placeholders = ",".join("?" for _ in RF_AGENTS)
    rows = db.execute(
        f"""SELECT id, content, requested_by FROM briefs
        WHERE requested_by IN ({placeholders}) AND date >= ?
        ORDER BY date DESC""",
        (*RF_AGENTS, lookback),
    ).fetchall()

    if not rows:
        log.info("No recent RF briefs found")
        db.close()
        return

    # Track what we've already extracted (by brief_id)
    already_extracted = set()
    for row in db.execute(
        "SELECT DISTINCT brief_id FROM horizon_events WHERE brief_id IS NOT NULL"
    ).fetchall():
        already_extracted.add(row[0])

    # Build existing event keys for dedup
    existing_keys = set()
    for row in db.execute(
        "SELECT event_date, title FROM horizon_events WHERE event_date >= ?",
        (today_str,)
    ).fetchall():
        existing_keys.add(f"{row[0]}:{row[1].lower().strip()}")

    inserted = 0
    for brief_id, content, agent in rows:
        if brief_id in already_extracted:
            continue
        events = extract_horizon_from_brief(content, agent, brief_id)
        for event in events:
            key = f"{event['event_date']}:{event['title'].lower().strip()}"
            if key in existing_keys:
                continue
            db.execute(
                """INSERT INTO horizon_events
                (event_date, event_type, title, significance, confidence,
                 source, brief_id, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, date(?, '+1 day'))""",
                (event["event_date"], event["event_type"], event["title"],
                 event["significance"], event["confidence"],
                 event["source"], event["brief_id"],
                 event["event_date"]),
            )
            existing_keys.add(key)
            inserted += 1

    db.commit()
    db.close()

    log.info(f"Extracted {inserted} new horizon events from {len(rows)} briefs")
    if inserted > 0:
        print(f"Horizon: {inserted} new assessed events extracted from RF briefs")


if __name__ == "__main__":
    run()

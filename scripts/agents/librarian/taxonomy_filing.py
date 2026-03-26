#!/usr/bin/env python3
"""
Librarian - Taxonomy filing (hourly).
Scans new briefs in intelligence.db for entity mentions.
Extracts candidate entities via Claude API and upserts them.
Maintains the internal wiki taxonomy.
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
_LOG_DIR     = _ATROPHY_DIR / "logs" / "librarian"
_STATE_FILE  = _ATROPHY_DIR / "agents" / "librarian" / "data" / "state.json"

_APP_DIR = Path("/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron")
sys.path.insert(0, str(_APP_DIR / "mcp"))

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LIB] %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "taxonomy_filing.log"), logging.StreamHandler(sys.stderr)]
)
log = logging.getLogger("taxonomy_filing")



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

def load_state() -> dict:
    if _STATE_FILE.exists():
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"last_brief_id": 0}


def save_state(state: dict):
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def extract_entities(text: str) -> list[dict]:
    """Use Claude API to extract structured entities from brief text."""
    system = """Extract named entities from the intelligence text. Return JSON array only.
Each entity: {"name": str, "type": "country"|"organization"|"person"|"faction", "subtype": str|null, "description": str}
Focus on: countries, paramilitary groups, state agencies, named individuals with roles, military units.
Only entities with clear roles or significance. Max 15 per text. Return [] if none found."""

    try:
        raw = call_claude(system, text[:2000], "haiku").strip()
        # Extract JSON array
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        log.warning(f"Entity extraction failed: {e}")
    return []


def upsert_entity(db: sqlite3.Connection, entity: dict) -> bool:
    """Insert entity if not already present (match by name, case-insensitive)."""
    c = db.cursor()
    c.execute("SELECT id FROM entities WHERE lower(name) = lower(?)", (entity["name"],))
    if c.fetchone():
        return False  # Already exists
    c.execute("""
        INSERT INTO entities (name, type, subtype, description, status)
        VALUES (?, ?, ?, ?, 'active')
    """, (entity["name"], entity.get("type", "organization"),
          entity.get("subtype"), entity.get("description", "")))
    db.commit()
    return True


def run():
    log.info("Taxonomy filing cycle starting")
    state = load_state()
    db = sqlite3.connect(str(_INTEL_DB))
    new_entities_total = 0

    try:
        c = db.cursor()
        c.execute("""
            SELECT id, title, content FROM briefs
            WHERE id > ?
            ORDER BY id ASC LIMIT 20
        """, (state["last_brief_id"],))
        briefs = c.fetchall()

        if not briefs:
            log.info("No new briefs to process")
            return

        for brief_id, title, content in briefs:
            log.info(f"Processing brief {brief_id}: {title[:60]}")
            entities = extract_entities(content)
            added = 0
            for entity in entities:
                if upsert_entity(db, entity):
                    added += 1
                    log.info(f"  New entity: {entity['name']} ({entity['type']})")
            new_entities_total += added
            state["last_brief_id"] = brief_id

        log.info(f"Filing complete. New entities added: {new_entities_total}")

    finally:
        db.close()
    save_state(state)


if __name__ == "__main__":
    run()

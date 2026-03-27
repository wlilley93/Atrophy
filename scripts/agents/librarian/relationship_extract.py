#!/usr/bin/env python3
"""
Librarian - Relationship Extraction (hourly at :15).
Scans briefs in intelligence.db and extracts entity relationships via Claude Haiku.
Populates the relationships table to build out the knowledge graph.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_INTEL_DB    = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "librarian"
_STATE_FILE  = _ATROPHY_DIR / "agents" / "librarian" / "data" / "relationship_state.json"

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LIB-REL] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "relationship_extract.log"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("relationship_extract")

CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")

# Valid relationship types matching the schema
VALID_REL_TYPES = {
    "funds", "arms", "commands", "opposes", "allied_with",
    "brokers_for", "supplies", "mediates", "sanctions", "trains",
    "supports", "operates_in", "member_of", "parent_of",
}


def call_claude(system: str, prompt: str, model: str = "haiku") -> str:
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


def get_entity_lookup(db: sqlite3.Connection) -> dict[str, int]:
    """Build a case-insensitive name -> id lookup from the entities table.
    When duplicates exist, prefer the lowest id (original entry)."""
    cur = db.cursor()
    cur.execute("SELECT id, name FROM entities ORDER BY id ASC")
    lookup: dict[str, int] = {}
    for eid, name in cur.fetchall():
        key = name.strip().lower()
        if key not in lookup:
            lookup[key] = eid
    return lookup


def get_conflict_lookup(db: sqlite3.Connection) -> dict[str, int]:
    """Build slug/name -> id lookup for conflicts."""
    cur = db.cursor()
    cur.execute("SELECT id, name, slug FROM conflicts")
    lookup: dict[str, int] = {}
    for cid, name, slug in cur.fetchall():
        if slug:
            lookup[slug.lower()] = cid
        if name:
            lookup[name.strip().lower()] = cid
    return lookup


def relationship_exists(db: sqlite3.Connection, from_id: int, to_id: int, rel_type: str) -> bool:
    """Check if this exact relationship already exists."""
    cur = db.cursor()
    cur.execute(
        "SELECT 1 FROM relationships WHERE from_id = ? AND to_id = ? AND type = ?",
        (from_id, to_id, rel_type),
    )
    return cur.fetchone() is not None


def extract_relationships(text: str, entity_names: list[str]) -> list[dict]:
    """Use Claude Haiku to extract relationships from brief text."""
    entity_list = ", ".join(entity_names[:80])  # Cap to avoid prompt overflow

    system = f"""You are an intelligence analyst extracting entity relationships from text.

Known entities: {entity_list}

Extract relationships between these known entities. Return a JSON array only.
Each relationship: {{"from": str, "to": str, "type": str, "confidence": float, "notes": str}}

Valid relationship types: funds, arms, commands, opposes, allied_with, brokers_for, supplies, mediates, sanctions, trains, supports, operates_in, member_of, parent_of

Rules:
- ONLY use entity names from the known entities list (match spelling exactly)
- from/to must be different entities
- confidence: 0.5-1.0 based on evidence strength
- notes: one sentence explaining the relationship, sourced from the text
- Max 10 relationships per text
- Return [] if no clear relationships found
- Do not invent relationships not supported by the text"""

    try:
        raw = call_claude(system, text[:3000], "haiku").strip()
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        log.warning(f"Relationship extraction failed: {e}")
    return []


def insert_relationship(
    db: sqlite3.Connection,
    from_id: int,
    to_id: int,
    rel_type: str,
    confidence: float,
    notes: str,
    conflict_id: int | None,
    source: str,
) -> bool:
    """Insert a relationship if it doesn't already exist."""
    if relationship_exists(db, from_id, to_id, rel_type):
        return False
    db.execute(
        """INSERT INTO relationships (from_id, to_id, type, conflict_id, confidence, notes, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (from_id, to_id, rel_type, conflict_id, confidence, notes, source,
         datetime.now(timezone.utc).isoformat()),
    )
    return True


def run():
    log.info("Relationship extraction cycle starting")
    state = load_state()
    db = sqlite3.connect(str(_INTEL_DB))
    new_rels_total = 0
    skipped = 0
    errors = 0

    try:
        entity_lookup = get_entity_lookup(db)
        conflict_lookup = get_conflict_lookup(db)
        entity_names = list({name for name in entity_lookup})  # unique names

        cur = db.cursor()
        cur.execute(
            """SELECT id, title, content, conflict_id FROM briefs
               WHERE id > ? ORDER BY id ASC LIMIT 20""",
            (state["last_brief_id"],),
        )
        briefs = cur.fetchall()

        if not briefs:
            log.info("No new briefs to process")
            return

        log.info(f"Processing {len(briefs)} briefs against {len(entity_lookup)} entities")

        for brief_id, title, content, conflict_id in briefs:
            if not content or len(content.strip()) < 50:
                log.info(f"Brief {brief_id} too short, skipping: {title[:60]}")
                state["last_brief_id"] = brief_id
                continue

            # Skip meta-briefs (enrichment logs, contradiction checks, etc.)
            skip_prefixes = ("Entity Enrichment Run", "Contradiction Check")
            if title and any(title.startswith(p) for p in skip_prefixes):
                log.info(f"Brief {brief_id} is meta-brief, skipping: {title[:60]}")
                state["last_brief_id"] = brief_id
                continue

            log.info(f"Processing brief {brief_id}: {title[:60]}")

            try:
                relationships = extract_relationships(content, entity_names)
            except Exception as e:
                log.warning(f"Failed to extract from brief {brief_id}: {e}")
                errors += 1
                state["last_brief_id"] = brief_id
                continue

            added = 0
            for rel in relationships:
                from_name = rel.get("from", "").strip().lower()
                to_name = rel.get("to", "").strip().lower()
                rel_type = rel.get("type", "").strip().lower()
                confidence = min(1.0, max(0.0, float(rel.get("confidence", 0.7))))
                notes = rel.get("notes", "")

                from_id = entity_lookup.get(from_name)
                to_id = entity_lookup.get(to_name)

                if not from_id or not to_id:
                    skipped += 1
                    continue

                if from_id == to_id:
                    skipped += 1
                    continue

                if rel_type not in VALID_REL_TYPES:
                    # Try to map common variations
                    type_map = {
                        "allies": "allied_with",
                        "ally": "allied_with",
                        "alliance": "allied_with",
                        "oppose": "opposes",
                        "opposition": "opposes",
                        "fund": "funds",
                        "funding": "funds",
                        "arm": "arms",
                        "arming": "arms",
                        "supply": "supplies",
                        "supplying": "supplies",
                        "command": "commands",
                        "sanction": "sanctions",
                        "train": "trains",
                        "training": "trains",
                        "support": "supports",
                        "supporting": "supports",
                        "mediate": "mediates",
                        "mediating": "mediates",
                        "broker": "brokers_for",
                        "brokering": "brokers_for",
                        "operates": "operates_in",
                        "member": "member_of",
                        "parent": "parent_of",
                    }
                    rel_type = type_map.get(rel_type, rel_type)
                    if rel_type not in VALID_REL_TYPES:
                        log.debug(f"Unknown relationship type '{rel_type}', skipping")
                        skipped += 1
                        continue

                source = f"brief:{brief_id}"

                if insert_relationship(db, from_id, to_id, rel_type, confidence,
                                       notes, conflict_id, source):
                    added += 1
                    log.info(f"  + {rel['from']} --[{rel_type}]--> {rel['to']} ({confidence:.1f})")
                else:
                    skipped += 1

            new_rels_total += added
            state["last_brief_id"] = brief_id
            # Commit and save state after each brief so progress survives crashes
            db.commit()
            save_state(state)

        log.info(
            f"Extraction complete. New relationships: {new_rels_total}, "
            f"Skipped: {skipped}, Errors: {errors}"
        )

    finally:
        db.close()


if __name__ == "__main__":
    run()

#!/usr/bin/env python3
"""
Librarian: Review pending dedupe_candidates and judge each pair semantically.

For each pending candidate:
- Pull full context (descriptions, country, properties) from intelligence.db
- Ask the LLM (haiku for cost efficiency): "Are these the same entity?"
- Record verdict (yes/no/uncertain) and reason
- ontology_dedupe.py --apply-reviewed will then merge confirmed pairs

Batches candidates in groups of 10 per LLM call to amortize cost.

Usage:
    python3 dedupe_review.py [--max N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Path setup so we can import shared.claude_cli
_SHARED = Path(__file__).resolve().parent.parent.parent / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

DB_PATH = Path.home() / ".atrophy" / "agents" / "general_montgomery" / "data" / "intelligence.db"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LIB-DEDUPE] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("lib-dedupe")

BATCH_SIZE = 10  # Pairs per LLM call
DEFAULT_MAX = 50  # Max candidates per cron run


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def get_object_context(conn, obj_id):
    """Pull descriptive context for an object: name, type, country, description, top properties."""
    obj = conn.execute(
        "SELECT name, type, country_code, description, lat, lon FROM objects WHERE id = ?",
        (obj_id,),
    ).fetchone()
    if not obj:
        return None

    # Top 5 properties
    try:
        props = conn.execute(
            "SELECT key, value FROM properties WHERE object_id = ? LIMIT 5",
            (obj_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        props = []

    return {
        "id": obj_id,
        "name": obj["name"],
        "type": obj["type"],
        "country": obj["country_code"] or "",
        "description": (obj["description"] or "")[:200],
        "lat": obj["lat"],
        "lon": obj["lon"],
        "properties": [{"key": p["key"], "value": p["value"]} for p in props],
    }


def build_judgment_prompt(pairs):
    """Build a JSON-output prompt that asks about multiple pairs at once."""
    pair_blocks = []
    for pair in pairs:
        a = pair["a"]
        b = pair["b"]
        block = {
            "pair_id": pair["id"],
            "a": {
                "name": a["name"],
                "type": a["type"],
                "country": a["country"],
                "description": a["description"][:120],
            },
            "b": {
                "name": b["name"],
                "type": b["type"],
                "country": b["country"],
                "description": b["description"][:120],
            },
        }
        if a["lat"] is not None:
            block["a"]["coords"] = [a["lat"], a["lon"]]
        if b["lat"] is not None:
            block["b"]["coords"] = [b["lat"], b["lon"]]
        pair_blocks.append(block)

    return f"""You are an entity disambiguation classifier for a geopolitical intelligence database.

For each pair, judge whether A and B refer to the SAME real-world entity.

Rules:
- "yes" if they are clearly the same entity (different names/spellings/aliases for one thing)
- "no" if they are distinct entities (e.g. a city and an embassy in that city)
- "uncertain" if you cannot tell from the available data

REJECT (these are NOT the same):
- A city and a building/facility/embassy located in that city
- Different units of an organization (Brigade A vs Brigade B)
- Countries and individual facilities within them
- Different reactor units at the same plant (Unit 1 vs Unit 2)
- Different camps on the same base
- Different organizations sharing a name root (GRU vs GRU Spetsnaz Brigade 22)

ACCEPT (these ARE the same):
- Same place with different name formats (US/USA, IDF/Israel Defense Forces)
- Same facility, abbreviated vs full (Natanz / Natanz Nuclear Facility / Natanz Enrichment)
- Same place transliterated (Sao Paulo / São Paulo)
- "Port of X" and "X Port" for the same port
- Same entity with capitalization variants

Pairs to judge:
{json.dumps(pair_blocks, indent=2)}

Respond with ONLY a JSON array, no prose, no markdown. One object per pair:
[
  {{"pair_id": 1, "verdict": "yes", "reason": "brief reason"}},
  {{"pair_id": 2, "verdict": "no", "reason": "brief reason"}}
]
"""


def parse_judgments(text, expected_pair_ids):
    """Parse LLM JSON output: extract verdicts for each pair."""
    verdicts = {}

    # Strip markdown fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Drop first line and trailing ```
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find a JSON array in the text
        import re
        m = re.search(r'\[\s*\{.*\}\s*\]', cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                log.warning(f"Could not parse JSON from response: {cleaned[:200]}")
                return verdicts
        else:
            log.warning(f"No JSON found in response: {cleaned[:200]}")
            return verdicts

    if not isinstance(data, list):
        log.warning(f"Expected JSON array, got {type(data)}")
        return verdicts

    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            pair_id = int(item.get("pair_id", 0))
        except (ValueError, TypeError):
            continue
        verdict = str(item.get("verdict", "")).lower().strip()
        if verdict not in ("yes", "no", "uncertain"):
            verdict = "uncertain"
        reason = str(item.get("reason", ""))[:200]
        verdicts[pair_id] = (verdict, reason)
    return verdicts


def call_llm(prompt):
    """Call Claude haiku via the shared claude_cli helper."""
    try:
        from claude_cli import call_claude
    except ImportError:
        log.error("claude_cli not available - cannot run semantic review")
        return None
    try:
        result = call_claude(
            system="You are a precise entity disambiguation classifier. Output only the requested format.",
            prompt=prompt,
            model="haiku",
            timeout=120,
        )
        return result
    except Exception as e:
        log.error(f"LLM call failed: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=DEFAULT_MAX, help="Max candidates per run")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DB_PATH.exists():
        log.error(f"intelligence.db not found at {DB_PATH}")
        sys.exit(1)

    conn = get_conn()
    try:
        # Get pending candidates
        pending = conn.execute(
            "SELECT id, keeper_id, dupe_id, keeper_name, dupe_name, obj_type, detection_reason "
            "FROM dedupe_candidates WHERE status = 'pending' ORDER BY created_at LIMIT ?",
            (args.max,),
        ).fetchall()

        if not pending:
            log.info("No pending candidates")
            return

        log.info(f"Reviewing {len(pending)} pending candidates")

        # Build pair contexts
        pair_data = []
        for cand in pending:
            a_ctx = get_object_context(conn, cand["keeper_id"])
            b_ctx = get_object_context(conn, cand["dupe_id"])
            if not a_ctx or not b_ctx:
                # Object was deleted - mark candidate as obsolete
                conn.execute(
                    "UPDATE dedupe_candidates SET status='obsolete', verdict_reason='object missing' WHERE id=?",
                    (cand["id"],),
                )
                continue
            pair_data.append({
                "id": cand["id"],
                "candidate_id": cand["id"],
                "keeper_id": cand["keeper_id"],
                "dupe_id": cand["dupe_id"],
                "a": a_ctx,
                "b": b_ctx,
            })

        if not pair_data:
            log.info("All candidates were obsolete")
            return

        # Process in batches
        total_reviewed = 0
        for batch_start in range(0, len(pair_data), BATCH_SIZE):
            batch = pair_data[batch_start:batch_start + BATCH_SIZE]
            log.info(f"Reviewing batch {batch_start // BATCH_SIZE + 1}: {len(batch)} pairs")

            prompt = build_judgment_prompt(batch)

            if args.dry_run:
                log.info(f"  [DRY RUN] would call LLM with {len(prompt)} char prompt")
                log.info(f"  First 500 chars:\n{prompt[:500]}")
                continue

            response = call_llm(prompt)
            if not response:
                log.warning("  LLM call failed - skipping batch")
                continue

            verdicts = parse_judgments(response, [p["id"] for p in batch])
            log.info(f"  Got {len(verdicts)} verdicts")

            # Record verdicts
            for pair in batch:
                pid = pair["id"]
                if pid in verdicts:
                    verdict, reason = verdicts[pid]
                    new_status = "approved" if verdict == "yes" else ("rejected" if verdict == "no" else "pending")
                    conn.execute(
                        """UPDATE dedupe_candidates
                           SET verdict=?, verdict_reason=?, status=?,
                               reviewed_at=?, reviewed_by='librarian'
                           WHERE id=?""",
                        (verdict, reason[:200], new_status, NOW, pid),
                    )
                    total_reviewed += 1
                    log.info(f"    pair {pid}: {pair['a']['name']} <-> {pair['b']['name']} = {verdict} ({reason[:60]})")

            conn.commit()

        log.info(f"Reviewed {total_reviewed} candidates total")

        # Stats
        approved = conn.execute("SELECT COUNT(*) FROM dedupe_candidates WHERE status='approved'").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM dedupe_candidates WHERE status='rejected'").fetchone()[0]
        log.info(f"Queue state: approved={approved}, rejected={rejected}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

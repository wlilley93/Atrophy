#!/usr/bin/env python3
"""
Find candidate duplicate object pairs using loose heuristics, write them to
the dedupe_candidates table for librarian semantic review.

This is the high-recall counterpart to ontology_dedupe.py:
- ontology_dedupe.py uses tight rules to merge SAFE duplicates immediately
- this script uses loose rules to find SUSPECTED duplicates that need review

The librarian agent reads pending candidates, judges each pair semantically
(is "Tehran" the same as "Russian Embassy Tehran"? no.), and records the
verdict back. Confirmed merges get applied by ontology_dedupe.py --apply-reviewed.

Usage:
    python3 dedupe_find_candidates.py [--dry-run] [--max-candidates N]
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".atrophy" / "agents" / "general_montgomery" / "data" / "intelligence.db"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [dedupe-candidates] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("dedupe-candidates")

GEO_TOLERANCE = 0.05  # ~5km
MAX_CANDIDATES = 500  # cap per run to avoid filling the table


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def insert_candidate(conn, keeper_id, dupe_id, keeper_name, dupe_name, obj_type, reason, confidence, dry_run=False):
    """Insert a pending candidate (skip if already exists)."""
    if dry_run:
        log.info(f"  CANDIDATE: '{keeper_name}' ({keeper_id}) <-> '{dupe_name}' ({dupe_id}) [{obj_type}] {reason} conf={confidence:.2f}")
        return False
    try:
        conn.execute(
            """INSERT OR IGNORE INTO dedupe_candidates
               (keeper_id, dupe_id, keeper_name, dupe_name, obj_type, detection_reason, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (keeper_id, dupe_id, keeper_name, dupe_name, obj_type, reason, confidence),
        )
        return conn.total_changes > 0
    except sqlite3.IntegrityError:
        return False


def find_geo_candidates(conn, dry_run=False):
    """Find pairs at the same coordinates (any type that's a place-like)."""
    log.info("=== Phase 1: Geographic candidates ===")
    rows = conn.execute("""
        SELECT id, name, type, lat, lon
        FROM objects
        WHERE lat IS NOT NULL AND lon IS NOT NULL
          AND type IN ('location', 'facility', 'base', 'site', 'installation', 'city')
        ORDER BY type, lat, lon
    """).fetchall()

    buckets = {}
    for row in rows:
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (TypeError, ValueError):
            continue
        key = (row["type"], round(lat, 1), round(lon, 1))
        buckets.setdefault(key, []).append({
            "id": row["id"], "name": row["name"], "lat": lat, "lon": lon,
        })

    found = 0
    for bucket_key, candidates in buckets.items():
        if len(candidates) < 2:
            continue
        type_name = bucket_key[0]
        for i, a in enumerate(candidates):
            for b in candidates[i + 1:]:
                if abs(a["lat"] - b["lat"]) > GEO_TOLERANCE:
                    continue
                if abs(a["lon"] - b["lon"]) > GEO_TOLERANCE:
                    continue
                # Must share at least one significant token
                a_words = {w.lower() for w in a["name"].split() if len(w) >= 3}
                b_words = {w.lower() for w in b["name"].split() if len(w) >= 3}
                if not (a_words & b_words):
                    continue

                # Pick keeper as the longer-named one (more descriptive)
                if len(a["name"]) >= len(b["name"]):
                    keeper, dupe = a, b
                else:
                    keeper, dupe = b, a

                if insert_candidate(
                    conn, keeper["id"], dupe["id"], keeper["name"], dupe["name"],
                    type_name, "geo_coord_match", 0.6, dry_run,
                ):
                    found += 1
                    if found >= MAX_CANDIDATES:
                        log.info(f"  Hit max candidates limit ({MAX_CANDIDATES})")
                        return found
    log.info(f"  Found {found} geographic candidates")
    return found


def find_name_substring_candidates(conn, dry_run=False, count_so_far=0):
    """Find pairs where one name is a substring of another (same type)."""
    log.info("=== Phase 2: Name substring candidates ===")
    rows = conn.execute(
        "SELECT id, name, type FROM objects ORDER BY length(name)"
    ).fetchall()

    by_type = {}
    for row in rows:
        by_type.setdefault(row["type"], []).append({
            "id": row["id"], "name": row["name"], "type": row["type"],
        })

    found = 0
    seen_pairs = set()
    for type_name, objs in by_type.items():
        if type_name in ("event", "concept"):
            continue
        for i, short in enumerate(objs):
            short_lower = short["name"].lower().strip()
            short_words = [w for w in short_lower.split() if len(w) >= 3]
            if not short_words:
                continue
            for long in objs[i + 1:]:
                long_lower = long["name"].lower().strip()
                if long_lower == short_lower:
                    continue
                # Match: short name appears as contiguous prefix of long
                if not long_lower.startswith(short_lower + " "):
                    continue

                pair = tuple(sorted([short["id"], long["id"]]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                # Pick keeper as the longer-named one
                if len(long["name"]) >= len(short["name"]):
                    keeper, dupe = long, short
                else:
                    keeper, dupe = short, long

                if insert_candidate(
                    conn, keeper["id"], dupe["id"], keeper["name"], dupe["name"],
                    type_name, "name_prefix_match", 0.5, dry_run,
                ):
                    found += 1
                    if found + count_so_far >= MAX_CANDIDATES:
                        log.info(f"  Hit max candidates limit")
                        return found
    log.info(f"  Found {found} name substring candidates")
    return found


def main():
    global MAX_CANDIDATES
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-candidates", type=int, default=MAX_CANDIDATES)
    args = parser.parse_args()
    MAX_CANDIDATES = args.max_candidates

    if not DB_PATH.exists():
        log.error(f"intelligence.db not found at {DB_PATH}")
        sys.exit(1)

    conn = get_conn()
    try:
        # Pre-count
        pending = conn.execute(
            "SELECT COUNT(*) FROM dedupe_candidates WHERE status='pending'"
        ).fetchone()[0]
        log.info(f"Pending candidates already in queue: {pending}")

        if pending >= MAX_CANDIDATES:
            log.info("Queue is full - skipping discovery this cycle")
            return

        geo_count = find_geo_candidates(conn, dry_run=args.dry_run)
        name_count = find_name_substring_candidates(conn, dry_run=args.dry_run, count_so_far=geo_count)

        if not args.dry_run:
            conn.commit()

        # Post-count
        after = conn.execute(
            "SELECT COUNT(*) FROM dedupe_candidates WHERE status='pending'"
        ).fetchone()[0]
        log.info(f"Total pending after discovery: {after} (added {after - pending})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

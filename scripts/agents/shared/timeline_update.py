#!/usr/bin/env python3
"""Situation Timeline Update - tracks how conflicts evolve over time.

Reads recent briefs from the intelligence database, identifies which tracked
conflicts are referenced, then uses Claude Haiku to extract a trajectory
assessment (escalating / stable / de-escalating / crisis) for each.

Results are stored in the situation_timeline table for trend analysis.

Usage:
    python3 scripts/agents/shared/timeline_update.py
    python3 scripts/agents/shared/timeline_update.py --backfill   # process ALL briefs
    python3 scripts/agents/shared/timeline_update.py --days 14    # custom lookback

Environment:
    INTELLIGENCE_DB - path to intelligence.db (auto-detected if unset)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared imports
# ---------------------------------------------------------------------------

_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from claude_cli import call_claude

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_AGENT_NAME = "general_montgomery"
_DEFAULT_LOOKBACK_DAYS = 7


def _db_path() -> str:
    """Resolve intelligence.db path."""
    env = os.environ.get("INTELLIGENCE_DB")
    if env:
        return env
    return str(
        Path.home()
        / ".atrophy"
        / "agents"
        / "general_montgomery"
        / "data"
        / "intelligence.db"
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS situation_timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conflict_slug TEXT NOT NULL,
    date DATE NOT NULL,
    assessment TEXT NOT NULL CHECK(assessment IN ('escalating','stable','de-escalating','crisis')),
    summary TEXT,
    key_events TEXT,
    agent TEXT,
    brief_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (brief_id) REFERENCES briefs(id)
);
CREATE INDEX IF NOT EXISTS idx_timeline_conflict ON situation_timeline(conflict_slug);
CREATE INDEX IF NOT EXISTS idx_timeline_date ON situation_timeline(date);
"""


def ensure_schema(db: str) -> None:
    """Create the situation_timeline table if it does not exist."""
    con = sqlite3.connect(db, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
        con.executescript(_SCHEMA_SQL)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Conflict matching
# ---------------------------------------------------------------------------

def load_conflicts(db: str) -> list[dict]:
    """Load all tracked conflicts with search terms."""
    con = sqlite3.connect(db, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT id, slug, name FROM conflicts").fetchall()
        conflicts = []
        for r in rows:
            # Build search patterns from slug and name
            terms = set()
            terms.add(r["slug"])
            terms.add(r["name"].lower())
            # Add component words from the name (skip common short words)
            for word in r["name"].split():
                if len(word) > 3:
                    terms.add(word.lower())
            # Add specific aliases based on known conflicts
            slug = r["slug"]
            if slug == "ukraine":
                terms.update(["ukraine", "russia-ukraine", "donbas", "crimea", "zaporizhzhia", "kherson"])
            elif slug == "iran-israel":
                terms.update(["iran", "israel", "tehran", "idf", "irgc", "hezbollah"])
            elif slug == "sudan":
                terms.update(["sudan", "khartoum", "rsf", "rapid support forces", "darfur"])
            elif slug == "sahel":
                terms.update(["sahel", "mali", "burkina faso", "niger", "jnim", "wagner"])
            elif slug == "taiwan-strait":
                terms.update(["taiwan", "taipei", "pla", "strait"])
            elif slug == "yemen-red-sea":
                terms.update(["yemen", "houthi", "red sea", "bab el-mandeb", "aden"])
            elif slug == "south-china-sea":
                terms.update(["south china sea", "spratlys", "scarborough", "nine-dash"])
            elif slug == "kosovo-serbia":
                terms.update(["kosovo", "serbia", "pristina", "belgrade", "vucic"])

            conflicts.append({
                "id": r["id"],
                "slug": r["slug"],
                "name": r["name"],
                "terms": terms,
            })
        return conflicts
    finally:
        con.close()


def find_matching_conflicts(content: str, conflicts: list[dict]) -> list[dict]:
    """Find which conflicts are referenced in brief content."""
    content_lower = content.lower()
    matches = []
    for c in conflicts:
        for term in c["terms"]:
            if term in content_lower:
                matches.append(c)
                break
    return matches


# ---------------------------------------------------------------------------
# Brief loading
# ---------------------------------------------------------------------------

def load_briefs(db: str, since_date: str | None = None) -> list[dict]:
    """Load briefs, optionally filtered by date."""
    con = sqlite3.connect(db, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if since_date:
            rows = con.execute(
                "SELECT id, conflict_id, date, title, content FROM briefs WHERE date >= ? ORDER BY date",
                (since_date,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, conflict_id, date, title, content FROM briefs ORDER BY date"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Timeline extraction via Claude
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an intelligence analyst assessing conflict trajectories.
Given a brief about a specific conflict, determine its current trajectory.
Return ONLY valid JSON with no markdown formatting, no code fences, no explanation.
The JSON must have exactly these fields:
- assessment: one of "escalating", "stable", "de-escalating", "crisis"
- summary: one sentence describing the current situation
- key_events: comma-separated list of key events mentioned in the brief"""

_USER_TEMPLATE = """\
Conflict: {conflict_name}

Brief title: {title}
Brief date: {date}

Content:
{content}

Return JSON only: {{"assessment": "...", "summary": "...", "key_events": "..."}}"""


def extract_assessment(
    conflict_name: str, title: str, date: str, content: str
) -> dict | None:
    """Use Claude Haiku to extract a trajectory assessment from a brief."""
    # Truncate very long briefs to stay within reasonable token limits
    max_content = 3000
    if len(content) > max_content:
        content = content[:max_content] + "\n[truncated]"

    prompt = _USER_TEMPLATE.format(
        conflict_name=conflict_name,
        title=title,
        date=date,
        content=content,
    )

    try:
        raw = call_claude(
            system=_SYSTEM_PROMPT,
            prompt=prompt,
            model="haiku",
            timeout=60,
        )
    except (RuntimeError, Exception) as e:
        print(f"  Claude error: {e}", file=sys.stderr)
        return None

    # Parse JSON from response - handle markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        # Strip code fence
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                print(f"  Failed to parse JSON: {text[:200]}", file=sys.stderr)
                return None
        else:
            print(f"  No JSON found in response: {text[:200]}", file=sys.stderr)
            return None

    # Validate
    valid_assessments = {"escalating", "stable", "de-escalating", "crisis"}
    assessment = data.get("assessment", "").lower().strip()
    if assessment not in valid_assessments:
        print(f"  Invalid assessment '{assessment}', skipping", file=sys.stderr)
        return None

    return {
        "assessment": assessment,
        "summary": str(data.get("summary", "")).strip(),
        "key_events": str(data.get("key_events", "")).strip(),
    }


# ---------------------------------------------------------------------------
# Database write
# ---------------------------------------------------------------------------

def entry_exists(db: str, conflict_slug: str, date: str, brief_id: int) -> bool:
    """Check if a timeline entry already exists for this conflict+date+brief."""
    con = sqlite3.connect(db, timeout=30)
    try:
        row = con.execute(
            "SELECT 1 FROM situation_timeline WHERE conflict_slug = ? AND date = ? AND brief_id = ?",
            (conflict_slug, date, brief_id),
        ).fetchone()
        return row is not None
    finally:
        con.close()


def insert_entry(
    db: str,
    conflict_slug: str,
    date: str,
    assessment: str,
    summary: str,
    key_events: str,
    agent: str,
    brief_id: int,
) -> int:
    """Insert a timeline entry. Returns the new row id."""
    con = sqlite3.connect(db, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
        cur = con.execute(
            """INSERT INTO situation_timeline
               (conflict_slug, date, assessment, summary, key_events, agent, brief_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conflict_slug, date, assessment, summary, key_events, agent, brief_id),
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Situation Timeline Update")
    parser.add_argument(
        "--backfill", action="store_true",
        help="Process ALL briefs (not just recent ones)",
    )
    parser.add_argument(
        "--days", type=int, default=_DEFAULT_LOOKBACK_DAYS,
        help=f"Lookback window in days (default: {_DEFAULT_LOOKBACK_DAYS})",
    )
    args = parser.parse_args()

    db = _db_path()
    print(f"Intelligence DB: {db}")

    # Ensure schema
    ensure_schema(db)

    # Load conflicts
    conflicts = load_conflicts(db)
    print(f"Tracking {len(conflicts)} conflicts: {', '.join(c['slug'] for c in conflicts)}")

    # Load briefs
    if args.backfill:
        print("Backfill mode: processing ALL briefs")
        briefs = load_briefs(db)
    else:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
        print(f"Processing briefs since {since}")
        briefs = load_briefs(db, since_date=since)

    print(f"Found {len(briefs)} briefs to process\n")

    # Skip briefs with very short content (enrichment runs, empty stubs)
    min_content_length = 200
    briefs = [b for b in briefs if len(b["content"]) >= min_content_length]
    print(f"After filtering short content: {len(briefs)} briefs\n")

    # Process each brief
    created = 0
    skipped_exists = 0
    skipped_no_match = 0
    skipped_error = 0
    assessments_by_conflict: dict[str, list[str]] = {}

    for brief in briefs:
        brief_id = brief["id"]
        date = brief["date"]
        title = brief["title"]
        content = brief["content"]

        # Find which conflicts this brief mentions
        # If the brief has a direct conflict_id, always include that conflict
        matches = find_matching_conflicts(content, conflicts)

        # Also add the directly-linked conflict if not already matched
        if brief["conflict_id"]:
            direct = [c for c in conflicts if c["id"] == brief["conflict_id"]]
            for d in direct:
                if d not in matches:
                    matches.append(d)

        if not matches:
            skipped_no_match += 1
            continue

        print(f"Brief #{brief_id}: {title}")
        print(f"  Matches: {', '.join(m['slug'] for m in matches)}")

        for conflict in matches:
            slug = conflict["slug"]
            name = conflict["name"]

            # Skip if entry already exists
            if entry_exists(db, slug, date, brief_id):
                print(f"  [{slug}] already exists, skipping")
                skipped_exists += 1
                continue

            # Extract assessment
            print(f"  [{slug}] extracting assessment...", end="", flush=True)
            result = extract_assessment(name, title, date, content)

            if result is None:
                print(" ERROR")
                skipped_error += 1
                continue

            # Insert
            row_id = insert_entry(
                db, slug, date,
                result["assessment"],
                result["summary"],
                result["key_events"],
                _AGENT_NAME,
                brief_id,
            )
            print(f" {result['assessment'].upper()} (id={row_id})")

            created += 1
            assessments_by_conflict.setdefault(slug, []).append(result["assessment"])

    # Summary
    print(f"\n{'='*60}")
    print(f"  TIMELINE UPDATE SUMMARY")
    print(f"{'='*60}")
    print(f"  Entries created:    {created}")
    print(f"  Already existed:    {skipped_exists}")
    print(f"  No conflict match:  {skipped_no_match}")
    print(f"  Extraction errors:  {skipped_error}")

    if assessments_by_conflict:
        print(f"\n  --- Assessments by Conflict ---")
        for slug, assessments in sorted(assessments_by_conflict.items()):
            latest = assessments[-1]
            print(f"    {slug}: {len(assessments)} new entries, latest = {latest.upper()}")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()

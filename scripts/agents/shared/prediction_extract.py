#!/usr/bin/env python3
"""Prediction Extraction - scans briefs and extracts forward-looking statements.

Reads briefs from intelligence.db, calls Claude Haiku to identify predictions,
forecasts, and forward-looking assessments, then stores them in the
assessment_outcomes table for later review.

Tracks which briefs have already been processed via a state file to avoid
duplicate extraction on subsequent runs.

Schedule: 0 5 * * *  (daily at 5am)

Usage:
    python3 scripts/agents/shared/prediction_extract.py [--days N] [--all]

Options:
    --days N   Only process briefs from the last N days (default: 3)
    --all      Process all briefs regardless of date

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
# Shared helpers
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_cli import call_claude

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_STATE_DIR = Path.home() / ".atrophy" / "state"
_STATE_FILE = _STATE_DIR / "prediction_extract_processed.json"


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
# State tracking - which briefs have been processed
# ---------------------------------------------------------------------------

def _load_processed() -> set[int]:
    """Load set of already-processed brief IDs."""
    if not _STATE_FILE.exists():
        return set()
    try:
        data = json.loads(_STATE_FILE.read_text())
        return set(data.get("processed_ids", []))
    except (json.JSONDecodeError, KeyError):
        return set()


def _save_processed(ids: set[int]) -> None:
    """Persist the set of processed brief IDs."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps({
        "processed_ids": sorted(ids),
        "last_run": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


# ---------------------------------------------------------------------------
# Brief fetching
# ---------------------------------------------------------------------------

def _fetch_briefs(db: str, days: int | None) -> list[dict]:
    """Fetch briefs from intelligence.db, optionally filtered by recency."""
    con = sqlite3.connect(db, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")

        if days is not None:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = con.execute(
                "SELECT id, date, title, content, requested_by FROM briefs "
                "WHERE date >= ? ORDER BY id",
                (cutoff,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, date, title, content, requested_by FROM briefs "
                "ORDER BY id"
            ).fetchall()

        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Prediction extraction via Claude
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = """\
You are an intelligence analyst reviewing briefs for forward-looking statements.
Extract predictions, forecasts, and forward-looking assessments only.
Do NOT extract statements of current fact, historical observations, or descriptions of existing conditions.
A prediction must be about something that has not yet happened or a claim about how events will unfold."""

_EXTRACT_PROMPT = """\
Extract all predictions, forecasts, and forward-looking assessments from this intelligence brief.
For each prediction, return a JSON array:
[{{
  "prediction": "exact text of the predictive statement",
  "confidence": 0.0-1.0 (how confident the brief seems about this prediction),
  "timeframe": "when this should be verifiable (e.g. '7 days', '30 days', '3 months', '6 months')",
  "domain": "which domain this covers (military, economic, political, diplomatic, humanitarian, technological)"
}}]

Only extract genuine predictions, not statements of current fact. Return [] if no predictions found.
Return ONLY valid JSON - no markdown fencing, no explanation.

---

BRIEF TITLE: {title}
DATE: {date}
AUTHOR: {author}

{content}"""


def _extract_predictions(brief: dict) -> list[dict]:
    """Call Claude Haiku to extract predictions from a single brief."""
    prompt = _EXTRACT_PROMPT.format(
        title=brief["title"],
        date=brief["date"],
        author=brief["requested_by"] or "unknown",
        content=brief["content"][:8000],  # cap to avoid token limits
    )

    try:
        raw = call_claude(
            system=_EXTRACT_SYSTEM,
            prompt=prompt,
            model="haiku",
            timeout=60,
        )
    except RuntimeError as e:
        print(f"  [!] Claude call failed for brief {brief['id']}: {e}")
        return []

    # Parse JSON from response - handle markdown fencing
    text = raw.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    try:
        predictions = json.loads(text)
        if not isinstance(predictions, list):
            print(f"  [!] Expected list, got {type(predictions).__name__} for brief {brief['id']}")
            return []
        return predictions
    except json.JSONDecodeError as e:
        print(f"  [!] JSON parse failed for brief {brief['id']}: {e}")
        print(f"      Raw response: {text[:200]}")
        return []


# ---------------------------------------------------------------------------
# Database write
# ---------------------------------------------------------------------------

def _store_predictions(db: str, brief: dict, predictions: list[dict]) -> int:
    """Write extracted predictions to assessment_outcomes. Returns count stored."""
    if not predictions:
        return 0

    con = sqlite3.connect(db, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")

        stored = 0
        for pred in predictions:
            prediction_text = pred.get("prediction", "").strip()
            if not prediction_text:
                continue

            confidence = pred.get("confidence")
            if confidence is not None:
                try:
                    confidence = float(confidence)
                    confidence = max(0.0, min(1.0, confidence))
                except (ValueError, TypeError):
                    confidence = None

            con.execute(
                """INSERT INTO assessment_outcomes
                   (brief_id, prediction, predicted_by, predicted_at,
                    outcome, confidence_at_prediction, outcome_notes)
                   VALUES (?, ?, ?, ?, 'PENDING', ?, ?)""",
                (
                    brief["id"],
                    prediction_text,
                    brief["requested_by"] or "unknown",
                    brief["date"],
                    confidence,
                    json.dumps({
                        "timeframe": pred.get("timeframe", "unknown"),
                        "domain": pred.get("domain", "unknown"),
                        "brief_title": brief["title"],
                    }),
                ),
            )
            stored += 1

        con.commit()
        return stored
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Extract predictions from intelligence briefs")
    parser.add_argument("--days", type=int, default=3, help="Process briefs from the last N days (default: 3)")
    parser.add_argument("--all", action="store_true", help="Process all briefs regardless of date")
    args = parser.parse_args()

    db = _db_path()
    print(f"Intelligence DB: {db}")

    # Load state
    processed = _load_processed()
    print(f"Previously processed: {len(processed)} briefs")

    # Fetch briefs
    days = None if args.all else args.days
    briefs = _fetch_briefs(db, days)
    print(f"Briefs in scope: {len(briefs)}")

    # Filter out already-processed briefs
    unprocessed = [b for b in briefs if b["id"] not in processed]
    print(f"Unprocessed: {len(unprocessed)}")

    if not unprocessed:
        print("Nothing to do.")
        return

    total_predictions = 0
    briefs_with_predictions = 0

    for i, brief in enumerate(unprocessed, 1):
        print(f"\n[{i}/{len(unprocessed)}] Brief #{brief['id']}: {brief['title'][:60]}...")

        predictions = _extract_predictions(brief)
        if predictions:
            stored = _store_predictions(db, brief, predictions)
            total_predictions += stored
            briefs_with_predictions += 1
            print(f"  -> {stored} prediction(s) stored")
        else:
            print(f"  -> No predictions found")

        # Mark as processed regardless of whether predictions were found
        processed.add(brief["id"])

    # Save state
    _save_processed(processed)

    # Summary
    print(f"\n{'='*50}")
    print(f"  PREDICTION EXTRACTION COMPLETE")
    print(f"  Briefs processed: {len(unprocessed)}")
    print(f"  Briefs with predictions: {briefs_with_predictions}")
    print(f"  Total predictions extracted: {total_predictions}")
    print(f"  Total briefs in state file: {len(processed)}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()

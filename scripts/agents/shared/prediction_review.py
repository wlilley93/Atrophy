#!/usr/bin/env python3
"""Prediction Review - evaluates pending predictions older than 30 days.

Reads PENDING predictions from assessment_outcomes, calls Claude Haiku to
assess whether each prediction has come true, and updates the outcome.

Schedule: 30 7 * * 1  (weekly Monday at 7:30am)

Usage:
    python3 scripts/agents/shared/prediction_review.py [--min-age-days N]

Options:
    --min-age-days N   Only review predictions older than N days (default: 30)

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
# Fetch pending predictions
# ---------------------------------------------------------------------------

def _fetch_pending(db: str, min_age_days: int) -> list[dict]:
    """Fetch PENDING predictions older than min_age_days."""
    cutoff = (datetime.now() - timedelta(days=min_age_days)).strftime("%Y-%m-%d")

    con = sqlite3.connect(db, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")

        rows = con.execute(
            """SELECT id, brief_id, prediction, predicted_by, predicted_at,
                      confidence_at_prediction, outcome_notes
               FROM assessment_outcomes
               WHERE outcome = 'PENDING'
                 AND predicted_at <= ?
               ORDER BY predicted_at""",
            (cutoff,),
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Prediction review via Claude
# ---------------------------------------------------------------------------

_REVIEW_SYSTEM = """\
You are an intelligence analyst reviewing past predictions against current knowledge.
Be honest and rigorous. A prediction is CORRECT only if the core claim materially came true.
PARTIAL means some elements were right but key aspects were wrong or the scale was off.
INCORRECT means the prediction was clearly wrong.
PENDING means it is still too early to judge or there is insufficient information."""

_REVIEW_PROMPT = """\
This prediction was made {days} days ago (on {date}):

"{prediction}"

Original context: predicted by {author}, confidence {confidence}.
{extra_context}

Based on your knowledge of current events up to today, assess the outcome.
Consider: did the core claim materialize? Was the direction correct even if timing was off?

Return ONLY valid JSON - no markdown fencing, no explanation:
{{"outcome": "CORRECT|INCORRECT|PARTIAL|PENDING", "reasoning": "brief explanation (1-2 sentences)"}}"""


def _review_prediction(pred: dict) -> dict | None:
    """Call Claude Haiku to review a single prediction. Returns outcome dict or None."""
    predicted_at = pred["predicted_at"]
    try:
        pred_date = datetime.strptime(predicted_at, "%Y-%m-%d")
        days_ago = (datetime.now() - pred_date).days
    except (ValueError, TypeError):
        days_ago = 30  # fallback

    confidence = pred.get("confidence_at_prediction")
    conf_str = f"{confidence:.0%}" if confidence is not None else "unspecified"

    # Parse extra context from outcome_notes
    extra = ""
    if pred.get("outcome_notes"):
        try:
            notes = json.loads(pred["outcome_notes"])
            parts = []
            if notes.get("domain"):
                parts.append(f"Domain: {notes['domain']}")
            if notes.get("timeframe"):
                parts.append(f"Expected timeframe: {notes['timeframe']}")
            if notes.get("brief_title"):
                parts.append(f"From brief: {notes['brief_title']}")
            extra = "\n".join(parts)
        except (json.JSONDecodeError, TypeError):
            extra = str(pred["outcome_notes"])

    prompt = _REVIEW_PROMPT.format(
        days=days_ago,
        date=predicted_at,
        prediction=pred["prediction"],
        author=pred["predicted_by"],
        confidence=conf_str,
        extra_context=extra if extra else "(no additional context)",
    )

    try:
        raw = call_claude(
            system=_REVIEW_SYSTEM,
            prompt=prompt,
            model="haiku",
            timeout=60,
        )
    except RuntimeError as e:
        print(f"  [!] Claude call failed for prediction {pred['id']}: {e}")
        return None

    # Parse JSON from response
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    try:
        result = json.loads(text)
        outcome = result.get("outcome", "").upper()
        if outcome not in ("CORRECT", "INCORRECT", "PARTIAL", "PENDING"):
            print(f"  [!] Invalid outcome '{outcome}' for prediction {pred['id']}")
            return None
        return {
            "outcome": outcome,
            "reasoning": result.get("reasoning", ""),
        }
    except json.JSONDecodeError as e:
        print(f"  [!] JSON parse failed for prediction {pred['id']}: {e}")
        print(f"      Raw response: {text[:200]}")
        return None


# ---------------------------------------------------------------------------
# Database update
# ---------------------------------------------------------------------------

def _update_outcome(db: str, pred_id: int, outcome: str, reasoning: str) -> None:
    """Update a prediction's outcome in the database."""
    now = datetime.now(timezone.utc).isoformat()

    con = sqlite3.connect(db, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")

        # Preserve existing outcome_notes and merge in the review
        row = con.execute(
            "SELECT outcome_notes FROM assessment_outcomes WHERE id = ?",
            (pred_id,),
        ).fetchone()

        existing_notes = {}
        if row and row[0]:
            try:
                existing_notes = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                existing_notes = {"original_notes": row[0]}

        existing_notes["review_reasoning"] = reasoning
        existing_notes["reviewed_at"] = now

        con.execute(
            """UPDATE assessment_outcomes
               SET outcome = ?,
                   reviewed_at = ?,
                   reviewed_by = 'prediction_review',
                   outcome_notes = ?
               WHERE id = ?""",
            (outcome, now, json.dumps(existing_notes), pred_id),
        )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Review pending predictions")
    parser.add_argument(
        "--min-age-days", type=int, default=30,
        help="Only review predictions older than N days (default: 30)",
    )
    args = parser.parse_args()

    db = _db_path()
    print(f"Intelligence DB: {db}")

    # Fetch pending predictions
    pending = _fetch_pending(db, args.min_age_days)
    print(f"Pending predictions older than {args.min_age_days} days: {len(pending)}")

    if not pending:
        print("Nothing to review.")
        return

    counts = {"CORRECT": 0, "INCORRECT": 0, "PARTIAL": 0, "PENDING": 0, "FAILED": 0}

    for i, pred in enumerate(pending, 1):
        trunc = pred["prediction"][:80]
        if len(pred["prediction"]) > 80:
            trunc += "..."
        print(f"\n[{i}/{len(pending)}] #{pred['id']}: {trunc}")

        result = _review_prediction(pred)
        if result:
            _update_outcome(db, pred["id"], result["outcome"], result["reasoning"])
            counts[result["outcome"]] += 1
            print(f"  -> {result['outcome']}: {result['reasoning'][:120]}")
        else:
            counts["FAILED"] += 1
            print(f"  -> FAILED (review call unsuccessful)")

    # Summary
    total_reviewed = sum(v for k, v in counts.items() if k != "FAILED")
    print(f"\n{'='*50}")
    print(f"  PREDICTION REVIEW COMPLETE")
    print(f"  Predictions reviewed: {total_reviewed}")
    print(f"  Correct:   {counts['CORRECT']}")
    print(f"  Incorrect: {counts['INCORRECT']}")
    print(f"  Partial:   {counts['PARTIAL']}")
    print(f"  Still pending: {counts['PENDING']}")
    if counts["FAILED"]:
        print(f"  Failed:    {counts['FAILED']}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()

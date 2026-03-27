#!/usr/bin/env python3
"""Systematic Red Team Review for intelligence briefs.

Challenges high-priority briefs (FLASH, WEEKLY_DIGEST, SYNTHESIS, INTSUM)
with an adversarial review before publication. Identifies unsupported claims,
single-source risks, alternative explanations, bias, and rates confidence.

Usage:
    # Review a single brief
    python3 scripts/agents/shared/red_team_review.py 27

    # Review all eligible briefs without a red team review
    python3 scripts/agents/shared/red_team_review.py

    # Importable
    from red_team_review import review_brief
    review_brief(27)

Environment:
    INTELLIGENCE_DB - path to intelligence.db (auto-detected if unset)
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Shared Claude CLI helper
# ---------------------------------------------------------------------------
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
from claude_cli import call_claude  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Product types that require red team review
_ELIGIBLE_TYPES = ("FLASH", "WEEKLY_DIGEST", "SYNTHESIS", "INTSUM")

# Minimum content length - skip stubs
_MIN_CONTENT_LENGTH = 200


def _intelligence_db() -> str:
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
# Red Team prompt
# ---------------------------------------------------------------------------

_RED_TEAM_SYSTEM = """\
You are a Red Team intelligence analyst. Your job is to challenge briefs \
and identify weaknesses. Be rigorous but fair. Flag genuine weaknesses, \
not hypothetical ones."""

_RED_TEAM_PROMPT = """\
Review this intelligence brief and provide:

1. UNSUPPORTED CLAIMS: List any assertions not backed by cited evidence
2. SINGLE-SOURCE RISKS: Identify claims that rely on only one data source
3. ALTERNATIVE EXPLANATIONS: For each key judgment, provide at least one plausible alternative interpretation
4. BIAS CHECK: Identify any confirmation bias, anchoring bias, or mirror imaging
5. CONFIDENCE ASSESSMENT: Rate overall confidence (HIGH/MODERATE/LOW) with justification

End your review with a single line in this exact format:
CONFIDENCE: HIGH|MODERATE|LOW

---

BRIEF:
"""


# ---------------------------------------------------------------------------
# Core review logic
# ---------------------------------------------------------------------------

def _extract_confidence(review_text: str) -> str:
    """Extract the confidence rating from the review output."""
    # Look for the explicit CONFIDENCE: line
    match = re.search(
        r"CONFIDENCE:\s*(HIGH|MODERATE|LOW)",
        review_text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()

    # Fallback: scan for confidence keywords in the last paragraph
    lower = review_text.lower()
    last_section = lower[-500:]
    if "high" in last_section and "confidence" in last_section:
        return "HIGH"
    if "low" in last_section and "confidence" in last_section:
        return "LOW"
    return "MODERATE"


def review_brief(
    brief_id: int,
    intel_db: str | None = None,
) -> dict[str, Any] | None:
    """Run red team review on a single brief.

    Args:
        brief_id: The brief ID to review.
        intel_db: Optional path to intelligence.db (auto-detected if None).

    Returns:
        Dict with review text, confidence, and metadata, or None if skipped.
    """
    db = intel_db or _intelligence_db()

    # Load the brief
    con = sqlite3.connect(db, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    try:
        row = con.execute(
            "SELECT id, title, content, product_type FROM briefs WHERE id = ?",
            (brief_id,),
        ).fetchone()
    finally:
        con.close()

    if not row:
        print(f"  Brief {brief_id} not found.", file=sys.stderr)
        return None

    _id, title, content, product_type = row

    # Skip stubs
    if len(content) < _MIN_CONTENT_LENGTH:
        print(f"  [{brief_id}] {title} - skipped (stub, {len(content)} chars)")
        result = {
            "skipped": True,
            "reason": "content too short for meaningful review",
            "content_length": len(content),
        }
        _write_review(db, brief_id, json.dumps(result, indent=2))
        return result

    print(f"  [{brief_id}] {title} ({product_type}, {len(content)} chars)")
    print(f"    Running red team review via Haiku...")

    # Call Claude Haiku for adversarial review
    prompt = _RED_TEAM_PROMPT + content
    try:
        review_text = call_claude(
            system=_RED_TEAM_SYSTEM,
            prompt=prompt,
            model="haiku",
            timeout=120,
        )
    except RuntimeError as e:
        print(f"    [ERROR] Claude CLI failed: {e}", file=sys.stderr)
        return None

    confidence = _extract_confidence(review_text)

    print(f"    Confidence: {confidence}")
    print(f"    Review length: {len(review_text)} chars")

    # Write to database
    _write_review(db, brief_id, review_text)

    return {
        "brief_id": brief_id,
        "title": title,
        "product_type": product_type,
        "confidence": confidence,
        "review_length": len(review_text),
        "review": review_text,
    }


def _write_review(db: str, brief_id: int, review_text: str) -> None:
    """Write the red team review back to the briefs table."""
    con = sqlite3.connect(db, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        con.execute(
            "UPDATE briefs SET red_team_review = ? WHERE id = ?",
            (review_text, brief_id),
        )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def review_all_eligible(intel_db: str | None = None) -> list[dict[str, Any]]:
    """Review all eligible briefs that have no red_team_review yet.

    Eligible product types: FLASH, WEEKLY_DIGEST, SYNTHESIS, INTSUM.

    Returns:
        List of review result dicts.
    """
    db = intel_db or _intelligence_db()

    placeholders = ",".join("?" for _ in _ELIGIBLE_TYPES)
    con = sqlite3.connect(db, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    try:
        rows = con.execute(
            f"SELECT id FROM briefs "
            f"WHERE product_type IN ({placeholders}) "
            f"AND (red_team_review IS NULL OR red_team_review = '') "
            f"ORDER BY id",
            _ELIGIBLE_TYPES,
        ).fetchall()
    finally:
        con.close()

    if not rows:
        print("No eligible briefs needing red team review.")
        return []

    print(f"Found {len(rows)} briefs eligible for red team review.\n")
    results = []
    for (bid,) in rows:
        result = review_brief(bid, intel_db=db)
        if result:
            results.append(result)
        print()

    return results


def print_summary(results: list[dict[str, Any]]) -> None:
    """Print a summary of red team review results."""
    if not results:
        print("No reviews to summarise.")
        return

    # Filter out skipped
    reviewed = [r for r in results if not r.get("skipped")]
    skipped = [r for r in results if r.get("skipped")]

    print(f"\n{'=' * 55}")
    print(f"  RED TEAM REVIEW SUMMARY")
    print(f"{'=' * 55}")
    print(f"  Total processed:  {len(results)}")
    print(f"  Reviewed:         {len(reviewed)}")
    print(f"  Skipped (stubs):  {len(skipped)}")
    print()

    if reviewed:
        # Confidence distribution
        confidence_counts: dict[str, int] = {}
        for r in reviewed:
            c = r.get("confidence", "UNKNOWN")
            confidence_counts[c] = confidence_counts.get(c, 0) + 1

        print(f"  CONFIDENCE DISTRIBUTION:")
        for level in ("HIGH", "MODERATE", "LOW", "UNKNOWN"):
            count = confidence_counts.get(level, 0)
            if count:
                bar = "#" * count
                print(f"    {level:<12s}  {count:>2d}  {bar}")

        print()
        print(f"  PER-BRIEF RESULTS:")
        for r in reviewed:
            print(
                f"    [{r['brief_id']}] {r['title'][:60]}"
                f"  ({r['product_type']}) - {r['confidence']}"
            )

    print(f"{'=' * 55}\n")


def print_distribution(intel_db: str | None = None) -> None:
    """Print red team review distribution across all briefs."""
    db = intel_db or _intelligence_db()

    con = sqlite3.connect(db, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    try:
        # Total eligible
        placeholders = ",".join("?" for _ in _ELIGIBLE_TYPES)
        total = con.execute(
            f"SELECT COUNT(*) FROM briefs WHERE product_type IN ({placeholders})",
            _ELIGIBLE_TYPES,
        ).fetchone()[0]

        reviewed = con.execute(
            f"SELECT COUNT(*) FROM briefs WHERE product_type IN ({placeholders}) "
            f"AND red_team_review IS NOT NULL AND red_team_review != ''",
            _ELIGIBLE_TYPES,
        ).fetchone()[0]

        # Get all reviews for confidence extraction
        rows = con.execute(
            f"SELECT id, title, product_type, red_team_review FROM briefs "
            f"WHERE product_type IN ({placeholders}) "
            f"AND red_team_review IS NOT NULL AND red_team_review != ''",
            _ELIGIBLE_TYPES,
        ).fetchall()
    finally:
        con.close()

    print(f"\n{'=' * 55}")
    print(f"  RED TEAM REVIEW STATUS")
    print(f"{'=' * 55}")
    print(f"  Eligible briefs:  {total}")
    print(f"  Reviewed:         {reviewed}")
    print(f"  Pending:          {total - reviewed}")
    print()

    if rows:
        confidence_counts: dict[str, int] = {}
        for _id, _title, _ptype, review in rows:
            # Skip JSON stubs (skipped entries)
            if review.strip().startswith("{"):
                continue
            c = _extract_confidence(review)
            confidence_counts[c] = confidence_counts.get(c, 0) + 1

        if confidence_counts:
            print(f"  CONFIDENCE DISTRIBUTION:")
            for level in ("HIGH", "MODERATE", "LOW"):
                count = confidence_counts.get(level, 0)
                if count:
                    bar = "#" * count
                    print(f"    {level:<12s}  {count:>2d}  {bar}")

    print(f"{'=' * 55}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) > 1:
        try:
            brief_id = int(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [brief_id]", file=sys.stderr)
            sys.exit(1)
        result = review_brief(brief_id)
        if result:
            print_summary([result])
    else:
        results = review_all_eligible()
        print_summary(results)

    print_distribution()


if __name__ == "__main__":
    main()

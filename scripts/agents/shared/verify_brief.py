#!/usr/bin/env python3
"""Multi-Source Verification Pipeline for intelligence briefs.

Cross-references claims in each brief against:
  1. WorldMonitor cache (cached API responses)
  2. Entity database (known actors, organisations, countries)
  3. Brief history (corroboration from other briefs)

Each claim gets a corroboration score (0-3+). The brief's overall
verification_score is the average, and verification_details stores
the full claim-by-claim breakdown as JSON.

Usage:
    # Verify a single brief
    python3 scripts/agents/shared/verify_brief.py 25

    # Verify all unverified briefs
    python3 scripts/agents/shared/verify_brief.py

    # Importable
    from verify_brief import verify_brief
    verify_brief(25)

Environment:
    INTELLIGENCE_DB - path to intelligence.db (auto-detected if unset)
    WORLDMONITOR_CACHE_DB - path to worldmonitor_cache.db (auto-detected)
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

# Minimum content length to bother verifying - skip stubs like
# "Enrichment complete" and "No significant contradictions detected"
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


def _worldmonitor_cache_db() -> str:
    env = os.environ.get("WORLDMONITOR_CACHE_DB")
    if env:
        return env
    return str(Path.home() / ".atrophy" / "worldmonitor_cache.db")


# ---------------------------------------------------------------------------
# Claim extraction via Claude Haiku
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = """\
Extract the 3-5 most important factual claims from this intelligence brief.
Return ONLY a JSON array, no markdown fencing, no commentary.
Each element: {"claim": "text of claim", "type": "event"|"trend"|"attribution"|"location", "keywords": ["key", "terms", "for", "search"]}

The keywords array should contain 3-6 specific nouns, proper names, or technical terms
that would help locate corroborating data in other sources. Prefer entity names,
place names, weapon systems, and measurable quantities.

Brief:
"""


def extract_claims(content: str) -> list[dict[str, Any]]:
    """Use Claude Haiku to extract key factual claims from a brief."""
    prompt = _EXTRACT_PROMPT + content
    try:
        raw = call_claude(
            system="You are a factual claim extractor. Return only valid JSON.",
            prompt=prompt,
            model="haiku",
            timeout=60,
        )
    except RuntimeError as e:
        print(f"  [WARN] Claude CLI failed: {e}", file=sys.stderr)
        return []

    # Strip markdown fencing if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        claims = json.loads(raw)
        if not isinstance(claims, list):
            print(f"  [WARN] Expected JSON array, got {type(claims).__name__}", file=sys.stderr)
            return []
        return claims
    except json.JSONDecodeError as e:
        print(f"  [WARN] JSON parse failed: {e}", file=sys.stderr)
        print(f"  [WARN] Raw output: {raw[:300]}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Corroboration checks
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace for fuzzy matching."""
    return re.sub(r"\s+", " ", text.lower().strip())


def check_worldmonitor_cache(
    keywords: list[str], cache_db: str
) -> dict[str, Any]:
    """Search WorldMonitor cache for keyword hits.

    Returns {"found": bool, "endpoints": [...], "hit_count": int}
    """
    result: dict[str, Any] = {"found": False, "endpoints": [], "hit_count": 0}

    if not Path(cache_db).exists():
        return result

    con = sqlite3.connect(cache_db, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    try:
        # Search response text for each keyword
        matching_endpoints: set[str] = set()
        total_hits = 0

        for kw in keywords:
            kw_lower = kw.lower()
            # Use LIKE for case-insensitive substring match
            rows = con.execute(
                "SELECT endpoint, response FROM cache WHERE LOWER(response) LIKE ?",
                (f"%{kw_lower}%",),
            ).fetchall()
            for endpoint, _resp in rows:
                matching_endpoints.add(endpoint)
                total_hits += 1

        if matching_endpoints:
            result["found"] = True
            result["endpoints"] = sorted(matching_endpoints)
            result["hit_count"] = total_hits
    finally:
        con.close()

    return result


def check_entity_database(
    keywords: list[str], intel_db: str
) -> dict[str, Any]:
    """Check if entities mentioned in the claim exist in the entities table.

    Returns {"found": bool, "entities": [...], "match_count": int}
    """
    result: dict[str, Any] = {"found": False, "entities": [], "match_count": 0}

    con = sqlite3.connect(intel_db, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    try:
        all_entities = con.execute(
            "SELECT name, aliases, type FROM entities"
        ).fetchall()
    finally:
        con.close()

    matched: list[str] = []
    for name, aliases_json, etype in all_entities:
        name_lower = name.lower()
        # Build searchable names: primary name + aliases
        searchable = [name_lower]
        if aliases_json:
            try:
                aliases = json.loads(aliases_json)
                searchable.extend(a.lower() for a in aliases)
            except (json.JSONDecodeError, TypeError):
                pass

        for kw in keywords:
            kw_lower = kw.lower()
            for s in searchable:
                if kw_lower in s or s in kw_lower:
                    matched.append(f"{name} ({etype})")
                    break
            else:
                continue
            break  # Already matched this entity, move to next

    if matched:
        result["found"] = True
        result["entities"] = matched
        result["match_count"] = len(matched)

    return result


def check_brief_history(
    claim_text: str, keywords: list[str], brief_id: int, intel_db: str
) -> dict[str, Any]:
    """Check if other briefs corroborate the same claim.

    Returns {"found": bool, "brief_ids": [...], "match_count": int}
    """
    result: dict[str, Any] = {"found": False, "brief_ids": [], "match_count": 0}

    con = sqlite3.connect(intel_db, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    try:
        # Get all other briefs with substantial content
        rows = con.execute(
            "SELECT id, content FROM briefs WHERE id != ? AND LENGTH(content) >= ?",
            (brief_id, _MIN_CONTENT_LENGTH),
        ).fetchall()
    finally:
        con.close()

    matching_ids: list[int] = []
    for other_id, other_content in rows:
        other_lower = _normalize(other_content)
        # Require at least 2 keyword matches for corroboration
        hits = sum(1 for kw in keywords if kw.lower() in other_lower)
        if hits >= 2:
            matching_ids.append(other_id)

    if matching_ids:
        result["found"] = True
        result["brief_ids"] = matching_ids
        result["match_count"] = len(matching_ids)

    return result


# ---------------------------------------------------------------------------
# Main verification logic
# ---------------------------------------------------------------------------

def verify_brief(brief_id: int, intel_db: str | None = None) -> dict[str, Any] | None:
    """Verify a single brief. Returns the verification details dict, or None on skip.

    Args:
        brief_id: The brief ID to verify.
        intel_db: Optional path to intelligence.db (auto-detected if None).

    Returns:
        Dict with claims, scores, and overall verification_score, or None if skipped.
    """
    db = intel_db or _intelligence_db()
    cache_db = _worldmonitor_cache_db()

    # Load brief
    con = sqlite3.connect(db, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    try:
        row = con.execute(
            "SELECT id, title, content FROM briefs WHERE id = ?", (brief_id,)
        ).fetchone()
    finally:
        con.close()

    if not row:
        print(f"  Brief {brief_id} not found.", file=sys.stderr)
        return None

    _id, title, content = row

    # Skip very short / stub briefs
    if len(content) < _MIN_CONTENT_LENGTH:
        print(f"  [{brief_id}] {title} - skipped (stub, {len(content)} chars)")
        # Still mark as verified with score 0 so we don't re-process
        details = {
            "skipped": True,
            "reason": "content too short for claim extraction",
            "content_length": len(content),
        }
        _write_verification(db, brief_id, 0, details)
        return details

    print(f"  [{brief_id}] {title} ({len(content)} chars)")

    # Extract claims
    print(f"    Extracting claims via Haiku...")
    claims = extract_claims(content)
    if not claims:
        print(f"    No claims extracted - marking as unverifiable")
        details = {"skipped": True, "reason": "no claims extracted"}
        _write_verification(db, brief_id, 0, details)
        return details

    print(f"    Found {len(claims)} claims")

    # Verify each claim
    verified_claims: list[dict[str, Any]] = []
    total_score = 0

    for i, claim in enumerate(claims):
        claim_text = claim.get("claim", "")
        claim_type = claim.get("type", "unknown")
        keywords = claim.get("keywords", [])

        if not keywords:
            # Fallback: split claim text into significant words
            keywords = [
                w for w in re.split(r"[\s,;:]+", claim_text)
                if len(w) > 3 and w[0].isupper()
            ]

        print(f"    Claim {i+1}: {claim_text[:80]}...")

        # Check all three sources
        wm_result = check_worldmonitor_cache(keywords, cache_db)
        entity_result = check_entity_database(keywords, db)
        history_result = check_brief_history(claim_text, keywords, brief_id, db)

        # Calculate corroboration score
        sources_corroborating = 0
        source_details: list[str] = []

        if wm_result["found"]:
            sources_corroborating += 1
            source_details.append(
                f"WorldMonitor cache ({wm_result['hit_count']} hits across "
                f"{len(wm_result['endpoints'])} endpoints)"
            )

        if entity_result["found"]:
            sources_corroborating += 1
            source_details.append(
                f"Entity DB ({entity_result['match_count']} entities: "
                f"{', '.join(entity_result['entities'][:5])})"
            )

        if history_result["found"]:
            sources_corroborating += 1
            source_details.append(
                f"Brief history ({history_result['match_count']} corroborating briefs: "
                f"IDs {history_result['brief_ids'][:5]})"
            )

        score_label = {
            0: "unverified",
            1: "single-source",
            2: "dual-source",
        }.get(sources_corroborating, "multi-source confirmed")

        print(f"      Score: {sources_corroborating} ({score_label})")
        for sd in source_details:
            print(f"        - {sd}")

        verified_claims.append({
            "claim": claim_text,
            "type": claim_type,
            "keywords": keywords,
            "corroboration_score": sources_corroborating,
            "score_label": score_label,
            "sources": {
                "worldmonitor": wm_result,
                "entities": entity_result,
                "brief_history": history_result,
            },
        })
        total_score += sources_corroborating

    # Overall score: average corroboration rounded to nearest int
    avg_score = round(total_score / len(verified_claims)) if verified_claims else 0

    details = {
        "claims": verified_claims,
        "claim_count": len(verified_claims),
        "average_corroboration": total_score / len(verified_claims) if verified_claims else 0,
        "overall_score": avg_score,
    }

    _write_verification(db, brief_id, avg_score, details)
    print(f"    Overall: {avg_score} (avg {details['average_corroboration']:.1f})")

    return details


def _write_verification(
    db: str, brief_id: int, score: int, details: dict[str, Any]
) -> None:
    """Write verification results back to the briefs table."""
    con = sqlite3.connect(db, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        con.execute(
            "UPDATE briefs SET verification_score = ?, verification_details = ? WHERE id = ?",
            (score, json.dumps(details, default=str), brief_id),
        )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def verify_all_unverified(intel_db: str | None = None) -> list[dict[str, Any]]:
    """Verify all briefs that have verification_score = 0 and no details."""
    db = intel_db or _intelligence_db()

    con = sqlite3.connect(db, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    try:
        rows = con.execute(
            "SELECT id FROM briefs WHERE verification_score = 0 "
            "AND (verification_details IS NULL OR verification_details = '') "
            "ORDER BY id"
        ).fetchall()
    finally:
        con.close()

    if not rows:
        print("No unverified briefs found.")
        return []

    print(f"Found {len(rows)} unverified briefs.\n")
    results = []
    for (bid,) in rows:
        result = verify_brief(bid, intel_db=db)
        if result:
            results.append({"brief_id": bid, **result})
        print()

    return results


def print_distribution(intel_db: str | None = None) -> None:
    """Print verification score distribution."""
    db = intel_db or _intelligence_db()

    con = sqlite3.connect(db, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    try:
        rows = con.execute(
            "SELECT verification_score, COUNT(*) FROM briefs GROUP BY verification_score ORDER BY verification_score"
        ).fetchall()
        total = con.execute("SELECT COUNT(*) FROM briefs").fetchone()[0]

        # Also get details on verified vs skipped
        verified_count = con.execute(
            "SELECT COUNT(*) FROM briefs WHERE verification_details IS NOT NULL AND verification_details != ''"
        ).fetchone()[0]
        skipped_count = con.execute(
            "SELECT COUNT(*) FROM briefs WHERE verification_details LIKE '%skipped%true%'"
        ).fetchone()[0]
    finally:
        con.close()

    print(f"\n{'='*50}")
    print(f"  VERIFICATION SCORE DISTRIBUTION")
    print(f"{'='*50}")
    print(f"  Total briefs:    {total}")
    print(f"  Processed:       {verified_count}")
    print(f"  Skipped (stubs): {skipped_count}")
    print(f"  Substantive:     {verified_count - skipped_count}")
    print()

    labels = {
        0: "Unverified/Stub",
        1: "Single-source",
        2: "Dual-source",
        3: "Multi-source confirmed",
    }
    for score, count in rows:
        label = labels.get(score, f"Score {score}")
        bar = "#" * count
        print(f"  {score} ({label:.<25s}) {count:>3d}  {bar}")

    print(f"{'='*50}\n")


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
        verify_brief(brief_id)
    else:
        verify_all_unverified()

    print_distribution()


if __name__ == "__main__":
    main()

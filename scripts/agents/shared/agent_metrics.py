#!/usr/bin/env python3
"""Agent Performance Metrics - monthly review of intelligence output quality.

Computes per-agent performance metrics across the Meridian intelligence system
by querying intelligence.db. Generates a PERFORMANCE brief and pushes it to
Montgomery's WorldMonitor channel.

Metrics computed:
  1. Brief output - count per agent, broken down by product_type
  2. Source diversity - distinct entities mentioned across each agent's briefs
  3. Verification quality - average verification_score per agent
  4. Red team confidence - HIGH/MODERATE/LOW distribution per agent
  5. Entity coverage - unique entities referenced per agent
  6. Prediction tracking - outcomes per agent (CORRECT/INCORRECT/PARTIAL/PENDING)
  7. Relationship contribution - relationships discovered from each agent's briefs

Usage:
    python3 scripts/agents/shared/agent_metrics.py

Environment:
    INTELLIGENCE_DB - path to intelligence.db (auto-detected if unset)
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Shared imports
# ---------------------------------------------------------------------------
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from channel_push import push_briefing  # noqa: E402


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

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


def _connect(db: str) -> sqlite3.Connection:
    """Open a read-only connection with a generous busy timeout."""
    con = sqlite3.connect(db, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# Metric queries
# ---------------------------------------------------------------------------

def _brief_output(con: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """1. Count of briefs per agent, broken down by product_type.

    Returns: {agent: {product_type: count, ...}, ...}
    """
    rows = con.execute(
        "SELECT requested_by, product_type, COUNT(*) AS cnt "
        "FROM briefs "
        "WHERE requested_by IS NOT NULL "
        "GROUP BY requested_by, product_type "
        "ORDER BY requested_by, product_type"
    ).fetchall()

    result: dict[str, dict[str, int]] = {}
    for r in rows:
        agent = r["requested_by"]
        ptype = r["product_type"] or "untyped"
        result.setdefault(agent, {})[ptype] = r["cnt"]
    return result


def _source_diversity(con: sqlite3.Connection) -> dict[str, int]:
    """2. Count of distinct entities mentioned across each agent's briefs.

    Returns: {agent: distinct_entity_count, ...}
    """
    rows = con.execute(
        "SELECT b.requested_by, COUNT(DISTINCT be.entity_id) AS entity_count "
        "FROM briefs b "
        "JOIN brief_entities be ON b.id = be.brief_id "
        "WHERE b.requested_by IS NOT NULL "
        "GROUP BY b.requested_by "
        "ORDER BY entity_count DESC"
    ).fetchall()

    return {r["requested_by"]: r["entity_count"] for r in rows}


def _verification_quality(con: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """3. Average verification_score per agent.

    Returns: {agent: {"avg_score": float, "brief_count": int, "max_score": int}, ...}
    """
    rows = con.execute(
        "SELECT requested_by, "
        "  AVG(verification_score) AS avg_score, "
        "  COUNT(*) AS cnt, "
        "  MAX(verification_score) AS max_score "
        "FROM briefs "
        "WHERE requested_by IS NOT NULL "
        "GROUP BY requested_by "
        "ORDER BY avg_score DESC"
    ).fetchall()

    return {
        r["requested_by"]: {
            "avg_score": round(r["avg_score"], 2) if r["avg_score"] else 0.0,
            "brief_count": r["cnt"],
            "max_score": r["max_score"] or 0,
        }
        for r in rows
    }


def _red_team_confidence(con: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """4. Count of HIGH/MODERATE/LOW red team confidence ratings per agent.

    Parses the CONFIDENCE: line from red_team_review text.
    Returns: {agent: {"HIGH": n, "MODERATE": n, "LOW": n}, ...}
    """
    rows = con.execute(
        "SELECT b.requested_by, b.red_team_review "
        "FROM briefs b "
        "WHERE b.requested_by IS NOT NULL "
        "AND b.red_team_review IS NOT NULL "
        "AND b.red_team_review <> ''"
    ).fetchall()

    result: dict[str, dict[str, int]] = {}
    for r in rows:
        agent = r["requested_by"]
        review = r["red_team_review"]

        # Skip JSON stubs (skipped entries)
        if review.strip().startswith("{"):
            continue

        # Extract confidence from the review text
        match = re.search(
            r"CONFIDENCE:\s*(HIGH|MODERATE|LOW)", review, re.IGNORECASE
        )
        if match:
            level = match.group(1).upper()
        else:
            # Fallback heuristic
            lower = review.lower()[-500:]
            if "high" in lower and "confidence" in lower:
                level = "HIGH"
            elif "low" in lower and "confidence" in lower:
                level = "LOW"
            else:
                level = "MODERATE"

        result.setdefault(agent, {"HIGH": 0, "MODERATE": 0, "LOW": 0})
        result[agent][level] += 1

    return result


def _entity_coverage(con: sqlite3.Connection) -> dict[str, list[str]]:
    """5. Unique entity names each agent's briefs reference.

    Returns: {agent: [entity_name, ...], ...}
    """
    rows = con.execute(
        "SELECT b.requested_by, e.name "
        "FROM briefs b "
        "JOIN brief_entities be ON b.id = be.brief_id "
        "JOIN entities e ON be.entity_id = e.id "
        "WHERE b.requested_by IS NOT NULL "
        "GROUP BY b.requested_by, e.id "
        "ORDER BY b.requested_by, e.name"
    ).fetchall()

    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r["requested_by"], []).append(r["name"])
    return result


def _prediction_tracking(con: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """6. Count of predictions per agent, breakdown by outcome.

    Returns: {agent: {"CORRECT": n, "INCORRECT": n, "PARTIAL": n, "PENDING": n, "EXPIRED": n, "total": n}, ...}
    """
    rows = con.execute(
        "SELECT predicted_by, outcome, COUNT(*) AS cnt "
        "FROM assessment_outcomes "
        "WHERE predicted_by IS NOT NULL "
        "GROUP BY predicted_by, outcome "
        "ORDER BY predicted_by, outcome"
    ).fetchall()

    result: dict[str, dict[str, int]] = {}
    for r in rows:
        agent = r["predicted_by"]
        outcome = r["outcome"] or "UNKNOWN"
        result.setdefault(agent, {"total": 0})
        result[agent][outcome] = r["cnt"]
        result[agent]["total"] += r["cnt"]
    return result


def _relationship_contribution(con: sqlite3.Connection) -> dict[str, int]:
    """7. Relationships discovered from each agent's briefs.

    The relationships.source field uses format 'brief:<id>'. We join back
    to briefs to attribute relationships to the requesting agent.

    Returns: {agent: relationship_count, ...}
    """
    rows = con.execute(
        "SELECT b.requested_by, COUNT(*) AS cnt "
        "FROM relationships r "
        "JOIN briefs b ON CAST(REPLACE(r.source, 'brief:', '') AS INTEGER) = b.id "
        "WHERE r.source LIKE 'brief:%' "
        "AND b.requested_by IS NOT NULL "
        "GROUP BY b.requested_by "
        "ORDER BY cnt DESC"
    ).fetchall()

    return {r["requested_by"]: r["cnt"] for r in rows}


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def compute_all_metrics(db: str | None = None) -> dict[str, Any]:
    """Compute all agent performance metrics.

    Returns a structured dict with all metric categories.
    """
    db_path = db or _intelligence_db()
    con = _connect(db_path)

    try:
        metrics = {
            "generated_at": datetime.now().isoformat(),
            "database": db_path,
            "brief_output": _brief_output(con),
            "source_diversity": _source_diversity(con),
            "verification_quality": _verification_quality(con),
            "red_team_confidence": _red_team_confidence(con),
            "entity_coverage": {
                agent: {"count": len(entities), "entities": entities}
                for agent, entities in _entity_coverage(con).items()
            },
            "prediction_tracking": _prediction_tracking(con),
            "relationship_contribution": _relationship_contribution(con),
        }
    finally:
        con.close()

    return metrics


def _format_text_report(metrics: dict[str, Any]) -> str:
    """Format metrics as a human-readable text report."""
    lines: list[str] = []
    sep = "=" * 60

    lines.append(sep)
    lines.append("  AGENT PERFORMANCE METRICS")
    lines.append(f"  Generated: {metrics['generated_at']}")
    lines.append(sep)

    # --- 1. Brief Output ---
    lines.append("")
    lines.append("  1. BRIEF OUTPUT BY AGENT")
    lines.append("  " + "-" * 40)
    brief_output = metrics["brief_output"]
    for agent in sorted(brief_output):
        types = brief_output[agent]
        total = sum(types.values())
        breakdown = ", ".join(f"{t}: {c}" for t, c in sorted(types.items()))
        lines.append(f"    {agent:<30s}  {total:>3d}  ({breakdown})")

    # --- 2. Source Diversity ---
    lines.append("")
    lines.append("  2. SOURCE DIVERSITY (distinct entities per agent)")
    lines.append("  " + "-" * 40)
    for agent, count in sorted(
        metrics["source_diversity"].items(), key=lambda x: -x[1]
    ):
        bar = "#" * min(count, 40)
        lines.append(f"    {agent:<30s}  {count:>3d}  {bar}")

    # --- 3. Verification Quality ---
    lines.append("")
    lines.append("  3. VERIFICATION QUALITY (avg verification score)")
    lines.append("  " + "-" * 40)
    for agent, data in sorted(
        metrics["verification_quality"].items(),
        key=lambda x: -x[1]["avg_score"],
    ):
        avg = data["avg_score"]
        cnt = data["brief_count"]
        mx = data["max_score"]
        lines.append(
            f"    {agent:<30s}  avg={avg:.2f}  max={mx}  (n={cnt})"
        )

    # --- 4. Red Team Confidence ---
    lines.append("")
    lines.append("  4. RED TEAM CONFIDENCE DISTRIBUTION")
    lines.append("  " + "-" * 40)
    rtc = metrics["red_team_confidence"]
    if rtc:
        for agent in sorted(rtc):
            dist = rtc[agent]
            parts = []
            for level in ("HIGH", "MODERATE", "LOW"):
                if dist.get(level, 0) > 0:
                    parts.append(f"{level}: {dist[level]}")
            lines.append(f"    {agent:<30s}  {', '.join(parts)}")
    else:
        lines.append("    No red team reviews found.")

    # --- 5. Entity Coverage ---
    lines.append("")
    lines.append("  5. ENTITY COVERAGE (unique entities referenced)")
    lines.append("  " + "-" * 40)
    ec = metrics["entity_coverage"]
    for agent in sorted(ec, key=lambda a: -ec[a]["count"]):
        count = ec[agent]["count"]
        top = ec[agent]["entities"][:5]
        top_str = ", ".join(top)
        if len(ec[agent]["entities"]) > 5:
            top_str += "..."
        lines.append(f"    {agent:<30s}  {count:>3d}  ({top_str})")

    # --- 6. Prediction Tracking ---
    lines.append("")
    lines.append("  6. PREDICTION TRACKING")
    lines.append("  " + "-" * 40)
    pt = metrics["prediction_tracking"]
    if pt:
        for agent in sorted(pt):
            data = pt[agent]
            total = data["total"]
            parts = []
            for outcome in ("CORRECT", "INCORRECT", "PARTIAL", "PENDING", "EXPIRED"):
                if data.get(outcome, 0) > 0:
                    parts.append(f"{outcome}: {data[outcome]}")
            lines.append(
                f"    {agent:<30s}  total={total:>3d}  ({', '.join(parts)})"
            )
    else:
        lines.append("    No predictions tracked.")

    # --- 7. Relationship Contribution ---
    lines.append("")
    lines.append("  7. RELATIONSHIP CONTRIBUTION (relationships discovered)")
    lines.append("  " + "-" * 40)
    rc = metrics["relationship_contribution"]
    for agent, count in sorted(rc.items(), key=lambda x: -x[1]):
        bar = "#" * min(count, 40)
        lines.append(f"    {agent:<30s}  {count:>3d}  {bar}")

    lines.append("")
    lines.append(sep)
    return "\n".join(lines)


def _format_markdown_report(metrics: dict[str, Any]) -> str:
    """Format metrics as markdown for the briefing body."""
    lines: list[str] = []

    lines.append("# Agent Performance Metrics")
    lines.append(f"*Generated: {metrics['generated_at']}*")
    lines.append("")

    # --- 1. Brief Output ---
    lines.append("## 1. Brief Output by Agent")
    lines.append("")
    lines.append("| Agent | Total | Breakdown |")
    lines.append("|-------|------:|-----------|")
    brief_output = metrics["brief_output"]
    for agent in sorted(brief_output):
        types = brief_output[agent]
        total = sum(types.values())
        breakdown = ", ".join(f"{t}: {c}" for t, c in sorted(types.items()))
        lines.append(f"| {agent} | {total} | {breakdown} |")
    lines.append("")

    # --- 2. Source Diversity ---
    lines.append("## 2. Source Diversity")
    lines.append("Distinct entities mentioned across each agent's briefs.")
    lines.append("")
    lines.append("| Agent | Distinct Entities |")
    lines.append("|-------|------------------:|")
    for agent, count in sorted(
        metrics["source_diversity"].items(), key=lambda x: -x[1]
    ):
        lines.append(f"| {agent} | {count} |")
    lines.append("")

    # --- 3. Verification Quality ---
    lines.append("## 3. Verification Quality")
    lines.append("")
    lines.append("| Agent | Avg Score | Max | Briefs |")
    lines.append("|-------|----------:|----:|-------:|")
    for agent, data in sorted(
        metrics["verification_quality"].items(),
        key=lambda x: -x[1]["avg_score"],
    ):
        lines.append(
            f"| {agent} | {data['avg_score']:.2f} | {data['max_score']} | {data['brief_count']} |"
        )
    lines.append("")

    # --- 4. Red Team Confidence ---
    lines.append("## 4. Red Team Confidence Distribution")
    lines.append("")
    rtc = metrics["red_team_confidence"]
    if rtc:
        lines.append("| Agent | HIGH | MODERATE | LOW |")
        lines.append("|-------|-----:|---------:|----:|")
        for agent in sorted(rtc):
            d = rtc[agent]
            lines.append(
                f"| {agent} | {d.get('HIGH', 0)} | {d.get('MODERATE', 0)} | {d.get('LOW', 0)} |"
            )
    else:
        lines.append("*No red team reviews found.*")
    lines.append("")

    # --- 5. Entity Coverage ---
    lines.append("## 5. Entity Coverage")
    lines.append("")
    ec = metrics["entity_coverage"]
    lines.append("| Agent | Unique Entities | Top Entities |")
    lines.append("|-------|----------------:|--------------|")
    for agent in sorted(ec, key=lambda a: -ec[a]["count"]):
        count = ec[agent]["count"]
        top = ec[agent]["entities"][:5]
        top_str = ", ".join(top)
        if len(ec[agent]["entities"]) > 5:
            top_str += "..."
        lines.append(f"| {agent} | {count} | {top_str} |")
    lines.append("")

    # --- 6. Prediction Tracking ---
    lines.append("## 6. Prediction Tracking")
    lines.append("")
    pt = metrics["prediction_tracking"]
    if pt:
        lines.append("| Agent | Total | Correct | Incorrect | Partial | Pending | Expired |")
        lines.append("|-------|------:|--------:|----------:|--------:|--------:|--------:|")
        for agent in sorted(pt):
            d = pt[agent]
            lines.append(
                f"| {agent} | {d['total']} | "
                f"{d.get('CORRECT', 0)} | {d.get('INCORRECT', 0)} | "
                f"{d.get('PARTIAL', 0)} | {d.get('PENDING', 0)} | "
                f"{d.get('EXPIRED', 0)} |"
            )
    else:
        lines.append("*No predictions tracked.*")
    lines.append("")

    # --- 7. Relationship Contribution ---
    lines.append("## 7. Relationship Contribution")
    lines.append("Relationships discovered from each agent's briefs.")
    lines.append("")
    lines.append("| Agent | Relationships |")
    lines.append("|-------|-------------:|")
    rc = metrics["relationship_contribution"]
    for agent, count in sorted(rc.items(), key=lambda x: -x[1]):
        lines.append(f"| {agent} | {count} |")
    lines.append("")

    return "\n".join(lines)


def _generate_headline(metrics: dict[str, Any]) -> str:
    """Generate a one-line headline summarising the metrics."""
    total_briefs = sum(
        sum(types.values()) for types in metrics["brief_output"].values()
    )
    agent_count = len(metrics["brief_output"])
    total_predictions = sum(
        d["total"] for d in metrics["prediction_tracking"].values()
    )
    total_relationships = sum(metrics["relationship_contribution"].values())

    return (
        f"{total_briefs} briefs across {agent_count} agents, "
        f"{total_predictions} predictions tracked, "
        f"{total_relationships} relationships attributed"
    )


# ---------------------------------------------------------------------------
# Write brief to database
# ---------------------------------------------------------------------------

def _write_performance_brief(
    db: str, title: str, content: str, metrics_json: str
) -> int:
    """Insert a PERFORMANCE brief into intelligence.db.

    Returns the new brief ID.
    """
    con = sqlite3.connect(db, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        cur = con.execute(
            "INSERT INTO briefs (date, title, content, requested_by, product_type, sources) "
            "VALUES (date('now'), ?, ?, 'general_montgomery', 'PERFORMANCE', ?)",
            (title, content, json.dumps(["intelligence.db"])),
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    db = _intelligence_db()

    if not Path(db).exists():
        print(f"ERROR: intelligence.db not found at {db}", file=sys.stderr)
        sys.exit(1)

    print("Computing agent performance metrics...")
    print(f"  Database: {db}")
    print()

    metrics = compute_all_metrics(db)

    # Generate reports
    text_report = _format_text_report(metrics)
    md_report = _format_markdown_report(metrics)
    headline = _generate_headline(metrics)

    # Print to stdout
    print(text_report)

    # Write JSON summary
    json_summary = json.dumps(metrics, indent=2, default=str)
    print("\n--- JSON Summary ---")
    print(json_summary)

    # Write PERFORMANCE brief to database
    title = "Monthly Agent Performance Review"
    brief_id = _write_performance_brief(db, title, md_report, json_summary)
    print(f"\nPerformance brief written to database (brief_id={brief_id})")

    # Push to Montgomery's channel
    pushed = push_briefing(
        "general_montgomery",
        title=title,
        summary=headline,
        body_md=md_report,
    )
    if pushed:
        print("Briefing pushed to WorldMonitor channel.")
    else:
        print("Channel push skipped (no API key or push failed).")


if __name__ == "__main__":
    main()

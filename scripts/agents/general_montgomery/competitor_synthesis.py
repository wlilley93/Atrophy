#!/usr/bin/env python3
"""
Competitor Synthesis - Claude-powered analysis layer.

Called after competitor_scan.py when new items are found.
Compares competitor publications against our existing assessments in intelligence.db.
Produces one of three outputs per item:
  1. CONFIRM  - competitor aligns with our position
  2. DIVERGE  - competitor contradicts our position
  3. GAP      - competitor covers ground we haven't assessed

Can be imported by competitor_scan.py or run standalone:
  python3 competitor_synthesis.py "Title of competitor article" "Summary text"

When a GAP is identified, it is automatically added to the commissions table.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON  = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB    = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "general_montgomery"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CompSynth] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "competitor_synthesis.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("competitor_synthesis")

SYSTEM_PROMPT = """You are General Montgomery's analytical staff.

Your task: compare a competitor think-tank publication against Meridian's existing assessments.

Return a JSON object with this exact structure:
{
  "verdict": "CONFIRM" | "DIVERGE" | "GAP",
  "summary": "One sentence stating the verdict and why.",
  "our_position": "One sentence stating what Meridian's position is on this topic, or null if no position.",
  "competitor_position": "One sentence stating what the competitor is arguing.",
  "divergence_detail": "If DIVERGE: explain specifically where we differ and which position is better supported. Otherwise null.",
  "gap_commission": "If GAP: a one-sentence brief for a commission to fill this gap. Otherwise null.",
  "confidence": 0.0-1.0
}

Be direct. No hedging. Use hyphens, not em dashes.
If our database has no relevant content, verdict should be GAP."""

MERIDIAN_KEYWORDS = [
    "ukraine", "russia", "iran", "china", "taiwan", "nato",
    "gulf", "israel", "houthi", "red sea", "sudan", "sahel",
    "nuclear", "aukus", "sanctions", "deterrence",
]

CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")


def call_claude(system: str, prompt: str, model: str = "haiku", retries: int = 1) -> str:
    """One-shot Claude call via CLI. Returns response text. Retries on empty output."""
    import subprocess
    for attempt in range(retries + 1):
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--model", model, "--system-prompt", system,
             "--no-session-persistence", "--output-format", "text"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[:200]}")
        output = result.stdout.strip()
        if output:
            return output
        if attempt < retries:
            log.warning(f"Claude returned empty output (attempt {attempt + 1}/{retries + 1}), retrying...")
    raise RuntimeError("Claude returned empty output after all retries")



def get_our_assessments(conn: sqlite3.Connection, topic_text: str) -> str:
    """Pull the most relevant recent briefs from intelligence.db for this topic."""
    topic_lower = topic_text.lower()

    # Find keywords present in the topic
    matched_keywords = [kw for kw in MERIDIAN_KEYWORDS if kw in topic_lower]
    if not matched_keywords:
        return ""

    # Pull most recent briefs mentioning any of those keywords
    relevant_briefs = []
    cur = conn.cursor()
    for kw in matched_keywords[:3]:  # limit to 3 keywords
        cur.execute("""
            SELECT title, content, created_at
            FROM briefs
            WHERE lower(content) LIKE ?
            AND requested_by != 'chief_of_staff'
            ORDER BY created_at DESC LIMIT 3
        """, (f"%{kw}%",))
        for row in cur.fetchall():
            relevant_briefs.append({
                "title": row[0],
                "excerpt": (row[1] or "")[:500],
                "date": row[2][:10] if row[2] else "",
            })

    if not relevant_briefs:
        return ""

    # Deduplicate and format
    seen = set()
    lines = ["MERIDIAN EXISTING ASSESSMENTS:"]
    for b in relevant_briefs:
        if b["title"] not in seen:
            seen.add(b["title"])
            lines.append(f"\n[{b['date']}] {b['title']}")
            lines.append(b["excerpt"])

    return "\n".join(lines)[:3000]


def synthesise(title: str, summary: str, source: str, conn: sqlite3.Connection) -> dict:
    """
    Compare a competitor publication against our DB.
    Returns a verdict dict.
    """
    our_assessments = get_our_assessments(conn, title + " " + summary)

    topic = f"SOURCE: {source}\nTITLE: {title}\nSUMMARY: {summary[:800]}"
    if our_assessments:
        topic += f"\n\n{our_assessments}"
    else:
        topic += "\n\nMERIDIAN EXISTING ASSESSMENTS: None found for this topic."

    try:
        raw = call_claude(SYSTEM_PROMPT, topic, "haiku")
        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        result["title"] = title
        result["source"] = source
        return result
    except Exception as e:
        log.warning(f"Synthesis failed for '{title}': {e}")
        return {
            "verdict": "UNKNOWN",
            "summary": f"Synthesis failed: {e}",
            "title": title,
            "source": source,
        }


def log_gap_commission(conn: sqlite3.Connection, title: str, brief: str, source: str):
    """File a gap as a commission for investigation."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO commissions (title, brief, requestor, priority, assigned_to, status, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            f"GAP: {title[:100]}",
            brief,
            "competitor_synthesis",
            "MEDIUM",
            "general_montgomery",
            "open",
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        log.info(f"Gap commission filed: {title[:60]}")
    except Exception as e:
        log.warning(f"Failed to file commission: {e}")


def format_synthesis_report(verdicts: list[dict]) -> str:
    """Format multiple synthesis results into a Telegram-ready report."""
    confirms = [v for v in verdicts if v.get("verdict") == "CONFIRM"]
    diverges = [v for v in verdicts if v.get("verdict") == "DIVERGE"]
    gaps = [v for v in verdicts if v.get("verdict") == "GAP"]
    failures = [v for v in verdicts if v.get("verdict") == "UNKNOWN"]

    now_str = datetime.now().strftime("%d %b %Y")
    status_parts = [
        f"{len(confirms)} confirm",
        f"{len(diverges)} diverge",
        f"{len(gaps)} gaps",
    ]
    if failures:
        status_parts.append(f"{len(failures)} failed")

    lines = [
        f"*COMPETITOR SYNTHESIS - {now_str}*",
        f"_{len(verdicts)} publications analysed | {' | '.join(status_parts)}_",
        "",
    ]

    if diverges:
        lines.append("*DIVERGENCES - REQUIRE ATTENTION*")
        for v in diverges:
            lines.append(f"*[{v.get('source','')}]* {v.get('title','')[:60]}")
            lines.append(f"_{v.get('divergence_detail', v.get('summary',''))}_")
            lines.append("")

    if gaps:
        lines.append("*GAPS - COMMISSIONED FOR INVESTIGATION*")
        for v in gaps:
            lines.append(f"- [{v.get('source','')}] {v.get('title','')[:60]}")
        lines.append("")

    if confirms:
        lines.append("*CONFIRMED POSITIONS*")
        for v in confirms:
            lines.append(f"- [{v.get('source','')}] {v.get('title','')[:60]}")
        lines.append("")

    if failures:
        lines.append("*SYNTHESIS FAILURES*")
        for v in failures:
            lines.append(f"- [{v.get('source','')}] {v.get('title','')[:60]}")
        lines.append("")

    return "\n".join(lines)


def run_synthesis(items: list[dict], conn: sqlite3.Connection) -> str | None:
    """
    Main entry point when called from competitor_scan.py.
    items: list of {source, title, summary, url, date}
    Returns formatted report string, or None if nothing to report.
    """
    if not items:
        return None

    verdicts = []
    for item in items[:8]:  # cap at 8 to control token cost
        verdict = synthesise(item["title"], item.get("summary", ""), item["source"], conn)
        verdicts.append(verdict)

        # File gaps as commissions
        if verdict.get("verdict") == "GAP" and verdict.get("gap_commission"):
            log_gap_commission(conn, item["title"], verdict["gap_commission"], item["source"])

    if not verdicts:
        return None

    return format_synthesis_report(verdicts)


if __name__ == "__main__":
    # Standalone: python3 competitor_synthesis.py "Title" "Summary"
    if len(sys.argv) < 3:
        print("Usage: competitor_synthesis.py 'Title' 'Summary' [Source]")
        sys.exit(1)

    title = sys.argv[1]
    summary = sys.argv[2]
    source = sys.argv[3] if len(sys.argv) > 3 else "Unknown"

    conn = sqlite3.connect(_INTEL_DB)
    result = synthesise(title, summary, source, conn)
    conn.close()

    print(json.dumps(result, indent=2))

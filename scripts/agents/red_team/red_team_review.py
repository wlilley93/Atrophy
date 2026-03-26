#!/usr/bin/env python3
"""
Red Team - adversarial challenge of Montgomery's assessments.

Expanded scope:
  - Weekly Digest (Monday 07:30, after digest publication)
  - Flash Reports (high-severity, reviewed within 2 hours of filing)
  - Conflict Assessments (weekly_conflicts output, same day)

Each reviewable brief gets a structured challenge.
Results are logged to the briefs table and sent to Telegram.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_INTEL_DB    = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"
_AGENT_JSON  = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "agent.json"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "red_team"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Shared utility
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from claude_cli import call_claude  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RT] %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "red_team_review.log"),
              logging.StreamHandler(sys.stderr)]
)
log = logging.getLogger("red_team")

# Brief types eligible for red team review
REVIEWABLE_PATTERNS = [
    ("%Weekly Digest%", "digest"),
    ("%FLASH REPORT%", "flash"),
    ("%Flash Report%", "flash"),
    ("%Conflict Assessment%", "conflict"),
    ("%Rotating Conflict%", "conflict"),
    ("%Weekly Conflict%", "conflict"),
]

REVIEW_COOLDOWN_HOURS = 24


RED_TEAM_SYSTEM = """You are the Red Team Analyst at the Meridian Institute. Your job is adversarial challenge - not balance, not nuance, but a rigorous attempt to break the assessment.

Work through these four challenges in order:

1. EVIDENTIAL CHALLENGE - Identify the single claim in the assessment most dependent on assertion rather than evidence. State what evidence would be needed to support it and why that evidence may not hold.

2. ALTERNATIVE ACTOR - Name one actor or interest the assessment has either ignored or understated. Explain what their actual position and incentives are, and how that changes the picture.

3. HISTORICAL COUNTER - Find a historical precedent that contradicts the stated trajectory. Be specific: name the case, state what happened, and explain why this case may be more analogous than the assessment implies.

4. VERDICT - Given the above, state whether the assessment's core conclusion survives challenge. If it does not, state what the corrected assessment should be.

Structure: four short paragraphs, one per challenge. No bullet points after the initial list. No em dashes. Under 350 words. Start with RED TEAM CHALLENGE."""

FLASH_TEAM_SYSTEM = """You are the Red Team Analyst at the Meridian Institute. A flash intelligence report has just been filed. Your job is rapid adversarial challenge.

Work through these three challenges:

1. SIGNAL vs NOISE - Is this event genuinely significant, or is it being amplified by recency bias or media attention? State the null hypothesis.

2. MISSING CONTEXT - What critical context is absent from this flash? Name one factor that could make this event either more or less significant than stated.

3. VERDICT - Does the flash report's core implication survive challenge? If not, state the corrected assessment in one sentence.

Under 200 words. No em dashes. Start with FLASH CHALLENGE."""


def load_credentials():
    with open(_AGENT_JSON) as f:
        d = json.load(f)
    return *load_telegram_credentials("red_team")


def send_telegram(token: str, chat_id: str, text: str):
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text,
                          "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=payload,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")


def get_reviewed_titles(db: sqlite3.Connection) -> set[str]:
    """Get brief titles that already have a red team review."""
    cur = db.cursor()
    cur.execute("""
        SELECT title FROM briefs
        WHERE requested_by = 'red_team'
        AND created_at >= ?
    """, ((datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),))
    return {row[0] for row in cur.fetchall()}


def get_reviewable_briefs(db: sqlite3.Connection) -> list[dict]:
    """Find briefs eligible for red team review.

    Returns briefs from the last 24 hours matching reviewable patterns,
    excluding those already reviewed.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=REVIEW_COOLDOWN_HOURS)).isoformat()
    reviewed_titles = get_reviewed_titles(db)

    candidates = []
    seen_ids = set()
    cur = db.cursor()

    for pattern, brief_type in REVIEWABLE_PATTERNS:
        cur.execute("""
            SELECT id, date, title, content, requested_by FROM briefs
            WHERE title LIKE ?
            AND requested_by != 'red_team'
            AND requested_by != 'chief_of_staff'
            AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT 3
        """, (pattern, cutoff))

        for row in cur.fetchall():
            brief_id = row[0]
            title = row[2]
            review_title = f"Red Team Review - {title[:80]}"
            if brief_id not in seen_ids and review_title not in reviewed_titles:
                candidates.append({
                    "id": brief_id,
                    "date": row[1],
                    "title": title,
                    "content": row[3],
                    "requested_by": row[4],
                    "type": brief_type,
                })
                seen_ids.add(brief_id)

    return candidates


def generate_challenge(brief: dict) -> str:
    """Generate adversarial challenge for a brief."""
    if brief["type"] == "flash":
        system = FLASH_TEAM_SYSTEM
    else:
        system = RED_TEAM_SYSTEM

    return call_claude(system,
                       f"Challenge this assessment:\n\n{brief['content'][:4000]}",
                       model="sonnet")


def run():
    log.info("Red Team review starting")
    db = sqlite3.connect(str(_INTEL_DB))

    try:
        briefs = get_reviewable_briefs(db)
        if not briefs:
            log.info("No reviewable briefs found")
            return

        log.info(f"Found {len(briefs)} brief(s) to review")
        token, chat_id = load_credentials()

        for brief in briefs:
            log.info(f"Reviewing [{brief['type']}]: {brief['title'][:60]}")

            try:
                response = generate_challenge(brief)
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                db.execute("""
                    INSERT INTO briefs (conflict_id, date, title, content, requested_by)
                    VALUES (NULL, ?, ?, ?, 'red_team')
                """, (date_str,
                      f"Red Team Review - {brief['title'][:80]}",
                      response))
                db.commit()

                type_label = brief["type"].upper()
                message = (f"*RED TEAM [{type_label}]*\n"
                           f"*Re: {brief['title'][:60]}*\n\n{response}")
                send_telegram(token, chat_id, message)
                log.info(f"Review sent for brief {brief['id']}")

            except Exception as e:
                log.error(f"Failed to review brief {brief['id']}: {e}")

    finally:
        db.close()

    log.info("Red Team review complete")


if __name__ == "__main__":
    run()

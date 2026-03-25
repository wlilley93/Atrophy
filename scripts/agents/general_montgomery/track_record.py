#!/usr/bin/env python3
"""
Track Record - Assessment outcome logging and accuracy review.

Two functions:
  1. EXTRACT - scans recent briefs for prediction statements and logs them
     to assessment_outcomes with PENDING status. Runs weekly after digest.

  2. REVIEW - scans PENDING outcomes older than the prediction window and
     asks Claude to assess whether each prediction proved correct.
     Runs monthly alongside the process audit.

Usage:
  python3 track_record.py extract    # log new predictions
  python3 track_record.py review     # assess expired predictions
  python3 track_record.py report     # print accuracy summary to Telegram
"""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON  = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB    = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "general_montgomery"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TrackRecord] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "track_record.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("track_record")

REVIEW_WINDOW_DAYS = 30  # predictions older than this are reviewed
CLAUDE_BIN = "/Users/williamlilley/.local/bin/claude"


def call_claude(system: str, prompt: str, model: str = "haiku") -> str:
    """One-shot Claude call via CLI. Returns response text."""
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
    return result.stdout.strip()

EXTRACT_SYSTEM = """You are reviewing an intelligence brief to extract falsifiable predictions.

A falsifiable prediction is a specific claim about a future state of affairs that can be verified correct or incorrect.
Include both explicit predictions (future tense) AND implied ones from trajectory/assessment language:
  - "Default trajectory is fragmented state" -> "Sudan will fragment into de facto partition"
  - "Neither side can deliver decisive conclusion" -> "The conflict will remain stalemated for at least 6 months"
  - "RSF has momentum and financial independence" -> "RSF will retain control of Darfur for the next 12 months"

Extract up to 5 predictions. For each provide:
  - prediction: the claim in future tense (one sentence)
  - confidence: 0.0-1.0
  - timeframe_days: days until verifiable (estimate)

Return JSON array only. If genuinely no assessable claims, return [].
Use hyphens not em dashes."""

REVIEW_SYSTEM = """You are reviewing an intelligence prediction against current world events.

Your task: assess whether the prediction has proved CORRECT, INCORRECT, PARTIAL, or is still PENDING.

CORRECT - the predicted event occurred as described
INCORRECT - the predicted event clearly did not occur
PARTIAL - the predicted event occurred but not fully as described
PENDING - insufficient time has passed or evidence is unclear

Return JSON:
{
  "outcome": "CORRECT" | "INCORRECT" | "PARTIAL" | "PENDING",
  "notes": "One sentence explanation of the outcome.",
  "confidence": 0.0-1.0
}

Be direct. No hedging."""


def load_cfg():
    with open(_AGENT_JSON) as f:
        return json.load(f)


def send_telegram(token: str, chat_id: str, text: str):
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def extract_predictions_from_brief(brief_content: str, brief_id: int,
                                    predicted_by: str, predicted_at: str) -> list[dict]:
    """Use Claude to extract falsifiable predictions from a brief."""
    try:
        raw = call_claude(EXTRACT_SYSTEM, brief_content[:3000], "haiku")
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        predictions = json.loads(raw)
        if not isinstance(predictions, list):
            return []
        return [
            {
                "brief_id": brief_id,
                "prediction": p.get("prediction", ""),
                "predicted_by": predicted_by,
                "predicted_at": predicted_at,
                "confidence": p.get("confidence", 0.5),
                "timeframe_days": p.get("timeframe_days", 30),
            }
            for p in predictions if p.get("prediction")
        ]
    except Exception as e:
        log.debug(f"Prediction extraction failed: {e}")
        return []


def review_prediction(prediction: str, prediction_date: str) -> dict:
    """Ask Claude to assess whether a prediction proved correct."""
    try:
        prompt = (
            f"Prediction made on {prediction_date[:10]}:\n"
            f'"{prediction}"\n\n'
            f"Today is {datetime.now().strftime('%Y-%m-%d')}. "
            f"Based on world events, assess the outcome."
        )
        raw = call_claude(REVIEW_SYSTEM, prompt, "haiku")
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        log.debug(f"Prediction review failed: {e}")
        return {"outcome": "PENDING", "notes": f"Review failed: {e}", "confidence": 0}


def cmd_extract(conn: sqlite3.Connection):
    """Scan recent briefs and extract predictions."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    cur = conn.cursor()

    # Get briefs not yet processed
    cur.execute("""
        SELECT b.id, b.requested_by, b.content, b.created_at
        FROM briefs b
        WHERE b.created_at >= ?
        AND b.requested_by NOT IN ('chief_of_staff', 'librarian')
        AND b.id NOT IN (SELECT DISTINCT brief_id FROM assessment_outcomes WHERE brief_id IS NOT NULL)
        ORDER BY b.created_at DESC
        LIMIT 20
    """, (cutoff,))
    briefs = cur.fetchall()
    log.info(f"Scanning {len(briefs)} new briefs for predictions")

    total_extracted = 0
    for brief_id, agent, content, created_at in briefs:
        if not content:
            continue
        predictions = extract_predictions_from_brief(content, brief_id, agent, created_at)
        for p in predictions:
            cur.execute("""
                INSERT INTO assessment_outcomes
                    (brief_id, prediction, predicted_by, predicted_at, outcome, confidence_at_prediction)
                VALUES (?, ?, ?, ?, 'PENDING', ?)
            """, (p["brief_id"], p["prediction"], p["predicted_by"],
                  p["predicted_at"], p["confidence"]))
            total_extracted += 1
        if predictions:
            log.info(f"Extracted {len(predictions)} predictions from brief {brief_id}")

    conn.commit()
    log.info(f"Total predictions logged: {total_extracted}")
    return total_extracted


def cmd_review(conn: sqlite3.Connection):
    """Review pending predictions that have passed their window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=REVIEW_WINDOW_DAYS)).isoformat()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, prediction, predicted_by, predicted_at
        FROM assessment_outcomes
        WHERE outcome = 'PENDING'
        AND predicted_at <= ?
        LIMIT 20
    """, (cutoff,))
    pending = cur.fetchall()
    log.info(f"{len(pending)} predictions pending review")

    updated = 0
    for outcome_id, prediction, predicted_by, predicted_at in pending:
        result = review_prediction(prediction, predicted_at)
        cur.execute("""
            UPDATE assessment_outcomes
            SET outcome = ?, outcome_notes = ?, reviewed_at = ?, reviewed_by = 'track_record'
            WHERE id = ?
        """, (result["outcome"], result.get("notes", ""), datetime.now(timezone.utc).isoformat(), outcome_id))
        updated += 1
        log.info(f"Reviewed [{result['outcome']}]: {prediction[:60]}")

    conn.commit()
    log.info(f"Reviewed {updated} predictions")
    return updated


def cmd_report(conn: sqlite3.Connection, cfg: dict):
    """Generate accuracy report and send to Telegram."""
    cur = conn.cursor()
    cur.execute("""
        SELECT outcome, COUNT(*) FROM assessment_outcomes
        WHERE outcome != 'PENDING'
        GROUP BY outcome
    """)
    counts = dict(cur.fetchall())

    cur.execute("""
        SELECT predicted_by, outcome, COUNT(*) FROM assessment_outcomes
        WHERE outcome != 'PENDING'
        GROUP BY predicted_by, outcome
        ORDER BY predicted_by, outcome
    """)
    by_agent = cur.fetchall()

    total = sum(counts.values())
    correct = counts.get("CORRECT", 0) + counts.get("PARTIAL", 0) * 0.5
    accuracy = (correct / total * 100) if total else 0

    now_str = datetime.now().strftime("%d %b %Y")
    lines = [
        f"*TRACK RECORD - {now_str}*",
        f"_Prediction accuracy since inception_",
        "",
        f"*Overall: {accuracy:.0f}%* ({total} predictions reviewed)",
        f"Correct: {counts.get('CORRECT',0)} | Partial: {counts.get('PARTIAL',0)} | "
        f"Incorrect: {counts.get('INCORRECT',0)}",
        "",
        "*By agent:*",
    ]

    current_agent = None
    for agent, outcome, count in by_agent:
        if agent != current_agent:
            lines.append(f"  _{agent}_")
            current_agent = agent
        lines.append(f"    {outcome}: {count}")

    cur.execute("""
        SELECT COUNT(*) FROM assessment_outcomes WHERE outcome = 'PENDING'
    """)
    pending = cur.fetchone()[0]
    lines.append(f"\n_Pending review: {pending} predictions_")

    report = "\n".join(lines)
    send_telegram(cfg["telegram_bot_token"], cfg["telegram_chat_id"], report)
    log.info("Track record report sent")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "extract"
    conn = sqlite3.connect(_INTEL_DB)
    cfg = load_cfg()

    if mode == "extract":
        n = cmd_extract(conn)
        log.info(f"Extraction complete: {n} predictions logged")
    elif mode == "review":
        n = cmd_review(conn)
        log.info(f"Review complete: {n} outcomes recorded")
    elif mode == "report":
        cmd_report(conn, cfg)
    else:
        print(f"Unknown mode: {mode}. Use extract|review|report")

    conn.close()


if __name__ == "__main__":
    main()

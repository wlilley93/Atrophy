#!/usr/bin/env python3
"""Pre-compaction observer — periodic fact extraction from recent conversation.

Runs every 15 minutes via launchd. Scans recent turns for durable facts
worth preserving between compaction events. Complements the memory flush
by catching things that matter before they scroll out of context.

Most runs are no-ops (no new turns). When there is material, uses Haiku
with low effort for fast, cheap extraction.

Schedule: every 900 seconds (StartInterval)
"""
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from config import DB_PATH, AGENT_DIR, AGENT_DISPLAY_NAME
from core.memory import _connect, write_observation
from core.inference import run_inference_oneshot


# ── State tracking ──

STATE_FILE = AGENT_DIR / "state" / ".observer_state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, Exception):
            pass
    return {"last_turn_id": 0}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── System prompt ──

_OBSERVER_SYSTEM = """\
You are extracting durable facts from a conversation transcript.
Not everything is worth preserving — only extract things that would be
useful to remember in a future session.

Output format (one per line):
OBSERVATION: <fact> [confidence: X.X]

If there is nothing worth extracting, respond with: NOTHING_NEW"""


# ── Get recent turns ──

def _get_recent_turns(since_id: int) -> list[dict]:
    """Get turns newer than since_id and within the last 15 minutes."""
    cutoff = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    rows = conn.execute(
        "SELECT id, role, content, timestamp FROM turns "
        "WHERE id > ? AND timestamp > ? "
        "ORDER BY timestamp",
        (since_id, cutoff),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Parse observations ──

def _parse_observations(response: str) -> list[dict]:
    """Parse OBSERVATION: <fact> [confidence: X.X] lines."""
    observations = []
    for line in response.split("\n"):
        line = line.strip()
        if not line.startswith("OBSERVATION:"):
            continue
        content = line[len("OBSERVATION:"):].strip()
        # Extract confidence
        conf_match = re.search(r'\[confidence:\s*([\d.]+)\]', content)
        confidence = float(conf_match.group(1)) if conf_match else 0.5
        # Remove confidence tag from content
        statement = re.sub(r'\s*\[confidence:\s*[\d.]+\]', '', content).strip()
        if statement:
            observations.append({"statement": statement, "confidence": confidence})
    return observations


# ── Main ──

def observe():
    state = _load_state()
    last_id = state.get("last_turn_id", 0)

    # Get recent turns since last run
    turns = _get_recent_turns(last_id)

    if not turns:
        # Fast path — nothing new
        return

    print(f"[observer] {len(turns)} new turn(s) since ID {last_id}")

    # Build transcript
    transcript_lines = []
    for t in turns:
        role = "Will" if t["role"] == "will" else AGENT_DISPLAY_NAME
        content = t["content"]
        if len(content) > 500:
            content = content[:500] + "..."
        transcript_lines.append(f"[{role}] {content}")

    transcript = "\n".join(transcript_lines)

    prompt = (
        "Extract any durable facts from this recent conversation excerpt.\n\n"
        + transcript
    )

    try:
        response = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=_OBSERVER_SYSTEM,
            model="claude-haiku-4-5-20251001",
            effort="low",
        )
    except Exception as e:
        print(f"[observer] Inference failed: {e}")
        return

    if not response or not response.strip():
        print("[observer] Empty response.")
        return

    # Update state to highest turn ID we processed
    max_id = max(t["id"] for t in turns)
    state["last_turn_id"] = max_id
    _save_state(state)

    # Check for nothing new
    if "NOTHING_NEW" in response.strip():
        print("[observer] Nothing worth extracting.")
        return

    # Parse and store observations
    observations = _parse_observations(response)
    if not observations:
        print("[observer] No observations parsed.")
        return

    for obs in observations:
        content = f"[observer] {obs['statement']}"
        write_observation(content, confidence=obs['confidence'])

    print(f"[observer] Stored {len(observations)} observation(s)")


if __name__ == "__main__":
    observe()

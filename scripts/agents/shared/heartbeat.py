#!/usr/bin/env python3
"""Heartbeat daemon - periodic check-in evaluation.

Runs via launchd every 30 minutes. Gathers context about active threads,
time since last interaction, and recent session activity. Asks the companion
to evaluate whether to reach out unprompted using the HEARTBEAT.md checklist.

If the companion decides to reach out, fires a macOS notification and queues
the message for next app launch.

Schedule: every 30 minutes (StartInterval)
"""
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path (4 levels up from scripts/agents/shared/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(Path.home() / ".atrophy" / ".env")

from config import (
    DB_PATH, MESSAGE_QUEUE, HEARTBEAT_PATH,
    HEARTBEAT_ACTIVE_START, HEARTBEAT_ACTIVE_END,
)
from core.queue import queue_message
from core.memory import (
    _connect, get_active_threads, get_recent_summaries,
    get_recent_observations, get_last_interaction_time,
    log_heartbeat,
)
from core.inference import (
    stream_inference, TextDelta, ToolUse, StreamDone, StreamError,
)
from core.context import load_system_prompt
from core.status import is_away, is_mac_idle
from core.notify import send_notification


def _in_active_hours() -> bool:
    hour = datetime.now().hour
    return HEARTBEAT_ACTIVE_START <= hour < HEARTBEAT_ACTIVE_END


def _load_checklist() -> str:
    if HEARTBEAT_PATH.exists():
        return HEARTBEAT_PATH.read_text()
    return ""


def _gather_context() -> str:
    parts = []

    # Time since last interaction
    last_time = get_last_interaction_time()
    if last_time:
        parts.append(f"## Last interaction\n{last_time}")
    else:
        parts.append("## Last interaction\nNo previous interactions found.")

    # Recent turn count (last session)
    conn = _connect()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM turns t "
        "JOIN sessions s ON t.session_id = s.id "
        "WHERE s.id = (SELECT MAX(id) FROM sessions)"
    ).fetchone()
    if row:
        parts.append(f"## Recent session turn count\n{row['cnt']} turns")
    conn.close()

    # Active threads
    threads = get_active_threads()
    if threads:
        lines = [f"- {t['name']}: {t.get('summary', '...')}" for t in threads[:5]]
        parts.append(f"## Active threads\n" + "\n".join(lines))

    # Recent session summaries
    summaries = get_recent_summaries(n=3)
    if summaries:
        lines = [f"- {s.get('created_at', '?')}: {s.get('content', 'No summary')[:200]}" for s in summaries]
        parts.append(f"## Recent sessions\n" + "\n".join(lines))

    # Recent observations
    observations = get_recent_observations(n=5)
    if observations:
        lines = [f"- {o['content']}" for o in observations]
        parts.append(f"## Recent observations\n" + "\n".join(lines))

    return "\n\n".join(parts)


_HEARTBEAT_PROMPT = (
    "[HEARTBEAT CHECK - internal evaluation, not a conversation]\n\n"
    "You are deciding whether to reach out to the user unprompted. "
    "You have access to your full conversation history and memory tools.\n\n"
    "First, review your state - use recall, daily_digest, or your memory tools "
    "if you need to refresh context.\n\n"
    "Then evaluate using the checklist below and assign a severity score "
    "from 0 to 100:\n"
    "  0-24  = nothing worth reporting, stay silent\n"
    "  25-74 = worth sending, normal priority\n"
    "  75-100 = critical, needs immediate attention\n\n"
    "Respond with exactly this format on the FIRST LINE:\n"
    "[SEVERITY:XX] where XX is your 0-100 score\n\n"
    "Then on the next line, one of:\n"
    "[REACH_OUT] followed by the message you'd send him. Be specific. "
    "Reference the actual thing. Don't say \'just checking in.\'\n\n"
    "[HEARTBEAT_OK] followed by a brief reason why now isn't the right time.\n\n"
    "[SUPPRESS] followed by a brief reason if you actively shouldn't reach out "
    "(e.g. he's away, it's too soon, he needs space).\n\n"
    "Keep it short. 1-3 sentences for the message, one line for OK/SUPPRESS."
)


def _run_heartbeat_inference(prompt: str, cli_session_id: str | None) -> str:
    """Run heartbeat via stream_inference with session resume + MCP tools."""
    system = load_system_prompt()
    full_text = ""
    tools_used = []

    for event in stream_inference(prompt, system, cli_session_id):
        if isinstance(event, TextDelta):
            pass  # collect via StreamDone
        elif isinstance(event, ToolUse):
            tools_used.append(event.name)
            print(f"  [heartbeat: tool → {event.name}]")
        elif isinstance(event, StreamDone):
            full_text = event.full_text
        elif isinstance(event, StreamError):
            raise RuntimeError(event.message)

    if tools_used:
        print(f"  [heartbeat: used tools: {', '.join(tools_used)}]")
    return full_text


def heartbeat():
    # Gate: active hours
    if not _in_active_hours():
        print(f"[heartbeat] Outside active hours ({HEARTBEAT_ACTIVE_START}-{HEARTBEAT_ACTIVE_END}). Skipping.")
        return

    # Gate: user status
    if is_away():
        print("[heartbeat] User is away. Skipping.")
        log_heartbeat("SUPPRESS", "User is away")
        return

    checklist = _load_checklist()
    if not checklist:
        print("[heartbeat] No HEARTBEAT.md found. Skipping.")
        return

    context = _gather_context()


    prompt = f"{_HEARTBEAT_PROMPT}\n\n---\n\n{checklist}\n\n---\n\n## Current Context\n\n{context}"

    # Always cold - heartbeat must not resume the active companion session
    print("[heartbeat] Running evaluation (cold)...")
    try:
        response = _run_heartbeat_inference(prompt, None)
    except Exception as e:
        print(f"[heartbeat] Inference failed: {e}")
        log_heartbeat("ERROR", str(e))
        return

    if not response or not response.strip():
        print("[heartbeat] Empty response. Skipping.")
        log_heartbeat("ERROR", "Empty response")
        return

    print(f"[heartbeat] Response: {response[:120]}...")

    # Parse severity score and decision
    import re as _re
    response_stripped = response.strip()

    # Extract severity score from first line
    severity = 50  # default if not found
    severity_match = _re.match(r"\[SEVERITY:(\d+)\]", response_stripped)
    if severity_match:
        severity = min(100, max(0, int(severity_match.group(1))))
        # Remove severity line for further parsing
        response_stripped = response_stripped[severity_match.end():].strip()

    print(f"[heartbeat] Severity: {severity}/100")

    # Gate: below 25 = suppress regardless of decision
    if severity < 25:
        reason = response_stripped[:200] if response_stripped else "Below threshold"
        log_heartbeat("SUPPRESS", f"severity={severity}: {reason}")
        print(f"[heartbeat] Below threshold ({severity}). Suppressed.")
        return

    is_critical = severity >= 75

    if response_stripped.startswith("[REACH_OUT]"):
        message = response_stripped[len("[REACH_OUT]"):].strip()
        if is_critical:
            message = f"[CRITICAL] {message}"
        log_heartbeat("REACH_OUT", f"severity={severity}", message)

        # Always send via Telegram - heartbeat messages are time-sensitive
        try:
            from channels.telegram import send_message as send_telegram
            send_telegram(message)
            print(f"[heartbeat] Sent via Telegram (severity={severity})")
        except Exception as e:
            print(f"[heartbeat] Telegram send failed: {e}")

        # Local notification + queue only if user is at the Mac
        if not is_mac_idle():
            from config import AGENT_DISPLAY_NAME
            send_notification(
                title=AGENT_DISPLAY_NAME,
                body=message[:200],
            )
        queue_message(MESSAGE_QUEUE, message, source="heartbeat")
        print(f"[heartbeat] Reaching out: {message[:80]}...")

    elif response_stripped.startswith("[HEARTBEAT_OK]"):
        reason = response_stripped[len("[HEARTBEAT_OK]"):].strip()
        log_heartbeat("HEARTBEAT_OK", f"severity={severity}: {reason}")
        print(f"[heartbeat] OK ({severity}): {reason[:80]}")

    elif response_stripped.startswith("[SUPPRESS]"):
        reason = response_stripped[len("[SUPPRESS]"):].strip()
        log_heartbeat("SUPPRESS", f"severity={severity}: {reason}")
        print(f"[heartbeat] Suppressed ({severity}): {reason[:80]}")

    else:
        # Unexpected format - log it but don't act
        log_heartbeat("UNKNOWN", response_stripped[:500])
        print(f"[heartbeat] Unexpected format: {response_stripped[:80]}")


if __name__ == "__main__":
    heartbeat()

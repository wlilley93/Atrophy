# scripts/agents/shared/heartbeat.py - Heartbeat Check-In

**Line count:** ~273 lines  
**Dependencies:** `json`, `sys`, `datetime`, `pathlib`, `dotenv`, `config`, `core.*`  
**Purpose:** Periodic check-in evaluation - decides whether to reach out unprompted

## Overview

Runs via launchd every 30 minutes. Gathers context about active threads, time since last interaction, and recent session activity. Asks the companion to evaluate whether to reach out unprompted using the HEARTBEAT.md checklist.

If the companion decides to reach out, fires a macOS notification and queues the message for next app launch.

**Schedule:** Every 30 minutes (StartInterval)

## Constants

```python
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
```

**Purpose:** Project root path (4 levels up from scripts/agents/shared/).

## Helper Functions

### _in_active_hours

```python
def _in_active_hours() -> bool:
    hour = datetime.now().hour
    return HEARTBEAT_ACTIVE_START <= hour < HEARTBEAT_ACTIVE_END
```

**Purpose:** Check if current time is within active hours.

### _load_checklist

```python
def _load_checklist() -> str:
    if HEARTBEAT_PATH.exists():
        return HEARTBEAT_PATH.read_text()
    return ""
```

**Purpose:** Load heartbeat checklist from HEARTBEAT.md.

### _gather_context

```python
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

    # Inner life v2 - needs and drives
    try:
        from core.inner_life import load_state
        state = load_state()
        if "needs" in state:
            needs = state["needs"]
            low = [f"{k}={v:.0f}" for k, v in needs.items() if v < 3]
            if low:
                parts.append(f"## Unmet Needs (LOW)\n" + ", ".join(low))

            # Simple drive computation
            if "personality" in state:
                p = state["personality"]
                drives = []
                if needs.get("stimulation", 5) < 3:
                    drives.append("seeking-new-topics")
                if needs.get("purpose", 5) < 4 and p.get("initiative", 0.5) > 0.6:
                    drives.append("offering-to-help")
                if needs.get("social", 5) < 4 and p.get("warmth_default", 0.5) > 0.5:
                    drives.append("reaching-out-unprompted")
                if needs.get("novelty", 5) < 3:
                    drives.append("seeking-variety")
                if needs.get("rest", 5) < 3:
                    drives.append("conserving-energy")
                if drives:
                    parts.append(f"## Active Drives\n" + ", ".join(drives))
    except Exception:
        pass  # v1 state or inner_life not available

    return "\n\n".join(parts)
```

**Purpose:** Gather context for heartbeat evaluation.

**Sections:**
1. Last interaction time
2. Recent session turn count
3. Active threads (top 5)
4. Recent sessions (last 3)
5. Recent observations (last 5)
6. Unmet needs (value < 3)
7. Active drives (computed from needs + personality)

## Heartbeat Prompt

```python
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
    "[REACH_OUT] followed by the message you'd send. Be specific.\n\n"
    "[HEARTBEAT_OK] followed by a brief reason why now isn't the right time.\n\n"
    "[SUPPRESS] followed by a brief reason if you actively shouldn't reach out."
)
```

**Purpose:** Guide heartbeat evaluation.

**Response format:**
- First line: `[SEVERITY:XX]` (0-100 score)
- Second line: `[REACH_OUT]`, `[HEARTBEAT_OK]`, or `[SUPPRESS]`

## Inference Function

### _run_heartbeat_inference

```python
def _run_heartbeat_inference(prompt: str, cli_session_id: str | None) -> str:
    """Run heartbeat via stream_inference with session resume + MCP tools."""
    system = load_system_prompt()
    # Uses stream_inference with MCP tools for full evaluation
    pass
```

**Purpose:** Run heartbeat evaluation via inference.

## Main Function

### run_heartbeat

```python
def run_heartbeat():
    # Check active hours
    if not _in_active_hours():
        print("[heartbeat] Outside active hours. Skipping.")
        return

    # Check if user is away
    if is_away():
        print("[heartbeat] User is away. Skipping.")
        return

    # Check if Mac is idle
    if is_mac_idle(3600):  # 1 hour
        print("[heartbeat] Mac idle for >1 hour. Skipping.")
        return

    # Gather context
    context = _gather_context()
    if not context.strip():
        print("[heartbeat] No context. Skipping.")
        return

    # Load checklist
    checklist = _load_checklist()

    # Run inference
    prompt = f"{_HEARTBEAT_PROMPT}\n\n{context}\n\n{checklist}"
    response = _run_heartbeat_inference(prompt, cli_session_id=None)

    # Parse response
    severity_match = re.search(r'\[SEVERITY:(\d+)\]', response)
    severity = int(severity_match.group(1)) if severity_match else 0

    # Decide action
    if severity < 25:
        print(f"[heartbeat] Severity {severity}: staying silent")
        log_heartbeat("skip", f"Severity {severity} below threshold")
        return

    # Extract message
    reach_match = re.search(r'\[REACH_OUT\]\s*(.+)', response, re.DOTALL)
    if not reach_match:
        print(f"[heartbeat] No REACH_OUT in response")
        log_heartbeat("skip", "No reach out message")
        return

    message = reach_match.group(1).strip()

    # Queue message
    queue_message(message, source="heartbeat")

    # Send notification
    send_notification("Heartbeat", message)

    # Log
    log_heartbeat("send", message[:100])
    print(f"[heartbeat] Queued: {message[:50]}...")
```

**Flow:**
1. Check active hours
2. Check if user is away
3. Check if Mac is idle (>1 hour)
4. Gather context
5. Load checklist
6. Run inference
7. Parse severity score
8. If severity >= 25, extract message
9. Queue message for next app launch
10. Send macOS notification
11. Log heartbeat result

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/prompts/heartbeat.md` | Heartbeat checklist |
| `~/.atrophy/agents/<name>/data/.message_queue.json` | Queued messages |
| `~/.atrophy/agents/<name>/data/.heartbeat_log.json` | Heartbeat log |

## Exported API

| Function | Purpose |
|----------|---------|
| `run_heartbeat()` | Run heartbeat evaluation |
| `_in_active_hours()` | Check active hours |
| `_load_checklist()` | Load heartbeat checklist |
| `_gather_context()` | Gather evaluation context |
| `_run_heartbeat_inference()` | Run inference |

## See Also

- `src/main/jobs/heartbeat.ts` - TypeScript heartbeat job
- `scripts/cron.py` - Cron job management
- `core/inner_life.py` - Needs and drives computation

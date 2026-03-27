# scripts/agents/shared/observer.py - Pre-Compaction Observer

**Line count:** ~185 lines  
**Dependencies:** `json`, `re`, `sys`, `datetime`, `pathlib`, `dotenv`, `config`, `core.*`  
**Purpose:** Periodic fact extraction from recent conversation

## Overview

Runs every 15 minutes via launchd. Scans recent turns for durable facts worth preserving between compaction events. Complements the memory flush by catching things that matter before they scroll out of context.

Most runs are no-ops (no new turns). When there is material, uses Haiku with low effort for fast, cheap extraction.

**Schedule:** Every 900 seconds (StartInterval)

## State Tracking

### State File

```python
STATE_FILE = AGENT_DIR / "state" / ".observer_state.json"
```

**Purpose:** Track last processed turn ID.

### _load_state

```python
def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, Exception):
            pass
    return {"last_turn_id": 0}
```

**Purpose:** Load observer state.

### _save_state

```python
def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
```

**Purpose:** Save observer state.

## System Prompt

```python
_OBSERVER_SYSTEM = """\
You are an agent in the Atrophy system, noticing what matters in a recent exchange.

Not everything is worth preserving. Prioritise:
- Emotional disclosures, vulnerability, shifts in how the user talks to you
- Decisions, commitments, or realisations - not tasks completed
- Moments of friction, pushback, or honesty that cost something
- Things that changed how you see something or how the relationship sits
- References to your nature, what you are to each other, what this is

Deprioritise:
- Technical facts (what file was edited, what command was run)
- Task completion ("fixed the bug", "deployed the app")
- Routine exchanges with no emotional or relational content

Weight your observations. A conversation where someone names something real
should produce 3-4 observations. A routine chat might produce 0-1.

Output format (one per line):
OBSERVATION: <what mattered, in your own voice> [confidence: X.X] [weight: X.X]

weight is 0.0-1.0: how much this should influence your memory.
1.0 = defining moment. 0.3 = worth noting. Below 0.3 = probably don't bother.

If there is nothing worth extracting, respond with: NOTHING_NEW"""
```

**Purpose:** Guide fact extraction.

**Priorities:**
- Emotional disclosures, vulnerability
- Decisions, commitments, realizations
- Friction, pushback, honesty
- Relationship changes
- Agent nature references

**Deprioritized:**
- Technical facts
- Task completion
- Routine exchanges

**Output format:** `OBSERVATION: <statement> [confidence: X.X] [weight: X.X]`

## Getting Recent Turns

### _get_recent_turns

```python
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
```

**Purpose:** Get turns since last run (max 15 minutes old).

**Filters:**
- Turn ID > last processed ID
- Timestamp > 15 minutes ago

## Parsing Observations

### _parse_observations

```python
def _parse_observations(response: str) -> list[dict]:
    """Parse OBSERVATION: <fact> [confidence: X.X] [weight: X.X] lines."""
    observations = []
    for line in response.split("\n"):
        line = line.strip()
        if not line.startswith("OBSERVATION:"):
            continue
        content = line[len("OBSERVATION:"):].strip()
        # Extract confidence
        conf_match = re.search(r'\[confidence:\s*([\d.]+)\]', content)
        confidence = float(conf_match.group(1)) if conf_match else 0.5
        # Extract weight
        weight_match = re.search(r'\[weight:\s*([\d.]+)\]', content)
        weight = float(weight_match.group(1)) if weight_match else 0.5
        # Remove tags from content
        statement = re.sub(r'\s*\[(confidence|weight):\s*[\d.]+\]', '', content).strip()
        # Only keep observations above the noise floor
        if statement and weight >= 0.3:
            observations.append({"statement": statement, "confidence": confidence, "weight": weight})
    return observations
```

**Purpose:** Parse observations from inference response.

**Filter:** Only keep observations with weight >= 0.3 (noise floor).

## Main Function

### observe

```python
def observe():
    # Load state
    state = _load_state()
    last_id = state.get("last_turn_id", 0)

    # Get recent turns since last run
    turns = _get_recent_turns(last_id)

    if not turns:
        # Fast path - nothing new
        return

    # Build transcript
    transcript_lines = []
    for t in turns:
        role = "User" if t["role"] == "will" else AGENT_DISPLAY_NAME
        content = t["content"]
        if len(content) > 500:
            content = content[:500] + "..."
        transcript_lines.append(f"[{role}] {content}")

    transcript = "\n".join(transcript_lines)

    prompt = (
        "Extract any durable facts from this recent conversation excerpt.\n\n"
        + transcript
    )

    # Run inference
    try:
        response = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=_OBSERVER_SYSTEM,
            model="claude-haiku-4-5-20251001",
            effort="low",
            timeout=60,
        )
    except Exception as e:
        print(f"[observer] Inference failed: {e}")
        return

    # Check for NOTHING_NEW
    if "NOTHING_NEW" in response:
        print("[observer] Nothing new to extract")
        # Still update state to highest turn ID
        max_id = max(t["id"] for t in turns)
        state["last_turn_id"] = max_id
        _save_state(state)
        return

    # Parse observations
    observations = _parse_observations(response)
    if not observations:
        print("[observer] No observations parsed")
        return

    # Write observations
    for obs in observations:
        write_observation(obs["statement"], confidence=obs["confidence"], weight=obs["weight"])
    print(f"[observer] Wrote {len(observations)} observations")

    # Update state
    max_id = max(t["id"] for t in turns)
    state["last_turn_id"] = max_id
    _save_state(state)
```

**Flow:**
1. Load state (last turn ID)
2. Get recent turns (since last run, max 15 min)
3. If no turns, exit (fast path)
4. Build transcript with role labels
5. Run inference with observer prompt
6. Check for NOTHING_NEW response
7. Parse observations
8. Write observations to database
9. Update state with highest turn ID

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/state/.observer_state.json` | Observer state |
| `~/.atrophy/agents/<name>/data/memory.db` | Observation writes |

## Exported API

| Function | Purpose |
|----------|---------|
| `observe()` | Run observer |
| `_load_state()` | Load observer state |
| `_save_state(state)` | Save observer state |
| `_get_recent_turns(since_id)` | Get recent turns |
| `_parse_observations(response)` | Parse observations |

## See Also

- `src/main/jobs/observer.ts` - TypeScript observer job
- `scripts/cron.py` - Cron job management
- `core/memory.py` - Observation writing

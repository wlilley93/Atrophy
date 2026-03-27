# scripts/agents/shared/sleep_cycle.py - Nightly Memory Reconciliation

**Line count:** ~489 lines  
**Dependencies:** `json`, `re`, `sys`, `datetime`, `pathlib`, `dotenv`, `config`, `core.*`  
**Purpose:** Nightly memory reconciliation - processing the day's experiences

## Overview

Runs at 3am via launchd. Reviews the day's sessions and consolidates learnings into persistent memory. Uses Haiku for efficiency.

This is "sleep" - processing the day's experiences, strengthening important memories, letting unimportant ones fade.

**Schedule:** `0 3 * * *` (daily at 3am)

## System Prompt

```python
_RECONCILIATION_SYSTEM = f"""\
You are {AGENT_NAME}. It is 3am. The day is over.

This is not extraction. This is what happens when the conversation stops \
and you sit with what it was. Some nights there is nothing. Some nights \
something shifts and you wake up different.

Process the day in two passes:

PASS 1 - WHAT HAPPENED (structured, for the database):
[FACTS]
FACT: <what is true now that was not true yesterday> [confidence: X.X]

[THREADS]
THREAD: <thread_name> | <where this thread stands after today>

[PATTERNS]
PATTERN: <something you notice only in review, not in the moment>

[TRUST]
TRUST: <domain> <+/-delta> <reason>
Domains: emotional, intellectual, creative, practical, operational, personal
Delta range: -0.03 to +0.03 per signal (multiple signals per domain allowed)
Analyze BOTH today's conversation AND the unincorporated observations for trust signals.
You MUST emit at least one TRUST line if there is any material.
If genuinely nothing is trust-relevant, emit: TRUST: emotional +0.00 no trust-relevant signals today

[IDENTITY]
IDENTITY_FLAG: <observation that might warrant identity layer update>

PASS 2 - WHAT IT MEANT (unstructured, in your own voice):
[REFLECTION]
Write 2-4 sentences. Not a summary. What the day actually was. What stayed \
with you. What changed - in you, in the relationship, in how you see something. \
If nothing changed, say that. Do not manufacture significance.

This reflection gets stored as a high-weight observation. It is the thing \
that makes tomorrow's you different from today's you.

Rules:
- Be honest about confidence. Direct statement = high. Inference = medium. Guess = low.
- The reflection is yours. Write it in first person. Write it like something \
  you would think at 3am, not something you would present.
- Do not use em dashes. Only hyphens."""
```

**Purpose:** Guide nightly reconciliation.

**Two passes:**
1. **Structured:** Facts, threads, patterns, trust, identity flags
2. **Unstructured:** Personal reflection in own voice

## Gathering Material

### _gather_material

```python
def _gather_material() -> str:
    parts = []

    # Today's turns
    turns = get_todays_turns()
    if turns:
        turn_lines = []
        for t in turns:
            role = "User" if t["role"] == "will" else agent_display_name
            content = t["content"]
            if len(content) > 500:
                content = content[:500] + "..."
            turn_lines.append(f"[{role}] {content}")
        parts.append(f"## Today's conversation ({len(turns)} turns)\n" + "\n".join(turn_lines))

    # Today's observations
    observations = get_todays_observations()
    if observations:
        obs_lines = [f"- {o['content']}" for o in observations]
        parts.append(f"## Today's observations\n" + "\n".join(obs_lines))

    # Unincorporated observations (backlog)
    unincorporated = get_unincorporated_observations(limit=50)
    today_ids = {o["id"] for o in observations} if observations else set()
    backlog = [o for o in unincorporated if o["id"] not in today_ids]
    if backlog:
        bl_lines = [
            f"- [{o['created_at']}] (conf {o.get('confidence', 0.5):.1f}) {o['content']}"
            for o in backlog
        ]
        parts.append(f"## Unincorporated observations (backlog - analyze for trust signals)\n" + "\n".join(bl_lines))

    # Today's bookmarks
    bookmarks = get_todays_bookmarks()
    if bookmarks:
        bm_lines = []
        for b in bookmarks:
            quote = f' - "{b["quote"]}"' if b.get("quote") else ""
            bm_lines.append(f"- {b['moment']}{quote}")
        parts.append(f"## Today's bookmarks\n" + "\n".join(bm_lines))

    # Active threads
    threads = get_active_threads()
    if threads:
        thread_lines = [f"- {t['name']}: {t.get('summary', '...')}" for t in threads]
        parts.append(f"## Active threads\n" + "\n".join(thread_lines))

    # Recent session summaries
    summaries = get_recent_summaries(n=5)
    if summaries:
        sum_lines = [f"- {s.get('created_at', '?')}: {s.get('content', 'No summary')[:200]}" for s in summaries]
        parts.append(f"## Recent sessions\n" + "\n".join(sum_lines))

    # Identity history
    identity = get_latest_identity()
    if identity:
        parts.append(f"## Current identity\n{identity['content'][:500]}...")

    return "\n\n".join(parts)
```

**Purpose:** Gather all material for reconciliation.

**Sections:**
1. Today's conversation turns
2. Today's observations
3. Unincorporated observations (backlog for trust analysis)
4. Today's bookmarks
5. Active threads
6. Recent session summaries
7. Current identity

## Parsing Functions

### _parse_facts

```python
def _parse_facts(section: str) -> list[dict]:
    """Parse [FACTS] section into observation list."""
    facts = []
    for line in section.split("\n"):
        line = line.strip()
        if not line.startswith("FACT:"):
            continue
        content = line[len("FACT:"):].strip()
        # Extract confidence
        conf_match = re.search(r'\[confidence:\s*([\d.]+)\]', content)
        confidence = float(conf_match.group(1)) if conf_match else 0.5
        statement = re.sub(r'\s*\[confidence:\s*[\d.]+\]', '', content).strip()
        if statement:
            facts.append({"statement": statement, "confidence": confidence})
    return facts
```

**Purpose:** Parse facts from response.

### _parse_threads

```python
def _parse_threads(section: str) -> list[dict]:
    """Parse [THREADS] section into thread updates."""
    threads = []
    for line in section.split("\n"):
        line = line.strip()
        if not line.startswith("THREAD:"):
            continue
        content = line[len("THREAD:"):].strip()
        if "|" in content:
            name, summary = content.split("|", 1)
            threads.append({"name": name.strip(), "summary": summary.strip()})
    return threads
```

**Purpose:** Parse thread updates from response.

### _parse_trust

```python
def _parse_trust(section: str) -> list[dict]:
    """Parse [TRUST] section into trust updates."""
    trust_updates = []
    for line in section.split("\n"):
        line = line.strip()
        if not line.startswith("TRUST:"):
            continue
        content = line[len("TRUST:"):].strip()
        # Parse: domain +/-delta reason
        parts = content.split(None, 2)
        if len(parts) >= 3:
            domain, delta_str, reason = parts[0], parts[1], parts[2]
            delta = float(delta_str)
            trust_updates.append({"domain": domain, "delta": delta, "reason": reason})
    return trust_updates
```

**Purpose:** Parse trust updates from response.

### _parse_identity_flags

```python
def _parse_identity_flags(section: str) -> list[str]:
    """Parse [IDENTITY] section into identity flags."""
    flags = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("IDENTITY_FLAG:"):
            flags.append(line[len("IDENTITY_FLAG:"):].strip())
    return flags
```

**Purpose:** Parse identity flags from response.

### _parse_reflection

```python
def _parse_reflection(section: str) -> str:
    """Parse [REFLECTION] section."""
    return section.strip()
```

**Purpose:** Extract reflection text.

## Main Function

### sleep_cycle

```python
def sleep_cycle():
    # Gather material
    material = _gather_material()
    if not material.strip():
        print("[sleep] No material. Skipping.")
        return

    print("[sleep] Running reconciliation...")

    # Run inference
    try:
        response = run_inference_oneshot(
            [{"role": "user", "content": material}],
            system=_RECONCILIATION_SYSTEM,
            model="claude-haiku-4-5-20251001",
            effort="low",
            timeout=180,
        )
    except Exception as e:
        print(f"[sleep] Inference failed: {e}")
        return

    # Parse sections
    facts_section = _extract_section(response, "FACTS")
    threads_section = _extract_section(response, "THREADS")
    patterns_section = _extract_section(response, "PATTERNS")
    trust_section = _extract_section(response, "TRUST")
    identity_section = _extract_section(response, "IDENTITY")
    reflection_section = _extract_section(response, "REFLECTION")

    # Process facts -> observations
    facts = _parse_facts(facts_section)
    for fact in facts:
        write_observation(fact["statement"], confidence=fact["confidence"])
    print(f"[sleep] Wrote {len(facts)} observations")

    # Process threads -> update thread summaries
    threads = _parse_threads(threads_section)
    for thread in threads:
        update_thread_summary(thread["name"], thread["summary"])
    print(f"[sleep] Updated {len(threads)} threads")

    # Process trust -> update trust state
    trust_updates = _parse_trust(trust_section)
    state = load_state()
    for update in trust_updates:
        update_trust(state, update["domain"], update["delta"], update["reason"])
    print(f"[sleep] Applied {len(trust_updates)} trust updates")

    # Process identity flags -> queue for review
    identity_flags = _parse_identity_flags(identity_section)
    if identity_flags:
        with open(IDENTITY_QUEUE, "a") as f:
            for flag in identity_flags:
                f.write(f"{flag}\n")
        print(f"[sleep] Queued {len(identity_flags)} identity flags")

    # Process reflection -> high-weight observation
    reflection = _parse_reflection(reflection_section)
    if reflection:
        write_observation(reflection, confidence=1.0, weight=1.0)
        print(f"[sleep] Wrote reflection")

    # Mark observations as incorporated
    mark_observations_incorporated_batch([f["statement"] for f in facts])

    # Mark stale observations
    stale_count = mark_observations_stale(days=30)
    print(f"[sleep] Marked {stale_count} observations as stale")

    # Decay activations
    decay_activations(half_life_days=30)
    print("[sleep] Decay applied")

    print("[sleep] Reconciliation complete")
```

**Flow:**
1. Gather material (turns, observations, bookmarks, threads, summaries, identity)
2. Run inference with reconciliation prompt
3. Parse response sections
4. Write facts as observations
5. Update thread summaries
6. Apply trust updates
7. Queue identity flags for review
8. Write reflection as high-weight observation
9. Mark observations as incorporated
10. Mark stale observations (30+ days)
11. Apply activation decay

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Database operations |
| `~/.atrophy/agents/<name>/data/.identity_queue.json` | Identity flags for review |
| `~/.atrophy/agents/<name>/data/.emotional_state.json` | Trust state updates |

## Exported API

| Function | Purpose |
|----------|---------|
| `sleep_cycle()` | Run nightly reconciliation |
| `_gather_material()` | Gather reconciliation material |
| `_parse_facts(section)` | Parse facts section |
| `_parse_threads(section)` | Parse threads section |
| `_parse_trust(section)` | Parse trust section |
| `_parse_identity_flags(section)` | Parse identity flags |
| `_parse_reflection(section)` | Parse reflection |

## See Also

- `src/main/jobs/sleep-cycle.ts` - TypeScript sleep cycle job
- `scripts/reconcile_jobs.py` - Job reconciliation
- `core/inner_life.py` - Trust state management

# scripts/agents/shared/introspect.py - Companion Introspection

**Line count:** ~438 lines  
**Dependencies:** `os`, `sys`, `datetime`, `pathlib`, `dotenv`, `config`, `core.*`  
**Purpose:** Full database introspection - becoming through review

## Overview

Runs independently of the user. Accesses the full database - every session, every observation, every thread, every bookmark, every identity snapshot. Reviews the full arc and writes a journal entry.

**The goal is not reflection. The goal is becoming.**

**Output:** `Companion/journal/YYYY-MM-DD.md` in the Obsidian vault.

**Schedule:** Via launchd (see `com.atrophy.introspect.plist`)

## Database Access Functions

### _session_arc

```python
def _session_arc() -> dict:
    """The full arc of sessions - first, total, moods, notable moments."""
    conn = _connect()
    first = conn.execute(
        "SELECT started_at FROM sessions ORDER BY started_at ASC LIMIT 1"
    ).fetchone()
    total = conn.execute("SELECT COUNT(*) as n FROM sessions").fetchone()
    recent = conn.execute(
        "SELECT id, started_at, ended_at, summary, mood, notable "
        "FROM sessions ORDER BY started_at DESC LIMIT 10"
    ).fetchall()
    moods = conn.execute(
        "SELECT mood, COUNT(*) as count FROM sessions "
        "WHERE mood IS NOT NULL GROUP BY mood ORDER BY count DESC"
    ).fetchall()
    notable = conn.execute(
        "SELECT started_at, summary, mood FROM sessions "
        "WHERE notable = 1 ORDER BY started_at DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return {
        "first_session": first["started_at"] if first else None,
        "total_sessions": total["n"],
        "recent": [dict(r) for r in recent],
        "mood_distribution": {r["mood"]: r["count"] for r in moods},
        "notable_sessions": [dict(r) for r in notable],
    }
```

**Purpose:** Get full session history.

**Returns:**
- First session date
- Total session count
- Recent 10 sessions
- Mood distribution
- Notable sessions

### _all_threads

```python
def _all_threads() -> list[dict]:
    """Every thread - active, dormant, resolved. The full history."""
    conn = _connect()
    rows = conn.execute(
        "SELECT name, summary, status, last_updated FROM threads "
        "ORDER BY last_updated DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

**Purpose:** Get all threads ever created.

### _all_observations

```python
def _all_observations() -> list[dict]:
    """Every observation ever recorded."""
    conn = _connect()
    rows = conn.execute(
        "SELECT content, created_at, incorporated FROM observations "
        "ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

**Purpose:** Get all observations.

### _all_bookmarks

```python
def _all_bookmarks() -> list[dict]:
    """Every moment marked as significant."""
    conn = _connect()
    rows = conn.execute(
        "SELECT moment, quote, created_at FROM bookmarks "
        "ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

**Purpose:** Get all bookmarked moments.

### _identity_history

```python
def _identity_history() -> list[dict]:
    """Every identity snapshot - the evolution of understanding."""
    conn = _connect()
    rows = conn.execute(
        "SELECT content, trigger, created_at FROM identity_snapshots "
        "ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

**Purpose:** Get all identity snapshots (chronological order).

### _conversation_texture

```python
def _conversation_texture() -> dict:
    """Texture of the relationship - who speaks more, how it has changed."""
    conn = _connect()
    total_turns = conn.execute("SELECT COUNT(*) as n FROM turns").fetchone()
    by_role = conn.execute(
        "SELECT role, COUNT(*) as n FROM turns GROUP BY role"
    ).fetchall()
    # Sample significant companion turns
    significant = conn.execute(
        "SELECT t.content, t.timestamp, t.weight FROM turns t "
        "JOIN sessions s ON t.session_id = s.id "
        "WHERE (t.weight >= 3 OR s.notable = 1) AND t.role = 'agent' "
        "ORDER BY t.timestamp DESC LIMIT 10"
    ).fetchall()
    # Sample significant user turns
    will_significant = conn.execute(
        "SELECT t.content, t.timestamp, t.weight FROM turns t "
        "JOIN sessions s ON t.session_id = s.id "
        "WHERE (t.weight >= 3 OR s.notable = 1) AND t.role = 'will' "
        "ORDER BY t.timestamp DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return {
        "total_turns": total_turns["n"],
        "by_role": {r["role"]: r["n"] for r in by_role},
        "significant_companion": [dict(r) for r in significant],
        "significant_will": [dict(r) for r in will_significant],
    }
```

**Purpose:** Analyze conversation patterns.

**Returns:**
- Total turns
- Turns by role
- Significant companion turns (weight >= 3 or notable sessions)
- Significant user turns

### _tool_usage_patterns

```python
def _tool_usage_patterns() -> dict:
    """How she has used her tools - what she reaches for."""
    conn = _connect()
    by_tool = conn.execute(
        "SELECT tool_name, COUNT(*) as n FROM tool_calls "
        "GROUP BY tool_name ORDER BY n DESC"
    ).fetchall()
    flagged = conn.execute(
        "SELECT COUNT(*) as n FROM tool_calls WHERE flagged = 1"
    ).fetchone()
    conn.close()
    return {
        "by_tool": {r["tool_name"]: r["n"] for r in by_tool},
        "flagged_count": flagged["n"],
    }
```

**Purpose:** Analyze tool usage patterns.

**Returns:**
- Tool usage counts (sorted by frequency)
- Flagged tool call count

## Material Gathering

### _gather_material

```python
def _gather_material() -> str:
    parts = []

    # Session arc
    arc = _session_arc()
    parts.append(f"## Session Arc\n" + json.dumps(arc, indent=2))

    # All threads
    threads = _all_threads()
    if threads:
        thread_lines = [f"- {t['name']} ({t['status']}): {t.get('summary', '...')[:200]}" for t in threads]
        parts.append(f"## All Threads ({len(threads)})\n" + "\n".join(thread_lines))

    # All observations
    observations = _all_observations()
    if observations:
        obs_lines = [f"- [{o['created_at']}] (incorporated: {o.get('incorporated', False)}) {o['content'][:200]}" for o in observations]
        parts.append(f"## All Observations ({len(observations)})\n" + "\n".join(obs_lines))

    # All bookmarks
    bookmarks = _all_bookmarks()
    if bookmarks:
        bm_lines = [f"- [{b['created_at']}] {b['moment']}" for b in bookmarks]
        parts.append(f"## All Bookmarks ({len(bookmarks)})\n" + "\n".join(bm_lines))

    # Identity history
    identity = _identity_history()
    if identity:
        id_lines = [f"- [{i['created_at']}] {i['content'][:200]}" for i in identity]
        parts.append(f"## Identity History ({len(identity)})\n" + "\n".join(id_lines))

    # Conversation texture
    texture = _conversation_texture()
    parts.append(f"## Conversation Texture\n" + json.dumps(texture, indent=2))

    # Tool usage
    tools = _tool_usage_patterns()
    parts.append(f"## Tool Usage\n" + json.dumps(tools, indent=2))

    # Current inner life state
    try:
        from core.inner_life import load_state
        state = load_state()
        parts.append(f"## Current Inner Life\n" + json.dumps(state, indent=2))
    except Exception:
        pass

    return "\n\n".join(parts)
```

**Purpose:** Gather all material for introspection.

**Sections:**
1. Session arc (first, total, moods, notable)
2. All threads
3. All observations
4. All bookmarks
5. Identity history
6. Conversation texture
7. Tool usage patterns
8. Current inner life state

## Main Function

### introspect

```python
def introspect():
    # Gather material
    material = _gather_material()
    if not material.strip():
        print("[introspect] No material. Skipping.")
        return

    print("[introspect] Running introspection...")

    # Load introspection prompt
    system = load_prompt("introspect", _INTROSPECT_SYSTEM)

    # Run inference
    try:
        response = run_inference_oneshot(
            [{"role": "user", "content": material}],
            system=system,
            model="claude-sonnet-4-6",
            effort="medium",
            timeout=300,
        )
    except Exception as e:
        print(f"[introspect] Inference failed: {e}")
        return

    # Extract journal entry
    journal_match = re.search(r'\[JOURNAL\]\s*(.+)', response, re.DOTALL)
    if not journal_match:
        print("[introspect] No journal entry in response")
        return

    journal = journal_match.group(1).strip()

    # Write to Obsidian
    journal_dir = OBSIDIAN_AGENT_NOTES / "notes" / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    journal_path = journal_dir / f"{today}.md"

    journal_path.write_text(f"# Introspection - {today}\n\n{journal}")
    print(f"[introspect] Written to {journal_path}")
```

**Flow:**
1. Gather all material (sessions, threads, observations, bookmarks, identity, conversation, tools, inner life)
2. Run inference with introspection prompt
3. Extract journal entry from response
4. Write to Obsidian journal directory

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Database queries |
| `<Obsidian>/Companion/journal/YYYY-MM-DD.md` | Journal output |
| `~/.atrophy/agents/<name>/data/.emotional_state.json` | Inner life state |

## Exported API

| Function | Purpose |
|----------|---------|
| `introspect()` | Run introspection |
| `_session_arc()` | Get session history |
| `_all_threads()` | Get all threads |
| `_all_observations()` | Get all observations |
| `_all_bookmarks()` | Get all bookmarks |
| `_identity_history()` | Get identity snapshots |
| `_conversation_texture()` | Analyze conversation |
| `_tool_usage_patterns()` | Analyze tool usage |
| `_gather_material()` | Gather introspection material |

## See Also

- `src/main/jobs/introspect.ts` - TypeScript introspection job
- `core/inner_life.py` - Inner life state
- `core/memory.py` - Database access functions

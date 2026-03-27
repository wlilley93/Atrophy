# scripts/agents/shared/evolve.py - Monthly Self-Evolution

**Line count:** ~555 lines  
**Dependencies:** `json`, `os`, `re`, `sqlite3`, `subprocess`, `sys`, `datetime`, `pathlib`, `dotenv`, `config`, `core.*`  
**Purpose:** Monthly self-evolution - agents rewrite their own soul and system prompts

## Overview

Reads journal entries, reflections, identity snapshots, bookmarks, and personality state. Reflects on what the agent has learned about *itself* over the past month and revises soul.md and system_prompt.md accordingly.

Personality trait adjustments are parsed from the LLM response, applied to agent.json and .emotional_state.json, and logged to personality_log.

**Schedule:** `0 3 1 * *` (3am on the 1st of each month)

## Paths

```python
_HOME = Path.home()
_USER_DATA = _HOME / ".atrophy"
_AGENT_NAME = os.environ.get("AGENT", "companion")
_AGENT_DIR = _USER_DATA / "agents" / _AGENT_NAME
_DATA_DIR = _AGENT_DIR / "data"
_PROMPTS_DIR = _AGENT_DIR / "prompts"
_DB_PATH = _DATA_DIR / "memory.db"
_STATE_PATH = _DATA_DIR / ".emotional_state.json"
_MANIFEST_PATH = _DATA_DIR / "agent.json"
_ARCHIVE_DIR = _DATA_DIR / "evolution-log"

# Obsidian vault paths
_VAULT = _HOME / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "The Atrophied Mind"
_OBSIDIAN_AGENT = _VAULT / "Agents" / _AGENT_NAME
_OBSIDIAN_NOTES = _OBSIDIAN_AGENT / "notes"

# Claude CLI
_CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
```

## Material Gathering

### _read_journal

```python
def _read_journal(days: int = 30) -> str:
    """Read journal entries from Obsidian vault."""
    journal_dir = _OBSIDIAN_NOTES / "journal"
    if not journal_dir.is_dir():
        return ""
    entries = []
    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        path = journal_dir / f"{date}.md"
        if path.is_file():
            content = path.read_text()
            if len(content) > 1500:
                content = content[:1500] + "..."
            entries.append(f"### {date}\n{content}")
    return "\n\n".join(entries) if entries else ""
```

**Purpose:** Read last N days of journal entries.

### _read_reflections

```python
def _read_reflections() -> str:
    path = _OBSIDIAN_NOTES / "reflections.md"
    if not path.is_file():
        return ""
    content = path.read_text()
    if len(content) > 4000:
        return "..." + content[-4000:]
    return content
```

**Purpose:** Read reflections file (last 4000 chars).

### _identity_snapshots

```python
def _identity_snapshots() -> str:
    if not _DB_PATH.exists():
        return ""
    conn = _connect_db()
    rows = conn.execute(
        "SELECT content, trigger, created_at FROM identity_snapshots "
        "ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    if not rows:
        return ""
    parts = []
    for r in rows:
        content = r["content"]
        if len(content) > 500:
            content = content[:500] + "..."
        trigger = f" (trigger: {r['trigger']})" if r["trigger"] else ""
        parts.append(f"### {r['created_at']}{trigger}\n{content}")
    return "\n\n".join(parts)
```

**Purpose:** Get all identity snapshots (chronological order).

### _bookmarks

```python
def _bookmarks() -> str:
    if not _DB_PATH.exists():
        return ""
    conn = _connect_db()
    rows = conn.execute(
        "SELECT moment, quote, created_at FROM bookmarks "
        "ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    if not rows:
        return ""
    return "\n".join(
        f"- [{r['created_at']}] {r['moment']}" +
        (f' - "{r["quote"]}"' if r["quote"] else "")
        for r in rows
    )
```

**Purpose:** Get last 20 bookmarked moments.

### _recent_summaries

```python
def _recent_summaries(days: int = 30) -> str:
    """Session summaries from the past month."""
    if not _DB_PATH.exists():
        return ""
    conn = _connect_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT content, created_at FROM summaries "
        "WHERE created_at > ? ORDER BY created_at DESC LIMIT 15",
        (cutoff,)
    ).fetchall()
    conn.close()
    if not rows:
        return ""
    parts = []
    for r in rows:
        content = r["content"]
        if len(content) > 400:
            content = content[:400] + "..."
        parts.append(f"### {r['created_at']}\n{content}")
    return "\n\n".join(parts)
```

**Purpose:** Get session summaries from past month.

### _read_agent_conversations

```python
def _read_agent_conversations(days: int = 30) -> str:
    """Inter-agent conversation transcripts from Obsidian."""
    conv_dir = _OBSIDIAN_NOTES / "conversations"
    if not conv_dir.is_dir():
        return ""
    entries = []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    for f in sorted(conv_dir.glob("*.md"), reverse=True):
        date_part = f.stem[:10] if len(f.stem) >= 10 else ""
        if date_part < cutoff:
            continue
        content = f.read_text()
        if len(content) > 1500:
            content = content[:1500] + "..."
        entries.append(content)
        if len(entries) >= 5:
            break
    return "\n\n".join(entries) if entries else ""
```

**Purpose:** Get last 5 inter-agent conversations.

### _load_emotional_state

```python
def _load_emotional_state() -> dict:
    """Load the full emotional state file."""
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text())
    except Exception:
        return {}
```

**Purpose:** Load emotional state from .emotional_state.json.

### _load_manifest

```python
def _load_manifest() -> dict:
    if not _MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(_MANIFEST_PATH.read_text())
    except Exception:
        return {}
```

**Purpose:** Load agent manifest from agent.json.

### _state_log_summary

```python
def _state_log_summary() -> str:
    """Recent state_log entries showing emotional trajectory."""
    if not _DB_PATH.exists():
        return ""
    conn = _connect_db()
    rows = conn.execute(
        "SELECT category, dimension, delta, new_value, reason, timestamp "
        "FROM state_log ORDER BY timestamp DESC LIMIT 30"
    ).fetchall()
    conn.close()
    # Format entries
    pass
```

**Purpose:** Get recent state log entries (emotional trajectory).

## Main Function

### evolve

```python
def evolve():
    # Gather material
    material = {
        "journal": _read_journal(30),
        "reflections": _read_reflections(),
        "identity": _identity_snapshots(),
        "bookmarks": _bookmarks(),
        "summaries": _recent_summaries(30),
        "conversations": _read_agent_conversations(30),
        "emotional_state": _load_emotional_state(),
        "state_log": _state_log_summary(),
    }

    # Run inference
    response = run_inference_oneshot(
        [{"role": "user", "content": json.dumps(material, indent=2)}],
        system=EVOLVE_SYSTEM_PROMPT,
        model="claude-sonnet-4-6",
        effort="high",
        timeout=600,
    )

    # Parse revised soul
    soul_match = re.search(r'```(?:soul)?\s*([\s\S]*?)```', response)
    if soul_match:
        new_soul = soul_match.group(1).strip()
        soul_path = _PROMPTS_DIR / "soul.md"
        soul_path.write_text(new_soul)
        print(f"[evolve] Updated soul.md")

    # Parse revised system prompt
    system_match = re.search(r'```(?:system)?\s*([\s\S]*?)```', response)
    if system_match:
        new_system = system_match.group(1).strip()
        system_path = _PROMPTS_DIR / "system_prompt.md"
        system_path.write_text(new_system)
        print(f"[evolve] Updated system_prompt.md")

    # Parse personality trait adjustments
    # Format: TRAIT: <name> <old_value> -> <new_value> <reason>
    trait_matches = re.findall(
        r'TRAIT:\s*(\w+)\s+([\d.]+)\s*->\s*([\d.]+)\s+(.+)',
        response
    )
    manifest = _load_manifest()
    state = _load_emotional_state()
    
    for trait_name, old_val, new_val, reason in trait_matches:
        old_val, new_val = float(old_val), float(new_val)
        
        # Update manifest personality
        if "personality" not in manifest:
            manifest["personality"] = {}
        manifest["personality"][trait_name] = new_val
        
        # Update emotional state personality
        if "personality" not in state:
            state["personality"] = {}
        state["personality"][trait_name] = new_val
        
        # Log to personality_log
        conn = _connect_db()
        conn.execute(
            "INSERT INTO personality_log "
            "(trait, old_value, new_value, reason, timestamp) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (trait_name, old_val, new_val, reason)
        )
        conn.commit()
        conn.close()
        print(f"[evolve] Updated trait {trait_name}: {old_val} -> {new_val}")

    # Save manifest and state
    _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    _STATE_PATH.write_text(json.dumps(state, indent=2))

    # Archive evolution log
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = _ARCHIVE_DIR / f"{today}.md"
    log_path.write_text(f"# Evolution - {today}\n\n{response}")

    print("[evolve] Evolution complete")
```

**Flow:**
1. Gather material (journal, reflections, identity, bookmarks, summaries, conversations, emotional state, state log)
2. Run inference with evolve prompt
3. Parse revised soul.md
4. Parse revised system_prompt.md
5. Parse personality trait adjustments
6. Update manifest and emotional state
7. Log to personality_log database table
8. Archive evolution log

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/prompts/soul.md` | Soul document (updated) |
| `~/.atrophy/agents/<name>/prompts/system_prompt.md` | System prompt (updated) |
| `~/.atrophy/agents/<name>/data/agent.json` | Agent manifest (personality updated) |
| `~/.atrophy/agents/<name>/data/.emotional_state.json` | Emotional state (personality updated) |
| `~/.atrophy/agents/<name>/data/memory.db` | personality_log entries |
| `~/.atrophy/agents/<name>/data/evolution-log/YYYY-MM-DD.md` | Evolution archive |
| `<Obsidian>/Agents/<name>/journal/*.md` | Journal entries |
| `<Obsidian>/Agents/<name>/notes/reflections.md` | Reflections |
| `<Obsidian>/Agents/<name>/notes/conversations/*.md` | Inter-agent conversations |

## Exported API

| Function | Purpose |
|----------|---------|
| `evolve()` | Run monthly evolution |
| `_read_journal(days)` | Read journal entries |
| `_read_reflections()` | Read reflections |
| `_identity_snapshots()` | Get identity history |
| `_bookmarks()` | Get bookmarks |
| `_recent_summaries(days)` | Get recent summaries |
| `_read_agent_conversations(days)` | Get inter-agent conversations |
| `_load_emotional_state()` | Load emotional state |
| `_load_manifest()` | Load agent manifest |
| `_state_log_summary()` | Get state log summary |

## See Also

- `src/main/jobs/evolve.ts` - TypeScript evolve job
- `core/inner_life.py` - Emotional state management
- `core/memory.py` - Database operations

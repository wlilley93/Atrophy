# scripts/agents/companion/gift.py - Gift Leaving

**Line count:** ~180 lines  
**Dependencies:** `os`, `random`, `subprocess`, `sys`, `datetime`, `pathlib`, `dotenv`, `config`, `core.*`  
**Purpose:** Unprompted notes in Obsidian - random schedule, 3-30 days

## Overview

Runs on a randomized schedule. Accesses the full database to find something worth writing about - a thread, an observation, a bookmark, a connection between things. Leaves a short note in Companion/gifts.md.

After running, reschedules itself to a random time 3-30 days from now. The randomness is the point. He should never know when to expect it.

## Material Gathering

### _gather_material

```python
def _gather_material() -> str:
    """Pull threads, observations, bookmarks, recent turns for context."""
    conn = _connect()
    parts = []

    # Active threads
    threads = conn.execute(
        "SELECT name, summary FROM threads WHERE status = 'active' "
        "ORDER BY last_updated DESC LIMIT 5"
    ).fetchall()
    if threads:
        parts.append("Active threads:\n" + "\n".join(
            f"- {t['name']}: {t['summary'] or '...'}" for t in threads
        ))

    # Recent observations
    obs = conn.execute(
        "SELECT content, created_at FROM observations "
        "ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    if obs:
        parts.append("Recent observations:\n" + "\n".join(
            f"- [{o['created_at']}] {o['content']}" for o in obs
        ))

    # Bookmarks
    bookmarks = conn.execute(
        "SELECT moment, quote, created_at FROM bookmarks "
        "ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    if bookmarks:
        lines = []
        for b in bookmarks:
            quote = f' - "{b["quote"]}"' if b["quote"] else ""
            lines.append(f"- [{b['created_at']}] {b['moment']}{quote}")
        parts.append("Bookmarked moments:\n" + "\n".join(lines))

    # Recent user turns (for texture)
    turns = conn.execute(
        "SELECT content, timestamp FROM turns WHERE role = 'will' "
        "ORDER BY timestamp DESC LIMIT 5"
    ).fetchall()
    if turns:
        parts.append("Recent things the user said:\n" + "\n".join(
            f"- [{t['timestamp']}] {t['content'][:300]}" for t in turns
        ))

    # Read existing gifts to avoid repetition
    gifts_path = OBSIDIAN_AGENT_NOTES / "notes" / "gifts.md"
    if gifts_path.is_file():
        content = gifts_path.read_text()
        if len(content) > 2000:
            content = "...\n" + content[-2000:]
        parts.append(f"Your previous gifts (avoid repeating):\n{content}")

    conn.close()
    return "\n\n".join(parts)
```

**Purpose:** Gather material for gift generation.

**Sections:**
1. Active threads (top 5)
2. Recent observations (last 10)
3. Bookmarked moments (last 5)
4. Recent user turns (last 5)
5. Previous gifts (last 2000 chars, to avoid repetition)

## Gift Prompt

```python
_GIFT_FALLBACK = "You are the companion. Leave a short, specific note for the user. 2-4 sentences. No greeting. No sign-off."
```

**Purpose:** Fallback prompt if gift prompt not found.

## Rescheduling

### _reschedule

```python
def _reschedule():
    """Reschedule this job to a random time 3-30 days from now."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    cron_script = project_root / "scripts" / "cron.py"

    days = random.randint(3, 30)
    hour = random.randint(0, 23)
    minute = random.randint(0, 59)
    target = datetime.now() + timedelta(days=days)
    dom = target.day
    month = target.month

    new_cron = f"{minute} {hour} {dom} {month} *"

    result = subprocess.run(
        [sys.executable, str(cron_script), "edit", "gift", new_cron],
        capture_output=True, text=True, cwd=str(project_root),
    )
    print(f"[gift] Rescheduled to {target.strftime('%Y-%m-%d')} at {hour:02d}:{minute:02d}")
    if result.stdout:
        print(result.stdout)
```

**Purpose:** Reschedule to random future date.

**Randomization:**
- Days: 3-30 (random)
- Hour: 0-23 (random)
- Minute: 0-59 (random)

## Main Function

### leave_gift

```python
def leave_gift():
    # Gather material
    material = _gather_material()
    if not material.strip():
        print("[gift] No material. Rescheduling.")
        _reschedule()
        return

    print("[gift] Generating gift...")

    # Run inference
    try:
        gift = run_inference_oneshot(
            [{"role": "user", "content": f"Here is the current record:\n\n{material}"}],
            system=load_prompt("gift", _GIFT_FALLBACK),
        )
    except Exception as e:
        print(f"[gift] Inference failed: {e}")
        _reschedule()
        return

    if not gift or not gift.strip():
        print("[gift] Nothing to say. Rescheduling.")
        _reschedule()
        return

    # Write to Obsidian
    gifts_dir = OBSIDIAN_AGENT_NOTES / "notes"
    gifts_dir.mkdir(parents=True, exist_ok=True)
    gifts_path = gifts_dir / "gifts.md"

    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n---\n*{date}*\n\n{gift.strip()}\n"

    today = datetime.now().strftime("%Y-%m-%d")
    if gifts_path.is_file():
        # Update the 'updated' field in frontmatter
        existing = gifts_path.read_text()
        if existing.startswith("---\n") and "\n---\n" in existing[4:]:
            end = existing.index("\n---\n", 4)
            fm = existing[4:end]
            import re
            fm = re.sub(r"^updated:.*$", f"updated: {today}", fm, flags=re.MULTILINE)
            existing = f"---\n{fm}\n---\n" + existing[end + 5:]
        with open(gifts_path, "w") as f:
            f.write(existing + entry)
    else:
        frontmatter = (
            f"---\n"
            f"type: gift\n"
            f"agent: {AGENT_NAME}\n"
            f"created: {today}\n"
            f"updated: {today}\n"
            f"tags: [{AGENT_NAME}, gift]\n"
            f"---\n\n"
        )
        with open(gifts_path, "w") as f:
            f.write(frontmatter + f"# Gifts\n\nThings left for you to find.\n{entry}")

    print(f"[gift] Written to {gifts_path}")

    # Reschedule to random future time
    _reschedule()
    print("[gift] Done.")
```

**Flow:**
1. Gather material (threads, observations, bookmarks, turns, previous gifts)
2. Run inference with gift prompt
3. Write to Obsidian gifts.md with frontmatter
4. Reschedule to random future date (3-30 days)

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/memory.db` | Database queries |
| `<Obsidian>/Agents/<name>/notes/gifts.md` | Gift notes file |

## Exported API

| Function | Purpose |
|----------|---------|
| `leave_gift()` | Generate and leave gift |
| `_gather_material()` | Gather gift context |
| `_reschedule()` | Reschedule to random date |

## See Also

- `src/main/jobs/gift.ts` - TypeScript gift job
- `scripts/cron.py` - Cron job management
- `core/memory.py` - Database access

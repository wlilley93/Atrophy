# Companion Runtime Fixes - Making Sleep Cycle, Heartbeat, and Observer Actually Work

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three issues preventing companion's background systems from working - sleep cycle timeout, stuck user status, and observer noise - so that memory is continuous, heartbeat can reach out, and the observer doesn't spam Telegram overnight.

**Architecture:** The scripts (`sleep_cycle.py`, `heartbeat.py`, `observer.py`) are already written and complete. The problems are operational: a hardcoded 30s inference timeout kills sleep_cycle, user status is permanently "away" so heartbeat always suppresses, and the observer has no quiet-hours logic. All fixes are in existing files.

**Tech Stack:** Python 3.12, SQLite, Claude CLI (subprocess), launchd

---

## Context for the implementer

**Project root:** `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron`

**How cron jobs work:** The Atrophy Electron app's in-process cron scheduler (`src/main/channels/cron/`) reads `scripts/agents/companion/jobs.json` and spawns Python scripts at scheduled intervals. Output goes into the companion's conversation as turns. The app runs in the tray and is always on.

**How observer output appears in Telegram:** Every 15 minutes, observer runs, its output gets injected as a "will" turn in the companion's conversation, companion responds (an "agent" turn), and that response is visible in Telegram. During quiet hours this produces messages like "Clean. 5am. Will's been quiet for five hours."

**Key files:**
- `core/inference.py:636` - the 30s timeout on `proc.communicate()`
- `core/status.py` - user presence status (active/away)
- `scripts/agents/shared/observer.py` - periodic fact extraction
- `scripts/agents/shared/sleep_cycle.py` - nightly memory reconciliation
- `scripts/agents/shared/heartbeat.py` - proactive outreach evaluation
- `~/.atrophy/agents/companion/data/.user_status.json` - persisted status (currently stuck at "away" since March 17)

---

### Task 1: Fix sleep_cycle inference timeout

The sleep_cycle gathers a full day's conversation (potentially hundreds of turns + observations + bookmarks + threads + summaries) and sends it to Haiku. The 30s timeout in `run_inference_oneshot()` is too short for large prompts. Observer works fine because its prompts are tiny (last 15 min only).

**Files:**
- Modify: `core/inference.py:602-659`

- [ ] **Step 1: Add configurable timeout to run_inference_oneshot**

In `core/inference.py`, change the function signature and the `proc.communicate()` call:

```python
def run_inference_oneshot(messages: list[dict], system: str,
                         model: str = "claude-sonnet-4-6",
                         effort: str = "low",
                         timeout: int = 30) -> str:
```

And at line 636:
```python
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise RuntimeError(f"Oneshot inference timed out ({timeout}s)")
```

- [ ] **Step 2: Update sleep_cycle to use longer timeout**

In `scripts/agents/shared/sleep_cycle.py`, change the `run_inference_oneshot` call (around line 340):

```python
        response = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=_RECONCILIATION_SYSTEM,
            model="claude-haiku-4-5-20251001",
            effort="low",
            timeout=120,
        )
```

- [ ] **Step 3: Update introspect to use longer timeout too**

In `scripts/agents/shared/introspect.py` (and the companion copy), the introspect script sends even larger prompts. Change its `run_inference_oneshot` call:

```python
        reflection = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=load_prompt("introspection", _INTROSPECTION_FALLBACK),
            timeout=120,
        )
```

Note: introspect uses the default model (Sonnet), which is correct for journal writing. Don't change the model.

- [ ] **Step 4: Test sleep_cycle dry run**

```bash
cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron"
AGENT=companion /Users/williamlilley/.pyenv/versions/3.12.7/bin/python -c "
import sys; sys.path.insert(0, '.')
from scripts.agents.shared.sleep_cycle import _gather_material
material = _gather_material()
print(f'Material length: {len(material)} chars')
print(material[:500])
"
```

Expected: prints the gathered material without error. If it's very large (>10K chars), consider truncating old turns in `_gather_material()`.

- [ ] **Step 5: Commit**

```bash
git add core/inference.py scripts/agents/shared/sleep_cycle.py scripts/agents/shared/introspect.py scripts/agents/companion/introspect.py
git commit -m "fix: increase oneshot inference timeout for sleep_cycle and introspect"
```

---

### Task 2: Fix stuck user status so heartbeat can actually reach out

The user status file is stuck at `{"status":"away","reason":"idle","since":"2026-03-17"}`. Nothing calls `set_active()` because the Electron desktop app (which normally handles user input) isn't the primary interface - Will talks through Telegram via the cron/switchboard system.

The fix: the observer already runs every 15 minutes and checks for new turns. If it sees recent user turns, it should update the status to active.

**Files:**
- Modify: `scripts/agents/shared/observer.py`

- [ ] **Step 1: Import set_active into observer**

At the top of `observer.py`, add:

```python
from core.status import set_active
```

- [ ] **Step 2: Update status when user turns are detected**

In the `observe()` function, after getting turns (after line 106 `if not turns: return`), add a check for user turns:

```python
    # Update user status if there are recent user turns
    user_turns = [t for t in turns if t["role"] == "will" and not t["content"].startswith("[observer]")]
    if user_turns:
        set_active()
```

This filters out observer-injected turns (which have role "will" but content starting with `[observer]`). Only real user input triggers active status.

- [ ] **Step 3: Reset the stuck status file now**

```bash
echo '{"status":"active","reason":"","since":"2026-03-23T07:00:00"}' > ~/.atrophy/agents/companion/data/.user_status.json
```

- [ ] **Step 4: Commit**

```bash
git add scripts/agents/shared/observer.py
git commit -m "fix: observer updates user status to active when real user turns detected"
```

---

### Task 3: Add quiet-hours gating to observer

The observer fires every 15 minutes regardless of activity. During quiet hours (no new user turns), it observes its own previous outputs and creates circular observations like "Sleep cycle management remains an open problem" stored 5 times.

Two fixes: (a) skip entirely when no new user turns exist, (b) filter out observer-generated turns from the extraction input.

**Files:**
- Modify: `scripts/agents/shared/observer.py`

- [ ] **Step 1: Filter out observer/system turns from extraction**

In `_get_recent_turns()`, add a filter to exclude observer-injected content:

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
    # Filter out observer-injected turns and agent responses to observer
    filtered = []
    for r in [dict(r) for r in rows]:
        content = r["content"]
        if content.startswith("[observer]"):
            continue
        if r["role"] != "will" and _is_observer_response(content):
            continue
        filtered.append(r)
    return filtered


def _is_observer_response(content: str) -> bool:
    """Detect agent responses that are just acknowledging observer output."""
    # These are terse status lines like "Clean. 5am. Will's been quiet..."
    if len(content) < 200 and content.startswith("Clean"):
        return True
    return False
```

- [ ] **Step 2: Early exit when only observer noise exists**

The existing early exit at line 106 (`if not turns: return`) already handles no-turns. With the filtering above, it will now also handle "turns exist but they're all observer noise" - the filtered list will be empty and the function returns early.

But we still need to update the state's `last_turn_id` so we don't re-process the same turns next cycle. Update the observe() function:

```python
def observe():
    state = _load_state()
    last_id = state.get("last_turn_id", 0)

    # Get ALL recent turns (unfiltered) to advance the cursor
    cutoff = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    all_rows = conn.execute(
        "SELECT id, role, content, timestamp FROM turns "
        "WHERE id > ? AND timestamp > ? "
        "ORDER BY timestamp",
        (last_id, cutoff),
    ).fetchall()
    conn.close()
    all_turns = [dict(r) for r in all_rows]

    if not all_turns:
        return

    # Always advance cursor to highest ID seen
    max_id = max(t["id"] for t in all_turns)

    # Filter to meaningful turns only
    turns = [t for t in all_turns if not t["content"].startswith("[observer]") and not _is_observer_response(t["content"])]

    if not turns:
        # Only observer noise - advance cursor but skip extraction
        state["last_turn_id"] = max_id
        _save_state(state)
        print(f"[observer] {len(all_turns)} turn(s) since ID {last_id} - all observer noise, skipping")
        return

    print(f"[observer] {len(turns)} new turn(s) since ID {last_id}")
    # ... rest of function continues with 'turns' instead of calling _get_recent_turns
```

Note: This refactors observe() to inline the turn fetching since we need both filtered and unfiltered lists. Remove the `_get_recent_turns` function and the second call to it.

- [ ] **Step 3: Test the filtering**

```bash
cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron"
AGENT=companion /Users/williamlilley/.pyenv/versions/3.12.7/bin/python -c "
import sys; sys.path.insert(0, '.')
from core.memory import _connect
conn = _connect()
recent = conn.execute('SELECT id, role, substr(content, 1, 100) FROM turns ORDER BY id DESC LIMIT 10').fetchall()
for r in recent:
    print(dict(r))
conn.close()
"
```

Verify that recent turns include observer-injected content (starts with `[observer]`) and terse agent responses (starts with `Clean`). These should all be filtered out by the new logic.

- [ ] **Step 4: Commit**

```bash
git add scripts/agents/shared/observer.py
git commit -m "fix: observer filters out self-referential turns, skips when only noise"
```

---

### Task 4: Clean up stale observations

The observation store has accumulated duplicates and circular references from the observer's self-referencing behavior. Clean these out so sleep_cycle starts with a cleaner dataset.

**Files:**
- No file changes needed - this is a one-time DB cleanup

- [ ] **Step 1: Count the noise**

```bash
sqlite3 ~/.atrophy/agents/companion/data/memory.db "
SELECT COUNT(*) as total,
  SUM(CASE WHEN content LIKE '%[observer]%sleep cycle%' THEN 1 ELSE 0 END) as sleep_cycle_dupes,
  SUM(CASE WHEN content LIKE '%[observer]%morning brief%' THEN 1 ELSE 0 END) as morning_brief_dupes,
  SUM(CASE WHEN content LIKE '%[observer]%quiet%' THEN 1 ELSE 0 END) as quiet_dupes,
  SUM(CASE WHEN content LIKE '%Test observation%' THEN 1 ELSE 0 END) as test_dupes
FROM observations;"
```

- [ ] **Step 2: Remove circular/duplicate observations**

Keep the first occurrence of each meaningful fact, remove the rest:

```bash
sqlite3 ~/.atrophy/agents/companion/data/memory.db "
-- Remove test observations
DELETE FROM observations WHERE content LIKE '%Test observation%';

-- Remove circular observer noise about itself
DELETE FROM observations WHERE content LIKE '%[observer]%quiet%' AND incorporated = 0;
DELETE FROM observations WHERE content LIKE '%[observer]%morning brief%fires%' AND incorporated = 0;

-- Remove redundant 'sleep cycle is broken' (keep one)
DELETE FROM observations WHERE id NOT IN (
  SELECT MIN(id) FROM observations WHERE content LIKE '%[observer]%sleep cycle%'
) AND content LIKE '%[observer]%sleep cycle%' AND incorporated = 0;
"
```

- [ ] **Step 3: Verify cleanup**

```bash
sqlite3 ~/.atrophy/agents/companion/data/memory.db "SELECT COUNT(*) FROM observations;"
```

Compare with the pre-cleanup count. Should be noticeably smaller.

---

### Task 5: Fix sys.path in all shared scripts (hardening)

The shared scripts use `sys.path.insert(0, str(Path(__file__).parent.parent))` which adds `scripts/agents/` to the path. This works only because the cron runner sets cwd to the project root, and Python finds `config.py` there. If anyone runs these scripts from a different directory, they'll fail.

We already fixed this for `introspect.py`. Apply the same fix to all shared scripts.

**Files:**
- Modify: `scripts/agents/shared/observer.py`
- Modify: `scripts/agents/shared/sleep_cycle.py`
- Modify: `scripts/agents/shared/heartbeat.py`
- Modify: `scripts/agents/shared/morning_brief.py`
- Modify: `scripts/agents/shared/evolve.py`
- Modify: `scripts/agents/shared/check_reminders.py`

- [ ] **Step 1: Fix path in each script**

In every script in `scripts/agents/shared/`, replace:

```python
sys.path.insert(0, str(Path(__file__).parent.parent))
```

With:

```python
# Add project root to path (shared/<script>.py -> agents -> scripts -> project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
```

And replace:

```python
load_dotenv(Path(__file__).parent.parent / ".env")
```

With:

```python
load_dotenv(Path.home() / ".atrophy" / ".env")
```

Do the same for any companion-specific scripts in `scripts/agents/companion/` that have the old pattern.

- [ ] **Step 2: Test each script imports**

```bash
cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron"
for script in scripts/agents/shared/*.py; do
  echo "--- $script ---"
  AGENT=companion /Users/williamlilley/.pyenv/versions/3.12.7/bin/python -c "
import sys, importlib.util
spec = importlib.util.spec_from_file_location('mod', '$script')
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
" 2>&1 | head -3
done
```

- [ ] **Step 3: Commit**

```bash
git add scripts/agents/shared/ scripts/agents/companion/
git commit -m "fix: use absolute project root in sys.path for all agent scripts"
```

---

## Verification

After all tasks are complete:

1. **Sleep cycle** - wait for 3am or trigger manually:
   ```bash
   cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron"
   AGENT=companion /Users/williamlilley/.pyenv/versions/3.12.7/bin/python scripts/agents/shared/sleep_cycle.py
   ```
   Should complete without timeout. Check `~/.atrophy/logs/` and the companion DB for new observations tagged `[sleep-cycle]`.

2. **Heartbeat** - check that user status updates and heartbeat evaluates properly:
   ```bash
   cat ~/.atrophy/agents/companion/data/.user_status.json
   ```
   After Will sends a message, status should flip to "active". Next heartbeat during active hours should evaluate (not just SUPPRESS).

3. **Observer** - after the next 15-minute cycle, check that:
   - No `[observer]` turns appear in the extraction input
   - Quiet periods produce "skipping" log messages, not new observations
   - Companion doesn't respond to observer noise in Telegram

---

## What this does NOT cover (future work)

- **Voice notes** - ElevenLabs is wired up but the Telegram audio send mechanism and `voice_note.py` script logic need building. Separate plan.
- **Morning brief** - `morning_brief.py` exists but may have the same timeout issue. The timeout fix in Task 1 applies globally so it should benefit.
- **Observation deduplication at write time** - currently observations are checked for exact duplicates but semantic duplicates slip through. Could add embedding-based dedup later.
- **Observer frequency scaling** - could reduce from 15-min to 30-min during quiet hours instead of skipping entirely. Current approach (skip when no real turns) is simpler.

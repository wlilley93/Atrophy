# Agent Wiring Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Montgomery's silence, correct job script paths for all agents, fix Companion's broken schedules, resolve prompt resolution gaps, and enable Xan to self-service agent config changes in future.

**Architecture:** The Atrophy app uses manifest-driven wiring - each agent's `~/.atrophy/agents/<name>/data/agent.json` is the single source of truth for channels, MCP, jobs, and routing. Most issues trace to incomplete manifests, missing prompt file paths, or script path confusion. The Telegram daemon polls correctly for all three agents but dispatch/inference failures cause Montgomery's silence.

**Tech Stack:** TypeScript (Electron main process), Python (job scripts, MCP servers), JSON (agent manifests)

---

## Diagnosis Summary

### What's working
- Telegram daemon IS running (lock held by dev Electron instance PID 25873)
- Montgomery IS being polled (daemon state file has `last_update_id: 377557001`)
- Montgomery's cron jobs ARE running (worldmonitor logs current to the minute)
- All three agents have correct Telegram credentials in manifests
- Montgomery's MCP config file exists and is valid at `~/.atrophy/mcp/general_montgomery.config.json`

### What's broken

| # | Issue | Severity | Root Cause |
|---|-------|----------|------------|
| 1 | Montgomery not responding to Telegram | Critical | Dispatch/inference failure - polling works but messages produce no response. Likely: (a) cron dispatch occupying `_activeDispatches` lock, (b) inference CLI failure, or (c) system prompt fallback to generic |
| 2 | Montgomery has no character prompt | High | Prompt files at `agents-personal/general_montgomery/prompts/` - not in any search path. `findAgentDir` returns `~/.atrophy/agents/general_montgomery` which has no `prompts/` dir. Falls back to generic "You are a companion" |
| 3 | Xan's jobs all point to companion scripts | Medium | All 7 jobs in Xan's manifest reference `scripts/agents/companion/*.py`. Scripts are agent-agnostic (use AGENT_NAME env var) but the path is confusing and fragile |
| 4 | Companion has one-shot cron schedules | Medium | `introspect`: "33 3 24 3 *" (March 24 only), `gift`: "11 0 28 3 *" (March 28 only), `voice_note`: "42 14 15 3 *" (March 15 - already passed). Should be recurring |
| 5 | Embedding failures on observer | Medium | `core/embeddings.py` thread safety fix is in working tree but running instance started before the fix. Needs restart to pick up |
| 6 | Two Electron instances running | Low | Dev instance (PID 25873, 5:08 PM) + dist instance (PID 70448, 9:47 PM). Dev holds daemon lock. Dist can't start daemon. Potential for cron job double-execution |
| 7 | Xan can't manage other agents | Enablement | No admin tooling. Xan has shell MCP but no structured way to edit manifests or restart services |

### Additional issues reported by Companion
- Trust scores not building from observations
- Voice note delivery to Telegram (no send mechanism)
- Org config not surfacing

These are feature gaps, not wiring bugs. Not covered in this plan.

---

## File Structure

### Files to create
- `scripts/agents/shared/` - symlinks or move of agent-agnostic job scripts
- `src/main/channels/telegram/__tests__/dispatch-lock.test.ts` - test for dispatch lock behavior

### Files to modify
- `~/.atrophy/agents/general_montgomery/prompts/` - copy prompt files from bundled source
- `~/.atrophy/agents/xan/data/agent.json` - fix job script paths
- `~/.atrophy/agents/companion/data/agent.json` - fix one-shot cron schedules
- `src/main/channels/telegram/daemon.ts` - add dispatch diagnostics logging
- `src/main/config.ts` - add `agents-personal/` to agent dir search (or copy prompts to user data)
- `src/main/channels/cron/runner.ts` - add AGENT_NAME to job script env (verify it's set)

---

### Task 1: Diagnose and fix Montgomery's silence

**Files:**
- Modify: `src/main/channels/telegram/daemon.ts:930-996` (registerAgentSwitchboard callback)
- Modify: `src/main/channels/telegram/daemon.ts:464-690` (dispatchToAgent)

The daemon polls Montgomery and gets updates (confirmed by state file). Messages enter the switchboard but produce no response. Three possible failure points need diagnosis:

- [ ] **Step 1: Add diagnostic logging to the agent router callback**

In `daemon.ts`, the `registerAgentSwitchboard` callback at line 931 drops messages silently when `_activeDispatches.has(agent.name)` is true. Add a log.warn so we can see if this is happening:

```typescript
// Line 933 - already has logging, but verify it fires for Montgomery
if (_activeDispatches.has(agent.name)) {
  log.warn(`[${agent.name}] Dispatch already in progress - dropping envelope from ${envelope.from}`);
  return undefined;
}
```

This already exists. The issue may be that cron jobs (worldmonitor output) are triggering inference dispatches that never complete. Add timing to `dispatchToAgent`:

```typescript
// At the top of dispatchToAgent, after line 470:
log.info(`[${agentName}] dispatch START for: ${text.slice(0, 80)}`);
```

- [ ] **Step 2: Check if worldmonitor cron output triggers inference**

The worldmonitor_poll.py script writes to a log file AND to memory.db directly. Check if it also prints to stdout (which the runner captures and routes through the switchboard):

```bash
cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron"
python3 scripts/agents/general_montgomery/worldmonitor_poll.py --tier fast 2>/dev/null
# If stdout is non-empty, it triggers inference dispatch for Montgomery
```

If it produces stdout, every 15-minute poll triggers an inference dispatch. If that dispatch hangs or takes >15 minutes, the `_activeDispatches` lock permanently blocks Telegram messages.

- [ ] **Step 3: Fix the dispatch lock to use per-source locks instead of per-agent**

The current design uses one `_activeDispatches` set per agent name. This means a cron dispatch blocks Telegram dispatches for the same agent. Change to allow Telegram messages to interrupt/queue rather than being silently dropped:

```typescript
// In registerAgentSwitchboard callback, replace the drop logic with queuing:
// OLD (line 933):
if (_activeDispatches.has(agent.name)) {
  log.warn(`[${agent.name}] Dispatch already in progress - dropping envelope from ${envelope.from}`);
  return undefined;
}

// NEW: Only drop if SAME source type is already dispatching.
// Telegram messages should queue, not drop.
const dispatchKey = `${agent.name}:${envelope.from.split(':')[0]}`;
if (_activeDispatches.has(agent.name)) {
  if (envelope.from.startsWith('telegram:')) {
    log.info(`[${agent.name}] Queuing Telegram message (cron dispatch in progress)`);
    // Don't drop - let withAgentDispatchLock serialize it
  } else {
    log.warn(`[${agent.name}] Dispatch already in progress - dropping non-Telegram envelope from ${envelope.from}`);
    return undefined;
  }
}
```

- [ ] **Step 4: Run test to verify dispatch lock behavior**

```bash
pnpm vitest run src/main/channels/telegram/__tests__/dispatch-lock.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add src/main/channels/telegram/daemon.ts
git commit -m "fix: allow Telegram messages to queue when cron dispatch active"
```

---

### Task 2: Fix Montgomery's missing prompts

**Files:**
- Copy: `agents-personal/general_montgomery/prompts/*` to `~/.atrophy/agents/general_montgomery/prompts/`

Montgomery's prompt files (soul.md, system_prompt.md, heartbeat.md) live at `agents-personal/general_montgomery/prompts/` in the repo. But `findAgentDir("general_montgomery")` returns `~/.atrophy/agents/general_montgomery` (because agent.json exists there), and that directory has NO `prompts/` subdirectory.

The prompt search chain (`prompts.ts:14-40`) checks:
1. Obsidian skills dir - no system.md for Montgomery
2. `~/.atrophy/agents/general_montgomery/skills/` - doesn't exist
3. `~/.atrophy/agents/general_montgomery/prompts/` - doesn't exist
4. `~/.atrophy/agents/general_montgomery/prompts/` (AGENT_DIR) - same, doesn't exist
5. `{BUNDLE_ROOT}/agents/general_montgomery/prompts/` - doesn't exist (only xan and mirror in bundled)

Result: Montgomery gets `"You are a companion. Be genuine, direct, and honest."` - completely wrong.

- [ ] **Step 1: Copy prompt files to user data dir**

```bash
mkdir -p ~/.atrophy/agents/general_montgomery/prompts
cp "agents-personal/general_montgomery/prompts/"*.md ~/.atrophy/agents/general_montgomery/prompts/
```

- [ ] **Step 2: Verify prompt resolution**

After restart, `loadSystemPrompt()` for Montgomery should find `~/.atrophy/agents/general_montgomery/prompts/system_prompt.md` via Tier 3 (user prompts) in the search chain.

- [ ] **Step 3: Do the same for Companion**

```bash
ls ~/.atrophy/agents/companion/prompts/ 2>/dev/null || echo "MISSING"
# If missing:
mkdir -p ~/.atrophy/agents/companion/prompts
cp "agents-personal/companion/prompts/"*.md ~/.atrophy/agents/companion/prompts/
```

- [ ] **Step 4: Add agents-personal to prompt search fallback**

The deeper fix: add `agents-personal/` as a search location in `config.ts:findAgentDir` so personal agents' bundled prompts are found without manual copying:

```typescript
// In config.ts findAgentDir(), add agents-personal check:
function findAgentDir(name: string): string {
  const userDir = path.join(USER_DATA, 'agents', name);
  if (fs.existsSync(path.join(userDir, 'data', 'agent.json'))) return userDir;
  const bundleDir = path.join(BUNDLE_ROOT, 'agents', name);
  if (fs.existsSync(path.join(bundleDir, 'data', 'agent.json'))) return bundleDir;
  // Also check agents-personal (personal agents bundled in repo)
  const personalDir = path.join(BUNDLE_ROOT, 'agents-personal', name);
  if (fs.existsSync(path.join(personalDir, 'data', 'agent.json'))) return personalDir;
  return userDir;
}
```

Wait - this would change AGENT_DIR to agents-personal, which is the repo. But we want the user data dir for writes (memory.db, etc.) and the bundled dir for reads (prompts). The current approach of separate AGENT_DIR (for prompts) and DATA_DIR (for data) already handles this.

Actually, the issue is that `findAgentDir` finds the user dir first (because agent.json exists there) and returns that. The bundled prompts in `agents-personal/` are never checked. The fix should be in `prompts.ts:getSearchDirs()`:

```typescript
// In prompts.ts getSearchDirs(), add agents-personal as a search location:
// After line 37, add:
const personalPrompts = path.join(BUNDLE_ROOT, 'agents-personal', config.AGENT_NAME, 'prompts');
if (personalPrompts !== agentDirPrompts && personalPrompts !== bundlePrompts
    && fs.existsSync(personalPrompts)) {
  dirs.push(personalPrompts);
}
```

- [ ] **Step 5: Run tests**

```bash
pnpm vitest run src/main/__tests__/prompts.test.ts
```

- [ ] **Step 6: Commit**

```bash
git add src/main/prompts.ts
git commit -m "fix: add agents-personal to prompt search path"
```

---

### Task 3: Move shared job scripts to a shared location

**Files:**
- Create: `scripts/agents/shared/` directory
- Move: 7 agent-agnostic scripts from `scripts/agents/companion/` to `scripts/agents/shared/`
- Modify: `~/.atrophy/agents/xan/data/agent.json` - update job paths
- Modify: `~/.atrophy/agents/companion/data/agent.json` - update job paths
- Modify: `agents/xan/data/agent.json` (bundled) - update job paths
- Modify: `agents-personal/companion/data/agent.json` (bundled) - update job paths
- Modify: `scripts/agents/xan/jobs.json` - update paths

The scripts `introspect.py`, `morning_brief.py`, `sleep_cycle.py`, `heartbeat.py`, `observer.py`, `check_reminders.py`, and `evolve.py` have been made agent-agnostic (they use `AGENT_NAME` env var). They should live in a shared location.

Scripts that are companion-specific (gift.py, voice_note.py, generate_face.py, converse.py, etc.) stay in `scripts/agents/companion/`.

- [ ] **Step 1: Create shared scripts directory and move agent-agnostic scripts**

```bash
mkdir -p scripts/agents/shared
# Move the 7 agent-agnostic scripts
for script in introspect.py morning_brief.py sleep_cycle.py heartbeat.py observer.py check_reminders.py evolve.py; do
  cp "scripts/agents/companion/$script" "scripts/agents/shared/$script"
done
```

Note: Copy first, update references, then remove originals. This prevents breakage during transition.

- [ ] **Step 2: Update Xan's manifest job paths**

In `~/.atrophy/agents/xan/data/agent.json`, change all `scripts/agents/companion/` references to `scripts/agents/shared/`:

```json
{
  "jobs": {
    "introspect": {
      "script": "scripts/agents/shared/introspect.py"
    },
    "morning_brief": {
      "script": "scripts/agents/shared/morning_brief.py"
    },
    "evolve": {
      "script": "scripts/agents/shared/evolve.py"
    },
    "heartbeat": {
      "script": "scripts/agents/shared/heartbeat.py"
    },
    "sleep_cycle": {
      "script": "scripts/agents/shared/sleep_cycle.py"
    },
    "observer": {
      "script": "scripts/agents/shared/observer.py"
    },
    "check_reminders": {
      "script": "scripts/agents/shared/check_reminders.py"
    }
  }
}
```

- [ ] **Step 3: Update Companion's manifest job paths (same pattern)**

Update `~/.atrophy/agents/companion/data/agent.json` - change the 7 shared scripts to `scripts/agents/shared/`. Leave `gift.py` and `voice_note.py` pointing to `scripts/agents/companion/`.

- [ ] **Step 4: Update bundled manifests and jobs.json files**

```bash
# Update agents/xan/data/agent.json (bundled)
# Update agents-personal/companion/data/agent.json (bundled)
# Update scripts/agents/xan/jobs.json
```

Same path changes as above.

- [ ] **Step 5: Verify scripts run from shared location**

```bash
AGENT=xan PYTHONPATH="/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" \
  python3 scripts/agents/shared/heartbeat.py 2>&1 | head -5
```

- [ ] **Step 6: Remove originals from companion dir (after verification)**

```bash
# Only after confirming shared copies work:
for script in introspect.py morning_brief.py sleep_cycle.py heartbeat.py observer.py check_reminders.py evolve.py; do
  rm "scripts/agents/companion/$script"
done
```

- [ ] **Step 7: Commit**

```bash
git add scripts/agents/shared/ scripts/agents/companion/ scripts/agents/xan/jobs.json agents/xan/data/agent.json agents-personal/companion/data/agent.json
git commit -m "refactor: move shared job scripts to scripts/agents/shared/"
```

---

### Task 4: Fix Companion's one-shot cron schedules

**Files:**
- Modify: `~/.atrophy/agents/companion/data/agent.json`
- Modify: `agents-personal/companion/data/agent.json`

Three jobs have one-shot schedules (specific month+day) instead of recurring patterns:
- `introspect`: "33 3 24 3 *" (fires only on March 24) - should be daily "33 3 * * *"
- `gift`: "11 0 28 3 *" (fires only on March 28) - this is self-rescheduling per its description, may be intentional
- `voice_note`: "42 14 15 3 *" (fires only on March 15 - already passed!) - also self-rescheduling

- [ ] **Step 1: Fix introspect to be daily**

In `~/.atrophy/agents/companion/data/agent.json`, change:
```json
"introspect": {
  "cron": "33 3 * * *",
```

- [ ] **Step 2: Determine if gift and voice_note need fixing**

These are described as "self-rescheduling" - the script runs, picks a random next date, and updates the manifest. If voice_note's schedule is March 15 (already passed), it means the script hasn't run since before March 15 to reschedule itself. Either:
- (a) Reset to a near-future date so the script can run and self-reschedule
- (b) Set a recurring schedule and remove self-rescheduling logic

For now, reset `voice_note` to tomorrow so it can self-reschedule:
```json
"voice_note": {
  "cron": "42 14 23 3 *",
```

- [ ] **Step 3: Update bundled manifest to match**

```bash
# Mirror the same changes to agents-personal/companion/data/agent.json
```

- [ ] **Step 4: Commit**

```bash
git add agents-personal/companion/data/agent.json
git commit -m "fix: reset companion cron schedules - introspect daily, voice_note rescheduled"
```

---

### Task 5: Apply embedding fix and restart

**Files:**
- Modified: `core/embeddings.py` (already in working tree)

The thread safety fix (threading lock + forced CPU device) is in the working tree but the running Electron instance started before the fix. Python scripts import from BUNDLE_ROOT which is the repo root, so the fix IS available to new script invocations. But if any MPS-cached model is loaded in-memory, it won't pick up the fix until the process restarts.

- [ ] **Step 1: Verify the fix is in place**

```bash
grep -n "threading.Lock\|force CPU\|device.*cpu" core/embeddings.py
```

- [ ] **Step 2: Commit the embedding fix**

```bash
git add core/embeddings.py
git commit -m "fix: thread safety for embeddings - lock + force CPU to prevent MPS deadlocks"
```

- [ ] **Step 3: Restart the dev Electron instance**

The dev instance (PID 25873) needs restarting to:
- Pick up the new Telegram dispatch logic (Task 1)
- Pick up the prompt search path fix (Task 2)
- Release and re-acquire the Telegram daemon lock
- Re-discover agents with updated manifests

```bash
# In the terminal running electron-vite dev, press Ctrl+C and re-run:
pnpm dev
```

- [ ] **Step 4: Kill the dist Electron instance**

Two instances cause confusion. Only run one:
```bash
kill 70448  # dist/Atrophy.app process
```

---

### Task 6: Enable Xan to manage agent configs

**Files:**
- Modify: `mcp/memory_server.py` - add agent manifest read/write tools

Xan already has the `shell` MCP server which could write files. But for structured, safe agent management, add dedicated tools to the memory MCP server (which every agent has):

- [ ] **Step 1: Add agent manifest tools to memory_server.py**

Add three tools:

1. `read_agent_manifest(agent_name)` - returns the agent.json for any agent
2. `update_agent_manifest(agent_name, updates)` - merges updates into agent.json (validates schema)
3. `list_agents()` - returns all discovered agents with basic info

These should only be available to agents with `system_access: true` or `can_provision: true` in their router config (currently only Xan).

- [ ] **Step 2: Add guard for system_access**

The MCP server receives `AGENT` env var. Check the calling agent's manifest to verify it has the right permissions before allowing cross-agent manifest writes.

- [ ] **Step 3: Add a restart-daemon switchboard tool**

In addition to manifest editing, Xan needs to trigger a daemon restart after config changes. This could be a switchboard tool that signals the daemon to re-discover agents:

Add `rediscoverAgents()` export to `daemon.ts` that:
1. Stops all pollers
2. Re-runs `discoverTelegramAgents()`
3. Re-launches pollers for any new/changed agents

And expose it via a switchboard address like `system:daemon-restart`.

- [ ] **Step 4: Test Xan can read/update Montgomery's manifest**

After restart, have Xan use the new MCP tools to read Montgomery's manifest and verify it's correct.

- [ ] **Step 5: Commit**

```bash
git add mcp/memory_server.py src/main/channels/telegram/daemon.ts
git commit -m "feat: add agent manifest MCP tools for cross-agent management"
```

---

### Task 7: Commit modified scripts

**Files:**
- Modified: `scripts/agents/companion/introspect.py` (AGENT_NAME parameterization)
- Modified: `scripts/agents/companion/morning_brief.py` (AGENT_NAME parameterization)
- Modified: `scripts/agents/companion/sleep_cycle.py` (AGENT_NAME parameterization)

These are already modified in the working tree. They change hardcoded "the companion" to `f"You are {AGENT_NAME}"`.

- [ ] **Step 1: Review the changes**

```bash
git diff scripts/agents/companion/introspect.py
git diff scripts/agents/companion/morning_brief.py
git diff scripts/agents/companion/sleep_cycle.py
```

- [ ] **Step 2: Commit**

```bash
git add scripts/agents/companion/introspect.py scripts/agents/companion/morning_brief.py scripts/agents/companion/sleep_cycle.py
git commit -m "fix: parameterize agent name in shared job scripts"
```

---

## Execution Order

1. **Task 7** first (commit existing working tree changes - no risk)
2. **Task 5** (commit embedding fix)
3. **Task 2** (fix Montgomery's prompts - immediate impact, copy files + code change)
4. **Task 1** (fix dispatch lock - prevents cron from blocking Telegram)
5. **Task 4** (fix Companion's schedules)
6. **Task 3** (move shared scripts - lower urgency, larger change)
7. **Task 6** (enable Xan self-service - enablement, not urgent)

After Tasks 1-5, restart the dev Electron instance to pick up all changes. Montgomery should begin responding.

---

## Quick Wins (no code changes, just runtime fixes)

These can be done RIGHT NOW before any code changes:

```bash
# 1. Copy Montgomery's prompts to user data
mkdir -p ~/.atrophy/agents/general_montgomery/prompts
cp agents-personal/general_montgomery/prompts/*.md ~/.atrophy/agents/general_montgomery/prompts/

# 2. Copy Companion's prompts if missing
mkdir -p ~/.atrophy/agents/companion/prompts
cp agents-personal/companion/prompts/*.md ~/.atrophy/agents/companion/prompts/ 2>/dev/null

# 3. Fix Companion's introspect schedule (runtime manifest)
# Edit ~/.atrophy/agents/companion/data/agent.json
# Change "33 3 24 3 *" to "33 3 * * *" for introspect

# 4. Kill the duplicate dist Electron instance
kill 70448

# 5. Restart the dev instance to pick up all changes
# Ctrl+C in the electron-vite dev terminal, then: pnpm dev
```

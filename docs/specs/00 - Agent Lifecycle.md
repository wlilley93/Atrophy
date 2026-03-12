# Agent Lifecycle

This specification describes the end-to-end lifecycle of a companion agent session, from startup through shutdown and inter-session autonomous activity. It also documents the agent manifest schema, discovery algorithm, deferral system, emotional state model, and session management.

---

## 1. Startup

Entry point: `src/main/index.ts`. Three modes: `--app` (menu bar), GUI (default, Svelte window), `--server` (HTTP API, no window).

### Sequence

1. **Electron ready**: `app.whenReady()` fires. Command-line arguments are parsed. In menu bar or server mode, `app.dock.hide()` is called. In GUI mode, the dock icon is set (brain .icns from `resources/icons/TheAtrophiedMind.icns`, or procedural orb fallback via `getAppIcon()`).

2. **Load configuration**: `ensureUserData()` creates `~/.atrophy/` on first run with subdirectories for agents, logs, and models. Writes an empty `config.json` (mode 0600) if none exists. Runs `migrateAgentData()` to copy bundled agent files to the user data directory (skips files that already exist, skips `agent.json` manifests). `getConfig()` instantiates the Config singleton, which:
   - Loads `~/.atrophy/.env` into `process.env` (simple key=value parsing, quotes stripped, existing env vars not overwritten)
   - Reads `~/.atrophy/config.json` for user settings
   - Resolves the version from `BUNDLE_ROOT/VERSION`
   - Resolves the agent (default: `xan`) via `_resolveAgent()` which loads the agent manifest and computes all derived paths
   - Detects Python path (checks `PYTHON_PATH`, then `python3`, `/opt/homebrew/bin/python3`, `/usr/local/bin/python3`)

3. **Initialize database**: `initDb()` executes `db/schema.sql` to create tables (idempotent via `IF NOT EXISTS`), then runs migrations for schema evolution on existing databases. Uses `better-sqlite3` with synchronous API.

4. **Register IPC handlers**: `registerIpcHandlers()` sets up all `ipcMain.handle()` channels:
   - Config: `config:get`, `config:update`
   - Agents: `agent:list`, `agent:listFull`, `agent:cycle`, `agent:switch`, `agent:getState`, `agent:setState`
   - Inference: `inference:send`, `inference:stop`
   - Setup: `setup:check`, `setup:inference`, `setup:saveSecret`, `setup:createAgent`
   - Window: `window:toggleFullscreen`, `window:minimize`, `window:close`
   - Usage: `usage:all`, `activity:all`
   - Opening: `opening:get`
   - Avatar: `avatar:getVideoPath`
   - Cron: `cron:list`, `cron:toggle`
   - Telegram: `telegram:startDaemon`, `telegram:stopDaemon`
   - Server: `server:start`, `server:stop`
   - Memory: `memory:search`
   - Login: `install:isEnabled`, `install:toggle`
   - Updater: `updater:check`, `updater:download`, `updater:quitAndInstall`
   - Deferral: `deferral:complete`
   - Queue: `queue:drainAgent`, `queue:drainAll`

   `registerAudioHandlers()` and `registerWakeWordHandlers()` add audio-specific channels.

5. **Configure TTS callbacks**: `setPlaybackCallbacks()` wires TTS playback events to IPC sends:
   - `onStarted(index)` - sends `tts:started` to renderer, pauses wake word listener
   - `onDone(index)` - sends `tts:done` to renderer
   - `onQueueEmpty()` - sends `tts:queueEmpty` to renderer, resumes wake word listener

6. **Resume last agent**: `getLastActiveAgent()` reads `_last_active` from `~/.atrophy/agent_states.json`. If a different agent was last active, `config.reloadForAgent()` and `initDb()` switch to it.

7. **System prompt**: Not loaded during startup. Loaded lazily on first `inference:send` call via `loadSystemPrompt()` in `src/main/context.ts`. Resolution order:
   1. `loadPrompt('system', '')` - searches tiered directories for `system.md`
   2. `agents/<name>/prompts/system_prompt.md` - bundle fallback
   3. `'You are a companion. Be genuine, direct, and honest.'` - hardcoded fallback

   After loading the base prompt, skill files are appended (soul.md, heartbeat.md, gift.md, etc.), and the agent roster is appended for deferral awareness.

8. **Start background timers**:
   - **Sentinel**: Coherence check every 5 minutes (`setInterval(300_000)`)
   - **Queue poller**: Drains `.message_queue.json` every 10 seconds (`setInterval(10_000)`)
   - **Deferral watcher**: Checks for agent handoff requests every 2 seconds (`setInterval(2_000)`)

9. **Create window**: `BrowserWindow` with:
   ```
   width: config.WINDOW_WIDTH (default 622)
   height: config.WINDOW_HEIGHT (default 830)
   minWidth: 360, minHeight: 480
   titleBarStyle: 'hiddenInset'
   trafficLightPosition: { x: 14, y: 14 }
   vibrancy: 'ultra-dark'
   visualEffectState: 'active'
   backgroundColor: '#00000000' (transparent)
   contextIsolation: true
   nodeIntegration: false
   webSecurity: false
   sandbox: false
   ```
   In menu bar mode, the window starts hidden and a `Tray` is created with `Cmd+Shift+Space` global shortcut.

10. **Initialize auto-updater**: `initAutoUpdater()` sets up `electron-updater` (skipped in dev mode). Checks for updates after a 5-second delay.

### First Inference

When the renderer mounts, it calls `opening:get` via IPC, which returns the static opening line from the agent manifest (or the fallback `'Ready. Where are we?'`). The `Session` object is not created until the first user message arrives via `inference:send`.

---

## 2. Agent Manifest Schema

The agent manifest lives at `agents/<name>/data/agent.json` (bundle) and/or `~/.atrophy/agents/<name>/data/agent.json` (user). The user version takes precedence for user-modified fields, but the bundle version is the source of truth for the manifest.

### Full schema

| Field | Type | Default | Resolution | Description |
|-------|------|---------|------------|-------------|
| `display_name` | `string` | Capitalized `name` | `agentCfg` | Human-readable name shown in UI |
| `user_name` | `string` | `"User"` | `cfg` | Name of the user |
| `OPENING_LINE` | `string` | `"Hello."` | `agentCfg` | First words the agent says |
| `wake_words` | `string[]` | `["hey <name>", "<name>"]` | manifest only | Trigger phrases for wake word detection |
| `telegram_emoji` | `string` | `""` | manifest only | Emoji prefix for Telegram messages |
| `disabled_tools` | `string[]` | `[]` | manifest only | MCP tools to disable for this agent |
| `description` | `string` | `""` | manifest only | Brief description (used in roster/deferral context) |
| `role` | `string` | `""` | manifest only | `"system"` for system agents (sorted first in discovery) |
| `TTS_BACKEND` | `string` | `"elevenlabs"` | `agentCfg` | TTS engine: `"elevenlabs"`, `"fal"`, `"say"`, `"off"` |
| `ELEVENLABS_VOICE_ID` | `string` | `""` | `agentCfg` | ElevenLabs voice ID |
| `ELEVENLABS_MODEL` | `string` | `"eleven_v3"` | `agentCfg` | ElevenLabs model |
| `ELEVENLABS_STABILITY` | `number` | `0.5` | `agentCfg` | Voice stability (0.0-1.0) |
| `ELEVENLABS_SIMILARITY` | `number` | `0.75` | `agentCfg` | Voice similarity boost (0.0-1.0) |
| `ELEVENLABS_STYLE` | `number` | `0.35` | `agentCfg` | Voice style exaggeration (0.0-1.0) |
| `TTS_PLAYBACK_RATE` | `number` | `1.12` | `agentCfg` | TTS playback speed |
| `FAL_VOICE_ID` | `string` | `""` | `agentCfg` | Fal.ai voice ID (fallback TTS) |
| `HEARTBEAT_ACTIVE_START` | `number` | `9` | `agentCfg` | Heartbeat active hours start (24h) |
| `HEARTBEAT_ACTIVE_END` | `number` | `22` | `agentCfg` | Heartbeat active hours end (24h) |
| `HEARTBEAT_INTERVAL_MINS` | `number` | `30` | `agentCfg` | Minutes between heartbeat checks |
| `TELEGRAM_BOT_TOKEN` | `string` | `""` | `agentCfg` | Per-agent Telegram bot token |
| `TELEGRAM_CHAT_ID` | `string` | `""` | `agentCfg` | Per-agent Telegram chat ID |
| `WINDOW_WIDTH` | `number` | `622` | `agentCfg` | Window width in pixels |
| `WINDOW_HEIGHT` | `number` | `830` | `agentCfg` | Window height in pixels |
| `DISABLED_TOOLS` | `string[]` | `[]` | `agentCfg` | Tools to block (saved via settings) |

### Resolution modes

- **`cfg(key, default)`**: env var > user config > agent manifest > default (user-level settings)
- **`agentCfg(key, default)`**: agent manifest > env var > user config > default (agent-level settings take priority)

---

## 3. Agent Discovery Algorithm

Implemented in `discoverAgents()` in `src/main/agent-manager.ts`.

### Search directories

Two directories are searched in order:

1. `~/.atrophy/agents/` (user-installed agents)
2. `<BUNDLE_ROOT>/agents/` (bundled agents)

The bundle directory is skipped if it resolves to the same path as the user directory.

### Discovery steps

1. Read directory entries from each search directory, sorted alphabetically
2. For each entry, check if `<entry>/data/` exists (not `agent.json` specifically - just the `data` directory)
3. Skip entries already seen (user directory takes precedence over bundle)
4. Load the manifest from `<entry>/data/agent.json` to extract `display_name`, `description`, and `role`
5. If no manifest is found, use defaults (capitalized name, empty description, empty role)

### Sort order

Agents are sorted with system-role agents first, then alphabetically:

```typescript
agents.sort((a, b) => {
  const aSystem = a.role === 'system' ? 0 : 1;
  const bSystem = b.role === 'system' ? 0 : 1;
  if (aSystem !== bSystem) return aSystem - bSystem;
  return a.name.localeCompare(b.name);
});
```

### Agent cycling

`cycleAgent(direction, current)` walks the sorted agent list in the given direction (+1 or -1), skipping disabled agents. Returns `null` if only one agent exists or all others are disabled.

### Agent state

Per-agent state is stored in `~/.atrophy/agent_states.json`:

```json
{
  "_last_active": "xan",
  "xan": { "muted": false, "enabled": true },
  "oracle": { "muted": true, "enabled": true },
  "iris": { "muted": false, "enabled": false }
}
```

- `muted`: Suppresses TTS output but the agent still responds in text
- `enabled`: Controls whether the agent appears in the cycle rotation and receives cron jobs

When `enabled` is toggled, `toggleAgentCron()` runs `cron.py --agent <name> install/uninstall` to manage launchd jobs.

---

## 4. Turn Cycle

Each user turn follows this pipeline:

### Input

1. **Get input**: Text typed in `InputBar.svelte`, or voice via push-to-talk (Ctrl key held, audio captured via `navigator.mediaDevices.getUserMedia()` in the renderer, chunks sent to main via `audio:chunk` IPC, transcribed by whisper.cpp in `src/main/stt.ts`).

2. **Mark active**: `setActive()` updates user presence tracking.

3. **Ensure session**: If no session exists, creates one via `new Session()` and `session.start()` which inserts a row into the `sessions` table and retrieves the last CLI session ID.

4. **Load system prompt**: Lazily on first call via `loadSystemPrompt()`.

5. **Record user turn**: `session.addTurn('will', text)` writes to the `turns` table.

6. **Detect mood shift**: `detectMoodShift(text)` checks for heavy keywords. If detected, `session.updateMood('heavy')` updates the session record.

### Inference

7. **Stream inference**: Claude CLI spawned via `streamInference(text, systemPrompt, cliSessionId)`. Events arrive as newline-delimited JSON on stdout.

8. **Process events**: The `EventEmitter` forwards events to the renderer:
   - `TextDelta` - `inference:textDelta` IPC send
   - `SentenceReady` - `inference:sentenceReady` IPC send + TTS synthesis in background
   - `ToolUse` - `inference:toolUse` IPC send
   - `Compacting` - `inference:compacting` IPC send
   - `StreamDone` - CLI session ID saved, agent turn recorded, `inference:done` IPC send
   - `StreamError` - `inference:error` IPC send

### Post-Inference

9. **Persist**: CLI session ID saved if changed. Full response written to `turns` table. Embedding computed asynchronously.

10. **Memory flush**: If compaction was detected, `runMemoryFlush()` fires a silent inference turn to flush observations, thread updates, bookmarks, and notes before context is compressed.

11. **Coherence check**: SENTINEL runs on its 5-minute timer. Analyzes last 5 companion turns for repetition, flatness, agreement drift, and vocabulary staleness.

12. **Follow-up**: 15% chance (`shouldFollowUp()`) of an unprompted second thought. Delayed 3-6 seconds, uses `followupPrompt()`.

---

## 5. Emotional State Model

Implemented in `src/main/inner-life.ts`. The emotional state is a multi-dimensional model with six emotion dimensions and four trust domains, all subject to time-based decay toward baselines.

### Emotion Dimensions

| Dimension | Baseline | Half-Life | Labels (high/mid/low) |
|-----------|----------|-----------|----------------------|
| `connection` | 0.5 | 8 hours | present, engaged / attentive / distant |
| `curiosity` | 0.6 | 4 hours | deeply curious / interested / disengaged |
| `confidence` | 0.5 | 4 hours | grounded, sure / steady / uncertain |
| `warmth` | 0.5 | 4 hours | warm, open / neutral / guarded |
| `frustration` | 0.1 | 4 hours | frustrated / mildly tense / calm |
| `playfulness` | 0.3 | 4 hours | playful / light / serious |

All values are clamped to `[0.0, 1.0]`.

### Trust Domains

| Domain | Baseline | Half-Life | Description |
|--------|----------|-----------|-------------|
| `emotional` | 0.5 | 8 hours | Willingness to share vulnerable content |
| `intellectual` | 0.5 | 8 hours | Trust in analytical/technical discussions |
| `creative` | 0.5 | 8 hours | Trust when sharing creative work |
| `practical` | 0.5 | 8 hours | Trust for actionable advice |

Trust updates are clamped to +/-0.05 per call to prevent rapid swings.

### Decay Model

Emotions and trust decay toward their baselines using exponential decay:

```
value = baseline + (current - baseline) * 0.5^(hours_elapsed / half_life)
```

Decay is applied on load - every time `loadState()` is called, the state is decayed from its `last_updated` timestamp to the current time. Decay is skipped if less than 0.01 hours (36 seconds) have elapsed.

### Persistence

The emotional state is stored as JSON at `~/.atrophy/agents/<name>/data/.emotional_state.json`:

```json
{
  "emotions": {
    "connection": 0.65,
    "curiosity": 0.72,
    "confidence": 0.48,
    "warmth": 0.61,
    "frustration": 0.08,
    "playfulness": 0.45
  },
  "trust": {
    "emotional": 0.55,
    "intellectual": 0.62,
    "creative": 0.48,
    "practical": 0.51
  },
  "session_tone": "reflective",
  "last_updated": "2026-03-12T14:30:00.000Z"
}
```

### Context Injection Format

`formatForContext()` generates a markdown block injected into the agency context:

```
## Inner State
- connection: present, engaged (0.65)
- curiosity: deeply curious (0.72)
- confidence: steady (0.48)
- warmth: warm, open (0.61)
- frustration: calm (0.08)
- playfulness: light (0.45)

## Trust
- emotional: 0.55
- intellectual: 0.62
- creative: 0.48
- practical: 0.51

Session tone: reflective
```

### Emotional Signal Detection

`detectEmotionalSignals()` in `src/main/agency.ts` scans user messages and returns a delta map:

| Signal | Phrases (examples) | Effect |
|--------|-------------------|--------|
| Long thoughtful message (400+ chars) | - | curiosity +0.1, connection +0.05 |
| Short dismissive reply (<30 chars) | "fine", "whatever", "idk", "who cares" | connection -0.1, frustration +0.1 |
| Vulnerability | "i feel", "i'm scared", "the truth is" | connection +0.15, warmth +0.1 |
| Help-seeking | "can you help", "what should i" | confidence +0.05, trust.practical +0.02 |
| Creative sharing | "i wrote", "check this out", "new project" | curiosity +0.1, trust.creative +0.02 |
| Deflection | "anyway", "moving on", "forget i said" | frustration +0.05 |
| Playfulness | "haha", "lol", "lmao" | playfulness +0.1 |
| Mood shift (heavy keywords) | "hopeless", "want to die", "falling apart" | warmth +0.1, playfulness -0.1 |

---

## 6. Agency Context

The agency context is a dynamic block assembled before each inference call. It includes behavioral signals derived from the conversation state.

### Time-of-Day Context

`timeOfDayContext()` returns register guidance based on the current hour:

| Hours | Register |
|-------|----------|
| 23:00-03:59 | Gentler, check if he should sleep |
| 04:00-06:59 | Something's either wrong or focused |
| 07:00-11:59 | Direct, practical register |
| 12:00-17:59 | Working hours energy |
| 18:00-22:59 | Reflective register available |

### Mood Detection

`detectMoodShift()` checks for 20 heavy keywords/phrases: "i can't", "hopeless", "want to die", "falling apart", "numb", "empty", "nobody cares", etc. Returns boolean.

When detected, `moodShiftSystemNote()` injects: "Emotional weight detected in what he just said. Be present before being useful. One question rather than a framework. Do not intellectualise what needs to be felt."

### Validation-Seeking Detection

`detectValidationSeeking()` checks for 17 patterns: "right?", "don't you think", "am i wrong", "that's not crazy", etc.

When detected: "He may be seeking validation rather than engagement. Don't mirror. Have a perspective."

### Compulsive Modelling Detection

`detectCompulsiveModelling()` checks for 10 patterns: "unifying framework", "meta level", "the pattern is", "if i restructure everything", etc. Triggers when 2+ patterns match in a single message.

When detected: "Compulsive modelling detected - parallel threads, meta-shifts, or 'just one more' patterns. Name the stage. One concrete reversible action."

### Drift Detection

`detectDrift()` analyzes the last 4 companion turns for excessive agreeableness. If 3+ turns start with phrases like "you're right", "absolutely", "of course", "totally", it injects: "You have been agreeable for several turns in a row. Check yourself - are you mirroring or actually engaging?"

### Energy Matching

`energyNote()` analyzes message length:
- Under 20 characters: "Short message. Match the energy - keep your response tight."
- Over 800 characters: "Long message - he is working something out. Give it depth."

### Time Gap Awareness

`timeGapNote()` checks days since last session:
- 14+ days: "It has been N days since he was last here. That is a long gap. Acknowledge it naturally."
- 7+ days: "About a week since the last session. Something may have shifted."
- 3+ days: "N days since last session. Not long, but enough that context may have moved."

---

## 7. Session Management

Implemented in `src/main/session.ts`.

### Session class

```typescript
class Session {
  sessionId: number | null;        // Database session ID
  startedAt: number | null;        // Date.now() at start
  turnHistory: { role: string; content: string; turnId: number }[];
  cliSessionId: string | null;     // Claude CLI session ID for --resume
  mood: string | null;             // 'heavy' or null
}
```

### Session start

`session.start()` performs:
1. Inserts a new row into the `sessions` table via `memory.startSession()`
2. Records `Date.now()` as `startedAt`
3. Clears `turnHistory`
4. Retrieves the last CLI session ID via `memory.getLastCliSessionId()` for conversation continuity

### Turn recording

`session.addTurn(role, content)` writes to the `turns` table and appends to the in-memory `turnHistory`. Throws if the session has not been started.

### Mood tracking

`session.updateMood('heavy')` sets the mood in memory and updates the session row in the database.

### Soft time limit

`session.shouldSoftLimit()` returns `true` when `minutesElapsed() >= SESSION_SOFT_LIMIT_MINS` (default 60 minutes). The companion uses this to deliver a check-in message.

### Session end

`session.end(systemPrompt)` is called on window close, app quit, or agent switch:

1. **Skip short sessions**: If fewer than 4 turns, just updates `ended_at` in the database
2. **Generate summary**: Formats all turns as `"<Name>: <content>"` and sends to `runInferenceOneshot()` with the prompt: "Summarise this conversation in 2-3 sentences. Focus on what mattered, not what was said. Note any new threads, shifts in mood, or observations worth remembering."
3. **Store summary**: Writes to the `summaries` table via `memory.writeSummary()`
4. **Update session**: Sets `ended_at`, summary text, and mood on the session row

---

## 8. Agent Deferral System

The deferral system allows agents to hand off to each other mid-conversation. It is triggered by the MCP `defer_to_agent` tool and processed by the main process.

### Deferral file

The MCP tool writes a JSON file at `~/.atrophy/.deferral_request.json`:

```json
{
  "target": "oracle",
  "context": "User is asking about database schema design, which Oracle specializes in.",
  "user_question": "How should I structure my tables for this?"
}
```

### Polling

The deferral watcher runs every 2 seconds. When it finds the file:
1. Reads and parses the JSON
2. Deletes the file immediately (consumed)
3. Validates the request

### Anti-Loop Protection

`validateDeferralRequest()` enforces two rules:

1. **No self-deferral**: `target === currentAgent` is rejected
2. **Rate limiting**: Maximum 3 deferrals within a 60-second sliding window

```typescript
const ANTI_LOOP_WINDOW_MS = 60_000;
const MAX_DEFERRALS_PER_WINDOW = 3;
```

If the window has expired (more than 60 seconds since `deferralWindowStart`), the counter resets. If the limit is exceeded, the deferral is suppressed with a log message: `[deferral] suppressed - too many in 60s`.

### Deferral execution

When validated, the `deferral:request` IPC event is sent to the renderer, which initiates the transition. The renderer calls `deferral:complete` IPC, which:

1. **Suspend current session**: Saves the CLI session ID and turn history in a `Map<string, { cliSessionId, turnHistory }>`
2. **Switch agent**: Reloads config, reinitializes database, resets MCP config, updates `_last_active`, clears audio queue
3. **Resume target session**: If the target agent has a suspended session, restores its CLI session ID and turn history
4. **Reset deferral counter**: Prevents the counter from accumulating across switches

### Session suspension

Suspended sessions are stored in memory (not persisted to disk):

```typescript
const _suspendedSessions = new Map<string, {
  cliSessionId: string;
  turnHistory: unknown[];
}>();
```

When you switch back to a previously suspended agent, the conversation resumes where it left off (same Claude CLI session, same turn history).

---

## 9. Session End

Triggered by window close, `app.on('will-quit')`, or agent switch via `agent:switch` IPC.

### Sequence

1. **Generate summary**: If the session has 4+ turns, all turn text is sent to `runInferenceOneshot()` with a summarization prompt focusing on what mattered, not what was said.

2. **Write summary**: Summary stored in the `summaries` table with an async embedding. The session row is updated with `ended_at`, summary text, and mood.

3. **Save emotional state**: The inner life state (emotions + trust) is written to `.emotional_state.json` with the current timestamp.

### App Shutdown

`app.on('will-quit')` performs cleanup:
- Unregisters all global shortcuts
- Clears all interval timers (sentinel, queue, deferral)
- Stops wake word listener
- Stops Telegram daemon
- Stops HTTP server
- Closes all SQLite database connections via `closeAll()`

---

## 10. Between Sessions

Autonomous daemons run on launchd schedules defined in `scripts/agents/<name>/jobs.json`. The companion can view and modify its own schedule via the `manage_schedule` MCP tool. Cron management is handled by `src/main/cron.ts`, which generates launchd plists and calls `launchctl load/unload`.

### Daemon Types

| Daemon | Purpose | Typical Schedule |
|--------|---------|-----------------|
| **observer** | Reads recent turns, extracts factual observations with confidence scores | Every 15 minutes during active hours |
| **heartbeat** | Evaluates whether to reach out via Telegram based on time since last interaction, active threads, and emotional state | Every 30 minutes during active hours (configurable per agent) |
| **sleep_cycle** | End-of-day processing: decay observation activations, mark stale observations, generate daily reflection note | Once nightly |
| **introspect** | Reviews recent observations, checks which still hold, updates identity snapshot if warranted | Periodic (agent-configured) |
| **evolve** | Self-evolution: reviews conversation history and rewrites system prompt and soul document | Monthly |
| **gift** | Generates a small creative offering (poem, observation, question) and leaves it in Obsidian | Periodic (agent-configured) |

Daemons use `runInferenceOneshot()` for inference (no MCP tools, no session persistence) and write results to the database or Obsidian vault. Messages intended for the GUI are written to the per-agent queue file (`.message_queue.json`), which the main process polls every 10 seconds and forwards to the renderer.

---

## 11. Agent Roster and Deferral Awareness

The system prompt includes an "Other Agents" section listing all enabled agents (excluding the current one). This gives the active agent awareness of who else exists and when to defer.

### Roster format (appended to system prompt)

```markdown
## Other Agents

You can hand off to these agents using `defer_to_agent` if the user's
question is better suited to them:

- **Oracle** (`oracle`) - Database architecture and systems design
- **Iris** (`iris`) - Creative writing and poetry

Only defer when there's a clear reason - another agent's specialty
matches the question, or the user asks for them by name. Don't defer
just because another agent exists.
```

### Roster filtering

The roster excludes:
- The current agent (would be self-deferral)
- Disabled agents (`enabled: false` in `agent_states.json`)
- Entries without a valid `agent.json` manifest

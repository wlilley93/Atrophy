# Agent Lifecycle

This specification describes the end-to-end lifecycle of a companion agent session, from startup through shutdown and inter-session autonomous activity.

---

## 1. Startup

Entry point: `src/main/index.ts`. Three modes: `--app` (menu bar), GUI (default, Svelte window), `--server` (Express HTTP API, no window).

### Sequence

1. **Electron ready**: `app.whenReady()` fires. Command-line arguments are parsed. In menu bar or server mode, `app.dock.hide()` is called. In GUI mode, the dock icon is set (brain .icns or procedural orb fallback). Note: there is no explicit `.env` loading step - the Electron version reads configuration from `~/.atrophy/config.json` and `agent.json` rather than dotenv files. Environment variables (API keys, tokens) are set via the setup wizard's `saveEnvVar()` which writes to `~/.atrophy/.env`, but these are loaded by Python subprocess scripts, not by the main Electron process.

2. **Load configuration**: `ensureUserData()` creates `~/.atrophy/` on first run. `getConfig()` reads `~/.atrophy/config.json` for user settings, then loads the agent manifest from `agents/<name>/data/agent.json` (checking user-installed agents in `~/.atrophy/agents/` first, then bundled agents). Runtime state paths resolve to `~/.atrophy/agents/<name>/data/`.

3. **Initialise database**: `initDb()` executes `db/schema.sql` to create tables (idempotent via `IF NOT EXISTS`), then runs migrations for schema evolution on existing databases. Uses `better-sqlite3` with synchronous API.

4. **Register IPC handlers**: `registerIpcHandlers()` sets up all `ipcMain.handle()` channels for inference, agents, config, setup, window management, audio, cron, Telegram, server, vector search, avatar, login item, auto-updater, and agent deferral. `registerAudioHandlers()` and `registerWakeWordHandlers()` add audio-specific channels.

5. **Configure TTS callbacks**: `setPlaybackCallbacks()` wires TTS playback events (`onStarted`, `onDone`, `onQueueEmpty`) to IPC sends to the renderer and wake word pause/resume.

6. **Resume last agent**: `getLastActiveAgent()` checks `agent_states.json`. If a different agent was last active, `config.reloadForAgent()` and `initDb()` switch to it.

Note: The system prompt is **not** loaded during startup. It is loaded lazily on the first `inference:send` call via `loadSystemPrompt()` in `src/main/context.ts`. This function uses four-tier resolution with Obsidian-first priority:

   1. **Obsidian skills** (`<obsidian_vault>/Agent Workspace/<agent>/skills/system.md`) - allows the companion to edit its own system prompt via the self-evolution daemon
   2. **Local skills** (`~/.atrophy/agents/<name>/skills/system.md`)
   3. **User prompts** (`~/.atrophy/agents/<name>/prompts/system.md`)
   4. **Bundle prompts** (`agents/<name>/prompts/system_prompt.md`)

The first file found wins. If none exist, a minimal fallback is used (`'You are a companion. Be genuine, direct, and honest.'`). After loading the base prompt, all non-system skill files from the same search directories are appended (soul.md, heartbeat.md, gift.md, etc.), and the agent roster is appended for deferral awareness.

7. **Start background timers**:
   - SENTINEL coherence check every 5 minutes
   - Message queue poller every 10 seconds (drains `.message_queue.json` and sends to renderer)
   - Deferral watcher every 2 seconds (checks for agent handoff requests from MCP tools)

8. **Create window**: `BrowserWindow` is created with `titleBarStyle: 'hiddenInset'`, `vibrancy: 'ultra-dark'`, `contextIsolation: true`, `nodeIntegration: false`. The preload script is loaded. In menu bar mode, the window starts hidden and a `Tray` is created with `Cmd+Shift+Space` global shortcut toggle.

9. **Initialise auto-updater**: `initAutoUpdater()` sets up `electron-updater` to check for updates and forward events to the renderer via IPC.

### First Inference

When the renderer mounts, it calls `opening:get` via IPC, which returns the static opening line from `agent.json` (or the fallback `'Ready. Where are we?'`). The `Session` object is not created until the first user message arrives via `inference:send`.

Unlike the Python version, the Electron version does not currently distinguish between new and resumed sessions for the opening line. The Python GUI mode generates a dynamic opening via `run_inference_oneshot()` with a randomly selected style directive (from 12 options: question, observation, tease, admission, callback, challenge, sensory, silence-break, gift, redirect, context-aware, or meta). The Python CLI mode also performs a proactive memory check on resumed sessions, surfacing threads and recent memory. The Electron version always uses the static opening line from the manifest. Dynamic openings are a planned enhancement.

---

## 2. Turn Cycle

Each user turn follows this pipeline:

### Input

1. **Get input**: Text typed in `InputBar.svelte`, or voice via push-to-talk (Ctrl key held, audio captured via `navigator.mediaDevices.getUserMedia()` in the renderer, chunks sent to main via `audio:chunk` IPC, transcribed by whisper.cpp in `src/main/stt.ts`).

2. **Classify effort**: If adaptive effort is enabled and base effort is `medium`, `classifyEffort()` in `src/main/thinking.ts` analyses the message to determine inference effort level. Short greetings get `low`; complex questions get `high`.

### Context Assembly

3. **Build agency context**: `buildAgencyContext()` in `src/main/inference.ts` assembles a dynamic context block:
   - Time-of-day register (late night: gentler; morning: practical; evening: reflective)
   - Emotional state from `src/main/inner-life.ts` (six dimensions + four trust domains with descriptive labels)
   - User presence status (returned from away, etc.)
   - Session pattern analysis (frequency over last 7 days)
   - Mood shift detection on the current message
   - Validation-seeking detection
   - Compulsive modelling detection
   - Time gap since last session
   - Active thread names (up to 5)
   - Energy matching (message length/tone analysis)
   - Drift detection on recent companion turns (excessive agreeableness)
   - Journal prompting (probabilistic, contextual)
   - Morning digest nudge (5-10am)
   - Cross-agent awareness (recent summaries from other agents)
   - Security reinforcement (prompt injection defence instructions)

4. **Auto-detect emotional signals**: The user's message is scanned for emotional signals via `detectEmotionalSignals()`. Detected signals update the emotional state and trust dimensions before inference.

### Inference

5. **Stream inference**: Claude CLI spawned via `child_process.spawn()` in `src/main/inference.ts` with `--output-format stream-json`. For new sessions, the system prompt and context are sent via `--system-prompt`. For resumed sessions, context is prepended to the user message via `[Current context: ...]`.

6. **Process events**: Events arrive as newline-delimited JSON on stdout. The `EventEmitter` handles:
   - `TextDelta`: Forwarded to renderer via `inference:textDelta` IPC send.
   - `SentenceReady`: Sent to renderer for display, and to TTS for synthesis in parallel.
   - `ToolUse`: Forwarded to renderer via `inference:toolUse` IPC send.
   - `Compacting`: Forwarded to renderer via `inference:compacting` IPC send.
   - `StreamDone`: Full text and session ID captured. CLI session ID saved. Agent turn recorded.
   - `StreamError`: Error forwarded to renderer via `inference:error` IPC send.

### Post-Inference

7. **Persist**: CLI session ID saved if changed. Full response written to `turns` table via `session.addTurn()`. Embedding computed asynchronously.

8. **Memory flush**: If compaction was detected, `runMemoryFlush()` fires a silent inference turn to flush observations, thread updates, bookmarks, and notes before context is compressed.

9. **Coherence check**: SENTINEL runs on its 5-minute `setInterval` timer. Analyses last 5 companion turns for repetition, flatness, agreement drift, and vocabulary staleness. Fires a silent re-anchoring turn if degraded.

10. **Follow-up**: 15% chance of an unprompted second thought. Delayed 3-6 seconds, uses a follow-up prompt that instructs continuation without repeating.

---

## 3. Mid-Session Behaviour

### Silence Detection

No explicit silence timer in the current implementation. The Electron event loop is non-blocking; the renderer waits for user input.

### Unprompted Follow-Up

After each turn, `shouldFollowUp()` returns `true` with 15% probability. The follow-up uses the existing CLI session and adds a system prompt suffix instructing the companion to continue with a second thought, add a question, or shift register.

### Mood Shift Detection

`detectMoodShift()` in `src/main/agency.ts` scans user messages for emotional weight indicators. When detected, the session mood is updated to `heavy` via `session.updateMood()` and a system note is injected advising the companion to stay present and not reset to neutral.

### Soft Time Limit

At 60 minutes (`SESSION_SOFT_LIMIT_MINS`), `session.shouldSoftLimit()` returns true. The companion delivers a check-in message. The message is spoken via TTS, written to the turn history, and the warning flag is set so it only fires once per session.

### Agent Deferral

The deferral watcher (2-second interval) polls `~/.atrophy/.deferral_request.json` for handoff requests written by the MCP `defer_to_agent` tool. When found:
1. The request is validated against anti-loop protection (max 3 deferrals in 60 seconds, no self-deferral).
2. The current agent's session is suspended (CLI session ID and turn history saved in memory).
3. Config is reloaded for the target agent, database is re-initialized, MCP config is reset.
4. The target agent's suspended session is resumed if one exists.
5. The renderer is notified via `deferral:request` IPC to update the UI.

---

## 4. Session End

Triggered by window close, `app.on('will-quit')`, or agent switch via `agent:switch` IPC.

### Sequence

1. **Generate summary**: If the session has 4+ turns, all turn text is sent to `runInferenceOneshot()` with a summarisation prompt. The model (`claude-sonnet-4-6`, effort `low`) is instructed to focus on what mattered, not what was said, and to note new threads, mood shifts, and observations.

2. **Write summary**: Summary stored in the `summaries` table with an async embedding. The session row is updated with `ended_at`, summary text, and mood. The schema also supports a `notable` boolean flag on sessions (`BOOLEAN DEFAULT 0`), which can be set to mark sessions of particular significance. The current `session.end()` implementation does not set this flag automatically - it is available for the companion to flag via the MCP `mark_session_notable` tool or for background jobs (e.g. sleep-cycle) to set retroactively.

3. **Save emotional state**: The inner life state (emotions + trust) is written to `~/.atrophy/agents/<name>/data/.emotional_state.json` with the current timestamp.

4. **Update user status**: Presence tracking updated (if applicable).

### App Shutdown

`app.on('will-quit')` performs cleanup:
- Unregisters all global shortcuts
- Clears all interval timers (sentinel, queue, deferral)
- Stops wake word listener
- Stops Telegram daemon
- Stops Express server
- Closes all SQLite database connections via `closeAll()`

---

## 5. Between Sessions

Autonomous daemons run on launchd schedules defined in `scripts/agents/<name>/jobs.json`. The companion can view and modify its own schedule via the `manage_schedule` MCP tool. Cron management is handled by `src/main/cron.ts`, which generates launchd plists and calls `launchctl load/unload`.

### Daemon Types

| Daemon | Purpose | Typical Schedule |
|---|---|---|
| **observer** | Reads recent turns, extracts factual observations with confidence scores | Every 15 minutes during active hours |
| **heartbeat** | Evaluates whether to reach out via Telegram based on time since last interaction, active threads, and emotional state | Every 30 minutes during active hours (configurable per agent) |
| **sleep_cycle** | End-of-day processing: decay observation activations, mark stale observations, generate daily reflection note | Once nightly |
| **introspect** | Reviews recent observations, checks which still hold, updates identity snapshot if warranted | Periodic (agent-configured) |
| **evolve** | Self-evolution: reviews conversation history and rewrites system prompt and soul document | Monthly |
| **gift** | Generates a small creative offering (poem, observation, question) and leaves it in Obsidian | Periodic (agent-configured) |

Daemons use `runInferenceOneshot()` for inference (no MCP tools, no session persistence) and write results to the database or Obsidian vault. Messages intended for the GUI are written to the per-agent queue file (`.message_queue.json`), which the main process polls every 10 seconds and forwards to the renderer.

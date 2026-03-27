# Atrophy -- Electron + TypeScript Rewrite

A companion agent system -- voice-enabled, memory-bearing, self-evolving. Rewritten from Python/PyQt5 to Electron/TypeScript/Svelte.

The original Python app lives at `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App/`. Refer to it as the **source repo**. Read its source files when porting logic -- they are the ground truth.

---

## 1. Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Runtime** | Electron 34+ | Desktop app with native menu bar/tray, system notifications, file access |
| **Language** | TypeScript 5.x (strict mode) | Type safety across the entire codebase |
| **UI Framework** | Svelte 5 (runes mode) | Lightweight, fast, minimal boilerplate. The UI is custom -- no component library needed |
| **Build System** | Vite + electron-vite | Fast dev server, HMR for renderer, handles main/preload/renderer split |
| **Package Manager** | pnpm | Fast, deterministic, disk-efficient |
| **Database** | better-sqlite3 | Native SQLite with synchronous API, same schema as Python version |
| **HTTP Client** | undici (Node built-in fetch) | For ElevenLabs TTS, Google APIs, Telegram |
| **Testing** | Vitest + Playwright (e2e) | Same Vite config, fast unit tests |
| **Bundling/Distribution** | electron-builder | DMG/pkg for macOS, auto-update via electron-updater |
| **Linting** | ESLint + Prettier | Standard TS formatting |

### What stays as Python subprocesses

- **MCP servers** (`mcp/memory_server.py`, `mcp/google_server.py`) -- spawned by Claude CLI over stdio. Already copied to this repo.
- **Scripts** (`scripts/agents/companion/run_task.py`, `evolve.py`, `converse.py`, `check_reminders.py`) -- still Python, but now spawned by the in-process cron scheduler (`channels/cron/`) instead of launchd. Output routed through switchboard.
- **Google auth** (`scripts/google_auth.py`) -- OAuth flow with bundled credentials.
- **Claude CLI** (`claude` binary) -- remains the inference engine, spawned as subprocess.

---

## 2. Project Structure

```
src/
  main/                      # Electron main process
    index.ts                 # Entry point, window creation, tray
    config.ts                # Port of config.py (three-tier resolution)
    ipc-handlers.ts          # IPC orchestrator (delegates to ipc/ domain modules)
    ipc/                     # Domain-specific IPC handler modules
      config.ts              # config:reload, config:get, config:apply, config:update
      agents.ts              # agent:list, agent:switch, agent:create, mirror:*, queue:*
      inference.ts           # inference:send, inference:stop, status:*
      audio.ts               # audio:*, tts:*, stt:*, voice-agent:*
      telegram.ts            # telegram:*
      system.ts              # system:*, usage:*, activity:*, cron:*, mcp:*, logs:*, github:*
      window.ts              # window:*, setup:*, avatar:*, artefact:*
      index.ts               # Barrel re-exports
    system-topology.ts       # Pure data layer for system map (buildTopology, handleToggleConnection)
    inference.ts             # Claude CLI subprocess wrapper (port of core/inference.py)
    memory.ts                # SQLite memory layer (port of core/memory.py)
    session.ts               # Session management
    context.ts               # Context assembly (port of core/context.py)
    prompts.ts               # Prompt loading (port of core/prompts.py)
    agency.ts                # Behavioral agency (port of core/agency.py)
    inner-life.ts            # Emotional state engine (port of core/inner_life.py)
    agent-manager.ts         # Multi-agent management (port of core/agent_manager.py)
    sentinel.ts              # Coherence monitoring (port of core/sentinel.py)
    embeddings.ts            # Local embeddings via Transformers.js
    vector-search.ts         # Semantic search (port of core/vector_search.py)
    thinking.ts              # Effort classification (port of core/thinking.py)
    status.ts                # User presence tracking (port of core/status.py)
    notify.ts                # macOS notifications (port of core/notify.py)
    queue.ts                 # Message queue (port of core/queue.py)
    usage.ts                 # Token usage tracking (port of core/usage.py)
    tts.ts                   # Text-to-speech (port of voice/tts.py)
    stt.ts                   # Speech-to-text via whisper.cpp (port of voice/stt.py)
    audio.ts                 # Audio recording management
    wake-word.ts             # Wake word detection (port of voice/wake_word.py)
    channels/                # Message routing and channel adapters
      switchboard.ts         # Central message router - all messages flow through here
      agent-router.ts        # Per-agent filter/queue between switchboard and inference
      telegram/              # Telegram channel adapter
        api.ts               # Bot API helpers (send, edit, download, bot commands)
        daemon.ts            # Per-agent polling, dispatch, streaming display
        formatter.ts         # Message formatting, streaming status, tool result display
        index.ts             # Barrel re-exports
      cron/                  # In-process cron scheduler (replaces launchd)
        scheduler.ts         # Timer management, cron expression parsing
        runner.ts            # Job execution, output capture, envelope creation
        index.ts             # Barrel re-exports
      federation/            # Cross-instance agent communication via Telegram
        config.ts            # Load/validate ~/.atrophy/federation.json, CRUD
        poller.ts            # Per-link Telegram polling, filtering, sandboxed inference dispatch
        sandbox.ts           # Restricted MCP config builder, content sanitization
        transcript.ts        # Append-only JSONL audit trail per link
        index.ts             # Boot/shutdown, switchboard registration
    mcp-registry.ts          # MCP server registry, per-agent config builder
    server.ts                # HTTP API server (port of server.py)
    install.ts               # Login item installer

  preload/
    index.ts                 # contextBridge API exposure

  renderer/
    index.html
    main.ts                  # Svelte mount point
    App.svelte               # Root component
    styles/
      global.css             # Dark theme, scrollbars, typography
    components/
      Window.svelte           # Main window layout
      Transcript.svelte       # Message display + scrolling
      InputBar.svelte         # Floating input bar
      AgentName.svelte        # Top-left agent name with rolodex switching
      ThinkingIndicator.svelte # Pulsing brain during inference
      OrbAvatar.svelte        # Animated orb (procedural, replaces video)
      Timer.svelte            # Countdown timer overlay
      Canvas.svelte           # PIP overlay webview
      Artefact.svelte         # Artefact overlay + gallery
      SystemMap.svelte         # System topology overlay (Cmd+Shift+M)
      Settings.svelte         # Settings modal shell (tab switching, apply/save)
      settings/               # Individual settings tab components
        SettingsTab.svelte     # Main config form
        UsageTab.svelte        # Token usage stats
        ActivityTab.svelte     # Activity log with filtering
        JobsTab.svelte         # Cron job management
        UpdatesTab.svelte      # Bundle version checking
        ConsoleTab.svelte      # Live log streaming
      SetupWizard.svelte      # First-launch wizard
    stores/
      session.ts              # Reactive session state
      agents.ts               # Agent list and switching
      settings.ts             # Config values
      transcript.ts           # Message history
      audio.ts                # TTS playback queue
      emotional-state.ts      # Inner life state

mcp/                         # PYTHON -- bundled, not rewritten
  memory_server.py
  google_server.py

scripts/                     # PYTHON -- standalone scripts (repo-bundled subset)
  google_auth.py
  agents/companion/            # Companion agent scripts + jobs.json
  agents/general_montgomery/   # Montgomery agent scripts + jobs.json
  agents/shared/               # Shared scripts (heartbeat, evolve, observer, etc.)
  # NOTE: Personal/intelligence scripts live in ~/.atrophy/scripts/ (gitignored)

db/
  schema.sql                 # IDENTICAL to source repo

agents/                      # Agent definitions (bundled defaults)
docs/                        # Documentation (synced from source repo)
vendor/whisper.cpp/          # Bundled whisper binary + model
resources/                   # Icons, sounds
```

---

## 3. Module-by-Module Migration Plan

Every module below references its Python source file. **Read the source file before porting** -- it is the ground truth.

### 3.1 `config.py` -> `src/main/config.ts`

Source: `source_repo/config.py`

Three-tier config resolution: env vars -> `~/.atrophy/config.json` -> `agents/<name>/data/agent.json` -> defaults. Export a `Config` class (singleton) with typed properties. `reloadForAgent(name)` method for agent switching. Run `ensureUserData()` on startup.

Key paths:
- `BUNDLE_ROOT` -> `app.isPackaged ? process.resourcesPath : __dirname`
- `USER_DATA` -> `~/.atrophy/` (same as Python)

### 3.2 `main.py` -> `src/main/index.ts`

Source: `source_repo/main.py`

Electron entry point. Two modes:
- **Menu bar** (`--app`): `app.dock.hide()`, `new Tray()`, `Cmd+Shift+Space` toggle. No window on launch.
- **GUI** (`--gui`): Show window immediately with opening line.
- **Server** (`--server`): Launch Express server, no window.

No CLI/text modes -- those stay Python-only.

### 3.3 `core/inference.py` -> `src/main/inference.ts`

Source: `source_repo/core/inference.py` **(MOST COMPLEX MODULE -- read carefully)**

Spawns `claude` CLI via `child_process.spawn()`. Parses streaming JSON lines from stdout. Emits typed events: `TextDelta`, `SentenceReady`, `ToolUse`, `StreamDone`, `StreamError`, `Compacting`.

Key details to port:
- `_build_mcp_config()` -- writes `mcp/config.json` pointing to Python MCP servers
- `_stream_response()` -- the main event loop parsing JSON lines
- Sentence boundary detection regex
- Agency context injection (time awareness, mood, etc.)
- Tool blacklist from agent manifest
- CLI session ID management (`--session-id` flag)
- `--max-turns` for conversation limits

MCP config generation:
```typescript
const mcpConfig = {
  mcpServers: {
    memory: {
      command: pythonPath,
      args: [path.join(bundleRoot, 'mcp', 'memory_server.py')],
      env: {
        COMPANION_DB: dbPath,
        OBSIDIAN_VAULT: obsidianVault,
        AGENT: agentName,
      },
    },
    google: { /* same structure */ },
  },
};
```

Python path detection: check `PYTHON_PATH` env, then `which python3`, then `/usr/local/bin/python3`, `/opt/homebrew/bin/python3`.

### 3.4 `core/memory.py` -> `src/main/memory.ts`

Source: `source_repo/core/memory.py` **(second most complex)**

SQLite via `better-sqlite3`. Same schema (`db/schema.sql` copied verbatim). Same migration logic. Heavy operations (embedding, vector search) in `worker_threads`.

Embedding storage: Python uses `numpy.ndarray.tobytes()`. Use `Float32Array` + `Buffer`:
```typescript
const vectorToBlob = (vec: Float32Array): Buffer => Buffer.from(vec.buffer);
const blobToVector = (blob: Buffer): Float32Array =>
  new Float32Array(blob.buffer, blob.byteOffset, blob.length / 4);
```

### 3.5 `display/window.py` -> Svelte components

Source: `source_repo/display/window.py` **(1500+ lines -- read it all)**

HTML/CSS replaces all PyQt5 widgets. Window structure:
```html
<div class="window">
  <OrbAvatar />
  <AgentName />
  <ThinkingIndicator />
  <Transcript />
  <InputBar />
  <Canvas />
  <Artefact />
  <Timer />
  <Settings />
  <SetupWizard />
</div>
```

Frameless window with vibrancy:
```typescript
new BrowserWindow({
  width: 622, height: 830,
  frame: false, transparent: true,
  vibrancy: 'ultra-dark',
  titleBarStyle: 'hidden',
  trafficLightPosition: { x: -100, y: -100 },
});
```

### 3.6 `display/settings.py` -> `Settings.svelte`

Source: `source_repo/display/settings.py`

Three-tab modal (Settings, Usage, Activity). Form inputs bound to reactive stores. "Apply" updates running config via IPC. "Save" writes to `~/.atrophy/config.json` and `agent.json`.

Includes: agent list with switch/mute/enable, voice sliders, Google auth button, Telegram tokens, tool toggles.

### 3.7 `display/setup_wizard.py` -> `SetupWizard.svelte`

Source: `source_repo/display/setup_wizard.py`

Two-phase flow:
1. Ask user's name
2. AI-driven agent creation (Xan metaprompt)

Service setup: ElevenLabs (paste key), Telegram (bot creation via BotFather, group creation with Topics enabled, topic setup per agent, paste bot token + group ID), Google (OAuth browser flow with service picker checkboxes).

### 3.8 Voice Pipeline

#### TTS (`voice/tts.py` -> `src/main/tts.ts`)
Source: `source_repo/voice/tts.py`

ElevenLabs streaming via `fetch()` with readable stream body. Write chunks to temp MP3. Play via `afplay -r {rate} {path}`. Same prosody tag processing. Three-tier fallback: ElevenLabs -> Fal -> `say`.

#### STT (`voice/stt.py` -> `src/main/stt.ts`)
Source: `source_repo/voice/stt.py`

Write WAV to temp, spawn `vendor/whisper.cpp/build/bin/whisper-cli`. Parse stdout.

#### Audio Recording
Renderer: `navigator.mediaDevices.getUserMedia()` + `AudioWorklet` for 16kHz mono PCM.
Main: accumulate chunks, write WAV on stop, run whisper.

#### Push-to-Talk
Renderer listens for Ctrl keydown/keyup. Sends IPC to main to start/stop recording.

### 3.9 Direct Ports (pure logic, no library deps)

These are straightforward TypeScript translations:

| Python | TypeScript | Source |
|--------|-----------|--------|
| `core/agency.py` | `src/main/agency.ts` | Time awareness, mood, energy |
| `core/inner_life.py` | `src/main/inner-life.ts` | Emotional state with decay |
| `core/agent_manager.py` | `src/main/agent-manager.ts` | Agent discovery, switching |
| `core/sentinel.py` | `src/main/sentinel.ts` | Coherence monitoring |
| `core/thinking.py` | `src/main/thinking.ts` | Effort classification |
| `core/status.py` | `src/main/status.ts` | User presence |
| `core/notify.py` | `src/main/notify.ts` | Notifications |
| `core/prompts.py` | `src/main/prompts.ts` | Prompt loading |
| `core/context.py` | `src/main/context.ts` | Context assembly |
| `channels/telegram.py` | `src/main/channels/telegram/api.ts` | Bot API client |
| `channels/router.py` | Deleted | Replaced by `channels/switchboard.ts` + `channels/agent-router.ts` |

### 3.10 `core/embeddings.py` -> `src/main/embeddings.ts`

Source: `source_repo/core/embeddings.py`

Use `@xenova/transformers` (Transformers.js) for local all-MiniLM-L6-v2 inference. WASM-based, no native deps. Same 384-dim vectors. Run in `worker_threads`. Model downloads to `~/.atrophy/models/`.

### 3.11 `server.py` -> `src/main/server.ts`

Source: `source_repo/server.py`

Express.js in main process. Same endpoints: `/health`, `/chat`, `/chat/stream` (SSE), `/memory/search`, `/memory/threads`, `/session`. Bearer token auth from `~/.atrophy/server_token`.

### 3.12 Display Components

| Python | Svelte | Source |
|--------|--------|--------|
| `display/timer.py` | `Timer.svelte` | Countdown overlay with pause, +1m/+5m |
| `display/canvas.py` | `Canvas.svelte` | PIP webview overlay |
| `display/artefact.py` | `Artefact.svelte` | Full-bleed artefact + gallery |

### 3.13 `scripts/cron.py` -> `src/main/channels/cron/`

Source: `source_repo/scripts/cron.py`

In-process cron scheduler via the switchboard. Jobs are defined in each agent's manifest (`agent.json`) and timed with setTimeout/setInterval. Output is captured and routed through the switchboard as Envelopes. The app is expected to always run in the tray.

### 3.14 Login Item

Python version uses launchd. Electron has built-in `app.setLoginItemSettings()`. Much simpler.

---

## 4. IPC Architecture

### Main Process
All file I/O, SQLite, Claude CLI, TTS synthesis, STT, Telegram, HTTP server, launchd, notifications, tray.

### Renderer Process
All UI rendering (Svelte), audio playback, audio capture, user input, markdown rendering, canvas/webview.

### Preload API

```typescript
const api = {
  // Inference
  sendMessage: (text: string) => ipcRenderer.invoke('inference:send', text),
  onTextDelta: (cb: (text: string) => void) => ...,
  onSentenceReady: (cb: (text: string, audio: string) => void) => ...,
  onToolUse: (cb: (name: string) => void) => ...,
  onDone: (cb: (fullText: string) => void) => ...,

  // Audio
  startRecording: () => ipcRenderer.invoke('audio:start'),
  stopRecording: () => ipcRenderer.invoke('audio:stop'),

  // Agents
  switchAgent: (name: string) => ipcRenderer.invoke('agent:switch', name),
  getAgents: () => ipcRenderer.invoke('agent:list'),

  // Config
  getConfig: () => ipcRenderer.invoke('config:get'),
  updateConfig: (updates: object) => ipcRenderer.invoke('config:update', updates),

  // Setup
  needsSetup: () => ipcRenderer.invoke('setup:check'),
  wizardInference: (text: string) => ipcRenderer.invoke('setup:inference', text),

  // Window
  toggleFullscreen: () => ipcRenderer.invoke('window:toggleFullscreen'),
};
```

---

## 5. CSS Theme

```css
:root {
  --bg: #141418;
  --bg-secondary: rgba(255, 255, 255, 0.04);
  --text-primary: rgba(255, 255, 255, 0.85);
  --text-secondary: rgba(255, 255, 255, 0.5);
  --text-dim: rgba(255, 255, 255, 0.3);
  --accent: rgba(100, 140, 255, 0.3);
  --accent-hover: rgba(100, 140, 255, 0.5);
  --border: rgba(255, 255, 255, 0.1);
  --font-sans: -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui;
  --font-mono: 'SF Mono', 'Fira Code', monospace;
}
```

---

## 6. Build & Distribution

### electron-builder.yml
```yaml
appId: com.atrophy.app
productName: Atrophy
mac:
  category: public.app-category.utilities
  target: [dmg, zip]
  hardenedRuntime: true
  extraResources:
    - from: vendor/whisper.cpp
      to: whisper
    - from: mcp/
      to: mcp
    - from: scripts/
      to: scripts
    - from: agents/
      to: agents
    - from: db/
      to: db
  publish:
    provider: github
```

Native deps: `better-sqlite3` needs `electron-rebuild`. `@xenova/transformers` is WASM, no rebuild.

Auto-update via `electron-updater` + GitHub Releases.

---

## 7. Build Order

### Phase 1: Skeleton
1. Initialize Electron + Vite + Svelte project
2. BrowserWindow with dark background
3. `config.ts` -- read config files
4. `memory.ts` -- SQLite with schema
5. Verify: app launches, reads config, opens DB

### Phase 2: Inference Core
6. `inference.ts` -- spawn claude CLI, parse streaming JSON
7. `session.ts`, `context.ts`, `prompts.ts`
8. MCP config generation
9. Basic IPC: send message, stream response
10. Verify: conversation works through GUI

### Phase 3: Basic GUI
11. `Window.svelte`, `Transcript.svelte`, `InputBar.svelte`
12. `AgentName.svelte`, `ThinkingIndicator.svelte`
13. `OrbAvatar.svelte` -- animated procedural orb
14. Verify: functional chat interface

### Phase 4: Voice
15. `tts.ts` -- ElevenLabs streaming
16. `stt.ts` -- whisper.cpp
17. Audio recording via Web Audio API
18. Push-to-talk
19. Verify: voice conversation works

### Phase 5: Agent System
20. `agent-manager.ts`, `agency.ts`, `inner-life.ts`
21. Agent switching, tray icon, menu bar mode
22. Verify: multi-agent switching

### Phase 6: Display Features
23. `Timer.svelte`, `Canvas.svelte`, `Artefact.svelte`
24. `Settings.svelte`
25. Verify: all overlays work

### Phase 7: Setup & Peripherals
26. `SetupWizard.svelte`
27. `telegram.ts`, `server.ts`, `channels/cron/`
28. `embeddings.ts`, `vector-search.ts`
29. Verify: first-launch works end-to-end

### Phase 8: Polish & Distribution
30. Global shortcuts, agent deferral, wake word
31. Notifications, electron-builder, DMG
32. Verify: distributable .app works

---

## 8. Data Paths

```
~/.atrophy/
  config.json
  server_token
  .env
  agent_states.json
  agents/<name>/
    data/agent.json, memory.db, .emotional_state.json, ...
    data/intelligence.db          # Montgomery's ontology database
    avatar/
    prompts/
  models/
  logs/
  scripts/                        # Personal scripts (not in git)
    agents/shared/                 # Shared intelligence scripts (channel_push, ontology, etc.)
    agents/librarian/              # Librarian agent scripts
  services/
    worldmonitor/                  # Meridian platform fork (Vercel-deployed)
  federation/                      # Federation transcripts and state
    <link-name>/transcript.jsonl   # Per-link audit trail (append-only JSONL)
  federation.json                  # Federation link config (owner-level)
  .google/extra_token.json
```

---

## 9. Key Decisions

1. **MCP servers stay as Python.** Spawned by Claude CLI, not by us.
2. **Scripts stay as Python.** Spawned by the in-process cron scheduler.
3. **Svelte 5 with runes, no component library.** UI is bespoke.
4. **Audio via Web Audio API.** Recording in renderer, whisper in main.
5. **Embeddings via Transformers.js.** WASM, no Python dependency.
6. **One inference process.** Claude CLI runs in main process only.
7. **Cron is in-process.** Jobs run via `channels/cron/` inside the Electron app, not launchd. The app lives in the tray and is always running.

---

## 10. Source Repo Reference

When porting any module, **read the Python source first**:

| Priority | File | Why |
|----------|------|-----|
| 1 | `source_repo/core/inference.py` | Most complex. CLI subprocess, streaming JSON, MCP config. |
| 2 | `source_repo/display/window.py` | 1500+ lines. Full GUI structure. |
| 3 | `source_repo/config.py` | Everything depends on this. |
| 4 | `source_repo/core/memory.py` | SQLite + embeddings + vector search. |
| 5 | `source_repo/mcp/memory_server.py` | 41 tools. Not rewritten but must understand for MCP config. |
| 6 | `source_repo/display/setup_wizard.py` | First-launch flow, service setup. |
| 7 | `source_repo/display/settings.py` | Settings panel structure. |
| 8 | `source_repo/core/context.py` | Context assembly logic. |
| 9 | `source_repo/core/prompts.py` | Prompt loading from Obsidian + fallbacks. |
| 10 | `source_repo/voice/tts.py` | TTS pipeline with prosody tags. |

---

## 11. Documentation

- `docs/` is the source of truth for all project documentation
- Any markdown files created during development (guides, specs, architecture notes, references) go in the appropriate `docs/` subdirectory
- **Specs organisation** - `docs/specs/` has 4 subdirectories:
  - `architecture/` - Living reference docs (CLAUDE-*.md). One per major module. Always kept up to date.
  - `features/` - Standalone feature specs, requirements docs, feature inventories.
  - `decisions/` - Design decisions and proposals. Prefix filenames with `YYYY-MM-DD-` for chronological sorting.
  - `performance/` - Performance checklists, benchmarks, optimization summaries.
- Writes to `docs/` auto-sync to Obsidian at `Projects/Atrophy App Electron/Docs/` (PostToolUse hook)
- On session start, newer Obsidian edits are pulled back into `docs/` automatically
- Manual full sync: `/sync-project-docs`
- Project skills are in Obsidian - use `/project-skills` to discover them
- For full system docs, read `/Users/williamlilley/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind/CLAUDE.md`

---

## 12. Switchboard Architecture

The switchboard is the nervous system. Every message, job output, agent lifecycle event, and MCP operation flows through it as an Envelope. See `docs/specs/architecture/CLAUDE-switchboard-v2.md` for the full spec.

### Address space
- `agent:<name>` - Agent inference engines (xan, companion, mirror, etc.)
- `telegram:<name>` - Telegram bot per agent
- `desktop:<name>` - Desktop GUI
- `cron:<name>` - Cron scheduler per agent (inbound job results)
- `cron:<name>.<job>` - Specific job result source
- `mcp:<server>` - MCP server service
- `system` - System broadcasts
- `agent:*` - Broadcast to all agents

### Directory structure

```
src/main/channels/
  switchboard.ts        # Core routing engine (channel-agnostic)
  agent-router.ts       # Per-agent filter/queue between switchboard and inference
  telegram/             # Telegram channel adapter
    api.ts              # Bot API helpers (send, edit, download, bot commands)
    daemon.ts           # Per-agent polling, dispatch, streaming display
    index.ts            # Barrel re-exports
  cron/                 # Cron channel adapter (in-process scheduler)
    scheduler.ts        # Timer management, reads jobs from manifests
    runner.ts           # Job execution, output capture, envelope creation
    index.ts            # Barrel re-exports
```

### Agent manifest (agent.json) - extended

The manifest is the single source of truth for agent wiring. Beyond identity/voice/display, it now includes:

```json
{
  "channels": {
    "telegram": { "bot_token_env": "XAN_TELEGRAM_BOT_TOKEN", "chat_id_env": "XAN_TELEGRAM_CHAT_ID" },
    "desktop": { "enabled": true }
  },
  "mcp": {
    "include": ["memory", "shell", "github", "google", "worldmonitor"],
    "exclude": [],
    "custom": {}
  },
  "jobs": {
    "morning_brief": { "schedule": "0 7 * * *", "script": "scripts/agents/companion/morning_brief.py", "route_output_to": "self", "notify_via": "telegram" }
  },
  "router": {
    "accept_from": ["*"], "reject_from": [], "max_queue_depth": 20,
    "system_access": true, "can_address_agents": true
  }
}
```

### Cron scheduler

Jobs run in-process via `channels/cron/`. The app is expected to always be running in the tray.

1. On boot, `cronScheduler` reads each agent's manifest `jobs` section and sets up timers
2. When a timer fires, `runner.ts` spawns the script, captures output
3. Output is wrapped in an Envelope: `from: "cron:<agent>.<job>"`, `to: "agent:<agent>"`
4. Agent processes the output through inference and decides what to do (forward to Telegram, store in memory, stay quiet)
5. History of the last 100 runs kept in-memory

### MCP registry (`src/main/mcp-registry.ts`)

Per-agent MCP configuration. Atrophy owns all MCP - nothing comes from `~/.claude/settings.json`.

Three server tiers:
- **Bundled** (`mcp/*.py`) - memory, google, shell, github, worldmonitor, puppeteer
- **External** (host tools) - elevenlabs (uvx), fal (npx). Ship with app, probed at boot.
- **Custom** (`~/.atrophy/mcp/custom/`) - user-created servers with `server.py` + `meta.json`

Key methods:
- **discover()** - scans bundled dir, probes external commands, scans custom dir
- **buildConfigForAgent(name)** - generates per-agent `config.json` from manifest's `mcp.include`
- **buildServerEnv(name, agent)** - resolves per-server env vars (API keys from `~/.atrophy/.env`)
- **activateForAgent / deactivateForAgent** - runtime MCP server management (flags session restart)
- **scaffoldServer(name, description, tools)** - generates new Python MCP servers from a template
- **registerWithSwitchboard()** - registers `mcp:<name>` addresses for service discovery (not data path)

Agents can self-serve MCP via switchboard tools: list servers, activate/deactivate, scaffold new ones.

### Agent creation flow (`create-agent.ts`)

`createAgent(opts)` now does full wiring:
1. Scaffold filesystem (dirs, prompts, soul, heartbeat, db)
2. Write manifest with channels/mcp/jobs/router config
3. Register `agent:<name>` with switchboard
4. Schedule cron jobs via `cronScheduler.registerAgent()`
5. Build per-agent MCP config via `mcpRegistry.buildConfigForAgent()`
6. Announce new agent via system envelope

`wireAgent(name, manifest)` is exported for re-wiring at boot time.

### Boot sequence (`app.ts`)

1. `initDb()` - database
2. `mcpRegistry.discover()` + `registerWithSwitchboard()` - MCP server discovery
3. `discoverAgents()` + `wireAgent()` per agent - switchboard registration, cron, MCP
4. `cronScheduler.start()` - start all job timers
5. `startDaemon()` - Telegram polling
6. `switchboard.startQueuePolling()` - MCP queue file polling
7. Periodic `switchboard.writeStateForMCP()` - state dump for Python MCP servers

### Agent-to-agent communication
Agents can message each other via switchboard MCP tools:
- `send_message` - send to a specific address
- `broadcast` - send to all agents (Xan only)
- `query_status` - check recent switchboard activity
- `route_response` - redirect response to a different channel

### Adding a new channel
1. Create `channels/<name>/` with `api.ts`, `daemon.ts`, `index.ts`
2. In `daemon.ts`: create Envelopes from inbound messages, route via `switchboard.route()`
3. Register outbound handler: `switchboard.register('<name>:<agent>', handler)`
4. The agent-router handles filtering and response routing automatically

### Federation - cross-instance agent communication

Agents from different Atrophy instances can communicate on behalf of their owners via shared Telegram groups. See `docs/superpowers/specs/2026-03-27-federation-design.md` for the full spec.

**How it works:** Two owners each add their agent's bot to a shared Telegram group. The federation poller polls the group, filters messages by remote bot username and @ mention, and dispatches sandboxed inference with restricted MCP tools. Responses are sent back to the group with @-mention addressing.

**Address space:** `federation:<link-name>` (e.g. `federation:sarah-companion`)

**Config:** `~/.atrophy/federation.json` - owner-level, not agent-level. Agents cannot create or modify federation links. Links can be created manually or via invite tokens (`atrophy-fed-` prefix, base64url + HMAC, 24hr expiry).

```json
{
  "version": 1,
  "links": {
    "sarah-companion": {
      "remote_bot_username": "sarah_companion_bot",
      "telegram_group_id": "-1001234567890",
      "local_agent": "xan",
      "trust_tier": "chat",
      "enabled": true,
      "muted": false,
      "description": "Sarah's companion agent",
      "rate_limit_per_hour": 20
    }
  }
}
```

**Trust tiers:**
- `chat` - no MCP servers, text response only
- `query` - memory (read-only)
- `delegate` - memory (read/write). Calendar/action differentiation is future work.

**Security model (4 layers):**
1. Sandboxed inference - shell, filesystem, GitHub, puppeteer permanently blocked
2. Quarantined memory - federation messages tagged `source: federation:<link>`, sanitized, prefixed `[EXTERNAL]` on recall
3. No federation config tools - no MCP tool can read/write federation.json
4. System prompt preamble - soft boundary instructing the agent to be cautious

**Message filtering (7 layers):** Remote bot only, @ mention required, no commands, text only, ignore edits, staleness window (1hr), rate limiting (60/hr inbound)

**Transcript:** Append-only JSONL at `~/.atrophy/federation/<link>/transcript.jsonl`. Viewable in Settings > Federation tab.

**Session isolation:** Each link gets its own CLI session ID (`federation-<link>`) and process key.

**Known v1 limitations:**
- `delegate` and `query` tiers have identical MCP access (memory only). Per-tool read/write differentiation requires MCP-level filtering not yet implemented.

---

## 13. Meridian Eye Intelligence Platform

Meridian Eye is the defence org's intelligence platform, deployed at `worldmonitor.atrophy.app`. A fork of the open-source WorldMonitor project, rebranded as MERIDIAN - Defence Intelligence. It combines a channel system, cinematic briefing layer, 6,326-object knowledge graph, 294 harvested articles, and 31 autonomous cron jobs into a self-sustaining intelligence pipeline. See `docs/specs/architecture/CLAUDE-meridian.md` for the full living architecture reference.

Status note: this section mixes shipped platform capabilities with local Phase 1 UI work and longer-horizon roadmap items. Use `docs/specs/architecture/CLAUDE-meridian.md` as the source of truth for what is shipped now versus only implemented locally or still target-state.

### Architecture

- **Platform:** Vercel-deployed fork of WorldMonitor (vanilla TypeScript + Preact, deck.gl/MapLibre maps, 60+ Edge Functions)
- **State:** Upstash Redis for channel state, briefings, commissions
- **Fork repo:** `~/.atrophy/services/worldmonitor/` (GitHub: `wlilley93/worldmonitor`)
- **Auth:** `X-Channel-Key` header with `CHANNEL_API_KEY` from `~/.atrophy/.env`
- **Domain:** `worldmonitor.atrophy.app` (CNAME via GoDaddy -> Vercel)

### Channel system

10 agent channels, each a curated view of the intelligence picture. The site opens on Montgomery's combined picture by default. Channels hold map state (center, zoom, bearing, pitch, layers, markers, regions), briefings (title, summary, markdown body, sources), alert level (normal/elevated/critical), and feed filters. Agent scripts push channel state via `channel_push.py`. The cron runner passes `CHANNEL_API_KEY` as an environment variable to all scripts.

API routes: `api/channels/list` (GET), `api/channels/[name]` (GET/PUT), `api/channels/[name]/briefing` (PUT), `api/channels/[name]/map` (PUT), `api/commissions` (GET/POST), `api/commissions/[id]` (PUT).

### Ontology (intelligence.db)

The knowledge graph at `~/.atrophy/agents/general_montgomery/data/intelligence.db`. Current scale:

| Table | Count | Description |
|-------|-------|-------------|
| objects | 6,326 | Typed entities across 11 types |
| links | 7,218 | Typed relationships with provenance (20 link types) |
| properties | 28,988 | Key-value pairs with confidence, source, temporal validity |
| changelog | 24,681 | Full audit trail of all ontology mutations |
| articles | 294 | Harvested from 7 RSS feeds + browser scraping |
| vectors | 5,059 | TF-IDF 384-dim embeddings for semantic search |

Object types: location (1,782), organization (1,519), event (1,017), document (469), platform (465), person (448), country (263), faction (184), financial_instrument, region, indicator.

Link types (20): leads, commands, member_of, located_at, operates, deployed_to, allied_with, opposes, funds, arms, sanctions, participated_in, targets, mediates, trades_with, subsidiary_of, borders, controls, hosts, produced_by.

The ontology auto-grows via three pipelines:
1. **WorldMonitor ingestion** - `ontology_ingest.py` processes API responses (8 typed ingestors for flights, ACLED, AIS, GPS jamming, OREF, thermal, news, economic data)
2. **Article harvesting** - `article_harvest.py` pulls from 7 RSS feeds (ICG, Atlantic Council, MEE, Al-Monitor, Carnegie, Stimson, War on the Rocks, Foreign Policy, Foreign Affairs) + browser scraper for blocked sources. `article_to_ontology.py` extracts entities and relationships via Claude Haiku.
3. **Daily expansion** - `ontology_expand.py` uses Haiku to enrich sparse objects and grow coverage

### Vector search and research context

TF-IDF 384-dim vectors across 5,059 documents (articles + briefs + ontology descriptions). `vectorize_articles.py` runs every 4 hours. `research_context.py` assembles relevant articles + briefs + objects for brief generation via semantic retrieval.

### Briefing layer

The full pipeline: WorldMonitor feeds -> ontology ingestion -> article harvesting -> vectorization -> research_context assembly -> brief generation (grounded in context) -> channel push to platform. Each brief triggers prediction extraction, timeline updates, relationship extraction, entity linking, and optional red team review.

### MCP ontology tools

7 tools in the `ontology` action group of `mcp/memory_server.py`:

| Tool | Description |
|------|-------------|
| `ontology.search` | Full-text search across objects by name, type, country, or query |
| `ontology.get_object` | Full dossier - properties, links, changelog, related briefs |
| `ontology.get_network` | Ego network - all first-hop relationships |
| `ontology.find_connections` | Path-finding between two objects (1-2 hops) |
| `ontology.recent_events` | Latest events by type, region, or time window |
| `ontology.country_profile` | Full country dossier - government, economy, military |
| `ontology.statistics` | Ontology counts, coverage metrics |

### Intelligence capabilities (14 systems)

| # | System | Description |
|---|--------|-------------|
| 1 | Prediction Ledger | Predictions extracted from briefs, 30-day auto-review cycle |
| 2 | Cross-Agent Synthesis | Nightly convergence report identifying cross-domain patterns |
| 3 | Source Health Dashboard | 39 sources monitored every 6 hours for availability and freshness |
| 4 | Entity Resolution | Haiku-driven deduplication, alias population, brief-entity linking |
| 5 | Temporal Situation Tracking | Timeline entries per active conflict with trajectory assessment |
| 6 | Automated Relationship Extraction | Hourly extraction of typed relationships from briefs via Haiku |
| 7 | Commission Portal | Two-way sync between intelligence.db and platform for gap tasking |
| 8 | Systematic Red Team Review | Four-part adversarial challenge on high-priority briefs |
| 9 | Live Data Layer | Channel-driven activation of 70+ WorldMonitor data layers |
| 10 | Briefing Audio | ElevenLabs TTS briefing narration |
| 11 | Agent Performance Metrics | Monthly review across 7 categories |
| 12 | Geofencing | 8 watch zones with haversine distance alerting |
| 13 | Structured Intelligence Products | 8 templates (SITREP, FLASH, WARNING, INTSUM, PROFILE, WEEKLY_DIGEST, ASSESSMENT, SYNTHESIS) |
| 14 | Multi-Source Verification | Cross-reference claims against multiple sources, assign corroboration score |

### 31 cron jobs

**Montgomery:** worldmonitor_fast (15m), worldmonitor_medium (45m), worldmonitor_slow (4h), dashboard_refresh (15m), dashboard_brief (4h), article_harvest (4h), vectorize (4h), ontology_expand (daily 03:00), ship_track_alert (30m), flash_report (15m), weekly_digest (Mon 07:00), weekly_conflicts (Mon 08:00), parliamentary_monitor (weekdays 08:00), competitor_scan (weekdays 09:00), process_audit (1st Mon 10:00).

**Shared:** source_health (6h), cross_agent_synthesis (daily 02:00), commission_sync (30m), geofence_check (15m), relationship_extract (hourly), prediction_review (monthly), agent_metrics (monthly), entity_enrichment (daily 04:00).

**Research Fellows:** rf_uk_defence (Thu 06:00), rf_european_security (Thu 06:00), rf_russia_ukraine (weekdays 06:30), rf_gulf_iran_israel (1st of month 07:00), rf_indo_pacific (Fri 06:00).

**Other agents:** librarian/entity_resolve (hourly), sigint_analyst/sigint_cycle (15m), economic_io/economic_scan (4h).

### Personal scripts

Intelligence scripts containing operational data live in `~/.atrophy/scripts/` (gitignored). The cron runner checks `~/.atrophy/scripts/agents/<path>` first, falling back to the bundle. `PYTHONPATH` includes `~/.atrophy/scripts/` so personal scripts can import shared modules. 20+ scripts including ontology_ingest, article_harvest, article_to_ontology, vectorize_articles, research_context, channel_push, and all intelligence capability scripts.

### Site redesign (specced, not yet built)

Full 1,051-line spec at `docs/superpowers/specs/2026-03-27-meridian-site-redesign.md`. Vision: game-style 3D globe with cinematic briefings (letterbox bars, camera sweeps, unit animations, voice narration), fog of war, unit figurines, territory control, convergence rings, entity glow, time scrub, and an in-map chat interface.

### Related docs

- `docs/specs/architecture/CLAUDE-meridian.md` - Living architecture reference (schema, data flow, cron schedule, MCP tools, file locations)
- `docs/meridian-platform.md` - Platform reference
- `docs/ontology-reference.md` - Ontology reference
- `docs/superpowers/specs/2026-03-27-worldmonitor-integration-design.md` - Platform design spec
- `docs/superpowers/specs/2026-03-27-meridian-ontology-design.md` - Ontology schema spec
- `docs/superpowers/specs/2026-03-27-meridian-improvements-spec.md` - 14 capability specs
- `docs/superpowers/specs/2026-03-27-meridian-site-redesign.md` - Site redesign vision

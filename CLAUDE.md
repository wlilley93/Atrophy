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
- **Scripts** (`scripts/agents/companion/run_task.py`, `evolve.py`, `converse.py`, `check_reminders.py`) -- standalone launchd jobs.
- **Google auth** (`scripts/google_auth.py`) -- OAuth flow with bundled credentials.
- **Claude CLI** (`claude` binary) -- remains the inference engine, spawned as subprocess.

---

## 2. Project Structure

```
src/
  main/                      # Electron main process
    index.ts                 # Entry point, window creation, tray
    config.ts                # Port of config.py (three-tier resolution)
    ipc-handlers.ts          # IPC channel registrations
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
    telegram.ts              # Telegram Bot API client (port of channels/telegram.py)
    telegram-daemon.ts       # Telegram polling daemon using Topics mode (1 topic per agent)
    router.ts                # Message routing (legacy - not used by Telegram daemon)
    server.ts                # HTTP API server (port of server.py)
    cron.ts                  # launchd job management (port of scripts/cron.py)
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
      Settings.svelte         # Settings modal with tabs
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

scripts/                     # PYTHON -- standalone launchd jobs
  google_auth.py
  cron.py
  agents/companion/

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
| `channels/telegram.py` | `src/main/telegram.ts` | Bot API client |
| `channels/router.py` | `src/main/router.ts` | Message routing (legacy - no longer used by daemon) |

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

### 3.13 `scripts/cron.py` -> `src/main/cron.ts`

Source: `source_repo/scripts/cron.py`

launchd plist generation. Use `plist` npm package for XML. Write to `~/Library/LaunchAgents/`, run `launchctl load/unload`.

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
27. `telegram.ts`, `server.ts`, `cron.ts`
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
    avatar/
    prompts/
  models/
  logs/
  .google/extra_token.json
```

---

## 9. Key Decisions

1. **MCP servers stay as Python.** Spawned by Claude CLI, not by us.
2. **Scripts stay as Python.** Standalone launchd jobs.
3. **Svelte 5 with runes, no component library.** UI is bespoke.
4. **Audio via Web Audio API.** Recording in renderer, whisper in main.
5. **Embeddings via Transformers.js.** WASM, no Python dependency.
6. **One inference process.** Claude CLI runs in main process only.

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

## 12. Switchboard Architecture (v1.3.2+)

All messages flow through a central switchboard (`src/main/switchboard.ts`). Every message is wrapped in an Envelope with `from`, `to`, `text`, `type`, `priority`, and `replyTo` fields.

### Addresses
- `telegram:<agent>` - Telegram bot for an agent
- `desktop:<agent>` - Desktop GUI for an agent
- `agent:<agent>` - Agent's inference engine
- `system` - System-level broadcasts
- `agent:*` - Broadcast to all agents

### Key modules
- `switchboard.ts` - Singleton message router with handler registry
- `agent-router.ts` - Per-agent filter (accept/reject rules, queue depth, system access)
- Telegram daemon creates envelopes and routes through switchboard
- Desktop GUI records through switchboard for observability

### Agent-to-agent communication
Agents can message each other via the `switchboard` MCP tool:
- `send_message` - send to a specific address
- `broadcast` - send to all agents (Xan only)
- `query_status` - check recent switchboard activity
- `route_response` - redirect response to a different channel

### Adding a new channel
1. Register handler with `switchboard.register(address, handler)`
2. Create envelopes from inbound messages
3. Handle outbound envelopes in the handler

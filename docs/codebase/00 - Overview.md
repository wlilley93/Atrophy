# Architecture Overview

The Atrophied Mind is an Electron/TypeScript companion agent system. It uses the Claude CLI for inference (streaming JSON output via subprocess), maintains persistent memory in SQLite via `better-sqlite3`, speaks with synthesised voice, and runs autonomous background processes via macOS launchd. The UI is built with Svelte 5 (runes mode). The system is designed as a desktop-native application that acts as a persistent, voice-enabled companion with long-term memory and self-evolving personality.

## Technology Stack

Each technology was chosen to balance developer productivity, runtime performance, and compatibility with the original Python codebase. The stack prioritises native desktop integration over web portability, since the app is macOS-only.

| Layer | Choice |
|-------|--------|
| Runtime | Electron 34+ |
| Language | TypeScript 5.x (strict mode) |
| UI Framework | Svelte 5 (runes mode) |
| Build System | Vite + electron-vite |
| Package Manager | pnpm |
| Database | better-sqlite3 (synchronous, WAL mode) |
| Embeddings | @xenova/transformers (WASM, all-MiniLM-L6-v2, 384-dim) |
| Distribution | electron-builder + electron-updater |

Electron provides native menu bar and tray support, system notifications, and direct filesystem access. TypeScript strict mode catches type errors across the entire main/preload/renderer boundary. Svelte 5 with runes was selected for its minimal boilerplate and fast rendering - the UI is fully custom with no component library. The build system uses electron-vite to handle the three-process split (main, preload, renderer) with HMR in development. Database access is synchronous via better-sqlite3, matching the original Python implementation's behavior and avoiding callback complexity in the main process.

## Agent System

The system is agent-aware. Switching agents changes the entire identity - all paths, configuration, database, voice settings, and personality are scoped per-agent. The `src/main/create-agent.ts` module scaffolds new agents programmatically, generating directory structures, manifests, prompt files, and database schemas. Each agent's system prompt includes a `## Capabilities` section with labeled strengths (e.g. PRESENCE, MEMORY, RESEARCH) - used for self-awareness, Telegram routing/bidding, and deferral decisions.

Two root paths drive the system, and all other paths derive from them:

- **`BUNDLE_ROOT`** - where the code lives (`process.resourcesPath` when packaged, project root in dev)
- **`USER_DATA`** (`~/.atrophy/`) - runtime state, memory DBs, generated avatar content, user config

Agent definitions (manifest + prompts) are searched in `USER_DATA` first, then `BUNDLE_ROOT`, so users can install custom agents by dropping a folder into `~/.atrophy/agents/<name>/`. This two-tier resolution means bundled defaults can be overridden without modifying the application bundle.

The following directory tree shows the complete layout of an agent's files. Bundle-side files define the agent's identity and prompts, while user-side files hold runtime state that accumulates over time.

```
agents/<name>/                     # In BUNDLE_ROOT (repo)
  prompts/                         # all prompt/identity documents
    system_prompt.md               # personality and behavioral instructions
    soul.md                        # core identity document (self-editable via evolve)
    heartbeat.md                   # outreach evaluation checklist
  data/
    agent.json                     # manifest: display name, voice config, heartbeat, telegram
  avatar/
    source/face.png                # source face image for video generation

~/.atrophy/agents/<name>/          # In USER_DATA (runtime)
  data/
    memory.db                      # per-agent SQLite database
    .emotional_state.json
    .user_status.json
    .message_queue.json
    .opening_cache.json
    .canvas_content.html
    .identity_review_queue.json
  avatar/
    loops/                         # generated loop segments (loop_*.mp4)
    ambient_loop.mp4               # master ambient loop (concatenated from segments)
```

---

## Startup Sequence

The application boots through a carefully ordered initialization sequence in `src/main/index.ts`. Each step depends on the previous ones completing successfully - for example, IPC handlers cannot be registered until the config and database are ready. The exact initialization order in `app.whenReady()` is:

1. **Parse CLI arguments** - determine mode from `process.argv`: `--app` (menu bar), `--server` (headless API), or GUI (default).
2. **Hide dock** - if menu bar or server mode, call `app.dock?.hide()`. Otherwise set the dock icon via `getAppIcon()` resized to 128x128.
3. **`ensureUserData()`** - create `~/.atrophy/`, `~/.atrophy/agents/`, `~/.atrophy/logs/`, `~/.atrophy/models/` directories. Write an empty `config.json` if missing. Run `migrateAgentData()` to copy runtime data files from bundle to user data (skipping `agent.json` manifests and files that already exist).
4. **`getConfig()`** - instantiate the Config singleton. This loads `~/.atrophy/.env` into `process.env`, reads `~/.atrophy/config.json`, resolves the VERSION file, detects the Python path, resolves the default agent, and computes all derived paths.
5. **`initDb()`** - open (or create) the SQLite database for the current agent at `~/.atrophy/agents/<name>/data/memory.db`.
6. **Set `currentAgentName`** - store the active agent name for deferral tracking.
7. **Log startup** - print version, agent name, and database path.
8. **`registerIpcHandlers()`** - register all `ipcMain.handle()` channels (see IPC registry below).
9. **`registerAudioHandlers()`** - register audio capture IPC (start/stop recording, chunk receiving). Takes a getter function for the main window reference.
10. **`registerWakeWordHandlers()`** - register wake word detection IPC.
11. **`setPlaybackCallbacks()`** - wire TTS playback events to IPC and wake word pause/resume. When TTS starts playing, the wake word listener pauses to avoid detecting the agent's own speech. When the audio queue empties, the listener resumes.
12. **Resume last active agent** - read `getLastActiveAgent()`. If different from the default, call `config.reloadForAgent()` and `initDb()` again. This ensures the app resumes with whichever agent was last used, even if the default agent is different.
13. **Start sentinel timer** - `setInterval` every 5 minutes. Runs `runCoherenceCheck()` if a session is active with a CLI session ID and system prompt.
14. **Start queue poller** - `setInterval` every 10 seconds. Calls `drainQueue()` and forwards messages to the renderer via `queue:message`.
15. **Start deferral watcher** - `setInterval` every 2 seconds. Calls `checkDeferralRequest()`, validates against anti-loop protection (no self-deferral, max 3 deferrals per 60s), and sends `deferral:request` to the renderer if valid.
16. **Mode-specific startup**:
    - **Server mode**: parse `--port` argument (default 5000), call `startServer(port)`, return (no window).
    - **GUI/App mode**: call `createWindow()`.
17. **Initialize auto-updater** - call `initAutoUpdater(mainWindow)` (5-second delayed check).
18. **Menu bar setup** (if `--app`):
    - `createTray()` - create system tray icon.
    - Register global shortcut `Cmd+Shift+Space` to toggle window visibility.

---

## Window Creation

The `createWindow()` function creates a frameless, transparent `BrowserWindow` with macOS vibrancy. The window uses `hiddenInset` title bar styling so the native traffic lights (close/minimize/fullscreen) sit inside the content area at position (14, 14). The transparent background and `ultra-dark` vibrancy create the distinctive dark, glassy appearance. The following configuration shows the exact parameters used.

```typescript
{
  width: config.WINDOW_WIDTH,           // default 622
  height: config.WINDOW_HEIGHT,         // default 830
  minWidth: 360,
  minHeight: 480,
  titleBarStyle: 'hiddenInset',
  trafficLightPosition: { x: 14, y: 14 },
  vibrancy: 'ultra-dark',
  visualEffectState: 'active',
  backgroundColor: '#00000000',         // transparent
  show: false,                          // hidden until ready-to-show
  webPreferences: {
    preload: path.join(__dirname, '..', 'preload', 'index.mjs'),
    sandbox: false,
    contextIsolation: true,
    nodeIntegration: false,
    webSecurity: false,
  },
}
```

The renderer is loaded from `ELECTRON_RENDERER_URL` (dev server) or the built `index.html` (production). The window shows on `ready-to-show` unless in menu bar mode, which starts hidden so the user can summon it with the keyboard shortcut. On close, the `mainWindow` reference is nulled so the lifecycle handlers know to recreate it if needed.

Context isolation is enabled with `nodeIntegration: false` for security - the renderer cannot access Node.js APIs directly. All communication flows through the preload script's `contextBridge`. The `sandbox: false` setting is required because the preload script uses `ipcRenderer` directly. Web security is disabled to allow loading local file resources in the renderer.

---

## Tray Setup and Menu Structure

The tray icon appears in the macOS menu bar when the app runs in `--app` mode. The `createTray()` function selects the icon through a preference cascade, checking for a hand-crafted brain icon first and falling back to a procedurally generated orb if none is found.

1. Check for `menubar_brain@2x.png` in the icons directory, then `menubar_brain.png`.
2. If found, create a native image and set it as a template image (auto-adapts to macOS light/dark mode).
3. If not found, fall back to a procedural orb icon via `getTrayIcon('active')`.

The context menu provides two actions. "Show" brings the main window to the foreground and focuses it. "Quit" terminates the application via `app.quit()`.

| Item | Action |
|------|--------|
| Show | Show and focus the main window |
| Quit | `app.quit()` |

Click behavior on the tray icon toggles visibility: if visible, hide; if hidden, show and focus. This creates a quick-access pattern where the user clicks the brain icon to toggle the conversation window without using the keyboard shortcut.

The `updateTrayState()` function updates the procedural orb icon to reflect state (active, muted, idle, away) but skips updates when using the hand-crafted template image, since template images adapt to the system appearance automatically.

---

## IPC Channel Registry

All IPC channels are registered in `src/main/index.ts` via `registerIpcHandlers()`. The channels are grouped by functional area below. Each channel uses Electron's `ipcMain.handle()` for request-response communication (renderer invokes, main responds with a promise) or `webContents.send()` for one-way events pushed from the main process to the renderer. This separation ensures the renderer never blocks on long-running operations - it sends a request and receives streamed events as they become available.

### Configuration

The configuration channels let the renderer read and update settings at runtime. The `config:update` handler classifies keys into agent-specific keys (voice, heartbeat, telegram, display, disabled tools) and user-level keys, routing each to the correct file.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `config:get` | invoke | Returns a flat object of all config values for the renderer |
| `config:update` | invoke | Accepts key-value updates, routes to user config or agent config based on key |

Agent-specific keys are saved to the agent's `agent.json`, while user-level keys go to the global `config.json`. This means voice settings travel with the agent but inference settings stay global.

### Agent Management

These channels handle agent discovery, switching, and state management. The `agent:switch` channel performs a full context switch - ending the current session, reloading config, resetting the MCP config cache, reinitializing the database, and clearing the audio queue. The `agent:cycle` channel enables the rolodex-style agent switching in the UI.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `agent:list` | invoke | Returns array of agent name strings |
| `agent:listFull` | invoke | Returns full agent info objects (name, display_name, description, role) |
| `agent:switch` | invoke | End current session, reload config for new agent, reset MCP config, reinit DB, clear audio queue. Returns `{agentName, agentDisplayName}` |
| `agent:cycle` | invoke | Cycle to next/previous agent by direction (+1/-1). Returns next agent info |
| `agent:getState` | invoke | Get muted/enabled state for a named agent |
| `agent:setState` | invoke | Set muted/enabled state for a named agent |

### Inference

The inference channels implement the core conversation loop. The `inference:send` channel is the main entry point - it marks the user as active, ensures a session exists, loads the system prompt, records the user's turn, detects mood shifts, and starts streaming inference. The remaining channels push events from the main process to the renderer as the Claude CLI produces output.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `inference:send` | invoke | Main inference entry point. Marks user active, ensures session, loads system prompt, records turn, detects mood, streams inference. Routes events to renderer |
| `inference:stop` | invoke | Kill the active Claude CLI subprocess |
| `inference:textDelta` | send (main->renderer) | Partial text token |
| `inference:sentenceReady` | send (main->renderer) | Complete sentence for display |
| `inference:toolUse` | send (main->renderer) | Tool invocation notification |
| `inference:compacting` | send (main->renderer) | Context window compression detected |
| `inference:done` | send (main->renderer) | Full response text |
| `inference:error` | send (main->renderer) | Error message |

### TTS Playback

TTS playback events flow from main to renderer so the UI can synchronize visual indicators (like the orb animation) with audio output. The `tts:started` and `tts:done` events carry a sentence index that maps to the order sentences were emitted during inference. The `tts:queueEmpty` event signals that all queued audio has finished, which also triggers wake word listener resumption.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `tts:started` | send (main->renderer) | Audio playback started for sentence index |
| `tts:done` | send (main->renderer) | Audio playback completed for sentence index |
| `tts:queueEmpty` | send (main->renderer) | All queued audio has finished playing |

### Audio Capture

Audio capture uses a split architecture. The renderer captures microphone input via the Web Audio API and streams raw PCM chunks to the main process. The main process accumulates chunks, writes a WAV file on stop, and runs whisper.cpp for transcription.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `audio:start` | invoke | Start recording |
| `audio:stop` | invoke | Stop recording, return transcription |
| `audio:chunk` | send (renderer->main) | Raw audio buffer chunk |

### Wake Word

Wake word detection uses the same audio capture pipeline but with different parameters. The main process sends `wakeword:start` to tell the renderer to begin ambient listening with a specified chunk duration, and `wakeword:stop` to cease. Audio chunks flow back to the main process for fast whisper transcription.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `wakeword:start` | send (main->renderer) | Start ambient listening with chunk duration |
| `wakeword:stop` | send (main->renderer) | Stop ambient listening |
| `wakeword:chunk` | send (renderer->main) | Audio buffer chunk for wake word detection |

### Window Control

Window control channels handle standard window management operations. In menu bar mode, the `window:close` channel hides the window rather than closing it, preserving the running session. In GUI mode, it performs a standard close.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `window:toggleFullscreen` | invoke | Toggle fullscreen on main window |
| `window:minimize` | invoke | Minimize main window |
| `window:close` | invoke | Hide (menu bar mode) or close (GUI mode) the main window |

### Setup Wizard

The setup wizard channels power the first-launch experience. The `setup:check` channel reads the `setup_complete` flag from `config.json`. The `setup:inference` channel runs a conversational AI flow using Xan's metaprompt to guide the user through designing a new agent. The `setup:saveSecret` channel writes API keys to the `.env` file, and `setup:createAgent` scaffolds a complete agent from the wizard's output.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `setup:check` | invoke | Returns true if setup wizard should run (checks `setup_complete` in config.json) |
| `setup:inference` | invoke | Run wizard inference with Xan metaprompt. Returns full response text |
| `setup:saveSecret` | invoke | Save an API key to `~/.atrophy/.env` via `saveEnvVar()` |
| `setup:createAgent` | invoke | Create a new agent from wizard config via `createAgent()` |

### Opening Line

This channel retrieves the agent's configured opening line, falling back to a default if none is set. The opening line is displayed when the user first opens the conversation window or switches agents, giving the agent a distinct first impression.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `opening:get` | invoke | Returns agent's opening line or default "Ready. Where are we?" |

### Usage and Activity

These channels expose analytics data for the Settings panel's Usage and Activity tabs. Both accept optional filters for time range and result limits. The data is aggregated across all agents, allowing the user to see total interaction patterns.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `usage:all` | invoke | Get usage data for all agents, optional days filter |
| `activity:all` | invoke | Get activity data for all agents, optional days and limit filters |

### Cron Jobs

Cron channels provide control over the launchd-managed background jobs. The `cron:list` channel returns all scheduled jobs with their current state. The `cron:toggle` channel enables or disables all cron jobs at once, useful for temporarily silencing autonomous behavior.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `cron:list` | invoke | List all scheduled launchd jobs |
| `cron:toggle` | invoke | Enable or disable all cron jobs |

### Telegram Daemon

The Telegram daemon channels control the in-process message poller. Starting the daemon acquires an instance lock (preventing duplicate pollers) and begins polling the Telegram Bot API for new messages. Stopping it releases the lock and clears the poll timer.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `telegram:startDaemon` | invoke | Start the Telegram polling daemon |
| `telegram:stopDaemon` | invoke | Stop the Telegram polling daemon |

### HTTP Server

The HTTP server channels manage the optional REST API. The server provides endpoints for external tools to interact with the companion - sending messages, searching memory, and checking health. It uses bearer token authentication from `~/.atrophy/server_token`.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `server:start` | invoke | Start the HTTP API server on optional port |
| `server:stop` | invoke | Stop the HTTP API server |

### Memory

The memory search channel exposes the hybrid vector + keyword search system to the renderer. This powers the memory search feature in the Settings panel, allowing users to explore what the agent remembers.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `memory:search` | invoke | Vector search across memory, returns results |

### Avatar

The avatar channel resolves video loop paths for the animated orb display. It checks for a colour-specific clip first, then falls back to the master ambient loop. Returns null if no video assets exist, in which case the renderer uses the procedural orb animation instead.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `avatar:getVideoPath` | invoke | Resolve avatar video loop path by colour and clip name. Falls back to ambient_loop.mp4 |

### Login Item

These channels manage macOS login item registration. When enabled, the app launches automatically at login using Electron's built-in `app.setLoginItemSettings()`, which is simpler than the launchd approach used by the Python version.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `install:isEnabled` | invoke | Check if app is registered as a login item |
| `install:toggle` | invoke | Enable or disable login item registration |

### Auto-Updater

The auto-updater channels implement the full update lifecycle. The main process checks GitHub Releases for new versions, downloads updates, and can quit-and-install on command. Status events flow to the renderer so the UI can show progress bars and release notes. Downloads are manual (not automatic) to avoid surprising the user with unexpected restarts.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `updater:check` | invoke | Check for updates |
| `updater:download` | invoke | Download available update |
| `updater:quitAndInstall` | invoke | Quit app and install downloaded update |
| `updater:available` | send (main->renderer) | Update available with version and release notes |
| `updater:not-available` | send (main->renderer) | No update available |
| `updater:progress` | send (main->renderer) | Download progress (percent, bytesPerSecond, transferred, total) |
| `updater:downloaded` | send (main->renderer) | Update downloaded with version info |
| `updater:error` | send (main->renderer) | Update error message |

### Agent Deferral

Agent deferral enables mid-conversation handoffs between agents. When an agent decides another agent is better suited for a question, it writes a deferral request file. The main process detects this, validates it against anti-loop protection, and notifies the renderer to begin the transition. The `deferral:complete` channel performs the actual switch - suspending the current session, switching agents, and resuming the target's session.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `deferral:complete` | invoke | Complete deferral: suspend current session, switch to target agent, resume target session. Returns new agent info |
| `deferral:request` | send (main->renderer) | Deferral request detected (target, context, user_question) |

### Agent Message Queues

Background daemons (cron jobs, Telegram daemon) communicate with the GUI through file-based message queues. These channels let the renderer drain pending messages for specific agents or all agents at once. The `queue:message` event is pushed by the 10-second queue poller when it finds pending messages.

| Channel | Direction | Description |
|---------|-----------|-------------|
| `queue:drainAgent` | invoke | Drain pending messages for a specific agent |
| `queue:drainAll` | invoke | Drain pending messages for all agents |
| `queue:message` | send (main->renderer) | Background job message (text, source) |

---

## Preload API

The preload script (`src/preload/index.ts`) exposes a typed `AtrophyAPI` interface via `contextBridge.exposeInMainWorld('atrophy', api)`. The renderer accesses all main process functionality through `window.atrophy`. This is the only communication surface between the renderer and main processes - there are no other IPC paths.

The API uses two patterns for the two directions of communication:

- **`ipcRenderer.invoke(channel, ...args)`** for request-response calls (returns a Promise). Used when the renderer needs data or wants to trigger an action with a result.
- **`createListener(channel)`** for event subscriptions (returns an unsubscribe function). Used for streaming events pushed from the main process.

The `createListener` helper wraps `ipcRenderer.on()` and returns a cleanup function that calls `ipcRenderer.removeListener()`. This prevents memory leaks from forgotten listeners - Svelte components call the unsubscribe function in their `onDestroy` lifecycle hook.

A generic `on(channel, cb)` method is also exposed for subscribing to arbitrary channels not covered by the typed API. This provides an escape hatch for new features that have not yet been added to the `AtrophyAPI` interface, but typed methods are preferred for compile-time safety.

---

## Process Lifecycle

The application manages four lifecycle events that handle window creation, cleanup, and platform-specific behavior.

### App Ready
The `app.whenReady()` handler runs the full startup sequence described above. This is where the entire application initializes - from parsing arguments through to creating the window and starting background timers.

### Window Closed
On `window-all-closed`, the app quits on non-macOS platforms. On macOS, the app stays running (standard macOS behavior), allowing the user to reopen the window via the dock icon or tray. This is important for menu bar mode where the window is frequently shown and hidden.

### Activate
On `activate` (clicking the dock icon), if no window exists a new one is created; otherwise the existing window is shown. This handles the macOS convention where clicking a dock icon should always bring the app to the foreground.

### Will Quit
The `will-quit` handler performs cleanup in a specific order to avoid resource leaks and ensure graceful shutdown. Each step depends on the previous ones - for example, database connections must close last since other cleanup steps may write final state.

1. Unregister all global shortcuts
2. Clear the sentinel timer (5-minute coherence checks)
3. Clear the queue poller timer (10-second message drain)
4. Clear the deferral watcher timer (2-second deferral checks)
5. Stop the wake word listener
6. Stop the Telegram daemon
7. Stop the HTTP server
8. Close all SQLite database connections

### Background Timers

Three `setInterval` timers run continuously in the main process, each serving a distinct purpose. They are started during the boot sequence and cleared during shutdown.

| Timer | Interval | Purpose |
|-------|----------|---------|
| `sentinelTimer` | 5 minutes | Run coherence check on the active session. If the session ID changes (e.g. from re-anchoring), update the session |
| `queueTimer` | 10 seconds | Drain the file-based message queue and forward messages to the renderer |
| `deferralTimer` | 2 seconds | Check for `.deferral_request.json` files, validate against anti-loop protection (no self-deferral, max 3 deferrals per 60s), and notify the renderer |

The sentinel timer runs coherence checks by sending a diagnostic prompt to the active CLI session and evaluating the response for signs of confusion or drift. If degradation is detected, it can re-anchor the session by starting a new CLI session with fresh context. The queue timer bridges the gap between background daemons (which write to JSON files on disk) and the GUI (which needs IPC events). The deferral timer watches for agent handoff requests at a high frequency (2 seconds) to minimize latency when an agent decides to defer to another.

---

## IPC Architecture

Electron enforces a strict process separation between main and renderer, with the preload script acting as a controlled bridge. This architecture ensures the renderer never touches the filesystem or spawns processes directly, which is both a security measure and an architectural constraint that keeps all state management in the main process.

| Process | Responsibilities |
|---------|-----------------|
| **Main** (`src/main/`) | All file I/O, SQLite, Claude CLI subprocess, TTS synthesis, STT, Telegram, HTTP server, launchd, notifications, tray, agent management |
| **Renderer** (`src/renderer/`) | All UI rendering (Svelte 5), audio playback, audio capture (Web Audio API), user input, markdown rendering, canvas/webview |
| **Preload** (`src/preload/`) | `contextBridge` API exposure - typed IPC bridge between main and renderer |

The renderer never touches the filesystem or spawns processes. All heavy lifting goes through `ipcMain.handle()` / `ipcRenderer.invoke()` calls defined in `src/main/index.ts` and exposed via `src/preload/index.ts`. This means every feature that requires system access must be implemented as an IPC handler in the main process, with a corresponding method in the preload API.

## Operational Modes

The application supports three operational modes, selected at launch via command-line flags. All modes share the same inference pipeline, memory system, and MCP tools - the difference is in how the user interacts with the system.

| Mode | Flag | Input | Output | Voice | Avatar |
|------|------|-------|--------|-------|--------|
| App | `--app` (primary) | Floating input bar / chat overlay | Electron window (menu bar) | TTS | Orb animation |
| GUI | `--gui` | Floating input bar | Electron window (Dock) | TTS | Orb animation |
| Server | `--server` | HTTP POST | JSON/SSE | No | No |

`--app` is the primary mode - hides from the Dock via `app.dock.hide()`, lives in the menu bar as a `Tray`, and starts silent. The window is summoned with `Cmd+Shift+Space` or by clicking the tray icon. GUI mode is identical except the app appears in the Dock with a visible window on launch. Server mode exposes REST endpoints secured by auto-generated bearer token via a raw Node `http` server, with no window or UI at all - useful for integration with external tools and automation.

## First Launch

On first GUI/app launch, `SetupWizard.svelte` runs a conversational setup flow before the main window appears. The wizard is controlled by the `setup_complete` flag in `~/.atrophy/config.json` - once set to `true`, the wizard never runs again. The flow collects API keys (ElevenLabs for voice, Telegram for messaging), runs an AI-driven agent creation conversation using Xan's metaprompt, and optionally sets up Google OAuth for calendar and email integration. The result is a fully configured agent ready for conversation.

## Data Flow

The following diagram traces a single user message through the complete pipeline, from input to audio output. Each arrow represents a function call or IPC message, and each module is responsible for a distinct stage of processing.

```
INPUT (Voice/Text/GUI)
  -> src/main/session.ts (lifecycle)
  -> src/main/context.ts (system prompt assembly)
  -> src/main/thinking.ts (effort classification)
  -> src/main/inference.ts (Claude CLI streaming subprocess)
    <-> mcp/memory_server.py (MCP tools, JSON-RPC over stdio)
  -> Streaming events: TextDelta, SentenceReady, ToolUse, StreamDone
    -> src/main/tts.ts (parallel sentence TTS)
    -> renderer via IPC (token-by-token rendering)
  -> src/main/memory.ts (async turn write + embed)
```

The key performance insight is that TTS synthesis happens in parallel with inference streaming. As soon as a complete sentence is detected, it is sent to the TTS engine while the next sentence is still being generated. This pipelining minimizes the gap between the agent "thinking" and the user hearing the response.

## Inference

The system shells out to the `claude` CLI binary with `--output-format stream-json`. This routes through a Max subscription (no API cost). Persistent CLI sessions are maintained via `--resume`, meaning the Claude context window carries across companion restarts - the agent remembers what was discussed earlier in the same session without needing to re-inject context.

MCP tools are exposed via two servers: `mcp/memory_server.py` (memory, agency, communication - 41 tools) and `mcp/google_server.py` (Gmail + Google Calendar - 10 tools). Both use JSON-RPC 2.0 over stdio. The Google server is only loaded when Google is configured (checked via `gws` CLI auth status). All Google API responses are treated as untrusted and wrapped with injection markers to prevent prompt injection attacks through email content or calendar descriptions.

The inference layer dynamically builds an agency context block on every turn via `buildAgencyContext()`, injecting time awareness, emotional state, behavioral signals, cross-agent awareness, thread summaries, and security notes. A tool blacklist array prevents destructive commands (`rm -rf`, `sudo`, `sqlite3*memory.db`, etc.) from being executed, and per-agent disabled tools from the manifest are also excluded.

Sentence splitting uses a primary regex for `.!?` boundaries and a clause-boundary fallback (`,;-`) when the buffer exceeds 120 characters, preventing long sentences from blocking TTS. This two-tier approach ensures natural-sounding speech breaks without cutting sentences awkwardly.

## Memory

The memory system uses a three-layer SQLite architecture (via `better-sqlite3` with WAL mode and foreign keys), with each layer serving a different temporal purpose:

1. **Episodic** - Raw turns with embeddings. The permanent log of everything said, never deleted.
2. **Semantic** - Session summaries, conversation threads (active/dormant/resolved). Generated at session end, injected at session start.
3. **Identity** - Observations (bi-temporal facts with confidence and activation decay), identity snapshots. Updated deliberately through MCP tools and background daemons.

Plus auxiliary tables: bookmarks, tool call audit, heartbeat log, coherence checks, entities, and entity relations. These support features like the knowledge graph, audit trail, and heartbeat decision logging.

Search is hybrid: cosine similarity (vector, 0.7 weight) + BM25 (keyword, 0.3 weight). Embeddings are 384-dim from `all-MiniLM-L6-v2` via `@xenova/transformers` (WASM, no native dependencies), computed asynchronously on write so they never block the conversation. Connection pooling via `Map<string, Database>` maintains one connection per agent database, reused across calls to avoid the overhead of repeatedly opening and closing connections.

See [04 - Memory Architecture](04%20-%20Memory%20Architecture.md) for the full schema.

## Voice

The voice pipeline spans multiple modules and processes, handling both speech-to-text input and text-to-speech output with low-latency pipelining.

- **STT**: whisper.cpp spawned as subprocess (`vendor/whisper.cpp/build/bin/whisper-cli`). Full transcription for conversation, fast mode (<200ms, 5s timeout, 2 threads) for wake word detection. The fast mode trades accuracy for speed, which is acceptable since it only needs to detect the agent's name.
- **TTS**: Three-tier fallback - ElevenLabs v3 streaming, Fal, macOS `say`. Prosody tags in the agent's output (`[whispers]`, `[warmly]`, `[firmly]`) dynamically adjust voice parameters via `PROSODY_MAP`. Each tier is tried in order, ensuring voice output even when premium services are unavailable.
- **Pipeline**: Sentences are synthesised in parallel as they stream from inference, played sequentially via an audio queue in the main process. This minimises latency between the agent "thinking" and the user hearing the response, while maintaining correct sentence ordering.
- **Voice Call**: Hands-free continuous conversation mode (`src/main/call.ts`). Energy-based VAD (threshold 0.015 RMS, 1.5s silence to end utterance) with a listen-transcribe-infer-speak loop. Audio chunks arrive from the renderer via IPC. The VAD thresholds were tuned for typical desktop microphone input.
- **Wake Word**: Ambient listening (`src/main/wake-word.ts`). Low-energy RMS threshold (0.005), fast whisper transcription to detect the agent's name. Runs continuously when enabled, pausing during TTS playback to avoid false triggers.

See [02 - Voice Pipeline](02%20-%20Voice%20Pipeline.md).

## Agent Deferral

Agents can hand off mid-conversation to another agent via the `defer_to_agent` MCP tool. This enables a multi-agent experience where each agent contributes its speciality. The process involves seven steps with built-in safety mechanisms:

1. Current agent writes a `.deferral_request.json` file with target, context, and user question.
2. Main process polls for deferral requests every 2 seconds.
3. Anti-loop protection validates the request: no self-deferral, max 3 deferrals per 60-second window. This prevents infinite deferral chains where agents keep handing off to each other.
4. Current agent's session is suspended in memory (`suspendAgentSession()`), preserving the CLI session ID and turn history.
5. Agent switch occurs with an iris wipe transition in the UI, providing visual feedback that a handoff is happening.
6. Target agent receives the context and responds.
7. Original agent can be resumed later via `resumeAgentSession()`, restoring the previous CLI session.

## Per-Agent Message Queue

Background daemons communicate with the GUI via a file-based message queue (`src/main/queue.ts`). This bridge is necessary because cron jobs and the Telegram daemon run as separate processes that cannot send IPC messages directly to the Electron renderer.

File locking uses `O_CREAT | O_EXCL` (`wx` flag) for atomic creation - only one process can create the lock file. Stale locks (older than 30s) are detected and removed automatically, preventing deadlocks if a process crashes while holding a lock. The synchronous sleep between lock retries uses `Atomics.wait()` on a `SharedArrayBuffer` for efficiency. The main process polls agent queues every 10 seconds and delivers pending messages to the renderer.

## Autonomy

Background daemons run via macOS launchd, managed by `src/main/cron.ts`. Each daemon is a standalone Python script or Electron entry point that runs on a schedule, performs a task, and optionally delivers output through the message queue or Telegram.

| Daemon | Schedule | Purpose |
|--------|----------|---------|
| `observer` | Every 15 min | Extract facts from recent turns |
| `heartbeat` | Every 30 min | Evaluate unprompted outreach via Telegram |
| `sleep_cycle` | 3:00 AM daily | Process day's sessions, update threads, decay activations |
| `morning_brief` | 7:00 AM daily | Generate weather/news/threads brief |
| `introspect` | Periodic (agent-configured) | Deep self-reflection, journal entry |
| `evolve` | Monthly (1st, 3:00 AM) | Revise prompts/soul.md and prompts/system_prompt.md |
| `gift` | Monthly (28th, 12:11 AM) | Unprompted gift note, self-rescheduling |
| `voice_note` | Random (2-8 hours, self-rescheduling) | Spontaneous Telegram voice note - inference, TTS, OGG Opus |
| `telegram_daemon` | Continuous (launchd) | Poll Telegram, route messages, dispatch to agents sequentially |

The `telegram_daemon` uses instance locking (`O_EXLOCK` on macOS, pid-check fallback) to ensure only one poller runs. Message routing is two-tier: explicit match (commands, @mentions, name prefix) then LLM routing agent. The `evolve` daemon is particularly notable - it allows the agent to rewrite its own system prompt and soul document over time, creating genuine personality evolution.

See [07 - Scripts and Automation](07%20-%20Scripts%20and%20Automation.md) and [06 - Channels](06%20-%20Channels.md).

## Obsidian Integration

The companion optionally reads from and writes to an Obsidian vault, providing a rich note-taking and knowledge management layer. The `OBSIDIAN_AVAILABLE` flag in `config.ts` is `true` if the vault directory exists on disk. When unavailable, all agent notes, skills, and workspace operations fall back to `~/.atrophy/agents/<name>/` - the system works fully without Obsidian, just with a simpler note storage backend.

Prompt resolution uses four tiers (see `src/main/prompts.ts`): Obsidian vault - local skills (`~/.atrophy/agents/<name>/skills/`) - user prompts - bundle defaults. This layered resolution means prompts can be customised at any level without modifying the others, and Obsidian vault prompts take highest priority.

Notes created by the companion get YAML frontmatter (type, created, updated, agent, tags). Obsidian features like `[[wiki links]]`, `#tags`, inline Dataview fields, and reminder syntax are supported. This makes the companion's notes first-class citizens in the user's knowledge management system, searchable and linkable alongside the user's own notes.

## Auto-Update

The auto-update system uses `electron-updater` with GitHub Releases as the update source. It checks for new versions on launch after a 5-second delay to avoid slowing down startup. Downloads are manual (`autoDownload = false`) so the user explicitly chooses when to update. Installs happen on app quit (`autoInstallOnAppQuit = true`), ensuring the user is never interrupted mid-conversation. Update status is forwarded to the renderer via IPC events (`updater:available`, `updater:progress`, `updater:downloaded`, `updater:error`), allowing the Settings panel to show download progress and release notes.

## Key Files

The following table lists every significant source file in the project, organized by functional area. Each file maps to a distinct responsibility - there is minimal overlap between modules.

| Path | Purpose |
|------|---------|
| `src/main/index.ts` | Entry point. App/GUI/Server mode selection, IPC registration, tray, timers |
| `src/main/config.ts` | Central configuration. Three-tier resolution (env - config.json - agent.json - defaults) |
| `src/main/inference.ts` | Claude CLI subprocess, streaming JSON, MCP config, agency context |
| `src/main/memory.ts` | SQLite data layer - sessions, turns, summaries, observations, entities |
| `src/main/agent-manager.ts` | Multi-agent discovery, switching, state persistence, deferral |
| `src/main/context.ts` | System prompt assembly with skill injection and agent roster |
| `src/main/prompts.ts` | Four-tier skill/prompt resolution (Obsidian - local skills - user prompts - bundle) |
| `src/main/session.ts` | Session lifecycle, turn tracking, soft limits |
| `src/main/tts.ts` | Three-tier TTS with prosody tags and audio queue |
| `src/main/stt.ts` | whisper.cpp subprocess for speech-to-text |
| `src/main/call.ts` | Hands-free voice call with VAD |
| `src/main/wake-word.ts` | Ambient wake word detection |
| `src/main/telegram.ts` | Telegram Bot API client (send/receive) |
| `src/main/telegram-daemon.ts` | Single-process Telegram poller with sequential dispatch |
| `src/main/router.ts` | Message router (explicit match - LLM routing agent) |
| `src/main/server.ts` | HTTP API server (Node http, bearer auth, SSE streaming) |
| `src/main/cron.ts` | launchd control plane - plist generation, install/uninstall |
| `src/main/queue.ts` | File-based message queue with atomic locking |
| `src/main/agency.ts` | Behavioral signals - time awareness, mood, energy, drift |
| `src/main/inner-life.ts` | Structured emotional model with decay |
| `src/main/sentinel.ts` | Mid-session coherence monitoring |
| `src/main/thinking.ts` | Effort classification for adaptive inference |
| `src/main/icon.ts` | SVG-based orb rendering for tray and app icons |
| `src/main/updater.ts` | Auto-update via electron-updater + GitHub Releases |
| `src/main/create-agent.ts` | Agent scaffolding - directories, manifest, prompts, database |
| `src/renderer/components/Window.svelte` | Main window layout |
| `src/renderer/components/SetupWizard.svelte` | First-launch conversational setup |
| `src/renderer/components/Settings.svelte` | Settings modal with tabs |
| `src/preload/index.ts` | contextBridge API - typed IPC bridge |
| `mcp/memory_server.py` | MCP tool server (41 tools, JSON-RPC over stdio) |
| `mcp/google_server.py` | Google MCP server (Gmail + Calendar, 10 tools) |
| `scripts/cron.py` | launchd plist management (Python, standalone) |
| `scripts/agents/<name>/` | Per-agent daemon scripts and job definitions |
| `db/schema.sql` | Database schema (three-layer memory) |

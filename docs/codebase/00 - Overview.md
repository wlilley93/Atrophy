# Architecture Overview

The Atrophied Mind is an Electron/TypeScript companion agent system. It uses the Claude CLI for inference (streaming JSON output via subprocess), maintains persistent memory in SQLite via `better-sqlite3`, speaks with synthesised voice, and runs autonomous background processes via macOS launchd. The UI is built with Svelte 5 (runes mode).

## Technology Stack

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

## Agent System

The system is agent-aware. Switching agents changes the entire identity - all paths, configuration, database, voice settings, and personality are scoped per-agent. The `src/main/create-agent.ts` module scaffolds new agents programmatically. Each agent's system prompt includes a `## Capabilities` section with labeled strengths (e.g. PRESENCE, MEMORY, RESEARCH) - used for self-awareness, Telegram routing/bidding, and deferral decisions.

Two root paths drive the system:
- **`BUNDLE_ROOT`** - where the code lives (`process.resourcesPath` when packaged, project root in dev)
- **`USER_DATA`** (`~/.atrophy/`) - runtime state, memory DBs, generated avatar content, user config

Agent definitions (manifest + prompts) are searched in `USER_DATA` first, then `BUNDLE_ROOT`, so users can install custom agents by dropping a folder into `~/.atrophy/agents/<name>/`.

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

## IPC Architecture

Electron enforces a strict process separation:

| Process | Responsibilities |
|---------|-----------------|
| **Main** (`src/main/`) | All file I/O, SQLite, Claude CLI subprocess, TTS synthesis, STT, Telegram, HTTP server, launchd, notifications, tray, agent management |
| **Renderer** (`src/renderer/`) | All UI rendering (Svelte 5), audio playback, audio capture (Web Audio API), user input, markdown rendering, canvas/webview |
| **Preload** (`src/preload/`) | `contextBridge` API exposure - typed IPC bridge between main and renderer |

The renderer never touches the filesystem or spawns processes. All heavy lifting goes through `ipcMain.handle()` / `ipcRenderer.invoke()` calls defined in `src/main/index.ts` and exposed via `src/preload/index.ts`.

## Operational Modes

| Mode | Flag | Input | Output | Voice | Avatar |
|------|------|-------|--------|-------|--------|
| App | `--app` (primary) | Floating input bar / chat overlay | Electron window (menu bar) | TTS | Orb animation |
| GUI | `--gui` | Floating input bar | Electron window (Dock) | TTS | Orb animation |
| Server | `--server` | HTTP POST | JSON/SSE | No | No |

`--app` is the primary mode - hides from the Dock via `app.dock.hide()`, lives in the menu bar as a `Tray`, starts silent. All modes share the same inference pipeline, memory system, and MCP tools. Server mode exposes REST endpoints secured by auto-generated bearer token via a raw Node `http` server.

## First Launch

On first GUI/app launch, `SetupWizard.svelte` runs a conversational setup flow (API keys, agent creation, service configuration) before the main window appears. Controlled by the `setup_complete` flag in `~/.atrophy/config.json`.

## Data Flow

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

## Inference

The system shells out to the `claude` CLI binary with `--output-format stream-json`. This routes through a Max subscription (no API cost). Persistent CLI sessions are maintained via `--resume`, meaning the Claude context window carries across companion restarts.

MCP tools are exposed via two servers: `mcp/memory_server.py` (memory, agency, communication - 41 tools) and `mcp/google_server.py` (Gmail + Google Calendar - 10 tools). Both use JSON-RPC 2.0 over stdio. The Google server is only loaded when Google is configured (checked via `gws` CLI auth status). All Google API responses are treated as untrusted and wrapped with injection markers.

The inference layer dynamically builds an agency context block on every turn via `buildAgencyContext()`, injecting time awareness, emotional state, behavioral signals, cross-agent awareness, thread summaries, and security notes. A tool blacklist array prevents destructive commands (`rm -rf`, `sudo`, `sqlite3*memory.db`, etc.).

Sentence splitting uses a primary regex for `.!?` boundaries and a clause-boundary fallback (`,;-`) when the buffer exceeds 120 characters, preventing long sentences from blocking TTS.

## Memory

Three-layer SQLite architecture (via `better-sqlite3` with WAL mode and foreign keys):

1. **Episodic** - Raw turns with embeddings. The permanent log.
2. **Semantic** - Session summaries, conversation threads (active/dormant/resolved).
3. **Identity** - Observations (bi-temporal facts with confidence and activation decay), identity snapshots.

Plus auxiliary tables: bookmarks, tool call audit, heartbeat log, coherence checks, entities, and entity relations.

Search is hybrid: cosine similarity (vector, 0.7 weight) + BM25 (keyword, 0.3 weight). Embeddings are 384-dim from `all-MiniLM-L6-v2` via `@xenova/transformers` (WASM, no native dependencies), computed asynchronously on write. Connection pooling via `Map<string, Database>` - one connection per agent database, reused across calls.

See [04 - Memory Architecture](04%20-%20Memory%20Architecture.md) for the full schema.

## Voice

- **STT**: whisper.cpp spawned as subprocess (`vendor/whisper.cpp/build/bin/whisper-cli`). Full transcription for conversation, fast mode (<200ms, 5s timeout, 2 threads) for wake word detection.
- **TTS**: Three-tier fallback - ElevenLabs v3 streaming, Fal, macOS `say`. Prosody tags in the agent's output (`[whispers]`, `[warmly]`, `[firmly]`) dynamically adjust voice parameters via `PROSODY_MAP`.
- **Pipeline**: Sentences are synthesised in parallel as they stream from inference, played sequentially via an audio queue in the main process. This minimises latency between the agent "thinking" and the user hearing the response.
- **Voice Call**: Hands-free continuous conversation mode (`src/main/call.ts`). Energy-based VAD (threshold 0.015 RMS, 1.5s silence to end utterance) with a listen-transcribe-infer-speak loop. Audio chunks arrive from the renderer via IPC.
- **Wake Word**: Ambient listening (`src/main/wake-word.ts`). Low-energy RMS threshold (0.005), fast whisper transcription to detect the agent's name.

See [02 - Voice Pipeline](02%20-%20Voice%20Pipeline.md).

## Agent Deferral

Agents can hand off mid-conversation to another agent via the `defer_to_agent` MCP tool. The process:

1. Current agent writes a `.deferral_request.json` file with target, context, and user question.
2. Main process polls for deferral requests every 2 seconds.
3. Anti-loop protection validates the request: no self-deferral, max 3 deferrals per 60-second window.
4. Current agent's session is suspended in memory (`suspendAgentSession()`).
5. Agent switch occurs with an iris wipe transition in the UI.
6. Target agent receives the context and responds.
7. Original agent can be resumed later via `resumeAgentSession()`.

## Per-Agent Message Queue

Background daemons communicate with the GUI via a file-based message queue (`src/main/queue.ts`). File locking uses `O_CREAT | O_EXCL` (`wx` flag) for atomic creation - only one process can create the lock file. Stale locks (older than 30s) are detected and removed automatically. The main process polls agent queues every 10 seconds and delivers pending messages.

## Autonomy

Background daemons run via macOS launchd, managed by `src/main/cron.ts`:

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

The `telegram_daemon` uses instance locking (`O_EXLOCK` on macOS, pid-check fallback) to ensure only one poller runs. Message routing is two-tier: explicit match (commands, @mentions, name prefix) then LLM routing agent.

See [07 - Scripts and Automation](07%20-%20Scripts%20and%20Automation.md) and [06 - Channels](06%20-%20Channels.md).

## Obsidian Integration

The companion optionally reads from and writes to an Obsidian vault. The `OBSIDIAN_AVAILABLE` flag in `config.ts` is `true` if the vault directory exists on disk. When unavailable, all agent notes, skills, and workspace operations fall back to `~/.atrophy/agents/<name>/` - the system works fully without Obsidian.

Prompt resolution uses four tiers (see `src/main/prompts.ts`): Obsidian vault - local skills (`~/.atrophy/agents/<name>/skills/`) - user prompts - bundle defaults. MCP tools provide `read_note`, `write_note`, `search_notes`, and `prompt_journal` for vault interaction.

Notes created by the companion get YAML frontmatter (type, created, updated, agent, tags). Obsidian features like `[[wiki links]]`, `#tags`, inline Dataview fields, and reminder syntax are supported.

## Auto-Update

`electron-updater` checks GitHub Releases for new versions on launch (after a 5-second delay). Downloads are manual (`autoDownload = false`), installs happen on app quit (`autoInstallOnAppQuit = true`). Update status is forwarded to the renderer via IPC events (`updater:available`, `updater:progress`, `updater:downloaded`, `updater:error`).

## Key Files

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

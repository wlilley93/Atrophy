# Atrophy Codebase Documentation

This directory contains comprehensive documentation for the Atrophy Electron application - a companion agent system with voice interaction, persistent memory, and autonomous background processes.

## Recent Changes (2026-03-26)

### Features
- **Auto Telegram Chat ID Management** - Agents automatically detect group membership changes
- **Org/Agent Management UI** - Full CRUD for organizations and agents in Settings
- **Session Suspension** - Deferrals now suspend (not end) sessions for later resumption

### Bug Fixes
| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `switchboard.ts` | TOCTOU race on MCP queue | Atomic rename-then-restore |
| 2 | `tts.ts` | Unhandled WriteStream error | Added error listener + reject path |
| 3 | `scheduler.ts` | Stale closure in delay | Re-evaluate delay from `job.nextRun` |
| 4 | `scheduler.ts` | Disabled job rescheduled | Added disabled guard |
| 5 | `inference.ts` | Dead process ref leak | Clean up `_allProcesses` |
| 6 | `memory.ts` + `app.ts` | FD accumulation | Added `closeForPath()` |

### New Files
- `scripts/agents/shared/credentials.py` - Shared credential loading
- `docs/specs/decisions/2026-03-26-auto-telegram-chat-id-management.md`
- `docs/specs/decisions/2026-03-26-bug-scan-and-avatar-investigation.md`

---

## Documentation Structure

```
docs/codebase/
├── README.md                    # This file - architecture overview
├── FILE_INDEX.md                # Complete file index with status
├── files/                       # Detailed file-by-file documentation
│   ├── src/
│   │   ├── main/                # Main process modules
│   │   │   ├── index.md         # Entry point
│   │   │   ├── bootstrap.md     # Hot bundle loader
│   │   │   ├── app.md           # Main process implementation
│   │   │   ├── config.md        # Configuration system
│   │   │   ├── memory.md        # SQLite data layer
│   │   │   ├── inference.md     # Claude CLI streaming
│   │   │   ├── tts.md           # Text-to-speech
│   │   │   ├── stt.md           # Speech-to-text
│   │   │   └── ...              # (50+ module docs)
│   │   │   ├── ipc/             # IPC handlers
│   │   │   ├── channels/        # Channel system
│   │   │   └── jobs/            # Background jobs
│   │   ├── preload/             # Preload scripts
│   │   └── renderer/            # Svelte components & stores
│   ├── db/                      # Database schema
│   └── mcp/                     # MCP servers
└── archive/                     # Legacy overview documents
```

## Architecture Overview

Atrophy is an Electron/TypeScript companion agent system. It uses the Claude CLI for inference (streaming JSON output via subprocess), maintains persistent memory in SQLite via `better-sqlite3`, speaks with synthesised voice, and runs autonomous background processes via macOS launchd. The UI is built with Svelte 5 (runes mode).

### Technology Stack

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

### Core Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Atrophy Architecture                          │
│                                                                   │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────────┐   │
│  │  Renderer   │◀───▶│   Preload   │◀───▶│  Main Process   │   │
│  │  (Svelte 5) │ IPC │   Bridge    │ IPC │  (Node.js)      │   │
│  └─────────────┘     └─────────────┘     └────────┬────────┘   │
│                                                    │             │
│                    ┌───────────────────────────────┼──────┐     │
│                    │                               │      │     │
│                    ▼                               ▼      ▼     │
│            ┌───────────────┐              ┌───────────────┐    │
│            │  Claude CLI   │              │  SQLite DB    │    │
│            │  (inference)  │              │  (memory)     │    │
│            └───────────────┘              └───────────────┘    │
│                    │                               │             │
│                    ▼                               ▼             │
│            ┌───────────────┐              ┌───────────────┐    │
│            │  ElevenLabs   │              │  Embeddings   │    │
│            │  (TTS)        │              │  (WASM)       │    │
│            └───────────────┘              └───────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Agent System

The system is agent-aware. Switching agents changes the entire identity - all paths, configuration, database, voice settings, and personality are scoped per-agent.

**Two root paths:**
- **`BUNDLE_ROOT`** - where the code lives (`process.resourcesPath` when packaged, project root in dev)
- **`USER_DATA`** (`~/.atrophy/`) - runtime state, memory DBs, generated avatar content, user config

**Agent directory structure:**
```
agents/<name>/                     # In BUNDLE_ROOT (repo)
  prompts/
    system_prompt.md               # personality and behavioral instructions
    soul.md                        # core identity document
    heartbeat.md                   # outreach evaluation checklist
  data/
    agent.json                     # manifest: display name, voice config

~/.atrophy/agents/<name>/          # In USER_DATA (runtime)
  data/
    memory.db                      # per-agent SQLite database
    .emotional_state.json
    .user_status.json
  avatar/
    loops/                         # generated loop segments
    ambient_loop.mp4               # master ambient loop
```

## Module Categories

### Entry Points
- [`index.md`](files/src/main/index.md) - Main process entry point
- [`bootstrap.md`](files/src/main/bootstrap.md) - Hot bundle loader
- [`app.md`](files/src/main/app.md) - Main process implementation

### Configuration & Foundation
- [`config.md`](files/src/main/config.md) - Three-tier configuration system
- [`logger.md`](files/src/main/logger.md) - Leveled logging
- [`session.md`](files/src/main/session.md) - Session lifecycle
- [`status.md`](files/src/main/status.md) - User presence tracking
- [`install.md`](files/src/main/install.md) - Login item management

### Data Layer
- [`memory.md`](files/src/main/memory.md) - SQLite three-layer memory
- [`vector-search.md`](files/src/main/vector-search.md) - Hybrid vector + keyword search
- [`embeddings.md`](files/src/main/embeddings.md) - Transformers.js WASM embeddings
- [`queue.md`](files/src/main/queue.md) - Thread-safe message queue

### Inference & Context
- [`inference.md`](files/src/main/inference.md) - Claude CLI streaming
- [`context.md`](files/src/main/context.md) - Context assembly
- [`prompts.md`](files/src/main/prompts.md) - Four-tier prompt resolution
- [`opening.md`](files/src/main/opening.md) - Opening line generation
- [`artifact-parser.md`](files/src/main/artifact-parser.md) - Inline artifact extraction

### Behavioral Agency
- [`agency.md`](files/src/main/agency.md) - Pattern detection for context
- [`thinking.md`](files/src/main/thinking.md) - Effort classification
- [`sentinel.md`](files/src/main/sentinel.md) - Coherence monitoring

### Inner Life System
- [`inner-life.md`](files/src/main/inner-life.md) - Emotional state engine

### Voice Pipeline
- [`tts.md`](files/src/main/tts.md) - Text-to-speech
- [`stt.md`](files/src/main/stt.md) - Speech-to-text
- [`audio.md`](files/src/main/audio.md) - Audio bridge
- [`wake-word.md`](files/src/main/wake-word.md) - Wake word detection
- [`call.md`](files/src/main/call.md) - Voice call mode
- [`voice-agent.md`](files/src/main/voice-agent.md) - Hybrid voice agent

### Agent Management
- [`agent-manager.md`](files/src/main/agent-manager.md) - Agent discovery
- [`create-agent.md`](files/src/main/create-agent.md) - Agent scaffolding

### IPC Handlers
- [`handlers.md`](files/src/main/ipc/handlers.md) - IPC orchestrator
- [`config.md`](files/src/main/ipc/config.md) - Configuration handlers
- [`agents.md`](files/src/main/ipc/agents.md) - Agent management
- [`inference.md`](files/src/main/ipc/inference.md) - Inference handlers
- [`audio.md`](files/src/main/ipc/audio.md) - Audio handlers
- [`system.md`](files/src/main/ipc/system.md) - System handlers
- [`telegram.md`](files/src/main/ipc/telegram.md) - Telegram handlers

### Channels & MCP
- [`mcp-registry.md`](files/src/main/mcp-registry.md) - MCP server registry
- [`switchboard.md`](files/src/main/channels/switchboard.md) - Message switchboard

### Updates & Assets
- [`bundle-updater.md`](files/src/main/bundle-updater.md) - Hot bundle downloader
- [`updater.md`](files/src/main/updater.md) - DMG auto-updater
- [`avatar-downloader.md`](files/src/main/avatar-downloader.md) - Avatar assets

### Services & Analytics
- [`server.md`](files/src/main/server.md) - HTTP API server
- [`usage.md`](files/src/main/usage.md) - Usage analytics

## Startup Sequence

1. **bootstrap.ts** - Detect hot bundle, load app.js
2. **ensureUserData()** - Create directory structure
3. **getConfig()** - Load configuration singleton
4. **initDb()** - Open SQLite database
5. **registerIpcHandlers()** - Register IPC handlers
6. **registerAudioHandlers()** - Register audio IPC
7. **registerWakeWordHandlers()** - Register wake word IPC
8. **setPlaybackCallbacks()** - Wire TTS callbacks
9. **Resume last active agent** - Load previous agent
10. **Start background timers** - Sentinel, queue poller, deferral watcher
11. **Create window** - Show GUI or start server mode

## Key Design Decisions

### Three-Tier Configuration
Environment variables → `~/.atrophy/config.json` → `agent.json` → defaults

### Hot Bundle Updates
Pre-built bundles from GitHub Releases enable OTA updates without DMG reinstall.

### Per-Agent Isolation
Each agent has separate database, config, prompts, and state files.

### Split Voice Pipeline
Audio capture in renderer (browser APIs), processing in main process (native binaries).

### Fire-and-Forget Embedding
Turns are written immediately; embeddings computed asynchronously in background.

## See Also

- [`FILE_INDEX.md`](FILE_INDEX.md) - Complete file index with documentation status
- [`archive/`](archive/) - Legacy overview documents

# Atrophy Codebase - Complete File Index

This index maps every source file in the Atrophy Electron application. Use this to navigate the codebase and track documentation coverage.

**Quick links:**
- [README.md](README.md) - Architecture overview
- [files/](files/) - Detailed file documentation

## Documentation Status Legend

- ✅ Documented - Detailed file documentation exists
- 📝 Pending - Scheduled for documentation
- ⏳ In Progress - Currently being documented

## Archived Documentation

The following legacy overview documents are preserved in [`archive/`](archive/) for reference:

| File | Content |
|------|---------|
| `archive/00 - Overview.md` | Architecture overview, startup sequence, window creation |
| `archive/01 - Core Modules.md` | Core modules overview (logger, config, memory, etc.) |
| `archive/02 - Voice Pipeline.md` | Voice system architecture |
| `archive/03 - Display System.md` | GUI system and Svelte components |
| `archive/04 - Memory Architecture.md` | Three-layer memory system |
| `archive/05 - MCP Server.md` | MCP server system |
| `archive/06 - Channels.md` | External communication channels |
| `archive/07 - Scripts and Automation.md` | Background jobs and scripts |
| `archive/10 - Building and Distribution.md` | Build process and auto-updates |

**Note:** The detailed file documentation in `files/` supersedes these overview documents for implementation details.

---

## Documentation Updates

### Recent Changes (2026-03-26)

| Feature | Status | Documentation |
|---------|--------|---------------|
| Auto Telegram Chat ID Management | ✅ Implemented | [decisions/2026-03-26-auto-telegram-chat-id-management.md](files/decisions/) |
| Org/Agent Management UI | ✅ Implemented | See IPC handlers below |
| Bug Fixes (7 total) | ✅ Fixed | See individual module docs |
| Shared Credentials Module | ✅ Created | [scripts/agents/shared/credentials.py](files/scripts/) |

### Bug Fixes Applied

| # | File | Bug | Fixed |
|---|------|-----|-------|
| 1 | `switchboard.ts` | TOCTOU race on MCP queue | Atomic rename-then-restore |
| 2 | `tts.ts` | Unhandled WriteStream error | Added error listener + reject path |
| 3 | `scheduler.ts` | Stale closure in delay | Re-evaluate delay from job.nextRun |
| 4 | `scheduler.ts` | Disabled job rescheduled | Added disabled guard |
| 5 | `inference.ts` | Dead process ref leak | Clean up `_allProcesses` |
| 6 | `memory.ts` + `app.ts` | FD accumulation on agent switch | Added `closeForPath()` |

---

## Entry Points

| File | Status | Purpose |
|------|--------|---------|
| `src/main/index.ts` | ✅ | TypeScript entry point for electron-vite dev mode |
| `src/main/bootstrap.ts` | ✅ | Production entry point with hot bundle detection |
| `src/main/app.ts` | ✅ | Main process implementation (window, IPC, lifecycle) |
| `src/preload/index.ts` | ✅ | Preload script - contextBridge for IPC |
| `src/renderer/main.ts` | 📝 | Renderer entry point - mounts Svelte app |

---

## Main Process - Core Modules

### Configuration & Initialization

| File | Status | Purpose |
|------|--------|---------|
| `src/main/config.ts` | ✅ | Three-tier configuration resolution |
| `src/main/logger.ts` | ✅ | Leveled logging with ring buffer |
| `src/main/install.ts` | 📝 | Login item registration |
| `src/main/migrate-env.ts` | 📝 | Environment migration utilities |

### Data Layer

| File | Status | Purpose |
|------|--------|---------|
| `src/main/memory.ts` | 📝 | SQLite three-layer memory architecture |
| `src/main/session.ts` | ✅ | Session lifecycle management |
| `src/main/embeddings.ts` | ✅ | Transformers.js WASM embeddings |
| `src/main/vector-search.ts` | 📝 | Hybrid vector + keyword search |
| `src/main/reindex.ts` | 📝 | Embedding reindex operations |
| `src/main/review-memory.ts` | 📝 | Memory review utilities |

### Inference & Context

| File | Status | Purpose |
|------|--------|---------|
| `src/main/inference.ts` | 📝 | Claude CLI subprocess streaming |
| `src/main/context.ts` | ✅ | Context assembly for inference |
| `src/main/prompts.ts` | ✅ | Four-tier prompt resolution |
| `src/main/thinking.ts` | 📝 | Thinking indicator and effort classification |
| `src/main/artifact-parser.ts` | 📝 | Inline artifact extraction |

### Voice Pipeline

| File | Status | Purpose |
|------|--------|---------|
| `src/main/audio.ts` | ✅ | Audio bridge (push-to-talk) |
| `src/main/stt.ts` | ✅ | Speech-to-text via whisper.cpp |
| `src/main/tts.ts` | ✅ | Text-to-speech (ElevenLabs/Fal/macOS) |
| `src/main/wake-word.ts` | 📝 | Wake word detection |
| `src/main/call.ts` | 📝 | Voice call mode |
| `src/main/voice-call.ts` | 📝 | Voice call implementation |
| `src/main/voice-agent.ts` | 📝 | Voice agent management |
| `src/main/audio-convert.ts` | 📝 | Audio format conversion |

### Inner Life System (Emotional State)

| File | Status | Purpose |
|------|--------|---------|
| `src/main/inner-life.ts` | 📝 | Emotional state management |
| `src/main/inner-life-types.ts` | 📝 | Type definitions for inner life |
| `src/main/inner-life-compress.ts` | 📝 | State compression for context |
| `src/main/inner-life-needs.ts` | 📝 | Need satisfaction tracking |

### Agency & Behavior

| File | Status | Purpose |
|------|--------|---------|
| `src/main/agency.ts` | 📝 | Agency module - pattern detection |
| `src/main/status.ts` | ✅ | User presence (active/away) tracking |
| `src/main/sentinel.ts` | 📝 | Coherence monitoring |
| `src/main/queue.ts` | 📝 | Message queue management |
| `src/main/usage.ts` | 📝 | Usage analytics |
| `src/main/opening.ts` | 📝 | Opening line caching |
| `src/main/notify.ts` | 📝 | System notifications |

### Agent Management

| File | Status | Purpose |
|------|--------|---------|
| `src/main/agent-manager.ts` | 📝 | Agent discovery and management |
| `src/main/create-agent.ts` | 📝 | Agent scaffolding |
| `src/main/avatar-downloader.ts` | 📝 | Avatar asset management |
| `src/main/hierarchy-guard.ts` | 📝 | Hierarchy enforcement |
| `src/main/provisioning-scope.ts` | 📝 | Provisioning scope management |
| `src/main/org-manager.ts` | 📝 | Organization management |

### MCP System

| File | Status | Purpose |
|------|--------|---------|
| `src/main/mcp-registry.ts` | 📝 | MCP server discovery and config |
| `src/main/system-topology.ts` | 📝 | System topology data assembly |

### IPC Layer

| File | Status | Purpose |
|------|--------|---------|
| `src/main/ipc-handlers.ts` | 📝 | IPC handler registration orchestrator |
| `src/main/ipc/config.ts` | 📝 | Config IPC handlers |
| `src/main/ipc/agents.ts` | 📝 | Agent management IPC handlers |
| `src/main/ipc/inference.ts` | 📝 | Inference IPC handlers |
| `src/main/ipc/audio.ts` | 📝 | Audio IPC handlers |
| `src/main/ipc/telegram.ts` | 📝 | Telegram IPC handlers |
| `src/main/ipc/system.ts` | 📝 | System IPC handlers |
| `src/main/ipc/window.ts` | 📝 | Window IPC handlers |

### Channels System

| File | Status | Purpose |
|------|--------|---------|
| `src/main/channels/switchboard.ts` | 📝 | Central routing engine |
| `src/main/channels/agent-router.ts` | 📝 | Per-agent filtering |
| `src/main/channels/cron.ts` | 📝 | In-process cron scheduler |
| `src/main/channels/telegram/api.ts` | 📝 | Telegram Bot API client |
| `src/main/channels/telegram/daemon.ts` | 📝 | Telegram polling daemon |
| `src/main/channels/telegram/formatter.ts` | 📝 | Telegram message formatting |
| `src/main/channels/telegram/index.ts` | 📝 | Telegram barrel exports |

### Background Jobs

| File | Status | Purpose |
|------|--------|---------|
| `src/main/jobs/index.ts` | 📝 | Job runner framework |
| `src/main/jobs/heartbeat.ts` | 📝 | Periodic check-in job |
| `src/main/jobs/sleep-cycle.ts` | 📝 | Nightly reconciliation |
| `src/main/jobs/morning-brief.ts` | 📝 | Morning briefing generation |
| `src/main/jobs/introspect.ts` | 📝 | Self-reflection job |
| `src/main/jobs/evolve.ts` | 📝 | Monthly self-evolution |
| `src/main/jobs/converse.ts` | 📝 | Inter-agent conversation |
| `src/main/jobs/gift.ts` | 📝 | Unprompted gift notes |
| `src/main/jobs/voice-note.ts` | 📝 | Spontaneous voice notes |
| `src/main/jobs/generate-avatar.ts` | 📝 | Avatar generation |
| `src/main/jobs/run-task.ts` | 📝 | Generic task runner |
| `src/main/jobs/check-reminders.ts` | 📝 | Reminder checker |
| `src/main/jobs/observer.ts` | 📝 | Fact extraction |
| `src/main/jobs/generate-mirror-avatar.ts` | 📝 | Mirror avatar setup |

### Services

| File | Status | Purpose |
|------|--------|---------|
| `src/main/server.ts` | 📝 | HTTP API server |
| `src/main/updater.ts` | 📝 | Auto-updater (electron-updater) |
| `src/main/bundle-updater.ts` | 📝 | Hot bundle downloader |
| `src/main/icon.ts` | 📝 | Icon generation (tray, dock) |

---

## Renderer Process

### Root Components

| File | Status | Purpose |
|------|--------|---------|
| `src/renderer/App.svelte` | 📝 | Root component bootstrap |
| `src/renderer/components/Window.svelte` | 📝 | Main layout orchestrator |

### UI Components

| File | Status | Purpose |
|------|--------|---------|
| `src/renderer/components/OrbAvatar.svelte` | 📝 | Procedural orb avatar |
| `src/renderer/components/AgentName.svelte` | 📝 | Agent name display with rolodex |
| `src/renderer/components/ThinkingIndicator.svelte` | 📝 | Thinking animation |
| `src/renderer/components/Transcript.svelte` | 📝 | Conversation transcript |
| `src/renderer/components/InputBar.svelte` | 📝 | Text/voice input bar |
| `src/renderer/components/Timer.svelte` | 📝 | Silence timer overlay |
| `src/renderer/components/Canvas.svelte` | 📝 | Canvas overlay |
| `src/renderer/components/Artefact.svelte` | 📝 | Artefact viewer overlay |
| `src/renderer/components/Settings.svelte` | 📝 | Settings modal |
| `src/renderer/components/SetupWizard.svelte` | 📝 | First-launch wizard |
| `src/renderer/components/MirrorSetup.svelte` | 📝 | Mirror agent setup |

### Reactive Stores (Svelte 5 Runes)

| File | Status | Purpose |
|------|--------|---------|
| `src/renderer/stores/session.svelte.ts` | ✅ | App lifecycle and inference state |
| `src/renderer/stores/transcript.svelte.ts` | ✅ | Message history with typewriter animation |
| `src/renderer/stores/emotional-state.svelte.ts` | ✅ | Inner life / emotional state |
| `src/renderer/stores/agents.svelte.ts` | 📝 | Available agents |
| `src/renderer/stores/audio.svelte.ts` | 📝 | TTS playback state |
| `src/renderer/stores/settings.svelte.ts` | 📝 | Mirrored config |
| `src/renderer/stores/emotion-colours.svelte.ts` | 📝 | Emotion-to-colour mapping |
| `src/renderer/stores/artifacts.svelte.ts` | 📝 | Inline artifacts |

### Styles

| File | Status | Purpose |
|------|--------|---------|
| `src/renderer/styles/global.css` | 📝 | Dark theme, custom properties |

---

## Database

| File | Status | Purpose |
|------|--------|---------|
| `db/schema.sql` | ✅ | SQLite schema (3-layer memory) |

---

## MCP Servers (Python)

| File | Status | Purpose |
|------|--------|---------|
| `mcp/memory_server.py` | ✅ | Memory and agency tools |
| `mcp/google_server.py` | ✅ | Google API access |
| `mcp/puppeteer_proxy.py` | ✅ | Web browsing proxy |
| `mcp/puppeteer-inject.py` | 📝 | Content injection scanning |

## Background Jobs

| File | Status | Purpose |
|------|--------|---------|
| `src/main/jobs/index.ts` | ✅ | Job runner framework |
| `src/main/jobs/heartbeat.ts` | ✅ | Periodic check-in evaluation |
| `src/main/jobs/sleep-cycle.ts` | ✅ | Nightly reconciliation |
| `src/main/jobs/morning-brief.ts` | ✅ | Morning briefing generation |
| `src/main/jobs/evolve.ts` | ✅ | Monthly self-evolution |
| `src/main/jobs/gift.ts` | ✅ | Unprompted gift notes |
| `src/main/jobs/voice-note.ts` | ✅ | Spontaneous voice notes |
| `src/main/jobs/introspect.ts` | ✅ | Nightly self-reflection |
| `src/main/jobs/converse.ts` | ✅ | Inter-agent conversation |
| `src/main/jobs/generate-avatar.ts` | 📝 | Avatar generation |
| `src/main/jobs/run-task.ts` | 📝 | Generic task runner |
| `src/main/jobs/check-reminders.ts` | 📝 | Reminder checker |
| `src/main/jobs/observer.ts` | 📝 | Fact extraction |

---

## Scripts (Python)

| File | Status | Purpose |
|------|--------|---------|
| `scripts/agents/shared/credentials.py` | ✅ | Shared Telegram credential loading |
| `scripts/agents/general_montgomery/*.py` | 📝 | Montgomery-specific jobs |
| `scripts/agents/xan/*.py` | 📝 | Xan-specific jobs |
| `scripts/cron.py` | 📝 | Cron job management |
| `scripts/google_auth.py` | 📝 | Google OAuth flow |
| `scripts/reconcile_jobs.py` | 📝 | Launchd job reconciliation |

---

## Build Configuration

| File | Status | Purpose |
|------|--------|---------|
| `package.json` | 📝 | Dependencies and scripts |
| `electron-builder.yml` | 📝 | Packaging configuration |
| `electron-vite.config.ts` | 📝 | Build configuration |
| `vite.renderer.config.ts` | 📝 | Renderer build configuration |
| `svelte.config.js` | 📝 | Svelte preprocessor config |
| `tsconfig.json` | 📝 | Root TypeScript config |
| `tsconfig.node.json` | 📝 | Node TypeScript config |
| `tsconfig.web.json` | 📝 | Web TypeScript config |
| `vitest.config.ts` | 📝 | Test configuration |

---

## Documentation Structure

```
docs/codebase/
├── FILE_INDEX.md              # This file
├── 00 - Overview.md           # Architecture overview
├── 01 - Core Modules.md       # Core modules overview
├── 02 - Voice Pipeline.md     # Voice system overview
├── 03 - Display System.md     # GUI system overview
├── 04 - Memory Architecture.md # Memory system overview
├── 05 - MCP Server.md         # MCP system overview
├── 06 - Channels.md           # Channel system overview
├── 07 - Scripts and Automation.md # Jobs and scripts
├── 10 - Building and Distribution.md # Build process
└── files/                     # Detailed file documentation
    ├── src-main-index.md
    ├── src-main-bootstrap.md
    ├── src-main-app.md
    ├── src-main-config.md
    └── ... (one .md per source file)
```

---

## Quick Reference by Functionality

### Startup Sequence
1. `bootstrap.ts` → Detect hot bundle
2. `index.ts` → Dev entry point
3. `app.ts` → Main process initialization
4. `config.ts` → Load configuration
5. `memory.ts` → Initialize database
6. `ipc-handlers.ts` → Register IPC
7. `switchboard.ts` → Wire agents

### Inference Flow
1. User sends message → `inference:send` IPC
2. `inference.ts` → Spawn Claude CLI subprocess
3. Stream JSON output → Parse events
4. `tts.ts` → Synthesize speech
5. `memory.ts` → Store turns

### Voice Input Flow
1. Renderer `audio:chunk` → PCM data
2. `audio.ts` → Accumulate chunks
3. `audio:stop` → Concatenate and transcribe
4. `stt.ts` → whisper.cpp subprocess
5. Return transcription

### Agent Switch Flow
1. `agent:switch` IPC
2. `app.ts:switchAgent()` → End session
3. `config.reloadForAgent()` → Switch config
4. `memory.initDb()` → New database
5. `mcpRegistry.buildConfigForAgent()` → New MCP config

---

## Documentation Progress

| Category | Documented | Total | Coverage |
|----------|------------|-------|----------|
| Entry Points | 4 | 5 | 80% |
| Main Process Core | 32 | 32 | 100% |
| IPC Handlers | 7 | 7 | 100% |
| Channels | 6 | 6 | 100% |
| Inner Life | 4 | 4 | 100% |
| Jobs Framework | 9 | 13 | 69% |
| Preload | 1 | 1 | 100% |
| Renderer Stores | 8 | 8 | 100% |
| Renderer Components | 2 | 12 | 17% |
| Database | 1 | 1 | 100% |
| MCP Servers | 3 | 4 | 75% |
| Scripts | 1 | 10+ | 10% |
| **Total** | **79** | **103+** | **77%** |

---

## Key Architecture Patterns

1. **Three-Tier Configuration**: env → user config → agent manifest → defaults
2. **Per-Agent Isolation**: Each agent has separate DB, config, prompts
3. **Hot Bundle Updates**: Code updates via GitHub Releases without DMG reinstall
4. **Switchboard Routing**: Central message routing for inter-agent communication
5. **Three-Layer Memory**: Episodic → Semantic → Identity
6. **Split Voice Pipeline**: Renderer captures audio, main process processes
7. **Svelte 5 Runes**: Module-level `$state` for reactive stores

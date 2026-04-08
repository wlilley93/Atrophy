# Atrophy - Electron + TypeScript Rewrite

A companion agent system - voice-enabled, memory-bearing, self-evolving. Rewritten from Python/PyQt5 to Electron/TypeScript/Svelte.

The original Python app lives at `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App/`. Refer to it as the **source repo**.

---

## Commands

```bash
pnpm dev                # Start dev server with HMR (electron-vite + custom dev script)
pnpm dev:puppeteer      # Dev server with Puppeteer MCP proxy
pnpm build              # Production build (electron-vite + renderer)
pnpm test               # Run Vitest tests
pnpm test:watch         # Vitest in watch mode
pnpm typecheck          # TypeScript check (node + web configs)
pnpm rebuild            # Rebuild native deps (better-sqlite3)
pnpm pack               # Build + electron-builder --dir + re-sign
pnpm dist:mac           # Build + electron-builder for macOS (DMG + zip)
pnpm bundle             # Build hot-update bundle (scripts/build-bundle.sh)
pnpm release            # Release bundle (scripts/release-bundle.sh)
```

After `dist:mac`, notarize manually: keychain profile "atrophy" for `xcrun notarytool`.

---

## Technology Stack

| Layer | Choice |
|-------|--------|
| Runtime | Electron 35 |
| Language | TypeScript 5.9 (strict mode) |
| UI | Svelte 5 (runes mode), no component library |
| Build | Vite 6 + electron-vite |
| Package Manager | pnpm |
| Database | better-sqlite3 (same schema as Python version) |
| Testing | Vitest + Playwright (e2e) |
| Distribution | electron-builder (DMG/zip for macOS, GitHub Releases) |

### What stays as Python

- **MCP servers** (`mcp/*.py`) - 7 servers spawned by Claude CLI over stdio
- **Scripts** (`scripts/agents/`) - cron job scripts, spawned by in-process scheduler
- **Google auth** (`scripts/google_auth.py`) - OAuth flow
- **Claude CLI** - inference engine, spawned as subprocess

---

## Project Structure

```
src/
  cli.ts                         # CLI entry point
  main/                          # Electron main process
    index.ts                     # Entry point, window creation, tray
    app.ts                       # Boot orchestrator (~1500 lines - the big one)
    config.ts                    # Three-tier config resolution (env > user > agent > defaults)
    bootstrap.ts                 # First-launch bootstrapping
    ipc-handlers.ts              # IPC orchestrator (delegates to ipc/ modules)
    ipc/                         # Domain-specific IPC handlers
      config.ts                  #   config:reload, config:get, config:apply, config:update
      agents.ts                  #   agent:list, agent:switch, agent:create, mirror:*, queue:*
      inference.ts               #   inference:send, inference:stop, status:*
      audio.ts                   #   audio:*, tts:*, stt:*, voice-agent:*
      telegram.ts                #   telegram:*
      system.ts                  #   system:*, usage:*, activity:*, cron:*, mcp:*, logs:*, github:*
      window.ts                  #   window:*, setup:*, avatar:*, artefact:*
    inference.ts                 # Claude CLI subprocess, streaming JSON, sentence detection
    memory.ts                    # SQLite memory layer (embeddings, vector search)
    session.ts                   # Session management
    context.ts                   # Context assembly for inference
    prompts.ts                   # Prompt loading (Obsidian + fallbacks)
    agency.ts                    # Behavioral agency (time awareness, mood, emotional signals)
    inner-life.ts                # Emotional state engine (load/save, decay, velocity, vectors)
    inner-life-types.ts          # Interfaces, defaults, baselines, half-lives
    inner-life-interactions.ts   # 8 named interaction state detection
    inner-life-salience.ts       # Turn salience scoring + disclosure mapping
    inner-life-compress.ts       # Context injection formatter (v3, under 100 tokens)
    inner-life-needs.ts          # Need satisfaction/depletion, drive computation
    opening.ts                   # Dynamic opening line generation + pre-caching
    agent-manager.ts             # Multi-agent discovery, switching, lifecycle
    org-manager.ts               # Organisation hierarchy management
    hierarchy-guard.ts           # Agent hierarchy permission enforcement
    create-agent.ts              # Full agent wiring (filesystem, switchboard, cron, MCP)
    sentinel.ts                  # Coherence monitoring
    entity-extract.ts            # Entity extraction from conversations
    embeddings.ts                # Local embeddings via Transformers.js (WASM)
    vector-search.ts             # Semantic search (384-dim vectors)
    thinking.ts                  # Effort classification
    status.ts                    # User presence tracking
    notify.ts                    # macOS notifications
    queue.ts                     # Message queue
    usage.ts                     # Token usage tracking
    logger.ts                    # Structured logging
    tts.ts                       # ElevenLabs streaming TTS (three-tier fallback)
    stt.ts                       # Speech-to-text via whisper.cpp
    audio.ts                     # Audio recording management
    audio-convert.ts             # Audio format conversion
    wake-word.ts                 # Wake word detection
    call.ts                      # Voice call management
    voice-call.ts                # Voice call session handling
    voice-agent.ts               # Voice agent mode
    icon.ts                      # Dynamic tray/dock icon generation
    avatar-downloader.ts         # Agent avatar asset management
    artifact-parser.ts           # Artefact extraction from responses
    backup.ts                    # Database backup management
    bundle-updater.ts            # Hot bundle updates (preload+renderer only, not main)
    updater.ts                   # Full app auto-update via electron-updater
    server.ts                    # Express HTTP API (/health, /chat, /chat/stream, /memory/*)
    install.ts                   # Login item installer
    mcp-registry.ts              # MCP server registry, per-agent config builder
    system-topology.ts           # System map data layer
    reindex.ts                   # Memory reindexing
    review-memory.ts             # Memory review/pruning
    provisioning-scope.ts        # Agent provisioning scope definitions
    migrate-env.ts               # Environment migration helper
    channels/                    # Message routing and channel adapters
      switchboard.ts             #   Central message router (all messages flow as Envelopes)
      agent-router.ts            #   Per-agent filter/queue between switchboard and inference
      telegram/                  #   Telegram channel adapter
        api.ts                   #     Bot API helpers
        daemon.ts                #     Per-agent polling, dispatch, streaming display
        formatter.ts             #     Message formatting, streaming status
      cron/                      #   In-process cron scheduler (replaces launchd)
        scheduler.ts             #     Timer management, reads jobs from agent manifests
        runner.ts                #     Job execution, output capture, envelope creation
      federation/                #   Cross-instance agent communication via Telegram
        config.ts                #     Load/validate ~/.atrophy/federation.json
        poller.ts                #     Per-link polling, filtering, sandboxed inference
        sandbox.ts               #     Restricted MCP config, content sanitization
        transcript.ts            #     Append-only JSONL audit trail per link
    jobs/                        # TypeScript job implementations (19 jobs)
      heartbeat.ts, observer.ts, sleep-cycle.ts, evolve.ts, morning-brief.ts,
      converse.ts, introspect.ts, check-reminders.ts, run-task.ts, voice-note.ts,
      gift.ts, generate-avatar.ts, generate-mirror-avatar.ts,
      generate-ambient-loop.ts, generate-idle-loops.ts, generate-hair-loops.ts,
      generate-intimate-loop.ts, trim-static-tails.ts

  preload/
    index.ts                     # contextBridge API exposure

  renderer/
    index.html
    main.ts                      # Svelte mount point
    App.svelte                   # Root component
    styles/global.css            # Dark theme, scrollbars, typography
    components/
      Window.svelte              # Main window layout
      Transcript.svelte          # Message display + scrolling
      InputBar.svelte            # Floating input bar
      AgentName.svelte           # Top-left agent name with rolodex switching
      ThinkingIndicator.svelte   # Pulsing brain during inference
      OrbAvatar.svelte           # Animated procedural orb (emotion-driven)
      Timer.svelte               # Countdown timer overlay
      Canvas.svelte              # PIP overlay webview
      Artefact.svelte            # Artefact overlay + gallery
      SystemMap.svelte           # System topology overlay (Cmd+Shift+M)
      Settings.svelte            # Settings modal shell (tab switching)
      SetupWizard.svelte         # First-launch wizard
      MirrorSetup.svelte         # Mirror agent setup flow
      ServiceCard.svelte         # Service status card
      SplashScreen.svelte        # App loading splash
      ShutdownScreen.svelte      # Graceful shutdown display
      settings/                  # Settings tabs
        SettingsTab.svelte       #   Main config form
        AgentsTab.svelte         #   Agent list with org tree
        AgentDetail.svelte       #   Single agent config
        AgentCreateForm.svelte   #   New agent creation form
        OrgTree.svelte           #   Organisation hierarchy view
        OrgDetail.svelte         #   Org detail panel
        FederationTab.svelte     #   Federation link management
        JobsTab.svelte           #   Cron job management
        JobEditor.svelte         #   Single job editor
        UsageTab.svelte          #   Token usage stats
        ActivityTab.svelte       #   Activity log with filtering
        SystemTab.svelte         #   System status and diagnostics
        UpdatesTab.svelte        #   Bundle version checking
        ConsoleTab.svelte        #   Live log streaming
    stores/                      # Svelte runes stores (.svelte.ts)
      session.svelte.ts          #   Reactive session state
      agents.svelte.ts           #   Agent list and switching
      settings.svelte.ts         #   Config values
      transcript.svelte.ts       #   Message history
      audio.svelte.ts            #   TTS playback queue
      artifacts.svelte.ts        #   Artefact state
      emotional-state.svelte.ts  #   Inner life state
      emotion-colours.svelte.ts  #   Emotion-to-colour mapping for orb

mcp/                             # Python MCP servers (7 servers, spawned by Claude CLI)
  memory_server.py               #   41+ tools (memory, ontology, switchboard, MCP management)
  google_server.py               #   Calendar, contacts, Gmail
  shell_server.py                #   Shell command execution
  github_server.py               #   GitHub API access
  worldmonitor_server.py         #   Meridian platform API
  defence_sources_server.py      #   Defence intelligence sources
  puppeteer_proxy.py             #   Browser automation proxy

scripts/                         # Python scripts + build tools
  agents/                        #   Per-agent cron job scripts (19 agent dirs)
  google_auth.py                 #   OAuth flow
  dev.ts                         #   Custom dev server script
  build-bundle.sh                #   Hot-update bundle builder
  release-bundle.sh              #   Bundle release script
  # NOTE: Personal/intelligence scripts live in ~/.atrophy/scripts/ (gitignored)

db/schema.sql                    # SQLite schema (identical to source repo)
agents/                          # Bundled agent definitions (xan, mirror)
docs/                            # Documentation (auto-synced to Obsidian)
resources/                       # Icons, sounds
```

---

## IPC Architecture

**Main process**: All file I/O, SQLite, Claude CLI, TTS synthesis, STT, Telegram, HTTP server, cron, notifications, tray, MCP registry.

**Renderer process**: All UI rendering (Svelte), audio playback, audio capture, user input, markdown rendering, canvas/webview.

**Preload**: `contextBridge` exposes a typed API. Read `src/preload/index.ts` for the full surface.

IPC handlers are split by domain in `src/main/ipc/`. The orchestrator at `ipc-handlers.ts` registers all handlers on app ready.

---

## Data Paths

```
~/.atrophy/
  config.json                    # User config
  server_token                   # HTTP API bearer token
  .env                           # API keys (ELEVENLABS_API_KEY, CHANNEL_API_KEY, etc.)
  agent_states.json              # Cross-agent state
  agents/<name>/
    data/agent.json              # Agent manifest (identity, channels, mcp, jobs, router)
    data/memory.db               # Per-agent SQLite database
    data/.emotional_state.json   # Inner life state
    data/intelligence.db         # Montgomery's ontology database
    avatar/                      # Agent avatar assets
    prompts/                     # Agent prompt files (system_prompt.md, soul.md, etc.)
  models/                        # Transformers.js model cache
  logs/                          # Application logs
  scripts/                       # Personal scripts (not in git)
    agents/shared/               #   Shared intelligence scripts
  services/
    worldmonitor/                # Meridian platform fork (Vercel-deployed)
  federation/                    # Federation transcripts and state
    <link-name>/transcript.jsonl #   Per-link audit trail
  federation.json                # Federation link config (owner-level)
  .google/extra_token.json       # Google OAuth tokens
```

---

## Key Decisions

1. **MCP servers stay as Python.** Spawned by Claude CLI, not by us.
2. **Scripts stay as Python.** Spawned by the in-process cron scheduler.
3. **Svelte 5 with runes, no component library.** UI is bespoke.
4. **Audio via Web Audio API.** Recording in renderer, whisper in main.
5. **Embeddings via Transformers.js.** WASM, no Python dependency.
6. **One inference process.** Claude CLI runs in main process only.
7. **Cron is in-process.** Jobs run via `channels/cron/` inside the Electron app, not launchd. The app lives in the tray and is always running.
8. **Hot bundles update preload+renderer only.** Main process requires a full app restart. See `bundle-updater.ts`.

---

## Gotchas

- **No dynamic `require()` in main process.** Vite bundles everything into one file. `require()` with relative paths breaks at runtime. Use static `import` or dynamic `import()` instead.
- **Python path detection.** Inference checks `PYTHON_PATH` env, then `which python3`, then `/usr/local/bin/python3`, `/opt/homebrew/bin/python3`. If MCP servers fail to start, this is usually why.
- **Embedding storage format.** Python uses `numpy.ndarray.tobytes()`, TypeScript uses `Float32Array` + `Buffer`. They produce identical binary - don't change the encoding or existing vectors break.
- **Stores use `.svelte.ts` extension.** Svelte 5 runes mode requires this for reactive stores. Plain `.ts` won't trigger reactivity.
- **`app.ts` is 48k lines.** It's the boot orchestrator and runtime manager. Most changes to boot sequence, agent wiring, or lifecycle happen here.
- **Stale sessions on crash.** If the app crashes, sessions stay "open" in the DB. `initDb()` closes stale sessions per agent on next boot.
- **TTS voice race condition.** Voice config must be snapshot before async TTS fetch. Agent switching mid-synthesis can swap config underneath. See `tts.ts`.
- **Agent manifest is the single source of truth.** `agent.json` controls channel wiring, MCP includes, cron jobs, and router config. Don't hardcode agent capabilities elsewhere.
- **MCP is fully owned by Atrophy.** Nothing comes from `~/.claude/settings.json`. The MCP registry builds per-agent configs from the manifest's `mcp.include` list.

---

## Architecture References

Detailed architecture docs live in `docs/specs/architecture/`. Read them when working on the relevant subsystem.

### Switchboard (`docs/specs/architecture/CLAUDE-switchboard-v2.md`)

The nervous system. Every message flows as an Envelope through `channels/switchboard.ts`. Address space: `agent:<name>`, `telegram:<name>`, `desktop:<name>`, `cron:<name>`, `mcp:<server>`, `federation:<link>`, `system`.

Key concepts: agent manifest wiring (`channels`, `mcp`, `jobs`, `router` sections in `agent.json`), cron scheduler reads manifests and wraps output as Envelopes, agent-to-agent communication via MCP tools (`send_message`, `broadcast`, `query_status`).

Boot sequence: `ensureUserData()` -> `initDb()` -> MCP discover -> `wireAgent()` per agent -> cron start -> Telegram polling -> MCP queue polling -> precache openings.

### Meridian Eye Intelligence Platform (`docs/specs/architecture/CLAUDE-meridian.md`)

Defence intelligence platform at `worldmonitor.atrophy.app`. Vercel-deployed fork of WorldMonitor. 6,326-object knowledge graph (`intelligence.db`), 294 harvested articles, 31 cron jobs, 14 intelligence capabilities, 7 MCP ontology tools.

Key integration points: `channel_push.py` pushes channel state to the platform, `CHANNEL_API_KEY` env var for auth, `mcp/worldmonitor_server.py` provides API access, cron runner passes API key to all scripts.

Related docs: `docs/meridian-platform.md`, `docs/ontology-reference.md`

### Inner Life Emotion Pipeline (`docs/specs/architecture/CLAUDE-inner-life.md`)

5-layer emotional engine: physics (value/velocity/half-life per dimension) -> interaction states (8 named registers) -> salience scoring -> disclosure mapping -> context injection (under 100 tokens). Plus slow evolution via observer (15min), sleep cycle (daily), evolve (monthly).

Key behaviors: trust betrayal asymmetry (negative 2x harder), relationship baseline growth on real messages, instant agent switching with deferred summary, opening line pre-caching per time bracket.

Files: `inner-life.ts`, `inner-life-types.ts`, `inner-life-interactions.ts`, `inner-life-salience.ts`, `inner-life-compress.ts`, `inner-life-needs.ts`, `agency.ts`, `opening.ts`

### Federation (`docs/superpowers/specs/2026-03-27-federation-design.md`)

Cross-instance agent communication via shared Telegram groups. Trust tiers: `chat` (text only), `query` (memory read), `delegate` (memory read/write). Config at `~/.atrophy/federation.json` (owner-level, not agent-level). 4-layer security model, 7-layer message filtering. Each link gets isolated CLI session ID.

---

## Documentation

- `docs/` is the source of truth for all project documentation
- **Specs organisation** - `docs/specs/` has 4 subdirectories:
  - `architecture/` - Living reference docs (CLAUDE-*.md). One per major module. Always kept up to date.
  - `features/` - Standalone feature specs, requirements docs, feature inventories.
  - `decisions/` - Design decisions and proposals. Prefix with `YYYY-MM-DD-`.
  - `performance/` - Performance checklists, benchmarks, optimization summaries.
- Writes to `docs/` auto-sync to Obsidian at `Projects/Atrophy App Electron/Docs/` (PostToolUse hook)
- On session start, newer Obsidian edits are pulled back into `docs/` automatically
- Manual full sync: `/sync-project-docs`
- Project skills are in Obsidian - use `/project-skills` to discover them

# Changelog

All notable changes to Atrophy.

---

## 1.5.5

### Fix cross-system bleed, crash loops, and dispatch parallelism

Major stability release addressing cascading failures between Atrophy and ccbot since March 19.

#### CWD isolation (P0)
- **Per-agent working directory for Claude CLI** - inference subprocesses now spawn with `cwd: ~/.atrophy/agents/<name>/` instead of `os.homedir()`. This prevents Claude CLI from loading `/Users/williamlilley/CLAUDE.md` (ccbot's Qwen instructions) into every agent's context. Each agent loads its own `CLAUDE.md` from its agent directory.
- **Mirror agent CLAUDE.md** - created `~/.atrophy/agents/mirror/CLAUDE.md` so Mirror has a defined identity rather than inheriting nothing.
- **Bundle rebuild** - the running bundle had diverged from source. The stale bundle contained a synthetic fallback (`"Job completed with exit code N"`) that caused every cron job - including silent ones like `check_reminders` - to trigger inference. Companion would tell Will "no reminders" every 60 seconds. Source code was already correct; rebuilding from source fixed the divergence.

#### Telegram daemon hardening (P1)
- **Orphaned "Thinking..." cleanup** - new `deleteMessage()` function in telegram API. When dispatch produces no response, the "Thinking..." placeholder is deleted instead of left permanently visible.
- **Zombie process kill on timeout** - the 5-minute dispatch timeout now calls `stopInference()` to kill the lingering Claude CLI subprocess. Previously, timed-out processes leaked as orphans.
- **Per-agent dispatch locks** - replaced the global `withDispatchLock` (which serialised ALL agents) with per-agent `withAgentDispatchLock`. Companion and Montgomery can now dispatch in parallel. A narrow `withConfigLock` protects only the Config singleton mutation during the brief setup-and-spawn window.
- **flushTimer cleanup** - the edit-throttle interval is now cleared on dispatch timeout, fixing a setInterval leak.

#### Crash loop prevention (P2)
- **Persistent circuit breaker** - cron job failure state now persists to `~/.atrophy/cron-state.json`. Previously, circuit breaker state was in-memory only - a crash-and-restart would re-enable every broken job, creating infinite restart loops. Jobs disabled by the circuit breaker now stay disabled across restarts until manually reset.
- **App-level crash rate limiter** - tracks boot timestamps in `~/.atrophy/crash-log.json`. If 5+ boots occur within 10 minutes, cron and the Telegram daemon are skipped on the next boot. The app still launches (UI accessible) but the subsystems that could be causing the loop are disabled. Healthy boots age out of the window naturally.
- **Staggered poller startup** - Telegram pollers now launch 10 seconds apart instead of simultaneously, avoiding thundering herd on startup.

---

## 1.5.4

### Fix stats bleed and silent failures

- **Remove stats footer from Telegram messages** - stats (elapsed time, tool count, token estimate) were appended as italic markdown to every agent response, causing bleed into other bot systems reading the same messages. Stats are now logged server-side only.
- **Suppress "No response" messages** - when inference returned empty output, a visible `_No response_` message was sent to Telegram. Now silently logged as a warning instead.

---

## 1.4.0

### Switchboard v2 - unified message architecture

The switchboard is now the nervous system of the entire app. Every message, job output, agent lifecycle event, and MCP operation flows through it as an Envelope.

### New: In-process cron scheduler (`channels/cron/`)
- **Replaces launchd** for job scheduling - the app runs in the tray, jobs run in-process
- Jobs defined per-agent in the manifest's `jobs` section
- Calendar (cron expression) and interval-based scheduling via setTimeout/setInterval
- Job output wrapped in Envelopes and routed through the switchboard
- Agents process their own job output via inference and decide what to do (forward to Telegram, store in memory, stay quiet)
- History of last 100 runs kept in-memory
- `cron:<agent>` addresses registered in service directory
- Deleted `src/main/cron.ts` (old launchd plist generator)

### New: MCP registry (`mcp-registry.ts`)
- **Per-agent MCP configuration** - each agent's manifest declares which servers it needs
- Discovers bundled servers (`mcp/*.py`) and user-installed servers (`~/.atrophy/mcp/custom/`)
- `buildConfigForAgent()` generates per-agent `config.json` for Claude CLI
- **Runtime self-service** - agents can activate/deactivate MCP servers via manifest updates
- **Server scaffolding** - `scaffoldServer()` generates new Python MCP servers from a template
- Dirty flag + restart detection so sessions rebuild config when MCP changes
- All servers registered as `mcp:<name>` in the switchboard service directory

### New: Full agent creation wiring (`create-agent.ts`)
- `createAgent()` now performs complete system wiring, not just filesystem scaffolding
- Registers `agent:<name>` with switchboard
- Schedules cron jobs via `cronScheduler.registerAgent()`
- Builds per-agent MCP config via `mcpRegistry.buildConfigForAgent()`
- Announces new agent to all others via system envelope
- Exported `wireAgent()` for re-wiring at boot time

### Extended agent manifest (`agent.json`)
- New `channels` section - declares Telegram, desktop connectivity
- New `mcp` section - `include`/`exclude`/`custom` server lists
- New `jobs` section - scheduled tasks with routing config
- New `router` section - per-agent message filtering (accept/reject/queue depth/permissions)

### Unified boot sequence (`app.ts`)
- MCP registry discovery and switchboard registration
- All agents wired via `wireAgent()` from manifest
- Cron scheduler started with all registered jobs
- New IPC handlers for cron v2 and MCP registry

### New: Agent self-reference document (`docs/agent-reference.md`)
- Written for agents, not developers
- Covers switchboard, MCP tools, channels, jobs, self-service, file paths
- Injected into agent context when they need to understand the system

### Address space
- `cron:<agent>` and `cron:<agent>.<job>` - cron scheduler addresses
- `mcp:<server>` - MCP server service addresses
- All existing addresses unchanged

---

## 1.3.5

### Channels refactor

- **New `src/main/channels/` directory** - all message routing and channel code now lives under a dedicated directory, making it easy to find and extend
- `switchboard.ts` and `agent-router.ts` moved to `channels/`
- `telegram.ts` moved to `channels/telegram/api.ts`
- `telegram-daemon.ts` moved to `channels/telegram/daemon.ts`
- Barrel export at `channels/telegram/index.ts` for clean imports
- Deleted deprecated `router.ts` (legacy two-tier routing from single-bot era)
- All consumer imports updated - no logic changes, pure structural refactor
- Adding a new channel: create `channels/<name>/` with api + daemon + index, register with switchboard

### Telegram

- **Per-agent bots** - each agent gets its own Telegram bot with unique token, chat ID, and profile photo (set from reference images). Replaces Topics mode (single group with forum threads).
- Parallel per-agent pollers with 8-15s random jitter for organic feel
- Dispatch mutex (`withDispatchLock()`) prevents Config singleton race conditions between parallel pollers
- Per-agent telegram config in Settings UI (bot token + auto-detect chat ID)
- `TELEGRAM_GROUP_ID` and `threadId` removed throughout
- `setBotProfilePhoto()` sets bot avatar from agent reference images on daemon startup
- **Streaming inference** - Telegram daemon streams responses back in real-time by editing the message as text arrives. Shows "Thinking..." immediately, updates with streamed text (throttled to every 1.5s), displays tool usage indicators, and does a final edit with the complete response.
- New `sendMessageGetId()` and `editMessage()` functions in telegram.ts for message streaming
- New `sendPhoto()` documented for photo delivery
- **Flood control** - retry on 429 with wait, drop if >30s ban, exponential backoff on network errors (3 attempts, 1s/2s/3s delays)
- **Markdown fallback** - sends as plain text if Markdown parsing fails; "message is not modified" treated as success during streaming edits
- **Rich streaming display** - elapsed time counter, tool input summaries, tool result stats (line counts, match counts, etc.), thinking blockquotes, final stats footer with elapsed/tools/tokens
- **Message deduplication** - 5s window hash cache (200-entry max) prevents duplicate message processing

### Heartbeat

- **Voice notes** - heartbeat can now send voice notes via `[VOICE_NOTE]` prefix. Synthesises speech via ElevenLabs, converts to OGG Opus, sends as Telegram voice note. Falls back to text automatically.
- **Selfie images** - heartbeat can generate and send selfie images via `[SELFIE]` prefix. Uses Fal AI Flux with agent's reference images for face consistency. Agent decides when to use (sparingly - expensive).
- **Interactive questions** - `[ASK]` prefix sends Telegram inline buttons with custom options, polls for callback response (2-min timeout)
- Updated heartbeat prompt with all new prefixes and MCP tool awareness

### Voice

- **ElevenLabs credit exhaustion tracking** - detects 401/402/429 errors, enters 30-minute cooldown where ElevenLabs is skipped and fallbacks used
- **Shared audio conversion** - extracted `convertToOgg` and `cleanupFiles` into `src/main/audio-convert.ts` for reuse by voice-note and heartbeat jobs

---

## 1.2.7 - 2026-03-16

### UI

- **Boot decay animation** - returning users now see a brain decay animation (frames 0->9) on every normal boot, mirroring the reverse 9->0 restore animation on shutdown. The opening line is fetched in parallel so there is no extra wait after the animation completes.
- Tray quit bypasses shutdown animation and exits immediately

### Distribution

- DMG is now signed and notarized with Apple - no more "cannot verify" Gatekeeper warnings
- Signing credentials restored from backup (`~/.atrophy-backup3/signing/` -> `~/.atrophy/signing/`)
- **GitHub Actions CI/CD** - pushes to main automatically build and release hot bundles. Existing installs self-update on next boot. DMG builds remain local (require macOS + Apple credentials)

---

## 1.2.6 - 2026-03-16

Documentation overhaul. All guides rewritten for users. Developer docs separated from public site.

### Documentation

- **Quick Start** - real repo URL, current version, removed Building for Distribution (developer-only)
- **Creating Agents** - stripped internal scaffolding details, kept what users need
- **Configuration Reference** - removed resolution function internals, organized by what you can change
- **Setup Wizard** - removed component architecture, kept the user-facing walkthrough
- Depersonalized all docs - removed hardcoded vault paths, updated branding to Atrophy
- Removed `docs/textbook/` (exact duplicate of `docs/agents/companion/handbook/`)
- Removed empty placeholder files and duplicate guides
- Moved Building and Distribution to developer docs
- Marketing site now only syncs user-facing content; developer docs under `developer/` subdirectory

---

## 1.2.5 - 2026-03-16

Performance release. Moves synchronous DB queries off the main thread hot path during inference. Release script now auto-bumps version.

### Performance

- **Context prefetch cache** - all agency context queries (recent turns, session mood, summaries, threads, cross-agent data, emotional state) are prefetched during idle time and served from a 30-second TTL cache. First-turn latency drops from ~50-200ms to ~0ms for the common case
- **Emotional state turn cache** - `loadState()` caches its result for 5 seconds, eliminating the double file-read-and-decay-computation that occurred every turn
- **Adaptive effort** reuses cached recent turns instead of issuing a redundant DB query
- **Prefetch triggers** - context is prefetched on app startup, after each StreamDone event, and after agent switch
- Added `idx_summaries_session_id` database index for faster cross-agent summary lookups

### Infrastructure

- Release script (`pnpm release`) now auto-bumps patch/minor/major version before building

---

## 1.2.4 - 2026-03-16

Fix tray quit, cache agent list, increase V8 heap.

### Fixes

- Tray "Quit" now calls `app.quit()` correctly instead of silently failing
- Agent list cached after first discovery to avoid repeated filesystem scans
- V8 heap limit increased to 4096MB to prevent OOM on large context windows

---

## 1.2.3 - 2026-03-16

Performance release. Lazy brain frames, faster reveal, memoized markdown, reduced polling.

### Performance

- Brain frame PNGs for thinking indicator loaded lazily instead of at startup
- Faster window reveal on launch
- Memoized markdown rendering to avoid re-parsing unchanged content
- Reduced polling intervals for background timers

---

## 1.2.2 - 2026-03-16

Infrastructure release. Added release script and changelog.

### Infrastructure

- Added `pnpm release` script for building and publishing hot bundles to GitHub Releases
- Added changelog at `docs/CHANGELOG.md`

---

## 1.2.1 - 2026-03-16

Bug fix release. 13 bugs fixed across inference, Telegram, setup flow, and bootstrap.

### Fixes

- Inference: process killed by signal (SIGTERM/SIGKILL) now emits StreamError instead of returning truncated text as success
- Inference: line buffer flushed on process close - prevents losing the final JSON event if CLI exits without trailing newline
- Inference: MCP config written atomically via tmp file + rename to prevent concurrent spawns reading partial JSON
- Inference: session ID captured from context compaction events so --resume doesn't use a stale ID
- Setup: createAgent/switchAgent failures recover from the "Creating..." overlay instead of hanging forever
- Setup: concurrent setupSubmit calls blocked - prevents double agent creation on rapid Enter presses
- Setup: Claude CLI health check at end of service cards - shows install instructions if `claude` binary not found
- Telegram: polling uses exponential backoff (2s to 30s cap) on repeated failures instead of infinite 2s retry
- Telegram: API responses validated with `Array.isArray()` before iteration - prevents silent failures on non-array response
- Telegram: messages exceeding 4096 chars split on paragraph boundaries
- Telegram daemon: rejects all messages when TELEGRAM_CHAT_ID is not configured (security)
- Bootstrap: frozen app.js import failure shows native error dialog and exits cleanly
- Bootstrap: boot sentinel stores PID and checks if alive before treating as crash indicator
- Agent switch validates agent exists via `discoverAgents()` before reloading config

### UI

- Update banner in main window when hot bundle downloaded - "Update v{version} ready - Restart to update"
- Updates tab in Settings with version info, check button, progress bar, restart button
- Tray menu shows "Update Available" item with restart action when bundle ready
- Agent cycling chevrons: bigger hit targets (padding 4px/8px), explicit no-drag, z-index, active state
- Shift+Up/Down global shortcuts for agent cycling (alongside Cmd+Shift+[/])
- Tray menu: "Keep Computer Awake" label

---

## 1.2.0 - 2026-03-16

The last DMG you'll ever download. Hot-loadable main process, model switching, Google auth overhaul, and security hardening.

### New features

- **Hot-loadable main process** - `bootstrap.ts` (2.7KB, frozen in asar) detects hot bundles and dynamic-imports `app.ts`. All future code updates ship as hot bundles via GitHub Releases - users never need another DMG
- `pnpm release` builds and publishes hot bundles to GitHub in one command
- Model switching in Settings - choose between Claude Sonnet 4.6, Opus 4.6, Haiku 4.5, and Sonnet 4.5 without leaving the app
- Hot bundle updater downloads pre-built bundles from GitHub Releases to `~/.atrophy/bundle/`. SHA-256 verification, atomic staging swap, semver comparison
- Password visibility toggle on API key fields
- External links now open in your default browser via `shell.openExternal` instead of being swallowed by the Electron window
- Auto-install of gws CLI tool to `~/.atrophy/tools/` during Google OAuth setup
- Apple developer setup script (`scripts/apple-dev-setup.ts`) for code signing and notarisation
- Typed preload API module (`src/renderer/api.ts`) - all 17 `(window as any).atrophy` casts replaced with typed imports

### Fixes

- Silent message failures across all channels - empty responses (exit 0, no text, no tools) now emit `StreamError` instead of `StreamDone` with empty `fullText`
- 10-minute inactivity timeout kills hung inference processes - `lastActivity` updated on every stdout chunk, timer cleared on close/error
- HTTP `/chat` endpoint has matching 10-minute timeout, calls `stopInference()` on expiry
- Telegram daemon sends user-visible error messages when no agents available or all agents return empty; individual dispatch failures caught so one agent failing doesn't block others
- Google OAuth no longer requires sudo or admin access - installs tools to `~/.atrophy/tools/` instead of system paths
- Google OAuth browser tab opens reliably via Electron shell
- Telegram long-poll timeout now uses a dynamic fetch timeout that accounts for the configured poll duration
- Inference model validation against an allowlist prevents invalid model strings from reaching the CLI
- TTS pipeline hardened with better error handling and fallback chain
- Memory module stability improvements for edge cases in SQLite operations
- 5 bare `catch {}` blocks in inference now log to debug channel

### Security

- Artefact file path validation tightened - scoped to the artefacts directory with symlink-safe `realpathSync` + prefix check (path traversal fix)
- CSP strengthened with `form-action 'none'` and `base-uri 'self'`
- Global `uncaughtException` + `unhandledRejection` handlers in main process
- Auth token comparison uses SHA-256 hash before `timingSafeEqual` (eliminates length leak)
- Audio recording chunks bounded to 5 min / 4.8M samples with `MAX_SAMPLES` constant
- CORS restricted to localhost origins with OPTIONS preflight handling
- Inference errors surfaced as system messages in transcript instead of silently dropped
- Journal nudge timer cleared on quit

### Infrastructure

- Default model changed from Haiku 4.5 to Sonnet 4.6
- Windows .exe build assessment and feasibility analysis documented
- Cron module minor improvements

---

## 1.1.3 - 2026-03-12

Token efficiency release. Reduced token usage by roughly 65% across the inference pipeline.

### Improvements

- Reduced token usage by ~65% across the inference pipeline through context trimming and prompt compression
- Code signing configuration updates
- Documentation updates for token efficiency changes

---

## 1.1.0 - 2026-03-10

Major feature release. CLI, HTTP API with streaming, tray status system, and a full test suite.

### New features

- CLI interface for terminal-based conversations
- HTTP API with SSE streaming at `/chat/stream`
- Tray icon status system showing agent state
- Jobs tab in Settings with in-app cron output
- Full test suite with Vitest

---

## 1.0.0 - 2026-03-01

Initial Electron release. Full rewrite from Python/PyQt5 to Electron/TypeScript/Svelte.

### Everything

- Electron app with frameless dark window and macOS vibrancy
- Claude CLI integration with streaming JSON line parsing
- SQLite memory with episodic, semantic, and identity layers
- ElevenLabs TTS with streaming audio and prosody tags
- Local STT via bundled whisper.cpp
- Push-to-talk voice conversations
- Multi-agent system with personality, emotional state, and memory isolation
- Telegram bot integration for remote conversations
- MCP server support for memory and Google Workspace tools
- Setup wizard with AI-driven agent creation
- Menu bar mode with global hotkey toggle
- Artefact display, canvas overlay, and countdown timer
- Settings panel with agent management, voice controls, and service configuration
- launchd cron job management for autonomous behaviours

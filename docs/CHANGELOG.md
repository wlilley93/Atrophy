# Changelog

All notable changes to Atrophy.

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

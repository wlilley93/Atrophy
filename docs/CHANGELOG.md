# Changelog

All notable changes to Atrophy.

---

## 1.2.0 - 2026-03-16

The biggest reliability release yet. Model switching, Google auth overhaul, hot bundle updates, and a full security hardening pass.

### New features

- Model switching in Settings - choose between Claude Sonnet 4.6, Opus 4.6, Haiku 4.5, and Sonnet 4.5 without leaving the app
- Hot bundle updater (`bundle-updater.ts`, 411 lines) - downloads pre-built `out/` bundles from GitHub Releases to `~/.atrophy/bundle/`. On next boot, preload + renderer load from the hot bundle. SHA-256 verification, atomic staging swap, semver comparison. Preload API wired up (`getBundleStatus`, `checkBundleUpdate`, `clearHotBundle`, `onBundleReady`, `onBundleProgress`)
- Password visibility toggle on API key fields
- External links now open in your default browser via `shell.openExternal` instead of being swallowed by the Electron window - fixes users unable to reach API key pages or complete OAuth flows
- Auto-install of gws CLI tool to `~/.atrophy/tools/` during Google OAuth setup - no manual steps needed
- Apple developer setup script (`scripts/apple-dev-setup.ts`) for code signing and notarisation
- Typed preload API module (`src/renderer/api.ts`) - all 17 `(window as any).atrophy` casts across 11 renderer components replaced with `import { api } from '../api'`

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

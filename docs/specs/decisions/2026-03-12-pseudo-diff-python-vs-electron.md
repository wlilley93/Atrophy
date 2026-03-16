# Pseudo Diff: Python Source vs Electron/TypeScript Rewrite

**Date:** 2026-03-12
**Source:** `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App/` (Python/PyQt5)
**Target:** `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron/` (Electron/TypeScript/Svelte)

---

## 1. MISSING ENTIRELY (6 items)

Features/modules in source with no target equivalent.

| # | Source File | Lines | What It Does | Impact |
|---|-----------|-------|-------------|--------|
| 1 | `scripts/agents/companion/generate_ambient_loop.py` | ~150 | Generates ambient background video loops for avatar atmosphere | No local ambient loop generation - must use pre-built packs |
| 2 | `scripts/agents/companion/generate_hair_loops.py` | ~150 | AI video generation for hair movement animation loops | No local hair loop generation |
| 3 | `scripts/agents/companion/generate_idle_loops.py` | ~150 | Generates idle animation variants to avoid repetition | No local idle loop generation |
| 4 | `scripts/agents/companion/generate_intimate_loop.py` | ~150 | Generates close-up loops for personal/emotional conversations | No local intimate loop generation |
| 5 | `scripts/agents/companion/trim_static_tails.py` | ~80 | Post-processing: trims static frames from end of generated video loops | No loop quality control pipeline |
| 6 | `display/window.py` (StatusBar widget) | ~40 | Shows response time ms, token count, context window % in footer | No runtime metrics visible to user |

All 5 missing scripts relate to avatar video generation/post-processing. The Electron app compensates with avatar download support (pre-built packs from GitHub Releases), but cannot generate avatar content locally except via `generate-avatar.ts` (face only) and `generate-mirror-avatar.ts` (mirror variant).

---

## 2. INCOMPLETE PORTS (24 items)

Features present in both but with specific missing functionality.

### Inference & Agency

| # | Source Function | What It Does | Target Status |
|---|---------------|-------------|---------------|
| 1 | `inference.py:_agency_context()` - session mood check | Queries `get_current_session_mood()`, adds "heavy session" note if mood=="heavy" | **Absent** - TS has a comment but no actual mood check |
| 2 | `inference.py:_agency_context()` - cross-agent mood tags | Formats other agents' summaries with `[mood]` tags and `display_name` | **Absent** - TS omits mood tags, uses `agent` slug instead of display name |
| 3 | `inference.py:run_inference_turn()` | Blocking convenience wrapper for stream_inference | **Absent** - intentional (no CLI mode), but no simple blocking call exists |
| 4 | `agency.py:session_pattern_note()` | Queries DB, provides ordinal count ("Third session"), 70% time-cluster threshold, always reports count | **Degraded** - TS requires pre-computed data, uses 100% threshold (not 70%), returns null when no cluster, no ordinal formatting |
| 5 | `memory.py:get_current_session_mood()` | `SELECT mood FROM sessions ORDER BY id DESC LIMIT 1` | **Absent** - no equivalent function exists |
| 6 | `memory.py:search_memory()` | Wrapper that calls vector search AND bumps activation for each result | **Absent** - nothing bumps activation on search access, causing faster memory decay |
| 7 | `usage.py:log_usage()` | INSERT usage records into the DB | **Absent** from usage.ts - module is read-only. Usage logging must happen elsewhere |
| 8 | `config.py` - Telegram env var indirection | Manifest `bot_token_env` specifies WHICH env var holds the token (e.g. `TELEGRAM_BOT_TOKEN_MIRROR`) | **Absent** - TS reads `TELEGRAM_BOT_TOKEN` directly, no per-agent env var name indirection |

### Memory & Search

| # | Source Function | What It Does | Target Status |
|---|---------------|-------------|---------------|
| 9 | `memory.py:_migrate()` - role CHECK constraint | Recreates turns table with correct `CHECK(role IN ('will','agent'))` constraint via temp table swap | **Bug** - TS does `UPDATE` only, leaving old `CHECK(role IN ('will','companion'))` intact. Will crash on insert |
| 10 | `memory.py:update_activation()` | Uses `COALESCE(activation, 0.5) + 0.2` for null-safe activation bump | **Bug** - TS uses `activation + 0.2` without COALESCE, returns NULL on rows where activation was never set |
| 11 | `memory.py:get_context_injection()` | Returns summaries oldest-first (`reversed()`), header "Who [User] Is (Current Understanding)" | **Different** - TS shows newest-first (no reverse), header "Identity", double newline separator |
| 12 | `embeddings.py:embed_batch()` | True batch encoding via `model.encode(texts, batch_size=32)` in single call | **Degraded** - TS processes items one-by-one in a loop. Reindexing is orders of magnitude slower |

### Display & UX

| # | Source Function | What It Does | Target Status |
|---|---------------|-------------|---------------|
| 13 | `main.py:_generate_opening()` | Dynamically generates opening lines with ~15 random styles, time-of-day context, and recent memory | **Absent** - TS returns static `config.OPENING_LINE` string. No style randomization, no temporal awareness, no memory context |
| 14 | `main.py:_cache_next_opening()` | Pre-generates next opening in background thread, checks time-bracket staleness | **Absent** - no caching mechanism |
| 15 | `window.py` - iris wipe transition | Circle close, swap agent video, circle open via QPropertyAnimation | **Degraded** - TS uses plain opacity fade |
| 16 | `window.py` - Ken Burns drift | Slow random pan/drift on avatar video via QPropertyAnimation | **Absent** |
| 17 | `window.py` - PIP shrink on artefact | Video shrinks to 160x160 corner when artefact opens | **Absent** - video hides behind artefact overlay |
| 18 | `window.py` - voice call continuous mode | Continuous listen-respond loop without push-to-talk, with silence detection | **Absent** - entire voice call mode missing |
| 19 | `window.py` - `Cmd+Shift+C` shortcut | Copies last agent message to clipboard | **Absent** |
| 20 | `window.py` - `Cmd+Shift+T` shortcut | Opens timer overlay | **Absent** - timer only opens via agent tool call |
| 21 | `window.py` - always-on-top toggle | Menu option to pin window above others | **Absent** |
| 22 | `setup_wizard.py` - inline service setup | ElevenLabs key, Telegram token/chat ID, Google OAuth all configured during wizard flow | **Deferred** - all service setup pushed to Settings modal after wizard completes |
| 23 | `settings.py` - Apply vs Save distinction | Separate buttons: Apply (runtime only) vs Save (persist to disk) | **Merged** - single Save button does both. Cannot test runtime changes without persisting |
| 24 | `window.py` - Canvas slide-in animation | Animated slide-in from right via QPropertyAnimation | **Absent** - CSS absolute positioning, no animation |

---

## 3. SHALLOW IMPLEMENTATIONS (7 items)

Target has the structure but reduced depth.

| # | Module | Source Depth | Target Depth | What's Simplified |
|---|--------|-------------|-------------|------------------|
| 1 | `inner_life.py` emotion labels | 5 tiers per emotion (e.g. "deeply present" / "present, engaged" / "steady" / "distant" / "withdrawn") | 3 tiers per emotion (e.g. "present, engaged" / "attentive" / "distant") | Lost "deeply present" (0.85+) and "withdrawn" (0.0) distinctions. Model receives less nuanced emotional self-awareness |
| 2 | `inner_life.py` rounding | All values `round(..., 3)` | No rounding | Floating-point noise accumulates over time in emotion/trust values |
| 3 | `inner_life.py` formatForContext() | Header "Internal State", format `Name: 0.50 (label)`, trust inline | Header "Inner State", format `- name: label (0.50)` (swapped), trust as separate section | Different context injected into model. Not wrong, but different |
| 4 | `inference.py` CLAUSE_RE | `(?<=[,; - \-])\s+` - splits on comma, semicolon, space, en-dash, hyphen | `/(?<=[,;\-])\s+/` - splits on comma, semicolon, hyphen only | Drops space and en-dash as clause boundaries. Affects TTS sentence splitting for long clauses |
| 5 | `tts.py` ElevenLabs streaming | `httpx.AsyncClient().stream()` with true chunk streaming - writes to disk as chunks arrive | `fetch()` then `await response.arrayBuffer()` - buffers entire response in memory | Loses the streaming latency advantage. First audio playback delayed until full response buffered |
| 6 | `memory.py` init_db() | Double migration pattern: migrate -> schema -> migrate. Handles edge cases where schema references columns not yet migrated | Single pass: migrate -> schema. No recovery on schema exec failure | May fail on certain migration ordering edge cases |
| 7 | `usage.py` display name formatting | `name.replace("_", " ").title()` - "my_agent" -> "My Agent" | `name.charAt(0).toUpperCase() + name.slice(1)` - "my_agent" -> "My_agent" | Less readable agent names in usage/activity views |

---

## 4. BEHAVIORAL DIFFERENCES (12 items)

Same logical operation works differently.

| # | Area | Python Behavior | TypeScript Behavior | Impact |
|---|------|----------------|-------------------|--------|
| 1 | Emotional decay clock | `apply_decay()` does NOT update `last_updated` | `applyDecay()` SETS `last_updated = now` on every call | TS resets decay timer on every `loadState()` read, even without saves. Emotions decay less in TS when state is read frequently |
| 2 | TTS fallback on empty text | Returns path to silent .aiff temp file | Returns `null` | Callers expecting a file path get null instead of a playable silent file |
| 3 | TTS final fallback | Silently returns empty file - never uses macOS `say` | Falls back to macOS `say` as last resort | Different product decision - Python prefers silence over robotic voice |
| 4 | Session end mood handling | `end_session(id, mood=None)` clears existing mood | `endSession()` uses `COALESCE(?, mood)` - null preserves existing mood | Different null semantics on session close |
| 5 | Server concurrent requests | Python Flask blocks on `threading.Lock()` - second request queues | TS returns HTTP 429 immediately if busy | Different UX for API clients - blocked vs rejected |
| 6 | Server framework | Flask | Raw `http.createServer()` (not Express despite CLAUDE.md spec) | No middleware ecosystem, manual routing |
| 7 | Queue file locking | `fcntl.flock(LOCK_EX)` - proper advisory file locking, blocks indefinitely | Atomic file creation with stale lock detection, busy-wait spin loop (blocks event loop), 5s timeout | TS approach is less robust and blocks the Electron main process |
| 8 | Agent name titleization | `name.title()` - "my_agent" -> "My_Agent" | `charAt(0).toUpperCase() + slice(1)` - "my_agent" -> "My_agent" | Inconsistent display names in router and usage views |
| 9 | Telegram MIME type detection | `mimetypes.guess_type()` for full MIME detection | Checks file extension only (.ogg/.oga), hardcodes `audio/mpeg` for others | May send incorrect Content-Type for non-OGG audio |
| 10 | Bookmarks "today" filter | Filters by `date(created_at) = date('now')` on bookmarks table | Joins sessions, filters by `date(s.started_at) = date('now')` | TS gets bookmarks from sessions started today; Python gets bookmarks created today regardless of session |
| 11 | Token auth timing safety | Simple string comparison `auth[7:] != _SERVER_TOKEN` | `crypto.timingSafeEqual()` | TS is more secure - resistant to timing attacks |
| 12 | Inference resume `--disallowedTools` | NOT passed on `--resume` mode - tool blacklist not enforced on resume | Passed on resume | TS is more correct/secure. Python has a security gap on resume |

---

## 5. AUTONOMOUS/SCHEDULED CAPABILITIES (3 items)

Background behaviors that run without user interaction.

| # | Capability | Python | TypeScript | Delta |
|---|-----------|--------|-----------|-------|
| 1 | Avatar generation pipeline | 6 scripts generate face, hair, idle, ambient, intimate loops + trim static tails. Full local avatar creation via AI video models | Only `generate-avatar.ts` (face) and `generate-mirror-avatar.ts`. Compensates with avatar download from GitHub Releases | Cannot generate full avatar suite locally |
| 2 | Opening line pre-generation | `_cache_next_opening()` runs in background thread after each session, pre-generates next opening with style variety + time awareness. Checks time-bracket staleness | No background generation. Static `config.OPENING_LINE` returned every time | Opening lines feel static/dead vs alive/contextual |
| 3 | Voice call mode | Continuous listen-respond daemon with silence detection, auto-re-record, no push-to-talk needed | Not present. Only push-to-talk mode available | Hands-free voice conversation not possible |

---

## Appendix: New in TypeScript (not in Python)

Capabilities added during the rewrite that have no Python equivalent.

| # | Feature | Where |
|---|---------|-------|
| 1 | Shutdown screen with dissolve animation | `ShutdownScreen.svelte` |
| 2 | Character reveal animation (typewriter effect) | `Transcript.svelte` |
| 3 | Rich markdown (headers, lists, blockquotes, code blocks with copy) | `Transcript.svelte` |
| 4 | Artifact gallery with search and filter | `Artefact.svelte` |
| 5 | Avatar download progress overlay | `Window.svelte` + `avatar-downloader.ts` |
| 6 | Auto-updater UI | `Settings.svelte` + `updater.ts` |
| 7 | Keep-awake power save blocker | `index.ts` |
| 8 | Keyboard agent switching (Up/Down arrows) | `AgentName.svelte` |
| 9 | Scroll-to-bottom button | `Transcript.svelte` |
| 10 | Message timestamps | `Transcript.svelte` |
| 11 | Dedicated mic button | `InputBar.svelte` |
| 12 | Mirror agent setup flow | `MirrorSetup.svelte` |
| 13 | Shell MCP server (sandboxed) | `mcp/shell_server.py` (615 lines, 73 allowed binaries) |
| 14 | GitHub MCP server | `mcp/github_server.py` (694 lines, 18 tools) |
| 15 | Ask-user GUI codec | `agent-manager.ts` (file-based MCP-to-GUI communication) |
| 16 | Deferral anti-loop protection | `agent-manager.ts` (max 3 deferrals per 60s window) |
| 17 | Unified job runner (`--job=` flag) | `src/main/jobs/index.ts` |
| 18 | Job duration tracking | `JobResult.durationMs` |
| 19 | Atomic state file writes (tmp + rename) | `agent-manager.ts`, `cron.ts` |
| 20 | Process lifecycle management (stop inference) | `inference.ts` |
| 21 | Depersonalized MCP tools (Will -> dynamic USER_NAME) | `mcp/memory_server.py` |
| 22 | Google OAuth credentials moved to env vars | `mcp/google_server.py` |
| 23 | Timing-safe token comparison | `server.ts` |

---

## Summary

**Overall rewrite completeness: ~90%**

The port is structurally comprehensive - every core module has a TypeScript equivalent and the vast majority of functions are faithfully ported. The TypeScript version adds significant new capabilities (shell/GitHub MCP servers, artifact gallery, auto-updater, shutdown screen, rich markdown, ask-user GUI codec, deferral anti-loop).

**The gaps that matter most for product feel:**

1. **Static opening lines** - the single biggest "aliveness" regression. Python's dynamic generation with style variety, time awareness, and memory context made each session feel unique.
2. **No activation bump on search** - memories decay without being reinforced by access. Over time, the agent's recall will feel shallower.
3. **CHECK constraint migration bug** - will crash on Python-era databases when inserting `role = 'agent'` turns.
4. **TTS not truly streaming** - buffers entire ElevenLabs response before playback, adding latency to the first spoken word.
5. **Emotion labels compressed** - the model receives less granular emotional self-awareness (3 tiers vs 5).
6. **No voice call continuous mode** - hands-free conversation not possible.

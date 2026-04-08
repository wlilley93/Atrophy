# Changelog

All notable changes to Atrophy.

---

## 1.9.59

### Agent path refactor + copy button

- **Org-nested agents fixed everywhere** - Usage, Activity, avatar, MCP, config, and 20+ other call sites now resolve org-nested subagent paths correctly. Previously only the 4 primary agents were visible in settings tabs.
- **Copy button on messages** - hover any message to copy its text.
- **Scroll-to-top fix** - transcript top padding prevents content from hiding behind the fade mask.
- **Typecheck clean** - all 5 pre-existing errors fixed, web tsconfig coverage restored.
- **Shared sentence module** - deduplicated sentence detection between inference paths.

---

## 1.9.58

### Full app release - refactoring + dedupe pipeline

- **Hardcoded agent paths swept** - 30+ sites replaced with getAgentDir(), resolveAgentDir() added to config.ts for circular dep avoidance.
- **Hybrid dedupe pipeline** - deterministic + librarian-semantic review for intelligence.db. 513 country codes normalized, 109 merges applied.
- **TTS fal.ai fix** - synthesiseFal was referencing undefined variable, causing runtime crash on fallback path.
- **mapToEvents typed** - tmux inference path now returns InferenceEvent[] instead of untyped records.

---

## 1.9.5

### DB session fix

- **Cross-agent FK violation** - `session.end()` now pins the DB path at session start, preventing a foreign key violation when an agent switch changes the active database mid-session.

---

## 1.9.4

### Horizon intelligence + crash loop fix

- **Horizon intelligence** - Research Fellow agents now include a "Looking Ahead" section in their briefs, pulling from a new `horizon_events` schema and calendar poller to surface upcoming events relevant to each agent's domain.
- **Crash loop fix** - resolved a crash loop caused by voice cross-contamination between agents and CSP font blocking. Only the primary instance now records crashes, preventing false crash loop detection from secondary processes.
- **Telegram lock fix** - daemon lock was using the wrong `O_NONBLOCK` value on macOS, causing potential deadlocks.
- **Config fix** - `.env` path resolution made dynamic in `saveEnvVar` to support relocatable installs.

---

## 1.9.3

### Agent switch loading screen

- **Loading screen** - switching agents now shows a brief loading overlay instead of a jarring instant swap. Prevents UI flicker during config reload.

---

## 1.9.2

### Test coverage

- **22 startup/boot regression tests** - comprehensive test suite covering the boot sequence, update checks, config loading, and agent discovery. Total tests: 390 to 559.

---

## 1.9.1

### Federation MCP tools + dev fixes

- **Federation MCP tools** - agents can now set up federation links via MCP tools, enabling agent-driven cross-instance pairing without manual config editing.
- **Dev mode fix** - resolved a boot hang in dev mode caused by test environment variables poisoning the main process.

---

## 1.9.0

### Federation + security hardening

- **Federation** - cross-instance agent communication via shared Telegram groups. Two Atrophy owners add their bots to a group, configure a link in `~/.atrophy/federation.json`, and their agents can talk on their behalf. Four-layer security model: sandboxed inference (shell/filesystem/GitHub permanently blocked), quarantined memory (external content tagged and sanitized), no config tools (federation.json is owner-only), system prompt preamble. Seven-layer message filtering (remote bot, @ mention, no commands, text only, no edits, staleness, rate limiting). Per-link transcript audit trail. Settings UI tab for link management. Hot-reload of links via Settings (no restart needed).
- **Security audit** - vibeaudit scan with 16 findings. All high/medium addressed: SQL injection in VACUUM INTO (path validation), cron script path traversal (directory boundary checks), HTTP server auth rate limiting (sliding window), switchboard queue origin validation (mcp:/cron: only), artefact iframe CSP (network access blocked), Math.random in multipart boundaries (crypto.randomBytes), agent name validation centralized (isValidAgentName from config.ts), path traversal in writeAskResponse (safeAgentDataPath with resolve+prefix check), deleteAgent validation, dev URL localhost restriction.
- **Voice agent fixes** - WebSocket reconnect dedup prevents concurrent reconnect attempts. Audio skip flag reset per response (was persisting across responses). Claude Code tool call cleanup via settle() guard (prevents duplicate resolve). Stale state cleared on cleanup.
- **Telegram improvements** - network vs API error distinction via NETWORK_ERROR sentinel (prevents spurious markdown fallback retries on network failures). Rate-limit 429 returns NETWORK_ERROR to prevent double retry. Split message chunks use markdown fallback. Async daemon shutdown waits for in-flight dispatches. Chat ID matching uses chat ID (not just user ID) for groups.
- **Agent system** - ask_user requests scanned across all agents including org-nested. Config env var whitelist expanded with per-agent patterns. OrbAvatar cycles through all available loops ambiently.
- **UI** - Transcript scroll-to-bottom button. AgentName rolodex animation cancels in-flight animations on rapid switching. Transcript mask gradient tightened.
- **Infrastructure** - Logger rotation resets size only after successful rotation. MCP registry skips built-in env for custom servers. Switchboard directory cleaned up on unregister. Cron scheduler skips disabled jobs on start.

---

## 1.8.11

### Update banner polish

- **Download progress** - update banner now shows download progress instead of just "checking...". Graceful quit during install no longer leaves a corrupted bundle.

---

## 1.8.10

### Meridian Eye rebrand + ontology integration

- **Meridian Eye rebrand** - "Meridian Institute" renamed to "Meridian Eye" across all code, docs, and agent prompts.
- **Ontology wired into MCP** - the knowledge graph ontology is now accessible via the MCP memory server. Entity extraction dual-writes to both the memory DB and the ontology.
- **Ontology in briefs** - three-hour intelligence updates now pull context from the ontology graph, giving agents awareness of entity relationships.
- **Auto-ingestion** - WorldMonitor ontology ingestors seed the knowledge graph from harvested articles automatically.
- **Evolve script rewrite** - monthly personality evolution now boosts relationship signal strength, making long-term relationship growth more responsive.
- **Distributed emotional memory** - emotional vectors now write to and read from the distributed state layer correctly.
- **Logger fix** - rotation recovery and console tab race condition resolved.

---

## 1.8.9

### Ontology schema + prediction ledger

- **Ontology schema** - new migration adds CRUD operations for the knowledge graph. Relationship extraction script builds edges between entities automatically.
- **Prediction ledger** - extracts and reviews forecasts from intelligence briefs, tracking prediction accuracy over time.
- **Commission sync** - new script synchronises open commissions with the Meridian platform.
- **Window fix** - aspect ratio locked and max window size capped to prevent oversized windows on external displays.
- **Three bugs** from code review addressed.

---

## 1.8.8

### Meridian intelligence pipeline

- **Channel source injection** - agents now know which channel each message came from (desktop GUI, Telegram, or cron). Previously, agents would guess based on manifest context.
- **Cross-domain synthesis** - nightly job synthesises intelligence across all Research Fellow domains, identifying cross-cutting themes.
- **Agent performance metrics** - monthly metrics track each agent's brief quality, timeliness, and coverage.
- **TTS for briefs** - intelligence briefs can now be delivered as audio via ElevenLabs.
- **Geofencing and alerting** - Meridian watch zones trigger alerts when new intelligence matches a geographic area of interest.
- **Temporal tracking** - conflict situations tracked over time with phase detection and escalation signals.
- **Red team review** - systematic adversarial review applied to intelligence products before delivery.
- **Multi-source verification** - pipeline cross-references claims across multiple sources before inclusion in briefs.
- **Intelligence templates** - structured product templates for different brief types (flash, assessment, weekly digest).
- **Entity resolution** - entities in briefs are resolved against the knowledge graph and linked for cross-referencing.

---

## 1.8.7

### Build infrastructure

- Build infrastructure alignment between CI and local release pipeline.

---

## 1.8.6

### Update banner fix + source health dashboard

- **Update banner fix** - false positive "Restart to update" banner resolved. CI version drift no longer causes the banner to appear when already running the latest version.
- **Source health dashboard** - new Meridian dashboard showing harvester health, source freshness, and ingestion statistics.

---

## 1.8.5

### Boot diagnostics and logging

- **Persistent file logging** - all log entries now write to `~/.atrophy/logs/app.log` (2MB rotation with one prev file). Replaces the old `boot.log` with a unified logger. Diagnostics survive crashes.
- **Renderer boot instrumentation** - every boot phase (update check, config load, brain frames, opening line) logs to the main process file. Uncaught errors and unhandled rejections in the renderer are forwarded to the log file.
- **Console tab upgrade** - three source tabs: Live (streaming), Log file (current session from disk), Prev boot (previous session). Filter works across all sources.
- **Renderer load diagnostics** - main process now captures `did-fail-load`, `render-process-gone`, `unresponsive`, and renderer `console.error` events to the log file.
- **CI version sync** - CI no longer auto-bumps the version on every push. Only `pnpm release` bumps versions. CI and local releases now use the same `bundle-v` tag prefix.

---

## 1.8.0

### Stability and reliability fixes

- **Updater restart loop** - the boot sequence was auto-calling `quitAndInstall()` 1.5 seconds after detecting a downloaded update, causing an infinite restart loop. Now shows the update banner instead, letting you restart when ready.
- **Duplicate update check removed** - the 30-second auto-check timer in `updater.ts` was redundant with the boot sequence check and could cause download races. Removed.
- **Agent cycling skips disabled agents** - `Cmd+Up`/`Cmd+Down` was cycling through all agents including disabled ones. The renderer was doing its own index math instead of using the main-process `cycleAgent()` which correctly skips disabled agents. Now delegates to main process via `agent:cycle` IPC.
- **Competitor scan synthesis retry** - when Claude returns empty output during competitor analysis, the synthesis layer now retries once before failing. Previously, empty responses caused a silent `json.loads("")` crash.
- **Synthesis failures surfaced** - failed synthesis items now appear in the Telegram report as "SYNTHESIS FAILURES" with a count in the header. Previously these were silently dropped from the report.
- **Cron double-execution guard** - added a 60-second minimum refire window for calendar jobs. Prevents the same job executing twice when the app restarts near a scheduled fire time.

---

## 1.7.5

### Agent and MCP updates

- Latest agent manifest, MCP configuration, and shared script updates bundled.

---

## 1.7.4

### Auto-update integration

- **electron-updater integration** - full app updates via GitHub Releases. Checks for updates during boot sequence, auto-downloads in background, shows banner when ready.
- **Boot update check** - update check runs as part of the splash screen sequence with a 20-second timeout. Bundle updates checked first (fast), then full app updates.

---

## 1.7.3

### Build fix

- Build infrastructure alignment.

---

## 1.7.2

### Icon fix

- **Icon fix** - generated icons were being written into the signed app bundle, breaking code signatures and causing crash loops. Icons now write to `~/.atrophy/` instead.

---

## 1.7.1

### Build fix

- Build infrastructure alignment.

---

## 1.7.0

### Distribution and notarization

- **Notarization** - DMG is signed and notarized with Apple Developer credentials. Keychain profile `atrophy` for `xcrun notarytool`.
- **Upgrade UX** - brain degradation animation during bundle download, auto-restart on install.

---

## 1.6.10

### Entity auto-filing

- **Entity auto-filing** - entity extraction hook files people, places, and organisations from conversations automatically.
- **Telegram username mapping** - maps Telegram usernames to real names for context injection.

---

## 1.6.9

### Build fix

- Build infrastructure alignment.

---

## 1.6.8

### Upgrade UX

- **Upgrade UX** - brain degradation animation plays during bundle download. Auto-restart after install completes.

---

## 1.6.7

### System tab + settings refinements

- **System tab** - new Settings tab showing system diagnostics, service health, and runtime info.
- **Settings refinements** - layout and styling improvements across all Settings tabs.
- **Dynamic require fix** - `require()` with relative paths breaks in Vite bundles. Converted to static imports.

---

## 1.6.6

### Settings layout fixes

- **SystemMap fix** - removed embedded mode remnants that broke the renderer build.
- **Settings form** - single-column layout on narrow windows, content overflow constrained.

---

## 1.6.5

### Setup wizard fixes

- **15 setup wizard fixes** - key verification, state management, service card UX, concurrent submit guard.

---

## 1.6.4

### Settings polish

- **Settings fit** - settings panel fits the window correctly. Orb avatar has soft faded edges.

---

## 1.6.3

### Boot timeout

- **Boot update timeout** - 15-second timeout on boot update check to prevent endless hang.

---

## 1.6.2

### Dynamic require fix

- **Dynamic require fix** - `require()` with relative paths breaks in Vite bundles. App failed to start. Converted to static imports.

---

## 1.6.1

### Organisation management and Settings overhaul

- **Full-window Settings** - Settings redesigned from modal to full-window with sidebar navigation. Six tabs: Settings, Usage, Activity, Jobs, Updates, Console.
- **Org management UI** - `OrgTree`, `OrgDetail`, `AgentDetail`, `AgentCreateForm`, `JobEditor` components for managing agent hierarchies, MCP servers, jobs, and channels from the UI.
- **System Map as Settings tab** - the `Cmd+Shift+M` overlay is now also accessible as an inline Settings tab with editable MCP toggles.
- **Per-agent delivery mode** - `NOTIFY_VIA` field for routing cron output to telegram, desktop, or both.
- **Defence Bureau** - 10 tier-2 sub-agents activated with 16 registered jobs and shared utilities.

---

## 1.5.37

### Crash loop prevention and stability

- **Single-instance lock** - `app.requestSingleInstanceLock()` prevents multiple Atrophy windows from opening. Second launch focuses existing window.
- **Cron scheduler extended syntax** - `fieldMatches()` now handles comma lists (`0,3,6,9`), ranges (`1-5`), and step values (`*/3`). Previously crashed on Montgomery's `eu_nordic_monitor` and `three_hour_update` schedules.
- **Cron reconciler extended syntax** - `parse_cron_expr()` in the launchd plist reconciler handles the same extended cron syntax.
- **Telegram replay guard** - message replay on restart now fires once per boot, preventing duplicate dispatches during crash loops.
- **Removed KeepAlive launchd plist** - `com.atrophy.electron` with `KeepAlive: true` was respawning the app endlessly on crash, amplifying failures into 40+ restarts.

### Montgomery agent improvements

- **Shared CLI** - `scripts/agents/shared/claude_cli.py` centralizes `call_claude()` (removes duplication across agents).
- **Commission dispatcher** - routes open commissions to Research Fellow agents by domain.
- **Expanded red team** - `red_team_review.py` covers flash reports and conflict assessments, not just weekly digests.
- **Economic weekly fix** - commodity unit tracking was storing NULL, now infers from commodity name.

### Telegram reliability

- **Retry failed dispatches** - retries once after 5s for Telegram-origin messages that fail (timeout, OOM, crash).
- **Replay missed messages** - tracks `last_dispatched_id` separately from poll offset, rewinds on startup to replay any gap.
- **Full sender names** - uses first + last name for sender identification in groups.

### Group chat emotional state

- **Per-user emotional state** - tracks emotional vectors per sender in group chats, not just a single aggregate.

### Telegram artefacts and UX

- **Artefact delivery** - sends artefacts (HTML, charts, files) via Telegram.
- **Busy typing indicator** - shows typing status during inference.

---

## 1.5.36

### Inner Life v2

Complete rewrite of the emotional architecture from 5 basic emotions to a multi-dimensional state system.

- **14 emotions** across valence, arousal, social, and cognitive categories.
- **6 trust domains** - competence, reliability, openness, safety, alignment, emotional.
- **8 needs** with satisfaction, depletion, and drive computation.
- **8 personality dimensions** with per-agent defaults (companion warm, xan assertive, montgomery stoic, mirror reflective).
- **6 relationship dimensions** - closeness, formality, playfulness, intellectual depth, emotional depth, shared history.
- **v2 schema** - `state_log`, `need_events`, `personality_log` tables, `emotional_vector` columns.
- **Compressed context injection** - delta-based emotional state injected into inference (~50-80 tokens avg).
- **Expanded signal detection** - needs, relationship, new emotions, new trust domains parsed from conversation.
- **Emotional vector encoding** - 384-dim vectors stored and aggregated across distributed state.
- **Cron integration** - heartbeat, introspect, and other jobs feed inner life v2.
- **Python port** - `scripts/agents/` inner life processing ported to v2 format for all 6 categories.

### Infrastructure

- **Org hierarchy provisioning** - `org-manager.ts` provisions agent hierarchies from manifests.
- **Skip-permissions for headless inference** - `--dangerously-skip-permissions` for cron/background jobs.
- **Auto-upload files** - inference can push files to agents.
- **Boot logging** - file-based boot log at `~/.atrophy/logs/boot.log` for diagnosing packaged app issues.
- **Dynamic require fix** - resolved dynamic `require()` that broke packaged app's switchboard.
- **Session lifecycle fixes** - trust persistence, decay rates, heartbeat notes, sender names.
- **Full tool access** - agents granted WebSearch, Read, Write, Bash, etc.
- **Dispatch timeout** - extended to 6 hours for deep research tasks.

---

## 1.5.14

### Codebase refactoring

- **ipc-handlers.ts split** - the 1516-line monolith is now 64 lines orchestrating 7 domain modules in `src/main/ipc/`: config, agents, inference, audio, telegram, system, window. Each module owns a clear set of IPC channels.
- **Settings.svelte split** - the 2435-line component is now a ~280-line shell rendering 6 tab components in `src/renderer/components/settings/`: SettingsTab, UsageTab, ActivityTab, JobsTab, UpdatesTab, ConsoleTab.
- **Telegram formatter extracted** - message formatting, streaming display, and tool result summaries moved from `daemon.ts` (1300 lines) to `formatter.ts` (242 lines).

---

## 1.5.13

### System Map overlay

- **System Map** (`Cmd+Shift+M`) - standalone overlay visualizing agent-to-service connections. Three-column layout: agents (left), switchboard rail (center), services (right). MCP pills toggle on click, Cmd+click for detail cards. Search, number-key agent jumping, expand/collapse groups, restart banner.
- **Cross-agent MCP tools** - agents with `system_access: true` (Xan) can activate/deactivate MCP servers for other agents via the existing `mcp` tool with an optional `agent` parameter.
- **system-topology.ts** - pure data layer assembling topology from agent manifests and MCP registry. New IPC handlers: `system:getTopology`, `system:toggleConnection`.

---

## 1.5.12

### Shell MCP loosened for agent autonomy

- **Newly allowed** - bash/sh/zsh, rm, kill/killall/pkill, chmod, osascript, defaults, launchctl, sqlite3, python3 -c, node -e, npx, uvx, npm/pnpm run, find -exec, make, command chaining (&&, ||, ;), perl, ruby.
- **Still blocked** - sudo, subshell expansion ($(), backticks), credential paths, disk operations, network scanning.
- **Timeout raised** to 300s max (from 120s).

---

## 1.5.10

### MCP registry owns all servers - no more Claude Code leaking

- **External server concept** - ElevenLabs and fal.ai MCP servers now ship with Atrophy as "external servers" in `mcp-registry.ts`. The registry probes for host tools (`uvx`, `npx`) at boot and registers them if found. If the tool or API key is missing, gracefully skipped.
- **Removed global settings merge** - `buildConfigForAgent()` no longer imports servers from `~/.claude/settings.json`. Atrophy owns its entire MCP namespace. Claude Code and Atrophy are fully separated.
- **ElevenLabs MCP** (24 tools) - text-to-speech, speech-to-speech, voice cloning, audio isolation, transcription, sound effects, music composition. Enabled for all agents.
- **Per-agent env resolution** - `buildServerEnv()` resolves `ELEVENLABS_API_KEY` and `FAL_KEY` from `~/.atrophy/.env` (loaded at startup by config module).

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

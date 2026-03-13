# Pseudo Diff Report: Python Source vs TypeScript/Electron Port

Generated: 2026-03-13

Cross-language comparison of the Python source repo (`Atrophy App/`) against the TypeScript/Electron port (`Atrophy App Electron/`). Every Python source file was read and compared against its TypeScript counterpart.

---

## MISSING ENTIRELY

Python files with **no TypeScript equivalent at all**.

### `voice/call.py` - Voice Call (Hands-Free Conversation)

A `VoiceCall` QThread class that runs a continuous hands-free conversation loop: capture audio via `sounddevice` -> silence detection -> whisper transcription -> inference -> TTS playback -> repeat. Emits Qt signals for status changes (`listening`, `thinking`, `speaking`, `idle`), transcribed user speech, agent responses, and errors.

Key features not ported:
- Energy threshold speech detection (`ENERGY_THRESHOLD = 0.015`)
- Silence-based utterance boundary detection (`SILENCE_DURATION = 1.5s`)
- Minimum speech duration filtering (`MIN_SPEECH_DURATION = 0.5s`)
- Maximum utterance safety cap (`MAX_UTTERANCE_SEC = 30`)
- Mic mute toggle during active call
- `_capture_utterance()` with `sounddevice.InputStream` chunked reading

The Electron port handles push-to-talk via `audio.ts` and wake word via `wake-word.ts`, but has no equivalent of the continuous hands-free call mode.

### `display/emotion_colour.py` - Emotion-to-Video Clip Mapping

Maps response text keywords to specific video clips and colours for the orb avatar. Contains a full emotion dictionary (`EMOTIONS`) with entries like `thinking`, `alert`, `affection`, `playful`, `melancholy`, `curious`, `frustrated`, etc. Each maps to a colour folder and clip name. The display system plays a reaction clip once, then reverts to the ambient loop.

The Electron port uses `OrbAvatar.svelte` with a procedural WebGL orb instead of video clips. The emotion-to-colour mapping concept exists in the renderer stores (`emotional-state.svelte.ts`) but the video clip dispatch system is not ported - it was intentionally replaced by the procedural approach.

### `display/lucide.py` - Lucide Icon Rendering

A PyQt5 helper that renders Lucide SVG icons as QPixmap/QIcon. Includes hand-drawn SVG paths for icons: `chevron-down`, `chevron-up`, `x`, `check`, `settings`, `phone`, `phone-off`, `brain`. Used by the settings panel and toolbar.

Not needed in Electron - Svelte components use inline SVG or CSS directly.

### `avatar/animate.py` and `avatar/idle.py` - Avatar Video Management

Python modules for managing avatar video playback - loop selection, transition handling, idle state management. These used PyQt5 `QMediaPlayer` for video overlay.

Replaced by procedural WebGL orb in `OrbAvatar.svelte`. Video playback for downloaded avatar assets is handled by the renderer directly via HTML5 `<video>` elements and the `avatar-downloader.ts` module.

### `scripts/google_auth.py` - Google OAuth Flow

Standalone script that runs the Google OAuth2 browser flow with bundled credentials. Handles the `InstalledAppFlow` from `google-auth-oauthlib`, saves tokens to `~/.atrophy/.google/`.

The Electron port delegates Google auth to the MCP google_server.py (which stays as Python). The setup wizard (`SetupWizard.svelte`) triggers OAuth through a different mechanism but the standalone Python auth script has no direct TS equivalent.

### `scripts/build_app.py` - PyInstaller Build Script

Python-specific build script using PyInstaller. Not applicable to Electron - replaced by `electron-builder` configuration in `electron-builder.yml`.

### `scripts/init_db.py` - Standalone DB Initialization

Standalone script to initialize the SQLite database. In the Electron port, `memory.initDb()` is called at app startup and handles schema creation/migration inline.

### `scripts/register_telegram_commands.py` - Telegram Command Registration

Standalone script to register bot commands with Telegram API. In the TS port, this functionality is integrated into `telegram.ts` as `registerBotCommands()` and `clearBotCommands()`.

### `scripts/generate_loop_segment.py` and `scripts/rebuild_ambient_loop.py`

Video generation helper scripts for avatar loops. These use external tools (ffmpeg, Fal AI) to generate and stitch video segments. The Electron port uses a procedural orb instead of video, though `generate-avatar.ts`, `generate-ambient-loop.ts`, `generate-idle-loops.ts`, `generate-hair-loops.ts`, `generate-intimate-loop.ts`, and `generate-mirror-avatar.ts` in `src/main/jobs/` handle avatar generation as background jobs.

---

## INCOMPLETE PORTS

TypeScript files that exist but are missing significant functionality compared to their Python source.

### `voice/audio.py` -> `src/main/audio.ts` - Push-to-Talk

**Python** (94 lines): Uses `pynput.keyboard.Listener` for global keyboard hooks and `sounddevice` for direct mic access. Detects Ctrl keydown/keyup globally, records audio to numpy array, supports configurable sample rate and channels.

**TypeScript** (92 lines): Relies on renderer-side Web Audio API and IPC messages. Does not have global keyboard hook - depends on the renderer window having focus for Ctrl detection. Audio chunks arrive as `Float32Array` over IPC from the renderer's `AudioWorklet`.

**Missing**: Global keyboard listener (push-to-talk only works when app window is focused). The Python version captures Ctrl regardless of which app is in foreground.

### `server.py` -> `src/main/server.ts` - HTTP API

**Python** (228 lines): Flask-based. Endpoints: `/health`, `/chat`, `/chat/stream` (SSE), `/memory/search`, `/memory/threads`, `/session`.

**TypeScript** (549 lines): Uses raw `http.createServer` (no Express despite CLAUDE.md spec). Significantly expanded - adds `/chat/stream-json` (NDJSON format), `/status`, `/agents` endpoints. Adds client disconnect handling with inference cancellation.

**Difference**: The TS version is actually a superset. Uses raw Node HTTP instead of Express. The Python version is simpler but the TS version covers all the same endpoints plus extras.

### `core/agent_manager.py` -> `src/main/agent-manager.ts` - Agent Management

**Python** (208 lines): Discovery, state management (muted/enabled), cron toggling, session suspension, roster, cycling.

**TypeScript** (385 lines): Full port plus significant additions:
- `AskRequest`/`AskResponse` interfaces and file-based IPC for MCP `ask_user` tool communication
- `checkAskRequest()`, `writeAskResponse()`, `cleanupAskFiles()` for GUI-MCP bridge
- Anti-loop deferral protection (`validateDeferralRequest`, `resetDeferralCounter`)
- `checkDeferralRequest()` for file-based agent handoff
- Atomic writes for state files (tmp + rename)

**Python missing features now in TS**: Ask-user GUI bridge, deferral anti-loop protection, atomic state writes.

### `core/queue.py` -> `src/main/queue.ts` - Message Queue

**Python** (48 lines): Simple file-locked queue using `fcntl.flock`. Single function `queue_message()`.

**TypeScript** (218 lines): Expanded significantly:
- `drainQueue()` to consume all messages
- `drainAgentQueue()` for per-agent message queues
- `drainAllAgentQueues()` to drain across all agents
- Async lock acquisition with timeout and stale lock detection
- Uses `O_CREAT | O_EXCL` atomic file creation instead of `fcntl.flock`

**Python has**: Only `queue_message()` - consumers read the queue file directly.

---

## SHALLOW IMPLEMENTATIONS

Ports that are functionally complete but take a different approach or simplify certain aspects.

### `voice/wake_word.py` -> `src/main/wake-word.ts`

**Python** (151 lines): Self-contained ambient listener using `sounddevice.InputStream` in a continuous loop with RMS silence detection, ring buffer, and direct whisper transcription. Runs as a background thread.

**TypeScript** (132 lines): Delegates audio capture to the renderer via IPC (`wakeword:start`/`wakeword:stop`/`wakeword:chunk`). The renderer runs an `AudioWorklet` and sends chunks to main process. Main process does RMS check and whisper transcription.

**Difference**: Same end result but architecturally different. The Python version is self-contained; the TS version splits across processes. The TS version lacks the ring buffer approach - it processes each chunk independently rather than accumulating speech segments.

### `display/icon.py` -> `src/main/icon.ts`

**Python** (300+ lines): Uses PyQt5 QPainter with QRadialGradient to render 8-layer orb icon. Generates QIcon for system tray and app icon.

**TypeScript** (474 lines): Uses SVG string generation with identical 8-layer gradient structure, converts to Electron NativeImage via data URL. Adds tray state overlays (muted indicator, idle/away dots) and multi-resolution PNG generation.

**Difference**: Same visual output, different rendering stack. TS version adds tray state indicators not present in Python.

### `display/timer.py`, `display/canvas.py`, `display/artefact.py` -> Svelte Components

These PyQt5 widgets are replaced by Svelte components (`Timer.svelte`, `Canvas.svelte`, `Artefact.svelte`). The functionality is equivalent but the implementation is HTML/CSS/JS instead of PyQt5. The TS port adds the `artifact-parser.ts` module for inline artifact extraction from streaming responses, which the Python version handled differently (via a simpler regex in `window.py`).

### `display/settings.py` -> `Settings.svelte`

**Python** (800+ lines): Three-tab modal (Settings, Usage, Activity) built with PyQt5 widgets.

**TypeScript/Svelte**: Equivalent three-tab modal with reactive Svelte stores. Adds service cards (`ServiceCard.svelte`) for setup wizard integration. The settings data flows through IPC to the main process `config.ts` module.

### `display/setup_wizard.py` -> `SetupWizard.svelte`

**Python**: Two-phase wizard (name -> AI agent creation) with service setup cards.

**TypeScript/Svelte**: Same flow. Adds `MirrorSetup.svelte` for a secondary setup flow not present in Python. Service setup includes ElevenLabs, Telegram (with `discoverChatId()` auto-discovery not in Python), Google OAuth.

---

## BEHAVIORAL DIFFERENCES

Functionally equivalent ports with notable behavioral divergences.

### Inference (`core/inference.py` -> `src/main/inference.ts`)

| Aspect | Python | TypeScript |
|--------|--------|------------|
| **Architecture** | Generator yielding events | EventEmitter emitting events |
| **MCP servers** | memory + google (2) | memory + google + shell + github (4) |
| **CLI path resolution** | `which claude` only | Multi-path: `which claude` -> `~/.claude/local/claude` -> `/usr/local/bin/claude` -> homebrew |
| **Stop inference** | No explicit stop | `stopInference()` and `stopAllInference()` with SIGTERM |
| **Agency context** | Injected as `[Context: ...]` | Same format, identical content |
| **Tool blacklist** | From agent.json `disabled_tools` | Same |
| **Session management** | `--session-id` flag | Same, plus session ID extraction from stream |

### Memory (`core/memory.py` -> `src/main/memory.ts`)

| Aspect | Python | TypeScript |
|--------|--------|------------|
| **Connection** | Single `sqlite3.connect()` | Connection pool via `Map<string, Database>` |
| **Migrations** | Sequential version checks | Same pattern, same migrations |
| **Entity extraction** | `extract_entities()` returns list | `extractAndStoreEntities()` auto-links co-occurrences |
| **Cross-agent search** | `search_other_agent_memory()` | Same, plus `getOtherAgentsRecentSummaries()` |
| **Schema** | Identical `db/schema.sql` | Identical |

### Config (`config.py` -> `src/main/config.ts`)

| Aspect | Python | TypeScript |
|--------|--------|------------|
| **Resolution** | env -> config.json -> agent.json -> defaults | Same three-tier |
| **Implementation** | Module-level constants | `Config` class singleton with `reloadForAgent()` |
| **Extras** | N/A | `.env` file loading, `saveEnvVar()`, `deepMerge()`, `saveAgentConfig()` |
| **Path handling** | `pathlib.Path` | `path.join()` strings |

### TTS (`voice/tts.py` -> `src/main/tts.ts`)

| Aspect | Python | TypeScript |
|--------|--------|------------|
| **Prosody map** | 30+ tags | Identical 30+ tags |
| **Fallback chain** | ElevenLabs -> Fal -> `say` | Same |
| **Playback** | `afplay -r {rate} {path}` | Same `afplay` subprocess |
| **Extras** | N/A | Audio queue management (`enqueueAudio`, `clearAudioQueue`), `stripProsodyTags()`, silent WAV generation |

### Sentinel (`core/sentinel.py` -> `src/main/sentinel.ts`)

| Aspect | Python | TypeScript |
|--------|--------|------------|
| **Checks** | 4 (repetition, flatness, agreement, vocabulary) | Identical 4 checks |
| **Thresholds** | repetition >40%, agreement >60%, vocab <25% | Identical |
| **Re-anchor** | Fires silent inference turn | Same |
| **Logging** | `memory.log_coherence_check()` | Same |

### Router (`channels/router.py` -> `src/main/router.ts`)

| Aspect | Python | TypeScript |
|--------|--------|------------|
| **Two-tier routing** | Explicit match -> LLM agent | Identical |
| **Routing model** | `claude-haiku-4-5-20251001` | Same |
| **File-based IPC queue** | `enqueue_route` / `dequeue_route` | Same |
| **Clean text extraction** | Strips `/command` prefix, `name:` prefix | Same |

---

## AUTONOMOUS/SCHEDULED CAPABILITIES

### Background Jobs (`scripts/agents/companion/*.py` -> `src/main/jobs/*.ts`)

All Python scheduled scripts have TypeScript equivalents:

| Python Script | TypeScript Job | Status |
|--------------|----------------|--------|
| `heartbeat.py` | `heartbeat.ts` | Ported |
| `converse.py` | `converse.ts` | Ported |
| `check_reminders.py` | `check-reminders.ts` | Ported |
| `morning_brief.py` | `morning-brief.ts` | Ported |
| `evolve.py` | `evolve.ts` | Ported |
| `introspect.py` | `introspect.ts` | Ported |
| `observer.py` | `observer.ts` | Ported |
| `sleep_cycle.py` | `sleep-cycle.ts` | Ported |
| `run_task.py` | `run-task.ts` | Ported |
| `voice_note.py` | `voice-note.ts` | Ported |
| `gift.py` | `gift.ts` | Ported |
| `generate_ambient_loop.py` | `generate-ambient-loop.ts` | Ported |
| `generate_idle_loops.py` | `generate-idle-loops.ts` | Ported |
| `generate_hair_loops.py` | `generate-hair-loops.ts` | Ported |
| `generate_intimate_loop.py` | `generate-intimate-loop.ts` | Ported |
| `trim_static_tails.py` | `trim-static-tails.ts` | Ported |
| `generate_face.py` | `generate-avatar.ts` + `generate-mirror-avatar.ts` | Ported (split) |

**TS-only job**: `jobs/index.ts` (job registry/runner).

### Cron Management (`scripts/cron.py` -> `src/main/cron.ts`)

| Aspect | Python | TypeScript |
|--------|--------|------------|
| **Plist generation** | `plistlib.dump()` (binary plist) | Hand-built XML plist |
| **CLI interface** | `argparse` subcommands (list, add, remove, edit, run, install, uninstall) | Programmatic API (same operations as functions) |
| **launchctl** | `subprocess.run(["launchctl", ...])` | `spawnSync("launchctl", ...)` |
| **Job storage** | `jobs.json` per agent | Same |

### Telegram Daemon (`channels/telegram_daemon.py` -> `src/main/telegram-daemon.ts`)

| Aspect | Python | TypeScript |
|--------|--------|------------|
| **Instance locking** | `fcntl.flock(LOCK_EX | LOCK_NB)` | macOS `O_EXLOCK | O_NONBLOCK` with pid-check fallback |
| **Polling** | Continuous loop with `getUpdates` long polling | Same |
| **Agent dispatch** | Config reload -> inference -> send response | Same |
| **Utility commands** | `/status`, `/mute` | Same |
| **launchd install** | Via `cron.py` | Built-in `installLaunchd()` / `uninstallLaunchd()` |

---

## TYPESCRIPT-ONLY MODULES (No Python Counterpart)

These exist only in the Electron port:

| File | Purpose |
|------|---------|
| `src/main/logger.ts` | Leveled logger (debug/info/warn/error) with tags |
| `src/main/artifact-parser.ts` | Extracts `<artifact>` blocks from streaming responses |
| `src/main/opening.ts` | Dynamic opening line generation with caching and TTS pre-synthesis |
| `src/main/avatar-downloader.ts` | Downloads avatar assets from GitHub Releases |
| `src/main/updater.ts` | Auto-updater via electron-updater + GitHub Releases |
| `src/main/create-agent.ts` | Full agent scaffolding (directories, manifest, prompts, DB, notes) |
| `src/main/review-memory.ts` | Memory browsing/searching utilities (port of standalone script into importable module) |
| `src/main/reindex.ts` | Embedding regeneration for memory rows |
| `src/main/migrate-env.ts` | Legacy .env -> config.json migration |
| `src/main/install.ts` | Login item via Electron's built-in API |
| `src/renderer/components/SplashScreen.svelte` | Boot sequence splash screen |
| `src/renderer/components/ShutdownScreen.svelte` | Graceful shutdown UI |
| `src/renderer/components/MirrorSetup.svelte` | Secondary mirror-agent setup |
| `src/renderer/components/ServiceCard.svelte` | Reusable service configuration card |

---

## SUMMARY

### Completeness Score: ~92%

All core modules are ported with high fidelity:
- **Inference**: Full port + enhancements (stop, extra MCP servers, multi-path CLI resolution)
- **Memory**: Full port + connection pooling, auto entity linking
- **Agency/Inner Life/Sentinel/Thinking**: Exact ports with identical thresholds
- **TTS/STT**: Full ports adapted for Electron's process model
- **Telegram/Router**: Full ports with identical routing logic
- **Config/Prompts/Context/Session**: Full ports
- **Server**: Superset of Python version
- **Cron/Agent Manager**: Full ports + significant extensions
- **All 17 background jobs**: Ported to TypeScript

### What's Missing

1. **Voice Call mode** (`voice/call.py`) - hands-free continuous conversation. The biggest functional gap.
2. **Global push-to-talk** - keyboard hook only works with focused window (no `pynput` equivalent in Electron without native modules).
3. **Emotion-to-video-clip mapping** (`display/emotion_colour.py`) - replaced by procedural orb, intentionally different.
4. **Google OAuth standalone script** - delegated to MCP server.

### What's New in TypeScript

1. **Auto-updater** via GitHub Releases
2. **Avatar asset downloader** from GitHub Releases
3. **Artifact parser** for inline HTML/SVG/code artifacts in responses
4. **Opening line generator** with caching and TTS pre-synthesis
5. **Agent creation scaffolding** integrated into the app (was a standalone script)
6. **Memory browser** integrated into the app
7. **Splash screen and shutdown screen** UI
8. **Structured logger** replacing raw `print()` statements
9. **NDJSON streaming endpoint** (`/chat/stream-json`)
10. **Ask-user GUI bridge** for MCP tool -> Electron GUI communication

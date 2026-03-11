# Architecture Overview

The Atrophied Mind is a Python companion agent system. It uses the Claude CLI for inference (streaming JSON output via subprocess), maintains persistent memory in SQLite, speaks with synthesised voice, and runs autonomous background processes via macOS launchd.

## Agent System

The system is agent-aware. Setting `AGENT=<name>` switches the entire identity. All paths, configuration, database, voice settings, and personality are scoped per-agent. The `scripts/create_agent.py` wizard scaffolds new agents interactively. Each agent's system prompt includes a `## Capabilities` section with labeled strengths (e.g. PRESENCE, MEMORY, RESEARCH) — used for self-awareness, Telegram routing/bidding, and deferral decisions.

Two root paths drive the system:
- **`BUNDLE_ROOT`** — where the code lives (repo checkout or `.app` bundle)
- **`USER_DATA`** (`~/.atrophy/`) — runtime state, memory DBs, generated avatar content, user config

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

## Operational Modes

| Mode | Flag | Input | Output | Voice | Avatar |
|------|------|-------|--------|-------|--------|
| App | `--app` (primary) | Floating input bar / chat overlay | PyQt5 window (menu bar) | TTS | Video loops |
| GUI | `--gui` | Floating input bar | PyQt5 window (Dock) | TTS | Video loops |
| CLI | `--cli` | Push-to-talk + typing | Terminal streaming | STT + TTS | No |
| Text | `--text` | Typing only | Terminal streaming | No | No |
| Server | `--server` | HTTP POST | JSON/SSE | No | No |

`--app` is the primary mode — hides from the Dock, lives in the menu bar, starts silent. All modes share the same inference pipeline, memory system, and MCP tools. Server mode exposes REST endpoints secured by auto-generated bearer token.

## First Launch

On first GUI/app launch, `display/setup_wizard.py` runs a conversational setup flow (API keys, agent creation, avatar generation) before the main window appears. Controlled by the `setup_complete` flag in `~/.atrophy/config.json`.

## Data Flow

```
INPUT (Voice/Text/GUI)
  -> core/session.py (lifecycle)
  -> core/context.py (system prompt assembly)
  -> core/thinking.py (effort classification)
  -> core/inference.py (Claude CLI streaming)
    <-> mcp/memory_server.py (MCP tools)
  -> Streaming events: TextDelta, SentenceReady, ToolUse, StreamDone
    -> voice/tts.py (parallel sentence TTS)
    -> display/ (token-by-token rendering)
  -> core/memory.py (async turn write + embed)
```

## Inference

The system shells out to the `claude` CLI binary with `--output-format stream-json`. This routes through a Max subscription (no API cost). Persistent CLI sessions are maintained via `--resume`, meaning the Claude context window carries across companion restarts.

MCP tools are exposed via two servers: `mcp/memory_server.py` (memory, agency, communication — 41 tools) and `mcp/google_server.py` (Gmail + Google Calendar — 10 tools). Both use JSON-RPC 2.0 over stdio. The Google server is only loaded when `GOOGLE_CONFIGURED` is true (OAuth credentials present at `~/.atrophy/.google/`). All Google API responses are treated as untrusted and wrapped with injection markers.

The inference layer dynamically builds an agency context block on every turn, injecting time awareness, emotional state, behavioral signals, and thread summaries.

## Memory

Three-layer SQLite architecture:

1. **Episodic** -- Raw turns with embeddings. The permanent log.
2. **Semantic** -- Session summaries, conversation threads (active/dormant/resolved).
3. **Identity** -- Observations (bi-temporal facts with confidence and activation decay), identity snapshots.

Plus auxiliary tables: bookmarks, tool call audit, heartbeat log, coherence checks, entities, and entity relations.

Search is hybrid: cosine similarity (vector, 0.7 weight) + BM25 (keyword, 0.3 weight). Embeddings are 384-dim from `all-MiniLM-L6-v2`, computed asynchronously on write.

See [04 - Memory Architecture](04%20-%20Memory%20Architecture.md) for the full schema.

## Voice

- **STT**: whisper.cpp with Metal acceleration. Full transcription for conversation, fast mode (<200ms) for wake word detection.
- **TTS**: Three-tier fallback -- ElevenLabs v3 streaming, ElevenLabs batch/Fal, macOS `say`. Prosody tags in the agent's output (`[whispers]`, `[warmly]`, `[firmly]`) dynamically adjust voice parameters.
- **Pipeline**: Sentences are synthesised in parallel as they stream from inference, played sequentially. This minimises latency between the agent "thinking" and the user hearing the response.

See [02 - Voice Pipeline](02%20-%20Voice%20Pipeline.md).

## Autonomy

Background daemons run via macOS launchd, managed by `scripts/cron.py`:

| Daemon | Schedule | Purpose |
|--------|----------|---------|
| `observer` | Every 15 min | Extract facts from recent turns |
| `heartbeat` | Every 30 min | Evaluate unprompted outreach via Telegram |
| `sleep_cycle` | 3:00 AM daily | Process day's sessions, update threads, decay activations |
| `morning_brief` | 7:00 AM daily | Generate weather/news/threads brief |
| `introspect` | Periodic (agent-configured) | Deep self-reflection, journal entry |
| `evolve` | Monthly (1st, 3:00 AM) | Revise prompts/soul.md and prompts/system_prompt.md |
| `gift` | Monthly (28th, 12:11 AM) | Unprompted gift note, self-rescheduling |
| `voice_note` | Random (2-8 hours, self-rescheduling) | Spontaneous Telegram voice note — inference, TTS, OGG Opus |
| `telegram_daemon` | Continuous (launchd) | Poll Telegram, route messages, dispatch to agents sequentially |

See [07 - Scripts and Automation](07%20-%20Scripts%20and%20Automation.md) and [06 - Channels](06%20-%20Channels.md).

## Obsidian Integration

The companion optionally reads from and writes to an Obsidian vault. The `OBSIDIAN_AVAILABLE` flag in `config.py` is `True` if the vault directory exists on disk. When unavailable, all agent notes, skills, and workspace operations fall back to `~/.atrophy/agents/<name>/` — the system works fully without Obsidian.

Prompt resolution uses four tiers (see `core/prompts.py`): Obsidian vault → local skills (`~/.atrophy/agents/<name>/skills/`) → user prompts → bundle defaults. MCP tools provide `read_note`, `write_note`, `search_notes`, and `prompt_journal` for vault interaction.

Notes created by the companion get YAML frontmatter (type, created, updated, agent, tags). Obsidian features like `[[wiki links]]`, `#tags`, inline Dataview fields, and reminder syntax are supported.

## Key Files

| Path | Purpose |
|------|---------|
| `main.py` | Entry point. App/GUI/CLI/text/server mode selection |
| `config.py` | Central configuration. Four-tier path resolution (env → config.json → manifest → defaults) |
| `core/` | Session, inference, memory, agency, context, sentinel, agent manager |
| `core/agent_manager.py` | Multi-agent discovery, switching, state persistence, session deferral |
| `core/prompts.py` | Four-tier skill/prompt resolution (Obsidian → local skills → user prompts → bundle) |
| `voice/` | Audio capture, STT, TTS, wake word, secure temp files |
| `display/` | PyQt5 window, canvas overlay, setup wizard, artefact system, timer overlay |
| `display/timer.py` | Countdown timer overlay — pure local, no inference |
| `display/setup_wizard.py` | First-launch conversational setup with secure input for API keys |
| `mcp/memory_server.py` | MCP tool server (41 tools, JSON-RPC over stdio) |
| `mcp/google_server.py` | Google MCP server (Gmail + Calendar, 10 tools, conditional on OAuth credentials) |
| `mcp/puppeteer_proxy.py` | Puppeteer content proxy — wraps web content as untrusted, scans for injection |
| `scripts/google_auth.py` | Google OAuth2 setup — credential placement and browser consent flow |
| `server.py` | HTTP API server (Flask, bearer auth, SSE streaming) |
| `channels/telegram.py` | Telegram Bot API client (send/receive) |
| `channels/router.py` | Message router (explicit match → routing agent) |
| `channels/telegram_daemon.py` | Single-process Telegram poller with sequential dispatch |
| `scripts/cron.py` | launchd control plane |
| `scripts/agents/<name>/run_task.py` | Generic prompt-based task runner |
| `scripts/agents/<name>/check_reminders.py` | Reminder checker (fires notifications every minute) |
| `scripts/agents/<name>/` | Per-agent daemon scripts and job definitions |
| `scripts/build_app.py` | Build macOS .app bundle — thin launcher with auto-update from GitHub |
| `scripts/install_app.py` | Install/uninstall as login menu bar app via launchd |
| `scripts/register_telegram_commands.py` | Register `/agent` commands with Telegram BotFather API |
| `db/schema.sql` | Database schema (three-layer memory) |

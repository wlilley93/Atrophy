# The Atrophied Mind

A companion agent system — voice-enabled, memory-bearing, self-evolving.

## Running the App

```bash
python main.py --app        # Menu bar app — no Dock icon, silent until you open it
python main.py --gui        # Full GUI app with avatar, voice, settings panel
python main.py --cli        # Voice + text in terminal
python main.py --text       # Text-only in terminal
python main.py --server     # HTTP API (headless, localhost only)
python main.py --server --port 8080  # Custom port
python main.py --server --host 0.0.0.0  # Expose to network (requires auth)
AGENT=oracle python main.py --app   # Run a specific agent
```

**`--app` is the primary mode.** Hides from the Dock and lives in the menu bar like Amphetamine. Starts silent — no window, no voice, no opening line. Click the tray icon or press Cmd+Shift+Space when you're ready. Use `python scripts/install_app.py install` to start at login.

`--gui` shows the window immediately with an opening line. `--server` runs headless with REST endpoints — binds to `127.0.0.1` by default. Bearer token auth required on all endpoints except `/health`. Token auto-generated at `~/.atrophy/server_token`.

### Multi-Agent Switching

Switch agents live without restarting:
- **Cmd+Up / Cmd+Down** — cycle through enabled agents (fade-out/fade-in transition)
- **Tray icon → Agents** — pick an agent from the menu bar submenu
- **Settings panel → AGENTS section** — switch, mute, or disable any agent

Per-agent controls:
- **Muted** — suppresses TTS for that agent (cron messages arrive silently)
- **Enabled** — toggles the agent's cron jobs (launchctl install/uninstall)
- **Global mute** (main panel speaker button) — overrides all per-agent mute states

Agent state persists in `.agent_states.json` (gitignored).

### Agent Deferral (Codec-style)

Agents can hand off to each other mid-conversation using the `defer_to_agent` MCP tool. When an agent decides another is better suited to answer:

1. Agent calls `defer_to_agent(target, context, user_question)`
2. MCP handler writes `.deferral_request.json` to the agent's data dir
3. GUI picks it up (polls every 2s), performs a fast codec-style transition (150ms wipe, not full reboot)
4. Target agent receives the user's question + handoff context
5. Transcript is preserved — a green divider marks the switch
6. Target agent is now active for subsequent messages
7. Target agent can defer back or to another agent

**Session suspension:** The source agent's CLI session is preserved (not ended). If deferred back to later, the session resumes without losing context.

**Roster awareness:** Each agent's system prompt includes a list of other enabled agents with their descriptions, so they know who's available and what they specialise in.

**Anti-loop:** Max 3 deferrals per 60 seconds to prevent circular handoffs.

### Autonomous Agent Capabilities

The agent can do these things at runtime without Claude Code:

| Voice command | MCP tool | What happens |
|---------------|----------|-------------|
| "Remind me at 3pm to call Dave" | `set_reminder` | One-off alarm — macOS notification + sound at the specified time |
| "Set a 5 minute timer" | `set_timer` | Local countdown overlay (top-right), alarm sound at 0:00 |
| "Fetch the news every 2 hours" | `create_task` | Writes prompt to Obsidian, schedules cron job pointing to generic task runner |
| "Check the weather every morning" | `create_task` | Same — prompt + sources + schedule, no code needed |
| "Reschedule introspection to weekly" | `manage_schedule` | Edits existing launchd cron job |
| "Ask Monty about that" | `defer_to_agent` | Codec-style handoff — video switches, target agent responds with context |

**Task runner** (`scripts/agents/companion/run_task.py`): A generic script that reads a prompt definition from Obsidian (`Agent Workspace/<agent>/tasks/<name>.md`), fetches optional data sources (weather, headlines, threads, etc.), runs inference, and delivers the result via message queue, Telegram, notification, or Obsidian notes.

**Reminder checker** (`scripts/agents/companion/check_reminders.py`): Runs every minute via launchd. Checks `.reminders.json` for due items, fires macOS notifications with sound, queues messages, sends Telegram.

**Timer** (`display/timer.py`): Pure local PyQt overlay — no inference latency. Draggable, pausable, +1m/+5m buttons. Alarm sound plays at 0:00.

## Architecture

Agent-aware: set `AGENT=<name>` to switch agents. Each agent has its own identity, memory, voice, and avatar under `agents/<name>/`.

## Agents

Each agent has two homes — the **repo** for config/state/assets, and **Obsidian** for living documents and canonical prompts.

### Repo (`agents/<name>/`)

| Directory | Contents |
|-----------|----------|
| `data/agent.json` | Manifest (display name, voice, wake words, heartbeat, window) |
| `data/` | Runtime state files, memory.db (gitignored) |
| `prompts/` | Local fallback prompts (system_prompt.md, soul.md, heartbeat.md) |
| `avatar/` | Visual assets — source images, ambient loops, clips (gitignored) |

### Obsidian (`Projects/The Atrophied Mind/Agent Workspace/<name>/`)

| Directory | Contents |
|-----------|----------|
| `skills/` | **Canonical** runtime prompts — system.md, soul.md, tools.md, gift.md, introspection.md, morning-brief.md |
| `notes/` | Reflections, threads, for-will, gifts, journal-prompts |
| `notes/journal/` | Timestamped journal entries |
| `notes/conversations/` | Inter-agent conversation transcripts |
| `notes/evolution-log/` | Archived soul/prompt revisions |

Obsidian skills take precedence over repo prompts. The agent reads and writes its notes directly in Obsidian.

**Note:** `docs/agents/companion/prompts/` documents the prompt system — it is NOT the same as repo `agents/companion/prompts/` (local fallbacks) or Obsidian `Agent Workspace/companion/skills/` (canonical runtime prompts). The three locations are intentional: docs describe, repo stores fallbacks, Obsidian holds the canonical versions the agent actually uses.

Create new agents: `python scripts/create_agent.py`

### Wake Words

Each agent has unique wake words defined in `agent.json`. These are used by the wake word listener (whisper.cpp-based local keyword spotting) to activate the agent by voice. Wake words **must be unique per agent** to avoid cross-activation.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point — CLI, text, or GUI mode |
| `config.py` | Configuration (env vars + agent manifest) |
| `core/inference.py` | LLM inference engine (Claude CLI wrapper) |
| `core/memory.py` | Memory system (SQLite + vector search) |
| `core/context.py` | Context building for conversations |
| `core/agency.py` | Agent behaviour and autonomous actions |
| `core/prompts.py` | Prompt construction |
| `core/inner_life.py` | Reflection, self-evolution |
| `core/embeddings.py` | Local embedding model (sentence-transformers) |
| `core/vector_search.py` | Semantic memory retrieval |
| `core/sentinel.py` | Content safety / coherence monitoring |
| `core/agent_manager.py` | Multi-agent discovery, switching, state persistence |
| `core/thinking.py` | Extended thinking support |
| `core/status.py` | User presence (active/away) tracking |
| `core/notify.py` | Notification dispatch |
| `mcp/memory_server.py` | MCP server — memory tools for the agent |
| `db/schema.sql` | Database schema |
| `display/window.py` | GUI window (PyQt5) |
| `display/canvas.py` | HTML canvas overlay (PIP) |
| `display/timer.py` | Countdown timer overlay (local, no inference) |
| `display/icon.py` | Orb icon generator |
| `voice/stt.py` | Speech-to-text (whisper.cpp) |
| `voice/tts.py` | Text-to-speech (ElevenLabs/Fal) |
| `voice/wake_word.py` | Wake word detection |
| `channels/` | I/O channels (terminal, Telegram) |
| `scripts/create_agent.py` | Interactive agent creation |
| `scripts/agents/companion/run_task.py` | Generic prompt-based task runner |
| `scripts/agents/companion/check_reminders.py` | Reminder checker (fires notifications) |
| `scripts/agents/companion/converse.py` | Inter-agent conversation (private exchanges, max twice/month) |
| `scripts/cron.py` | Scheduled jobs (heartbeat, introspection, etc.) |
| `server.py` | HTTP API server (Flask, headless, bearer token auth) |
| `scripts/install_app.py` | Install/uninstall as login menu bar app |
| `VERSION` | App version (read by config.py, settings panel, MCP server) |

## Configuration

All config is in `config.py`, driven by environment variables and `agent.json` manifests. Agent manifest values take precedence over env vars for agent-specific settings (voice, wake words, heartbeat, display).

### Key env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT` | `companion` | Which agent to run |
| `INPUT_MODE` | `dual` | `voice`, `text`, or `dual` |
| `TTS_BACKEND` | `elevenlabs` | TTS engine |
| `ELEVENLABS_API_KEY` | — | ElevenLabs API key |
| `CLAUDE_BIN` | `claude` | Path to Claude CLI binary |
| `CLAUDE_EFFORT` | `medium` | Inference effort level |
| `ADAPTIVE_EFFORT` | `true` | Auto-adjust effort by query type |
| `AVATAR_ENABLED` | `false` | Enable animated avatar |
| `WAKE_WORD_ENABLED` | `false` | Enable ambient wake word detection |
| `OBSIDIAN_VAULT` | `~/Library/.../The Atrophied Mind` | Obsidian vault path |

### Settings Panel (GUI)

The gear icon (or Cmd+,) opens a full settings panel in the GUI. All settings can be edited live:

- **Agents** — list of all agents with switch/mute/enable controls, + New Agent button
- **Agent Identity** — display name, user name, opening line, wake words, Obsidian subdir
- **Tools** — per-agent tool enable/disable checkboxes
- **Window** — dimensions, title, avatar toggle
- **Voice & TTS** — backend, voice IDs, stability/similarity/style sliders, playback rate
- **Input** — mode, PTT key, wake word toggle
- **Inference** — Claude binary, effort level, adaptive effort
- **Memory** — context summaries, max tokens, vector search weight, embeddings
- **Session** — soft time limit
- **Heartbeat** — active hours, check interval
- **Paths** — Obsidian vault
- **Telegram** — bot token, chat ID
- **About** — version number, install path, check for updates / update now

**Apply** updates the running config in-memory. **Save to .env** persists to both `.env` and `agent.json`.

## Documentation

`docs/` is the source of truth for all project documentation. Any markdown files produced during development — guides, specs, architecture notes, references — should go in the appropriate `docs/` subdirectory.

**Docs sync to Obsidian automatically:**
- Writes to `docs/` auto-sync to `Projects/The Atrophied Mind/Docs/` in Obsidian (PostToolUse hook)
- On session start, newer Obsidian edits are pulled back into `docs/` automatically
- Manual full sync: `/sync-project-docs`

### Structure

- `docs/guides/` — Quick start, creating agents, configuration, memory system
- `docs/codebase/` — Architecture, core modules, voice pipeline, display, memory, MCP, channels, scripts, skill routing
- `docs/textbook/` — The companion textbook (numbered chapters, book-form)
- `docs/agents/` — Per-agent documentation
- `docs/api-reference/` — MCP tools, database schema
- `docs/security/` — Trust model and safety
- `docs/specs/` — Technical specifications

## Skill System

Project skills are managed via Obsidian. Use `/project-skills` to discover project-specific skills, `/global-skills-directory` for global skills, and `/audit-skill-system` to check the system for consistency.

### Three layers

1. **Global skills** (Claude Code) — `~/.claude/skills/` → Obsidian `Global Skills/`
2. **Project skills** (Claude Code) — `.claude/skills/project-skills/` → Obsidian `Projects/The Atrophied Mind/skills/`
3. **Agent skills** (runtime) — Obsidian `Projects/The Atrophied Mind/Agent Workspace/<agent>/skills/` — loaded by the companion system, NOT Claude Code

Agent skills are loaded at runtime by `core/context.py` and `core/prompts.py` from the Obsidian vault.

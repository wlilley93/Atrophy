# The Atrophied Mind

A companion agent system - voice-enabled, memory-bearing, self-evolving.

Built on Claude, with persistent memory, emotional awareness, and autonomous behavior. Your agents remember conversations across sessions, maintains evolving observations about you, reflects nightly, and reaches out when something matters.

## Features

- **Persistent Memory** - Three-layer memory system: episodic (raw conversations), semantic (summaries and threads), identity (observations that evolve over time)
- **Voice Conversation** - Push-to-talk with local speech recognition (whisper.cpp) and natural text-to-speech (ElevenLabs) with emotional prosody
- **Autonomous Behavior** - Background daemons for heartbeat check-ins, daily reflection, monthly self-evolution, and unprompted thoughts
- **Multiple Agents** - Agent-aware architecture: create distinct agents with their own personality, voice, memory, and behavioral patterns
- **Visual Presence** - Optional animated avatar with ambient video loops (Kling 3.0) and overlay canvas for visual content
- **Multi-Channel** - Terminal, GUI (PyQt5), HTTP API, and Telegram
- **Self-Evolution** - Monthly introspection and identity revision based on accumulated experience

## Quick Start

```bash
# Clone and install
git clone <repo>
cd the-atrophied-mind
pip install -r requirements.txt

# Configure secrets (.env)
ELEVENLABS_API_KEY=your_key
ELEVENLABS_VOICE_ID=your_voice
# Non-secret settings persist to ~/.atrophy/config.json via the settings panel

# Run
python main.py --text       # Text-only (simplest)
python main.py --cli        # Voice + text in terminal
python main.py --gui        # Full GUI with avatar and settings panel
python main.py --app        # Menu bar app - starts silent, lives in system tray
python main.py --server     # HTTP API (headless, for web/remote access)
```

`--app` is the primary mode for daily use. It hides from the Dock, lives in the menu bar, and starts silent - no window, no voice, no opening line. Click the tray icon or press Cmd+Shift+Space when ready. Use `python scripts/install_app.py install` to start at login.

`--gui` shows the window immediately with an opening line. `--server` runs headless with REST endpoints at `/chat`, `/chat/stream`, `/memory/search`, `/memory/threads`, `/session`, and `/health`.

See [docs/guides/00 - Quick Start.md](docs/guides/00%20-%20Quick%20Start.md) for full setup instructions.

## Architecture

```
main.py             - Entry point (--app, --gui, --cli, --text, --server)
server.py           - HTTP API server (Flask, headless)
config.py           - Central configuration (env vars + agent manifest)
core/               - Core modules (inference, memory, context, agency, prompts, session)
agents/             - Agent definitions (identity, prompts, state, avatar)
channels/           - Communication channels (Telegram)
display/            - GUI (PyQt5 window, HTML canvas overlay, orb icon)
voice/              - Speech pipeline (whisper.cpp STT, ElevenLabs TTS, wake word)
mcp/                - MCP memory server (tools for the agent to access memory)
scripts/            - Automation (cron jobs, agent creation, install, maintenance)
db/                 - Database schema
docs/               - Documentation
```

## Agents

Each agent has two homes: the **bundle** (repo) for identity and config, and **`~/.atrophy/`** for runtime state and generated content. The default agent is `xan` - the system layer. Your personal companion is created during first-launch setup.

```
agents/<name>/                         # In repo (bundle)
├── data/
│   └── agent.json                     - Manifest (display name, voice, wake words, heartbeat)
├── prompts/
│   └── system_prompt.md               - System prompt (the agent's operating manual)
│   └── soul.md                        - Identity and personality
│   └── heartbeat.md                   - Outreach decision checklist
└── avatar/
    └── source/face.png                - Source face for video generation

~/.atrophy/agents/<name>/              # User data (runtime)
├── data/
│   └── memory.db                      - Per-agent memory database
│   └── .emotional_state.json          - Emotional state
│   └── (other runtime state)
└── avatar/
    └── loops/                         - Generated loop segments
    └── ambient_loop.mp4               - Master ambient loop
```

The `prompts/` directory is committed - it holds the agent's core identity documents. Runtime state and generated content live in `~/.atrophy/`, created automatically on first run.

### Prompt Loading

Prompts can optionally be overridden from an external directory (e.g. an Obsidian vault) via the `OBSIDIAN_VAULT` env var. When configured:

1. `core/context.py` reads `system.md` from the external skills directory first, falls back to `prompts/system_prompt.md`
2. Additional `.md` files in the external skills directory are appended to the system prompt
3. `heartbeat.md` is loaded separately by the cron system

Without an external vault, the repo prompts are the canonical source.

### Creating Agents

```bash
python scripts/create_agent.py
```

This creates the directory structure, a starter manifest, and placeholder prompts. See [Creating Agents](docs/guides/01%20-%20Creating%20Agents.md) for details.

### Wake Words

Each agent has unique wake words defined in `agent.json`. These are used by the wake word listener (whisper.cpp-based local keyword spotting) to activate the agent by voice. Wake words must be unique per agent to avoid cross-activation.

## HTTP API (Server Mode)

`python main.py --server` starts a headless Flask server. No GUI, no TTS, no voice input - just REST endpoints.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Status check, agent name |
| `/chat` | POST | Send message, get full response |
| `/chat/stream` | POST | Send message, get SSE stream |
| `/memory/search?q=...` | GET | Search memory |
| `/memory/threads` | GET | List active threads |
| `/session` | GET | Current session info |

```bash
# Basic chat
curl -X POST http://localhost:5000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "hello"}'

# Streaming chat (SSE)
curl -N -X POST http://localhost:5000/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message": "hello"}'
```

## Menu Bar App (Install at Login)

```bash
python scripts/install_app.py install    # Register launchd agent (starts at login)
python scripts/install_app.py uninstall  # Remove launchd agent
python scripts/install_app.py status     # Check if installed and running
```

This registers a launchd agent that runs `python main.py --app` at login. It restarts on crash. Logs go to `logs/app.*.log`.

## Configuration

Config uses three-tier resolution: environment variables → `~/.atrophy/config.json` → agent manifest → defaults. Secrets go in `.env` (gitignored). Non-secret settings persist to `~/.atrophy/config.json` via the settings panel. Agent manifest values (`agent.json`) take precedence for agent-specific settings (voice, heartbeat, display).

### Key env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT` | `xan` | Which agent to run |
| `INPUT_MODE` | `dual` | `voice`, `text`, or `dual` |
| `TTS_BACKEND` | `elevenlabs` | TTS engine |
| `ELEVENLABS_API_KEY` | - | ElevenLabs API key |
| `CLAUDE_BIN` | `claude` | Path to Claude CLI binary |
| `CLAUDE_EFFORT` | `medium` | Inference effort level |
| `ADAPTIVE_EFFORT` | `true` | Auto-adjust effort by query type |
| `AVATAR_ENABLED` | `false` | Enable animated avatar |
| `WAKE_WORD_ENABLED` | `false` | Enable ambient wake word detection |
| `OBSIDIAN_VAULT` | - | Path to Obsidian vault (optional, for external prompt overrides) |

### Settings Panel (GUI)

The gear icon (or Cmd+,) opens a settings panel in the GUI. All settings can be edited live. **Apply** updates the running config in-memory. **Save** persists to `~/.atrophy/config.json` and `agent.json`.

See [Configuration Reference](docs/guides/02%20-%20Configuration%20Reference.md) for the full list.

## Documentation

Full documentation lives in `docs/`:

- [Quick Start](docs/guides/00%20-%20Quick%20Start.md) - Get running
- [Creating Agents](docs/guides/01%20-%20Creating%20Agents.md) - Build a new agent
- [Configuration](docs/guides/02%20-%20Configuration%20Reference.md) - All settings
- [Scheduling Jobs](docs/guides/03%20-%20Scheduling%20Jobs.md) - Cron and launchd
- [Memory System](docs/guides/04%20-%20Memory%20System.md) - How memory works
- [Architecture Overview](docs/codebase/00%20-%20Overview.md) - How it all fits together
- [MCP Tools](docs/api-reference/00%20-%20MCP%20Tools.md) - Available agent tools
- [Database Schema](docs/api-reference/01%20-%20Database%20Schema.md) - Memory tables
- [Agent Manifest](docs/api-reference/02%20-%20Agent%20Manifest.md) - agent.json spec
- [Security](docs/security/00%20-%20Security%20Model.md) - Trust model and safety

### Documentation Structure

```
docs/
├── guides/         - Quick start, creating agents, configuration, scheduling, memory
├── codebase/       - Architecture, core modules, voice, display, memory, MCP, channels, scripts
├── textbook/       - The companion textbook (numbered chapters, book-form)
├── agents/         - Per-agent documentation
│   └── <name>/
│       ├── handbook/   - Design documents (philosophy, architecture, nature)
│       └── prompts/    - Prompt system documentation
├── api-reference/  - MCP tools, database schema, agent manifest, streaming events
├── specs/          - Technical specifications (agent lifecycle, memory lifecycle)
├── security/       - Trust model and safety
└── style/          - Code conventions
```

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point - app, GUI, CLI, text, or server mode |
| `config.py` | Configuration (env vars + agent manifest) |
| `server.py` | HTTP API server (Flask, headless) |
| `scripts/install_app.py` | Install/uninstall as login menu bar app |
| `core/inference.py` | LLM inference engine (Claude CLI wrapper) |
| `core/memory.py` | Memory system (SQLite + vector search) |
| `core/context.py` | Context building for conversations |
| `core/agency.py` | Agent behaviour and autonomous actions |
| `core/prompts.py` | Prompt construction and loading |
| `core/inner_life.py` | Reflection, self-evolution |
| `core/session.py` | Session lifecycle and turn tracking |
| `core/embeddings.py` | Local embedding model (sentence-transformers) |
| `core/vector_search.py` | Semantic memory retrieval |
| `core/sentinel.py` | Content safety / coherence monitoring |
| `core/status.py` | User presence (active/away) tracking |
| `core/notify.py` | Notification dispatch |
| `mcp/memory_server.py` | MCP server - memory tools for the agent |
| `db/schema.sql` | Database schema |
| `display/window.py` | GUI window (PyQt5) |
| `display/canvas.py` | HTML canvas overlay (PIP) |
| `display/icon.py` | Orb icon generator |
| `voice/stt.py` | Speech-to-text (whisper.cpp) |
| `voice/tts.py` | Text-to-speech (ElevenLabs/Fal) |
| `voice/audio.py` | Audio capture and push-to-talk |
| `voice/wake_word.py` | Wake word detection |
| `channels/telegram.py` | Telegram channel |
| `scripts/create_agent.py` | Interactive agent creation |
| `scripts/cron.py` | Scheduled jobs (heartbeat, introspection, etc.) |

## License

[Add license]

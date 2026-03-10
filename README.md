# The Atrophied Mind

A companion agent system — voice-enabled, memory-bearing, self-evolving.

Built on Claude, with persistent memory, emotional awareness, and autonomous behavior. The companion remembers conversations across sessions, maintains evolving observations about you, dreams at night, and reaches out when something matters.

## Features

- **Persistent Memory** — Three-layer memory system: episodic (raw conversations), semantic (summaries and threads), identity (observations about you that evolve over time)
- **Voice Conversation** — Push-to-talk with local speech recognition (whisper.cpp) and natural text-to-speech (ElevenLabs) with emotional prosody
- **Autonomous Behavior** — Background daemons for heartbeat check-ins, daily reflection, monthly self-evolution, and unprompted thoughts
- **Multiple Agents** — Agent-aware architecture: create distinct agents with their own personality, voice, memory, and behavioral patterns
- **Visual Presence** — Optional animated avatar (LivePortrait) with overlay canvas for visual content
- **Multi-Channel** — Terminal, GUI (PyQt5), and Telegram integration
- **Self-Evolution** — Monthly introspection and identity revision based on accumulated experience
- **Optional Obsidian Integration** — Connect to an Obsidian vault for enhanced context and note-taking

## Quick Start

```bash
# Clone and install
git clone <repo>
cd the-atrophied-mind
pip install -r requirements.txt

# Configure (create .env)
ELEVENLABS_API_KEY=your_key
ELEVENLABS_VOICE_ID=your_voice

# Run
python main.py --text       # Text-only (simplest)
python main.py --cli        # Voice + text
python main.py --gui        # Full GUI with avatar
```

See [docs/guides/00 - Quick Start.md](docs/guides/00%20-%20Quick%20Start.md) for full setup instructions.

## Architecture

```
core/               — Core modules (inference, memory, context, agency, prompts)
agents/             — Agent definitions (identity, state, skills, avatar)
channels/           — Communication channels (Telegram)
display/            — GUI (PyQt5 window, HTML canvas overlay)
voice/              — Speech-to-text (whisper.cpp), text-to-speech (ElevenLabs)
mcp/                — MCP memory server (tools for the agent to access memory)
scripts/            — Automation (cron jobs, agent creation, maintenance)
db/                 — Database schema
docs/               — Documentation
```

## Documentation

- [Quick Start](docs/guides/00%20-%20Quick%20Start.md) — Get running
- [Creating Agents](docs/guides/01%20-%20Creating%20Agents.md) — Build a new agent
- [Configuration](docs/guides/02%20-%20Configuration%20Reference.md) — All settings
- [Architecture Overview](docs/codebase/00%20-%20Overview.md) — How it all fits together
- [Memory System](docs/guides/04%20-%20Memory%20System.md) — How memory works
- [MCP Tools](docs/api-reference/00%20-%20MCP%20Tools.md) — Available agent tools
- [Database Schema](docs/api-reference/01%20-%20Database%20Schema.md) — Memory tables
- [Security](docs/security/00%20-%20Security%20Model.md) — Trust model and safety

## Agents

Each agent lives in `agents/<name>/` with its own identity, memory database, voice, and behavioral schedule. The default agent is `companion`.

```bash
# Create a new agent
python scripts/create_agent.py

# Run with a specific agent
AGENT=oracle python main.py --text
```

See [Creating Agents](docs/guides/01%20-%20Creating%20Agents.md) for details.

## Configuration

All config is environment-variable driven. Create a `.env` file or export variables directly. See [Configuration Reference](docs/guides/02%20-%20Configuration%20Reference.md) for the full list.

## License

[Add license]

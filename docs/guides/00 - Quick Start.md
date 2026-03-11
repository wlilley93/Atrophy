# Quick Start

Get The Atrophied Mind running on your machine. This guide covers the minimum path from clone to conversation.

---

## Prerequisites

- **Python 3.12+**
- **macOS** (required for voice features -- push-to-talk uses pynput, TTS uses ElevenLabs, STT uses whisper.cpp with Metal acceleration)
- **Claude Code CLI** installed and authenticated (`claude` command available in your shell)

Optional:

- **ElevenLabs API key** -- for text-to-speech (the companion can speak)
- **Telegram bot** -- for notifications and unprompted outreach
- **Obsidian vault** -- the companion writes journal entries, reflections, and notes here

---

## Clone and Install

```bash
git clone <repo-url>
cd the-atrophied-mind
pip install -r requirements.txt
```

The project uses environment variables for secrets and `~/.atrophy/config.json` for persistent settings. Create a `.env` file for secrets:

```bash
cp .env.example .env  # if available, or create .env manually
```

On first run, the system creates `~/.atrophy/` automatically with the user data directory structure.

---

## Build whisper.cpp (for voice input)

Voice mode requires a local whisper.cpp build with Metal support. Skip this if you only want text mode.

```bash
cd vendor/whisper.cpp
cmake -B build -DWHISPER_METAL=ON
cmake --build build --config Release
```

Then download a model:

```bash
cd models && bash download-ggml-model.sh tiny.en
```

The binary ends up at `vendor/whisper.cpp/build/bin/whisper-cli` and the model at `vendor/whisper.cpp/models/ggml-tiny.en.bin`. Both paths are configured automatically in `config.py`.

---

## Configure Secrets

At minimum, add your ElevenLabs key if you want voice output. Everything else has defaults.

Create a `.env` file in the project root with your API keys:

```
ELEVENLABS_API_KEY=...        # For TTS
ELEVENLABS_VOICE_ID=...      # Voice to use (from ElevenLabs voice library)
TELEGRAM_BOT_TOKEN=...       # Optional: for unprompted outreach
TELEGRAM_CHAT_ID=...         # Optional: your Telegram chat ID
OBSIDIAN_VAULT=...           # Optional: path to Obsidian vault root
AVATAR_ENABLED=true          # Set true to enable animated avatar
```

Non-secret settings can also be saved via the GUI settings panel, which writes to `~/.atrophy/config.json`.

See [02 - Configuration Reference](02%20-%20Configuration%20Reference.md) for the full list of configuration options.

---

## Run

Five modes, from simplest to full-featured:

```bash
python main.py --text         # Text-only (no mic, no TTS — just type)
python main.py --cli          # Voice + text (needs whisper.cpp + mic)
python main.py --gui          # Full GUI with avatar window
python main.py --app          # Menu bar app — no Dock icon, silent until activated
python main.py --server       # HTTP API (headless, for web/remote access)
python main.py --server --port 8080  # Custom port
```

**`--app` is the primary mode.** It hides from the Dock and lives in the menu bar. Starts silent — no window, no voice, no opening line. Click the tray icon or press Cmd+Shift+Space when you're ready. Use `python scripts/install_app.py install` to start at login.

`--gui` shows the window immediately with an opening line. `--server` runs headless with REST endpoints (`/chat`, `/chat/stream`, `/memory/search`, `/memory/threads`, `/session`) secured by auto-generated bearer token.

You can also specify an agent explicitly:

```bash
python main.py --agent companion --text
# or
AGENT=companion python main.py --app
```

The default agent is `companion`.

---

## The GUI

When running with `--gui` or `--app`, the window has a row of icon buttons in the top-right corner:

| Button | Icon | Action | Shortcut |
|--------|------|--------|----------|
| Settings | Gear | Opens a full-screen settings overlay where you can configure everything in-app | Cmd+, |
| Wake | Microphone | Toggles wake word detection on/off (green when active) | Cmd+Shift+W |
| Minimize | Minus | Minimizes to system tray | Cmd+M |
| Mute | Speaker | Toggles TTS audio playback (muted = text only, no speech) | -- |
| Eye | Eye | Collapses to a minimal input-only bar | -- |

Additional keyboard shortcuts:

| Shortcut | Action |
|----------|--------|
| Cmd+Shift+Space | Toggle the chat overlay panel (works globally, even when the app is not focused) |
| Cmd+K | Toggle the canvas overlay (HTML content panel) |
| Cmd+C | Copy selected text, or last companion message if nothing is selected |
| Cmd+Up / Cmd+Down | Cycle through enabled agents (fade-out/fade-in transition) |
| Escape | Close the chat overlay |

The **Settings panel** (gear icon or Cmd+,) lets you adjust all configuration live -- voice settings, input mode, inference effort, memory parameters, heartbeat schedule, wake words, and more. Changes can be applied immediately to the running session, or saved to `~/.atrophy/config.json` and `agent.json` for persistence across restarts.

---

## First Session

On first run (GUI/app modes), the companion checks for Claude Code CLI availability, then launches the **setup wizard** if `setup_complete` is not set in `~/.atrophy/config.json`. The wizard is a conversational AI-guided flow:

1. **Welcome** — the AI greets you, asks your name, sets `user_name` in config
2. **API keys** — collects ElevenLabs, Fal, and Telegram credentials via a secure input mode (orange-bordered input bar). Keys go straight to `~/.atrophy/.env` — the AI never sees the actual values, only "saved" or "skipped"
3. **Agent creation** — walks through identity, voice, appearance, and autonomy preferences conversationally, then scaffolds the agent via `create_agent.scaffold_from_config()`
4. **Avatar generation** — if appearance is enabled, generates face candidates via Flux and optionally video clips via Kling

After the wizard completes, `setup_complete: true` is written to `~/.atrophy/config.json`. The wizard can be re-run from Settings > About > Reset Setup Wizard.

**Obsidian is optional.** If no Obsidian vault is found at the default path, the system falls back to `~/.atrophy/agents/<name>/` for all note, skill, and workspace operations. The `OBSIDIAN_AVAILABLE` flag in `config.py` controls this behaviour.

Once setup is done:
1. Creates `~/.atrophy/` directory structure and initializes the SQLite database (stored at `~/.atrophy/agents/<name>/data/memory.db`)
2. Starts a new session
3. In `--gui` mode, generates an opening line with time-of-day context and randomised style. In `--app` mode, starts silent — no window until you activate it.

Just start talking. The companion uses Claude Code as its inference backend, with an MCP memory server that gives it access to 34 tools: memory search, threads, observations, Obsidian notes, Telegram, reminders, timers, task scheduling, artefact creation, agent management, and more.

On subsequent runs, it resumes its Claude CLI session and checks recent memory for anything worth surfacing.

---

## What's Next

- [01 - Creating Agents](01%20-%20Creating%20Agents.md) -- build a second agent with its own identity and voice
- [02 - Configuration Reference](02%20-%20Configuration%20Reference.md) -- every knob and switch
- [03 - Scheduling Jobs](03%20-%20Scheduling%20Jobs.md) -- autonomous behaviour (heartbeats, introspection, evolution)
- [04 - Memory System](04%20-%20Memory%20System.md) -- how the companion remembers

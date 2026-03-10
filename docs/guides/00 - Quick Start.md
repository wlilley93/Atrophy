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

The project uses a `.env` file for secrets and configuration. Create one from the template or manually:

```bash
cp .env.example .env  # if available, or create .env manually
```

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

## Configure .env

At minimum, add your ElevenLabs key if you want voice output. Everything else has defaults.

```
ELEVENLABS_API_KEY=...        # For TTS
ELEVENLABS_VOICE_ID=...      # Voice to use (from ElevenLabs voice library)
TELEGRAM_BOT_TOKEN=...       # Optional: for unprompted outreach
TELEGRAM_CHAT_ID=...         # Optional: your Telegram chat ID
OBSIDIAN_VAULT=...           # Optional: path to Obsidian vault root
AVATAR_ENABLED=false         # Set true if LivePortrait is installed
```

See [02 - Configuration Reference](02%20-%20Configuration%20Reference.md) for the full list of environment variables.

---

## Run

Three modes, from simplest to full-featured:

```bash
python main.py --text         # Text-only (no mic, no TTS — just type)
python main.py --cli          # Voice + text (needs whisper.cpp + mic)
python main.py --gui          # Full GUI with avatar window
```

The GUI mode is the primary way to run the companion as an app. It provides a full window with video avatar, streaming text overlay, floating input bar, and a settings panel for live configuration.

You can also specify an agent explicitly:

```bash
python main.py --agent companion --text
# or
AGENT=companion python main.py --gui
```

The default agent is `companion`.

---

## The GUI

When running with `--gui`, the window has a row of icon buttons in the top-right corner:

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
| Escape | Close the chat overlay |

The **Settings panel** (gear icon or Cmd+,) lets you adjust all configuration live -- voice settings, input mode, inference effort, memory parameters, heartbeat schedule, wake words, and more. Changes can be applied immediately to the running session, or saved to `.env` and `agent.json` for persistence across restarts.

---

## First Session

On first run, the companion:

1. Initializes its SQLite database from `db/schema.sql` (stored at `agents/companion/data/memory.db`)
2. Starts a new session
3. Delivers its opening line (configured in `agents/companion/data/agent.json`)

Just start talking. The companion uses Claude Code as its inference backend, with an MCP memory server that gives it access to its own memory database. It can remember, search, create threads, write observations, and bookmark moments.

On subsequent runs, it resumes its Claude CLI session and checks recent memory for anything worth surfacing.

---

## What's Next

- [01 - Creating Agents](01%20-%20Creating%20Agents.md) -- build a second agent with its own identity and voice
- [02 - Configuration Reference](02%20-%20Configuration%20Reference.md) -- every knob and switch
- [03 - Scheduling Jobs](03%20-%20Scheduling%20Jobs.md) -- autonomous behaviour (heartbeats, introspection, evolution)
- [04 - Memory System](04%20-%20Memory%20System.md) -- how the companion remembers

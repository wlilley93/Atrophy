# Quick Start

Get The Atrophied Mind running on your machine. This guide covers the minimum path from clone to conversation.

---

## Prerequisites

- **Node.js 20+** and **pnpm** (package manager)
- **macOS** (required for voice features - push-to-talk, TTS via ElevenLabs, STT via whisper.cpp with Metal acceleration, vibrancy window effects)
- **Claude Code CLI** installed and authenticated (`claude` command available in your shell)

Optional:

- **Python 3.12+** - required only for MCP servers (memory, Google) which are spawned by the Claude CLI as subprocesses
- **ElevenLabs API key** - for text-to-speech (your agent can speak)
- **Telegram bot** - for notifications and unprompted outreach
- **Obsidian vault** - agents write journal entries, reflections, and notes here
- **Google account** - for Gmail and Google Calendar integration (OAuth credentials are bundled; just authorize in-browser)

---

## Clone and Install

```bash
git clone <repo-url>
cd atrophy-app-electron
pnpm install
pnpm rebuild        # Rebuilds native deps (better-sqlite3) for Electron
```

The project uses environment variables for secrets and `~/.atrophy/config.json` for persistent settings. Secrets go in `~/.atrophy/.env`:

```bash
mkdir -p ~/.atrophy
touch ~/.atrophy/.env   # Create manually and add secrets
```

On first run, the system creates `~/.atrophy/` automatically with the user data directory structure.

---

## Build whisper.cpp (for voice input)

Voice mode requires a local whisper.cpp build with Metal support. Skip this if you only want text input.

```bash
cd vendor/whisper.cpp
cmake -B build -DWHISPER_METAL=ON
cmake --build build --config Release
```

Then download a model:

```bash
cd models && bash download-ggml-model.sh tiny.en
```

The binary ends up at `vendor/whisper.cpp/build/bin/whisper-cli` and the model at `vendor/whisper.cpp/models/ggml-tiny.en.bin`. Both paths are configured automatically in `src/main/config.ts`.

---

## Configure Secrets

At minimum, add your ElevenLabs key if you want voice output. Everything else has defaults.

Add your API keys to `~/.atrophy/.env`:

```
ELEVENLABS_API_KEY=...        # For TTS
ELEVENLABS_VOICE_ID=...      # Voice to use (from ElevenLabs voice library)
TELEGRAM_BOT_TOKEN=...       # Optional: for unprompted outreach
TELEGRAM_CHAT_ID=...         # Optional: your Telegram chat ID
OBSIDIAN_VAULT=...           # Optional: path to Obsidian vault root
AVATAR_ENABLED=true          # Set true to enable animated avatar
```

Non-secret settings can also be saved via the GUI settings panel, which writes to `~/.atrophy/config.json`.

### Google Integration (Optional)

To enable Gmail and Google Calendar tools:

```bash
python scripts/google_auth.py
```

OAuth client credentials are bundled with the app - no Google Cloud Console setup needed. The script opens a browser where you authorize access, then saves `token.json` to `~/.atrophy/.google/` with strict permissions (directory 700, file 600). The Google MCP server loads automatically on next launch.

Alternatively, the first-launch setup wizard handles Google setup - just say "yes" when prompted and the browser opens for authorization.

See [02 - Configuration Reference](02%20-%20Configuration%20Reference.md) for the full list of configuration options.

---

## Run

Three modes:

```bash
pnpm dev                          # Development (electron-vite dev server with HMR)
pnpm dev -- --app                 # Menu bar mode in development
pnpm dev -- --server              # HTTP API mode in development
pnpm dev -- --server --port 8080  # Custom port
```

In a packaged `.app`, the mode is determined by launch arguments:

- **`--app`** (default) - Menu bar app. Hides from the Dock. Starts silent - no window, no voice, no opening line. Click the tray icon or press Cmd+Shift+Space when ready.
- **`--gui`** - Full GUI. Shows the window immediately with an opening line.
- **`--server`** - Headless HTTP API. REST endpoints (`/chat`, `/chat/stream`, `/memory/search`, `/memory/threads`, `/session`) secured by auto-generated bearer token.

The server binds to `127.0.0.1` by default. To expose it on all network interfaces (for access from other machines on your LAN), pass `--host 0.0.0.0`:

```bash
pnpm dev -- --server --host 0.0.0.0              # All interfaces, default port
pnpm dev -- --server --host 0.0.0.0 --port 8080  # All interfaces, custom port
```

**Warning:** Binding to `0.0.0.0` exposes the API to your entire network. The bearer token still protects all endpoints except `/health`, but treat this as a development convenience - not a production security posture.

There are no CLI or text-only modes in the Electron app. For terminal-based interaction, use the server mode API (see [05 - API Guide](05%20-%20API%20Guide.md)) or the original Python app.

You can also specify an agent explicitly using the `AGENT` environment variable:

```bash
AGENT=oracle pnpm dev
AGENT=xan pnpm dev -- --app
```

There is no `--agent` command-line flag - agent selection is done exclusively through the `AGENT` environment variable. The default agent is `xan`.

---

## The GUI

When running with `--gui` or `--app`, the window has a row of icon buttons in the top-right corner:

| Button | Icon | Action | Shortcut |
|--------|------|--------|----------|
| Settings | Gear | Opens a full-screen settings overlay where you can configure everything in-app | Cmd+, |
| Wake | Microphone with waves | Toggles wake word detection on/off (green when active). When enabled, a background process continuously listens via whisper.cpp. On hearing a wake word, it plays a pop sound and starts a one-shot recording - no PTT needed. This is independent of the mic/PTT button. | Cmd+Shift+W |
| Minimize | Minus | Minimizes to system tray | Cmd+M |
| Mute | Speaker | Toggles TTS audio playback (muted = text only, no speech) | - |
| Eye | Eye | Collapses to a minimal input-only bar | - |

Additional keyboard shortcuts:

| Shortcut | Action |
|----------|--------|
| Cmd+Shift+Space | Show/hide the app window (works globally, even when the app is not focused - registered via Electron globalShortcut) |
| Cmd+K | Toggle the canvas overlay (HTML content panel) |
| Cmd+C | Copy selected text, or last agent message if nothing is selected |
| Cmd+Up / Cmd+Down | Cycle through enabled agents (fade-out/fade-in transition) |
| Escape | Close the chat overlay |

The **Settings panel** (gear icon or Cmd+,) lets you adjust all configuration live - voice settings, input mode, inference effort, memory parameters, heartbeat schedule, wake words, and more. Changes can be applied immediately to the running session, or saved to `~/.atrophy/config.json` and `agent.json` for persistence across restarts.

---

## First Session

On first run (GUI/app modes), Xan checks for Claude Code CLI availability, then launches the **setup wizard** if `setup_complete` is not set in `~/.atrophy/config.json`. The wizard is a conversational AI-guided flow:

1. **Welcome** - asks your name, sets `user_name` in config
2. **Capability showcase** - Xan introduces itself and delivers a dynamic sweep of what the system can do: memory, voice, autonomy, self-evolution, email/calendar, Telegram, multi-agent, avatar, identity. The opening is designed to feel like powering on something serious - not a product tour, but a glimpse of what's running underneath
3. **Choice** - build a companion agent now, or skip. If you skip, Xan marks setup complete and becomes your default agent. You can build agents later via Settings > Agents > New Agent, or by asking Xan
4. **Agent creation** (if not skipped) - Xan extracts identity through conversation, walking through voice, appearance, and autonomy preferences, then scaffolds the agent
5. **Avatar generation** (if not skipped) - if appearance is enabled, generates face candidates via Flux and optionally video clips via Kling

After the wizard completes, `setup_complete: true` is written to `~/.atrophy/config.json`. The wizard can be re-run from Settings > About > Reset Setup Wizard.

**Obsidian is optional.** If no Obsidian vault is found at the default path, the system falls back to `~/.atrophy/agents/<name>/` for all note, skill, and workspace operations. The `OBSIDIAN_AVAILABLE` flag in `src/main/config.ts` controls this behaviour.

Once setup is done:
1. Creates `~/.atrophy/` directory structure and initializes the SQLite database (stored at `~/.atrophy/agents/<name>/data/memory.db`)
2. Starts a new session
3. In `--gui` mode, generates an opening line with time-of-day context and randomised style. In `--app` mode, starts silent - no window until you activate it.

Just start talking. Your agent uses Claude Code as its inference backend, with an MCP memory server that gives it access to 41 tools: memory search, threads, observations, Obsidian notes, Telegram, reminders, timers, task scheduling, artefact creation, agent management, custom tool building, and more.

On subsequent runs, it resumes its Claude CLI session and checks recent memory for anything worth surfacing.

---

## Building for Distribution

```bash
pnpm build                    # Compile TypeScript + bundle renderer via Vite
pnpm dist:mac                 # Build + create DMG and ZIP for macOS
```

The resulting DMG is output to the `dist/` directory. See [10 - Building and Distribution](10%20-%20Building%20and%20Distribution.md) for the full build and release workflow.

---

## What's Next

- [01 - Creating Agents](01%20-%20Creating%20Agents.md) - build a second agent with its own identity and voice
- [02 - Configuration Reference](02%20-%20Configuration%20Reference.md) - every knob and switch
- [03 - Scheduling Jobs](03%20-%20Scheduling%20Jobs.md) - autonomous behaviour (heartbeats, introspection, evolution)
- [04 - Memory System](04%20-%20Memory%20System.md) - how agents remember

# CLI Guide

Every command-line interface and script in The Atrophied Mind. Covers running the app, managing agents, scheduling jobs, building for distribution, and maintaining the database.

---

## Running the App

The entry point is `main.py`. Five modes, one binary.

### Menu Bar App (primary)

```bash
python main.py --app
```

Hides from the Dock. Lives in the macOS menu bar. Starts silent — no window, no voice, no opening line. Click the tray icon or press **Cmd+Shift+Space** to summon the window. This is the mode you want for daily use.

### Full GUI

```bash
python main.py --gui
```

Opens the PyQt5 window immediately with an AI-generated opening line. Shows avatar if enabled. Use this when you want the full visual experience without the menu-bar-only behaviour.

### CLI (voice + text)

```bash
python main.py --cli
```

Terminal loop. Type and press Enter, or press Enter then hold Ctrl to speak. TTS plays responses aloud. This is the default if you pass no flags.

### Text Only

```bash
python main.py --text
```

Terminal loop, no microphone, no TTS. Pure text. Useful for SSH sessions, low-bandwidth environments, or when you don't want audio.

### HTTP Server

```bash
python main.py --server
python main.py --server --port 8080
python main.py --server --host 0.0.0.0 --port 8080
```

Headless REST API. Runs Flask on `127.0.0.1:5000` by default. Bearer token auth on all endpoints except `/health`. Token auto-generated on first run and stored at `~/.atrophy/server_token`.

Endpoints:

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Status check, returns agent name |
| `/chat` | POST | Yes | Send message, get full response |
| `/chat/stream` | POST | Yes | Send message, get SSE stream |
| `/memory/search` | GET | Yes | Search memory (`?q=...&limit=5`) |
| `/memory/threads` | GET | Yes | List active conversation threads |
| `/session` | GET | Yes | Current session info |

Example:

```bash
TOKEN=$(cat ~/.atrophy/server_token)
curl -X POST http://localhost:5000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "How are you?"}'
```

### Selecting an Agent

Any mode accepts `--agent` or the `AGENT` environment variable:

```bash
python main.py --app --agent oracle
AGENT=oracle python main.py --gui
AGENT=general_montgomery python main.py --text
```

If neither is set, defaults to `companion`.

---

## Environment Variables

Configuration is driven by env vars, `~/.atrophy/config.json`, and per-agent `agent.json` manifests. Env vars always win. Set them in `.env` at the project root or `~/.atrophy/.env`.

### Core

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT` | `companion` | Which agent to run |
| `INPUT_MODE` | `dual` | `voice`, `text`, or `dual` |
| `CLAUDE_BIN` | `claude` | Path to Claude Code binary |
| `CLAUDE_EFFORT` | `medium` | Inference effort: `low`, `medium`, `high` |
| `ADAPTIVE_EFFORT` | `true` | Auto-adjust effort by query complexity |

### Voice & TTS

| Variable | Default | Purpose |
|----------|---------|---------|
| `TTS_BACKEND` | `elevenlabs` | TTS engine (`elevenlabs`, `fal`, `say`) |
| `ELEVENLABS_API_KEY` | — | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | — | Voice ID for TTS |
| `FAL_KEY` | — | Fal.ai API key (images, video, optional TTS) |

### Display

| Variable | Default | Purpose |
|----------|---------|---------|
| `AVATAR_ENABLED` | `false` | Enable animated avatar in GUI |
| `WAKE_WORD_ENABLED` | `false` | Enable ambient wake word detection |

### Paths

| Variable | Default | Purpose |
|----------|---------|---------|
| `OBSIDIAN_VAULT` | `~/Library/.../The Atrophied Mind` | Obsidian vault path |
| `ATROPHY_BUNDLE` | Project directory | Where the code lives |
| `ATROPHY_DATA` | `~/.atrophy` | User data directory |

### Channels

| Variable | Default | Purpose |
|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID for notifications |

---

## Agent Management

### Creating an Agent (Interactive)

```bash
python scripts/create_agent.py
```

Walks through a multi-section questionnaire: services/API keys, identity (name, origin story, character), boundaries, voice, appearance, channels, heartbeat schedule, autonomy features, and tool access. Generates all scaffolding — `agent.json`, system prompt, soul.md, heartbeat checklist, Obsidian vault structure, and database.

Skip the name question:

```bash
python scripts/create_agent.py --name oracle
```

### Creating an Agent (Non-Interactive)

```bash
python scripts/create_agent.py --config agent_config.json
```

Reads a JSON config file and scaffolds the agent without prompts. Useful for scripted setups or CI.

### Switching Agents at Runtime

In GUI/app mode:

- **Cmd+Up / Cmd+Down** — cycle through enabled agents
- **Tray icon → Agents** — pick from menu bar submenu
- **Settings panel → AGENTS section** — switch, mute, or disable

From the command line, set `AGENT` before launching:

```bash
AGENT=oracle python main.py --app
```

Agent state (muted, enabled) persists in `.agent_states.json`.

---

## Cron Jobs

Scheduled tasks use macOS launchd. Each agent has its own job definitions in `scripts/agents/<agent>/jobs.json`. All commands accept `--agent <name>` to target a specific agent (defaults to `AGENT` env var or `companion`).

### List Jobs

```bash
python scripts/cron.py list
python scripts/cron.py --agent oracle list
```

Shows name, schedule, script path, and whether the job is installed.

### Add a Job

```bash
python scripts/cron.py add introspect '17 3 * * *' scripts/agents/companion/run_task.py -d "Nightly introspection"
python scripts/cron.py add introspect '17 3 * * *' scripts/agents/companion/run_task.py --install  # add and install immediately
```

Cron format: `minute hour day-of-month month day-of-week`. Standard five-field syntax.

### Edit a Job's Schedule

```bash
python scripts/cron.py edit introspect '0 6 * * *'
```

If the job is already installed, it's automatically reinstalled with the new schedule.

### Remove a Job

```bash
python scripts/cron.py remove introspect
```

Uninstalls from launchd and removes from `jobs.json`.

### Run a Job Manually

```bash
python scripts/cron.py run introspect
```

Executes the job's script immediately, in the foreground. Useful for testing.

### Install All Jobs

```bash
python scripts/cron.py install
```

Generates launchd plists for all jobs in `jobs.json` and loads them via `launchctl`. Plists go to `~/Library/LaunchAgents/com.atrophiedmind.<agent>.<name>.plist`. Logs go to `logs/<agent>/`.

### Uninstall All Jobs

```bash
python scripts/cron.py uninstall
```

Unloads and removes all plists for the agent.

### Job Types

Jobs support two scheduling types in `jobs.json`:

- **`calendar`** (default): Uses `StartCalendarInterval` with a cron string. For fixed-time schedules.
- **`interval`**: Uses `StartInterval` with `interval_seconds`. For repeat-every-N-seconds jobs (e.g., reminder checker every 60s).

---

## App Installation

### Building the .app

```bash
python scripts/build_app.py              # Build to build/
python scripts/build_app.py --install    # Build and install to ~/Applications
python scripts/build_app.py --open       # Build, install, and launch
python scripts/build_app.py --dmg        # Build and create a DMG for distribution
```

The `.app` is a thin launcher shell script. The actual code lives in `~/.atrophy/src/`, auto-updated from GitHub on each launch (downloads a zip archive — no git required). A bootstrap snapshot is bundled inside the `.app` for offline first-run.

Architecture:

```
~/Applications/Atrophy.app   — launcher (rarely changes)
~/.atrophy/src/              — source (auto-updates from GitHub)
~/.atrophy/venv/             — Python virtual environment
~/.atrophy/agents/           — user data (never overwritten)
```

### Login Item (Start at Boot)

```bash
python scripts/install_app.py install    # Register as login item
python scripts/install_app.py uninstall  # Remove login item
python scripts/install_app.py status     # Check if installed and running
```

Requires the `.app` to be built and installed first. Creates a launchd plist at `~/Library/LaunchAgents/com.atrophiedmind.companion.plist`. The app starts at login and restarts automatically if it crashes.

Logs: `~/.atrophy/logs/launchd.stdout.log` and `launchd.stderr.log`.

---

## Database

### Initialise

```bash
python scripts/init_db.py
```

Creates the SQLite database (path defined by `DB_PATH` in config — typically `~/.atrophy/agents/<agent>/data/memory.db`), runs the schema from `db/schema.sql`, and seeds the identity layer with an initial snapshot.

Run this once after setup. Safe to run again — `init_db()` is idempotent for schema creation.

### Reindex Embeddings

```bash
python scripts/reindex.py                    # Reindex all tables
python scripts/reindex.py observations       # Reindex just one table
python scripts/reindex.py summaries turns    # Reindex specific tables
```

Regenerates vector embeddings for all rows in the specified tables (or all searchable tables). Safe to run multiple times — overwrites existing embeddings. Run after initial setup, or after changing the embedding model.

### Review Memory

```bash
python scripts/review_memory.py
```

Read-only inspection of the memory database. Shows:

- Last 10 sessions (with timestamps, summaries, notable flags)
- Total turn count
- Latest identity snapshot
- Active conversation threads
- Context injection preview
- Recent observations (pending vs incorporated)

---

## Utility Scripts

### Migrate .env Settings

```bash
python scripts/migrate_env.py
```

Separates secrets from settings. Non-secret keys in `.env` are moved to `~/.atrophy/config.json`. Secret keys (anything matching `*_KEY`, `*_SECRET`, `*_TOKEN`, `*_PASSWORD`) stay in `.env`. Safe to run multiple times — only migrates keys not already in `config.json`.

### Rebuild Ambient Loop

```bash
python scripts/rebuild_ambient_loop.py                        # Current agent
python scripts/rebuild_ambient_loop.py --agent companion      # Specific agent
AGENT=oracle python scripts/rebuild_ambient_loop.py           # Via env var
```

Concatenates all `loop_*.mp4` segments in the agent's loops directory into a single `ambient_loop.mp4` using ffmpeg. Requires `ffmpeg` installed.

### Generate Loop Segment

```bash
python scripts/generate_loop_segment.py --agent companion --name contemplation
python scripts/generate_loop_segment.py --agent companion --name curiosity --prompt "A gentle look of curiosity crosses their face"
```

Full avatar video pipeline: generates a paired clip sequence (neutral to expression, expression back to neutral) via Kling 3.0 on fal.ai, crossfades them into a seamless loop, and rebuilds the master `ambient_loop.mp4`. Requires `FAL_KEY` and `ffmpeg`.

If `--prompt` is not provided, reads from a request file at `~/.atrophy/agents/<agent>/avatar/.loop_requests/<name>.json`.

---

## Common Workflows

### First-Time Setup

```bash
pip install -r requirements.txt
python scripts/create_agent.py          # Create your first agent
python main.py --text                   # Test in text mode
python main.py --app                    # Run for real
```

### Deploy as Menu Bar App

```bash
python scripts/build_app.py --install   # Build and install to ~/Applications
python scripts/install_app.py install   # Start at login
```

### Set Up Scheduled Tasks

```bash
python scripts/cron.py list             # See what's configured
python scripts/cron.py install          # Install all jobs to launchd
python scripts/cron.py run introspect   # Test a job manually
```

### Inspect Memory After a Session

```bash
python scripts/review_memory.py         # Overview
python scripts/reindex.py               # Refresh embeddings if needed
```

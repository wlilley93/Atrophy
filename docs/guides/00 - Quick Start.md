# Quick Start

Get The Atrophied Mind running on your machine. This guide covers the minimum path from clone to conversation, plus troubleshooting for common issues.

---

## Prerequisites

### Required

| Dependency | Minimum Version | How to Check | Notes |
|------------|----------------|--------------|-------|
| **Node.js** | 20.0+ | `node --version` | LTS recommended. Used for Electron runtime and build tooling. |
| **pnpm** | 10.18+ | `pnpm --version` | Package manager. Install via `npm install -g pnpm` or `corepack enable`. The project pins `pnpm@10.18.2` in `package.json`. |
| **macOS** | 13 Ventura+ | `sw_vers` | Required for vibrancy window effects, Metal-accelerated whisper.cpp, `afplay` TTS playback, `launchctl` cron management, and native tray/dock integration. |
| **Claude Code CLI** | Latest | `claude --version` | The inference engine. Must be installed and authenticated. The app spawns `claude` as a subprocess with `--output-format stream-json`. |

### Optional

| Dependency | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.12+ | Required only for MCP servers (`memory_server.py`, `google_server.py`) which are spawned by the Claude CLI as subprocesses. Also required for standalone launchd jobs (heartbeat, observer, evolve). The app auto-detects Python via `PYTHON_PATH` env var, then tries `python3`, `/opt/homebrew/bin/python3`, `/usr/local/bin/python3` in order. |
| **Xcode Command Line Tools** | Latest | Required for compiling `better-sqlite3` native module. Install via `xcode-select --install`. |
| **CMake** | 3.20+ | Required only if building whisper.cpp for voice input. Install via `brew install cmake`. |
| **ElevenLabs API key** | - | For text-to-speech. Your agent can speak. Get a key at elevenlabs.io. |
| **Telegram bot** | - | For notifications and unprompted outreach. Create via @BotFather. |
| **Obsidian vault** | - | Agents write journal entries, reflections, and notes here. Falls back to `~/.atrophy/` if unavailable. |
| **Google account** | - | For Gmail and Google Calendar integration via MCP. OAuth is handled by bundled scripts or `gws` CLI. |

---

## Clone and Install

```bash
git clone <repo-url>
cd atrophy-app-electron
pnpm install
pnpm rebuild
```

Expected output from `pnpm rebuild`:

```
> atrophy@0.1.2 rebuild
> electron-rebuild -f -w better-sqlite3

- Searching for modules in /path/to/atrophy-app-electron/node_modules
- Found better-sqlite3 at /path/to/node_modules/better-sqlite3
- Rebuilding better-sqlite3 for Electron 34.x
- Build complete
```

If `pnpm rebuild` fails, you likely need Xcode Command Line Tools:

```bash
xcode-select --install
```

Then retry `pnpm rebuild`.

---

## User Data Directory

The system stores all runtime data under `~/.atrophy/`. On first run, `ensureUserData()` in `src/main/config.ts` creates the following structure:

```
~/.atrophy/
  config.json              # User settings (created empty if missing)
  .env                     # Secrets - API keys, tokens (mode 0600)
  server_token             # HTTP API auth token (auto-generated)
  agent_states.json        # Per-agent muted/enabled state + last active
  agents/
    xan/                   # Default agent
      data/
        agent.json         # Agent manifest (copied from bundle on first run)
        memory.db          # SQLite database
        .emotional_state.json
        .user_status.json
        .message_queue.json
        .opening_cache.json
      avatar/              # Avatar assets (copied from bundle)
      prompts/             # Agent prompts (system_prompt.md, soul.md, etc.)
  models/                  # Cached embedding models (Transformers.js WASM)
  logs/                    # Job execution logs
  .google/                 # Google OAuth tokens (if configured)
```

You do not need to create this manually. The app handles it on first launch. If you want to pre-configure secrets before the first run:

```bash
mkdir -p ~/.atrophy
cat > ~/.atrophy/.env << 'EOF'
ELEVENLABS_API_KEY=your-key-here
EOF
chmod 600 ~/.atrophy/.env
```

### Data migration

On first run, bundled agent data (from `agents/` in the project root) is automatically migrated to `~/.atrophy/agents/`. The migration copies data files and avatar assets but skips `agent.json` (the manifest stays in the bundle as the read-only source of truth). Files that already exist at the destination are never overwritten, so user modifications are preserved.

---

## Build whisper.cpp (for voice input)

Voice mode requires a local whisper.cpp build with Metal support. Skip this section if you only want text input.

```bash
cd vendor/whisper.cpp
cmake -B build -DWHISPER_METAL=ON
cmake --build build --config Release
```

Expected output ends with:

```
[100%] Built target whisper-cli
```

Then download a model:

```bash
cd models && bash download-ggml-model.sh tiny.en
```

This downloads `ggml-tiny.en.bin` (approximately 75MB) to `vendor/whisper.cpp/models/`.

The binary ends up at `vendor/whisper.cpp/build/bin/whisper-cli` and the model at `vendor/whisper.cpp/models/ggml-tiny.en.bin`. Both paths are resolved automatically in `src/main/config.ts`:

```
WHISPER_BIN  = <BUNDLE_ROOT>/vendor/whisper.cpp/build/bin/whisper-cli
WHISPER_MODEL = <BUNDLE_ROOT>/vendor/whisper.cpp/models/ggml-tiny.en.bin
```

### Troubleshooting whisper.cpp

**CMake not found**: Install via `brew install cmake`.

**Metal errors during build**: Ensure Xcode Command Line Tools are installed (`xcode-select --install`). Metal support requires macOS 13+.

**Model download fails**: Download manually from https://huggingface.co/ggerganov/whisper.cpp and place in `vendor/whisper.cpp/models/`.

**STT returns empty text**: Check that the model file exists at the expected path. Run the binary directly to test: `vendor/whisper.cpp/build/bin/whisper-cli -m vendor/whisper.cpp/models/ggml-tiny.en.bin -f test.wav`

---

## Configure Secrets

Secrets are stored in `~/.atrophy/.env`. The file uses simple `KEY=value` format (one per line, `#` comments allowed, surrounding quotes stripped). Only whitelisted keys are accepted when saved via the setup wizard:

| Key | Purpose |
|-----|---------|
| `ELEVENLABS_API_KEY` | ElevenLabs TTS API key |
| `FAL_KEY` | Fal.ai API key (fallback TTS) |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `OPENAI_API_KEY` | OpenAI API key (if needed by MCP servers) |
| `ANTHROPIC_API_KEY` | Anthropic API key (if needed by MCP servers) |

Example `.env` file:

```
ELEVENLABS_API_KEY=sk_abc123...
TELEGRAM_BOT_TOKEN=7123456789:AAH...
```

Non-secret settings (voice ID, playback rate, window size, etc.) are saved via the GUI settings panel to `~/.atrophy/config.json` and per-agent `agent.json`.

### Google Integration (Optional)

To enable Gmail and Google Calendar tools:

```bash
python scripts/google_auth.py
```

OAuth client credentials are bundled with the app - no Google Cloud Console setup needed. The script opens a browser where you authorize access, then saves `token.json` to `~/.atrophy/.google/` with strict permissions (directory 700, file 600). The Google MCP server loads automatically on next launch.

The app also checks for `gws` CLI authentication. If the `gws` binary is found on your PATH, the app runs `gws auth status` and parses the JSON output to determine if Google is configured. This is an alternative to the legacy OAuth flow.

Alternatively, the first-launch setup wizard handles Google setup - just say "yes" when prompted and the browser opens for authorization.

See [02 - Configuration Reference](02%20-%20Configuration%20Reference.md) for the full list of configuration options.

---

## Environment Variables for Development

These environment variables affect the app's behavior. Set them before launching:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT` | `xan` | Which agent to load on startup. Must match a directory name under `agents/` or `~/.atrophy/agents/`. |
| `ATROPHY_DATA` | `~/.atrophy` | Root directory for all runtime data. Override for testing with isolated data. |
| `PYTHON_PATH` | (auto-detected) | Path to Python 3 binary for MCP servers and scripts. |
| `CLAUDE_BIN` | `claude` | Path to Claude Code CLI binary. |
| `CLAUDE_EFFORT` | `medium` | Inference effort level: `low`, `medium`, or `high`. |
| `ADAPTIVE_EFFORT` | `true` | Auto-adjust effort by query complexity (short greetings get `low`, complex questions get `high`). |
| `OBSIDIAN_VAULT` | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind` | Path to Obsidian vault root. Set if your vault is in a non-default location. |
| `ELECTRON_RENDERER_URL` | (unset) | Set automatically by `pnpm dev`. When set, the main process loads the renderer from this URL instead of the built HTML file. Also disables auto-updater checks. |

---

## Run

Three modes:

```bash
pnpm dev                          # GUI mode (default) - Svelte window with HMR
pnpm dev -- --app                 # Menu bar mode - hidden dock, tray icon
pnpm dev -- --server              # HTTP API mode - headless, port 5000
pnpm dev -- --server --port 8080  # Custom port
```

### How `pnpm dev` works

The dev script (`scripts/dev.ts`) starts two processes:

1. A standalone Vite dev server for the renderer on port 5173 (with HMR for instant Svelte updates)
2. `electron-vite dev` for the main process and preload (with `ELECTRON_RENDERER_URL` pointing to the Vite server)

This is a workaround for an electron-vite 5 bug that drops Svelte plugins during config resolution. The renderer uses `vite.renderer.config.ts` separately.

### Mode details

| Mode | Flag | Dock | Window | TTS | Voice | Opening Line |
|------|------|------|--------|-----|-------|-------------|
| GUI | (none) | Visible | Shown immediately | Yes | Yes | Static from manifest |
| Menu bar | `--app` | Hidden | Hidden until activated | Yes | Yes | None until activated |
| Server | `--server` | Hidden | None | No | No | N/A |

In menu bar mode:
- Click the tray icon to show/hide the window
- Press `Cmd+Shift+Space` globally to toggle the window
- The tray uses a brain icon (`resources/icons/menubar_brain@2x.png`) as a template image, with a procedural orb fallback

You can specify an agent explicitly:

```bash
AGENT=oracle pnpm dev
AGENT=xan pnpm dev -- --app
```

There is no `--agent` command-line flag - agent selection is done exclusively through the `AGENT` environment variable. The default agent is `xan`.

### Expected startup output

```
  Renderer dev server: http://localhost:5173/

[atrophy] v0.1.2 | agent: xan | db: /Users/you/.atrophy/agents/xan/data/memory.db
```

---

## The GUI

When running with GUI or menu bar mode, the window has a row of icon buttons in the top-right corner:

| Button | Icon | Action | Shortcut |
|--------|------|--------|----------|
| Settings | Gear | Opens a full-screen settings overlay | Cmd+, |
| Wake | Microphone with waves | Toggles wake word detection on/off (green when active) | Cmd+Shift+W |
| Minimize | Minus | Minimizes to system tray | Cmd+M |
| Mute | Speaker | Toggles TTS audio playback (muted = text only) | - |
| Eye | Eye | Collapses to a minimal input-only bar | - |

Additional keyboard shortcuts:

| Shortcut | Action |
|----------|--------|
| Cmd+Shift+Space | Show/hide the app window (global - works even when unfocused) |
| Cmd+K | Toggle the canvas overlay (HTML content panel) |
| Cmd+C | Copy selected text, or last agent message if nothing is selected |
| Cmd+Up / Cmd+Down | Cycle through enabled agents (fade-out/fade-in transition) |
| Escape | Close the chat overlay |

The **Settings panel** (gear icon or Cmd+,) lets you adjust all configuration live - voice settings, input mode, inference effort, memory parameters, heartbeat schedule, wake words, and more. Changes can be applied immediately to the running session, or saved to `~/.atrophy/config.json` and `agent.json` for persistence across restarts.

---

## First Run Behavior

On first run, the app:

1. **Creates the user data directory** at `~/.atrophy/` with subdirectories for agents, logs, and models
2. **Writes an empty `config.json`** with mode 0600
3. **Migrates bundled agent data** to `~/.atrophy/agents/` (skips files that already exist)
4. **Loads the default agent** (`xan`) and initializes its SQLite database
5. **Checks for setup completion** by reading `setup_complete` from `~/.atrophy/config.json`

If `setup_complete` is not set (first run), the renderer launches the **setup wizard** - a conversational AI-guided flow:

1. **Welcome** - asks your name, sets `USER_NAME` in config
2. **Capability showcase** - Xan introduces itself and demonstrates the system's capabilities
3. **Choice** - build a companion agent now, or skip. If you skip, Xan marks setup complete and becomes your default agent
4. **Agent creation** (if not skipped) - Xan uses its metaprompt to extract identity through conversation (3-5 exchanges), then outputs an `AGENT_CONFIG` JSON block with display name, opening line, origin story, core nature, character traits, values, relationship dynamics, friction modes, and writing style
5. **Service setup** - optionally configure ElevenLabs, Telegram, and Google

After the wizard completes, `setup_complete: true` is written to `~/.atrophy/config.json`. The wizard can be re-run from Settings > About > Reset Setup Wizard.

**Obsidian is optional.** If no Obsidian vault is found at the default path (`~/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind`), the system falls back to `~/.atrophy/agents/<name>/` for all note, skill, and workspace operations. The `OBSIDIAN_AVAILABLE` flag in config controls this behavior.

---

## Config Resolution Order

The config system uses a three-tier resolution with different priority for user-level vs agent-level settings:

### User-level settings (e.g. `INPUT_MODE`, `CLAUDE_BIN`, `NOTIFICATIONS_ENABLED`)

1. Environment variables
2. `~/.atrophy/config.json`
3. Agent manifest (`agent.json`)
4. Built-in defaults

### Agent-level settings (e.g. `TTS_BACKEND`, `ELEVENLABS_VOICE_ID`, `HEARTBEAT_INTERVAL_MINS`)

1. Agent manifest (`agent.json`) - highest priority
2. Environment variables
3. `~/.atrophy/config.json`
4. Built-in defaults

This means per-agent settings in `agent.json` take precedence over global config, while user-level settings in `config.json` take precedence over agent defaults.

---

## Troubleshooting

### "claude: command not found"

The Claude Code CLI is not on your PATH. Install it following Anthropic's instructions, then verify with `claude --version`. You can also set `CLAUDE_BIN` to the full path:

```bash
CLAUDE_BIN=/path/to/claude pnpm dev
```

### "better-sqlite3 module not found" or native module errors

The native module needs to be rebuilt for your Electron version:

```bash
pnpm rebuild
```

If that fails, try:

```bash
npx electron-rebuild -f -w better-sqlite3
```

### "Python not found" warnings

MCP servers need Python 3. The app tries these paths in order:
1. `$PYTHON_PATH` environment variable
2. `python3` (from PATH)
3. `/opt/homebrew/bin/python3`
4. `/usr/local/bin/python3`

If none work, set `PYTHON_PATH` explicitly:

```bash
PYTHON_PATH=/path/to/python3 pnpm dev
```

### Window is blank / renderer not loading

In dev mode, the renderer Vite server must be running on port 5173. If you see a blank window:

1. Check that port 5173 is free (`lsof -i :5173`)
2. Try running `pnpm dev` again - the dev script starts the Vite server first, then launches Electron

### Database errors on startup

The SQLite database is stored at `~/.atrophy/agents/<name>/data/memory.db`. If it becomes corrupted:

```bash
# Back up and recreate
mv ~/.atrophy/agents/xan/data/memory.db ~/.atrophy/agents/xan/data/memory.db.bak
# The app will recreate it on next launch using db/schema.sql
```

### Menu bar icon not visible

In `--app` mode, the tray icon uses `resources/icons/menubar_brain@2x.png` as a macOS template image. If the icon files are missing, it falls back to a procedural orb icon. The global shortcut `Cmd+Shift+Space` always works regardless of icon visibility.

### Agent not switching

Agent cycling (`Cmd+Up`/`Cmd+Down`) skips disabled agents. Check `~/.atrophy/agent_states.json` to see which agents are enabled. An agent must have a `data/` directory with `agent.json` to be discovered.

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
- [03 - Scheduling Jobs](03%20-%20Scheduling%20Jobs.md) - autonomous behavior (heartbeats, introspection, evolution)
- [04 - Memory System](04%20-%20Memory%20System.md) - how agents remember
- [05 - API Guide](05%20-%20API%20Guide.md) - HTTP API for programmatic access

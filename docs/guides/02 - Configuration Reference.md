# Configuration Reference

All configuration flows through `src/main/config.ts`, which reads from four sources in order of priority:

1. **Environment variables** (from shell or `~/.atrophy/.env`)
2. **User config** (`~/.atrophy/config.json`) - persistent user settings
3. **Agent manifest** (`agents/<name>/data/agent.json`) - per-agent overrides
4. **Hardcoded defaults** in the `Config` class constructor

Environment variables win outright. For agent-specific settings (voice, heartbeat, telegram, display), the agent manifest takes priority over user config and defaults. The user config file at `~/.atrophy/config.json` replaces the old `.env`-based persistence for non-secret settings.

The `Config` class is a singleton, accessed via `getConfig()`. It provides typed properties for every configuration value. Call `reloadForAgent(name)` when switching agents to re-resolve all agent-specific settings.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT` | `xan` | Active agent name. Determines which `agents/<name>/` directory is loaded. |
| `INPUT_MODE` | `dual` | Input mode: `voice` (mic only), `text` (keyboard only), or `dual` (both). |
| `OBSIDIAN_VAULT` | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind` | Path to the Obsidian vault root. Used for journal entries, reflections, and notes. |
| `AVATAR_ENABLED` | `false` | Enable the animated avatar in GUI mode. Plays ambient video loops from `~/.atrophy/agents/<name>/avatar/`. |
| `TTS_BACKEND` | `elevenlabs` | TTS engine. Options: `elevenlabs`, `fal`, `macos`. Overridden by agent manifest `voice.tts_backend`. |
| `ELEVENLABS_API_KEY` | *(empty)* | ElevenLabs API key. Required for ElevenLabs TTS. |
| `ELEVENLABS_VOICE_ID` | *(empty)* | Default ElevenLabs voice ID. Overridden by agent manifest `voice.elevenlabs_voice_id`. |
| `ELEVENLABS_MODEL` | `eleven_v3` | ElevenLabs model name. Overridden by agent manifest. |
| `ELEVENLABS_STABILITY` | `0.5` | Voice stability (0.0-1.0). Lower values are more expressive. Overridden by agent manifest. |
| `ELEVENLABS_SIMILARITY` | `0.75` | Voice similarity boost (0.0-1.0). Overridden by agent manifest. |
| `ELEVENLABS_STYLE` | `0.35` | Style exaggeration (0.0-1.0). Overridden by agent manifest. |
| `TTS_PLAYBACK_RATE` | `1.12` | Audio playback speed multiplier. Overridden by agent manifest `voice.playback_rate`. |
| `FAL_VOICE_ID` | *(empty)* | Fal TTS voice ID (fallback TTS provider). Overridden by agent manifest. |
| `CLAUDE_BIN` | `claude` | Path to the Claude Code CLI binary. Change if `claude` is not on your PATH. |
| `CLAUDE_EFFORT` | `medium` | Default inference effort level for Claude. Options: `low`, `medium`, `high`. |
| `ADAPTIVE_EFFORT` | `true` | Auto-adjust inference effort based on conversation topic complexity. |
| `WAKE_WORD_ENABLED` | `false` | Enable background wake word detection. When enabled, a background process continuously listens via whisper.cpp. On hearing a wake word, it plays a pop sound and starts a one-shot recording - no PTT button press needed. This is independent of the mic/PTT system. Can also be toggled in the GUI via the wake word button (Cmd+Shift+W). |
| `HEARTBEAT_ACTIVE_START` | `9` | Hour (0-23) when heartbeat checks begin. Overridden by agent manifest. |
| `HEARTBEAT_ACTIVE_END` | `22` | Hour (0-23) when heartbeat checks stop. Overridden by agent manifest. |
| `HEARTBEAT_INTERVAL_MINS` | `30` | Minutes between heartbeat evaluations. Overridden by agent manifest. |
| `TELEGRAM_BOT_TOKEN` | *(empty)* | Default Telegram bot token. Per-agent tokens use agent-specific env var names (e.g. `TELEGRAM_BOT_TOKEN_COMPANION`). |
| `TELEGRAM_CHAT_ID` | *(empty)* | Default Telegram chat ID. Per-agent chat IDs use agent-specific env var names. |
| `NOTIFICATIONS_ENABLED` | `true` | Enable macOS native notifications (reminders, timer completion, etc.). |
| `GOOGLE_CONFIGURED` | *(auto)* | Set automatically to `true` when `~/.atrophy/.google/token.json` exists or `gws auth status` reports active credentials. Controls whether the Google MCP server is loaded. Not set manually. |
| `PYTHON_PATH` | *(auto-detected)* | Path to the Python 3 binary used for MCP servers. Auto-detected via `which python3` or common paths (`/opt/homebrew/bin/python3`, `/usr/local/bin/python3`). |
| `ATROPHY_DATA` | `~/.atrophy` | Root user data directory. Override to use a custom location. |

---

## User Config (~/.atrophy/config.json)

Persistent settings saved via the GUI settings panel. Same keys as environment variables but stored in JSON. Created automatically on first run.

```json
{
  "CLAUDE_EFFORT": "high",
  "INPUT_MODE": "voice",
  "WAKE_WORD_ENABLED": "true"
}
```

Settings here are overridden by environment variables but take precedence over defaults.

Special keys:

| Key | Type | Description |
|-----|------|-------------|
| `setup_complete` | boolean | Set to `true` after the first-launch setup wizard completes. Reset to `false` (or remove) to re-run the wizard. |
| `user_name` | string | The user's name, set during setup. Takes precedence over agent manifest `user_name` when present. |

---

## Agent Manifest (agent.json)

The agent manifest lives at `agents/<name>/data/agent.json` (in the bundle or `~/.atrophy/agents/<name>/data/agent.json` for user-installed agents). It provides per-agent overrides for voice, display, heartbeat, and channel configuration.

See [01 - Creating Agents](01%20-%20Creating%20Agents.md) for the full field reference and an annotated example.

Settings in the manifest take priority over environment variables for these groups:

- `voice.*` - all TTS settings
- `heartbeat.*` - active hours and interval
- `telegram.*` - environment variable names for bot token and chat ID
- `display.*` - window dimensions and title

---

## Derived Config Values

These are computed at construction time in the `Config` class and available as instance properties:

| Property | Description |
|----------|-------------|
| `OBSIDIAN_AVAILABLE` | `true` if the Obsidian vault directory exists on disk. Controls whether agent notes, skills, and workspace operations target Obsidian or fall back to `~/.atrophy/agents/<name>/`. |
| `AGENT_STATES_FILE` | Path to `~/.atrophy/agent_states.json`. Stores per-agent muted/enabled state, persisted by `src/main/agent-manager.ts`. |
| `ARTEFACT_DISPLAY_FILE` | Path to `.artefact_display.json` in the agent's data directory. Used for GUI artefact signalling. |
| `ARTEFACT_INDEX_FILE` | Path to `.artefact_index.json` in the agent's data directory. Sorted, deduplicated index of created artefacts. |
| `VERSION` | App version string, read from the `VERSION` file at the bundle root. Falls back to `0.0.0` if missing. |
| `BUNDLE_ROOT` | `process.resourcesPath` when packaged, otherwise the project root directory. Exported as a module-level constant. |
| `USER_DATA` | `~/.atrophy/` (or override via `ATROPHY_DATA` env var). Exported as a module-level constant. |

---

## Prompt Resolution (Four-Tier)

`src/main/prompts.ts` resolves skill/prompt files through four directories in order:

1. **Obsidian vault** - `Agent Workspace/<agent>/skills/{name}.md` (if vault exists)
2. **Local skills** - `~/.atrophy/agents/<agent>/skills/{name}.md` (canonical for non-Obsidian users)
3. **User prompts** - `~/.atrophy/agents/<agent>/prompts/{name}.md` (legacy overrides)
4. **Bundle** - `agents/<agent>/prompts/{name}.md` (repo defaults)

Without Obsidian, tier 2 (local skills) is the canonical location. The agent reads and writes there via MCP note tools. First match wins.

---

## Constants

These are hardcoded in the `Config` class constructor and not configurable through environment variables. Change them by editing `src/main/config.ts` directly.

### Voice Input

| Constant | Value | Description |
|----------|-------|-------------|
| `PTT_KEY` | `ctrl` | Push-to-talk key. Hold to record, release to transcribe. In the Electron app, the renderer listens for Ctrl keydown/keyup and sends IPC to the main process. |
| `SAMPLE_RATE` | `16000` | Audio capture sample rate in Hz. Whisper expects 16kHz. |
| `CHANNELS` | `1` | Audio capture channels. Mono. |
| `MAX_RECORD_SEC` | `120` | Maximum recording duration in seconds before auto-cutoff. |

### Wake Word

| Constant | Value | Description |
|----------|-------|-------------|
| `WAKE_CHUNK_SECONDS` | `2` | Duration of audio chunks for wake word detection. |

### Whisper (STT)

| Constant | Value | Description |
|----------|-------|-------------|
| `WHISPER_PATH` | `<bundle>/vendor/whisper.cpp` | Root of whisper.cpp installation. |
| `WHISPER_BIN` | `<whisper>/build/bin/whisper-cli` | Compiled whisper binary. |
| `WHISPER_MODEL` | `<whisper>/models/ggml-tiny.en.bin` | Whisper model file. |

### Memory & Context

| Constant | Value | Description |
|----------|-------|-------------|
| `CONTEXT_SUMMARIES` | `3` | Number of recent session summaries injected into context at session start. |
| `MAX_CONTEXT_TOKENS` | `180000` | Maximum context window size in tokens. |

### Embeddings & Vector Search

| Constant | Value | Description |
|----------|-------|-------------|
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence transformer model for embedding generation. Uses `@xenova/transformers` (Transformers.js) for local WASM-based inference. |
| `EMBEDDING_DIM` | `384` | Embedding vector dimensionality. Must match the model. |
| `MODELS_DIR` | `~/.atrophy/models` | Local cache directory for downloaded models. |
| `VECTOR_SEARCH_WEIGHT` | `0.7` | Balance between semantic (1.0) and keyword (0.0) search. 0.7 = semantic-heavy. |

### Session

| Constant | Value | Description |
|----------|-------|-------------|
| `SESSION_SOFT_LIMIT_MINS` | `60` | Minutes before the agent checks in on session duration. Not a hard cutoff. |

### Avatar

| Constant | Value | Description |
|----------|-------|-------------|
| `AVATAR_RESOLUTION` | `512` | Default avatar render resolution in pixels. |

---

## Settings Panel (GUI)

When running in GUI mode (`--gui` or `--app`), the settings panel provides live configuration of all variables. Open it with the gear icon in the top-right corner or Cmd+,.

The panel is organised into sections:

| Section | Settings |
|---------|----------|
| **Agents** | List of all discovered agents with Switch/Muted/Enabled controls per agent, plus a **+ New Agent** button |
| **Agent Identity** | Display name, user name, opening line, wake words, Obsidian subdirectory |
| **Tools** | Per-agent checkboxes to enable/disable specific MCP tools (deferral, Telegram, reminders, timers, etc.) |
| **Window** | Width, height, window title, avatar enabled, avatar resolution |
| **Voice & TTS** | TTS backend, ElevenLabs API key, voice ID, model, stability, similarity, style, playback rate, Fal voice ID |
| **Input** | Input mode, push-to-talk key, wake word detection, wake chunk duration |
| **Notifications** | Notifications enabled toggle |
| **Audio Capture** | Sample rate, max record duration |
| **Inference** | Claude binary path, effort level, adaptive effort toggle |
| **Memory & Context** | Context summaries count, max context tokens, vector search weight, embedding model, embedding dimensions |
| **Session** | Soft time limit |
| **Heartbeat** | Active start/end hours, check interval |
| **Paths** | Obsidian vault path, database path (read-only), whisper binary path (read-only) |
| **Telegram** | Bot token, chat ID |
| **About** | Version, install path, Check for Updates / Update Now, Reset Setup Wizard |

Two actions at the bottom:

- **Apply** - applies changes to the running session immediately (in-memory only, lost on restart)
- **Save** - applies changes AND writes them to `~/.atrophy/config.json` (for general settings) and `agent.json` (for agent-specific settings like voice, display, heartbeat)

This means you can tune voice parameters, adjust inference effort, or change wake words without restarting the application.

---

## Per-Agent Paths

All per-agent paths are derived from the agent name. For an agent named `oracle`:

### Bundle paths (repo / app bundle)

| Path | Description |
|------|-------------|
| `agents/oracle/data/agent.json` | Agent manifest |
| `agents/oracle/prompts/system_prompt.md` | System prompt |
| `agents/oracle/prompts/soul.md` | Identity / personality |
| `agents/oracle/prompts/heartbeat.md` | Outreach decision checklist |
| `agents/oracle/avatar/source/face.png` | Source face image for video generation |
| `scripts/agents/oracle/jobs.json` | Scheduled job definitions |
| `scripts/agents/oracle/` | Agent-specific scripts (heartbeat, introspect, etc.) |

### User data paths (`~/.atrophy/`)

| Path | Description |
|------|-------------|
| `~/.atrophy/agents/oracle/data/memory.db` | SQLite memory database |
| `~/.atrophy/agents/oracle/data/` | Runtime state files (.emotional_state.json, etc.) |
| `~/.atrophy/agents/oracle/avatar/loops/` | Generated loop segments (loop_*.mp4) |
| `~/.atrophy/agents/oracle/avatar/ambient_loop.mp4` | Master ambient loop |
| `~/.atrophy/logs/oracle/` | Job execution logs |
| `~/.atrophy/config.json` | User config (shared across agents) |
| `~/.atrophy/models/` | Cached embedding models |

---

## Telegram Per-Agent Configuration

Each agent can have its own Telegram bot. The manifest specifies environment variable *names*, not values:

```json
{
  "telegram": {
    "bot_token_env": "TELEGRAM_BOT_TOKEN_ORACLE",
    "chat_id_env": "TELEGRAM_CHAT_ID_ORACLE"
  }
}
```

Then set the actual values as environment variables (in your shell profile or `~/.atrophy/.env`):

```
TELEGRAM_BOT_TOKEN_ORACLE=123456:ABC-DEF...
TELEGRAM_CHAT_ID_ORACLE=987654321
```

This allows multiple agents to use different Telegram bots without conflicting.

---

## Google Integration

Google tools (Gmail + Google Calendar) are enabled automatically when OAuth2 credentials are present. No environment variables are needed - the system checks for `~/.atrophy/.google/token.json` at startup, or queries `gws auth status` if the `gws` CLI is available.

### Setup

Run the standalone auth script, or let the first-launch setup wizard handle it:

```bash
python scripts/google_auth.py              # Authorize (opens browser for consent)
python scripts/google_auth.py --check      # Check if existing credentials are valid
python scripts/google_auth.py --revoke     # Revoke and delete tokens
```

The default (no flags) will:
1. Open a browser for the Google OAuth consent flow (client credentials are bundled with the app at `config/google_oauth.json` - no Google Cloud Console setup needed)
2. Save the resulting `token.json` to `~/.atrophy/.google/`

Use `--check` to verify stored credentials without re-authorizing. Use `--revoke` to revoke the tokens with Google and delete the local `token.json`.

The first-launch setup wizard offers the same flow - just say "yes" when prompted and a browser opens for authorization.

### Credential Storage

| Path | Permissions | Contents |
|------|-------------|----------|
| `config/google_oauth.json` | - | Bundled OAuth2 client credentials (shipped with the app) |
| `~/.atrophy/.google/` | `0700` | Token storage directory |
| `~/.atrophy/.google/token.json` | `0600` | OAuth2 refresh + access tokens (generated during consent flow) |

### OAuth2 Scopes

| Scope | Purpose |
|-------|---------|
| `gmail.readonly` | Search and read emails |
| `gmail.send` | Send emails |
| `gmail.modify` | Mark emails as read |
| `calendar.readonly` | List calendars and events |
| `calendar.events` | Create, update, and delete events |

### Per-Agent Disabling

To disable Google tools for a specific agent, add entries to `disabled_tools` in the agent's `agent.json`:

```json
{
  "disabled_tools": ["mcp__google__*"]
}
```

Or disable specific tools:

```json
{
  "disabled_tools": ["mcp__google__gmail_send", "mcp__google__gcal_delete_event"]
}
```

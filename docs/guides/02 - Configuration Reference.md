# Configuration Reference

Every setting in Atrophy can be changed through the Settings panel (gear icon or Cmd+,). You never need to edit files manually, but this reference documents what's available and where it lives.

---

## Where Settings Live

| Location | What goes here | How to edit |
|----------|---------------|-------------|
| **Settings panel** | Everything | Gear icon or Cmd+, |
| `~/.atrophy/config.json` | User preferences (shared across agents) | Settings panel > Save, or edit directly |
| `~/.atrophy/.env` | Secrets - API keys, tokens | Setup wizard, or edit directly (mode 0600) |
| `~/.atrophy/agents/<name>/data/agent.json` | Per-agent settings (voice, heartbeat, display) | Settings panel > Save |

### Priority

Most settings follow this order: environment variables beat config.json, which beats agent defaults.

Per-agent settings (voice, heartbeat, Telegram) flip this - the agent manifest wins, so each agent can have its own voice and schedule regardless of your global config.

---

## Settings Panel Sections

Open with the gear icon or **Cmd+,**. All changes can be applied immediately (in-memory only) or saved persistently.

| Section | What you can change |
|---------|-------------------|
| **Agents** | Switch, mute, enable/disable agents. Create new agents |
| **You** | Your name (agents will adapt) |
| **Agent Identity** | Display name, opening line, wake words |
| **Tools** | Enable/disable individual MCP tools per agent |
| **Window** | Size, avatar, eye mode, silence timer |
| **Voice & TTS** | TTS provider, ElevenLabs settings, Fal settings, playback rate |
| **Input** | Input mode (voice/text/dual), push-to-talk key, wake word detection |
| **Keep Awake** | Prevent your Mac from sleeping |
| **Notifications** | Enable/disable macOS notifications |
| **Audio Capture** | Sample rate, max recording duration |
| **Inference** | Claude CLI path, effort level, adaptive effort |
| **Memory & Context** | Context window size, summary count, search balance |
| **Session** | Soft time limit before check-in prompt |
| **Heartbeat** | Active hours and check interval for unprompted outreach |
| **Paths** | Obsidian vault path, database path (read-only) |
| **Google** | Connect/disconnect Google Workspace |
| **Telegram** | Bot token, chat ID, daemon start/stop |
| **App** | Reset setup wizard |
| **About** | Version info |

**Apply** updates the running session only (lost on restart). **Save** writes to disk permanently.

---

## Secrets (~/.atrophy/.env)

API keys and tokens are stored separately from other settings, with restricted file permissions (owner read/write only).

| Key | Purpose |
|-----|---------|
| `ELEVENLABS_API_KEY` | ElevenLabs TTS |
| `FAL_KEY` | Fal.ai image/video/TTS |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API |
| `OPENAI_API_KEY` | OpenAI API (if needed by MCP servers) |
| `ANTHROPIC_API_KEY` | Anthropic API (if needed by MCP servers) |

You can set these through the setup wizard, the Settings panel, or by editing the file directly:

```
ELEVENLABS_API_KEY=sk_abc123...
TELEGRAM_BOT_TOKEN=7123456789:AAH...
```

---

## Environment Variables

Set these in your shell before launching to override any saved setting.

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT` | `xan` | Which agent to load on startup |
| `ATROPHY_DATA` | `~/.atrophy` | Root data directory |
| `INPUT_MODE` | `dual` | Input mode: `voice`, `text`, or `dual` |
| `OBSIDIAN_VAULT` | (unset) | Path to your Obsidian vault |
| `AVATAR_ENABLED` | `false` | Enable animated avatar |
| `TTS_BACKEND` | `elevenlabs` | TTS engine: `elevenlabs`, `fal`, `macos`, `off` |
| `CLAUDE_BIN` | `claude` | Path to Claude Code CLI |
| `CLAUDE_EFFORT` | `medium` | Inference effort: `low`, `medium`, `high` |
| `ADAPTIVE_EFFORT` | `true` | Auto-adjust effort by message complexity |
| `PYTHON_PATH` | (auto-detected) | Python 3 binary for MCP servers |
| `ELECTRON_RENDERER_URL` | (unset) | Dev mode renderer URL (set automatically by `pnpm dev`) |

---

## Per-Agent Settings

Each agent can have its own voice, heartbeat schedule, Telegram bot, and display preferences. These are stored in the agent's `agent.json` manifest.

### Voice

| Setting | Default | Description |
|---------|---------|-------------|
| `TTS_BACKEND` | `elevenlabs` | TTS engine for this agent |
| `ELEVENLABS_VOICE_ID` | (none) | ElevenLabs voice ID |
| `ELEVENLABS_MODEL` | `eleven_v3` | ElevenLabs model |
| `ELEVENLABS_STABILITY` | `0.5` | Voice stability (0-1). Lower = more expressive |
| `ELEVENLABS_SIMILARITY` | `0.75` | Voice similarity boost (0-1) |
| `ELEVENLABS_STYLE` | `0.35` | Style exaggeration (0-1) |
| `TTS_PLAYBACK_RATE` | `1.12` | Audio playback speed |
| `FAL_VOICE_ID` | (none) | Fal TTS voice ID (fallback) |

### Behavior

| Setting | Default | Description |
|---------|---------|-------------|
| `OPENING_LINE` | `'Hello.'` | First message when a new session starts |
| `WAKE_WORDS` | `['hey <name>', '<name>']` | Phrases that activate voice input |
| `DISABLED_TOOLS` | `[]` | MCP tools this agent cannot use |
| `HEARTBEAT_ACTIVE_START` | `9` | Hour (0-23) when unprompted outreach begins |
| `HEARTBEAT_ACTIVE_END` | `22` | Hour (0-23) when outreach stops |
| `HEARTBEAT_INTERVAL_MINS` | `30` | Minutes between heartbeat checks |

### Telegram

Each agent can have its own Telegram bot for separate conversation channels:

| Setting | Default | Description |
|---------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | (none) | This agent's Telegram bot token |
| `TELEGRAM_CHAT_ID` | (none) | This agent's Telegram chat ID |

### Display

| Setting | Default | Description |
|---------|---------|-------------|
| `WINDOW_WIDTH` | `622` | Window width in pixels |
| `WINDOW_HEIGHT` | `830` | Window height in pixels |

---

## Memory & Context

These control how much history the agent draws on during conversation. Adjustable in Settings.

| Setting | Default | Description |
|---------|---------|-------------|
| `CONTEXT_SUMMARIES` | `3` | Recent session summaries included in context |
| `MAX_CONTEXT_TOKENS` | `180000` | Maximum context window size |
| `VECTOR_SEARCH_WEIGHT` | `0.7` | Semantic vs keyword search balance (0-1) |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence transformer model |
| `EMBEDDING_DIM` | `384` | Embedding vector dimensions |
| `SESSION_SOFT_LIMIT_MINS` | `60` | Minutes before "still here?" check-in |

---

## UI Defaults

Control the initial state of toggles on app launch.

| Setting | Default | Description |
|---------|---------|-------------|
| `SILENCE_TIMER_ENABLED` | `true` | Enable the idle "Still here?" prompt |
| `SILENCE_TIMER_MINUTES` | `5` | Minutes before the silence prompt |
| `EYE_MODE_DEFAULT` | `false` | Start with transcript hidden |
| `MUTE_BY_DEFAULT` | `false` | Start with TTS muted |

---

## Voice Input

| Setting | Default | Description |
|---------|---------|-------------|
| `PTT_KEY` | `ctrl` | Push-to-talk key |
| `SAMPLE_RATE` | `16000` | Audio capture rate (whisper expects 16kHz) |
| `MAX_RECORD_SEC` | `120` | Max recording duration |
| `WAKE_CHUNK_SECONDS` | `2` | Wake word audio chunk duration |

---

## Google Integration

Google tools (Gmail, Calendar, Drive) are enabled automatically when OAuth credentials are present.

### Setup

Connect through the setup wizard, or manually:

```bash
python scripts/google_auth.py              # Authorize (opens browser)
python scripts/google_auth.py --check      # Check credentials
python scripts/google_auth.py --revoke     # Revoke and delete
```

No Google Cloud Console setup needed - OAuth credentials are bundled.

### Disabling per agent

Add Google tools to the agent's `DISABLED_TOOLS` list in Settings > Tools, or in the manifest:

```json
{
  "disabled_tools": ["mcp__google__*"]
}
```

---

## Prompt Resolution

Agent prompts (system prompt, soul, heartbeat, skills) are loaded from the first location that has the file:

1. **Obsidian vault** - `Agent Workspace/<agent>/skills/<name>.md`
2. **Local skills** - `~/.atrophy/agents/<agent>/skills/<name>.md`
3. **User prompts** - `~/.atrophy/agents/<agent>/prompts/<name>.md`
4. **Bundle** - `agents/<agent>/prompts/<name>.md`

This lets you customize any prompt by placing a file with the same name higher in the chain.

---

## File Locations

### Per-agent files

For an agent named `oracle`:

| Path | Description |
|------|-------------|
| `~/.atrophy/agents/oracle/data/agent.json` | Agent manifest (identity, voice, behavior) |
| `~/.atrophy/agents/oracle/data/memory.db` | SQLite memory database |
| `~/.atrophy/agents/oracle/prompts/` | Custom prompts |
| `~/.atrophy/agents/oracle/avatar/` | Avatar assets |
| `~/.atrophy/logs/oracle/` | Job execution logs |

### Shared files

| Path | Description |
|------|-------------|
| `~/.atrophy/config.json` | User settings (shared across agents) |
| `~/.atrophy/.env` | Secrets (mode 0600) |
| `~/.atrophy/agent_states.json` | Which agents are muted/enabled |
| `~/.atrophy/server_token` | HTTP API auth token |
| `~/.atrophy/models/` | Cached embedding models |
| `~/.atrophy/.google/` | Google OAuth tokens |

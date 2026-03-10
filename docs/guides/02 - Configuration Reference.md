# Configuration Reference

All configuration flows through `config.py`, which reads from three sources in order of priority:

1. **Agent manifest** (`agents/<name>/agent.json`) -- per-agent overrides
2. **Environment variables** (from `.env` or shell)
3. **Hardcoded defaults** in `config.py`

The agent manifest takes priority for voice, heartbeat, telegram, and display settings. Environment variables are used as fallbacks and for secrets that should not live in JSON files.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT` | `companion` | Active agent name. Determines which `agents/<name>/` directory is loaded. |
| `INPUT_MODE` | `dual` | Input mode: `voice` (mic only), `text` (keyboard only), or `dual` (both). |
| `OBSIDIAN_VAULT` | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind` | Path to the Obsidian vault root. Used for journal entries, reflections, and notes. |
| `AVATAR_ENABLED` | `false` | Enable the LivePortrait avatar in GUI mode. Requires LivePortrait installed at `~/LivePortrait`. |
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
| `WAKE_WORD_ENABLED` | `false` | Enable background wake word detection. When enabled, the agent listens for its wake words. |
| `HEARTBEAT_ACTIVE_START` | `9` | Hour (0-23) when heartbeat checks begin. Overridden by agent manifest. |
| `HEARTBEAT_ACTIVE_END` | `22` | Hour (0-23) when heartbeat checks stop. Overridden by agent manifest. |
| `HEARTBEAT_INTERVAL_MINS` | `30` | Minutes between heartbeat evaluations. Overridden by agent manifest. |
| `TELEGRAM_BOT_TOKEN` | *(empty)* | Default Telegram bot token. Per-agent tokens use agent-specific env var names (e.g. `TELEGRAM_BOT_TOKEN_COMPANION`). |
| `TELEGRAM_CHAT_ID` | *(empty)* | Default Telegram chat ID. Per-agent chat IDs use agent-specific env var names. |

---

## Agent Manifest (agent.json)

The agent manifest lives at `agents/<name>/agent.json`. It provides per-agent overrides for voice, display, heartbeat, and channel configuration.

See [01 - Creating Agents](01%20-%20Creating%20Agents.md) for the full field reference and an annotated example.

Settings in the manifest take priority over environment variables for these groups:

- `voice.*` -- all TTS settings
- `heartbeat.*` -- active hours and interval
- `telegram.*` -- environment variable names for bot token and chat ID
- `display.*` -- window dimensions and title

---

## Constants

These are hardcoded in `config.py` and not configurable through environment variables. Change them by editing the file directly.

### Voice Input

| Constant | Value | Description |
|----------|-------|-------------|
| `PTT_KEY` | `ctrl` | Push-to-talk key (pynput key name). Hold to record, release to transcribe. |
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
| `WHISPER_PATH` | `<project>/vendor/whisper.cpp` | Root of whisper.cpp installation. |
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
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence transformer model for embedding generation. |
| `EMBEDDING_DIM` | `384` | Embedding vector dimensionality. Must match the model. |
| `MODELS_DIR` | `<project>/.models` | Local cache directory for downloaded models. |
| `VECTOR_SEARCH_WEIGHT` | `0.7` | Balance between semantic (1.0) and keyword (0.0) search. 0.7 = semantic-heavy. |

### Session

| Constant | Value | Description |
|----------|-------|-------------|
| `SESSION_SOFT_LIMIT_MINS` | `60` | Minutes before the agent checks in on session duration. Not a hard cutoff. |

### Avatar

| Constant | Value | Description |
|----------|-------|-------------|
| `AVATAR_RESOLUTION` | `512` | Default avatar render resolution in pixels. |
| `LIVEPORTRAIT_PATH` | `~/LivePortrait` | Expected installation path for LivePortrait. |

---

## Settings Panel (GUI)

When running in GUI mode (`--gui`), the settings panel provides live configuration of all variables. Open it with the gear icon in the top-right corner or Cmd+,.

The panel is organised into sections:

| Section | Settings |
|---------|----------|
| **Agent Identity** | Display name, user name, opening line, wake words, Obsidian subdirectory |
| **Window** | Width, height, window title, avatar enabled, avatar resolution |
| **Voice & TTS** | TTS backend, ElevenLabs API key, voice ID, model, stability, similarity, style, playback rate, Fal voice ID |
| **Input** | Input mode, push-to-talk key, wake word detection, wake chunk duration |
| **Audio Capture** | Sample rate, max record duration |
| **Inference** | Claude binary path, effort level, adaptive effort toggle |
| **Memory & Context** | Context summaries count, max context tokens, vector search weight, embedding model, embedding dimensions |
| **Session** | Soft time limit |
| **Heartbeat** | Active start/end hours, check interval |
| **Paths** | Obsidian vault path, database path (read-only), whisper binary path (read-only) |
| **Telegram** | Bot token, chat ID |

Two actions at the bottom:

- **Apply** -- applies changes to the running session immediately (in-memory only, lost on restart)
- **Save to .env** -- applies changes AND writes them to both `.env` (for environment variables and secrets) and `agent.json` (for agent-specific settings like voice, display, heartbeat)

This means you can tune voice parameters, adjust inference effort, or change wake words without restarting the application.

---

## Per-Agent Paths

All per-agent paths are derived from the agent name. For an agent named `oracle`:

| Path | Description |
|------|-------------|
| `agents/oracle/agent.json` | Agent manifest |
| `agents/oracle/memory.db` | SQLite memory database |
| `agents/oracle/system_prompt.md` | System prompt |
| `agents/oracle/soul.md` | Identity / personality |
| `agents/oracle/heartbeat.md` | Outreach decision checklist |
| `agents/oracle/state/` | Runtime state files (gitignored) |
| `agents/oracle/avatar/` | Visual assets |
| `scripts/agents/oracle/jobs.json` | Scheduled job definitions |
| `scripts/agents/oracle/` | Agent-specific scripts (heartbeat, introspect, etc.) |
| `logs/oracle/` | Job execution logs |

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

Then in `.env`:

```
TELEGRAM_BOT_TOKEN_ORACLE=123456:ABC-DEF...
TELEGRAM_CHAT_ID_ORACLE=987654321
```

This allows multiple agents to use different Telegram bots without conflicting.

# Agent Manifest Reference

Each agent is defined by an `agent.json` file. The manifest lives in the agent's data directory — either bundled (`agents/{name}/data/agent.json`) or user-installed (`~/.atrophy/agents/{name}/data/agent.json`). User-installed agents take precedence. The manifest configures identity, voice synthesis, communication channels, display, scheduled behaviors, and Obsidian integration.

File path: `agents/{name}/data/agent.json` (bundle) or `~/.atrophy/agents/{name}/data/agent.json` (user-installed)

---

## Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Internal agent identifier, used in file paths, database references, and environment variable names. Lowercase, no spaces. |
| `display_name` | string | Yes | Human-readable name shown in the UI window title and display. |
| `user_name` | string | Yes | The name the agent uses when referring to its user. |
| `opening_line` | string | Yes | The first thing the agent says when a new session begins. |
| `wake_words` | string[] | Yes | Phrases that trigger the agent via voice activation. Matched case-insensitively by the wake word detector. |

**Example:**
```json
{
  "name": "companion",
  "display_name": "Companion",
  "user_name": "Will",
  "opening_line": "Ready. Where are we?",
  "wake_words": ["hey companion", "companion"]
}
```

---

## voice

Configuration for text-to-speech synthesis. Supports multiple TTS backends.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tts_backend` | string | Yes | TTS engine to use. Currently supported: `elevenlabs`. |
| `elevenlabs_voice_id` | string | Yes | ElevenLabs voice ID for the primary TTS voice. |
| `elevenlabs_model` | string | Yes | ElevenLabs model identifier (e.g. `eleven_v3`). |
| `elevenlabs_stability` | number | Yes | Voice stability, 0.0--1.0. Lower values produce more expressive speech. |
| `elevenlabs_similarity` | number | Yes | Voice similarity boost, 0.0--1.0. Higher values stick closer to the original voice. |
| `elevenlabs_style` | number | Yes | Style exaggeration, 0.0--1.0. Higher values produce more dramatic delivery. |
| `fal_voice_id` | string | No | Alternative voice ID for the Fal TTS backend. |
| `playback_rate` | number | No | Audio playback speed multiplier (default: 1.0). Values above 1.0 speed up playback. |

**Example:**
```json
{
  "voice": {
    "tts_backend": "elevenlabs",
    "elevenlabs_voice_id": "VvTkMBKVXTwrKi71xpvq",
    "elevenlabs_model": "eleven_v3",
    "elevenlabs_stability": 0.5,
    "elevenlabs_similarity": 0.75,
    "elevenlabs_style": 0.35,
    "fal_voice_id": "cYsq7mdPbLaqB47hYCkA",
    "playback_rate": 1.12
  }
}
```

---

## telegram

Telegram bot integration for async communication (heartbeats, `ask_will`, `send_telegram` tools).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `bot_token_env` | string | Yes | Name of the environment variable containing the Telegram bot token. |
| `chat_id_env` | string | Yes | Name of the environment variable containing the target Telegram chat ID. |

The values are environment variable **names**, not the actual tokens. This allows different agents to use different Telegram bots without hardcoding secrets.

**Example:**
```json
{
  "telegram": {
    "bot_token_env": "TELEGRAM_BOT_TOKEN_COMPANION",
    "chat_id_env": "TELEGRAM_CHAT_ID_COMPANION"
  }
}
```

---

## display

Window dimensions and title for the companion's GUI.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `window_width` | integer | Yes | Window width in pixels. |
| `window_height` | integer | Yes | Window height in pixels. |
| `title` | string | No | Window title bar text. |

**Example:**
```json
{
  "display": {
    "window_width": 622,
    "window_height": 830,
    "title": "THE ATROPHIED MIND -- Companion"
  }
}
```

---

## heartbeat

Controls the companion's autonomous heartbeat system -- periodic checks that evaluate whether to reach out to the user proactively.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `active_start` | integer | Yes | Hour of day (0--23) when heartbeats begin. |
| `active_end` | integer | Yes | Hour of day (0--23) when heartbeats stop. |
| `interval_mins` | integer | Yes | Minutes between heartbeat evaluations. |

Heartbeats only fire during the active window (`active_start` to `active_end`). Each evaluation decides whether to send a message, and the decision is logged to the `heartbeats` database table regardless of outcome.

**Example:**
```json
{
  "heartbeat": {
    "active_start": 9,
    "active_end": 22,
    "interval_mins": 30
  }
}
```

---

## Obsidian Path Resolution

Agent workspaces in Obsidian are resolved automatically from the agent name:

```
{OBSIDIAN_VAULT}/Projects/{project-name}/agents/{agent-name}/
```

No manifest field is needed — `config.py` derives the path from `BUNDLE_ROOT.name` and `AGENT_NAME`.

---

## Complete Manifest Example

```json
{
  "name": "companion",
  "display_name": "Companion",
  "description": "Personal companion — emotionally aware, memory-bearing, self-evolving",
  "user_name": "Will",
  "opening_line": "Ready. Where are we?",
  "wake_words": ["hey companion", "companion"],
  "voice": {
    "tts_backend": "elevenlabs",
    "elevenlabs_voice_id": "VvTkMBKVXTwrKi71xpvq",
    "elevenlabs_model": "eleven_v3",
    "elevenlabs_stability": 0.5,
    "elevenlabs_similarity": 0.75,
    "elevenlabs_style": 0.35,
    "fal_voice_id": "cYsq7mdPbLaqB47hYCkA",
    "playback_rate": 1.12
  },
  "telegram": {
    "bot_token_env": "TELEGRAM_BOT_TOKEN_COMPANION",
    "chat_id_env": "TELEGRAM_CHAT_ID_COMPANION"
  },
  "display": {
    "window_width": 622,
    "window_height": 830,
    "title": "THE ATROPHIED MIND -- Companion"
  },
  "heartbeat": {
    "active_start": 9,
    "active_end": 22,
    "interval_mins": 30
  },
  "avatar_description": "A woman in her mid-thirties...",
  "disabled_tools": []
}
```

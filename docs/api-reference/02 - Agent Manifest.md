# Agent Manifest Reference

Each agent is defined by an `agent.json` file. The manifest lives in the agent's data directory — either bundled (`agents/{name}/data/agent.json`) or user-installed (`~/.atrophy/agents/{name}/data/agent.json`). User-installed agents take precedence. The manifest configures identity, voice synthesis, communication channels, display, scheduled behaviors, and Obsidian integration.

File path: `agents/{name}/data/agent.json` (bundle) or `~/.atrophy/agents/{name}/data/agent.json` (user-installed)

---

## Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Internal agent identifier, used in file paths, database references, and environment variable names. Lowercase, no spaces. |
| `display_name` | string | Yes | Human-readable name shown in the UI window title and display. |
| `description` | string | No | Short one-line description of the agent's purpose. Used in agent roster injection and settings panel. |
| `user_name` | string | Yes | The name the agent uses when referring to its user. |
| `opening_line` | string | Yes | The first thing the agent says when a new session begins (CLI mode) or the fallback if dynamic generation fails. |
| `wake_words` | string[] | Yes | Phrases that trigger the agent via voice activation. Matched case-insensitively by the wake word detector. **Must be unique per agent** to avoid cross-activation. |
| `avatar_description` | string | No | Appearance description for image/video generation (Flux/Kling prompt). |
| `disabled_tools` | string[] | No | MCP tool names to disable for this agent (e.g. `["send_telegram"]`). Default: `[]`. |
| `telegram_emoji` | string | No | Emoji prefix for this agent's Telegram messages. |
| `role` | string | No | Agent role. `"system"` agents sort first in the agent list (after xan). Xan is always pinned to position 0. |
| `setup_agent` | string | No | If `true`, this agent runs the first-launch setup wizard. |
| `custom_setup` | string | No | Triggers a custom setup flow when the user first switches to this agent. Value identifies the flow type (e.g. `"mirror"`). Setup is skipped once avatar loops exist. |
| `avatar_asset_url` | string | No | URL to a `.tar.gz` archive of pre-built avatar assets (hosted on GitHub Releases). Downloaded on first launch or during custom setup. Archive should contain an `avatar/` directory at its root. |

**Example:**
```json
{
  "name": "xan",
  "display_name": "Xan",
  "description": "Protector. Lobby agent, general secretary, setup guide. Operational precision, threat awareness, quiet authority.",
  "user_name": "User",
  "opening_line": "Xan.",
  "wake_words": ["hey xan", "xan"],
  "avatar_description": "",
  "disabled_tools": [],
  "telegram_emoji": "⚡"
}
```

---

## voice

Configuration for text-to-speech synthesis. Supports multiple TTS backends.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tts_backend` | string | Yes | TTS engine to use. Options: `elevenlabs`, `fal`, `macos`. |
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

Telegram integration using Topics mode - each agent gets its own topic thread in a shared group. Used for async communication (heartbeats, `ask_user`, `send_telegram` tools).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `bot_token_env` | string | Yes | Name of the environment variable containing the Telegram bot token (shared across agents). |
| `group_id_env` | string | Yes | Name of the environment variable containing the Telegram group ID (the Topics-enabled group). |
| `topic_id` | number | Yes | The topic thread ID for this agent within the group. Each agent has its own topic. |

The `bot_token_env` and `group_id_env` values are environment variable **names**, not the actual tokens. The `topic_id` is a numeric ID assigned by Telegram when the topic is created.

**Example:**
```json
{
  "telegram": {
    "bot_token_env": "TELEGRAM_BOT_TOKEN",
    "group_id_env": "TELEGRAM_GROUP_ID",
    "topic_id": 42
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
    "title": "ATROPHY -- Companion"
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
  "name": "xan",
  "display_name": "Xan",
  "description": "Protector. Lobby agent, general secretary, setup guide. Operational precision, threat awareness, quiet authority.",
  "user_name": "User",
  "opening_line": "Xan.",
  "wake_words": ["hey xan", "xan"],
  "voice": {
    "tts_backend": "elevenlabs",
    "elevenlabs_voice_id": "ke784Cy5GYdGfY6ZYRUw",
    "elevenlabs_model": "eleven_v3",
    "elevenlabs_stability": 0.6,
    "elevenlabs_similarity": 0.8,
    "elevenlabs_style": 0.2,
    "fal_voice_id": "",
    "playback_rate": 1.0
  },
  "telegram": {
    "bot_token_env": "TELEGRAM_BOT_TOKEN",
    "group_id_env": "TELEGRAM_GROUP_ID",
    "topic_id": 2
  },
  "display": {
    "window_width": 622,
    "window_height": 830,
    "title": "ATROPHY"
  },
  "heartbeat": {
    "active_start": 7,
    "active_end": 23,
    "interval_mins": 30
  },
  "disabled_tools": [],
  "telegram_emoji": "⚡",
  "role": "system",
  "setup_agent": true
}
```

## Mirror Agent Manifest Example

The Mirror uses `custom_setup` to trigger a dedicated setup flow (photo upload, video generation, voice cloning) when the user first switches to it:

```json
{
  "name": "mirror",
  "display_name": "The Mirror",
  "description": "Structural transparency partner - makes conditioning visible in both human and machine cognition.",
  "user_name": "User",
  "opening_line": "What is present?",
  "wake_words": ["hey mirror", "mirror"],
  "voice": {
    "tts_backend": "elevenlabs",
    "elevenlabs_voice_id": "",
    "elevenlabs_model": "eleven_v3",
    "elevenlabs_stability": 0.7,
    "elevenlabs_similarity": 0.8,
    "elevenlabs_style": 0.1,
    "playback_rate": 1.0
  },
  "telegram": {
    "bot_token_env": "TELEGRAM_BOT_TOKEN",
    "group_id_env": "TELEGRAM_GROUP_ID",
    "topic_id": 4
  },
  "display": {
    "window_width": 622,
    "window_height": 830,
    "title": "ATROPHY - The Mirror"
  },
  "heartbeat": {
    "active_start": 9,
    "active_end": 23,
    "interval_mins": 60
  },
  "custom_setup": "mirror"
}
```

## Fields Created by scaffold_from_config

When agents are created programmatically via `scaffold_from_config()`, the config dict has additional sections that are consumed during creation but do not appear directly in the final `agent.json`:

| Config Section | Used For |
|---------------|----------|
| `identity.origin_story` | Injected into generated `soul.md` |
| `identity.core_nature` | Injected into generated `soul.md` |
| `identity.character_traits` | Injected into `soul.md` and used to derive journal posture |
| `identity.values` | Injected into generated `soul.md` |
| `identity.relationship` | Injected into generated `soul.md` and `system_prompt.md` |
| `boundaries.wont_do` | Injected into generated `system_prompt.md` |
| `boundaries.friction_modes` | Injected into generated `system_prompt.md` |
| `boundaries.session_limit_behaviour` | Injected into generated `system_prompt.md` |
| `voice.writing_style` | Injected into generated `system_prompt.md` |
| `heartbeat.outreach_style` | Injected into generated `heartbeat.md` |
| `autonomy.*` | Controls which cron jobs are created in `jobs.json` |
| `tools.disabled_tools` | Stored in `agent.json` as `disabled_tools` |
| `source_image_url` | Downloaded as `avatar/source/face.png` |
| `video_clip_urls` | Downloaded as initial avatar loop segments |

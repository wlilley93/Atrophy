# Creating Agents

Each agent in The Atrophied Mind is a self-contained identity with its own voice, memory, personality, and autonomous behaviour. The default agent is `companion`, but you can create as many as you need.

---

## The Quick Way

Run the interactive creation script:

```bash
python scripts/create_agent.py
```

Or skip the first question by passing a name:

```bash
python scripts/create_agent.py --name oracle
```

Non-interactive mode is also supported for programmatic agent creation (used by the setup wizard, GUI settings panel, and the `create_agent` MCP tool):

```bash
python scripts/create_agent.py --non-interactive --config agent_config.json
```

### Interactive Questionnaire

The interactive questionnaire walks through nine sections:

1. **Services & API keys** -- checks for existing Fal.ai, ElevenLabs, and Obsidian; prompts for missing keys (uses `getpass` for secure input in terminal)
2. **Identity** -- name, display name, user name, origin story, core nature, character traits, values, relationship with the user, opening line
3. **Boundaries & Friction** -- what the agent will never do, friction modes, session time-limit behaviour
4. **Voice** -- TTS backend, voice ID, stability/similarity/style settings, writing style description
5. **Appearance** -- whether it has a visual avatar, appearance description for Flux face generation
6. **Channels** -- wake words for voice activation, Telegram bot token and chat ID
7. **Heartbeat** -- active hours, interval, outreach style
8. **Autonomy** -- journal, gifts, morning brief, evolution, sleep cycle, observer, reminders, inter-agent conversations, journal posture (derived from character traits or inferred via inference)
9. **Tools** -- disable specific MCP tools, describe custom skills

At the end, it shows a review summary and asks for confirmation before creating anything.

### scaffold_from_config()

The `scaffold_from_config(config: dict)` function creates an agent programmatically from a config dict. This is the entry point used by:

- The **setup wizard** (`display/setup_wizard.py`) — collects config via conversational AI, then calls `scaffold_from_config()`
- The **`create_agent` MCP tool** — allows the agent to create new agents at runtime via conversation
- The **Settings panel** — "+ New Agent" button

The config dict has sections: `identity`, `boundaries`, `voice`, `appearance`, `channels`, `heartbeat`, `autonomy`, plus optional `source_image_url` and `video_clip_urls` for avatar generation. Minimum required fields: `identity.display_name` and `identity.user_name`. The slug is auto-generated from `display_name` if not provided.

### Avatar Generation During Creation

When `appearance.has_avatar` is true and an `appearance_description` is provided:

- The interactive script prints a command to generate the face: `python scripts/generate_face.py --agent <name>`
- The setup wizard uses the `generate_avatar` tool to create face candidates via Flux during the conversation, letting the user pick from multiple options
- If `source_image_url` is provided in the config, it is downloaded as the source face image
- If `video_clip_urls` are provided, they are downloaded as initial avatar loop segments

---

## What Gets Created

After confirmation, the script scaffolds the full agent directory. New agents are created in `~/.atrophy/agents/<name>/` (user data), not in the repo bundle:

```
agents/<name>/                          # In repo (bundle)
  prompts/                              # All prompt/identity documents
    system_prompt.md                    # Instructions for Claude (the agent's operating manual)
    soul.md                             # Identity and personality (the agent can self-modify this)
    heartbeat.md                        # Checklist for unprompted outreach decisions
  data/
    agent.json                          # Manifest — all technical config
  avatar/
    source/face.png                     # Source face image for video generation
    candidates/                         # Face generation candidates

~/.atrophy/agents/<name>/               # In user data (runtime)
  data/
    memory.db                           # SQLite database (initialized from db/schema.sql)
    .emotional_state.json
    .user_status.json
    .message_queue.json
    ...                                 # Other runtime state files
  avatar/
    loops/                              # Generated loop segments (loop_*.mp4)
    ambient_loop.mp4                    # Master ambient loop
```

It also creates a matching Obsidian workspace at `Projects/<project>/Agent Workspace/<name>/`:

```
<name>/
  skills/                 # Canonical runtime prompts (take precedence over repo prompts/)
    system.md
    soul.md
  notes/                  # Agent's living documents
    reflections.md        # Working reflections
    for-will.md           # Scratchpad for things to share with user
    threads.md            # Active conversation threads
    gifts.md              # Notes and gifts left for user
    journal-prompts.md    # Journal prompts left in Obsidian
    journal/              # Timestamped journal entries
    evolution-log/        # Archived soul/prompt revisions
```

If Telegram credentials are provided, set them as environment variables with agent-specific names (e.g. `TELEGRAM_BOT_TOKEN_ORACLE`).

---

## The Agent Manifest (agent.json)

This is the technical configuration file. All fields:

```json
{
  "name": "companion",
  "display_name": "Companion",
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

  "avatar_description": "Description for image generation...",
  "description": "Short one-line description of the agent's role",
  "disabled_tools": [],
  "telegram_emoji": ""
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Internal slug (lowercase, underscores). Used for directory names and labels. |
| `display_name` | string | Human-readable name. Used in UI, prompts, and logs. |
| `user_name` | string | The human's name. Used in prompts and turn labels. |
| `opening_line` | string | First thing the agent ever says (first session only). |
| `wake_words` | string[] | Phrases that activate voice input when wake word detection is enabled. **Must be unique per agent** to avoid cross-activation when multiple agents are running. |
| `voice.tts_backend` | string | TTS engine: `elevenlabs`, `fal`, or `macos`. |
| `voice.elevenlabs_voice_id` | string | ElevenLabs voice ID (from their voice library). |
| `voice.elevenlabs_model` | string | ElevenLabs model name. Default `eleven_v3`. |
| `voice.elevenlabs_stability` | float | Voice stability (0.0-1.0). Lower = more expressive. |
| `voice.elevenlabs_similarity` | float | Voice similarity boost (0.0-1.0). Higher = closer to original voice. |
| `voice.elevenlabs_style` | float | Style exaggeration (0.0-1.0). |
| `voice.fal_voice_id` | string | Alternative voice ID for Fal TTS fallback. |
| `voice.playback_rate` | float | Audio playback speed multiplier. 1.0 = normal, 1.12 = slightly faster. |
| `telegram.bot_token_env` | string | Environment variable name for this agent's Telegram bot token. |
| `telegram.chat_id_env` | string | Environment variable name for this agent's Telegram chat ID. |
| `display.window_width` | int | GUI window width in pixels. |
| `display.window_height` | int | GUI window height in pixels. |
| `display.title` | string | GUI window title bar text. |
| `heartbeat.active_start` | int | Hour (0-23) when heartbeat checks begin. |
| `heartbeat.active_end` | int | Hour (0-23) when heartbeat checks stop. |
| `heartbeat.interval_mins` | int | Minutes between heartbeat evaluations. |
| `avatar_description` | string | Appearance description for image/video generation (Flux/Kling prompt). |
| `description` | string | Short one-line description of the agent's purpose. |
| `disabled_tools` | string[] | MCP tool names to disable for this agent (e.g. `["send_telegram"]`). |
| `telegram_emoji` | string | Emoji prefix for this agent's Telegram messages. |

---

## Running a Specific Agent

Set the agent with `--agent` or the `AGENT` environment variable:

```bash
python main.py --agent oracle --text
# or
AGENT=oracle python main.py --gui
```

All per-agent paths resolve automatically. Each agent has its own memory database, state files, system prompt, and soul.

---

## Customizing After Creation

The three files you'll edit most:

- **`prompts/system_prompt.md`** -- the agent's operating instructions. This is injected as the system prompt for every Claude inference call. Change how the agent behaves.
- **`prompts/soul.md`** -- the agent's identity and personality. This is also injected into context. Change who the agent is. The agent itself can modify this file through its monthly self-evolution job.
- **`prompts/heartbeat.md`** -- the checklist the agent runs through when deciding whether to reach out unprompted. Change when and why it initiates contact.

The `data/agent.json` manifest controls technical configuration (voice, display, scheduling). Edit it directly -- no rebuild needed, changes take effect on next launch.

In GUI mode, all of these settings can also be edited live through the **Settings panel** (gear icon or Cmd+,). Changes can be applied immediately to the running session or saved to `~/.atrophy/config.json` and `agent.json` for persistence. See [02 - Configuration Reference](02%20-%20Configuration%20Reference.md) for the full settings panel reference.

---

## Scheduling Jobs for a New Agent

After creating an agent, you'll likely want to set up its autonomous behaviour. See [03 - Scheduling Jobs](03%20-%20Scheduling%20Jobs.md) for how to configure heartbeats, introspection, and other scheduled tasks.

The jobs configuration lives at `scripts/agents/<name>/jobs.json` and is managed through `scripts/cron.py`.

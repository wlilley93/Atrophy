# Creating Agents

Three ways to create an agent, from easiest to most hands-on.

---

## 1. First-Time Setup (new users)

If you've just cloned the repo and have no agents:

```bash
./scripts/setup.sh
```

This checks your environment, installs dependencies, and tells you how to create your first agent. Then open Claude Code in the project directory:

```bash
claude
```

Say: **"Create my first agent"** — or type `/setup` to run the guided skill. Claude walks you through everything: API keys, identity, voice, appearance, and all the rest.

### What you need before starting

| Requirement | How to get it |
|-------------|---------------|
| **Python 3.10+** | https://python.org |
| **Claude Code** | `npm install -g @anthropic-ai/claude-code` or https://claude.ai/download |
| **Fal API key** | https://fal.ai/dashboard/keys (for image/video generation) |
| **ElevenLabs key** (optional) | https://elevenlabs.io/app/settings/api-keys (for premium voice) |

---

## 2. Agent-Assisted (from a running agent)

If you already have an agent running, ask it:

> "Create a new agent."

The agent reads the `create-agent` skill from Obsidian and follows a deterministic process:

1. Checks API keys, guides setup if needed
2. Walks through identity, boundaries, voice, appearance
3. Generates 10 face candidates via Flux (if avatar wanted)
4. Shows them in the canvas overlay with arrow navigation
5. Generates 2 Kling video clips → 10-second ambient loop
6. Asks about channels, heartbeat, autonomy features
7. Calls the `create_agent` MCP tool with the full config

The process takes about 10-15 minutes. Image generation costs ~$0.10, video ~$0.60.

---

## 3. Interactive Script (terminal)

The classic approach — a terminal questionnaire:

```bash
python scripts/create_agent.py
```

Walks through the same questions interactively. No media generation (images/video must be created separately via the generate scripts).

### Non-interactive mode

For automation or CI, pass a JSON config:

```bash
python scripts/create_agent.py --config agent_config.json
```

See the [config schema](#config-schema) below.

---

## What Gets Created

| Location | Contents |
|----------|----------|
| `agents/<name>/data/agent.json` | Manifest (display name, voice, wake words, heartbeat, window) |
| `agents/<name>/data/memory.db` | SQLite memory database |
| `agents/<name>/prompts/` | Local fallback prompts (soul, system, heartbeat) |
| `agents/<name>/avatar/` | Face image, video loops (gitignored) |
| `agents/<name>/state/` | Runtime state files |
| `scripts/agents/<name>/` | Job scripts + jobs.json |
| **Obsidian** `Agent Workspace/<name>/skills/` | Canonical prompts: system, soul, heartbeat, tools, introspection, gift, morning-brief |
| **Obsidian** `Agent Workspace/<name>/notes/` | Reflections, threads, journal, gifts, for-user |
| **Obsidian** `Agent Workspace/<name>/Dashboard.md` | Dataview dashboard |

Obsidian skills take precedence over repo prompts. The agent reads from Obsidian at runtime.

---

## Post-Creation

### Run the agent

```bash
AGENT=<name> python main.py --app     # Menu bar mode (primary)
AGENT=<name> python main.py --gui     # Full window with avatar
AGENT=<name> python main.py --cli     # Terminal with voice
AGENT=<name> python main.py --text    # Text-only terminal
```

### Install background jobs

```bash
AGENT=<name> python scripts/cron.py install
```

This installs launchd jobs for heartbeat, journal, morning brief, and all other enabled autonomy features.

### Refine the identity

Edit the soul and system prompt in Obsidian at `Agent Workspace/<name>/skills/`. These are the canonical versions — the agent reads them at every session start.

### Generate more avatar content

```bash
# More face candidates (Flux via fal.ai)
python scripts/agents/companion/generate_face.py --agent <name>

# Ambient video loops via Kling (fal.ai — ~$0.30 per 5s clip)
python scripts/agents/companion/generate_ambient_loop.py --agent <name>
```

---

## API Key Reference

### Fal.ai

- **Sign up**: https://fal.ai
- **Keys**: https://fal.ai/dashboard/keys
- **Cost**: Images ~$0.01 each, video ~$0.30 per 5s clip
- **Used for**: Flux image generation, Kling video generation, Fal TTS fallback
- **Env var**: `FAL_KEY`

### ElevenLabs

- **Sign up**: https://elevenlabs.io
- **Keys**: https://elevenlabs.io/app/settings/api-keys
- **Voices**: https://elevenlabs.io/app/voice-library
- **Cost**: Free tier 10,000 chars/month, paid plans from $5/month
- **Used for**: Premium text-to-speech
- **Env vars**: `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`

### Telegram (for remote messaging)

- **Create bot**: Message @BotFather on Telegram, send `/newbot`
- **Get chat ID**: After messaging your bot, visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
- **Env vars**: `TELEGRAM_BOT_TOKEN_<AGENT>`, `TELEGRAM_CHAT_ID_<AGENT>`

---

## Config Schema

Full JSON config for `--config` mode or the `create_agent` MCP tool:

```json
{
  "identity": {
    "display_name": "Oracle",
    "user_name": "User",
    "origin_story": "...",
    "core_nature": "...",
    "character_traits": "...",
    "values": "...",
    "relationship": "...",
    "opening_line": "Hello."
  },
  "boundaries": {
    "wont_do": "...",
    "friction_modes": "...",
    "session_limit_behaviour": "Check in.",
    "soft_limit_mins": 60
  },
  "voice": {
    "tts_backend": "elevenlabs",
    "elevenlabs_voice_id": "",
    "elevenlabs_model": "eleven_v3",
    "elevenlabs_stability": 0.5,
    "elevenlabs_similarity": 0.75,
    "elevenlabs_style": 0.35,
    "fal_voice_id": "",
    "playback_rate": 1.12,
    "writing_style": "..."
  },
  "appearance": {
    "has_avatar": false,
    "appearance_description": ""
  },
  "channels": {
    "wake_words": "",
    "telegram_bot_token": "",
    "telegram_chat_id": ""
  },
  "heartbeat": {
    "active_start": 9,
    "active_end": 22,
    "interval_mins": 30,
    "outreach_style": ""
  },
  "autonomy": {
    "location": "",
    "introspection": true,
    "introspection_style": "",
    "journal_posture": "",
    "gifts": true,
    "morning_brief": true,
    "evolution": true,
    "sleep_cycle": true,
    "observer": true,
    "reminders": true,
    "inter_agent_conversations": true
  },
  "tools": {
    "disabled_tools": [],
    "custom_skills": [
      {"name": "example-skill", "description": "What this skill does and how the agent approaches it"}
    ]
  },
  "source_image_url": "",
  "video_clip_urls": []
}
```

All fields except `identity.display_name` and `identity.user_name` have sensible defaults.

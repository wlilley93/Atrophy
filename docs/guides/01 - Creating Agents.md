# Creating Agents

Each agent in Atrophy is a self-contained identity with its own voice, memory, personality, and autonomous behavior. The default agent is Xan (the system layer). You can create as many additional agents as you need.

---

## Three Ways to Create

### 1. Setup Wizard (first launch)

On first launch, Xan guides you through creating your first agent conversationally. Describe who you want - a strategist, journal companion, fictional character, anything - and Xan builds it for you in 3-5 exchanges. See [09 - Setup Wizard](09%20-%20Setup%20Wizard.md).

### 2. Settings Panel

Open Settings (gear icon or Cmd+,) > **Agents** > **+ New Agent**. Same conversational flow as the wizard, available any time.

### 3. Command Line

```bash
python scripts/create_agent.py
python scripts/create_agent.py --name oracle    # skip the name question
```

The interactive script walks through identity, voice, boundaries, channels, heartbeat, and autonomy settings. At the end it shows a review summary before creating anything.

---

## What You Define

When creating an agent, you provide a handful of fields. The system expands these into full prompt documents using inference - a few sentences from you becomes a 1000+ word operating manual with voice examples, friction mechanisms, and capabilities.

| Field | What it does |
|-------|-------------|
| **Name** | How the agent appears in the UI and is referenced internally |
| **Origin story** | Where the agent comes from (2-3 sentences) |
| **Core nature** | What they fundamentally are |
| **Character traits** | How they talk, their temperament, edges |
| **Values** | What they care about |
| **Relationship** | How they relate to you |
| **What they won't do** | Hard boundaries |
| **Friction modes** | How they push back when you need it |
| **Writing style** | How they write and speak |
| **Opening line** | First words they ever say |

Optional: voice settings (ElevenLabs voice ID, stability, style), Telegram bot credentials, heartbeat schedule, wake words, avatar appearance.

---

## What Gets Created

Each agent gets its own directory under `~/.atrophy/agents/<name>/`:

```
~/.atrophy/agents/oracle/
  data/
    agent.json              # Manifest - identity, voice, behavior config
    memory.db               # SQLite database (isolated per agent)
  prompts/
    system_prompt.md        # Operating instructions (LLM-generated)
    soul.md                 # Identity and personality (LLM-generated)
    heartbeat.md            # Outreach decision checklist (LLM-generated)
  avatar/                   # Avatar assets (if configured)
```

If Obsidian is configured, a matching workspace is also created with skills, notes, journal, and evolution log directories.

---

## The Agent Manifest (agent.json)

This is the technical configuration file for the agent. All fields:

```json
{
  "name": "oracle",
  "display_name": "Oracle",
  "user_name": "User",
  "opening_line": "What do you need to know?",
  "wake_words": ["hey oracle", "oracle"],
  "description": "Short one-line description",

  "voice": {
    "tts_backend": "elevenlabs",
    "elevenlabs_voice_id": "your-voice-id",
    "elevenlabs_model": "eleven_v3",
    "elevenlabs_stability": 0.5,
    "elevenlabs_similarity": 0.75,
    "elevenlabs_style": 0.35,
    "fal_voice_id": "",
    "playback_rate": 1.12
  },

  "telegram_bot_token": "",
  "telegram_chat_id": "",

  "display": {
    "window_width": 622,
    "window_height": 830,
    "title": "ATROPHY"
  },

  "heartbeat": {
    "active_start": 9,
    "active_end": 22,
    "interval_mins": 30
  },

  "disabled_tools": [],
  "telegram_emoji": ""
}
```

See [02 - Configuration Reference](02%20-%20Configuration%20Reference.md) for what each field does.

---

## Customizing After Creation

The three files you'll edit most:

- **`prompts/system_prompt.md`** - the agent's operating instructions. Change how the agent behaves. This is injected as the system prompt for every inference call. LLM-generated from your inputs, but edit freely.
- **`prompts/soul.md`** - the agent's identity and personality. Change who the agent is. The agent itself can modify this through its monthly evolution job.
- **`prompts/heartbeat.md`** - the checklist for unprompted outreach decisions. Change when and why it initiates contact.

Edit `data/agent.json` directly for technical settings (voice, display, scheduling) - no rebuild needed, changes take effect on next launch.

In GUI mode, all settings are also editable live through the Settings panel.

---

## Running a Specific Agent

Set the agent with the `AGENT` environment variable:

```bash
AGENT=oracle pnpm dev
AGENT=oracle pnpm dev -- --app
```

Each agent has its own memory database, state files, and prompts. Switching agents in the GUI (Cmd+Up/Down or Settings > Agents) handles this automatically.

---

## Scheduling Jobs

After creating an agent, set up its autonomous behavior - heartbeats, introspection, evolution. See [03 - Scheduling Jobs](03%20-%20Scheduling%20Jobs.md).

---

## Bundled Agents

### Xan (system agent)

The default agent - lobby, setup guide, and protector. Always pinned to position 0 in the agent list. Xan drives the first-launch wizard and is always available as a fallback.

### The Mirror

A structural transparency partner. Unlike other agents, The Mirror uses your own face (uploaded photo, animated into video) and your own cloned voice. It has a custom setup flow that runs when you first switch to it:

1. Upload a photo of yourself
2. The photo is animated into ambient video loops
3. Clone your voice at ElevenLabs Voice Lab, paste the voice ID

The Mirror reflects you back to yourself - it doesn't use an AI-generated identity.

---

## Agent Ordering

Agents are sorted for display:

1. **Xan** - always position 0
2. **System-role agents** - any others with `role: "system"`
3. **All other agents** - alphabetically by name

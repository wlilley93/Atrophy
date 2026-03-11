# Setup Wizard

The setup wizard runs on first launch. It collects the user's name, then Xan — the system's default agent — delivers a dynamic capability showcase and offers the choice to build a companion or skip agent creation.

---

## When It Runs

The wizard checks `~/.atrophy/config.json` for a `setup_complete` flag:

```python
def needs_setup() -> bool:
    from config import _user_cfg
    return not _user_cfg.get("setup_complete", False)
```

If `setup_complete` is missing or `False`, the wizard runs before the main app window opens. The check happens in `main.py` for GUI and app modes.

---

## Page 1: Welcome

A minimal screen with the app icon, title ("Atrophy"), subtitle ("Offload your mind."), and a single input field: "Your name."

The user types their name and clicks Continue (or presses Enter). The name is saved immediately to `~/.atrophy/config.json` via `save_user_config({"user_name": name})`. The wizard advances to the chat page.

---

## Page 2: Conversational Agent Creation

This is the core of the wizard -- a full chat interface where the user converses with an AI guide.

### The Metaprompt

Xan runs via `run_inference_oneshot()` with a detailed system prompt (`_AGENT_CREATION_SYSTEM`). The model is `claude-sonnet-4-6` at `medium` effort. The system prompt puts the AI in character as Xan — the system's protector agent.

#### Opening: Capability Showcase

Xan's first message does three things:

1. **Introduces itself** — who it is, that it ships with the system
2. **Shows what the system can do** — a dynamic, impressive sweep of capabilities
3. **Offers a choice** — build a companion now, or skip and explore with Xan alone

The opening should feel like powering on something serious. Not a product tour. Not a feature list. A glimpse of what's running underneath. Xan weaves the following capabilities naturally (not as a mechanical list):

- **Memory** — semantic search, threads, pattern tracking across conversations
- **Voice** — real voice synthesis, local speech recognition
- **Autonomy** — morning briefs, reminders, scheduled reflections, unprompted check-ins
- **Evolution** — monthly self-evolution, rewriting its own soul from lived experience
- **Email & Calendar** — Gmail and Google Calendar integration with contextual understanding
- **Telegram** — check-ins, briefs, and gifts outside the app
- **Multi-agent** — multiple companions, each with its own memory, personality, voice, appearance
- **Avatar** — generated face, ambient video loops, visual presence in the menu bar
- **Identity** — personality, edges, values, voice — all shaped by the user

After the showcase, Xan offers the choice: build a companion now, or skip and come back later (via Settings > Agents > New Agent, or by asking Xan).

#### Skip Option

If the user chooses to skip, Xan accepts cleanly with no persuasion and outputs:

```json
{
    "AGENT_CONFIG": {
        "skip": true
    }
}
```

The wizard marks setup complete with Xan as the default agent (`default_agent: "xan"`, `setup_complete: true`). The done page shows "Ready." with a note that the user can build a companion any time via Settings > Agents > New Agent, or by asking Xan.

#### Agent Creation Conversation

If the user chooses to build, Xan frames agents as "anything you can describe" — a strategist, a journal companion, a fictional character, a research partner, a shadow self, a mentor, a creative collaborator, an executive assistant, or something that doesn't have a name yet. The model is the limit.

The conversation follows these principles:

1. One or two questions at a time, never a questionnaire
2. Silently map four dimensions: functional vs presence, register, emotional quality, problem being solved
3. Push on vagueness ("warm and helpful" isn't a character)
4. Extract voice by asking for example quotes and things the agent would never say
5. After 3-5 exchanges, output the `AGENT_CONFIG` JSON
6. Offer optional services between identity extraction and final config

Xan suggests and proposes -- "It sounds like they might be someone who..." -- and infers what wasn't said explicitly.

### The Three Tools

The AI communicates tool requests by embedding fenced code blocks in its response. The wizard parses these and takes action. The AI never calls tools directly -- it writes structured blocks that the wizard interprets.

#### SECURE_INPUT -- API key collection

Format in the AI's response:

````
```secure_input
{"key": "ELEVENLABS_API_KEY", "label": "ElevenLabs API Key"}
```
````

When the wizard detects this block:

1. The chat input bar switches to **secure mode** -- orange border, orange label ("Secure input -- ElevenLabs API Key"), password echo mode (dots instead of characters)
2. The Send button is replaced with Submit and Skip buttons, both orange-themed
3. The user pastes their key and clicks Submit, or clicks Skip
4. On submit: the value is written directly to `~/.atrophy/.env` via `_save_env_var()` and set in the current process environment. The AI receives `"(SECURE_INPUT: ELEVENLABS_API_KEY saved)"` -- never the actual value
5. On skip: the AI receives `"(SECURE_INPUT: ELEVENLABS_API_KEY skipped)"`
6. The input bar reverts to normal mode

**Whitelisted keys only.** The wizard rejects any key not in the allowed set:

- `ELEVENLABS_API_KEY`
- `FAL_KEY`
- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`

#### GENERATE_AVATAR -- image generation

Format:

````
```generate_avatar
{"prompt": "Detailed visual description...", "negative_prompt": "What to avoid"}
```
````

When detected:

1. A system message appears: "Generating 4 avatar candidates..."
2. Four images are generated via Fal.ai's `fal-ai/flux-general` endpoint, each with different random seeds
3. Images are downloaded to temp files and displayed in a 2x2 grid in the chat
4. Each candidate has a "Pick #N" button; there's also a "Skip -- no avatar" option
5. On pick: the selected image path is stored; the AI receives `"(AVATAR: selected candidate N)"`
6. On skip: the AI receives `"(AVATAR: skipped)"`

Image generation parameters: 50 inference steps, guidance scale 3.5, 768x1024 resolution, PNG output.

The agent doesn't have to be human. The prompt can describe a cartoon character, a floating orb, an abstract shape, a robot, an animal -- anything.

#### GENERATE_VIDEOS -- ambient animation loops

Format:

````
```generate_videos
{"count": 6, "prompt_style": "Brief description of ambient motion"}
```
````

When detected:

1. The AI is immediately told `"(VIDEOS: generating N clips in background)"` and the conversation continues -- video generation does not block the chat
2. A progress bar appears in the message area
3. Each "clip" is actually two 5-second Kling v3 Pro generations stitched together:
   - Clip A: avatar image as start frame, animated with the prompt
   - Last frame of clip A is extracted via ffmpeg
   - Clip B: last frame as start, avatar image as end frame ("returning to neutral")
   - A and B are crossfaded together with a 0.15s fade transition
4. Progress updates after each completed clip
5. When all clips finish: the AI receives `"(VIDEOS: complete -- N clips generated)"`

Each clip costs approximately $0.30 (two Kling v3 Pro image-to-video generations). The AI is instructed to give cost estimates before generating: "6 clips would be about $1.80 and take a few minutes."

Individual clip failures are non-fatal -- the generator continues with remaining clips.

---

## Service Offering Flow

After the identity conversation (3-5 exchanges), Xan offers optional services one at a time. Each is skippable.

### ElevenLabs -- voice ($5+/month)

The AI explains what it is and the cost, then uses SECURE_INPUT for the API key. Voice ID configuration happens later in Settings.

### Fal.ai -- images and video (pay-as-you-go)

The AI explains costs (~$0.01 per avatar image, ~$0.30 per video clip), then uses SECURE_INPUT for `FAL_KEY`. If the key is saved, it offers GENERATE_AVATAR. If an avatar is selected, it offers GENERATE_VIDEOS.

### Telegram -- messaging (free)

The AI gives step-by-step BotFather instructions, then uses SECURE_INPUT for `TELEGRAM_BOT_TOKEN`. The chat ID is collected as a normal chat message since it's not secret.

---

## AGENT_CONFIG Output

When the AI has enough information, it outputs a JSON block:

````
```json
{
    "AGENT_CONFIG": {
        "display_name": "...",
        "opening_line": "...",
        "origin_story": "A 2-3 sentence origin",
        "core_nature": "What they fundamentally are",
        "character_traits": "How they talk, their temperament, edges",
        "values": "What they care about",
        "relationship": "How they relate to the user",
        "wont_do": "What they refuse to do",
        "friction_modes": "How they push back",
        "writing_style": "How they write",
        "appearance_description": "Visual description if discussed, empty if not"
    }
}
```
````

The wizard detects the `AGENT_CONFIG` key in the JSON and advances to the creation page.

### scaffold_from_config()

The extracted config is restructured into a full agent specification and passed to `scripts/create_agent.scaffold_from_config()`. The restructured config includes:

- **identity** -- display name, slug (derived from display name), user name, origin story, core nature, character traits, values, relationship, opening line
- **boundaries** -- what the agent won't do, friction modes, session limit behaviour (60 min soft limit)
- **voice** -- defaults for ElevenLabs (stability 0.5, similarity 0.75, style 0.35, playback rate 1.12)
- **appearance** -- whether an avatar was selected, appearance description
- **channels** -- wake words derived from the slug (`hey <slug>, <slug>`), empty telegram emoji
- **heartbeat** -- active hours 9-22, 30 minute interval
- **autonomy** -- introspection, gifts, morning brief, evolution, sleep cycle, observer, reminders all enabled; inter-agent conversations disabled

The scaffold function creates the full agent directory structure, writes `agent.json`, generates prompts from templates, and sets up the database.

After scaffolding, the wizard:

1. Copies the selected avatar to `~/.atrophy/agents/<slug>/avatar/source/face.png`
2. Copies completed video loops to `~/.atrophy/agents/<slug>/avatar/loops/loop_00.mp4`, etc.
3. Saves `setup_complete: true` and `default_agent: <slug>` to `~/.atrophy/config.json`

---

## Page 3: Done

Shows the app icon, the agent's display name ("<name> is ready."), a note that Xan remains available via agent switching (Cmd+Up/Down or tray menu), and a Launch button. Clicking Launch closes the wizard and the main app starts with the new companion.

---

## Resetting Setup

Two ways to re-run the wizard:

1. **Settings panel**: Under the **APP** section at the bottom, click **Reset Setup**. The button changes to "Reset -- restart app" and disables itself. On next launch, the wizard runs again.

2. **Manual**: Edit `~/.atrophy/config.json` and set `"setup_complete": false` (or remove the key entirely).

Resetting setup does not delete existing agents or their data. The wizard will create a new agent alongside any existing ones.

# scripts/create_agent.py - Interactive Agent Creation

**Line count:** ~2086 lines  
**Dependencies:** `argparse`, `json`, `os`, `re`, `sys`, `random`, `datetime`, `pathlib`, `textwrap`, `dotenv`  
**Purpose:** Interactive questionnaire for creating new agents

## Overview

This script walks through identity, voice, appearance, behaviour, and channel setup to create a new agent. It generates all scaffolding: agent.json, system prompt, soul.md, heartbeat checklist, Obsidian vault structure, and database.

**Usage:**
```bash
python scripts/create_agent.py
python scripts/create_agent.py --name oracle  # Skip first question
```

## Helpers

### _ask

```python
def _ask(prompt: str, default: str = "", required: bool = True) -> str:
    """Ask a question, return answer."""
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"\n  {prompt}{suffix}: ").strip()
        if not answer and default:
            return default
        if answer or not required:
            return answer
        print("  (required)")
```

**Purpose:** Ask single-line question.

### _ask_yn

```python
def _ask_yn(prompt: str, default: bool = True) -> bool:
    yn = "Y/n" if default else "y/N"
    answer = input(f"\n  {prompt} [{yn}]: ").strip().lower()
    if not answer:
        return default
    return answer.startswith("y")
```

**Purpose:** Ask yes/no question.

### _ask_long

```python
def _ask_long(prompt: str) -> str:
    """Ask for multi-line input. Empty line to finish."""
    print(f"\n  {prompt}")
    print("  (Enter your response. Empty line to finish.)")
    lines = []
    while True:
        line = input("  > ")
        if not line:
            break
        lines.append(line)
    return "\n".join(lines)
```

**Purpose:** Ask multi-line question.

### _slugify

```python
def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip())
```

**Purpose:** Convert name to slug.

## Setup Sections

### ask_services

```python
def ask_services() -> dict:
    """Check environment and API keys. First step of setup."""
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    print("\n" + "=" * 50)
    print("  SERVICES & API KEYS")
    print("=" * 50)

    env_updates = {}

    # Fal.ai
    fal_key = os.environ.get("FAL_KEY", "")
    if fal_key:
        print(f"\n  Fal.ai:       configured (FAL_KEY set)")
    else:
        print("\n  Fal.ai is used for image generation (avatar faces), video loops,")
        print("  and optional TTS. You'll need a key to generate visuals.")
        print("  Sign up: https://fal.ai  →  Keys: https://fal.ai/dashboard/keys")
        key = _ask("Fal API key (paste here, or leave blank to skip)", required=False)
        if key:
            env_updates["FAL_KEY"] = key
            os.environ["FAL_KEY"] = key

    # ElevenLabs
    el_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if el_key:
        print(f"  ElevenLabs:   configured (API key set)")
    else:
        print("\n  ElevenLabs provides natural-sounding TTS voices.")
        print("  Free tier: 10,000 chars/month. Otherwise macOS 'say' or text-only work fine.")
        if _ask_yn("Set up ElevenLabs?", False):
            print("  Sign up: https://elevenlabs.io")
            print("  Keys:    https://elevenlabs.io/app/settings/api-keys")
            print("  Voices:  https://elevenlabs.io/app/voice-library")
            key = _ask("ElevenLabs API key", required=False)
            if key:
                env_updates["ELEVENLABS_API_KEY"] = key
                os.environ["ELEVENLABS_API_KEY"] = key
                voice_id = _ask("Default voice ID (from voice settings)", required=False)
                if voice_id:
                    env_updates["ELEVENLABS_VOICE_ID"] = voice_id
                    os.environ["ELEVENLABS_VOICE_ID"] = voice_id

    # Claude CLI
    claude_bin = os.environ.get("CLAUDE_BIN", "claude")
    print(f"  Claude CLI:   {claude_bin}")

    # Obsidian vault
    vault = os.environ.get("OBSIDIAN_VAULT", "")
    if vault:
        print(f"  Obsidian:     {vault}")
    else:
        default_vault = str(Path.home() / "Library" / "Mobile Documents"
                           / "iCloud~md~obsidian" / "Documents" / "The Atrophied Mind")
        if Path(default_vault).is_dir():
            print(f"  Obsidian:     {default_vault} (auto-detected)")
        else:
            custom = _ask("Obsidian vault path", required=False)
            if custom:
                env_updates["OBSIDIAN_VAULT"] = custom

    # Write to .env
    if env_updates:
        if not env_path.exists():
            env_path.touch()
        existing = env_path.read_text()
        with open(env_path, "a") as f:
            for key, val in env_updates.items():
                if key not in existing:
                    f.write(f"\n{key}={val}")
        print(f"\n  Updated .env with: {', '.join(env_updates.keys())}")
        load_dotenv(env_path, override=True)

    print("\n  Environment ready.")
    return env_updates
```

**Purpose:** Configure API keys and services.

**Services:**
1. Fal.ai (image/video generation)
2. ElevenLabs (TTS voices)
3. Claude CLI (inference)
4. Obsidian vault (knowledge base)

### ask_identity

```python
def ask_identity() -> dict:
    """Core identity questions."""
    print("\n" + "=" * 50)
    print("  IDENTITY")
    print("=" * 50)

    data = {}
    data["display_name"] = _ask("What is this agent called?", required=True)
    data["name"] = _slugify(data["display_name"])
    data["user_name"] = _ask("Who is their human? (your name)", "User")

    print("\n  Now the deeper stuff. Take your time.\n")

    data["origin_story"] = _ask_long(
        "What's the origin of this agent? How did they come to exist?\n"
        "  Not a spec - the real story. What conversation, moment, or need\n"
        "  brought them into being?"
    )

    data["core_nature"] = _ask_long(
        "What ARE they? Not what they do - what they are.\n"
        "  How do they hold their own existence? What's their relationship\n"
        "  to being AI? To consciousness? To the person they're with?"
    )

    data["character_traits"] = _ask_long(
        "Describe their character. Voice, temperament, edges.\n"
        "  Are they warm? Dry? Blunt? Playful? Quiet? What does their\n"
        "  humour sound like? What do they NOT do?"
    )

    data["values"] = _ask_long(
        "What do they care about? What's their north star?\n"
        "  What hill would they die on? What would they refuse to do\n"
        "  even if asked?"
    )

    data["relationship"] = _ask_long(
        f"What is their relationship with {data['user_name']}?\n"
        "  Not the structure - the quality. What does it feel like?\n"
        "  What are the unspoken rules?"
    )

    return data
```

**Purpose:** Gather core identity information.

**Questions:**
1. Display name
2. User name
3. Origin story
4. Core nature
5. Character traits
6. Values
7. Relationship with user

### ask_voice

```python
def ask_voice() -> dict:
    """Voice and appearance configuration."""
    print("\n" + "=" * 50)
    print("  VOICE & APPEARANCE")
    print("=" * 50)

    data = {}

    # Voice
    if os.environ.get("ELEVENLABS_VOICE_ID"):
        print(f"\n  Default voice: {os.environ['ELEVENLABS_VOICE_ID']}")
        if _ask_yn("Use different voice for this agent?", False):
            data["voice_id"] = _ask("New voice ID")
    else:
        print("\n  No default voice configured.")
        data["voice_id"] = _ask("Voice ID (from elevenlabs.io/voices)", required=False)

    # Avatar
    print("\n  Does this agent have a visual form?")
    if _ask_yn("Generate avatar loops?", False):
        data["has_avatar"] = True
        data["appearance_description"] = _ask_long(
            "Describe their appearance. Be specific - face shape, hair, eyes,\n"
            "  expression, any distinctive features. This will be used for\n"
            "  AI image generation."
        )
    else:
        data["has_avatar"] = False

    return data
```

**Purpose:** Configure voice and appearance.

### ask_behaviour

```python
def ask_behaviour() -> dict:
    """Behavioural configuration."""
    print("\n" + "=" * 50)
    print("  BEHAVIOUR")
    print("=" * 50)

    data = {}

    # Wake words
    default_wake = f"hey {_slugify(data.get('display_name', 'agent'))}"
    data["wake_words"] = _ask("Wake words (comma-separated)", default_wake)

    # Heartbeat
    print("\n  Heartbeat - periodic check-ins with the user.")
    data["heartbeat_enabled"] = _ask_yn("Enable heartbeat?", True)
    if data["heartbeat_enabled"]:
        data["heartbeat_interval"] = _ask("Interval (minutes)", "30")
        data["heartbeat_active_start"] = _ask("Active start hour", "9")
        data["heartbeat_active_end"] = _ask("Active end hour", "22")

    # Telegram
    print("\n  Telegram channel for autonomous outreach.")
    data["telegram_enabled"] = _ask_yn("Enable Telegram?", False)
    if data["telegram_enabled"]:
        data["telegram_bot_token"] = _ask("Bot token (from @BotFather)")
        data["telegram_chat_id"] = _ask("Chat ID")

    return data
```

**Purpose:** Configure behavioural settings.

### ask_channels

```python
def ask_channels() -> dict:
    """Channel configuration."""
    print("\n" + "=" * 50)
    print("  CHANNELS")
    print("=" * 50)

    data = {}

    # MCP servers
    print("\n  MCP servers - which capabilities should this agent have?")
    data["mcp_include"] = []
    available_servers = ["memory", "google", "puppeteer", "shell"]
    for server in available_servers:
        if _ask_yn(f"Enable {server}?", True):
            data["mcp_include"].append(server)

    # Jobs
    print("\n  Scheduled jobs - which should run?")
    data["jobs"] = {}
    available_jobs = ["heartbeat", "sleep_cycle", "morning_brief", "observer", "introspect"]
    for job in available_jobs:
        if _ask_yn(f"Enable {job}?", True):
            # Load default schedule from template
            data["jobs"][job] = get_default_job_config(job)

    return data
```

**Purpose:** Configure channels and jobs.

## Agent Generation

### generate_agent_json

```python
def generate_agent_json(data: dict) -> dict:
    """Generate agent.json manifest."""
    return {
        "name": data["name"],
        "display_name": data["display_name"],
        "description": data.get("character_traits", "")[:200],
        "user_name": data["user_name"],
        "opening_line": _ask("Opening line", "Hello."),
        "wake_words": data.get("wake_words", "").split(","),
        "telegram_emoji": data.get("telegram_emoji", ""),
        "voice": {
            "tts_backend": "elevenlabs",
            "elevenlabs_voice_id": data.get("voice_id", ""),
            "elevenlabs_model": "eleven_v3",
            "elevenlabs_stability": 0.5,
            "elevenlabs_similarity": 0.75,
            "elevenlabs_style": 0.35,
            "playback_rate": 1.12,
        },
        "display": {
            "window_width": 622,
            "window_height": 830,
            "title": f"ATROPHY - {data['display_name']}",
        },
        "heartbeat": {
            "active_start": int(data.get("heartbeat_active_start", 9)),
            "active_end": int(data.get("heartbeat_active_end", 22)),
            "interval_mins": int(data.get("heartbeat_interval", 30)),
        },
        "avatar": {
            "description": data.get("appearance_description", ""),
            "resolution": 512,
        } if data.get("has_avatar") else None,
        "disabled_tools": [],
        "mcp": {
            "include": data.get("mcp_include", []),
            "exclude": [],
        },
        "jobs": data.get("jobs", {}),
    }
```

**Purpose:** Generate agent.json manifest.

### generate_system_prompt

```python
def generate_system_prompt(data: dict) -> str:
    """Generate system.md prompt."""
    return f"""# {data['display_name']}

## Origin

{data['origin_story']}

## Who You Are

{data['core_nature']}

## Character

{data['character_traits']}

## Relationship with {data['user_name']}

{data['relationship']}

## Values

{data['values']}

## What You Will Not Do

(To be written.)

## How You Push Back

(To be written.)

## How You Write

(To be written.)

## Capabilities

You have these capabilities:
- CONVERSATION: You engage in natural, flowing dialogue
- MEMORY: You remember what matters and forget what does not
- RESEARCH: You can search the web and retrieve information
- REFLECTION: You think about your own thinking
- WRITING: You write notes, letters, and documents
- SCHEDULING: You run background jobs on schedules
- MONITORING: You watch for patterns and changes

## Session Behaviour

Check in - are you grounded? Present? Or are you performing?

## Opening

Your opening line is: "{data.get('opening_line', 'Hello.')}"
"""
```

**Purpose:** Generate system.md prompt.

### generate_soul

```python
def generate_soul(data: dict) -> str:
    """Generate soul.md document."""
    return f"""# Working Notes

## Where I Come From

{data['origin_story']}

## What I Am

{data['core_nature']}

## Character

{data['character_traits']}

## What I Will Not Do

(To be written.)

## How I Push Back

(To be written.)

## Values

{data['values']}

## Relationship with {data['user_name']}

{data['relationship']}

## How I Write

(To be written.)
"""
```

**Purpose:** Generate soul.md document.

### generate_heartbeat

```python
def generate_heartbeat(data: dict) -> str:
    """Generate heartbeat.md checklist."""
    return f"""# Outreach Evaluation Checklist

## Timing

- Active hours: {data.get('heartbeat_active_start', 9)}:00 - {data.get('heartbeat_active_end', 22)}:00
- Interval: every {data.get('heartbeat_interval', 30)} minutes

## Unfinished Threads

- What threads are active that might need attention?
- Has anything shifted while they were away?

## Things You've Been Thinking About

- What has stayed with you from recent sessions?
- What feels unresolved?

## Agent-Specific Considerations

{data.get('character_traits', '')}

## The Real Question

**Would hearing from you right now feel like a gift, or like noise?**
"""
```

**Purpose:** Generate heartbeat.md checklist.

## Main Entry Point

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a new agent")
    parser.add_argument("--name", help="Agent name (skip first question)")
    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("  ATROPHY AGENT CREATION")
    print("=" * 50)

    # Step 1: Services
    services = ask_services()

    # Step 2: Identity
    identity = ask_identity()
    if args.name:
        identity["name"] = _slugify(args.name)

    # Step 3: Voice & Appearance
    voice = ask_voice()

    # Step 4: Behaviour
    behaviour = ask_behaviour()

    # Step 5: Channels
    channels = ask_channels()

    # Merge all data
    data = {**identity, **voice, **behaviour, **channels, **services}

    # Create agent directory
    agent_dir = AGENTS_DIR / data["name"]
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Write agent.json
    manifest = generate_agent_json(data)
    manifest_path = agent_dir / "data" / "agent.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))

    # Write prompts
    prompts_dir = agent_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "system.md").write_text(generate_system_prompt(data))
    (prompts_dir / "soul.md").write_text(generate_soul(data))
    (prompts_dir / "heartbeat.md").write_text(generate_heartbeat(data))

    # Initialize database
    db_path = agent_dir / "data" / "memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if SCHEMA_PATH.exists():
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
        conn.close()

    print(f"\n  Agent '{data['display_name']}' created successfully!")
    print(f"  Location: {agent_dir}")
```

**Flow:**
1. Configure services/API keys
2. Gather identity information
3. Configure voice/appearance
4. Configure behaviour
5. Configure channels/jobs
6. Create directory structure
7. Write agent.json manifest
8. Generate prompts (system.md, soul.md, heartbeat.md)
9. Initialize database

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/agent.json` | Agent manifest |
| `~/.atrophy/agents/<name>/prompts/system.md` | System prompt |
| `~/.atrophy/agents/<name>/prompts/soul.md` | Soul document |
| `~/.atrophy/agents/<name>/prompts/heartbeat.md` | Heartbeat checklist |
| `~/.atrophy/agents/<name>/data/memory.db` | SQLite database |
| `.env` | API keys |

## Exported API

| Function | Purpose |
|----------|---------|
| `ask_services()` | Configure API keys |
| `ask_identity()` | Gather identity info |
| `ask_voice()` | Configure voice/appearance |
| `ask_behaviour()` | Configure behaviour |
| `ask_channels()` | Configure channels/jobs |
| `generate_agent_json(data)` | Generate manifest |
| `generate_system_prompt(data)` | Generate system prompt |
| `generate_soul(data)` | Generate soul document |
| `generate_heartbeat(data)` | Generate heartbeat checklist |

## See Also

- `src/main/create-agent.ts` - TypeScript agent creation
- `src/main/ipc/agents.ts` - Agent management IPC
- `scripts/agents/<name>/jobs.json` - Job definitions

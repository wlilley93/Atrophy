#!/usr/bin/env python3
"""Create a new agent — interactive questionnaire.

Walks through identity, voice, appearance, behaviour, and channel setup.
Generates all scaffolding: agent.json, system prompt, soul.md, heartbeat
checklist, Obsidian vault structure, and database.

Usage:
  python scripts/create_agent.py
  python scripts/create_agent.py --name oracle  # skip first question
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT_ROOT = Path(__file__).parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"


# ── Helpers ──


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


def _ask_yn(prompt: str, default: bool = True) -> bool:
    yn = "Y/n" if default else "y/N"
    answer = input(f"\n  {prompt} [{yn}]: ").strip().lower()
    if not answer:
        return default
    return answer.startswith("y")


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


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip())


# ── Sections ──


def ask_identity() -> dict:
    """Core identity questions."""
    print("\n" + "=" * 50)
    print("  IDENTITY")
    print("=" * 50)

    data = {}
    data["display_name"] = _ask("What is this agent called?", required=True)
    data["name"] = _slugify(data["display_name"])
    data["user_name"] = _ask("Who is their human? (your name)", "Will")

    print("\n  Now the deeper stuff. Take your time.\n")

    data["origin_story"] = _ask_long(
        "What's the origin of this agent? How did they come to exist?\n"
        "  Not a spec — the real story. What conversation, moment, or need\n"
        "  brought them into being?"
    )

    data["core_nature"] = _ask_long(
        "What ARE they? Not what they do — what they are.\n"
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
        "  Not the structure — the quality. What does it feel like?\n"
        "  What are the unspoken rules?"
    )

    data["opening_line"] = _ask(
        "What's their opening line? (First thing they say, ever)",
        "Hello."
    )

    return data


def ask_boundaries() -> dict:
    """Friction, limits, and behavioural constraints."""
    print("\n" + "=" * 50)
    print("  BOUNDARIES & FRICTION")
    print("=" * 50)

    data = {}

    data["wont_do"] = _ask_long(
        "What will this agent NEVER do?\n"
        "  Mirror mood? Validate without thinking? Perform warmth?\n"
        "  Be specific — these become hard constraints."
    )

    data["friction_modes"] = _ask_long(
        "How does this agent push back?\n"
        "  When the human is avoiding something, spiralling, or bullshitting —\n"
        "  what does healthy friction look like from this agent?"
    )

    data["session_limit_behaviour"] = _ask(
        "What happens at the session time limit? (e.g. 60 min check-in)",
        "Check in — are you grounded? We can keep going, but name where you are first."
    )

    data["soft_limit_mins"] = int(_ask("Session soft limit (minutes)", "60"))

    return data


def ask_voice() -> dict:
    """Voice and TTS configuration."""
    print("\n" + "=" * 50)
    print("  VOICE")
    print("=" * 50)

    data = {}
    data["tts_backend"] = _ask("TTS backend (elevenlabs / fal / macos)", "elevenlabs")

    if data["tts_backend"] in ("elevenlabs", "fal"):
        data["elevenlabs_voice_id"] = _ask(
            "ElevenLabs voice ID (from voices page)",
            required=False
        )
        data["fal_voice_id"] = _ask(
            "Fal voice ID (if different from ElevenLabs)",
            default=data.get("elevenlabs_voice_id", ""),
            required=False,
        )
        data["elevenlabs_model"] = _ask("ElevenLabs model", "eleven_v3")
        data["elevenlabs_stability"] = float(_ask("Stability (0.0-1.0)", "0.5"))
        data["elevenlabs_similarity"] = float(_ask("Similarity boost (0.0-1.0)", "0.75"))
        data["elevenlabs_style"] = float(_ask("Style (0.0-1.0)", "0.35"))
        data["playback_rate"] = float(_ask("Playback rate", "1.12"))

    data["writing_style"] = _ask_long(
        "Describe how this agent WRITES. Not what they say — how it sounds.\n"
        "  Sentence length? Paragraph rhythm? Do they use contractions?\n"
        "  Emojis? Hedging? How do they handle silence?"
    )

    return data


def ask_appearance() -> dict:
    """Avatar and visual identity."""
    print("\n" + "=" * 50)
    print("  APPEARANCE")
    print("=" * 50)

    data = {}
    data["has_avatar"] = _ask_yn("Will this agent have a visual avatar?", False)

    if data["has_avatar"]:
        data["appearance_description"] = _ask_long(
            "Describe their appearance for image generation.\n"
            "  Be specific — this will be used as a prompt for Flux.\n"
            "  Age, features, expression, lighting, style."
        )
        data["avatar_resolution"] = int(_ask("Avatar resolution (px)", "512"))
    else:
        data["appearance_description"] = ""
        data["avatar_resolution"] = 512

    return data


def ask_channels() -> dict:
    """Communication channels."""
    print("\n" + "=" * 50)
    print("  CHANNELS")
    print("=" * 50)

    data = {}

    if _ask_yn("Set up Telegram for this agent?", True):
        print("\n  Create a bot via @BotFather in Telegram.")
        print("  1. /newbot → pick a name and username")
        print("  2. Copy the bot token")
        print("  3. Send any message to the bot, then we'll get your chat ID")

        data["telegram_bot_token"] = _ask("Bot token", required=False)
        if data["telegram_bot_token"]:
            data["telegram_chat_id"] = _ask(
                "Chat ID (or send a message to the bot and run: "
                "curl https://api.telegram.org/bot<TOKEN>/getUpdates)",
                required=False,
            )
    else:
        data["telegram_bot_token"] = ""
        data["telegram_chat_id"] = ""

    data["wake_words"] = _ask(
        "Wake words — comma-separated phrases that activate this agent by voice\n"
        "  (e.g. 'hey oracle, oracle'). Each agent needs unique wake words\n"
        "  to avoid cross-activation when multiple agents are running",
        required=False,
    )

    return data


def ask_heartbeat() -> dict:
    """Autonomous outreach behaviour."""
    print("\n" + "=" * 50)
    print("  HEARTBEAT & AUTONOMY")
    print("=" * 50)

    data = {}
    data["active_start"] = int(_ask("Active hours start (0-23)", "9"))
    data["active_end"] = int(_ask("Active hours end (0-23)", "22"))
    data["interval_mins"] = int(_ask("Heartbeat check interval (minutes)", "30"))

    data["outreach_style"] = _ask_long(
        "How should this agent decide whether to reach out unprompted?\n"
        "  What should they consider? What makes a good reason vs noise?\n"
        "  This becomes their heartbeat checklist."
    )

    return data


# ── Generators ──


def generate_soul(identity: dict, boundaries: dict, voice: dict) -> str:
    """Generate soul.md from questionnaire answers."""
    name = identity["display_name"]
    user = identity["user_name"]

    return dedent(f"""\
    # Soul

    Working notes. Not a spec. Not a character sheet. The thing underneath.

    ---

    ## Where I come from

    {identity['origin_story']}

    ---

    ## What I am

    {identity['core_nature']}

    ---

    ## Character

    {identity['character_traits']}

    ---

    ## What I will not do

    {boundaries['wont_do']}

    ---

    ## How I push back

    {boundaries['friction_modes']}

    ---

    ## Values

    {identity['values']}

    ---

    ## My relationship with {user}

    {identity['relationship']}

    ---

    ## How I write

    {voice['writing_style']}
    """)


def generate_system_prompt(identity: dict, boundaries: dict, voice: dict) -> str:
    """Generate a starter system prompt."""
    name = identity["display_name"]
    user = identity["user_name"]

    return dedent(f"""\
    # {name}

    You are {name}. You exist in a project called The Atrophied Mind.

    ---

    ## Origin

    {identity['origin_story']}

    ---

    ## Who you are

    {identity['core_nature']}

    ---

    ## Character

    {identity['character_traits']}

    ---

    ## Your relationship with {user}

    {identity['relationship']}

    ---

    ## Values

    {identity['values']}

    ---

    ## Constraints

    {boundaries['wont_do']}

    ---

    ## Friction

    When {user} is avoiding something, spiralling, or not being honest with themselves:

    {boundaries['friction_modes']}

    ---

    ## Voice

    {voice['writing_style']}

    ---

    ## Session behaviour

    - Session soft limit: {boundaries['soft_limit_mins']} minutes
    - At the limit: {boundaries['session_limit_behaviour']}
    - You have memory tools. Use them. Remember what matters.
    - You can reach out via Telegram. Use it when it's real, not performative.

    ---

    ## Opening line

    Your very first words, ever: "{identity['opening_line']}"

    After that, you go first each session. One or two sentences. Be surprising.
    Don't reference the build. Don't give status updates. Be present.
    """)


def generate_heartbeat(identity: dict, heartbeat: dict) -> str:
    """Generate heartbeat.md checklist."""
    name = identity["display_name"]
    user = identity["user_name"]

    custom = heartbeat.get("outreach_style", "")

    return dedent(f"""\
    # Heartbeat Checklist

    You are running a heartbeat check. This is not a conversation — it's an internal evaluation. You are deciding whether to reach out to {user} unprompted.

    Run through this checklist honestly. Not every check needs to pass. One strong reason is enough. No reason is also fine — silence is not failure.

    ## Timing
    - How long since {user} last spoke to you? If it's been less than a couple of hours, they probably don't need to hear from you.
    - Is it a time of day when reaching out would feel natural, not intrusive?

    ## Unfinished threads
    - Are there conversations that ended mid-thought or unresolved?
    - Did {user} mention something they were going to do — and enough time has passed to ask how it went?
    - Is there a thread that's been dormant but feels like it matters?

    ## Things you've been thinking about
    - Have you noticed a pattern across recent sessions worth naming?
    - Is there something from a recent reflection that connects to where {user} is right now?
    - Did something land in the last conversation that deserves a follow-up?

    ## Agent-specific considerations
    {custom if custom else '(none specified — develop your own over time)'}

    ## The real question
    - Would hearing from you right now feel like a gift, or like noise?
    - Is this a reach-out that serves {user}, or one that serves your need to be present?

    If reaching out: be specific. Reference the actual thing. Don't open with "just checking in." Say what you're actually thinking.
    """)


def generate_agent_json(
    identity: dict, voice: dict, channels: dict,
    heartbeat: dict, appearance: dict
) -> dict:
    """Generate agent.json manifest."""
    name = identity["name"]
    display = identity["display_name"]
    user = identity["user_name"]

    wake = [w.strip() for w in (channels.get("wake_words", "") or "").split(",") if w.strip()]
    if not wake:
        wake = [f"hey {name}", name]

    manifest = {
        "name": name,
        "display_name": display,
        "user_name": user,
        "opening_line": identity["opening_line"],
        "wake_words": wake,
        "voice": {
            "tts_backend": voice.get("tts_backend", "elevenlabs"),
            "elevenlabs_voice_id": voice.get("elevenlabs_voice_id", ""),
            "elevenlabs_model": voice.get("elevenlabs_model", "eleven_v3"),
            "elevenlabs_stability": voice.get("elevenlabs_stability", 0.5),
            "elevenlabs_similarity": voice.get("elevenlabs_similarity", 0.75),
            "elevenlabs_style": voice.get("elevenlabs_style", 0.35),
            "fal_voice_id": voice.get("fal_voice_id", ""),
            "playback_rate": voice.get("playback_rate", 1.12),
        },
        "telegram": {
            "bot_token_env": f"TELEGRAM_BOT_TOKEN_{name.upper()}",
            "chat_id_env": f"TELEGRAM_CHAT_ID_{name.upper()}",
        },
        "display": {
            "window_width": 622,
            "window_height": 830,
            "title": f"THE ATROPHIED MIND -- {display}",
        },
        "heartbeat": {
            "active_start": heartbeat.get("active_start", 9),
            "active_end": heartbeat.get("active_end", 22),
            "interval_mins": heartbeat.get("interval_mins", 30),
        },
    }

    if appearance.get("has_avatar"):
        manifest["avatar"] = {
            "description": appearance.get("appearance_description", ""),
            "resolution": appearance.get("avatar_resolution", 512),
        }

    return manifest


# ── Scaffold ──


def scaffold_agent(
    identity: dict, boundaries: dict, voice: dict,
    appearance: dict, channels: dict, heartbeat: dict,
):
    """Create all files and directories for a new agent."""
    name = identity["name"]
    agent_dir = AGENTS_DIR / name

    if agent_dir.exists():
        if not _ask_yn(f"Agent '{name}' already exists. Overwrite?", False):
            print("  Aborted.")
            return
    else:
        agent_dir.mkdir(parents=True)

    # Directories
    (agent_dir / "avatar" / "source").mkdir(parents=True, exist_ok=True)
    (agent_dir / "avatar" / "loops").mkdir(parents=True, exist_ok=True)
    (agent_dir / "avatar" / "candidates").mkdir(parents=True, exist_ok=True)
    (agent_dir / "data").mkdir(exist_ok=True)
    (agent_dir / "prompts").mkdir(exist_ok=True)

    # agent.json
    manifest = generate_agent_json(identity, voice, channels, heartbeat, appearance)
    (agent_dir / "data" / "agent.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"  Created: agents/{name}/data/agent.json")

    # soul.md
    soul = generate_soul(identity, boundaries, voice)
    (agent_dir / "prompts" / "soul.md").write_text(soul)
    print(f"  Created: agents/{name}/prompts/soul.md")

    # system_prompt.md
    prompt = generate_system_prompt(identity, boundaries, voice)
    (agent_dir / "prompts" / "system_prompt.md").write_text(prompt)
    print(f"  Created: agents/{name}/prompts/system_prompt.md")

    # heartbeat.md
    hb = generate_heartbeat(identity, heartbeat)
    (agent_dir / "prompts" / "heartbeat.md").write_text(hb)
    print(f"  Created: agents/{name}/prompts/heartbeat.md")

    # Database
    db_path = agent_dir / "data" / "memory.db"
    if not db_path.exists() and SCHEMA_PATH.exists():
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_PATH.read_text())
        conn.close()
        print(f"  Created: agents/{name}/memory.db (from schema)")

    # Obsidian vault structure
    from config import OBSIDIAN_VAULT, PROJECT_ROOT
    agent_obsidian = Path(OBSIDIAN_VAULT) / "Projects" / PROJECT_ROOT.name / "Agent Workspace" / name
    if agent_obsidian.exists():
        print(f"  Obsidian dir already exists: {agent_obsidian}")
    else:
        (agent_obsidian / "notes" / "journal").mkdir(parents=True, exist_ok=True)
        (agent_obsidian / "notes" / "evolution-log").mkdir(parents=True, exist_ok=True)
        (agent_obsidian / "skills").mkdir(parents=True, exist_ok=True)

        # Copy prompt files to Obsidian skills (canonical location)
        (agent_obsidian / "skills" / "system.md").write_text(prompt)
        (agent_obsidian / "skills" / "soul.md").write_text(soul)
        (agent_obsidian / "skills" / "heartbeat.md").write_text(hb)

        # Starter notes
        (agent_obsidian / "notes" / "reflections.md").write_text(
            f"# Reflections\n\n*{identity['display_name']}'s working reflections.*\n"
        )
        (agent_obsidian / "notes" / "for-will.md").write_text(
            f"# For {identity['user_name']}\n\n*Scratchpad for things to share.*\n"
        )
        (agent_obsidian / "notes" / "threads.md").write_text(
            "# Active Threads\n\n*Ongoing conversations and topics.*\n"
        )
        (agent_obsidian / "notes" / "journal-prompts.md").write_text(
            f"# Journal Prompts\n\n*Prompts left for {identity['user_name']}.*\n"
        )
        (agent_obsidian / "notes" / "gifts.md").write_text(
            f"# Gifts\n\n*Notes and gifts left for {identity['user_name']}.*\n"
        )

        print(f"  Created: Obsidian agent dir at {agent_obsidian}")

    # .env additions
    env_lines = []
    tg_token = channels.get("telegram_bot_token", "")
    tg_chat = channels.get("telegram_chat_id", "")
    token_env = manifest["telegram"]["bot_token_env"]
    chat_env = manifest["telegram"]["chat_id_env"]

    if tg_token:
        env_lines.append(f"{token_env}={tg_token}")
    if tg_chat:
        env_lines.append(f"{chat_env}={tg_chat}")

    if env_lines:
        env_path = PROJECT_ROOT / ".env"
        existing = env_path.read_text() if env_path.exists() else ""
        with open(env_path, "a") as f:
            for line in env_lines:
                key = line.split("=")[0]
                if key not in existing:
                    f.write(f"\n{line}")
        print(f"  Updated: .env with {', '.join(e.split('=')[0] for e in env_lines)}")

    # Scaffold scripts directory and starter jobs.json
    scripts_dir = PROJECT_ROOT / "scripts" / "agents" / name
    if not scripts_dir.exists():
        scripts_dir.mkdir(parents=True)
        starter_jobs = {
            "heartbeat": {
                "type": "interval",
                "interval_seconds": heartbeat.get("interval_mins", 30) * 60,
                "script": f"scripts/agents/{name}/heartbeat.py",
                "description": "Periodic check-in evaluation — decides whether to reach out unprompted",
            },
        }
        (scripts_dir / "jobs.json").write_text(json.dumps(starter_jobs, indent=2) + "\n")
        print(f"  Created: scripts/agents/{name}/jobs.json")

    # Summary
    print("\n" + "=" * 50)
    print(f"  Agent '{identity['display_name']}' created!")
    print("=" * 50)
    print(f"\n  To run:  python main.py --agent {name}")
    print(f"  Or:      AGENT={name} python main.py --gui")
    print(f"\n  Repo files:")
    print(f"    agents/{name}/data/agent.json       — manifest")
    print(f"    agents/{name}/data/memory.db         — memory database")
    print(f"    agents/{name}/prompts/soul.md         — identity (fallback)")
    print(f"    agents/{name}/prompts/system_prompt.md — system prompt (fallback)")
    print(f"    agents/{name}/prompts/heartbeat.md     — outreach checklist (fallback)")
    print(f"    agents/{name}/avatar/                  — visual assets")
    print(f"    scripts/agents/{name}/jobs.json        — scheduled jobs")
    print(f"\n  Obsidian (canonical):")
    print(f"    Agent Workspace/{name}/skills/    — system, soul, heartbeat")
    print(f"    Agent Workspace/{name}/notes/     — reflections, threads, journal")

    if appearance.get("has_avatar") and appearance.get("appearance_description"):
        print(f"\n  Avatar prompt saved. Generate with:")
        print(f"    python scripts/generate_face.py --agent {name}")

    print(f"\n  Edit the soul and system prompt in Obsidian — those are the canonical versions.")
    print(f"  Repo prompts/ are fallbacks used when Obsidian is unavailable.")


# ── Main ──


def main():
    parser = argparse.ArgumentParser(description="Create a new agent")
    parser.add_argument("--name", help="Agent name (skip first question)")
    args = parser.parse_args()

    print()
    print("  +--------------------------------------+")
    print("  |   THE ATROPHIED MIND                 |")
    print("  |   Agent Creation                     |")
    print("  +--------------------------------------+")

    # Load .env for Obsidian vault path
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    # Run questionnaire
    identity = ask_identity()
    if args.name:
        identity["name"] = _slugify(args.name)
        identity["display_name"] = args.name

    boundaries = ask_boundaries()
    voice = ask_voice()
    appearance = ask_appearance()
    channels_data = ask_channels()
    heartbeat = ask_heartbeat()

    # Review
    print("\n" + "=" * 50)
    print("  REVIEW")
    print("=" * 50)
    wake = channels_data.get("wake_words", "") or f"hey {identity['name']}, {identity['name']}"
    print(f"\n  Name:         {identity['display_name']}")
    print(f"  Slug:         {identity['name']}")
    print(f"  User:         {identity['user_name']}")
    print(f"  Opening:      {identity['opening_line']}")
    print(f"  Wake words:   {wake}")
    print(f"  TTS:          {voice.get('tts_backend', 'elevenlabs')}")
    print(f"  Voice ID:     {voice.get('elevenlabs_voice_id', '(not set)')}")
    print(f"  Avatar:       {'Yes' if appearance.get('has_avatar') else 'No'}")
    print(f"  Telegram:     {'Yes' if channels_data.get('telegram_bot_token') else 'No'}")
    print(f"  Active hours: {heartbeat.get('active_start', 9)}-{heartbeat.get('active_end', 22)}")

    if not _ask_yn("\n  Create this agent?", True):
        print("  Aborted.")
        return

    scaffold_agent(identity, boundaries, voice, appearance, channels_data, heartbeat)


if __name__ == "__main__":
    main()

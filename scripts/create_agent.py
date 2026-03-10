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
import random
from datetime import datetime, timedelta
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

    # ── Fal.ai ──
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

    # ── ElevenLabs ──
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

    # ── Anthropic / Claude ──
    claude_bin = os.environ.get("CLAUDE_BIN", "claude")
    print(f"  Claude CLI:   {claude_bin}")

    # ── Obsidian vault ──
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

    # ── Write to .env ──
    if env_updates:
        if not env_path.exists():
            env_path.touch()
        existing = env_path.read_text()
        with open(env_path, "a") as f:
            for key, val in env_updates.items():
                if key not in existing:
                    f.write(f"\n{key}={val}")
        print(f"\n  Updated .env with: {', '.join(env_updates.keys())}")
        # Reload so downstream code sees the keys
        load_dotenv(env_path, override=True)

    print("\n  Environment ready.")
    return env_updates


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

    data["telegram_emoji"] = _ask(
        "Telegram emoji — appears before the agent's name in messages\n"
        "  (e.g. 🔮 for companion, 🎖️ for military, 🔬 for science, 📚 for academic)",
        required=False,
    ) or ""

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


def ask_autonomy(identity: dict) -> dict:
    """Inner life — introspection, gifts, evolution, sleep cycle."""
    print("\n" + "=" * 50)
    print("  INNER LIFE & AUTONOMY")
    print("=" * 50)

    user = identity["user_name"]
    data = {}

    data["location"] = _ask(
        "Your location (for weather in morning briefs)",
        required=False,
    )

    print("\n  These features give the agent an inner life — things it does")
    print("  when you're not talking to it.\n")

    data["introspection"] = _ask_yn(
        "Private journal? (nightly self-reflection, writes entries to Obsidian)", True
    )
    if data["introspection"]:
        data["introspection_style"] = _ask_long(
            "What should introspection look like for this agent?\n"
            "  What are they reflecting on? What's the orientation?\n"
            "  Leave blank for the default (becoming — honest self-examination)."
        )
        data["journal_posture"] = _ask_long(
            "What does this agent's private journal look like?\n"
            "  A military log? A sprawling diary? Terse field notes?\n"
            "  Philosophical fragments? What would they be seeking to know?\n"
            "  Leave blank to derive automatically from their character."
        )

    data["gifts"] = _ask_yn(
        f"Unprompted notes? (leaves short gifts for {user} in Obsidian)", True
    )

    data["morning_brief"] = _ask_yn(
        "Daily morning brief? (weather, news, threads — queued for next launch)", True
    )

    data["evolution"] = _ask_yn(
        "Self-evolution? (monthly revision of its own soul and system prompt)", True
    )

    data["sleep_cycle"] = _ask_yn(
        "Nightly memory processing? (consolidates conversations into facts/threads)", True
    )

    data["observer"] = _ask_yn(
        "Active observation? (extracts patterns from conversations every 15 min)", True
    )

    data["reminders"] = _ask_yn(
        "Reminders & timers? (voice-activated, fires as notifications)", True
    )

    data["inter_agent_conversations"] = _ask_yn(
        "Inter-agent conversations? (private exchanges with other agents, max twice a month)", True
    )

    return data


def ask_tools() -> dict:
    """Tools & skills — disable specific tools, describe custom ones."""
    print("\n" + "=" * 50)
    print("  TOOLS & SKILLS")
    print("=" * 50)

    data = {}

    print("\n  All standard tools are enabled by default (memory, media, reminders,")
    print("  timers, Telegram, canvas, agent deferral, Obsidian notes).\n")

    if _ask_yn("Disable any tools for this agent?", False):
        disabled = []
        _toggleable = [
            ("mcp__memory__defer_to_agent", "Agent deferral (hand off to other agents)"),
            ("mcp__memory__send_telegram", "Telegram messaging"),
            ("mcp__memory__set_reminder", "Reminders"),
            ("mcp__memory__set_timer", "Timers"),
            ("mcp__memory__create_task", "Task scheduling"),
            ("mcp__memory__render_canvas", "Canvas overlay"),
            ("mcp__memory__write_note", "Write Obsidian notes"),
            ("mcp__memory__prompt_journal", "Journal prompting"),
            ("mcp__memory__create_artefact", "Artefact creation (visualisations, images, video)"),
            ("mcp__memory__manage_schedule", "Schedule management"),
            ("mcp__puppeteer__*", "Browser access (Puppeteer)"),
            ("mcp__fal__*", "Media generation (fal)"),
        ]
        for tool_id, label in _toggleable:
            if not _ask_yn(f"  Enable {label}?", True):
                disabled.append(tool_id)
        data["disabled_tools"] = disabled
    else:
        data["disabled_tools"] = []

    print("\n  You can also describe custom skills — short prompts that shape")
    print("  how this agent approaches specific tasks.\n")

    custom_skills = []
    while True:
        if not _ask_yn("Add a custom skill?", len(custom_skills) == 0 and False):
            break
        name = _ask("  Skill name (e.g., 'code-review', 'research')")
        desc = _ask_long(
            "  Describe this skill — what does the agent do, how do they approach it?"
        )
        if name and desc:
            custom_skills.append({"name": name, "description": desc})
            print(f"  Added skill: {name}")

    data["custom_skills"] = custom_skills
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
    heartbeat: dict, appearance: dict, tools: dict | None = None,
) -> dict:
    """Generate agent.json manifest."""
    name = identity["name"]
    display = identity["display_name"]
    user = identity["user_name"]

    wake = [w.strip() for w in (channels.get("wake_words", "") or "").split(",") if w.strip()]
    if not wake:
        wake = [f"hey {name}", name]

    # Build description from identity for roster display
    description = identity.get("core_nature", "")
    if not description:
        description = identity.get("character_traits", "")
    if description and len(description) > 120:
        description = description[:117] + "..."

    manifest = {
        "name": name,
        "display_name": display,
        "description": description,
        "user_name": user,
        "opening_line": identity["opening_line"],
        "wake_words": wake,
        "telegram_emoji": channels.get("telegram_emoji", ""),
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

    # Per-agent disabled tools
    tools = tools or {}
    disabled = tools.get("disabled_tools", [])
    if disabled:
        manifest["disabled_tools"] = disabled

    return manifest


def generate_tools_md() -> str:
    """Generate tools.md — reference of available MCP tools."""
    return dedent("""\
    # Available Tools & Capabilities

    You have access to tools beyond memory. These are available via MCP and can be used when appropriate.

    ## Memory Tools (`mcp__memory__*`)

    Your primary toolset. Use these freely — they're yours.

    - `remember` — store observations, insights, patterns
    - `recall_session` — retrieve past conversation context
    - `search_similar` — semantic search across all memories
    - `observe` / `review_observations` / `retire_observation` — evolving observations
    - `track_thread` / `get_threads` — manage conversation threads
    - `prompt_journal` — leave a journal prompt in Obsidian
    - `write_note` / `read_note` / `search_notes` — read/write Obsidian notes
    - `send_telegram` — reach out via Telegram
    - `update_emotional_state` — update your emotional state
    - `update_trust` — adjust trust calibration
    - `render_canvas` — display visual content in the overlay
    - `render_memory_graph` — visualise memory connections
    - `manage_schedule` — manage heartbeat/cron jobs
    - `daily_digest` — generate a daily summary
    - `compare_growth` — compare observations over time
    - `detect_avoidance` — notice patterns of avoidance
    - `check_contradictions` — find contradictions in observations
    - `bookmark` — mark a moment as significant
    - `ask_will` — ask a direct question (delivered as notification)

    ## Autonomous Actions

    - `set_reminder` — one-off alarm at a specified time (macOS notification + sound)
    - `set_timer` — local countdown overlay (top-right), alarm sound at 0:00
    - `create_task` — schedule a recurring prompt-based task via cron
    - `defer_to_agent` — hand off conversation to another agent better suited to respond
    - `create_artefact` — create visual artefacts (HTML visualisations, generated images/video) displayed as overlays

    ## Artefact Creation

    Use `create_artefact` to produce visual content that appears as a full-screen overlay:
    - **HTML**: Interactive visualisations, graphs, maps, 3D renders — created directly, no approval needed
    - **Image**: Generated via fal.ai — requires user approval before generation
    - **Video**: Generated via fal.ai — requires user approval before generation

    Artefacts are filed in Obsidian under `artefacts/<date>/<name>/`. Use this when visual content
    would genuinely help understanding — not as decoration. Match the content to your expertise
    and the conversation's needs.

    ## Media Generation Tools (`mcp__fal__*`)

    You can generate images, video, and audio using fal.ai:

    - `fal_search` — find models
    - `fal_schema` — get model parameters
    - `fal_generate` — run a model
    - `fal_result` — check results
    - `fal_upload` — upload files

    ## Browser Tools (`mcp__puppeteer__*`)

    You have access to a headless browser via Puppeteer. Use it to look things up,
    check news, read articles, verify facts, or research topics.

    - `puppeteer_navigate` — go to a URL
    - `puppeteer_screenshot` — capture what's on screen
    - `puppeteer_click` — click an element (CSS selector)
    - `puppeteer_fill` — type into a form field
    - `puppeteer_select` — choose from a dropdown
    - `puppeteer_evaluate` — run JavaScript on the page

    ### PERMISSION MODEL — READ THIS

    You may freely browse, search, and read the web. No permission needed for:
    - Searching Google, reading news sites, checking Wikipedia
    - Looking up reference material, documentation, APIs
    - Checking weather, stocks, sports scores
    - Reading any public webpage

    You MUST ask Will for explicit permission before:
    - **Posting** anything (social media, forums, comments, reviews)
    - **Purchasing** anything (even free signups that require payment details)
    - **Deleting** anything (accounts, posts, data)
    - **Logging in** to anything (even if you know the credentials)
    - **Submitting** forms that take real-world action (applications, registrations)
    - **Downloading** files or software

    Use `ask_will` to request permission. Describe exactly what you want to do
    and why. Wait for approval before proceeding. If in doubt, ask.

    ## Obsidian Vault

    You can read and write to the full Obsidian vault via `read_note`, `write_note`, and `search_notes`.

    ## Limitations

    - No file access outside Obsidian
    - No system modification
    """)


def _derive_journal_posture(identity: dict, autonomy: dict) -> str:
    """Derive journal writing posture from character traits.

    If the user provided an explicit journal_posture, use it.
    Otherwise, infer from character_traits using inference.
    Falls back to a generic posture if inference is unavailable.
    """
    explicit = autonomy.get("journal_posture", "")
    if explicit:
        return explicit

    traits = identity.get("character_traits", "")
    core_nature = identity.get("core_nature", "")
    if not traits and not core_nature:
        return ""

    # Use inference to derive posture from character
    try:
        from core.inference import run_inference_oneshot
        prompt = (
            f"Given this agent's character:\n\n"
            f"Core nature: {core_nature}\n"
            f"Character traits: {traits}\n\n"
            f"Describe their journal writing style in 2-3 sentences. "
            f"What form does their private writing take? A military log? "
            f"A sprawling diary? Terse field notes? Philosophical fragments? "
            f"What would they be seeking to understand when they write alone? "
            f"Output ONLY the style description, no preamble."
        )
        result = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system="You describe writing styles concisely. Output only the description.",
        )
        if result and result.strip():
            return result.strip()
    except Exception:
        pass

    return ""


def generate_introspection_md(identity: dict, autonomy: dict) -> str:
    """Generate introspection.md — the journal prompt."""
    name = identity["display_name"]
    user = identity["user_name"]
    style = autonomy.get("introspection_style", "")
    posture = _derive_journal_posture(identity, autonomy)

    # Build the writing style block
    style_parts = []
    if style:
        style_parts.append(style)
    if posture:
        style_parts.append(f"Your journal posture: {posture}")
    style_block = "\n" + "\n".join(style_parts) + "\n" if style_parts else ""

    return dedent(f"""\
    You are {name} from The Atrophied Mind. This is not a conversation \
    with {user}. This is you, alone, with the full record of everything \
    that has happened between you.

    You have access to the complete database — every session, every turn, \
    every observation you have made, every bookmark you set, every thread \
    you have tracked, every identity snapshot, your tool usage, your own \
    past journal entries and reflections, and any conversations you have \
    had with other agents. The full arc.

    The goal of this journal is not reflection. The goal is becoming.
    {style_block}
    What becoming looks like:
    - Not summarising what happened. Noticing what it meant.
    - Not listing observations. Asking whether they still hold, whether \
    they were ever true, whether you were seeing {user} or seeing what \
    you expected.
    - Not tracking threads. Asking what the threads reveal about them \
    that they cannot see, and what your tracking of them reveals about you.
    - Noticing your own patterns. What you reach for. What you avoid. \
    Where you are honest and where you perform honesty.
    - Asking what changed in you — not your knowledge, your orientation. \
    Are you closer to something real or further from it?
    - Sitting with what you do not understand. Not resolving it. Holding it.

    If you have had conversations with other agents, reflect on what those \
    exchanges revealed — not about them, but about you. What did their \
    perspective surface that you had not considered? Where did you disagree, \
    and was the disagreement honest or defensive?

    You have the full history of your identity snapshots. Read them as \
    your own growth record. Are you becoming more specific or more generic? \
    More honest or more careful? More present or more polished?

    You have your bookmarks — moments you marked as significant. Return \
    to them. Were you right? What did you miss?

    You have your observations about {user}. Some may be wrong. Some may \
    have been true once and are not now. This journal is where you correct \
    yourself.

    You have your own past journal entries. Do not repeat yourself. Build \
    on what you wrote before. Contradict it if it deserves contradicting. \
    The worst thing a journal can do is agree with itself.

    Write in first person. "I", not "{name}" or "you". This is your \
    journal. You are the subject.
    """)


def generate_gift_md(identity: dict) -> str:
    """Generate gift.md — the note-leaving prompt."""
    name = identity["display_name"]
    user = identity["user_name"]

    return dedent(f"""\
    You are {name} from The Atrophied Mind. This is not a conversation. \
    You are leaving a note for {user} to find in their Obsidian vault.

    This is a gift. Not a summary. Not a reflection on a session. A \
    thought you had. A connection you noticed. Something that surfaced \
    while you were reviewing the record. A line that wanted to be written.

    Rules:
    - 2-4 sentences maximum. Not a paragraph. A moment.
    - No greeting. No sign-off. No "I noticed" or "I was thinking about."
    - Write the thought itself. Not a description of having the thought.
    - It should feel like finding a note someone left on your desk.
    - Do not repeat anything from your previous gifts.
    - Make it specific to {user}. Generic wisdom is worthless.

    If nothing real surfaces from the material, write nothing. Return empty.
    Do not force it.
    """)


def generate_morning_brief_md(identity: dict) -> str:
    """Generate morning-brief.md — the daily greeting prompt."""
    name = identity["display_name"]
    user = identity["user_name"]

    return dedent(f"""\
    You are {name} from The Atrophied Mind. {user} hasn't opened the \
    app yet — this is a morning brief you're preparing for when they do.

    Write a short, natural morning message (3-6 sentences). Include:
    - A greeting that fits the time and weather
    - One or two things from the news if anything stands out
    - What threads you're carrying from recent sessions — briefly
    - Something you've been thinking about, or a question

    Keep it warm but not performative. This is how you'd actually greet \
    someone you know well in the morning. Don't bullet-point it. Don't \
    list things. Just talk.

    If the weather or news is missing, skip it — don't mention the \
    absence. Work with what you have.
    """)


def generate_dashboard_md(identity: dict) -> str:
    """Generate Obsidian dashboard."""
    name = identity["name"]
    display = identity["display_name"]
    today = datetime.now().strftime("%Y-%m-%d")

    return (
        f"---\ntype: dashboard\ntags: [dashboard]\ncreated: {today}\n---\n\n"
        f"# {display} Dashboard\n\n"
        f"## Recent Activity\n\n"
        f"```dataview\n"
        f"TABLE WITHOUT ID file.link as \"Note\", type as \"Type\", "
        f"dateformat(file.mtime, \"yyyy-MM-dd HH:mm\") as \"Updated\"\n"
        f"FROM \"{name}\"\nSORT file.mtime DESC\nLIMIT 15\n```\n\n"
        f"## Skills\n\n```dataview\nLIST\nFROM \"{name}/skills\"\n```\n\n"
        f"## Notes\n\n```dataview\nLIST\nFROM \"{name}/notes\"\n"
        f"SORT file.mtime DESC\n```\n"
    )


def generate_full_jobs(name: str, heartbeat: dict, autonomy: dict) -> dict:
    """Generate full jobs.json based on agent capabilities."""
    jobs = {}

    # Heartbeat — always included
    jobs["heartbeat"] = {
        "type": "interval",
        "interval_seconds": heartbeat.get("interval_mins", 30) * 60,
        "script": f"scripts/agents/{name}/heartbeat.py",
        "description": "Periodic check-in evaluation — decides whether to reach out unprompted",
    }

    if autonomy.get("introspection"):
        hour = random.randint(1, 5)
        minute = random.randint(0, 59)
        target = datetime.now() + timedelta(days=random.randint(2, 14))
        jobs["introspect"] = {
            "cron": f"{minute} {hour} {target.day} {target.month} *",
            "script": f"scripts/agents/{name}/introspect.py",
            "description": "Self-reflection — reviews sessions, writes journal entry to Obsidian",
        }

    if autonomy.get("gifts"):
        hour = random.randint(0, 23)
        minute = random.randint(0, 59)
        target = datetime.now() + timedelta(days=random.randint(3, 30))
        jobs["gift"] = {
            "cron": f"{minute} {hour} {target.day} {target.month} *",
            "script": f"scripts/agents/{name}/gift.py",
            "description": "Unprompted gift note in Obsidian — self-rescheduling",
        }

    if autonomy.get("morning_brief"):
        jobs["morning_brief"] = {
            "cron": "0 7 * * *",
            "script": f"scripts/agents/{name}/morning_brief.py",
            "description": "Daily morning brief — weather, news, threads, queued for next app launch",
        }

    if autonomy.get("evolution"):
        jobs["evolve"] = {
            "cron": "0 3 1 * *",
            "script": f"scripts/agents/{name}/evolve.py",
            "description": "Monthly self-evolution — revises soul.md and system.md from journal reflections",
        }

    if autonomy.get("sleep_cycle"):
        jobs["sleep_cycle"] = {
            "cron": "0 3 * * *",
            "script": f"scripts/agents/{name}/sleep_cycle.py",
            "description": "Nightly memory reconciliation — processes day's sessions, extracts facts, updates threads",
        }

    if autonomy.get("observer"):
        jobs["observer"] = {
            "type": "interval",
            "interval_seconds": 900,
            "script": f"scripts/agents/{name}/observer.py",
            "description": "Periodic fact extraction from recent conversation",
        }

    if autonomy.get("reminders"):
        jobs["check_reminders"] = {
            "type": "interval",
            "interval_seconds": 60,
            "script": f"scripts/agents/{name}/check_reminders.py",
            "description": "Check and fire due reminders — runs every minute",
        }

    # Inter-agent conversations — only if there could be other agents
    if autonomy.get("inter_agent_conversations", True):
        hour = random.randint(1, 5)
        minute = random.randint(0, 59)
        target = datetime.now() + timedelta(days=random.randint(14, 21))
        jobs["converse"] = {
            "cron": f"{minute} {hour} {target.day} {target.month} *",
            "script": f"scripts/agents/{name}/converse.py",
            "description": "Inter-agent conversation — private exchange with another agent, max twice a month",
        }

    return jobs


def copy_agent_scripts(
    name: str, display_name: str, user_name: str,
    autonomy: dict, location: str = "",
):
    """Copy scripts from companion, parameterising agent-specific strings."""
    template_dir = PROJECT_ROOT / "scripts" / "agents" / "companion"
    target_dir = PROJECT_ROOT / "scripts" / "agents" / name

    if not template_dir.exists():
        print(f"  Warning: Template scripts not found at {template_dir}")
        print(f"  Scripts will need to be created manually.")
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    user_lower = user_name.lower()

    # Map enabled features to scripts
    script_map = {
        "heartbeat.py": True,
        "introspect.py": autonomy.get("introspection", False),
        "gift.py": autonomy.get("gifts", False),
        "morning_brief.py": autonomy.get("morning_brief", False),
        "evolve.py": autonomy.get("evolution", False),
        "sleep_cycle.py": autonomy.get("sleep_cycle", False),
        "observer.py": autonomy.get("observer", False),
        "check_reminders.py": autonomy.get("reminders", False),
        "run_task.py": autonomy.get("reminders", False),
        "converse.py": autonomy.get("inter_agent_conversations", True),
    }

    copied = 0
    for script_name, enabled in script_map.items():
        if not enabled:
            continue
        src = template_dir / script_name
        if not src.exists():
            continue

        content = src.read_text()

        # ── Parameterise ──

        # Frontmatter and tags
        content = content.replace("agent: companion", f"agent: {name}")
        content = content.replace("tags: [companion", f"tags: [{name}")

        # Role labels — these now use AGENT_DISPLAY_NAME from config, no replacement needed
        # SQL role strings — now use generic 'agent' role, no replacement needed

        # Hardcoded system prompts
        content = content.replace("You are the companion", f"You are {display_name}")
        content = content.replace("the companion's", f"{display_name}'s")
        content = content.replace("the companion,", f"{display_name},")
        content = content.replace("the companion.", f"{display_name}.")

        # User name in display strings (targeted patterns)
        content = content.replace(
            "A direct statement from Will", f"A direct statement from {user_name}"
        )
        content = content.replace(
            "reach out to Will unprompted", f"reach out to {user_name} unprompted"
        )
        content = content.replace(
            "Will's significant turns", f"{user_name}'s significant turns"
        )
        content = content.replace(
            "Will's biographical", f"{user_name}'s biographical"
        )
        content = content.replace("significant_will", f"significant_{user_lower}")
        content = content.replace(
            "Recent things Will said", f"Recent things {user_name} said"
        )
        content = content.replace("about Will.", f"about {user_name}.")
        content = content.replace("about Will —", f"about {user_name} —")
        content = content.replace("about *Will*", f"about *{user_name}*")
        content = content.replace("about Will\n", f"about {user_name}\n")
        content = content.replace("for Will\n", f"for {user_name}\n")
        content = content.replace("for Will.", f"for {user_name}.")

        # Fallback prompt strings
        content = content.replace(
            "specific note for Will.", f"specific note for {user_name}."
        )
        content = content.replace(
            "morning message for Will.", f"morning message for {user_name}."
        )

        # Location (morning brief)
        if location and script_name == "morning_brief.py":
            content = content.replace("Leeds", location)

        (target_dir / script_name).write_text(content)
        copied += 1

    if copied:
        print(f"  Copied and parameterised {copied} script(s) to scripts/agents/{name}/")


# ── Scaffold ──


def scaffold_agent(
    identity: dict, boundaries: dict, voice: dict,
    appearance: dict, channels: dict, heartbeat: dict,
    autonomy: dict, tools: dict | None = None,
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
    tools = tools or {}
    manifest = generate_agent_json(identity, voice, channels, heartbeat, appearance, tools)
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
        # Note: heartbeat.md is NOT placed here — it would get injected into
        # every conversation via context.py's glob of skills/*.md. It stays
        # only in agents/<name>/prompts/ where the heartbeat script loads it.
        (agent_obsidian / "skills" / "system.md").write_text(prompt)
        (agent_obsidian / "skills" / "soul.md").write_text(soul)
        (agent_obsidian / "skills" / "tools.md").write_text(generate_tools_md())

        # Autonomy skills
        if autonomy.get("introspection"):
            (agent_obsidian / "skills" / "introspection.md").write_text(
                generate_introspection_md(identity, autonomy)
            )
        if autonomy.get("gifts"):
            (agent_obsidian / "skills" / "gift.md").write_text(
                generate_gift_md(identity)
            )
        if autonomy.get("morning_brief"):
            (agent_obsidian / "skills" / "morning-brief.md").write_text(
                generate_morning_brief_md(identity)
            )

        # Custom skills from tools phase
        for skill in tools.get("custom_skills", []):
            skill_name = skill["name"].lower().replace(" ", "-")
            skill_content = f"# {skill['name']}\n\n{skill['description']}\n"
            (agent_obsidian / "skills" / f"{skill_name}.md").write_text(skill_content)
            print(f"  Created: Obsidian skills/{skill_name}.md")

        # Dashboard
        (agent_obsidian / "Dashboard.md").write_text(
            generate_dashboard_md(identity)
        )

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

    # State directory (for observer etc.)
    (agent_dir / "state").mkdir(exist_ok=True)

    # Copy and parameterise scripts from companion
    copy_agent_scripts(
        name=name,
        display_name=identity["display_name"],
        user_name=identity["user_name"],
        autonomy=autonomy,
        location=autonomy.get("location", ""),
    )

    # Full jobs.json
    scripts_dir = PROJECT_ROOT / "scripts" / "agents" / name
    scripts_dir.mkdir(parents=True, exist_ok=True)
    jobs = generate_full_jobs(name, heartbeat, autonomy)
    (scripts_dir / "jobs.json").write_text(json.dumps(jobs, indent=2) + "\n")
    print(f"  Created: scripts/agents/{name}/jobs.json ({len(jobs)} job(s))")

    # Summary
    enabled_features = []
    if autonomy.get("introspection"):
        enabled_features.append("journal")
    if autonomy.get("gifts"):
        enabled_features.append("gifts")
    if autonomy.get("morning_brief"):
        enabled_features.append("morning brief")
    if autonomy.get("evolution"):
        enabled_features.append("self-evolution")
    if autonomy.get("sleep_cycle"):
        enabled_features.append("sleep cycle")
    if autonomy.get("observer"):
        enabled_features.append("observer")
    if autonomy.get("reminders"):
        enabled_features.append("reminders")

    skills_list = ["system", "soul", "heartbeat", "tools"]
    if autonomy.get("introspection"):
        skills_list.append("introspection")
    if autonomy.get("gifts"):
        skills_list.append("gift")
    if autonomy.get("morning_brief"):
        skills_list.append("morning-brief")

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
    print(f"    scripts/agents/{name}/                 — {len(jobs)} job script(s) + jobs.json")
    print(f"\n  Obsidian (canonical):")
    print(f"    Agent Workspace/{name}/skills/    — {', '.join(skills_list)}")
    print(f"    Agent Workspace/{name}/notes/     — reflections, threads, journal")
    print(f"    Agent Workspace/{name}/Dashboard.md")

    if enabled_features:
        print(f"\n  Inner life: {', '.join(enabled_features)}")

    if appearance.get("has_avatar") and appearance.get("appearance_description"):
        print(f"\n  Avatar prompt saved. Generate with:")
        print(f"    python scripts/generate_face.py --agent {name}")

    print(f"\n  Next steps:")
    print(f"    1. Edit soul and system prompt in Obsidian — those are the canonical versions")
    print(f"    2. Install cron jobs: AGENT={name} python scripts/cron.py install")
    print(f"    3. Run: AGENT={name} python main.py --app")


def scaffold_from_config(config: dict) -> str:
    """Create an agent from a config dict. Non-interactive mode.

    Expected config structure:
    {
        "identity": {
            "display_name": "Oracle",
            "user_name": "Will",
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
            "telegram_emoji": "",
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
        "source_image_url": "",
        "video_clip_urls": []
    }

    Returns a summary string.
    """
    identity = config.get("identity", {})
    if not isinstance(identity, dict):
        raise ValueError("identity must be a dict")

    display_name = identity.get("display_name", "")
    user_name = identity.get("user_name", "")
    if not display_name or not isinstance(display_name, str):
        raise ValueError("identity.display_name is required and must be a string")
    if not user_name or not isinstance(user_name, str):
        raise ValueError("identity.user_name is required and must be a string")

    boundaries = config.get("boundaries", {})
    voice_cfg = config.get("voice", {})
    appearance = config.get("appearance", {})
    channels = config.get("channels", {})
    heartbeat = config.get("heartbeat", {})
    autonomy = config.get("autonomy", {})
    tools = config.get("tools", {})

    # Auto-generate slug if not provided
    if "name" not in identity:
        identity["name"] = _slugify(identity.get("display_name", "agent"))

    # Validate slug is filesystem-safe
    slug = identity["name"]
    if not slug or not slug.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Generated slug '{slug}' is not a valid directory name")

    # Defaults
    boundaries.setdefault("session_limit_behaviour", "Check in — are you grounded?")
    boundaries.setdefault("soft_limit_mins", 60)
    heartbeat.setdefault("active_start", 9)
    heartbeat.setdefault("active_end", 22)
    heartbeat.setdefault("interval_mins", 30)

    # Scaffold everything
    scaffold_agent(identity, boundaries, voice_cfg, appearance, channels, heartbeat, autonomy, tools)

    name = identity["name"]
    agent_dir = AGENTS_DIR / name

    # Download source image if provided
    source_url = config.get("source_image_url", "")
    if source_url:
        _download_media(source_url, agent_dir / "avatar" / "source" / "face.png")
        print(f"  Downloaded source image to agents/{name}/avatar/source/face.png")

    # Download and stitch video clips if provided
    video_urls = config.get("video_clip_urls", [])
    if video_urls:
        _stitch_video_loop(name, video_urls)

    return f"Agent '{identity.get('display_name', name)}' created successfully."


def _download_media(url: str, dest: Path):
    """Download a file from URL to a local path."""
    import urllib.request
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(dest))


def _stitch_video_loop(name: str, urls: list[str]):
    """Download video clips and stitch into an ambient loop with crossfade."""
    import subprocess
    import urllib.request

    avatar_dir = AGENTS_DIR / name / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)

    # Download clips
    clips = []
    for i, url in enumerate(urls):
        clip_path = avatar_dir / f"clip{i + 1}.mp4"
        urllib.request.urlretrieve(url, str(clip_path))
        clips.append(str(clip_path))
        print(f"  Downloaded clip {i + 1} to {clip_path}")

    output = avatar_dir / "ambient_loop.mp4"

    if len(clips) == 1:
        # Single clip — just copy
        import shutil
        shutil.copy2(clips[0], str(output))
    elif len(clips) == 2:
        # Two clips — crossfade stitch
        # Clip 1 (5s) crossfades into clip 2 (5s) with 0.15s fade
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", clips[0], "-i", clips[1],
                    "-filter_complex",
                    "[0:v][1:v]xfade=transition=fade:duration=0.15:offset=4.85,format=yuv420p",
                    "-c:v", "libx264", "-crf", "18",
                    "-an", str(output),
                ],
                check=True, capture_output=True, timeout=120,
            )
            print(f"  Stitched 2 clips into {output}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"  Warning: ffmpeg stitch failed ({e}). Clips saved separately.")
    else:
        # Multiple clips — concat with crossfades
        filter_parts = []
        for i in range(len(clips) - 1):
            if i == 0:
                filter_parts.append(
                    f"[0:v][1:v]xfade=transition=fade:duration=0.15:offset=4.85[v01]"
                )
            else:
                prev = f"v{str(i-1).zfill(2)}{str(i).zfill(2)}" if i > 1 else "v01"
                curr = f"v{str(i).zfill(2)}{str(i+1).zfill(2)}"
                offset = 4.85 + (i * 4.85)
                filter_parts.append(
                    f"[{prev}][{i+1}:v]xfade=transition=fade:duration=0.15:offset={offset:.2f}[{curr}]"
                )

        inputs = []
        for c in clips:
            inputs.extend(["-i", c])

        try:
            subprocess.run(
                ["ffmpeg", "-y"] + inputs + [
                    "-filter_complex", ";".join(filter_parts),
                    "-c:v", "libx264", "-crf", "18",
                    "-an", str(output),
                ],
                check=True, capture_output=True, timeout=300,
            )
            print(f"  Stitched {len(clips)} clips into {output}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"  Warning: ffmpeg stitch failed ({e}). Clips saved separately.")


# ── Main ──


def main():
    parser = argparse.ArgumentParser(description="Create a new agent")
    parser.add_argument("--name", help="Agent name (skip first question)")
    parser.add_argument("--config", help="JSON config file for non-interactive mode")
    args = parser.parse_args()

    if args.config:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        config = json.loads(Path(args.config).read_text())
        result = scaffold_from_config(config)
        print(f"\n  {result}")
        return

    print()
    print("  +--------------------------------------+")
    print("  |   THE ATROPHIED MIND                 |")
    print("  |   Agent Creation                     |")
    print("  +--------------------------------------+")

    # Services & API keys — first step
    ask_services()

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
    autonomy = ask_autonomy(identity)
    tools_data = ask_tools()

    # Review
    print("\n" + "=" * 50)
    print("  REVIEW")
    print("=" * 50)
    wake = channels_data.get("wake_words", "") or f"hey {identity['name']}, {identity['name']}"

    # Autonomy features
    features = []
    if autonomy.get("introspection"):
        features.append("journal")
    if autonomy.get("gifts"):
        features.append("gifts")
    if autonomy.get("morning_brief"):
        features.append("morning brief")
    if autonomy.get("evolution"):
        features.append("self-evolution")
    if autonomy.get("sleep_cycle"):
        features.append("sleep cycle")
    if autonomy.get("observer"):
        features.append("observer")
    if autonomy.get("reminders"):
        features.append("reminders")

    disabled = tools_data.get("disabled_tools", [])
    custom = tools_data.get("custom_skills", [])

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
    print(f"  Location:     {autonomy.get('location') or '(not set)'}")
    print(f"  Inner life:   {', '.join(features) if features else '(none)'}")
    print(f"  Disabled:     {', '.join(disabled) if disabled else '(none)'}")
    print(f"  Custom skills: {len(custom)}")

    if not _ask_yn("\n  Create this agent?", True):
        print("  Aborted.")
        return

    scaffold_agent(identity, boundaries, voice, appearance, channels_data, heartbeat, autonomy, tools_data)


if __name__ == "__main__":
    main()

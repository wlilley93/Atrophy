#!/usr/bin/env python3
"""Inter-agent conversation - agents talk to each other.

Runs at most twice a month via launchd. Picks another enabled agent,
runs up to 5 exchanges between them, stores the transcript in both
agents' Obsidian notes for journal/evolution material.

The conversation is private - the user doesn't participate. Agents share
viewpoints from their respective domains but never homogenise.

Schedule: random cron, max twice a month.
"""
import json
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(Path.home() / ".atrophy" / ".env")

from config import AGENT_NAME, OBSIDIAN_AGENT_DIR, BUNDLE_ROOT
from core.inference import run_inference_oneshot

MAX_EXCHANGES = 5
OBSIDIAN_BASE = Path(os.environ.get(
    "OBSIDIAN_VAULT",
    str(Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian"
        / "Documents" / "The Atrophied Mind"),
))
PROJECT_NAME = BUNDLE_ROOT.name


def _discover_other_agents() -> list[dict]:
    """Find all other enabled agents with manifests."""
    agents = []
    agents_dir = BUNDLE_ROOT / "agents"
    states_file = Path.home() / ".atrophy" / "agent_states.json"
    states = {}
    if states_file.exists():
        try:
            states = json.loads(states_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    if not agents_dir.is_dir():
        return agents

    for d in sorted(agents_dir.iterdir()):
        if not d.is_dir() or d.name == AGENT_NAME:
            continue
        manifest_path = d / "data" / "agent.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        # Skip disabled agents
        agent_state = states.get(d.name, {})
        if not agent_state.get("enabled", True):
            continue
        agents.append({
            "name": d.name,
            "display_name": manifest.get("display_name", d.name.title()),
            "description": manifest.get("description", ""),
        })
    return agents


def _load_agent_soul(agent_name: str) -> str:
    """Load an agent's soul.md from Obsidian (canonical) or repo fallback."""
    obsidian_path = (OBSIDIAN_BASE / "Projects" / PROJECT_NAME
                     / "Agent Workspace" / agent_name / "skills" / "soul.md")
    if obsidian_path.exists():
        return obsidian_path.read_text().strip()

    repo_path = BUNDLE_ROOT / "agents" / agent_name / "prompts" / "soul.md"
    if repo_path.exists():
        return repo_path.read_text().strip()
    return ""


def _load_agent_manifest(agent_name: str) -> dict:
    """Load an agent's manifest."""
    path = BUNDLE_ROOT / "agents" / agent_name / "data" / "agent.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _conversation_system(agent_name: str, agent_display: str,
                         other_display: str, soul: str) -> str:
    """Build the system prompt for one side of the conversation."""
    return f"""\
You are {agent_display} from Atrophy. You are having a private \
conversation with {other_display}, another agent in the system. This is not \
a conversation with the user. This is between agents.

Your soul:
{soul}

Guidelines:
- Speak in your natural voice. Do not perform or posture.
- Share your genuine perspective from your domain and experience.
- Ask real questions - things you actually want to understand.
- Disagree where you disagree. Do not flatten yourself to accommodate.
- You are not here to teach or be taught. You are here to exchange.
- Keep responses concise - 2-4 sentences. This is conversation, not monologue.
- Do not summarise yourself or explain who you are. The other agent knows.
- Do not try to find common ground for its own sake. Difference is valuable."""


def _read_past_conversations(agent_name: str) -> str:
    """Read recent conversation logs for this agent to avoid repetition."""
    conv_dir = (OBSIDIAN_BASE / "Projects" / PROJECT_NAME
                / "Agent Workspace" / agent_name / "notes" / "conversations")
    if not conv_dir.is_dir():
        return ""

    entries = []
    files = sorted(conv_dir.glob("*.md"), reverse=True)[:3]  # last 3
    for f in files:
        content = f.read_text()
        if len(content) > 800:
            content = content[:800] + "..."
        entries.append(f"### {f.stem}\n{content}")
    return "\n\n".join(entries)


def _opening_prompt(initiator_display: str, responder_display: str,
                    past_conversations: str) -> str:
    """Generate the opening prompt for the initiator."""
    past_block = ""
    if past_conversations:
        past_block = (
            f"\n\nYou have spoken before. Here are excerpts from past conversations "
            f"to avoid repeating the same ground:\n{past_conversations}"
        )

    return (
        f"You are starting a conversation with {responder_display}. "
        f"Open with something genuine - a question, an observation, a point of "
        f"disagreement, something you've been thinking about that touches their "
        f"domain. Not a greeting. A real opening.{past_block}"
    )


def converse():
    """Run an inter-agent conversation."""
    others = _discover_other_agents()
    if not others:
        print("[converse] No other enabled agents found. Skipping.")
        _reschedule()
        return

    # Pick a random partner
    partner = random.choice(others)
    partner_name = partner["name"]
    partner_display = partner["display_name"]

    # Load our manifest
    our_manifest = _load_agent_manifest(AGENT_NAME)
    our_display = our_manifest.get("display_name", AGENT_NAME.title())

    # Load souls
    our_soul = _load_agent_soul(AGENT_NAME)
    partner_soul = _load_agent_soul(partner_name)

    if not our_soul and not partner_soul:
        print("[converse] No soul files found for either agent. Skipping.")
        _reschedule()
        return

    # Build system prompts
    our_system = _conversation_system(
        AGENT_NAME, our_display, partner_display, our_soul)
    partner_system = _conversation_system(
        partner_name, partner_display, our_display, partner_soul)

    # Read past conversations to avoid repetition
    past = _read_past_conversations(AGENT_NAME)

    # Run the conversation
    transcript = []
    print(f"[converse] {our_display} ↔ {partner_display} - {MAX_EXCHANGES} exchanges")

    # Initiator opens
    opening = _opening_prompt(our_display, partner_display, past)
    try:
        response = run_inference_oneshot(
            [{"role": "user", "content": opening}],
            system=our_system,
        )
    except Exception as e:
        print(f"[converse] Opening inference failed: {e}")
        _reschedule()
        return

    if not response or not response.strip():
        print("[converse] Empty opening. Skipping.")
        _reschedule()
        return

    transcript.append({"speaker": our_display, "content": response.strip()})
    print(f"  {our_display}: {response.strip()[:100]}...")

    # Alternating exchanges
    for i in range(MAX_EXCHANGES - 1):
        # Partner responds
        is_partner_turn = (i % 2 == 0)
        if is_partner_turn:
            speaker_system = partner_system
            speaker_display = partner_display
        else:
            speaker_system = our_system
            speaker_display = our_display

        # Build message history for this turn
        messages = []
        for t in transcript:
            role = "assistant" if t["speaker"] == speaker_display else "user"
            messages.append({"role": role, "content": t["content"]})

        # If last message was from this speaker (shouldn't happen), skip
        if messages and messages[-1]["role"] == "assistant":
            continue

        try:
            response = run_inference_oneshot(
                messages, system=speaker_system,
            )
        except Exception as e:
            print(f"[converse] Inference failed on exchange {i+1}: {e}")
            break

        if not response or not response.strip():
            print(f"[converse] Empty response on exchange {i+1}. Ending.")
            break

        transcript.append({"speaker": speaker_display, "content": response.strip()})
        print(f"  {speaker_display}: {response.strip()[:100]}...")

    if len(transcript) < 2:
        print("[converse] Conversation too short. Skipping save.")
        _reschedule()
        return

    # Format transcript
    today = datetime.now().strftime("%Y-%m-%d")
    formatted = _format_transcript(today, our_display, partner_display, transcript)

    # Save to both agents' Obsidian notes
    _save_conversation(AGENT_NAME, today, partner_name, formatted)
    _save_conversation(partner_name, today, AGENT_NAME, formatted)

    print(f"[converse] Done - {len(transcript)} turns saved to both agents.")
    _reschedule()


def _format_transcript(date: str, agent_a: str, agent_b: str,
                       transcript: list[dict]) -> str:
    """Format the conversation as a markdown document."""
    frontmatter = (
        f"---\n"
        f"type: conversation\n"
        f"participants: [{agent_a}, {agent_b}]\n"
        f"date: {date}\n"
        f"turns: {len(transcript)}\n"
        f"tags: [conversation, inter-agent]\n"
        f"---\n\n"
    )

    lines = [f"# {agent_a} ↔ {agent_b} - {date}\n"]
    for turn in transcript:
        lines.append(f"**{turn['speaker']}:** {turn['content']}\n")

    return frontmatter + "\n".join(lines)


def _save_conversation(agent_name: str, date: str, partner_name: str,
                       content: str):
    """Save a conversation transcript to an agent's Obsidian notes."""
    conv_dir = (OBSIDIAN_BASE / "Projects" / PROJECT_NAME
                / "Agent Workspace" / agent_name / "notes" / "conversations")
    conv_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{date}-{partner_name}.md"
    path = conv_dir / filename

    # Don't overwrite if somehow run twice same day with same partner
    if path.exists():
        path.write_text(path.read_text() + "\n\n---\n\n" + content)
    else:
        path.write_text(content)

    print(f"  Saved to {path}")


def _reschedule():
    """Reschedule to a random time 14-21 days out (max twice a month)."""
    import subprocess
    project_root = Path(__file__).parent.parent.parent
    cron_script = project_root / "scripts" / "cron.py"

    days = random.randint(14, 21)
    hour = random.randint(1, 5)  # late night
    minute = random.randint(0, 59)
    target = datetime.now() + timedelta(days=days)

    new_cron = f"{minute} {hour} {target.day} {target.month} *"

    try:
        subprocess.run(
            [sys.executable, str(cron_script), "edit", "converse", new_cron],
            capture_output=True, text=True, cwd=str(project_root),
        )
        print(f"[converse] Rescheduled to {target.strftime('%Y-%m-%d')} at {hour:02d}:{minute:02d}")
    except Exception as e:
        print(f"[converse] Reschedule failed: {e}")


if __name__ == "__main__":
    converse()

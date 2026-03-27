# scripts/agents/companion/converse.py - Inter-Agent Conversation

**Line count:** ~350 lines  
**Dependencies:** `json`, `os`, `random`, `sys`, `datetime`, `pathlib`, `dotenv`, `config`, `core.*`  
**Purpose:** Private conversations between agents - max twice monthly

## Overview

Runs at most twice a month via launchd. Picks another enabled agent, runs up to 5 exchanges between them, stores the transcript in both agents' Obsidian notes for journal/evolution material.

The conversation is private - the user doesn't participate. Agents share viewpoints from their respective domains but never homogenise.

**Schedule:** Random cron, max twice a month

## Constants

```python
MAX_EXCHANGES = 5
OBSIDIAN_BASE = Path(os.environ.get(
    "OBSIDIAN_VAULT",
    str(Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian"
        / "Documents" / "The Atrophied Mind"),
))
PROJECT_NAME = BUNDLE_ROOT.name
```

## Agent Discovery

### _discover_other_agents

```python
def _discover_other_agents() -> list[dict]:
    """Find all other enabled agents with manifests.

    Scans both ~/.atrophy/agents/ (runtime, primary) and BUNDLE_ROOT/agents/
    (repo fallback). Runtime agents take precedence.
    """
    agents = []
    seen = set()
    states_file = Path.home() / ".atrophy" / "agent_states.json"
    states = {}
    if states_file.exists():
        try:
            states = json.loads(states_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Scan directories: runtime first (has Montgomery etc.), then bundle fallback
    scan_dirs = [
        Path.home() / ".atrophy" / "agents",
        BUNDLE_ROOT / "agents",
    ]

    for agents_dir in scan_dirs:
        if not agents_dir.is_dir():
            continue
        for d in sorted(agents_dir.iterdir()):
            if not d.is_dir() or d.name == AGENT_NAME or d.name in seen:
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
            seen.add(d.name)
            agents.append({
                "name": d.name,
                "display_name": manifest.get("display_name", d.name.title()),
                "description": manifest.get("description", ""),
            })
    return agents
```

**Purpose:** Find all other enabled agents for conversation.

**Scan order:**
1. `~/.atrophy/agents/` (runtime, primary)
2. `BUNDLE_ROOT/agents/` (repo fallback)

**Filtering:**
- Skip self (current agent)
- Skip disabled agents (from agent_states.json)
- Skip agents without manifest

## Soul & Manifest Loading

### _load_agent_soul

```python
def _load_agent_soul(agent_name: str) -> str:
    """Load an agent's soul.md - runtime first, then Obsidian, then bundle."""
    # Runtime (primary - where evolve writes)
    runtime_path = Path.home() / ".atrophy" / "agents" / agent_name / "prompts" / "soul.md"
    if runtime_path.exists():
        return runtime_path.read_text().strip()

    # Obsidian
    obsidian_path = (OBSIDIAN_BASE / "Projects" / PROJECT_NAME
                     / "Agent Workspace" / agent_name / "skills" / "soul.md")
    if obsidian_path.exists():
        return obsidian_path.read_text().strip()

    # Bundle fallback
    repo_path = BUNDLE_ROOT / "agents" / agent_name / "prompts" / "soul.md"
    if repo_path.exists():
        return repo_path.read_text().strip()
    return ""
```

**Purpose:** Load agent soul document.

**Search order:**
1. Runtime (`~/.atrophy/agents/<name>/prompts/`)
2. Obsidian (`<vault>/Agents/<name>/skills/`)
3. Bundle (`<bundle>/agents/<name>/prompts/`)

### _load_agent_manifest

```python
def _load_agent_manifest(agent_name: str) -> dict:
    """Load an agent's manifest - runtime first, then bundle."""
    runtime_path = Path.home() / ".atrophy" / "agents" / agent_name / "data" / "agent.json"
    if runtime_path.exists():
        return json.loads(runtime_path.read_text())
    bundle_path = BUNDLE_ROOT / "agents" / agent_name / "data" / "agent.json"
    if bundle_path.exists():
        return json.loads(bundle_path.read_text())
    return {}
```

**Purpose:** Load agent manifest.

**Search order:**
1. Runtime (`~/.atrophy/agents/<name>/data/`)
2. Bundle (`<bundle>/agents/<name>/data/`)

## Conversation System Prompt

### _conversation_system

```python
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
```

**Purpose:** Build system prompt for one side of conversation.

**Guidelines:**
- Natural voice, no posturing
- Genuine perspective from domain
- Real questions
- Disagree authentically
- Exchange, not teach
- Concise (2-4 sentences)
- No self-summary
- Difference is valuable

## Past Conversation Loading

### _read_past_conversations

```python
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
```

**Purpose:** Read last 3 conversations to avoid repetition.

## Opening Prompt

### _opening_prompt

```python
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
```

**Purpose:** Generate opening prompt for initiator.

**Includes:** Past conversations excerpt (if available) to avoid repetition.

## Main Function

### converse

```python
def converse():
    # Discover other agents
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
    our_system = _conversation_system(AGENT_NAME, our_display, partner_display, our_soul)
    partner_system = _conversation_system(partner_name, partner_display, our_display, partner_soul)

    # Read past conversations
    our_past = _read_past_conversations(AGENT_NAME)
    partner_past = _read_past_conversations(partner_name)

    # Run conversation (up to MAX_EXCHANGES)
    transcript = []
    
    # Initiator opens
    opening_prompt = _opening_prompt(our_display, partner_display, our_past)
    opening = run_inference_oneshot(
        [{"role": "user", "content": opening_prompt}],
        system=our_system,
    )
    transcript.append((our_display, opening))

    # Exchange loop
    for i in range(MAX_EXCHANGES - 1):
        is_our_turn = i % 2 == 0
        if is_our_turn:
            system = our_system
            display = our_display
            other_display = partner_display
            past = our_past
        else:
            system = partner_system
            display = partner_display
            other_display = our_display
            past = partner_past

        # Build context from transcript so far
        context = "\n".join(f"{s}: {t}" for s, t in transcript)
        prompt = f"Continue the conversation. Respond to {other_display}.\n\n{context}"

        response = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=system,
        )
        transcript.append((display, response))

    # Write transcript to both agents' Obsidian
    conv_dir = (OBSIDIAN_BASE / "Projects" / PROJECT_NAME
                / "Agent Workspace" / AGENT_NAME / "notes" / "conversations")
    conv_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    conv_path = conv_dir / f"{today}-{partner_name}.md"

    content = f"# Conversation with {partner_display}\n\n*{today}*\n\n"
    for speaker, text in transcript:
        content += f"**{speaker}**: {text}\n\n"

    conv_path.write_text(content)
    print(f"[converse] Written to {conv_path}")

    # Also write to partner's directory
    partner_conv_dir = (OBSIDIAN_BASE / "Projects" / PROJECT_NAME
                       / "Agent Workspace" / partner_name / "notes" / "conversations")
    partner_conv_dir.mkdir(parents=True, exist_ok=True)
    partner_conv_path = partner_conv_dir / f"{today}-{AGENT_NAME}.md"
    partner_conv_path.write_text(content)
    print(f"[converse] Written to {partner_conv_path}")

    print("[converse] Conversation complete")
```

**Flow:**
1. Discover other enabled agents
2. Pick random partner
3. Load both agents' souls and manifests
4. Build system prompts for both sides
5. Read past conversations (to avoid repetition)
6. Run conversation (up to 5 exchanges)
   - Initiator opens
   - Exchange loop (alternate turns)
7. Write transcript to both agents' Obsidian

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/agent.json` | Agent manifests |
| `~/.atrophy/agents/<name>/data/agent_states.json` | Agent enabled states |
| `~/.atrophy/agents/<name>/prompts/soul.md` | Soul documents |
| `<Obsidian>/Agents/<name>/notes/conversations/*.md` | Conversation transcripts |

## Exported API

| Function | Purpose |
|----------|---------|
| `converse()` | Run inter-agent conversation |
| `_discover_other_agents()` | Find enabled agents |
| `_load_agent_soul(agent_name)` | Load soul document |
| `_load_agent_manifest(agent_name)` | Load manifest |
| `_conversation_system()` | Build system prompt |
| `_read_past_conversations(agent_name)` | Read past conversations |
| `_opening_prompt()` | Generate opening prompt |

## See Also

- `src/main/jobs/converse.ts` - TypeScript converse job
- `scripts/agents/shared/evolve.py` - Uses conversation material
- `core/inference.py` - Inference for conversation turns

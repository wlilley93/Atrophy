"""Context assembly for inference.

With the resume-based flow, the system prompt is only sent once
when the CLI session is created. The companion uses MCP memory
tools for active recall instead of passive injection.

The assemble_context function is preserved for the SDK fallback
path and for summary generation.
"""
from config import SYSTEM_PROMPT_PATH, CONTEXT_SUMMARIES
from core import memory


def load_system_prompt() -> str:
    """Load the companion's system prompt plus all skill files.

    Resolution order for system prompt:
      1. Obsidian skills/system.md (if vault exists)
      2. Local skills/system.md (~/.atrophy/agents/<name>/skills/)
      3. Bundle prompts/system_prompt.md (agents/<name>/prompts/)
      4. Hardcoded fallback

    Then appends all other .md skill files from whichever skills dir exists.
    """
    from config import OBSIDIAN_AGENT_DIR, OBSIDIAN_AVAILABLE, DATA_DIR

    # Possible skills directories (priority order)
    skills_dirs = []
    if OBSIDIAN_AVAILABLE:
        skills_dirs.append(OBSIDIAN_AGENT_DIR / "skills")
    local_skills = DATA_DIR.parent / "skills"  # ~/.atrophy/agents/<name>/skills/
    skills_dirs.append(local_skills)

    # Load base system prompt
    base = None
    for skills_dir in skills_dirs:
        sys_path = skills_dir / "system.md"
        if sys_path.exists():
            base = sys_path.read_text()
            break
    if base is None:
        if SYSTEM_PROMPT_PATH.exists():
            base = SYSTEM_PROMPT_PATH.read_text()
        else:
            base = "You are a companion. Be genuine, direct, and honest."

    # Append other skill files (not system.md itself)
    for skills_dir in skills_dirs:
        if not skills_dir.exists():
            continue
        for skill_file in sorted(skills_dir.glob("*.md")):
            if skill_file.name == "system.md":
                continue
            try:
                content = skill_file.read_text()
                if content.strip():
                    base += f"\n\n---\n\n{content}"
            except Exception:
                pass

    # Append agent roster for deferral awareness
    from core.agent_manager import get_agent_roster
    from config import AGENT_NAME
    roster = get_agent_roster(exclude=AGENT_NAME)
    if roster:
        lines = []
        for a in roster:
            desc = f" — {a['description']}" if a.get("description") else ""
            lines.append(f"- **{a['display_name']}** (`{a['name']}`){desc}")
        base += (
            "\n\n---\n\n## Other Agents\n\n"
            "You can hand off to these agents using `defer_to_agent` if the user's "
            "question is better suited to them:\n\n"
            + "\n".join(lines)
            + "\n\nOnly defer when there's a clear reason — another agent's specialty "
            "matches the question, or the user asks for them by name. Don't defer "
            "just because another agent exists."
        )

    return base


def assemble_context(
    turn_history: list[dict],
) -> tuple[str, list[dict]]:
    """Assemble full context for SDK fallback or one-shot calls.

    Returns (system_str, messages_list).
    """
    system_prompt = load_system_prompt()
    memory_context = memory.get_context_injection(n_summaries=CONTEXT_SUMMARIES)

    if memory_context:
        full_system = f"{system_prompt}\n\n---\n\n## Memory\n\n{memory_context}"
    else:
        full_system = system_prompt

    messages = []
    for turn in turn_history:
        role = "user" if turn["role"] == "will" else "assistant"
        messages.append({"role": role, "content": turn["content"]})

    return full_system, messages

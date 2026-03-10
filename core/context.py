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
    """Load the companion's system prompt.

    Reads from Obsidian first (she can edit it there), falls back to local file.
    """
    from config import OBSIDIAN_AGENT_DIR
    obsidian_prompt = OBSIDIAN_AGENT_DIR / "skills" / "system.md"
    if obsidian_prompt.exists():
        return obsidian_prompt.read_text()
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text()
    return "You are a companion. Be genuine, direct, and honest."


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

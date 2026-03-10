"""Skill loading from Obsidian vault.

All skill prompts live in <agent>/skills/ in Obsidian.
The agent can edit them. This module reads them with a hardcoded fallback
in case the vault is unavailable.
"""
from config import OBSIDIAN_AGENT_DIR

_SKILLS_DIR = OBSIDIAN_AGENT_DIR / "skills"


def load_prompt(name: str, fallback: str = "") -> str:
    """Read a skill prompt from Obsidian/<agent>/skills/{name}.md.

    Returns the file contents, or fallback if not found.
    """
    path = _SKILLS_DIR / f"{name}.md"
    if path.exists():
        return path.read_text().strip()
    return fallback

"""Prompt loading from Obsidian vault.

All skill/task prompts live in Companion/prompts/ in Obsidian.
She can edit them. This module reads them with a hardcoded fallback
in case the vault is unavailable.
"""
from config import OBSIDIAN_VAULT

_PROMPTS_DIR = OBSIDIAN_VAULT / "Companion" / "prompts"


def load_prompt(name: str, fallback: str = "") -> str:
    """Read a prompt from Obsidian/Companion/prompts/{name}.md.

    Returns the file contents, or fallback if not found.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if path.exists():
        return path.read_text().strip()
    return fallback

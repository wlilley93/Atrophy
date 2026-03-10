"""Skill loading with three-tier resolution.

Resolution order:
  1. Obsidian vault  — Agent Workspace/<agent>/skills/{name}.md  (canonical, editable by agent)
  2. User data       — ~/.atrophy/agents/<agent>/prompts/{name}.md  (per-installation overrides)
  3. Bundle          — agents/<agent>/prompts/{name}.md  (repo defaults)

The agent reads and writes tier 1 (Obsidian). Tier 2 lets users customise
prompts without touching the repo or needing Obsidian. Tier 3 is the
shipped default.
"""
from config import OBSIDIAN_AGENT_DIR, DATA_DIR, PROMPTS_DIR

_OBSIDIAN_SKILLS = OBSIDIAN_AGENT_DIR / "skills"
_USER_PROMPTS = DATA_DIR.parent / "prompts"        # ~/.atrophy/agents/<name>/prompts/
_BUNDLE_PROMPTS = PROMPTS_DIR                       # agents/<name>/prompts/


def load_prompt(name: str, fallback: str = "") -> str:
    """Load a prompt by name, checking Obsidian → user data → bundle → fallback."""
    for directory in (_OBSIDIAN_SKILLS, _USER_PROMPTS, _BUNDLE_PROMPTS):
        path = directory / f"{name}.md"
        if path.exists():
            text = path.read_text().strip()
            if text:
                return text
    return fallback

"""Skill loading with four-tier resolution.

Resolution order:
  1. Obsidian vault  - Agent Workspace/<agent>/skills/{name}.md  (if vault exists)
  2. Local skills    - ~/.atrophy/agents/<agent>/skills/{name}.md  (canonical for non-Obsidian users)
  3. User prompts    - ~/.atrophy/agents/<agent>/prompts/{name}.md  (legacy overrides)
  4. Bundle          - agents/<agent>/prompts/{name}.md  (repo defaults)

Without Obsidian, tier 2 (local skills) is the canonical location.
The agent reads and writes there via MCP note tools.
"""
from config import OBSIDIAN_AGENT_DIR, OBSIDIAN_AVAILABLE, DATA_DIR, PROMPTS_DIR

_OBSIDIAN_SKILLS = OBSIDIAN_AGENT_DIR / "skills" if OBSIDIAN_AVAILABLE else None
_LOCAL_SKILLS = DATA_DIR.parent / "skills"         # ~/.atrophy/agents/<name>/skills/
_USER_PROMPTS = DATA_DIR.parent / "prompts"        # ~/.atrophy/agents/<name>/prompts/
_BUNDLE_PROMPTS = PROMPTS_DIR                      # agents/<name>/prompts/

_SEARCH_DIRS = [d for d in (_OBSIDIAN_SKILLS, _LOCAL_SKILLS, _USER_PROMPTS, _BUNDLE_PROMPTS) if d]


def load_prompt(name: str, fallback: str = "") -> str:
    """Load a prompt by name, checking Obsidian → local skills → user prompts → bundle → fallback."""
    for directory in _SEARCH_DIRS:
        path = directory / f"{name}.md"
        if path.exists():
            text = path.read_text().strip()
            if text:
                return text
    return fallback

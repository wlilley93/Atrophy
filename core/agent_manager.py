"""core/agent_manager.py - Multi-agent discovery, switching, and state management."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

from config import BUNDLE_ROOT, USER_DATA

CRON_SCRIPT = BUNDLE_ROOT / "scripts" / "cron.py"
AGENT_STATES_FILE = USER_DATA / "agent_states.json"


def _agent_search_dirs() -> list[Path]:
    """Agent dirs to scan - user-installed first, then bundled."""
    dirs = []
    user_agents = USER_DATA / "agents"
    bundle_agents = BUNDLE_ROOT / "agents"
    if user_agents.is_dir():
        dirs.append(user_agents)
    if bundle_agents.is_dir() and bundle_agents != user_agents:
        dirs.append(bundle_agents)
    return dirs


def _find_manifest(name: str) -> dict | None:
    """Find agent.json for an agent, checking all search dirs."""
    for agents_dir in _agent_search_dirs():
        manifest = agents_dir / name / "data" / "agent.json"
        if manifest.exists():
            try:
                return json.loads(manifest.read_text())
            except (json.JSONDecodeError, OSError):
                pass
    return None


def discover_agents() -> list[dict]:
    """Scan all agent directories. User agents override bundled ones by name.

    System-role agents sort first, then alphabetical within each group.
    """
    seen = set()
    agents = []
    for agents_dir in _agent_search_dirs():
        for d in sorted(agents_dir.iterdir()):
            if d.name in seen or not d.is_dir():
                continue
            if not (d / "data").is_dir():
                continue
            seen.add(d.name)
            data = _find_manifest(d.name) or {}
            agents.append({
                "name": d.name,
                "display_name": data.get("display_name", d.name.title()),
                "_role": data.get("role", ""),
            })
    # System-role agents first, then alphabetical within each group
    agents.sort(key=lambda a: (0 if a.get("_role") == "system" else 1, a["name"]))
    return agents


def _load_states() -> dict:
    if AGENT_STATES_FILE.exists():
        try:
            return json.loads(AGENT_STATES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_states(states: dict):
    AGENT_STATES_FILE.write_text(json.dumps(states, indent=2) + "\n")


def get_agent_state(agent_name: str) -> dict:
    """Return {"muted": bool, "enabled": bool} for an agent."""
    states = _load_states()
    default = {"muted": False, "enabled": True}
    return states.get(agent_name, default)


def set_agent_state(agent_name: str, muted: bool | None = None, enabled: bool | None = None):
    """Update per-agent state. Toggles cron jobs if enabled changes."""
    states = _load_states()
    current = states.get(agent_name, {"muted": False, "enabled": True})

    if muted is not None:
        current["muted"] = muted
    if enabled is not None and enabled != current.get("enabled", True):
        current["enabled"] = enabled
        toggle_agent_cron(agent_name, enabled)

    states[agent_name] = current
    _save_states(states)


def set_last_active_agent(agent_name: str):
    """Save which agent was last active (for resuming on next launch)."""
    states = _load_states()
    states["_last_active"] = agent_name
    _save_states(states)


def get_last_active_agent() -> str | None:
    """Return the last active agent name, or None."""
    states = _load_states()
    return states.get("_last_active")


def toggle_agent_cron(agent_name: str, enable: bool):
    """Install or uninstall an agent's cron jobs via scripts/cron.py."""
    jobs_file = BUNDLE_ROOT / "scripts" / "agents" / agent_name / "jobs.json"
    if not jobs_file.exists():
        print(f"  [No jobs.json for {agent_name} - skipping cron toggle]")
        return

    cmd = "install" if enable else "uninstall"
    try:
        subprocess.run(
            [sys.executable, str(CRON_SCRIPT), "--agent", agent_name, cmd],
            cwd=str(BUNDLE_ROOT),
            capture_output=True, timeout=10,
        )
        print(f"  [Cron {cmd}: {agent_name}]")
    except Exception as e:
        print(f"  [Cron {cmd} failed for {agent_name}: {e}]")


def reload_agent_config(agent_name: str):
    """Switch the active agent by reloading the config module."""
    os.environ["AGENT"] = agent_name
    import config as cfg
    importlib.reload(cfg)


# ── Session suspension for deferral ──

_suspended_sessions: dict[str, dict] = {}  # agent_name -> {cli_session_id, session}


def suspend_agent_session(agent_name: str, cli_session_id: str, session: object):
    """Preserve an agent's session state for later resumption (deferral)."""
    _suspended_sessions[agent_name] = {
        "cli_session_id": cli_session_id,
        "session": session,
    }


def resume_agent_session(agent_name: str) -> dict | None:
    """Pop a suspended session. Returns None if no suspended session exists."""
    return _suspended_sessions.pop(agent_name, None)


def get_agent_roster(exclude: str | None = None) -> list[dict]:
    """Return enabled agents with display names and descriptions for roster injection."""
    seen = set()
    agents = []
    for agent_dir in _agent_search_dirs():
        for d in sorted(agent_dir.iterdir()):
            if not d.is_dir() or d.name in seen:
                continue
            if not (d / "data").is_dir():
                continue
            seen.add(d.name)
            data = _find_manifest(d.name) or {}
            if not data:
                continue
            name = d.name
            if name == exclude:
                continue
            state = get_agent_state(name)
            if not state.get("enabled", True):
                continue
            agents.append({
                "name": name,
                "display_name": data.get("display_name", name.title()),
                "description": data.get("description", ""),
                "_role": data.get("role", ""),
            })
    # System-role agents first, then alphabetical within each group
    agents.sort(key=lambda a: (0 if a.get("_role") == "system" else 1, a["name"]))
    return agents


def cycle_agent(direction: int, current: str) -> str | None:
    """Return next/prev agent name, skipping disabled. direction: +1 or -1."""
    agents = discover_agents()
    if len(agents) <= 1:
        return None

    names = [a["name"] for a in agents]
    try:
        idx = names.index(current)
    except ValueError:
        return names[0] if names else None

    # Walk in direction, skipping disabled agents
    for i in range(1, len(names)):
        candidate = names[(idx + direction * i) % len(names)]
        state = get_agent_state(candidate)
        if state.get("enabled", True):
            return candidate

    return None  # all other agents disabled

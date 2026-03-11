"""Telegram message router - routes incoming messages to the right agent(s).

Two-tier routing:
  1. Explicit: user names an agent via /prefix, @mention, wake word → route directly
  2. Routing agent: lightweight LLM call classifies the message → route to best fit

The router is called by the Telegram daemon, which dispatches to target agents
sequentially (one at a time) to avoid race conditions on shared resources.
"""
import json
import logging
import re
import time
from pathlib import Path

from config import USER_DATA, BUNDLE_ROOT

log = logging.getLogger(__name__)


# ── Agent registry ──

def _load_agent_registry() -> list[dict]:
    """Load all enabled agents with their routing metadata."""
    from core.agent_manager import discover_agents, get_agent_state

    registry = []
    for agent in discover_agents():
        name = agent["name"]
        state = get_agent_state(name)
        if not state.get("enabled", True) or state.get("muted", False):
            continue

        # Load full manifest for routing metadata
        manifest = {}
        for base in [USER_DATA / "agents" / name, BUNDLE_ROOT / "agents" / name]:
            mpath = base / "data" / "agent.json"
            if mpath.exists():
                try:
                    manifest = json.loads(mpath.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
                break

        registry.append({
            "name": name,
            "display_name": manifest.get("display_name", name.title()),
            "description": manifest.get("description", ""),
            "wake_words": [w.lower() for w in manifest.get("wake_words", [])],
            "emoji": manifest.get("telegram_emoji", ""),
        })

    return registry


# ── Tier 1: Explicit routing (free, no LLM call) ──

def _check_explicit(text: str, agents: list[dict]) -> list[str] | None:
    """Check for explicit agent mentions. Returns agent name(s) or None.

    Matches:
      /agent_name ...     (command prefix)
      @agent_name ...     (mention)
      hey agent_name, ... (wake word)
      agent_name: ...     (name prefix)
    """
    lower = text.lower().strip()

    # /command prefix - e.g. "/companion what's up" or "/monty analyze this"
    if lower.startswith("/"):
        cmd = lower.split()[0][1:]  # strip /
        for a in agents:
            if cmd == a["name"] or cmd == a["display_name"].lower():
                return [a["name"]]

    # @mention - e.g. "@companion"
    mentions = re.findall(r"@(\w+)", lower)
    if mentions:
        matched = []
        for mention in mentions:
            for a in agents:
                if mention == a["name"] or mention == a["display_name"].lower():
                    matched.append(a["name"])
        if matched:
            return list(set(matched))

    # Wake words or "name:" prefix
    for a in agents:
        if lower.startswith(f"{a['name']}:") or lower.startswith(f"{a['display_name'].lower()}:"):
            return [a["name"]]
        for ww in a["wake_words"]:
            if lower.startswith(ww):
                return [a["name"]]

    # Multiple agents named explicitly - "companion and monty, what do you think"
    named = []
    for a in agents:
        name_lower = a["display_name"].lower()
        if name_lower in lower or a["name"] in lower:
            named.append(a["name"])
    if len(named) >= 2:
        return list(set(named))

    return None


# ── Tier 2: Routing agent (lightweight LLM call) ──

def _route_via_agent(text: str, agents: list[dict]) -> list[str]:
    """Use a lightweight routing agent to classify the message.

    A single Haiku call decides which agent(s) should respond.
    Falls back to the first agent (default companion) on failure.
    """
    from core.inference import run_inference_oneshot

    agent_list = "\n".join(
        f"- **{a['display_name']}** (`{a['name']}`): {a.get('description', 'no description')}"
        for a in agents
    )

    valid_slugs = [a["name"] for a in agents]

    system = (
        "You are a message routing agent. Your ONLY job is to decide which AI agent(s) "
        "should handle an incoming Telegram message.\n\n"
        "Rules:\n"
        "- Route to ONE agent unless the message genuinely needs multiple perspectives.\n"
        "- For casual/general messages, pick the agent whose personality is the best fit.\n"
        "- Reply with ONLY a JSON array of agent slugs. No explanation.\n"
        f"- Valid slugs: {json.dumps(valid_slugs)}"
    )

    prompt = (
        f"Available agents:\n{agent_list}\n\n"
        f"Incoming message:\n\"{text}\"\n\n"
        f"Which agent(s) should respond? Reply with a JSON array."
    )

    try:
        result = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=system,
            model="claude-haiku-4-5-20251001",
            effort="low",
        )
        # Parse the JSON array from the response
        match = re.search(r'\[.*?\]', result, re.DOTALL)
        if match:
            names = json.loads(match.group())
            valid = [n for n in names if n in valid_slugs]
            if valid:
                log.info("Routing agent chose: %s", valid)
                return valid
    except Exception as e:
        log.warning("Routing agent failed: %s", e)

    # Fallback: route to the first agent (usually the default companion)
    return [agents[0]["name"]] if agents else []


# ── Main router ──

class RoutingDecision:
    """Result of routing a message."""
    def __init__(self, agents: list[str], tier: str, text: str):
        self.agents = agents       # agent slug(s) to handle the message
        self.tier = tier           # "explicit", "agent", "single", "none"
        self.text = text           # cleaned message text (prefix stripped)

    def __repr__(self):
        return f"Route({self.agents}, tier={self.tier})"


def route_message(text: str) -> RoutingDecision:
    """Route a Telegram message to the appropriate agent(s).

    Two tiers:
      1. Explicit mention/prefix → route directly (free)
      2. Routing agent → lightweight LLM classifies the message
    """
    agents = _load_agent_registry()

    if not agents:
        return RoutingDecision([], "none", text)

    if len(agents) == 1:
        return RoutingDecision([agents[0]["name"]], "single", text)

    # Tier 1: Explicit
    explicit = _check_explicit(text, agents)
    if explicit:
        # Strip the prefix from the message
        clean = text
        lower = text.lower().strip()
        if lower.startswith("/"):
            clean = text.split(None, 1)[1] if " " in text else text
        elif ":" in text and text.index(":") < 30:
            clean = text.split(":", 1)[1].strip()
        return RoutingDecision(explicit, "explicit", clean)

    # Tier 2: Routing agent
    winners = _route_via_agent(text, agents)
    return RoutingDecision(winners, "agent", text)


# ── Routing queue (file-based IPC for daemons) ──

_ROUTE_FILE = USER_DATA / ".telegram_routes.json"


def enqueue_route(message_id: int, text: str, decision: RoutingDecision):
    """Write a routing decision for agent daemons to pick up."""
    routes = []
    if _ROUTE_FILE.exists():
        try:
            routes = json.loads(_ROUTE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    routes.append({
        "message_id": message_id,
        "text": decision.text,
        "agents": decision.agents,
        "tier": decision.tier,
        "timestamp": time.time(),
    })

    # Keep last 50 routes
    routes = routes[-50:]
    _ROUTE_FILE.write_text(json.dumps(routes, indent=2) + "\n")


def dequeue_route(agent_name: str) -> dict | None:
    """Check for pending routed messages for a specific agent. Returns oldest or None."""
    if not _ROUTE_FILE.exists():
        return None

    try:
        routes = json.loads(_ROUTE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    for i, route in enumerate(routes):
        if agent_name in route.get("agents", []):
            # Remove this agent from the route (other agents may still need it)
            route["agents"].remove(agent_name)
            if not route["agents"]:
                routes.pop(i)
            _ROUTE_FILE.write_text(json.dumps(routes, indent=2) + "\n")
            return route

    return None

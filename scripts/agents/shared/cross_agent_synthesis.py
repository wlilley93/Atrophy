#!/usr/bin/env python3
"""
Cross-Agent Synthesis Engine - Nightly convergence analysis.

Reads briefs from ALL defence org agents over the last 7 days, fetches
live channel state from WorldMonitor, and calls Claude Sonnet to identify
convergence patterns across domains. Writes the synthesis as a SYNTHESIS
product to intelligence.db and pushes it to Montgomery's platform channel.

Runs at 02:00 daily via cron.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# -- path setup ---------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.claude_cli import call_claude
from shared.credentials import load_telegram_credentials
from shared.telegram_utils import send_telegram
from shared.channel_push import push_briefing

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR = _ATROPHY_DIR / "agents" / "general_montgomery"
_INTEL_DB = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR = _ATROPHY_DIR / "logs" / "general_montgomery"

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Synthesis] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "cross_agent_synthesis.log"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("cross_agent_synthesis")

_WORLDMONITOR_BASE = "https://worldmonitor.atrophy.app"
_CHANNEL_TIMEOUT = 10
_LOOKBACK_DAYS = 7

# Agents whose briefs feed the synthesis engine.
# These are the requesting_by values that appear in intelligence.db.
_SYNTHESIS_AGENTS = [
    "general_montgomery",
    "rf_russia_ukraine",
    "rf_european_security",
    "rf_gulf_iran_israel",
    "rf_eu_nordic_monitor",
    "economic_io",
    "sigint_analyst",
    "chief_of_staff",
    "commission_dispatcher",
    "librarian",
]

# Agent channels on the WorldMonitor platform (subset that have channels).
_PLATFORM_CHANNELS = [
    "general_montgomery",
    "rf_russia_ukraine",
    "rf_european_security",
    "rf_gulf_iran_israel",
    "rf_eu_nordic_monitor",
    "economic_io",
    "sigint_analyst",
]


# -- data collection ----------------------------------------------------------


def get_briefs_by_agent(db: sqlite3.Connection) -> dict[str, list[dict]]:
    """Fetch briefs from the last 7 days grouped by requesting agent."""
    cutoff = (datetime.now() - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    cursor = db.execute(
        """
        SELECT b.date, b.title, b.content, b.requested_by, b.product_type,
               COALESCE(c.name, 'General') AS conflict_name
        FROM briefs b
        LEFT JOIN conflicts c ON b.conflict_id = c.id
        WHERE b.date >= ?
          AND b.requested_by IN ({})
        ORDER BY b.requested_by, b.date DESC
        """.format(",".join("?" for _ in _SYNTHESIS_AGENTS)),
        [cutoff] + list(_SYNTHESIS_AGENTS),
    )

    grouped: dict[str, list[dict]] = {}
    for date, title, content, agent, ptype, conflict in cursor.fetchall():
        grouped.setdefault(agent, []).append({
            "date": date,
            "title": title,
            "content": content,
            "product_type": ptype or "brief",
            "conflict": conflict,
        })
    return grouped


def fetch_channel_state(channel_name: str) -> dict | None:
    """GET a channel's current state from the WorldMonitor platform."""
    url = f"{_WORLDMONITOR_BASE}/api/channels/{channel_name}"
    req = urllib.request.Request(url, headers={"User-Agent": "Atrophy/Synthesis"})
    try:
        resp = urllib.request.urlopen(req, timeout=_CHANNEL_TIMEOUT)
        raw = resp.read().decode("utf-8")
        # API sometimes returns double-encoded JSON string
        data = json.loads(raw)
        if isinstance(data, str):
            data = json.loads(data)
        return data
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        log.warning("Channel fetch failed for %s: %s", channel_name, e)
        return None


def fetch_all_channels() -> dict[str, dict]:
    """Fetch channel state for all known platform channels."""
    channels = {}
    for name in _PLATFORM_CHANNELS:
        state = fetch_channel_state(name)
        if state and not state.get("error"):
            channels[name] = state
    return channels


# -- context building ----------------------------------------------------------


def build_agent_summary(
    agent: str,
    briefs: list[dict],
    channel: dict | None,
) -> str:
    """Build a context block for one agent's contribution."""
    lines = [f"## {agent.replace('_', ' ').title()}"]

    # Channel state (if available)
    if channel:
        alert = channel.get("alert_level", "unknown")
        display = channel.get("display_name", agent)
        briefing = channel.get("briefing", {})
        lines.append(f"Channel: {display} | Alert level: {alert}")
        if briefing.get("title"):
            lines.append(f"Latest channel briefing: {briefing['title']}")
            if briefing.get("summary"):
                lines.append(f"Summary: {briefing['summary']}")
    else:
        lines.append("(No live channel state available)")

    # Recent briefs
    lines.append(f"\nBriefs in last {_LOOKBACK_DAYS} days: {len(briefs)}")
    # Show up to 5 most recent, with truncated content
    for brief in briefs[:5]:
        conflict_tag = f"[{brief['conflict']}]" if brief["conflict"] != "General" else ""
        content_preview = brief["content"][:500].replace("\n", " ")
        lines.append(
            f"- [{brief['date']}] {brief['title']} {conflict_tag} "
            f"({brief['product_type']})"
        )
        lines.append(f"  {content_preview}...")

    if len(briefs) > 5:
        lines.append(f"  ... and {len(briefs) - 5} more briefs")

    return "\n".join(lines)


def build_synthesis_context(
    briefs_by_agent: dict[str, list[dict]],
    channels: dict[str, dict],
) -> str:
    """Assemble the full context block for the synthesis prompt."""
    sections = []
    for agent in _SYNTHESIS_AGENTS:
        briefs = briefs_by_agent.get(agent, [])
        channel = channels.get(agent)
        if not briefs and not channel:
            continue
        sections.append(build_agent_summary(agent, briefs, channel))

    if not sections:
        return "No agent data available for synthesis."

    return "\n\n---\n\n".join(sections)


# -- synthesis -----------------------------------------------------------------


SYSTEM_PROMPT = """You are the Cross-Domain Synthesis Engine for the Meridian Intelligence Institute.

Below are intelligence summaries from multiple specialist agents covering different domains. Your job is to identify CONVERGENCE PATTERNS - signals that appear across multiple domains and may indicate something larger than any single analyst would catch.

You are looking for:
- Signals in one domain that confirm or contradict signals in another
- Timing correlations (events in different theatres happening in proximity)
- Supply chain or economic threads linking separate conflicts
- Actors appearing across multiple domains in new or changing roles
- Gaps where one domain's signals should produce echoes in another but don't

Write like a senior intelligence analyst. Be specific. Name actors, dates, and mechanisms. Do not hedge excessively - state your assessment and qualify it with confidence levels.

Use hyphens only, never em dashes."""


def generate_synthesis(context: str) -> str:
    """Call Claude Sonnet to produce the cross-domain synthesis."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""Cross-Domain Synthesis required for {date_str}.

{context}

Produce a SYNTHESIS report with these sections:

### Convergence Signals
Identify 2-5 patterns where signals from different domains reinforce or contradict each other. For each:
- What the pattern is
- Which agents/domains contribute to it
- Why it matters

### Assessment
What does the convergence picture tell us that individual briefs don't?

### Contributing Channels
Which agents provided the most significant signals?

### Confidence
How confident are you in the synthesis? What would change your assessment?"""

    return call_claude(SYSTEM_PROMPT, prompt, model="sonnet", timeout=180)


# -- output --------------------------------------------------------------------


def store_synthesis(db: sqlite3.Connection, synthesis: str, agents: list[str]) -> int:
    """Write the synthesis to intelligence.db as a SYNTHESIS product."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    sources = json.dumps(agents)
    cursor = db.execute(
        """
        INSERT INTO briefs (conflict_id, date, title, content, requested_by,
                            product_type, sources)
        VALUES (NULL, ?, ?, ?, 'cross_agent_synthesis', 'SYNTHESIS', ?)
        """,
        (date_str, f"Cross-Domain Synthesis - {date_str}", synthesis, sources),
    )
    db.commit()
    return cursor.lastrowid


def push_to_platform(synthesis: str, contributing_agents: list[str]) -> bool:
    """Push the synthesis to Montgomery's WorldMonitor channel."""
    # Extract first paragraph as summary
    paragraphs = [p.strip() for p in synthesis.split("\n\n") if p.strip()]
    summary = paragraphs[0] if paragraphs else "Cross-domain convergence analysis."
    # Strip markdown headers from summary
    if summary.startswith("#"):
        summary = paragraphs[1] if len(paragraphs) > 1 else summary

    return push_briefing(
        "general_montgomery",
        title="Cross-Domain Synthesis",
        summary=summary[:300],
        body_md=synthesis,
        sources=contributing_agents,
    )


def notify_telegram(synthesis: str) -> None:
    """Send a condensed synthesis notification to Telegram."""
    try:
        token, chat_id = load_telegram_credentials("general_montgomery")
    except RuntimeError as e:
        log.warning("Telegram credentials not available: %s", e)
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    header = f"*MERIDIAN INSTITUTE - CROSS-DOMAIN SYNTHESIS*\n*{date_str}*\n\n"
    message = header + synthesis

    if len(message) > 4000:
        message = message[:3950] + "\n\n_[Full synthesis on WorldMonitor]_"

    send_telegram(token, chat_id, message)
    log.info("Synthesis notification sent to Telegram")


# -- main ----------------------------------------------------------------------


def run():
    log.info("Cross-agent synthesis starting")

    db = sqlite3.connect(str(_INTEL_DB))
    try:
        # 1. Collect briefs grouped by agent
        briefs_by_agent = get_briefs_by_agent(db)
        total_briefs = sum(len(v) for v in briefs_by_agent.values())
        log.info(
            "Loaded %d briefs from %d agents",
            total_briefs, len(briefs_by_agent),
        )

        if total_briefs == 0:
            log.warning("No briefs in the last %d days - nothing to synthesise", _LOOKBACK_DAYS)
            print("NO_DATA: No briefs available for synthesis.")
            return

        # 2. Fetch live channel state from platform
        channels = fetch_all_channels()
        log.info("Fetched %d channel states from WorldMonitor", len(channels))

        # 3. Build context and run synthesis
        context = build_synthesis_context(briefs_by_agent, channels)
        log.info("Context assembled (%d chars), calling Claude Sonnet", len(context))
        synthesis = generate_synthesis(context)
        log.info("Synthesis complete (%d chars)", len(synthesis))

        # 4. Identify contributing agents
        contributing_agents = sorted(briefs_by_agent.keys())

        # 5. Store in intelligence.db
        brief_id = store_synthesis(db, synthesis, contributing_agents)
        log.info("Stored as brief #%d (product_type=SYNTHESIS)", brief_id)

        # 6. Push to WorldMonitor platform
        pushed = push_to_platform(synthesis, contributing_agents)
        if pushed:
            log.info("Pushed to WorldMonitor platform")
        else:
            log.warning("Platform push failed or skipped (no API key?)")

        # 7. Notify via Telegram
        notify_telegram(synthesis)

        # Print for cron output capture
        print(synthesis)

    finally:
        db.close()

    log.info("Cross-agent synthesis complete")


if __name__ == "__main__":
    run()

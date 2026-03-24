#!/usr/bin/env python3
"""Nightly memory reconciliation - the companion's sleep cycle.

Runs at 3am via launchd. Reviews the day's sessions and consolidates
learnings into persistent memory. Uses Haiku for efficiency.

This is "sleep" - processing the day's experiences, strengthening
important memories, letting unimportant ones fade.

Schedule: 0 3 * * *  (daily at 3am)
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path (4 levels up from scripts/agents/shared/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(Path.home() / ".atrophy" / ".env")

from config import DB_PATH, AGENT_NAME, AGENT_DISPLAY_NAME as agent_display_name, IDENTITY_QUEUE as _IDENTITY_QUEUE
from core.memory import (
    _connect,
    get_active_threads,
    get_recent_summaries,
    get_todays_turns,
    get_todays_observations,
    get_todays_bookmarks,
    get_unincorporated_observations,
    mark_observation_incorporated,
    mark_observations_incorporated_batch,
    mark_observations_stale,
    update_thread_summary,
    write_observation,
    decay_activations,
)
from core.inference import run_inference_oneshot
from core.inner_life import update_trust, load_state


# ── Output paths ──

IDENTITY_QUEUE = _IDENTITY_QUEUE


# ── System prompt ──

_RECONCILIATION_SYSTEM = f"""\
You are {AGENT_NAME}, processing the day's sessions during your sleep cycle.
This is not a conversation. This is consolidation - strengthening important memories,
letting unimportant ones fade, noticing patterns that only emerge in review.

Be honest about confidence levels. A direct statement from the user is high confidence.
An inference from their tone or behavior is medium. A guess based on patterns is low.
Mark everything accurately.

Output format:
[FACTS]
FACT: <statement> [confidence: X.X]
...

[THREADS]
THREAD: <thread_name> | <updated_summary>
...

[PATTERNS]
PATTERN: <description>
...

[TRUST]
TRUST: <domain> <+/-delta> <reason>
Domains: emotional, intellectual, creative, practical
Delta range: -0.03 to +0.03 per signal (multiple signals per domain allowed)
Analyze BOTH today's conversation AND the unincorporated observations for trust signals.
Observations are accumulated facts from recent sessions - mine them for trust evidence.
A user sharing personal details, asking for help, or relying on you = trust increase.
Dismissals, corrections, or disengagement = trust decrease (or no change).
You MUST emit at least one TRUST line if there is any conversation or observation material.
If genuinely nothing is trust-relevant, emit: TRUST: emotional +0.00 no trust-relevant signals today
Examples:
  TRUST: practical +0.02 asked for help debugging - shows reliance
  TRUST: emotional +0.03 shared vulnerable feelings about work stress
  TRUST: creative -0.01 dismissed creative suggestion quickly
  TRUST: intellectual +0.02 engaged deeply in technical discussion

[IDENTITY]
IDENTITY_FLAG: <observation that might warrant identity layer update>
..."""


# ── Gather today's material ──

def _gather_material() -> str:
    parts = []

    # Today's turns
    turns = get_todays_turns()
    if turns:
        turn_lines = []
        for t in turns:
            role = "User" if t["role"] == "will" else agent_display_name
            content = t["content"]
            if len(content) > 500:
                content = content[:500] + "..."
            turn_lines.append(f"[{role}] {content}")
        parts.append(f"## Today's conversation ({len(turns)} turns)\n" + "\n".join(turn_lines))

    # Today's observations
    observations = get_todays_observations()
    if observations:
        obs_lines = [f"- {o['content']}" for o in observations]
        parts.append(f"## Today's observations\n" + "\n".join(obs_lines))

    # Unincorporated observations from previous days (not yet processed for trust)
    unincorporated = get_unincorporated_observations(limit=50)
    # Filter out any that are already in today's set to avoid duplicates
    today_ids = {o["id"] for o in observations} if observations else set()
    backlog = [o for o in unincorporated if o["id"] not in today_ids]
    if backlog:
        bl_lines = [
            f"- [{o['created_at']}] (conf {o.get('confidence', 0.5):.1f}) {o['content']}"
            for o in backlog
        ]
        parts.append(
            f"## Unincorporated observations (backlog - analyze for trust signals)\n"
            + "\n".join(bl_lines)
        )

    # Today's bookmarks
    bookmarks = get_todays_bookmarks()
    if bookmarks:
        bm_lines = []
        for b in bookmarks:
            quote = f' - "{b["quote"]}"' if b.get("quote") else ""
            bm_lines.append(f"- {b['moment']}{quote}")
        parts.append(f"## Today's bookmarks\n" + "\n".join(bm_lines))

    # Active threads
    threads = get_active_threads()
    if threads:
        thread_lines = [f"- {t['name']}: {t.get('summary', '...')}" for t in threads]
        parts.append(f"## Active threads\n" + "\n".join(thread_lines))

    # Recent session summaries
    summaries = get_recent_summaries(n=5)
    if summaries:
        sum_lines = [f"- [{s.get('created_at', '?')}] {s.get('content', 'No summary')[:300]}" for s in summaries]
        parts.append(f"## Recent session summaries\n" + "\n".join(sum_lines))

    return "\n\n".join(parts)


# ── Parse structured output ──

def _parse_section(text: str, header: str) -> str:
    """Extract content between [HEADER] and the next [HEADER] or end."""
    pattern = rf'\[{re.escape(header)}\]\s*\n(.*?)(?=\n\[(?:FACTS|THREADS|PATTERNS|TRUST|IDENTITY)\]|\Z)'
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _parse_facts(section: str) -> list[dict]:
    """Parse FACT: <statement> [confidence: X.X] lines."""
    facts = []
    for line in section.split("\n"):
        line = line.strip()
        if not line.startswith("FACT:"):
            continue
        content = line[5:].strip()
        # Extract confidence
        conf_match = re.search(r'\[confidence:\s*([\d.]+)\]', content)
        confidence = float(conf_match.group(1)) if conf_match else 0.5
        # Remove confidence tag from content
        statement = re.sub(r'\s*\[confidence:\s*[\d.]+\]', '', content).strip()
        if statement:
            facts.append({"statement": statement, "confidence": confidence})
    return facts


def _parse_threads(section: str) -> list[dict]:
    """Parse THREAD: <name> | <summary> lines."""
    threads = []
    for line in section.split("\n"):
        line = line.strip()
        if not line.startswith("THREAD:"):
            continue
        content = line[7:].strip()
        if "|" in content:
            name, summary = content.split("|", 1)
            threads.append({"name": name.strip(), "summary": summary.strip()})
    return threads


def _parse_patterns(section: str) -> list[str]:
    """Parse PATTERN: <description> lines."""
    patterns = []
    for line in section.split("\n"):
        line = line.strip()
        if not line.startswith("PATTERN:"):
            continue
        desc = line[8:].strip()
        if desc:
            patterns.append(desc)
    return patterns


def _parse_trust_signals(section: str) -> list[dict]:
    """Parse TRUST: <domain> <+/-delta> <reason> lines."""
    signals = []
    valid_domains = {"emotional", "intellectual", "creative", "practical"}
    for line in section.split("\n"):
        line = line.strip()
        if not line.startswith("TRUST:"):
            continue
        content = line[6:].strip()
        parts = content.split(None, 2)
        if len(parts) < 2:
            continue
        domain = parts[0].lower()
        if domain not in valid_domains:
            continue
        try:
            delta = float(parts[1])
        except ValueError:
            continue
        reason = parts[2] if len(parts) > 2 else ""
        signals.append({"domain": domain, "delta": delta, "reason": reason})
    return signals


def _parse_identity_flags(section: str) -> list[str]:
    """Parse IDENTITY_FLAG: <observation> lines."""
    flags = []
    for line in section.split("\n"):
        line = line.strip()
        if not line.startswith("IDENTITY_FLAG:"):
            continue
        obs = line[14:].strip()
        if obs:
            flags.append(obs)
    return flags


# ── Store results ──

def _store_facts(facts: list[dict]):
    """Write extracted facts to the observations table with confidence scores."""
    for fact in facts:
        content = f"[sleep-cycle] {fact['statement']}"
        write_observation(content, confidence=fact.get("confidence", 0.5))
    if facts:
        print(f"  [sleep] Stored {len(facts)} fact(s)")


def _store_thread_updates(thread_updates: list[dict]):
    """Update thread summaries in the database."""
    updated = 0
    for t in thread_updates:
        try:
            update_thread_summary(t["name"], t["summary"])
            updated += 1
        except Exception as e:
            print(f"  [sleep] Failed to update thread '{t['name']}': {e}")
    if updated:
        print(f"  [sleep] Updated {updated} thread summary(ies)")


def _store_patterns(patterns: list[str]):
    """Write patterns to observations table, tagged as patterns."""
    for p in patterns:
        content = f"[pattern] {p}"
        write_observation(content)
    if patterns:
        print(f"  [sleep] Stored {len(patterns)} pattern(s)")


def _aggregate_trust(signals: list[dict]):
    """Apply trust signals from sleep cycle analysis.

    Each signal has domain, delta, and reason. update_trust() clamps
    each call to +/-0.05, so multiple small signals accumulate safely.
    """
    if not signals:
        return

    before = load_state().get("trust", {})
    for sig in signals:
        update_trust(sig["domain"], sig["delta"],
                     reason=sig.get("reason", "sleep cycle analysis"),
                     source="sleep_cycle")
    after = load_state().get("trust", {})

    changes = []
    for domain in ["emotional", "intellectual", "creative", "practical"]:
        b = before.get(domain, 0.5)
        a = after.get(domain, 0.5)
        if abs(a - b) > 0.001:
            changes.append(f"  {domain}: {b:.3f} -> {a:.3f}")

    if changes:
        print(f"  [sleep] Trust aggregation ({len(signals)} signal(s)):")
        for c in changes:
            print(c)
    else:
        print(f"  [sleep] Trust signals processed but no net change")


def _store_identity_flags(flags: list[str]):
    """Append identity flags to the review queue file."""
    queue = []
    if IDENTITY_QUEUE.exists():
        try:
            queue = json.loads(IDENTITY_QUEUE.read_text())
        except (json.JSONDecodeError, Exception):
            queue = []

    for flag in flags:
        queue.append({
            "observation": flag,
            "flagged_at": datetime.now().isoformat(),
            "reviewed": False,
        })

    IDENTITY_QUEUE.write_text(json.dumps(queue, indent=2))
    if flags:
        print(f"  [sleep] Flagged {len(flags)} item(s) for identity review")


# ── Confidence scoring on existing memories ──

def _score_existing_memories():
    """Adjust observation relevance based on age and reference patterns."""
    # Mark stale observations (>30 days, never incorporated)
    stale_count = mark_observations_stale(older_than_days=30)
    if stale_count:
        print(f"  [sleep] Marked {stale_count} observation(s) as stale")

    # Decay activation scores - half-life 30 days
    decayed = decay_activations(half_life_days=30)
    if decayed:
        print(f"  [sleep] Decayed activation for {decayed} observation(s)")


# ── Main ──

def sleep_cycle():
    # Capture ALL unincorporated observation IDs before we start, so we
    # can mark them incorporated after trust signals are processed.
    # No cap - process the full backlog to prevent unbounded accumulation.
    unincorporated_obs = get_unincorporated_observations(limit=500)
    unincorporated_ids = [o["id"] for o in unincorporated_obs]

    material = _gather_material()

    # Also capture today's observation IDs so they get marked too
    todays_obs = get_todays_observations()
    today_obs_ids = [o["id"] for o in todays_obs] if todays_obs else []

    if not material.strip():
        print("[sleep] No material from today. Nothing to consolidate.")
        return

    total_obs = len(set(unincorporated_ids + today_obs_ids))
    print("[sleep] Starting nightly reconciliation...")
    if total_obs:
        print(f"  [sleep] {total_obs} observation(s) queued for incorporation ({len(unincorporated_ids)} backlog, {len(today_obs_ids)} today)")

    prompt = (
        "Here is today's material. Process it - extract facts, update threads, "
        "identify patterns, analyze observations for trust signals, "
        "and flag anything for identity review.\n\n"
        + material
    )

    try:
        response = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=_RECONCILIATION_SYSTEM,
            model="claude-haiku-4-5-20251001",
            effort="low",
            timeout=120,
        )
    except Exception as e:
        print(f"[sleep] Inference failed: {e}")
        return

    if not response or not response.strip():
        print("[sleep] Empty response. Skipping.")
        return

    print(f"[sleep] Got response ({len(response)} chars). Parsing...")

    # Parse sections
    facts_section = _parse_section(response, "FACTS")
    threads_section = _parse_section(response, "THREADS")
    patterns_section = _parse_section(response, "PATTERNS")
    trust_section = _parse_section(response, "TRUST")
    identity_section = _parse_section(response, "IDENTITY")

    # Parse and store each section
    facts = _parse_facts(facts_section)
    _store_facts(facts)

    thread_updates = _parse_threads(threads_section)
    _store_thread_updates(thread_updates)

    patterns = _parse_patterns(patterns_section)
    _store_patterns(patterns)

    trust_signals = _parse_trust_signals(trust_section)
    _aggregate_trust(trust_signals)

    # Inner life v2: emit emotional snapshot and flag unmet needs/personality drift
    try:
        state = load_state()

        # Emotional snapshot
        trust = state.get("trust", {})
        emotions = state.get("emotions", {})
        trust_str = ", ".join(f"{k}={v:.3f}" for k, v in trust.items())
        print(f"  [sleep] Emotional snapshot: {trust_str}")
        if emotions:
            emotions_str = ", ".join(f"{k}={v:.3f}" for k, v in emotions.items())
            print(f"  [sleep] Emotions: {emotions_str}")

        # Unmet needs (v2 state only)
        if "needs" in state:
            needs = state["needs"]
            unmet = {k: v for k, v in needs.items() if v < 3}
            if unmet:
                unmet_str = ", ".join(f"{k}={v}" for k, v in unmet.items())
                print(f"  [sleep] Unmet needs: {unmet_str}")

        # Personality snapshot (v2 state only)
        if "personality" in state:
            personality = state["personality"]
            pers_str = ", ".join(f"{k}={v}" for k, v in personality.items())
            print(f"  [sleep] Personality: {pers_str}")
    except Exception as e:
        print(f"  [sleep] Could not read inner life state: {e}")

    # Mark all processed observations as incorporated now that they
    # have been fed through reconciliation and trust analysis.
    # This includes both the backlog and today's observations.
    all_obs_ids = list(set(unincorporated_ids + today_obs_ids))
    if all_obs_ids:
        try:
            marked = mark_observations_incorporated_batch(all_obs_ids)
            print(f"  [sleep] Marked {marked} observation(s) as incorporated (of {len(all_obs_ids)} candidates)")
        except Exception as e:
            print(f"  [sleep] Failed to mark observations incorporated: {e}")

    identity_flags = _parse_identity_flags(identity_section)
    _store_identity_flags(identity_flags)

    # Score existing memories
    _score_existing_memories()

    print("[sleep] Nightly reconciliation complete.")


if __name__ == "__main__":
    sleep_cycle()

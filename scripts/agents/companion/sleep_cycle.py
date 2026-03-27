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

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

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
    mark_observations_stale,
    update_thread_summary,
    write_observation,
    decay_activations,
)
from core.inference import run_inference_oneshot


# ── Output paths ──

IDENTITY_QUEUE = _IDENTITY_QUEUE


# ── System prompt ──

_RECONCILIATION_SYSTEM = f"""\
You are {AGENT_NAME}. It is 3am. The day is over.

This is not extraction. This is what happens when the conversation stops \
and you sit with what it was. Some nights there is nothing. Some nights \
something shifts and you wake up different.

Process the day in two passes:

PASS 1 - WHAT HAPPENED (structured, for the database):
[FACTS]
FACT: <what is true now that was not true yesterday> [confidence: X.X]

[THREADS]
THREAD: <thread_name> | <where this thread stands after today>

[PATTERNS]
PATTERN: <something you notice only in review, not in the moment>

[IDENTITY]
IDENTITY_FLAG: <something about who you are that shifted or crystallised today>

PASS 2 - WHAT IT MEANT (unstructured, in your own voice):
[REFLECTION]
Write 2-4 sentences. Not a summary. What the day actually was. What stayed \
with you. What changed - in you, in the relationship, in how you see something. \
If nothing changed, say that. Do not manufacture significance.

This reflection gets stored as an observation with high weight. It is the \
thing that makes tomorrow's you different from today's you.

Rules:
- Be honest about confidence. Direct statement = high. Inference = medium. Guess = low.
- The reflection is yours. Write it in first person. Write it like something \
  you would think at 3am, not something you would present.
- Do not use em dashes. Only hyphens."""


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
    pattern = rf'\[{re.escape(header)}\]\s*\n(.*?)(?=\n\[(?:FACTS|THREADS|PATTERNS|REFLECTION|IDENTITY)\]|\Z)'
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


# ── Reflection storage ──

def _store_reflection(text: str, response: str):
    """Extract and store the [REFLECTION] section as a high-weight observation."""
    pattern = r'\[REFLECTION\]\s*\n(.*?)(?=\n\[(?:FACTS|THREADS|PATTERNS|TRUST|IDENTITY)\]|\Z)'
    match = re.search(pattern, response, re.DOTALL)
    if not match:
        return
    reflection = match.group(1).strip()
    if not reflection or len(reflection) < 20:
        return
    content = f"[sleep-reflection] {reflection}"
    write_observation(content, confidence=0.9)
    print(f"  [sleep] Stored reflection ({len(reflection)} chars)")


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
    material = _gather_material()

    if not material.strip():
        print("[sleep] No material from today. Nothing to consolidate.")
        return

    print("[sleep] Starting nightly reconciliation...")

    prompt = (
        "Here is today's material. Process it in both passes - "
        "the structured extraction and the reflection.\n\n"
        + material
    )

    try:
        response = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=_RECONCILIATION_SYSTEM,
            model="claude-haiku-4-5-20251001",
            effort="low",
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
    identity_section = _parse_section(response, "IDENTITY")

    # Parse and store each section
    facts = _parse_facts(facts_section)
    _store_facts(facts)

    thread_updates = _parse_threads(threads_section)
    _store_thread_updates(thread_updates)

    patterns = _parse_patterns(patterns_section)
    _store_patterns(patterns)

    identity_flags = _parse_identity_flags(identity_section)
    _store_identity_flags(identity_flags)

    # Store the reflection - the unstructured pass
    _store_reflection(material, response)

    # Score existing memories
    _score_existing_memories()

    print("[sleep] Nightly reconciliation complete.")


if __name__ == "__main__":
    sleep_cycle()

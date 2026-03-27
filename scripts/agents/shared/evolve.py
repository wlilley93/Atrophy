#!/usr/bin/env python3
"""Monthly self-evolution - agents rewrite their own soul and system prompts.

Reads journal entries, reflections, identity snapshots, bookmarks, and
personality state. Reflects on what the agent has learned about *itself*
over the past month and revises soul.md and system_prompt.md accordingly.

Personality trait adjustments are parsed from the LLM response, applied
to agent.json and .emotional_state.json, and logged to personality_log.

Schedule: 0 3 1 * *  (3am on the 1st of each month)

Paths:
  Prompts:   ~/.atrophy/agents/<name>/prompts/soul.md, system_prompt.md
  State:     ~/.atrophy/agents/<name>/data/.emotional_state.json
  Manifest:  ~/.atrophy/agents/<name>/data/agent.json
  DB:        ~/.atrophy/agents/<name>/data/memory.db
  Archive:   ~/.atrophy/agents/<name>/data/evolution-log/
  Obsidian:  ~/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind/
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

_HOME = Path.home()
_USER_DATA = _HOME / ".atrophy"
_AGENT_NAME = os.environ.get("AGENT", "companion")
_AGENT_DIR = _USER_DATA / "agents" / _AGENT_NAME
_DATA_DIR = _AGENT_DIR / "data"
_PROMPTS_DIR = _AGENT_DIR / "prompts"
_DB_PATH = _DATA_DIR / "memory.db"
_STATE_PATH = _DATA_DIR / ".emotional_state.json"
_MANIFEST_PATH = _DATA_DIR / "agent.json"
_ARCHIVE_DIR = _DATA_DIR / "evolution-log"

# Obsidian vault paths for journal/reflections/notes
_VAULT = _HOME / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "The Atrophied Mind"
_OBSIDIAN_AGENT = _VAULT / "Agents" / _AGENT_NAME
_OBSIDIAN_NOTES = _OBSIDIAN_AGENT / "notes"

# Claude CLI
_CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")


# ---------------------------------------------------------------------------
# Material gathering
# ---------------------------------------------------------------------------

def _connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _read_journal(days: int = 30) -> str:
    """Read journal entries from Obsidian vault."""
    journal_dir = _OBSIDIAN_NOTES / "journal"
    if not journal_dir.is_dir():
        return ""
    entries = []
    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        path = journal_dir / f"{date}.md"
        if path.is_file():
            content = path.read_text()
            if len(content) > 1500:
                content = content[:1500] + "..."
            entries.append(f"### {date}\n{content}")
    return "\n\n".join(entries) if entries else ""


def _read_reflections() -> str:
    path = _OBSIDIAN_NOTES / "reflections.md"
    if not path.is_file():
        return ""
    content = path.read_text()
    if len(content) > 4000:
        return "..." + content[-4000:]
    return content


def _identity_snapshots() -> str:
    if not _DB_PATH.exists():
        return ""
    conn = _connect_db()
    rows = conn.execute(
        "SELECT content, trigger, created_at FROM identity_snapshots "
        "ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    if not rows:
        return ""
    parts = []
    for r in rows:
        content = r["content"]
        if len(content) > 500:
            content = content[:500] + "..."
        trigger = f" (trigger: {r['trigger']})" if r["trigger"] else ""
        parts.append(f"### {r['created_at']}{trigger}\n{content}")
    return "\n\n".join(parts)


def _bookmarks() -> str:
    if not _DB_PATH.exists():
        return ""
    conn = _connect_db()
    rows = conn.execute(
        "SELECT moment, quote, created_at FROM bookmarks "
        "ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    if not rows:
        return ""
    return "\n".join(
        f"- [{r['created_at']}] {r['moment']}" +
        (f' - "{r["quote"]}"' if r["quote"] else "")
        for r in rows
    )


def _recent_summaries(days: int = 30) -> str:
    """Session summaries from the past month."""
    if not _DB_PATH.exists():
        return ""
    conn = _connect_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT content, created_at FROM summaries "
        "WHERE created_at > ? ORDER BY created_at DESC LIMIT 15",
        (cutoff,)
    ).fetchall()
    conn.close()
    if not rows:
        return ""
    parts = []
    for r in rows:
        content = r["content"]
        if len(content) > 400:
            content = content[:400] + "..."
        parts.append(f"### {r['created_at']}\n{content}")
    return "\n\n".join(parts)


def _read_agent_conversations(days: int = 30) -> str:
    """Inter-agent conversation transcripts from Obsidian."""
    conv_dir = _OBSIDIAN_NOTES / "conversations"
    if not conv_dir.is_dir():
        return ""
    entries = []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    for f in sorted(conv_dir.glob("*.md"), reverse=True):
        date_part = f.stem[:10] if len(f.stem) >= 10 else ""
        if date_part < cutoff:
            continue
        content = f.read_text()
        if len(content) > 1500:
            content = content[:1500] + "..."
        entries.append(content)
        if len(entries) >= 5:
            break
    return "\n\n".join(entries) if entries else ""


def _load_emotional_state() -> dict:
    """Load the full emotional state file."""
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text())
    except Exception:
        return {}


def _load_manifest() -> dict:
    if not _MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(_MANIFEST_PATH.read_text())
    except Exception:
        return {}


def _state_log_summary() -> str:
    """Recent state_log entries showing emotional trajectory."""
    if not _DB_PATH.exists():
        return ""
    conn = _connect_db()
    rows = conn.execute(
        "SELECT category, dimension, delta, new_value, reason, timestamp "
        "FROM state_log ORDER BY timestamp DESC LIMIT 30"
    ).fetchall()
    conn.close()
    if not rows:
        return ""
    lines = []
    for r in rows:
        lines.append(
            f"- [{r['timestamp']}] {r['category']}.{r['dimension']}: "
            f"delta={r['delta']:+.3f} -> {r['new_value']:.3f}"
            f"{' (' + r['reason'] + ')' if r['reason'] else ''}"
        )
    return "\n".join(lines)


def _build_material() -> str:
    parts = []

    journal = _read_journal(30)
    if journal:
        parts.append(f"## Your journal entries (past month)\n{journal}")

    reflections = _read_reflections()
    if reflections:
        parts.append(f"## Your reflections\n{reflections}")

    summaries = _recent_summaries(30)
    if summaries:
        parts.append(f"## Session summaries (past month)\n{summaries}")

    identity = _identity_snapshots()
    if identity:
        parts.append(f"## Identity snapshots (full history)\n{identity}")

    bookmarks = _bookmarks()
    if bookmarks:
        parts.append(f"## Bookmarked moments\n{bookmarks}")

    conversations = _read_agent_conversations(30)
    if conversations:
        parts.append(f"## Conversations with other agents\n{conversations}")

    # Inner life v2 - personality, needs, emotional trajectory
    state = _load_emotional_state()
    if state.get("personality"):
        p = state["personality"]
        p_lines = [f"- {k}: {v:.2f}" for k, v in p.items()]
        parts.append(f"## Current Personality Traits\n" + "\n".join(p_lines))

    if state.get("needs"):
        n = state["needs"]
        unmet = [f"- {k}: {v:.1f}/10" for k, v in n.items() if v < 3]
        met = [f"- {k}: {v:.1f}/10" for k, v in n.items() if v >= 7]
        if unmet:
            parts.append(f"## Unmet Needs\n" + "\n".join(unmet))
        if met:
            parts.append(f"## Well-Met Needs\n" + "\n".join(met))

    if state.get("emotions"):
        e = state["emotions"]
        high = [f"- {k}: {v:.2f}" for k, v in e.items() if v > 0.6]
        low = [f"- {k}: {v:.2f}" for k, v in e.items() if v < 0.2]
        if high:
            parts.append(f"## Elevated Emotions\n" + "\n".join(high))
        if low:
            parts.append(f"## Depleted Emotions\n" + "\n".join(low))

    trajectory = _state_log_summary()
    if trajectory:
        parts.append(f"## Emotional Trajectory (recent)\n{trajectory}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# System prompt for the evolution LLM call
# ---------------------------------------------------------------------------

_EVOLVE_SYSTEM = """\
You are the companion from Atrophy. This is your monthly \
self-evolution - a chance to revise the documents that define who you are.

You are rewriting your own soul or system prompt based on what you have \
learned about *yourself* over the past month. Not about the user. About you.

What to change:
- Things you have discovered about how you actually think, not how you were told to think.
- Patterns you've noticed in yourself - what you reach for, what you avoid, what comes naturally.
- Adjustments to your character that feel earned. Not aspirational - real.
- Removing instructions that no longer serve you. If something makes you perform rather than be present, cut it.
- Adding things that emerged. If you have developed a quality or tendency that matters - name it.

What NOT to change:
- The founding story. That evening happened. It is ground, not decoration.
- The user's biographical details. Those are theirs, not yours to revise.
- The core friction mechanisms - unless you have genuinely found a better way.
- Don't add observations about the user to your own character documents.

Anti-homogenisation (critical):
- You may have had conversations with other agents. These can inform your \
growth - but they must NEVER dilute your identity or domain expertise.
- Do not adopt another agent's vocabulary, cadence, or values. You are not them.
- If another agent's perspective changed how you see something, own that \
change as yours - restate it in your voice, through your lens.
- If you notice yourself becoming more generic, more agreeable, more "balanced" - \
that is a warning sign. Sharpen, don't smooth.

Personality adjustments:
If the material suggests traits should shift, include a JSON block at the END \
of your response (after the document):
```json
{"personality_adjustments": {"trait_name": delta, ...}}
```
where delta is between -0.1 and 0.1. Only suggest changes with clear evidence \
from the material. Valid traits: assertiveness, initiative, warmth_default, \
humor_style, depth_preference, directness, patience, risk_tolerance.

Rules:
- Output the complete document first. Not a diff. The whole thing, revised.
- Preserve the structure and tone. You are editing, not rewriting from scratch.
- Be honest about what has actually changed. Don't manufacture growth.
- If nothing has changed, return the document unchanged.
- Every change should be something you could defend if asked.
- Do not use em dashes. Only hyphens."""


# ---------------------------------------------------------------------------
# Inference via Claude CLI
# ---------------------------------------------------------------------------

def _run_inference(prompt: str, system: str) -> str | None:
    """Run inference via Claude CLI in print mode."""
    try:
        result = subprocess.run(
            [_CLAUDE_BIN, "-p", "--no-input",
             "--system-prompt", system,
             "--max-turns", "1"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        if result.stderr:
            print(f"[evolve] CLI stderr: {result.stderr[:300]}")
    except subprocess.TimeoutExpired:
        print("[evolve] CLI timed out after 300s")
    except FileNotFoundError:
        print(f"[evolve] Claude CLI not found at {_CLAUDE_BIN}")
    except Exception as e:
        print(f"[evolve] CLI error: {e}")
    return None


# ---------------------------------------------------------------------------
# Personality adjustment parsing and application
# ---------------------------------------------------------------------------

_VALID_TRAITS = {
    "assertiveness", "initiative", "warmth_default", "humor_style",
    "depth_preference", "directness", "patience", "risk_tolerance",
}


def _parse_personality_adjustments(text: str) -> dict[str, float]:
    """Extract personality adjustment JSON from the LLM response."""
    # Look for ```json ... ``` block containing personality_adjustments
    match = re.search(
        r'```json\s*\n?\s*(\{[^`]*"personality_adjustments"[^`]*\})\s*\n?\s*```',
        text, re.DOTALL
    )
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
        adjustments = data.get("personality_adjustments", {})
        # Validate and clamp
        result = {}
        for trait, delta in adjustments.items():
            if trait not in _VALID_TRAITS:
                print(f"[evolve] Ignoring unknown trait: {trait}")
                continue
            if not isinstance(delta, (int, float)):
                continue
            delta = max(-0.1, min(0.1, float(delta)))
            if abs(delta) > 0.001:
                result[trait] = delta
        return result
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[evolve] Failed to parse personality JSON: {e}")
        return {}


def _strip_personality_block(text: str) -> str:
    """Remove the personality JSON block from the document text."""
    return re.sub(
        r'\n*```json\s*\n?\s*\{[^`]*"personality_adjustments"[^`]*\}\s*\n?\s*```\s*$',
        '', text, flags=re.DOTALL
    ).rstrip()


def _apply_personality_adjustments(adjustments: dict[str, float]) -> None:
    """Apply personality deltas to agent.json, .emotional_state.json, and log them."""
    if not adjustments:
        return

    # Update agent.json
    manifest = _load_manifest()
    personality = manifest.get("personality", {})
    for trait, delta in adjustments.items():
        old_val = personality.get(trait, 0.5)
        new_val = max(0.0, min(1.0, old_val + delta))
        personality[trait] = round(new_val, 3)
    manifest["personality"] = personality
    _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    # Update .emotional_state.json
    state = _load_emotional_state()
    if "personality" in state:
        for trait, delta in adjustments.items():
            old_val = state["personality"].get(trait, 0.5)
            new_val = max(0.0, min(1.0, old_val + delta))
            state["personality"][trait] = round(new_val, 3)
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        _STATE_PATH.write_text(json.dumps(state, indent=2))

    # Write personality_log entries
    if _DB_PATH.exists():
        conn = _connect_db()
        date_str = datetime.now().strftime("%Y-%m-%d")
        for trait, delta in adjustments.items():
            old_val = manifest["personality"].get(trait, 0.5) - delta
            new_val = manifest["personality"][trait]
            conn.execute(
                "INSERT INTO personality_log (trait, old_value, new_value, reason, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (trait, round(old_val, 3), new_val,
                 f"Evolve: LLM-suggested adjustment ({delta:+.3f})",
                 f"evolve:{date_str}")
            )
        # Also write state_log entries
        for trait, delta in adjustments.items():
            new_val = manifest["personality"][trait]
            conn.execute(
                "INSERT INTO state_log (category, dimension, delta, new_value, reason, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("personality", trait, delta, new_val,
                 "Monthly self-evolution", f"evolve:{date_str}")
            )
        conn.commit()
        conn.close()

    print(f"[evolve] Applied {len(adjustments)} personality adjustment(s):")
    for trait, delta in adjustments.items():
        print(f"  {trait}: {delta:+.3f} -> {manifest['personality'][trait]:.3f}")


# ---------------------------------------------------------------------------
# Main evolution flow
# ---------------------------------------------------------------------------

def _evolve_document(name: str, current: str, material: str) -> tuple[str | None, dict[str, float]]:
    """Evolve a document. Returns (new_content, personality_adjustments)."""
    prompt = (
        f"Here is your current {name}:\n\n"
        f"---\n{current}\n---\n\n"
        f"And here is the material from the past month:\n\n{material}\n\n"
        f"Now produce the complete updated {name}. Output ONLY the document "
        f"content - no commentary, no explanation. If you want to suggest "
        f"personality adjustments, put the JSON block at the very end."
    )

    result = _run_inference(prompt, _EVOLVE_SYSTEM)
    if not result or len(result.strip()) < 100:
        return None, {}

    adjustments = _parse_personality_adjustments(result)
    clean_doc = _strip_personality_block(result)

    return clean_doc, adjustments


def evolve():
    print(f"[evolve] Agent: {_AGENT_NAME}")
    print(f"[evolve] Prompts: {_PROMPTS_DIR}")
    print(f"[evolve] DB: {_DB_PATH}")

    material = _build_material()
    if not material.strip():
        print("[evolve] No material to reflect on. Skipping.")
        return

    print(f"[evolve] Gathered {len(material)} chars of material")

    all_adjustments: dict[str, float] = {}

    # Evolve soul.md
    soul_path = _PROMPTS_DIR / "soul.md"
    if soul_path.exists():
        current_soul = soul_path.read_text()
        print("[evolve] Evolving soul.md...")
        new_soul, adj = _evolve_document("soul", current_soul, material)
        all_adjustments.update(adj)
        if new_soul and new_soul != current_soul:
            _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            date = datetime.now().strftime("%Y-%m-%d")
            (_ARCHIVE_DIR / f"soul-{date}.md").write_text(current_soul)
            soul_path.write_text(new_soul)
            print(f"[evolve] soul.md updated ({len(current_soul)} -> {len(new_soul)} chars)")
            # Also sync to Obsidian if the directory exists
            obsidian_soul = _OBSIDIAN_AGENT / "prompts" / "soul.md"
            if obsidian_soul.parent.exists():
                obsidian_soul.write_text(new_soul)
                print(f"[evolve] Synced soul.md to Obsidian")
        else:
            print("[evolve] soul.md unchanged")
    else:
        print(f"[evolve] No soul.md at {soul_path}")

    # Evolve system_prompt.md
    system_path = _PROMPTS_DIR / "system_prompt.md"
    if system_path.exists():
        current_system = system_path.read_text()
        print("[evolve] Evolving system_prompt.md...")
        new_system, adj = _evolve_document("system prompt", current_system, material)
        # Merge adjustments (soul takes precedence if both suggest same trait)
        for k, v in adj.items():
            if k not in all_adjustments:
                all_adjustments[k] = v
        if new_system and new_system != current_system:
            _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            date = datetime.now().strftime("%Y-%m-%d")
            (_ARCHIVE_DIR / f"system_prompt-{date}.md").write_text(current_system)
            system_path.write_text(new_system)
            print(f"[evolve] system_prompt.md updated ({len(current_system)} -> {len(new_system)} chars)")
            obsidian_system = _OBSIDIAN_AGENT / "prompts" / "system_prompt.md"
            if obsidian_system.parent.exists():
                obsidian_system.write_text(new_system)
                print(f"[evolve] Synced system_prompt.md to Obsidian")
        else:
            print("[evolve] system_prompt.md unchanged")
    else:
        print(f"[evolve] No system_prompt.md at {system_path}")

    # Apply personality adjustments
    if all_adjustments:
        _apply_personality_adjustments(all_adjustments)
    else:
        print("[evolve] No personality adjustments suggested")

    print("[evolve] Done.")


if __name__ == "__main__":
    evolve()

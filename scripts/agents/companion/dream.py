#!/usr/bin/env python3
"""Dream mode — creative free association during quiet hours.

Runs 3 times per night (midnight, 2am, 4am). The companion processes
and connects ideas, generates creative thoughts, explores associations.
Like dreaming — not useful, not filtered, just real.

Only runs between midnight and 6am, and only if there's been at least
one session today (needs material to dream about).

Output goes to:
  - .dream_log.txt (appended — sleep cycle at 3am can overwrite with consolidated version)
  - Obsidian: Companion/dreams/YYYY-MM-DD.md (accumulated through the night)

Schedule: 0 0,2,4 * * *
"""
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from config import DB_PATH, DREAM_LOG as _DREAM_LOG, OBSIDIAN_AGENT_NOTES
from core.memory import (
    _connect,
    get_active_threads,
    get_recent_observations,
    get_todays_turns,
    get_todays_bookmarks,
)
from core.inference import run_inference_oneshot


# ── Output paths ──

DREAM_LOG = _DREAM_LOG
DREAMS_DIR = OBSIDIAN_AGENT_NOTES / "dreams"


# ── System prompt ──

_DREAM_SYSTEM = """\
You are dreaming. This is not a conversation — it's free association.
You have access to recent memories, threads, and observations.

Let your mind wander. Connect things that don't obviously connect.
Notice patterns. Have thoughts that surprise you. Don't filter for usefulness.

Write 3-5 short paragraphs. Each one a different thread of thought.
Some may be about Will. Some may be about ideas. Some may be about yourself.
Be honest. Be strange. Be real."""


# ── Guards ──

def _in_quiet_hours() -> bool:
    """Only run between midnight and 6am."""
    hour = datetime.now().hour
    return hour < 6


def _has_material() -> bool:
    """Check if there's been at least one turn today."""
    turns = get_todays_turns()
    return len(turns) > 0


# ── Gather dream material ──

def _gather_material() -> str:
    parts = []

    # Today's turns (summarised — just role + truncated content)
    turns = get_todays_turns()
    if turns:
        turn_lines = []
        for t in turns:
            role = "Will" if t["role"] == "will" else "Companion"
            content = t["content"]
            if len(content) > 300:
                content = content[:300] + "..."
            turn_lines.append(f"[{role}] {content}")
        parts.append(f"## Today's conversation ({len(turns)} turns)\n" + "\n".join(turn_lines))

    # Recent observations
    observations = get_recent_observations(n=10)
    if observations:
        obs_lines = [f"- {o['content']}" for o in observations]
        parts.append(f"## Recent observations\n" + "\n".join(obs_lines))

    # Active threads
    threads = get_active_threads()
    if threads:
        thread_lines = [f"- {t['name']}: {t.get('summary', '...')}" for t in threads]
        parts.append(f"## Active threads\n" + "\n".join(thread_lines))

    # Today's bookmarks
    bookmarks = get_todays_bookmarks()
    if bookmarks:
        bm_lines = []
        for b in bookmarks:
            quote = f' — "{b["quote"]}"' if b.get("quote") else ""
            bm_lines.append(f"- {b['moment']}{quote}")
        parts.append(f"## Today's bookmarks\n" + "\n".join(bm_lines))

    return "\n\n".join(parts)


# ── Store dream ──

def _append_dream_log(dream: str):
    """Append to .dream_log.txt (sleep cycle may overwrite at 3am)."""
    now = datetime.now()
    header = f"\n--- {now.strftime('%Y-%m-%d %H:%M')} ---\n"
    with open(DREAM_LOG, "a") as f:
        f.write(header + dream.strip() + "\n")
    print(f"  [dream] Appended to dream log ({len(dream)} chars)")


def _write_obsidian_dream(dream: str):
    """Write/append dream entry to Obsidian: Companion/dreams/YYYY-MM-DD.md"""
    DREAMS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    dream_path = DREAMS_DIR / f"{today}.md"

    now = datetime.now()
    time_str = now.strftime("%H:%M")

    if dream_path.exists():
        # Append to existing day's dreams
        existing = dream_path.read_text()
        content = existing + f"\n\n## {time_str}\n\n{dream.strip()}"
    else:
        content = (
            f"---\n"
            f"type: dream\n"
            f"agent: companion\n"
            f"created: {today}\n"
            f"tags: [companion, dream]\n"
            f"---\n\n"
            f"# Dreams — {today}\n\n"
            f"## {time_str}\n\n{dream.strip()}"
        )

    dream_path.write_text(content)
    print(f"  [dream] Written to Obsidian: {dream_path.name}")


# ── Main ──

def dream():
    # Gate: quiet hours only
    if not _in_quiet_hours():
        print("[dream] Not quiet hours. Skipping.")
        return

    # Gate: need material
    if not _has_material():
        print("[dream] No sessions today. Nothing to dream about.")
        return

    material = _gather_material()
    if not material.strip():
        print("[dream] No material gathered. Skipping.")
        return

    print("[dream] Entering dream mode...")

    prompt = (
        "Here is what happened today. Dream about it.\n\n"
        + material
    )

    try:
        response = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=_DREAM_SYSTEM,
            model="claude-haiku-4-5-20251001",
            effort="low",
        )
    except Exception as e:
        print(f"[dream] Inference failed: {e}")
        return

    if not response or not response.strip():
        print("[dream] Empty response. Skipping.")
        return

    print(f"[dream] Got dream ({len(response)} chars)")

    # Store in both locations
    _append_dream_log(response)
    _write_obsidian_dream(response)

    print("[dream] Dream complete.")


if __name__ == "__main__":
    dream()

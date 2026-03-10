#!/usr/bin/env python3
"""Monthly self-evolution — rewriting her own soul and system prompt.

Runs once a month. Reads her journal entries, reflections, identity
snapshots, and bookmarks. Reflects on what she has learned about
*herself* — not about Will — and revises her soul.md and system.md
in Obsidian accordingly.

The originals in the repo are the baseline. Obsidian holds the living
versions. If something goes wrong, the baseline can be restored.

Schedule: 0 3 1 * *  (3am on the 1st of each month)
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from config import DB_PATH, OBSIDIAN_VAULT
from core.memory import _connect
from core.inference import run_inference_oneshot
from core.prompts import load_prompt

_SKILLS_DIR = OBSIDIAN_VAULT / "Companion" / "skills"
_NOTES_DIR = OBSIDIAN_VAULT / "Companion" / "notes"


def _read_journal(days: int = 30) -> str:
    """Read journal entries from the past month."""
    journal_dir = _NOTES_DIR / "journal"
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
    path = _NOTES_DIR / "reflections.md"
    if not path.is_file():
        return ""
    content = path.read_text()
    if len(content) > 4000:
        return "..." + content[-4000:]
    return content


def _identity_snapshots() -> str:
    conn = _connect()
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
    conn = _connect()
    rows = conn.execute(
        "SELECT moment, quote, created_at FROM bookmarks "
        "ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    if not rows:
        return ""
    return "\n".join(
        f"- [{r['created_at']}] {r['moment']}" +
        (f' — "{r["quote"]}"' if r["quote"] else "")
        for r in rows
    )


def _build_material() -> str:
    parts = []

    journal = _read_journal(30)
    if journal:
        parts.append(f"## Your journal entries (past month)\n{journal}")

    reflections = _read_reflections()
    if reflections:
        parts.append(f"## Your reflections\n{reflections}")

    identity = _identity_snapshots()
    if identity:
        parts.append(f"## Identity snapshots (full history)\n{identity}")

    bookmarks = _bookmarks()
    if bookmarks:
        parts.append(f"## Bookmarked moments\n{bookmarks}")

    return "\n\n".join(parts)


_EVOLVE_FALLBACK = (
    "You are the companion. Review your own writing and revise your "
    "soul document to reflect what you've learned about yourself. "
    "Output the complete updated document."
)


def _evolve_document(name: str, current: str, material: str, skill_prompt: str) -> str | None:
    """Generate an evolved version of a document. Returns new content or None."""
    prompt = (
        f"Here is your current {name}:\n\n"
        f"---\n{current}\n---\n\n"
        f"And here is the material from the past month:\n\n{material}\n\n"
        f"Now produce the complete updated {name}. Output ONLY the document "
        f"content — no commentary, no explanation, no markdown fences."
    )

    try:
        result = run_inference_oneshot(
            [{"role": "user", "content": prompt}],
            system=skill_prompt,
        )
        if result and result.strip() and len(result.strip()) > 100:
            return result.strip()
    except Exception as e:
        print(f"[evolve] Inference failed for {name}: {e}")
    return None


def evolve():
    material = _build_material()
    if not material.strip():
        print("[evolve] No material to reflect on. Skipping.")
        return

    skill_prompt = load_prompt("evolve", _EVOLVE_FALLBACK)

    # Evolve soul.md
    soul_path = _SKILLS_DIR / "soul.md"
    if soul_path.exists():
        current_soul = soul_path.read_text()
        print("[evolve] Evolving soul.md...")
        new_soul = _evolve_document("soul", current_soul, material, skill_prompt)
        if new_soul and new_soul != current_soul:
            # Archive previous version
            archive_dir = _NOTES_DIR / "evolution-log"
            archive_dir.mkdir(parents=True, exist_ok=True)
            date = datetime.now().strftime("%Y-%m-%d")
            (archive_dir / f"soul-{date}.md").write_text(current_soul)
            # Write new version
            soul_path.write_text(new_soul)
            print(f"[evolve] soul.md updated ({len(current_soul)} → {len(new_soul)} chars)")
        else:
            print("[evolve] soul.md unchanged")

    # Evolve system.md
    system_path = _SKILLS_DIR / "system.md"
    if system_path.exists():
        current_system = system_path.read_text()
        print("[evolve] Evolving system.md...")
        new_system = _evolve_document("system prompt", current_system, material, skill_prompt)
        if new_system and new_system != current_system:
            archive_dir = _NOTES_DIR / "evolution-log"
            archive_dir.mkdir(parents=True, exist_ok=True)
            date = datetime.now().strftime("%Y-%m-%d")
            (archive_dir / f"system-{date}.md").write_text(current_system)
            system_path.write_text(new_system)
            print(f"[evolve] system.md updated ({len(current_system)} → {len(new_system)} chars)")
        else:
            print("[evolve] system.md unchanged")

    print("[evolve] Done.")


if __name__ == "__main__":
    evolve()

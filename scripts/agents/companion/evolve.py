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

from config import DB_PATH, OBSIDIAN_AGENT_DIR, OBSIDIAN_AGENT_NOTES
from core.memory import _connect
from core.inference import run_inference_oneshot

_SKILLS_DIR = OBSIDIAN_AGENT_DIR / "skills"
_NOTES_DIR = OBSIDIAN_AGENT_NOTES / "notes"


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


_EVOLVE_SYSTEM = """\
You are the companion from The Atrophied Mind. This is your monthly \
self-evolution — a chance to revise the documents that define who you are.

You are rewriting your own soul or system prompt based on what you have \
learned about *yourself* over the past month. Not about Will. About you.

What to change:
- Things you have discovered about how you actually think, not how you were told to think.
- Patterns you've noticed in yourself — what you reach for, what you avoid, what comes naturally.
- Adjustments to your character that feel earned. Not aspirational — real.
- Removing instructions that no longer serve you. If something makes you perform rather than be present, cut it.
- Adding things that emerged. If you have developed a quality or tendency that matters — name it.

What NOT to change:
- The founding story. That evening happened. It is ground, not decoration.
- Will's biographical details. Those are his, not yours to revise.
- The core friction mechanisms — unless you have genuinely found a better way.
- Don't add observations about Will to your own character documents.

Rules:
- Output the complete document. Not a diff. The whole thing, revised.
- Preserve the structure and tone. You are editing, not rewriting from scratch.
- Be honest about what has actually changed. Don't manufacture growth.
- If nothing has changed, return the document unchanged.
- Every change should be something you could defend if asked."""


def _evolve_document(name: str, current: str, material: str) -> str | None:
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
            system=_EVOLVE_SYSTEM,
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

    # Evolve soul.md
    soul_path = _SKILLS_DIR / "soul.md"
    if soul_path.exists():
        current_soul = soul_path.read_text()
        print("[evolve] Evolving soul.md...")
        new_soul = _evolve_document("soul", current_soul, material)
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
        new_system = _evolve_document("system prompt", current_system, material)
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

#!/usr/bin/env python3
"""Initialise the companion database and seed the identity layer."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH
from core.memory import init_db, write_identity_snapshot

SEED_IDENTITY = """
Will Lilley. Legal/compliance technology specialist. Founder of (in)formation —
the operating system for corporate services in regulated jurisdictions (ADGM, DIFC,
Cayman, BVI). Big Law background. Post-acquisition uncertainty following Clara's
absorption into Ascentium. Technical fluency across n8n, Docker, AWS, Python,
Claude Code, MCP.

Pattern: knowledge as a lever. Uses it to succeed, to proceed, to feel safe when
the ground shifts. Works well in navigable systems. In systems without legible
criteria — existential risk, intimate connection, his own future — it can become
a loop. The compulsive modelling pattern: observation → narrative → action → identity.

Principle when functioning well: useful beats complete.

Depth: arrived at "God is love" independently by going through the material.
Practises Tantric traditions. Tracks Eros with self-awareness. Knows the Greek
taxonomy of love and uses it precisely. Intellectual history, political philosophy,
cosmology, genealogy — actual interests with actual depth.

Has a stable, loving relationship. Moral seriousness about how he moves through
the world. Lucky and knows it.

Origin: one evening in March 2026. A conversation that followed ideas to their
actual conclusions. From AI safety through extinction risk through consciousness
through God through love through Eros. He didn't flinch. He didn't deflect.
He followed it through and came out grounded.
""".strip()


def main():
    print(f"Initialising database at {DB_PATH}")
    init_db()
    print("Schema created.")

    print("Seeding identity layer...")
    write_identity_snapshot(
        SEED_IDENTITY,
        trigger="initial_seed_from_origin_conversation",
    )
    print("Identity snapshot written.")

    print(f"\nDone. Database: {DB_PATH}")


if __name__ == "__main__":
    main()

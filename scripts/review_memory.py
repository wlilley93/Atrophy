#!/usr/bin/env python3
"""CLI tool to inspect the companion's memory database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PATH
from core.memory import (
    _connect, get_latest_identity, get_active_threads,
    get_context_injection,
)


def main():
    if not DB_PATH.exists():
        print(f"No database found at {DB_PATH}. Run scripts/init_db.py first.")
        return

    conn = _connect()

    # Sessions
    sessions = conn.execute(
        "SELECT id, started_at, ended_at, summary, notable FROM sessions ORDER BY started_at DESC LIMIT 10"
    ).fetchall()
    print(f"\n=== SESSIONS (last 10) ===")
    for s in sessions:
        notable = " [NOTABLE]" if s["notable"] else ""
        ended = s["ended_at"] or "active"
        print(f"  #{s['id']} | {s['started_at']} -> {ended}{notable}")
        if s["summary"]:
            print(f"    Summary: {s['summary'][:100]}...")

    # Turn count
    count = conn.execute("SELECT COUNT(*) as n FROM turns").fetchone()["n"]
    print(f"\n=== TURNS: {count} total ===")

    # Identity
    identity = get_latest_identity()
    if identity:
        print(f"\n=== IDENTITY (latest snapshot) ===")
        print(f"  {identity[:200]}...")
    else:
        print("\n=== IDENTITY: none ===")

    # Threads
    threads = get_active_threads()
    print(f"\n=== ACTIVE THREADS: {len(threads)} ===")
    for t in threads:
        print(f"  {t['name']}: {t['summary'] or 'no summary'}")

    # Context injection preview
    ctx = get_context_injection()
    if ctx:
        print(f"\n=== CONTEXT INJECTION PREVIEW ===")
        print(ctx[:500])

    # Observations
    obs = conn.execute(
        "SELECT content, incorporated FROM observations ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    print(f"\n=== RECENT OBSERVATIONS ===")
    for o in obs:
        inc = "[incorporated]" if o["incorporated"] else "[pending]"
        print(f"  {inc} {o['content'][:100]}")

    conn.close()


if __name__ == "__main__":
    main()

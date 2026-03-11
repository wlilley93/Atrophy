#!/usr/bin/env python3
"""Regenerate all embeddings for existing memory rows.

Run this once after initial setup, or periodically to ensure all rows
have up-to-date embeddings. Safe to run multiple times - it overwrites
existing embeddings.

Usage:
    python scripts/reindex.py              # reindex all tables
    python scripts/reindex.py observations # reindex just observations
    python scripts/reindex.py summaries turns  # reindex specific tables
"""
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.memory import init_db
from core.vector_search import reindex, SEARCHABLE_TABLES


def main():
    # Ensure schema is up to date (runs migrations)
    init_db()

    tables = sys.argv[1:] if len(sys.argv) > 1 else None

    if tables:
        unknown = [t for t in tables if t not in SEARCHABLE_TABLES]
        if unknown:
            print(f"Unknown tables: {', '.join(unknown)}")
            print(f"Available: {', '.join(SEARCHABLE_TABLES.keys())}")
            sys.exit(1)
        print(f"Reindexing: {', '.join(tables)}")
    else:
        print(f"Reindexing all tables: {', '.join(SEARCHABLE_TABLES.keys())}")

    t0 = time.time()

    if tables:
        for table in tables:
            reindex(table=table)
    else:
        reindex()

    elapsed = time.time() - t0
    print(f"\nReindex complete in {elapsed:.1f}s")


if __name__ == "__main__":
    main()

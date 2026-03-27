#!/usr/bin/env python3
"""WorldMonitor polling cron job for General Montgomery.

Usage:
    python worldmonitor_poll.py --tier fast|medium|slow

Polls the WorldMonitor API for the specified tier, detects significant changes,
writes observations to Montgomery's memory database, and ingests structured
data into the ontology knowledge graph.
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add the mcp directory to the path so we can import WorldMonitorClient
_MCP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp")
sys.path.insert(0, os.path.abspath(_MCP_DIR))

# Add shared scripts to path for ontology_ingest
_SHARED_DIR = Path(__file__).resolve().parent.parent / "shared"
_PERSONAL_SHARED = Path.home() / ".atrophy" / "scripts" / "agents" / "shared"
for _p in [str(_PERSONAL_SHARED), str(_SHARED_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from worldmonitor_server import WorldMonitorClient  # noqa: E402

# Paths
_ATROPHY_DIR = Path.home() / ".atrophy"
_CACHE_DB = _ATROPHY_DIR / "worldmonitor_cache.db"
_MEMORY_DB = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "memory.db"
_LOG_DIR = _ATROPHY_DIR / "logs" / "general_montgomery"


def _setup_logging(tier: str) -> logging.Logger:
    """Configure logging to file and stderr."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOG_DIR / f"worldmonitor_{tier}.log"

    logger = logging.getLogger(f"worldmonitor_poll.{tier}")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # File handler
        fh = logging.FileHandler(log_path)
        fh.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        # Stderr handler
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.WARNING)
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    return logger


def file_observation(db_path: str, change: dict) -> None:
    """Write a WorldMonitor change as an observation to Montgomery's memory DB."""
    conn = sqlite3.connect(db_path)
    content = f"[INTEL/WM/{change['domain']}] {change['summary']}"
    conn.execute(
        "INSERT INTO observations (content, created_at) VALUES (?, ?)",
        (content, change.get("timestamp", datetime.now(timezone.utc).isoformat())),
    )
    conn.commit()
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll WorldMonitor for a given tier")
    parser.add_argument(
        "--tier",
        choices=["fast", "medium", "slow"],
        required=True,
        help="Which polling tier to run: fast, medium, or slow",
    )
    args = parser.parse_args()
    tier: str = args.tier

    logger = _setup_logging(tier)
    logger.info("Starting WorldMonitor poll for tier: %s", tier)

    # Ensure cache dir exists
    _ATROPHY_DIR.mkdir(parents=True, exist_ok=True)

    client = WorldMonitorClient(cache_db=str(_CACHE_DB))

    try:
        changes = client.poll_tier(tier)
    except Exception as exc:
        logger.error("poll_tier(%s) failed: %s", tier, exc)
        sys.exit(1)

    logger.info("poll_tier(%s) returned %d significant change(s)", tier, len(changes))

    if not changes:
        logger.info("No significant changes - nothing to file")
        return

    memory_db = str(_MEMORY_DB)
    _MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)

    filed = 0
    for change in changes:
        try:
            file_observation(memory_db, change)
            logger.info(
                "Filed observation: [INTEL/WM/%s] %s",
                change.get("domain", "UNKNOWN"),
                change.get("summary", ""),
            )
            filed += 1
        except Exception as exc:
            logger.error(
                "Failed to file observation for domain %s: %s",
                change.get("domain", "UNKNOWN"),
                exc,
            )

    logger.info("Done. Filed %d/%d observation(s)", filed, len(changes))

    # Ingest structured data into the ontology knowledge graph.
    # Each change carries the raw API response and endpoint - the ingestor
    # routes to typed handlers (flights, ACLED, AIS, jamming, etc.).
    try:
        from ontology_ingest import ingest_worldmonitor_response
        ingested = 0
        for change in changes:
            endpoint = change.get("endpoint", "")
            raw_data = change.get("raw_data")
            if not endpoint or raw_data is None:
                continue
            try:
                result = ingest_worldmonitor_response(
                    endpoint,
                    raw_data,
                    source=f"worldmonitor:{change.get('domain', 'unknown')}",
                )
                if result and result.get("objects_upserted", 0) > 0:
                    ingested += result["objects_upserted"]
            except Exception as exc:
                logger.warning("Ontology ingest failed for %s: %s", endpoint, exc)
        if ingested:
            logger.info("Ontology: ingested %d objects from WorldMonitor data", ingested)
    except ImportError:
        logger.debug("ontology_ingest not available - skipping knowledge graph update")
    except Exception as exc:
        logger.warning("Ontology ingestion failed (non-fatal): %s", exc)


if __name__ == "__main__":
    main()

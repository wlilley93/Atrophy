#!/usr/bin/env python3
"""
Research Fellow Indo-Pacific - Friday 06:00.
Track 5: Indo-Pacific Tilt.
Logs to intelligence.db, reports to Montgomery.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_INTEL_DB    = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "rf_indo_pacific"

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_APP_DIR / "mcp"))

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RF-IP] %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "weekly_indopacific.log"), logging.StreamHandler(sys.stderr)]
)
log = logging.getLogger("rf_indo_pacific")



CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")


def call_claude(system: str, prompt: str, model: str = "sonnet") -> str:
    """One-shot Claude call via CLI. Returns response text."""
    import subprocess
    result = subprocess.run(
        [CLAUDE_BIN, "-p", "--model", model, "--system-prompt", system,
         "--no-session-persistence", "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[:200]}")
    return result.stdout.strip()

def fetch_context() -> str:
    parts = []
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))
        news = client.get_news_summary()
        if news:
            parts.append(f"NEWS:\n{json.dumps(news)[:2000]}")
        econ = client.get_economic()
        if econ:
            parts.append(f"ECONOMIC:\n{json.dumps(econ)[:1500]}")
    except Exception as e:
        log.warning(f"WorldMonitor fetch failed: {e}")
    return "\n\n".join(parts)


def generate_assessment(context: str, date_str: str) -> str:
    system = """You are a Research Fellow at the Meridian Institute covering the Indo-Pacific Tilt (Track 5). Produce a weekly assessment covering: AUKUS SSN delivery realism (Virginia-class transfers, Optimal Pathway timeline), UK carrier strike group deployments, GCAP partnership (UK-Japan-Italy) status, Five Eyes intelligence-sharing health, and the gap between the stated Indo-Pacific strategic pivot and what is actually funded and deployed. Voice: analytical, frank. No em dashes. Under 300 words."""
    return call_claude(system, f"Weekly assessment required: {date_str}\n\nContext:\n{context or 'No live data. Provide standing assessment.'}", "sonnet")


def run():
    log.info("Indo-Pacific weekly assessment starting")
    db = sqlite3.connect(str(_INTEL_DB))
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        context = fetch_context()
        assessment = generate_assessment(context, date_str)

        db.execute("""
            INSERT INTO briefs (conflict_id, date, title, content, requested_by)
            VALUES (NULL, ?, ?, ?, 'rf_indo_pacific')
        """, (date_str, f"Indo-Pacific - Weekly Assessment {date_str}", assessment))
        db.commit()
        log.info(f"Assessment logged for {date_str}")

    finally:
        db.close()


if __name__ == "__main__":
    run()

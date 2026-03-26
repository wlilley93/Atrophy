#!/usr/bin/env python3
"""
Research Fellow European Security - Thursday 06:00.
Track 2: European Security Architecture.
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
_LOG_DIR     = _ATROPHY_DIR / "logs" / "rf_european_security"

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_APP_DIR / "mcp"))

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RF-EU] %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "weekly_security.log"), logging.StreamHandler(sys.stderr)]
)
log = logging.getLogger("rf_european_security")



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

        # News digest - pull categories relevant to European security
        digest_data, _ = client.fetch_cached("api/news/v1/list-feed-digest")
        if digest_data:
            cats = digest_data.get("categories", {})
            if not cats and isinstance(digest_data.get("data"), dict):
                cats = digest_data["data"].get("categories", {})
            headlines = []
            for cat in ["europe", "intel", "thinktanks", "politics"]:
                cat_val = cats.get(cat, {})
                items = cat_val.get("items", cat_val) if isinstance(cat_val, dict) else cat_val
                for a in (items or [])[:4]:
                    title = a.get("title", "")
                    source = a.get("source", "")
                    if title:
                        headlines.append(f"[{source}] {title}")
            if headlines:
                parts.append("NEWS:\n" + "\n".join(headlines[:20]))

        # Energy prices - relevant to European economic security posture
        econ_data, _ = client.fetch_cached("api/economic/v1/get-energy-prices")
        if econ_data:
            parts.append(f"ENERGY PRICES:\n{json.dumps(econ_data)[:800]}")

    except Exception as e:
        log.warning(f"WorldMonitor fetch failed: {e}")
    return "\n\n".join(parts)


def generate_assessment(context: str, date_str: str) -> str:
    system = """You are a Research Fellow at the Meridian Institute covering European Security Architecture (Track 2). Produce a weekly assessment covering: NATO compliance status across key member states, Lancaster House Treaty (UK-France) status, European rearmament momentum and gaps, UK's post-Brexit security position, and the current state of Ukraine settlement scenario planning. Voice: analytical, frank. No em dashes. Under 300 words."""
    return call_claude(system, f"Weekly assessment required: {date_str}\n\nContext:\n{context or 'No live data. Provide standing assessment.'}", "sonnet")


def run():
    log.info("European Security weekly assessment starting")
    db = sqlite3.connect(str(_INTEL_DB))
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        context = fetch_context()
        assessment = generate_assessment(context, date_str)

        db.execute("""
            INSERT INTO briefs (conflict_id, date, title, content, requested_by)
            VALUES (NULL, ?, ?, ?, 'rf_european_security')
        """, (date_str, f"European Security - Weekly Assessment {date_str}", assessment))
        db.commit()
        log.info(f"Assessment logged for {date_str}")

    finally:
        db.close()


if __name__ == "__main__":
    run()

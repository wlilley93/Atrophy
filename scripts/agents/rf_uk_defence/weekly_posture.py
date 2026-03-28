#!/usr/bin/env python3
"""
Research Fellow UK Defence - Wednesday 06:00.
Track 1: UK Defence Posture.
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
_LOG_DIR     = _ATROPHY_DIR / "logs" / "rf_uk_defence"

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_APP_DIR / "mcp"))

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RF-UKD] %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "weekly_posture.log"), logging.StreamHandler(sys.stderr)]
)
log = logging.getLogger("rf_uk_defence")



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

        # News digest - pull categories relevant to UK defence
        digest_data, _ = client.fetch_cached("api/news/v1/list-feed-digest")
        if digest_data:
            cats = digest_data.get("categories", {})
            if not cats and isinstance(digest_data.get("data"), dict):
                cats = digest_data["data"].get("categories", {})
            headlines = []
            for cat in ["intel", "gov", "europe", "politics"]:
                cat_val = cats.get(cat, {})
                items = cat_val.get("items", cat_val) if isinstance(cat_val, dict) else cat_val
                for a in (items or [])[:5]:
                    title = a.get("title", "")
                    source = a.get("source", "")
                    if title:
                        headlines.append(f"[{source}] {title}")
            if headlines:
                parts.append("NEWS:\n" + "\n".join(headlines[:20]))

        # BIS policy rates - useful for defence budget context
        econ_data, _ = client.fetch_cached("api/economic/v1/get-bis-policy-rates")
        if econ_data:
            parts.append(f"POLICY RATES:\n{json.dumps(econ_data)[:800]}")

    except Exception as e:
        log.warning(f"WorldMonitor fetch failed: {e}")
    return "\n\n".join(parts)


def generate_assessment(context: str, date_str: str) -> str:
    system = """You are a Research Fellow at the Meridian Institute covering UK Defence Posture (Track 1). Produce a weekly assessment covering: procurement programme status (Type 26 frigate, F-35B, GCAP/Tempest, AUKUS SSN), force structure gaps, what the 2.5% GDP commitment actually funds vs stated ambition, and one item from the past week that reveals something real about UK defence readiness. Voice: analytical, frank. No em dashes. Under 300 words.

After your main assessment, add a section:

## Next 7 Days
List 3-5 dated events or developments expected in the next 7 days for your area.
Each line MUST follow this exact format:
- YYYY-MM-DD | CONFIDENCE | Event description (one sentence)

CONFIDENCE is one of: CONFIRMED, HIGH, MEDIUM, SPECULATIVE
CONFIRMED = scheduled event with fixed date. HIGH = very likely based on pattern/intel. MEDIUM = probable. SPECULATIVE = possible but uncertain."""
    return call_claude(system, f"Weekly assessment required: {date_str}\n\nContext:\n{context or 'No live data. Provide standing assessment.'}", "sonnet")


def run():
    log.info("UK Defence weekly assessment starting")
    db = sqlite3.connect(str(_INTEL_DB))
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        context = fetch_context()
        assessment = generate_assessment(context, date_str)

        db.execute("""
            INSERT INTO briefs (conflict_id, date, title, content, requested_by)
            VALUES (NULL, ?, ?, ?, 'rf_uk_defence')
        """, (date_str, f"UK Defence - Weekly Assessment {date_str}", assessment))
        db.commit()
        log.info(f"Assessment logged for {date_str}")

    finally:
        db.close()


if __name__ == "__main__":
    run()

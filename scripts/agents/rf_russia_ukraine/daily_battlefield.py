#!/usr/bin/env python3
"""
Research Fellow Russia/Ukraine - Daily battlefield summary.
Runs 06:00 daily. Logs to intelligence.db, flags significant changes to Montgomery.
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
_AGENT_JSON  = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "agent.json"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "rf_russia_ukraine"

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_APP_DIR / "mcp"))
from shared.credentials import load_telegram_credentials

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RF-RU] %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "daily_battlefield.log"), logging.StreamHandler(sys.stderr)]
)
log = logging.getLogger("daily_battlefield")

UKRAINE_CONFLICT_SLUG = "ukraine"



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

def load_credentials():
    with open(_AGENT_JSON) as f:
        d = json.load(f)
    return *load_telegram_credentials("rf_russia_ukraine")


def fetch_ukraine_data() -> str:
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))
        conflicts, _wm_delta = client.fetch_cached("api/conflict/v1/list-acled-events")
        news, _news_delta = client.fetch_cached("api/news/v1/digest")
        parts = []
        if conflicts:
            parts.append(f"CONFLICTS DATA:\n{json.dumps(conflicts)[:2500]}")
        if news:
            parts.append(f"NEWS:\n{json.dumps(news)[:2000]}")
        return "\n\n".join(parts)
    except Exception as e:
        log.warning(f"WorldMonitor fetch failed: {e}")
        return ""


def generate_summary(context: str) -> str:
    system = """You are a Research Fellow at the Meridian Institute specialising in Russia-Ukraine.
Produce a terse daily battlefield summary: frontline status, Black Sea posture, notable strikes or moves,
UK/Western weapons supply status, and one sentence on Russian hybrid operations.
Voice: analytical, factual. No em dashes. Under 300 words."""
    return call_claude(system, f"Daily summary required - {datetime.now().strftime('%Y-%m-%d')}\n\n{context}", "sonnet")


def run():
    log.info("Daily battlefield summary starting")
    db = sqlite3.connect(str(_INTEL_DB))

    try:
        c = db.cursor()
        c.execute("SELECT id FROM conflicts WHERE slug = ?", (UKRAINE_CONFLICT_SLUG,))
        row = c.fetchone()
        conflict_id = row[0] if row else None

        context = fetch_ukraine_data()
        summary = generate_summary(context)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        db.execute("""
            INSERT INTO briefs (conflict_id, date, title, content, requested_by)
            VALUES (?, ?, ?, ?, 'rf_russia_ukraine')
        """, (conflict_id, date_str, f"Ukraine Battlefield Summary - {date_str}", summary))
        db.commit()
        log.info("Battlefield summary logged to intelligence.db")

        # Push channel state to WorldMonitor
        try:
            from shared.channel_push import push_channel

            # Derive markers from ACLED conflict data if available
            markers = []
            try:
                if context:
                    import re
                    # Context contains raw JSON snippets - try to extract lat/lon from conflicts
                    for match in re.finditer(r'"latitude"\s*:\s*"?([0-9.-]+)"?\s*,\s*"longitude"\s*:\s*"?([0-9.-]+)"?', context):
                        lat, lon = float(match.group(1)), float(match.group(2))
                        markers.append({"lat": lat, "lon": lon, "label": "ACLED event"})
                        if len(markers) >= 20:
                            break
            except Exception:
                pass

            summary_line = summary.split("\n")[0] if summary else ""
            push_channel("rf_russia_ukraine", {
                "agent": "rf_russia_ukraine",
                "display_name": "RF Russia/Ukraine",
                "alert_level": "elevated",
                "briefing": {
                    "title": f"Ukraine Battlefield Summary - {date_str}",
                    "summary": summary_line,
                    "body_md": summary,
                    "sources": ["ACLED", "WorldMonitor"],
                },
                "map": {
                    "center": [48.5, 35.0],
                    "zoom": 6,
                    "layers": ["acled-events", "thermal-escalations"],
                    "regions": ["UA", "RU"],
                    "markers": markers,
                },
            })
        except Exception:
            pass  # channel push is best-effort

    finally:
        db.close()


if __name__ == "__main__":
    run()

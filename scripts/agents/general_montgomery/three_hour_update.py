#!/usr/bin/env python3
"""
Three-Hour Update - Regular situational awareness check-in.

Every 3 hours. Pulls live WorldMonitor data, checks for new signals,
and sends a brief Montgomery-voice update to Telegram.

Not a full brief - a situation check. What has moved. What is the posture.
If nothing material has changed, says so in one sentence.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.credentials import load_telegram_credentials

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON  = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB    = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "general_montgomery"

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
_MCP_DIR = _APP_DIR / "mcp"
sys.path.insert(0, str(_MCP_DIR))

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [3hUpdate] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "three_hour_update.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("three_hour_update")

CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")

SYSTEM_PROMPT = """You are General Montgomery producing a full situational brief.

Structure it as a proper intelligence brief - the same weight as the morning digest:

SITUATION (1 paragraph) - The defining development of the past 3 hours. What has moved and why it matters. If nothing has moved, state current posture and what is being watched.

ACTIVE THEATRES - One short paragraph per theatre with live activity. Cover only theatres where something is actually happening. Name the development, the actor, the implication. Do not pad with standing assessment if nothing has changed.

SIGNALS - Any new intelligence signals, AIS anomalies, OREF activity, military flights, or GPS jamming worth noting. One sentence each.

ECONOMIC POSTURE - Energy price movements or sanctions signals if material. Skip if nothing to report.

WATCH - Two or three specific developments to monitor in the next update window. Named, specific, falsifiable.

Voice: clipped, precise, no hedging, no em dashes, hyphens only. This is a full brief not a check-in. Give it weight. Under 500 words."""


def call_claude(system: str, prompt: str, model: str = "sonnet") -> str:
    result = subprocess.run(
        [CLAUDE_BIN, "-p", "--model", model, "--system-prompt", system,
         "--no-session-persistence", "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[:200]}")
    return result.stdout.strip()


def fetch_live_data() -> dict:
    """Pull full WorldMonitor snapshot for brief generation."""
    data = {}
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(
            cache_db=str(Path.home() / ".atrophy" / "worldmonitor_cache.db")
        )

        alerts, alerts_delta = client.fetch_cached("api/oref-alerts")
        if alerts:
            data["oref_alerts"] = {"raw": alerts, "delta": alerts_delta}

        flights, flights_delta = client.fetch_cached("api/military-flights")
        if flights:
            data["military_flights"] = {"raw": flights, "delta": flights_delta}

        jamming, jam_delta = client.fetch_cached("api/gpsjam")
        if jamming:
            data["gps_jamming"] = {"raw": jamming, "delta": jam_delta}

        ais, ais_delta = client.fetch_cached("api/ais-snapshot")
        if ais:
            data["ais"] = {"raw": ais, "delta": ais_delta}

        conflicts, conf_delta = client.fetch_cached("api/conflict/v1/list-acled-events")
        if conflicts:
            data["conflict_events"] = {"raw": conflicts, "delta": conf_delta}

        economic, econ_delta = client.fetch_cached("api/economic/v1/get-energy-prices")
        if economic:
            data["energy_prices"] = {"raw": economic, "delta": econ_delta}

        trade, trade_delta = client.fetch_cached("api/trade/v1/get-trade-restrictions")
        if trade:
            data["trade"] = {"raw": trade, "delta": trade_delta}

        news, news_delta = client.fetch_cached("api/news/v1/digest")
        if news:
            data["news"] = {"raw": news, "delta": news_delta}

    except Exception as e:
        log.warning(f"WorldMonitor fetch failed: {e}")
        data["wm_error"] = str(e)

    return data


def get_recent_signals(db: sqlite3.Connection) -> list[dict]:
    """Pull signals logged in the past 3 hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    cur = db.cursor()
    cur.execute("""
        SELECT agent, signal_type, title, severity, created_at
        FROM signals
        WHERE created_at >= ?
        ORDER BY created_at DESC
        LIMIT 10
    """, (cutoff,))
    return [
        {"agent": r[0], "type": r[1], "title": r[2], "severity": r[3]}
        for r in cur.fetchall()
    ]


def get_recent_flash_reports(db: sqlite3.Connection) -> list[str]:
    """Pull any flash reports filed in the past 3 hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    cur = db.cursor()
    cur.execute("""
        SELECT title FROM briefs
        WHERE requested_by = 'flash_report'
        AND created_at >= ?
        ORDER BY created_at DESC
        LIMIT 5
    """, (cutoff,))
    return [r[0] for r in cur.fetchall()]


def send_telegram(token: str, chat_id: str, text: str):
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")


def main():
    log.info("Three-hour update starting")

    with open(_AGENT_JSON) as f:
        cfg = json.load(f)

    db = sqlite3.connect(str(_INTEL_DB))

    try:
        live = fetch_live_data()
        signals = get_recent_signals(db)
        flash_reports = get_recent_flash_reports(db)
        now_str = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

        def truncate(obj, n=2000):
            return json.dumps(obj)[:n] if obj else ""

        context_parts = [f"TIME: {now_str}\n"]

        if live.get("oref_alerts"):
            context_parts.append(f"OREF ALERTS (delta {live['oref_alerts']['delta']}):\n{truncate(live['oref_alerts']['raw'])}")

        if live.get("military_flights"):
            context_parts.append(f"MILITARY FLIGHTS (delta {live['military_flights']['delta']}):\n{truncate(live['military_flights']['raw'])}")

        if live.get("gps_jamming"):
            context_parts.append(f"GPS JAMMING:\n{truncate(live['gps_jamming']['raw'], 1000)}")

        if live.get("ais"):
            context_parts.append(f"AIS SNAPSHOT (delta {live['ais']['delta']}):\n{truncate(live['ais']['raw'])}")

        if live.get("conflict_events"):
            context_parts.append(f"CONFLICT EVENTS (delta {live['conflict_events']['delta']}):\n{truncate(live['conflict_events']['raw'])}")

        if live.get("energy_prices"):
            context_parts.append(f"ENERGY PRICES (delta {live['energy_prices']['delta']}):\n{truncate(live['energy_prices']['raw'], 1000)}")

        if live.get("trade"):
            context_parts.append(f"TRADE RESTRICTIONS:\n{truncate(live['trade']['raw'], 800)}")

        if live.get("news"):
            context_parts.append(f"NEWS DIGEST:\n{truncate(live['news']['raw'])}")

        if signals:
            sig_lines = [f"  [{s['severity']}] {s['agent']}: {s['title']}" for s in signals[:5]]
            context_parts.append(f"NEW SIGNALS (past 3 hrs):\n" + "\n".join(sig_lines))

        if flash_reports:
            context_parts.append(f"FLASH REPORTS FILED: {', '.join(flash_reports)}")

        if live.get("wm_error"):
            context_parts.append(f"WORLDMONITOR UNAVAILABLE: {live['wm_error']}")

        context = "\n\n".join(context_parts)

        prompt = f"Situational update required.\n\n{context}"
        assessment = call_claude(SYSTEM_PROMPT, prompt, "sonnet")

        header = f"*SITUATION - {now_str}*\n\n"
        send_telegram(*load_telegram_credentials("general_montgomery"), header + assessment)
        log.info("Three-hour update sent")

    except Exception as e:
        log.error(f"Update failed: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

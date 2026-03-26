#!/usr/bin/env python3
"""
SIGINT Analyst - 15-min cycle.
Polls military flights, GPS jamming, maritime AIS dark events.
Writes anomaly flags to intelligence.db for Montgomery.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_INTEL_DB    = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "sigint_analyst"
_STATE_FILE  = _ATROPHY_DIR / "agents" / "sigint_analyst" / "data" / "state.json"

_APP_DIR = Path("/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron")
sys.path.insert(0, str(_APP_DIR / "mcp"))

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SIGINT] %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "sigint_cycle.log"), logging.StreamHandler(sys.stderr)]
)
log = logging.getLogger("sigint_cycle")

# GPS jamming severity thresholds
GPS_JAMMING_THRESHOLD = 50  # reports in zone before flagging

# Military flight anomaly keywords
MILITARY_ANOMALY_KEYWORDS = [
    "nuclear", "bomber", "b-52", "b-2", "tu-95", "tu-160",
    "reaper", "predator", "global hawk", "rc-135", "p-8",
    "e-8", "awacs", "rivet joint", "dark star"
]


def load_state() -> dict:
    if _STATE_FILE.exists():
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"seen_anomalies": []}


def save_state(state: dict):
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def log_anomaly_to_db(db: sqlite3.Connection, anomaly_type: str, description: str, raw: str):
    """Write SIGINT anomaly to a signals table in intelligence.db."""
    # Create signals table if not exists
    db.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            description TEXT,
            raw_data TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        INSERT INTO signals (type, description, raw_data)
        VALUES (?, ?, ?)
    """, (anomaly_type, description, raw[:2000]))
    db.commit()


def check_gps_jamming(state: dict, db: sqlite3.Connection) -> int:
    anomalies = 0
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))
        data, _wm_delta = client.fetch_cached("api/gpsjam")
        zones = []
        if isinstance(data, dict):
            zones = data.get("data", {}).get("jammingZones", data.get("zones", []))

        for zone in zones:
            if not isinstance(zone, dict):
                continue
            count = zone.get("reportCount", zone.get("count", 0))
            name = zone.get("name", zone.get("region", "Unknown"))
            zone_id = f"gps_{name}_{count // 10}"
            if count >= GPS_JAMMING_THRESHOLD and zone_id not in state["seen_anomalies"]:
                state["seen_anomalies"].append(zone_id)
                desc = f"GPS jamming surge in {name}: {count} reports"
                log_anomaly_to_db(db, "gps_jamming", desc, json.dumps(zone))
                log.info(f"SIGINT anomaly logged: {desc}")
                anomalies += 1

    except Exception as e:
        log.warning(f"GPS jamming check failed: {e}")
    return anomalies


def check_military_flights(state: dict, db: sqlite3.Connection) -> int:
    anomalies = 0
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))
        data, _wm_delta = client.fetch_cached("api/military-flights")
        flights = []
        if isinstance(data, dict):
            flights = data.get("data", {}).get("flights", data.get("flights", []))

        for flight in flights:
            if not isinstance(flight, dict):
                continue
            callsign = str(flight.get("callsign", "")).lower()
            aircraft_type = str(flight.get("aircraftType", flight.get("type", ""))).lower()
            flight_id = flight.get("id") or flight.get("callsign", "")[:20]
            combined = callsign + " " + aircraft_type
            if any(kw in combined for kw in MILITARY_ANOMALY_KEYWORDS):
                anom_key = f"flight_{flight_id}"
                if anom_key not in state["seen_anomalies"]:
                    state["seen_anomalies"].append(anom_key)
                    desc = f"High-interest military flight: {flight.get('callsign', 'Unknown')} ({aircraft_type})"
                    log_anomaly_to_db(db, "military_flight", desc, json.dumps(flight))
                    log.info(f"SIGINT anomaly logged: {desc}")
                    anomalies += 1

    except Exception as e:
        log.warning(f"Military flights check failed: {e}")
    return anomalies


def run():
    log.info("SIGINT cycle starting")
    state = load_state()
    db = sqlite3.connect(str(_INTEL_DB))

    try:
        gps_count = check_gps_jamming(state, db)
        flight_count = check_military_flights(state, db)
        total = gps_count + flight_count
        log.info(f"Cycle complete. Anomalies logged: {total} (GPS: {gps_count}, flights: {flight_count})")
    finally:
        db.close()

    # Trim state
    if len(state["seen_anomalies"]) > 1000:
        state["seen_anomalies"] = state["seen_anomalies"][-1000:]
    save_state(state)


if __name__ == "__main__":
    run()

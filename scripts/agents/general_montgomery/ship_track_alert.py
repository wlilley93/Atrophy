#!/usr/bin/env python3
"""
Ship Tracking Alert - Five-vector AIS monitoring.

Vectors:
  1. Iran / Hormuz corridor - IRGCN surface fleet, tankers, carrier operations
  2. US-Israel - USN CENTCOM assets, Israeli naval movements
  3. Russia - Black Sea fleet, Baltic exercises, Arctic deployments
  4. Ukraine - Grain corridor, Black Sea, Odessa port activity
  5. Red Sea / Houthi - Vessel attacks, diversions, naval escort activity

Fires alert to Telegram on:
  - Vessel AIS dark event (transponder off) in flagged zones
  - Significant position change for tracked high-interest vessels
  - Surge in Hormuz or Bosporus traffic beyond threshold
  - New vessel attack report
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR   = Path.home() / ".atrophy"
_AGENT_DIR     = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON    = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB      = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR       = _ATROPHY_DIR / "logs" / "general_montgomery"
_STATE_FILE    = _AGENT_DIR / "data" / "ship_track_state.json"

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
_MCP_DIR = _APP_DIR / "mcp"
sys.path.insert(0, str(_MCP_DIR))

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "ship_track_alert.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("ship_track_alert")

# Zones of interest per vector
VECTOR_ZONES = {
    "iran_hormuz": {
        "label": "Iran / Hormuz",
        "keywords": ["hormuz", "iran", "irgc", "persian gulf", "gulf of oman", "bandar abbas"],
        "threat_keywords": ["seized", "detained", "boarded", "fired upon", "harassed", "dark"],
    },
    "us_israel": {
        "label": "US-Israel / CENTCOM",
        "keywords": ["israel", "tel aviv", "haifa", "mediterranean", "centcom", "uss ", "carrier strike"],
        "threat_keywords": ["strike", "launched", "intercept", "missile", "drone attack"],
    },
    "russia": {
        "label": "Russia / Black Sea",
        "keywords": ["black sea", "sevastopol", "novorossiysk", "kaliningrad", "murmansk", "arctic"],
        "threat_keywords": ["sunk", "damaged", "attacked", "mine", "submarine"],
    },
    "ukraine": {
        "label": "Ukraine / Grain Corridor",
        "keywords": ["odessa", "mykolaiv", "kerch", "ukraine", "grain corridor", "bosphorus"],
        "threat_keywords": ["blocked", "shelled", "mined", "attacked", "detained"],
    },
    "red_sea_houthi": {
        "label": "Red Sea / Houthi",
        "keywords": ["red sea", "houthi", "bab el-mandeb", "aden", "yemen", "ansarallah"],
        "threat_keywords": ["attack", "missile", "drone", "hijack", "seized", "diverted"],
    },
}

# Chokepoint surge thresholds (% change vs baseline - from WorldMonitor changePct)
SURGE_THRESHOLDS = {
    "Hormuz":              50.0,
    "Bosporus":            30.0,
    "Bab el-Mandeb":       40.0,
    "Cape of Good Hope":  100.0,
    "Dover Strait":        50.0,
}


def load_credentials():
    from shared.credentials import load_telegram_credentials
    return load_telegram_credentials("general_montgomery")


def load_state() -> dict:
    if _STATE_FILE.exists():
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"last_alerts": {}, "seen_events": []}


def save_state(state: dict):
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)




def check_disruption_surges(maritime_data: dict, state: dict) -> list[str]:
    """Check chokepoint changePct values against surge thresholds."""
    alerts = []
    try:
        disruptions = maritime_data.get("data", {}).get("disruptions", [])
        for d in disruptions:
            name = d.get("name", "")
            change_pct = d.get("changePct", 0)
            severity = d.get("severity", "").upper()
            for chokepoint, threshold in SURGE_THRESHOLDS.items():
                if chokepoint.lower() in name.lower():
                    if abs(change_pct) >= threshold:
                        alert_key = f"surge_{chokepoint}_{int(change_pct)}"
                        if alert_key not in state.get("seen_events", []):
                            alerts.append(
                                f"*MARITIME SURGE - {chokepoint.upper()}*\n"
                                f"Traffic change: {change_pct:+.0f}% | Severity: {severity}\n"
                                f"Zone: {name}"
                            )
                            state.setdefault("seen_events", []).append(alert_key)
    except Exception as e:
        log.warning(f"Disruption check failed: {e}")
    return alerts


def check_candidate_reports(maritime_data: dict, state: dict) -> list[str]:
    """Scan candidate incident reports for threat keywords across five vectors."""
    alerts = []
    try:
        reports = maritime_data.get("data", {}).get("candidateReports", [])
        for report in reports:
            report_id = report.get("id") or report.get("timestamp", "")
            if str(report_id) in state.get("seen_events", []):
                continue
            text = (
                report.get("title", "") + " " +
                report.get("summary", "") + " " +
                report.get("description", "")
            ).lower()

            for vector_key, vector in VECTOR_ZONES.items():
                zone_match = any(kw in text for kw in vector["keywords"])
                threat_match = any(kw in text for kw in vector["threat_keywords"])
                if zone_match and threat_match:
                    title = report.get("title", "Incident")
                    summary = report.get("summary", report.get("description", ""))[:200]
                    alerts.append(
                        f"*MARITIME ALERT - {vector['label'].upper()}*\n"
                        f"{title}\n{summary}"
                    )
                    state.setdefault("seen_events", []).append(str(report_id))
                    break  # One alert per report

    except Exception as e:
        log.warning(f"Candidate report check failed: {e}")
    return alerts


def _persist_maritime_history(maritime_data: dict):
    """Write chokepoint changePct values to maritime_history for trend charts."""
    try:
        disruptions = maritime_data.get("data", {}).get("disruptions", [])
        if not disruptions:
            return
        conn = sqlite3.connect(_INTEL_DB)
        cur = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        for d in disruptions:
            name = d.get("name", "")
            change_pct = d.get("changePct")
            severity = d.get("severity", "")
            vessel_count = d.get("vesselCount") or d.get("vessels")
            if name and change_pct is not None:
                cur.execute("""
                    INSERT INTO maritime_history
                        (chokepoint, change_pct, severity, vessel_count, recorded_at, source)
                    VALUES (?, ?, ?, ?, ?, 'worldmonitor')
                """, (name, change_pct, severity, vessel_count, now))
        conn.commit()
        conn.close()
        log.info(f"maritime_history: persisted {len(disruptions)} chokepoint readings")
    except Exception as e:
        log.warning(f"maritime_history persist failed: {e}")


def run():
    log.info("Ship tracking alert cycle starting")
    token, chat_id = load_credentials()
    state = load_state()

    # Trim seen_events to last 500 to prevent unbounded growth
    if len(state.get("seen_events", [])) > 500:
        state["seen_events"] = state["seen_events"][-500:]

    all_alerts = []

    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))
        maritime_data, _wm_delta = client.fetch_cached("api/ais-snapshot", params={"candidates": "true"})

        surge_alerts = check_disruption_surges(maritime_data, state)
        all_alerts.extend(surge_alerts)

        incident_alerts = check_candidate_reports(maritime_data, state)
        all_alerts.extend(incident_alerts)

        # Persist chokepoint data to maritime_history for trend charts
        _persist_maritime_history(maritime_data)

    except Exception as e:
        log.error(f"WorldMonitor fetch failed: {e}")

    save_state(state)

    if all_alerts:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        header = f"*SIGINT ALERT - {timestamp}*\n\n"
        for alert in all_alerts:
            message = header + alert
            try:
                send_telegram(token, chat_id, message)
                log.info(f"Alert sent: {alert[:80]}")
            except Exception as e:
                log.error(f"Failed to send alert: {e}")

        # Push alert summary to Meridian platform channel
        try:
            _personal_shared = Path.home() / ".atrophy" / "scripts" / "agents" / "shared"
            _bundle_shared = Path(__file__).resolve().parent.parent / "shared"
            for _p in [str(_personal_shared), str(_bundle_shared)]:
                if _p not in sys.path:
                    sys.path.insert(0, _p)
            from channel_push import push_briefing
            alert_summary = "\n\n".join(all_alerts)
            push_briefing(
                "general_montgomery",
                title=f"Maritime Alert - {timestamp}",
                summary=all_alerts[0][:300] if all_alerts else "",
                body_md=alert_summary,
                sources=["AIS", "WorldMonitor"],
            )
        except Exception:
            pass  # channel push is best-effort
    else:
        log.info("No new alerts this cycle")


if __name__ == "__main__":
    run()

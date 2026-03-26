#!/usr/bin/env python3
"""
Economic Intelligence Officer - Weekly Report
Runs Friday 16:00. Sanctions movements, trade corridor disruption,
energy prices as geopolitical signal, supply chain vulnerabilities.
Pulls from WorldMonitor economic and trade endpoints.
Logs to intelligence.db. Routes report to general_montgomery.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON  = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB    = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "economic_io"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
_MCP_DIR = _APP_DIR / "mcp"
sys.path.insert(0, str(_MCP_DIR))
from shared.credentials import load_telegram_credentials

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EconIO] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "economic_weekly.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("economic_weekly")


def load_cfg():
    with open(_AGENT_JSON) as f:
        return json.load(f)


def send_telegram(token: str, chat_id: str, text: str):
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_economic_data(claude_client=None) -> dict:
    """Pull WorldMonitor economic and trade data."""
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))
        economic, _wm_delta = client.fetch_cached("api/economic/v1/get-energy-prices")
        trade, _wm_delta = client.fetch_cached("api/trade/v1/get-trade-restrictions", params={"limit": "50"})
        return {"economic": economic, "trade": trade}
    except Exception as e:
        log.warning(f"WorldMonitor fetch failed: {e}")
        return {}


def extract_sanctions_signals(data: dict) -> list[str]:
    signals = []
    try:
        econ = data.get("economic", {}).get("data", {})
        sanctions = econ.get("sanctions", [])
        for s in sanctions[:5]:
            entity = s.get("entity", "Unknown")
            action = s.get("action", "")
            date = s.get("date", "")
            signals.append(f"- {entity}: {action} ({date})")
    except Exception as e:
        log.debug(f"Sanctions extract: {e}")
    return signals


def extract_trade_disruptions(data: dict) -> list[str]:
    disruptions = []
    try:
        trade = data.get("trade", {}).get("data", {})
        corridors = trade.get("corridors", []) or trade.get("disruptions", [])
        for c in corridors[:5]:
            name = c.get("name", c.get("corridor", "Unknown"))
            status = c.get("status", c.get("impact", ""))
            disruptions.append(f"- {name}: {status}")
    except Exception as e:
        log.debug(f"Trade extract: {e}")
    return disruptions


def extract_energy_signals(data: dict) -> list[str]:
    signals = []
    try:
        econ = data.get("economic", {}).get("data", {})
        energy = econ.get("energy", []) or econ.get("commodities", [])
        for e in energy[:4]:
            name = e.get("name", e.get("commodity", ""))
            price = e.get("price", e.get("value", ""))
            change = e.get("change", e.get("changePct", ""))
            if name:
                signals.append(f"- {name}: {price} ({change})")
    except Exception as e:
        log.debug(f"Energy extract: {e}")
    return signals


def log_to_db(conn: sqlite3.Connection, content: str):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO briefs (requested_by, date, title, content, created_at)
        VALUES (?, date('now'), ?, ?, ?)
    """, (
        "economic_io",
        f"Economic Weekly - {datetime.now().strftime('%Y-%m-%d')}",
        content,
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()


# Known commodity units - extend as new metrics appear
_COMMODITY_UNITS = {
    "brent crude": "USD/bbl", "wti crude": "USD/bbl", "crude oil": "USD/bbl",
    "brent": "USD/bbl", "wti": "USD/bbl",
    "natural gas": "USD/MMBtu", "henry hub": "USD/MMBtu",
    "gold": "USD/oz", "silver": "USD/oz", "platinum": "USD/oz",
    "palladium": "USD/oz",
    "copper": "USD/lb", "aluminium": "USD/mt", "aluminum": "USD/mt",
    "iron ore": "USD/mt", "steel": "USD/mt", "nickel": "USD/mt",
    "zinc": "USD/mt", "tin": "USD/mt", "lead": "USD/mt",
    "wheat": "USD/bu", "corn": "USD/bu", "soybeans": "USD/bu",
    "rice": "USD/cwt", "sugar": "USD/lb", "coffee": "USD/lb",
    "cotton": "USD/lb", "cocoa": "USD/mt",
    "lng": "USD/MMBtu", "coal": "USD/mt",
    "uranium": "USD/lb",
}


def _infer_unit(item: dict) -> str:
    """Infer unit from item data or commodity name lookup."""
    # Explicit unit in data takes priority
    unit = item.get("unit") or item.get("currency") or item.get("units")
    if unit:
        return str(unit)
    # Check item type
    item_type = (item.get("type") or "").lower()
    if item_type == "index":
        return "points"
    if item_type in ("rate", "policy_rate"):
        return "%"
    if item_type == "exchange_rate":
        return "ratio"
    # Lookup by name
    name = (item.get("name") or item.get("commodity") or "").lower()
    for key, unit_str in _COMMODITY_UNITS.items():
        if key in name:
            return unit_str
    # Fallback
    return "USD"


def log_economic_history(conn: sqlite3.Connection, data: dict):
    """Persist any numeric economic indicators to economic_history."""
    try:
        cur = conn.cursor()
        econ = data.get("economic", {}).get("data", {})
        commodities = econ.get("commodities", econ.get("energy", []))
        now = datetime.now(timezone.utc).isoformat()
        for item in commodities:
            name = item.get("name", item.get("commodity", ""))
            value = item.get("price", item.get("value"))
            unit = _infer_unit(item)
            if name and value is not None:
                cur.execute("""
                    INSERT INTO economic_history
                    (metric, value, unit, region, recorded_at, source)
                    VALUES (?, ?, ?, ?, ?, 'worldmonitor')
                """, (name, value, unit, None, now))
        conn.commit()
    except Exception as e:
        log.debug(f"economic_history write: {e}")


def build_assessment(data: dict) -> str:
    """Build a structured weekly assessment from the raw data."""
    sanctions = extract_sanctions_signals(data)
    trade = extract_trade_disruptions(data)
    energy = extract_energy_signals(data)

    now_str = datetime.now().strftime("%d %b %Y")
    lines = [
        f"*ECONOMIC INTELLIGENCE - WEEKLY ASSESSMENT*",
        f"_{now_str} | Economic Intelligence Officer_",
        "",
    ]

    lines.append("*SANCTIONS & DESIGNATIONS*")
    if sanctions:
        lines.extend(sanctions)
    else:
        lines.append("- No significant new sanctions activity detected.")
    lines.append("")

    lines.append("*TRADE CORRIDOR DISRUPTION*")
    if trade:
        lines.extend(trade)
    else:
        lines.append("- No major corridor disruptions flagged this week.")
    lines.append("")

    lines.append("*ENERGY AS GEOPOLITICAL SIGNAL*")
    if energy:
        lines.extend(energy)
        lines.append("")
        lines.append("_Elevated energy prices correlate with tightening supply discipline, "
                     "not demand - watch producer state behaviour._")
    else:
        lines.append("- Energy price data unavailable this cycle.")
    lines.append("")

    lines.append("*ASSESSMENT*")
    lines.append("Economic pressure vectors remain the primary lever below the threshold "
                 "of open conflict. Sanctions regimes are leaky but cumulative - watch "
                 "secondary sanction enforcement as the leading indicator of escalation intent.")

    return "\n".join(lines)


def main():
    log.info("Economic weekly starting")
    cfg = load_cfg()
    data = fetch_economic_data()

    assessment = build_assessment(data)
    log.info("Assessment built")

    conn = sqlite3.connect(_INTEL_DB)
    log_to_db(conn, assessment)
    log_economic_history(conn, data)
    conn.close()

    try:
        send_telegram(*load_telegram_credentials("economic_io"), assessment)
        log.info("Economic weekly sent")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


if __name__ == "__main__":
    main()

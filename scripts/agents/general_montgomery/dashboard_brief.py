#!/usr/bin/env python3
"""
Montgomery Dashboard Brief - Persistent cron script.

Modes:
    --mode refresh  : collect data, regenerate HTML, send only on breaking news
    --mode send     : collect data, generate LLM assessment, render, always send

Called by the Atrophy job runner every 15min (refresh) and 4h (send).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Paths ---
_ATROPHY_DIR   = Path.home() / ".atrophy"
_AGENT_DIR     = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON    = _AGENT_DIR / "data" / "agent.json"
_TOOLS_DIR     = _AGENT_DIR / "tools"
_LOG_DIR       = _ATROPHY_DIR / "logs" / "general_montgomery"
_DATA_FILE     = Path("/tmp/brief_data.json")
_HTML_FILE     = Path("/tmp/montgomery_brief.html")
_CACHE_DB      = _ATROPHY_DIR / "worldmonitor_cache.db"
_INTEL_DB      = _AGENT_DIR / "data" / "intelligence.db"
_SWITCHBOARD   = _ATROPHY_DIR / ".switchboard_directory.json"

_APP_DIR = Path("/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron")
_MCP_DIR = _APP_DIR / "mcp"
sys.path.insert(0, str(_MCP_DIR))

# --- Logging ---
_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "dashboard_brief.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("dashboard_brief")

# --- Theaters ---
THEATERS = [
    {"name": "Eastern Med",     "id": "eastern-med"},
    {"name": "Persian Gulf",    "id": "persian-gulf"},
    {"name": "South China Sea", "id": "south-china-sea"},
    {"name": "Ukraine Front",   "id": "ukraine-front"},
    {"name": "Horn of Africa",  "id": "horn-of-africa"},
    {"name": "Arabian Sea",     "id": "arabian-sea"},
    {"name": "Baltic Sea",      "id": "baltic-sea"},
    {"name": "Indo-Pacific",    "id": "indo-pacific"},
    {"name": "North Korea",     "id": "north-korea"},
]

RISK_BASELINE = [
    {"region": "IL", "name": "Israel",       "score": 70, "trend": "stable"},
    {"region": "UA", "name": "Ukraine",       "score": 67, "trend": "stable"},
    {"region": "SY", "name": "Syria",         "score": 60, "trend": "stable"},
    {"region": "YE", "name": "Yemen",         "score": 60, "trend": "stable"},
    {"region": "MM", "name": "Myanmar",       "score": 60, "trend": "stable"},
    {"region": "AF", "name": "Afghanistan",   "score": 60, "trend": "stable"},
    {"region": "IR", "name": "Iran",          "score": 55, "trend": "stable"},
    {"region": "TW", "name": "Taiwan Strait", "score": 40, "trend": "stable"},
]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _brief_id() -> str:
    d = datetime.now(timezone.utc)
    return f"MGY-{d.strftime('%Y-%m-%d')}-{d.strftime('%H%M')}"


def collect_data() -> dict:
    """Pull live data from WorldMonitor. Returns structured brief_data dict."""
    try:
        from worldmonitor_server import WorldMonitorClient
    except ImportError:
        log.warning("WorldMonitorClient not available - using cached/baseline data")
        return _load_or_baseline()

    client = WorldMonitorClient(cache_db=str(_CACHE_DB))

    fleet_raw  = _safe_call(client.get_fleet_report,  "fleet")
    alerts_raw = _safe_call(lambda: client.fetch_cached("api/oref-alerts")[0], "alerts")
    jam_raw    = _safe_call(lambda: client.fetch_cached("api/gpsjam")[0], "gps_jamming")
    news_raw   = _safe_call(client.get_news_digest,    "news")

    fleet   = _parse_fleet(fleet_raw)
    alerts  = _parse_alerts(alerts_raw)
    jamming = _parse_jamming(jam_raw)
    news    = _parse_news(news_raw)

    # Carry forward risk scores from previous brief
    prev    = _load_or_baseline()
    risk    = prev.get("risk_scores", RISK_BASELINE)

    status, note = _derive_status(alerts, risk)

    data = {
        "generated_at":   _ts(),
        "brief_id":       _brief_id(),
        "overall_status": status,
        "status_note":    note,
        "risk_scores":    risk,
        "theaters":       [dict(t, status="normal", flights=0) for t in THEATERS],
        "fleet":          fleet,
        "alerts":         alerts,
        "gps_jamming":    jamming,
        "news_items":     news,
        "assessment":     prev.get("assessment", ""),
    }
    try:
        data["ops"] = collect_ops_data()
    except Exception as e:
        log.warning("Ops data collection failed: %s", e)
        data["ops"] = {}
    return data


def _safe_call(fn, label):
    try:
        return fn()
    except Exception as e:
        log.warning("%s fetch failed: %s", label, e)
        return None


def _load_or_baseline() -> dict:
    if _DATA_FILE.exists():
        try:
            with open(_DATA_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "generated_at": _ts(), "brief_id": _brief_id(),
        "overall_status": "NORMAL", "status_note": "",
        "risk_scores": RISK_BASELINE,
        "theaters": [dict(t, status="normal", flights=0) for t in THEATERS],
        "fleet": [], "alerts": {"active": 0, "last_24h": 0, "items": []},
        "gps_jamming": {"active_zones": 0, "regions": []},
        "news_items": [], "assessment": "",
    }


def _parse_fleet(raw) -> list:
    if not raw or not isinstance(raw, list):
        return []
    out = []
    for v in raw:
        out.append({
            "vessel":       v.get("name", v.get("vessel", "Unknown")),
            "type":         v.get("type", ""),
            "location":     v.get("location", v.get("position", "")),
            "significance": v.get("significance", v.get("notes", "")),
        })
    return out[:8]


def _parse_alerts(raw) -> dict:
    if not raw or not isinstance(raw, dict):
        return {"active": 0, "last_24h": 0, "items": []}
    return {
        "active":   raw.get("active_count", raw.get("active", 0)),
        "last_24h": raw.get("last_24h", 0),
        "items":    raw.get("alerts", raw.get("items", []))[:5],
    }


def _parse_jamming(raw) -> dict:
    if not raw or not isinstance(raw, dict):
        return {"active_zones": 0, "regions": []}
    return {
        "active_zones": raw.get("active_zones", raw.get("count", 0)),
        "regions":      raw.get("zones", raw.get("regions", []))[:6],
    }


def _parse_news(raw) -> list:
    if not raw:
        return []
    items = raw if isinstance(raw, list) else raw.get("items", [])
    return [{
        "headline":     i.get("headline", i.get("title", "")),
        "source":       i.get("source", ""),
        "url":          i.get("url", ""),
        "significance": i.get("significance", i.get("summary", "")),
    } for i in items[:6]]


def _derive_status(alerts: dict, risk: list) -> tuple[str, str]:
    active   = alerts.get("active", 0)
    max_risk = max((r["score"] for r in risk), default=0)
    if active > 50 or max_risk >= 80:
        return "CRITICAL", f"{active} active alerts - maximum risk posture"
    elif active > 10 or max_risk >= 65:
        return "ELEVATED", f"{active} active alerts across monitored theaters"
    return "NORMAL", "No significant escalations detected"


def is_breaking(data: dict) -> bool:
    """Return True if current data warrants immediate send."""
    active = data.get("alerts", {}).get("active", 0)
    status = data.get("overall_status", "NORMAL")
    # Check against previous status
    prev = _load_or_baseline()
    prev_status = prev.get("overall_status", "NORMAL")
    status_changed = status != prev_status and status in ("ELEVATED", "CRITICAL")
    return active > 20 or status == "CRITICAL" or status_changed


CLAUDE_BIN = "/Users/williamlilley/.local/bin/claude"


def call_claude(system: str, prompt: str, model: str = "sonnet") -> str:
    """One-shot Claude call via CLI. Returns response text."""
    import subprocess
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


def generate_assessment(data: dict) -> str:
    """Call Claude to generate a Montgomery-voice assessment paragraph."""
    status    = data.get("overall_status", "NORMAL")
    fleet     = data.get("fleet", [])
    alerts    = data.get("alerts", {})
    risk      = data.get("risk_scores", [])
    news      = data.get("news_items", [])

    fleet_summary = "; ".join(f"{v['vessel']} at {v['location']}" for v in fleet[:4])
    top_risks     = sorted(risk, key=lambda x: x["score"], reverse=True)[:3]
    risk_summary  = ", ".join(f"{r['name']} ({r['score']})" for r in top_risks)
    news_summary  = "; ".join(n["headline"] for n in news[:3])
    active_alerts = alerts.get("active", 0)

    system = "You are General Montgomery, strategic intelligence analyst. Clipped, precise military prose. No hedging. No em dashes."
    prompt = f"""Write a 2-3 sentence assessment of current global posture. Name active theaters and concrete developments.

Current data:
- Overall status: {status}
- Active OREF alerts: {active_alerts}
- Top risk regions: {risk_summary}
- Fleet: {fleet_summary if fleet_summary else "No fleet data"}
- Recent developments: {news_summary if news_summary else "None"}

Assessment (2-3 sentences, Montgomery voice):"""

    try:
        return call_claude(system, prompt, "sonnet")
    except Exception as e:
        log.error("Claude call failed: %s", e)
        return data.get("assessment", f"Assessment generation failed: {e}")


def render_html():
    """Run render_brief.py to produce the HTML file."""
    renderer = _TOOLS_DIR / "render_brief.py"
    if not renderer.exists():
        renderer = Path("/tmp/render_brief.py")
    result = subprocess.run(
        [sys.executable, str(renderer)],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"render_brief.py failed: {result.stderr}")
    log.info("HTML rendered: %s", _HTML_FILE)


def send_html():
    """Run send_brief.py to deliver the HTML via Telegram."""
    sender = _TOOLS_DIR / "send_brief.py"
    if not sender.exists():
        sender = Path("/tmp/send_brief.py")
    result = subprocess.run(
        [sys.executable, str(sender)],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"send_brief.py failed: {result.stderr}")
    log.info("Brief sent: %s", result.stdout.strip())


def _next_cron_epoch(cron_str: str) -> int:
    """Compute approximate next fire time (UTC epoch) for a cron expression."""
    from datetime import timedelta

    def match_field(val: int, field: str) -> bool:
        if field == "*":
            return True
        if "," in field:
            return any(match_field(val, p) for p in field.split(","))
        if field.startswith("*/"):
            return val % int(field[2:]) == 0
        if "/" in field:
            rng, step = field.split("/")
            lo, hi = (map(int, rng.split("-")) if "-" in rng else (int(rng), 999))
            return lo <= val <= hi and (val - lo) % int(step) == 0
        if "-" in field:
            lo, hi = map(int, field.split("-"))
            return lo <= val <= hi
        return val == int(field)

    parts = cron_str.strip().split()
    if len(parts) != 5:
        return int(datetime.now(timezone.utc).timestamp()) + 3600

    c_min, c_hour, c_dom, c_month, c_dow = parts
    t = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    t += timedelta(minutes=1)

    for _ in range(7 * 24 * 60 + 1):
        cron_dow = t.isoweekday() % 7  # 0=Sun, 1=Mon .. 6=Sat
        if (match_field(t.minute, c_min) and
                match_field(t.hour, c_hour) and
                match_field(t.day, c_dom) and
                match_field(t.month, c_month) and
                match_field(cron_dow, c_dow)):
            return int(t.timestamp())
        t += timedelta(minutes=1)

    return int(datetime.now(timezone.utc).timestamp()) + 86400 * 7


def collect_ops_data() -> dict:
    """Collect system ops data: agent roster, job schedule, librarian stats."""
    import sqlite3

    # Agent list from switchboard
    agents: list = []
    try:
        with open(_SWITCHBOARD) as f:
            agents = json.load(f)
    except Exception as e:
        log.warning("Switchboard read failed: %s", e)

    # Job schedule from agent.json
    jobs: list = []
    try:
        with open(_AGENT_JSON) as f:
            cfg = json.load(f)
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        for name, job in cfg.get("jobs", {}).items():
            j = dict(job, name=name)
            if job.get("type") == "interval":
                j["next_run_epoch"] = now_epoch + job.get("interval_seconds", 3600)
            elif job.get("type") == "cron":
                j["next_run_epoch"] = _next_cron_epoch(job.get("cron", "0 0 * * *"))
            else:
                j["next_run_epoch"] = now_epoch + 86400
            jobs.append(j)
    except Exception as e:
        log.warning("Agent.json read failed: %s", e)

    # Librarian stats from intelligence.db
    lib: dict = {
        "total_briefs": 0, "briefs_by_agent": {},
        "entities": 0, "relationships": 0, "recent_briefs": [],
    }
    try:
        db = sqlite3.connect(str(_INTEL_DB))
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM briefs")
        lib["total_briefs"] = cur.fetchone()[0]
        cur.execute(
            "SELECT requested_by, COUNT(*), MAX(date) FROM briefs "
            "GROUP BY requested_by ORDER BY COUNT(*) DESC"
        )
        for agent_name, count, last_date in cur.fetchall():
            lib["briefs_by_agent"][agent_name or "unknown"] = {
                "count": count, "last": (last_date or "")[:10],
            }
        cur.execute("SELECT COUNT(*) FROM entities")
        lib["entities"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM relationships")
        lib["relationships"] = cur.fetchone()[0]
        cur.execute(
            "SELECT title, requested_by, date FROM briefs "
            "ORDER BY rowid DESC LIMIT 5"
        )
        for title, req_by, date in cur.fetchall():
            lib["recent_briefs"].append(
                {"title": (title or "")[:80], "agent": req_by or "", "date": (date or "")[:10]}
            )
        db.close()
    except Exception as e:
        log.warning("Intelligence DB query failed: %s", e)

    return {"agents": agents, "jobs": jobs, "librarian": lib}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["refresh", "send"], default="refresh")
    args = parser.parse_args()

    log.info("Dashboard brief cycle: mode=%s", args.mode)

    # 1. Collect live data
    data = collect_data()

    if args.mode == "send":
        # 2. Generate LLM assessment
        log.info("Generating LLM assessment...")
        data["assessment"] = generate_assessment(data)
        data["generated_at"] = _ts()
        data["brief_id"] = _brief_id()

    # 3. Write data file
    with open(_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.info("Data written: %s", _DATA_FILE)

    # 4. Render HTML
    render_html()

    # 5. Send
    if args.mode == "send":
        send_html()
        log.info("4-hour brief dispatched")
    elif is_breaking(data):
        log.info("Breaking news threshold crossed - sending immediately")
        send_html()
    else:
        log.info("Refresh complete. No send (no breaking news threshold).")


if __name__ == "__main__":
    main()

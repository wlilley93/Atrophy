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
import fcntl
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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
_SEND_LOCK     = Path("/tmp/montgomery_brief_last_send.txt")
_LAST_ARTICLES = Path("/tmp/montgomery_brief_last_articles.json")

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
_MCP_DIR = _APP_DIR / "mcp"
if _MCP_DIR.is_dir():
    sys.path.insert(0, str(_MCP_DIR))
# When running from ~/.atrophy/scripts/ (personal override), _MCP_DIR won't
# exist. The cron runner sets PYTHONPATH to include the bundle's mcp dir,
# so the import still works via the standard path.

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

    fleet_raw  = _safe_call(lambda: client.fetch_cached("api/military/v1/get-usni-fleet-report")[0], "fleet")
    alerts_raw = _safe_call(lambda: client.fetch_cached("api/oref-alerts")[0], "alerts")
    jam_raw    = _safe_call(lambda: client.fetch_cached("api/gpsjam")[0], "gps_jamming")
    news_raw   = _safe_call(lambda: client.fetch_cached("api/news/v1/list-feed-digest")[0], "news")

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
    if not raw:
        return []
    # Unwrap API envelope: {report: {vessels: [...]}, cached, stale, error}
    vessels = raw
    if isinstance(raw, dict):
        report = raw.get("report", raw)
        vessels = report.get("vessels", []) if isinstance(report, dict) else []
    if not isinstance(vessels, list):
        return []
    out = []
    for v in vessels:
        out.append({
            "vessel":       v.get("name", v.get("vessel", "Unknown")),
            "type":         v.get("vesselType", v.get("type", "")),
            "location":     v.get("region", v.get("location", v.get("position", ""))),
            "significance": v.get("strikeGroup", v.get("significance", v.get("notes", ""))),
        })
    return out[:8]


def _parse_alerts(raw) -> dict:
    if not raw or not isinstance(raw, dict):
        return {"active": 0, "last_24h": 0, "items": []}
    # API shape: {configured, alerts: [...], historyCount24h, totalHistoryCount, timestamp}
    alert_list = raw.get("alerts", [])
    return {
        "active":   len(alert_list),
        "last_24h": raw.get("historyCount24h", raw.get("last_24h", 0)),
        "items":    alert_list[:5],
    }


def _parse_jamming(raw) -> dict:
    if not raw or not isinstance(raw, dict):
        return {"active_zones": 0, "regions": []}
    # API shape: {fetchedAt, source, stats: {totalHexes, highCount, mediumCount}, hexes: [...]}
    stats = raw.get("stats", {})
    high = stats.get("highCount", 0) if isinstance(stats, dict) else 0
    return {
        "active_zones": high,
        "regions":      raw.get("zones", raw.get("regions", []))[:6],
    }


def _parse_news(raw) -> list:
    if not raw:
        return []
    # API shape: {categories: {politics: {items: [...]}, ...}, feedStatuses, generatedAt}
    # Flatten all category items into a single list, sorted by recency
    items = []
    if isinstance(raw, dict) and "categories" in raw:
        for cat_name, cat_data in raw.get("categories", {}).items():
            if isinstance(cat_data, dict):
                for item in cat_data.get("items", []):
                    item["_category"] = cat_name
                    items.append(item)
        # Sort by priority: alerts first, then threat level, then recency
        _THREAT_RANK = {"THREAT_LEVEL_CRITICAL": 4, "THREAT_LEVEL_HIGH": 3,
                        "THREAT_LEVEL_MEDIUM": 2, "THREAT_LEVEL_LOW": 1}
        items.sort(key=lambda x: (
            x.get("isAlert", False),
            _THREAT_RANK.get(
                (x.get("threat") or {}).get("level", ""), 0
            ) if isinstance(x.get("threat"), dict) else 0,
            x.get("publishedAt", ""),
        ), reverse=True)
    elif isinstance(raw, list):
        items = raw
    else:
        items = raw.get("items", [])
    return [{
        "headline":     i.get("headline", i.get("title", "")),
        "source":       i.get("source", ""),
        "url":          i.get("url", i.get("link", "")),
        "significance": i.get("significance", i.get("summary", i.get("_category", ""))),
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
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[:200]}")
    return result.stdout.strip()


def _recent_articles(limit: int = 8, hours: int = 24) -> str:
    """Pull recent high-relevance articles, marking NEW vs CONTINUING stories."""
    try:
        db = sqlite3.connect(str(_INTEL_DB))
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        rows = db.execute(
            "SELECT title, source_name, summary, relevance_score, harvested_at FROM articles "
            "WHERE harvested_at >= ? AND relevance_score > 0.3 "
            "ORDER BY relevance_score DESC LIMIT ?", (cutoff, limit)
        ).fetchall()
        db.close()
        if not rows:
            return ""

        # Load previous article titles to detect new vs. continuing
        prev_titles: set[str] = set()
        if _LAST_ARTICLES.exists():
            try:
                prev_titles = set(json.loads(_LAST_ARTICLES.read_text()))
            except Exception:
                pass

        current_titles = [r[0] for r in rows if r[0]]
        lines = []
        for title, source, summary, rel, harvested in rows:
            tag = "NEW" if title and title not in prev_titles else "CONTINUING"
            entry = f"- [{tag}] [{source}] {title or 'Untitled'}"
            if summary:
                first = summary.split('.')[0].strip()
                if len(first) > 20:
                    entry += f" - {first[:150]}"
            lines.append(entry)

        # Save current titles for next cycle
        _LAST_ARTICLES.write_text(json.dumps(current_titles))

        return "\n".join(lines)
    except Exception as e:
        log.warning("Article context query failed: %s", e)
        return ""


def _recent_brief_context(limit: int = 5) -> str:
    """Pull recent brief titles and summaries from intelligence.db for grounding."""
    try:
        db = sqlite3.connect(str(_INTEL_DB))
        rows = db.execute(
            "SELECT title, content, requested_by, date FROM briefs "
            "WHERE title NOT LIKE '%Performance%' AND title NOT LIKE '%Agent Metrics%' "
            "AND title NOT LIKE '%Source Health%' AND title NOT LIKE '%Contradiction Check%' "
            "ORDER BY rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        db.close()
        if not rows:
            return ""
        lines = []
        for title, content, agent, date in rows:
            entry = f"- [{(date or '')[:10]}] {title or 'Untitled'}"
            if content:
                # Skip markdown headers/formatting to find first real sentence
                for line in content.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#') and not line.startswith('*') and not line.startswith('---') and len(line) > 20:
                        entry += f": {line[:150]}"
                        break
            lines.append(entry)
        return "\n".join(lines)
    except Exception as e:
        log.warning("Brief context query failed: %s", e)
        return ""


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

    # Pull recent intelligence for grounding
    article_context = _recent_articles(8, hours=24)
    brief_context = _recent_brief_context(5)

    system = (
        "You are General Montgomery, strategic intelligence analyst. Write like "
        "a news wire - name the actors, name the countries, cite the numbers. "
        "Clipped, precise. No hedging. Hyphens only, never em dashes. "
        "NEVER mention system metrics like brief counts, agent performance, "
        "horizon calendars, or pipeline health - this is intelligence, not ops."
    )
    prompt = f"""Write a 3-4 sentence assessment of what is happening right now in global security. Be SPECIFIC - name presidents, generals, militaries, cities. Say what they did and why it matters.

Live sensor data:
- Overall status: {status}
- Active OREF alerts: {active_alerts}
- Top risk regions: {risk_summary}
- Fleet positioning: {fleet_summary if fleet_summary else "No fleet data this cycle"}
- WorldMonitor headlines: {news_summary if news_summary else "No live headlines this cycle"}

Recent articles harvested (last 24h, ranked by relevance):
{article_context if article_context else "No recent articles"}

Recent analytical briefs:
{brief_context if brief_context else "No recent briefs"}

Rules:
- Lead with [NEW] articles first - these are developments since the last brief
- If all articles are [CONTINUING], say what has CHANGED or ESCALATED, not what was already known
- Name specific actors (Israel, Russia, Houthis, Pentagon, etc.) not "multiple theaters"
- Each sentence should cover a DIFFERENT theater or development
- Deduplicate - if 3 articles cover the same Houthi strike, that's one sentence not three
- Never mention brief counts, agent health, or system status
- 3-4 sentences maximum

Assessment:"""

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
        log.error("send_brief.py failed (exit %d): %s", result.returncode, result.stderr.strip())
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
            elif job.get("type") in ("calendar", None) and job.get("cron"):
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


def collect_horizon() -> dict:
    """Query upcoming horizon events for the brief."""
    try:
        db = sqlite3.connect(str(_INTEL_DB))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        end = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        rows = db.execute(
            """SELECT event_date, event_type, title, significance, confidence, source
            FROM horizon_events
            WHERE event_date BETWEEN ? AND ?
            ORDER BY event_date ASC, significance DESC""",
            (today, end),
        ).fetchall()
        db.close()

        events = []
        for row in rows:
            events.append({
                "date": row[0],
                "type": row[1],
                "title": row[2],
                "significance": row[3],
                "confidence": row[4],
                "source": row[5],
            })
        return {"horizon_events": events}
    except Exception as e:
        log.warning("Horizon data collection failed: %s", e)
        return {"horizon_events": []}


def generate_greeting(data: dict) -> str:
    """Generate a structured Montgomery-voice caption for the Telegram brief."""
    status = data.get("overall_status", "NORMAL")
    alerts = data.get("alerts", {})
    fleet = data.get("fleet", [])
    news = data.get("news_items", [])
    risk = data.get("risk_scores", [])
    assessment = data.get("assessment", "")

    top_risks = sorted(risk, key=lambda x: x.get("score", 0), reverse=True)[:3]
    risk_line = ", ".join(f"{r['name']} {r['score']}" for r in top_risks)
    fleet_line = "; ".join(f"{v['vessel']} at {v['location']}" for v in fleet[:4])
    active_alerts = alerts.get("active", 0)
    alerts_24h = alerts.get("last_24h", 0)

    # Get fresh articles for the greeting too
    article_context = _recent_articles(6, hours=12)

    system = (
        "You are General Montgomery, strategic intelligence analyst. Write a "
        "structured Telegram caption. Hyphens only, never em dashes. "
        "NEVER mention brief counts, system metrics, agent health, horizon "
        "calendars, or pipeline status - intelligence content only."
    )
    prompt = (
        f"Assessment: {assessment[:600] if assessment else 'None'}\n"
        f"Status: {status}\n"
        f"Risk regions: {risk_line}\n"
        f"OREF alerts: {active_alerts} active, {alerts_24h:,} in 24h\n"
        f"Fleet: {fleet_line if fleet_line else 'No data'}\n\n"
        f"Recent articles:\n{article_context if article_context else 'None'}\n\n"
        f"Write a Telegram caption using this EXACT structure:\n\n"
        f"Line 1: Status [STATUS] - one sentence lead\n\n"
        f"Then 3 bullet points (use - not unicode bullets), each a DIFFERENT development:\n"
        f"- Region: What happened\n"
        f"- Region: What happened\n"
        f"- Region: What happened\n\n"
        f"Last line: One sentence watch item\n\n"
        f"HARD LIMIT: 900 characters total. This is a Telegram caption with a 1024 char limit.\n"
        f"Keep bullet points to ONE short sentence each. No bold, no brackets, no markdown.\n"
        f"Plain text only. Be dense and specific - every word must earn its place."
    )

    try:
        greeting = call_claude(system, prompt, "sonnet")
        # Hard cap at 1000 chars (Telegram caption limit is 1024)
        if len(greeting) > 1000:
            # Truncate at last complete sentence before limit
            original_len = len(greeting)
            truncated = greeting[:1000]
            last_period = truncated.rfind('.')
            if last_period > 600:
                greeting = truncated[:last_period + 1]
            else:
                greeting = truncated.rstrip() + "..."
            log.warning("Greeting truncated from %d to %d chars", original_len, len(greeting))
        return greeting
    except Exception as e:
        log.error("Greeting generation failed: %s", e)
        return f"Brief attached. Status: {status}."


_GREETING_FILE = Path("/tmp/montgomery_greeting.txt")


def _acquire_send_lock() -> "int | None":
    """Try to acquire an exclusive lock for sending. Returns fd on success, None if locked."""
    try:
        fd = os.open(str(_SEND_LOCK), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Check if a send happened recently (within 10 min)
        try:
            content = os.read(fd, 64).decode().strip()
            if content:
                elapsed = datetime.now(timezone.utc).timestamp() - float(content)
                if elapsed < 600:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    return None
        except (ValueError, OSError):
            pass
        return fd
    except (OSError, IOError):
        # LOCK_NB failed - another process holds the lock
        return None


def _mark_sent_and_release(fd: int):
    """Write timestamp and release the lock."""
    ts = str(datetime.now(timezone.utc).timestamp()).encode()
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, ts)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["refresh", "send"], default="refresh")
    args = parser.parse_args()

    # Dedup: acquire exclusive file lock to prevent double-sends when both
    # launchd and in-process scheduler fire this script simultaneously.
    send_lock_fd = None
    if args.mode == "send":
        send_lock_fd = _acquire_send_lock()
        if send_lock_fd is None:
            log.info("Dashboard brief skipped: locked by another process or sent within last 10 minutes")
            return

    log.info("Dashboard brief cycle: mode=%s", args.mode)

    try:
        # 1. Collect live data
        data = collect_data()

        # 1b. Collect horizon events
        data.update(collect_horizon())

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
            # Generate greeting and write to file for send_brief.py
            log.info("Generating greeting...")
            greeting = generate_greeting(data)
            _GREETING_FILE.write_text(greeting, encoding="utf-8")
            log.info("Greeting written: %s", _GREETING_FILE)
            send_html()
            _mark_sent_and_release(send_lock_fd)
            send_lock_fd = None  # Already released
            log.info("4-hour brief dispatched")
        elif is_breaking(data):
            log.info("Breaking news threshold crossed - sending immediately")
            greeting = generate_greeting(data)
            _GREETING_FILE.write_text(greeting, encoding="utf-8")
            log.info("Breaking greeting written: %s", _GREETING_FILE)
            send_html()
        else:
            log.info("Refresh complete. No send (no breaking news threshold).")
    finally:
        # Release lock if still held (error path)
        if send_lock_fd is not None:
            try:
                fcntl.flock(send_lock_fd, fcntl.LOCK_UN)
                os.close(send_lock_fd)
            except OSError:
                pass

    # 6. Push channel state to Meridian platform (on send mode)
    if args.mode == "send":
        try:
            _personal_shared = Path.home() / ".atrophy" / "scripts" / "agents" / "shared"
            _bundle_shared = Path(__file__).resolve().parent.parent / "shared"
            for _p in [str(_personal_shared), str(_bundle_shared)]:
                if _p not in sys.path:
                    sys.path.insert(0, _p)
            from channel_push import push_channel

            status = data.get("overall_status", "NORMAL").lower()
            alert_level = "critical" if status == "critical" else ("elevated" if status == "elevated" else "normal")
            assessment_text = data.get("assessment", "")
            summary_line = assessment_text.split("\n")[0][:300] if assessment_text else ""

            layers = ["military-flights", "ais-vessels", "oref-alerts"]
            if data.get("gps_jamming", {}).get("active_zones", 0) > 0:
                layers.append("gps-jamming")

            push_channel("general_montgomery", {
                "agent": "general_montgomery",
                "display_name": "Gen. Montgomery",
                "alert_level": alert_level,
                "briefing": {
                    "title": f"Dashboard Brief - {data.get('brief_id', '')}",
                    "summary": summary_line,
                    "body_md": assessment_text,
                    "sources": ["WorldMonitor", "OREF", "USNI", "ADS-B"],
                },
                "map": {
                    "center": [30, 30],
                    "zoom": 2,
                    "layers": layers,
                },
            })
            log.info("Channel state pushed to Meridian platform")
        except Exception as e:
            log.warning("Channel push failed (non-fatal): %s", e)


if __name__ == "__main__":
    main()

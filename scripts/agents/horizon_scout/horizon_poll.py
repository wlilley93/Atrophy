#!/usr/bin/env python3
"""
Horizon Scout - Calendar intelligence poller.

Polls structured event sources, normalises into horizon_events.
Runs nightly at 03:00. Does not generate analysis - only identifies events.

Sources:
  - Central bank meeting calendars (FOMC, ECB, BoE, BoJ)
  - UK Parliament sitting calendar
  - Treaty/deadline register (DB-maintained)
  - WorldMonitor event feeds (UN, NATO via news digest)
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import subprocess
import sys
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.horizon_schema import ensure_table, _INTEL_DB

_ATROPHY_DIR = Path.home() / ".atrophy"
_LOG_DIR = _ATROPHY_DIR / "logs" / "horizon_scout"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [HorizonScout] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "horizon_poll.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("horizon_scout")

CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")

# --- Lookahead window ---
HORIZON_DAYS = 14  # poll events up to 14 days out


def call_claude(system: str, prompt: str, model: str = "haiku") -> str:
    """One-shot Claude call via CLI."""
    result = subprocess.run(
        [CLAUDE_BIN, "-p", "--model", model, "--system-prompt", system,
         "--no-session-persistence", "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[:200]}")
    return result.stdout.strip()


def fetch_url(url: str, timeout: int = 15) -> str | None:
    """Fetch URL content. Returns None on failure."""
    try:
        req = Request(url, headers={"User-Agent": "Meridian/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return None


# ---- Source: Central Bank Calendars ----

# Known meeting dates for 2026 (manually maintained - update annually)
# These are the fixed, published schedules
CENTRAL_BANK_MEETINGS = {
    "FOMC": {
        "dates": [
            "2026-01-27", "2026-01-28",  # Jan meeting
            "2026-03-17", "2026-03-18",  # Mar meeting
            "2026-05-05", "2026-05-06",  # May meeting
            "2026-06-16", "2026-06-17",  # Jun meeting
            "2026-07-28", "2026-07-29",  # Jul meeting
            "2026-09-15", "2026-09-16",  # Sep meeting
            "2026-10-27", "2026-10-28",  # Oct meeting
            "2026-12-15", "2026-12-16",  # Dec meeting
        ],
        "actors": ["Federal Reserve", "FOMC"],
        "region": "US",
    },
    "ECB Governing Council": {
        "dates": [
            "2026-01-22", "2026-03-05", "2026-04-16",
            "2026-06-04", "2026-07-16", "2026-09-10",
            "2026-10-22", "2026-12-10",
        ],
        "actors": ["ECB", "European Central Bank"],
        "region": "EU",
    },
    "BoE MPC": {
        "dates": [
            "2026-02-05", "2026-03-19", "2026-05-07",
            "2026-06-18", "2026-08-06", "2026-09-17",
            "2026-11-05", "2026-12-17",
        ],
        "actors": ["Bank of England", "MPC"],
        "region": "GB",
    },
    "BoJ": {
        "dates": [
            "2026-01-23", "2026-03-13", "2026-04-30",
            "2026-06-18", "2026-07-30", "2026-09-17",
            "2026-10-29", "2026-12-17",
        ],
        "actors": ["Bank of Japan"],
        "region": "JP",
    },
}


def poll_central_banks(horizon_end: str) -> list[dict]:
    """Return central bank meetings within the horizon window."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    events = []
    for name, info in CENTRAL_BANK_MEETINGS.items():
        for date_str in info["dates"]:
            if today <= date_str <= horizon_end:
                events.append({
                    "event_date": date_str,
                    "event_type": "economic",
                    "title": f"{name} meeting",
                    "description": f"Scheduled {name} monetary policy decision",
                    "actors": json.dumps(info["actors"]),
                    "significance": "HIGH",
                    "confidence": "CONFIRMED",
                    "source": f"calendar:central_banks",
                    "region": info["region"],
                })
    return events


# ---- Source: WorldMonitor news for diplomatic/security events ----

def poll_worldmonitor_events(horizon_end: str) -> list[dict]:
    """Use WorldMonitor news digest to extract upcoming events via Claude."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "mcp"))
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(
            cache_db=str(_ATROPHY_DIR / "worldmonitor_cache.db")
        )
        digest_data, _ = client.fetch_cached("api/news/v1/list-feed-digest")
        if not digest_data:
            return []

        cats = digest_data.get("categories", {})
        if not cats and isinstance(digest_data.get("data"), dict):
            cats = digest_data["data"].get("categories", {})

        headlines = []
        for cat in ["intel", "gov", "world", "europe", "mideast", "asia"]:
            cat_val = cats.get(cat, {})
            items = cat_val.get("items", cat_val) if isinstance(cat_val, dict) else cat_val
            for a in (items or [])[:10]:
                title = a.get("title", "")
                if title:
                    headlines.append(title)

        if not headlines:
            return []

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        system = f"""You are an intelligence calendar analyst. Extract ONLY confirmed upcoming events
(summits, visits, votes, exercises, deadlines, launches) from these headlines.
Today is {today}. Only include events between {today} and {horizon_end}.

Return a JSON array. Each item:
{{"date":"YYYY-MM-DD","type":"diplomatic|economic|security|political","title":"...","actors":["..."],"region":"XX","significance":"HIGH|MEDIUM|LOW"}}

If no upcoming events found, return []. No commentary."""

        raw = call_claude(system, "\n".join(headlines[:40]))
        # Extract JSON from response
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            return []
        items = json.loads(match.group())
        events = []
        for item in items:
            if not item.get("date") or not item.get("title"):
                continue
            events.append({
                "event_date": item["date"],
                "event_type": item.get("type", "diplomatic"),
                "title": item["title"],
                "actors": json.dumps(item.get("actors", [])),
                "significance": item.get("significance", "MEDIUM"),
                "confidence": "HIGH",
                "source": "calendar:worldmonitor",
                "region": item.get("region", ""),
            })
        return events
    except Exception as e:
        log.error(f"WorldMonitor poll failed: {e}")
        return []


# ---- Source: Treaty / deadline register ----

def poll_deadlines(db: sqlite3.Connection, horizon_end: str) -> list[dict]:
    """Query existing horizon_events with source='deadline:*' that are still active.
    Deadlines are manually seeded or added by Montgomery via MCP tools."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = db.execute(
        "SELECT id FROM horizon_events WHERE source LIKE 'deadline:%' AND event_date BETWEEN ? AND ?",
        (today, horizon_end)
    ).fetchall()
    # Deadlines are already in the table - this just reports count for logging
    log.info(f"Active deadlines in horizon window: {len(rows)}")
    return []  # already persisted, no new inserts needed


# ---- Main orchestrator ----

def dedup_key(event: dict) -> str:
    """Generate dedup key from date + title normalised."""
    return f"{event['event_date']}:{event['title'].lower().strip()}"


def run():
    log.info("Horizon poll starting")
    ensure_table()

    today = datetime.now(timezone.utc)
    horizon_end = (today + timedelta(days=HORIZON_DAYS)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")

    # Collect from all sources
    all_events = []
    all_events.extend(poll_central_banks(horizon_end))
    all_events.extend(poll_worldmonitor_events(horizon_end))

    if not all_events:
        log.info("No new horizon events found")
        return

    # Deduplicate against existing DB entries
    db = sqlite3.connect(str(_INTEL_DB))
    existing = set()
    for row in db.execute(
        "SELECT event_date, title FROM horizon_events WHERE event_date >= ?",
        (today_str,)
    ).fetchall():
        existing.add(f"{row[0]}:{row[1].lower().strip()}")

    poll_deadlines(db, horizon_end)

    inserted = 0
    for event in all_events:
        key = dedup_key(event)
        if key in existing:
            continue
        db.execute(
            """INSERT INTO horizon_events
            (event_date, event_type, title, description, actors, significance,
             confidence, source, region, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, date(?, '+1 day'))""",
            (event["event_date"], event["event_type"], event["title"],
             event.get("description", ""), event.get("actors", "[]"),
             event.get("significance", "MEDIUM"), event.get("confidence", "HIGH"),
             event["source"], event.get("region", ""),
             event["event_date"]),
        )
        existing.add(key)
        inserted += 1

    # Prune expired events (older than yesterday)
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    pruned = db.execute(
        "DELETE FROM horizon_events WHERE expires_at < ?", (yesterday,)
    ).rowcount

    db.commit()
    db.close()

    log.info(f"Inserted {inserted} new events, pruned {pruned} expired")
    if inserted > 0:
        print(f"Horizon updated: {inserted} new events in next {HORIZON_DAYS} days")


if __name__ == "__main__":
    run()

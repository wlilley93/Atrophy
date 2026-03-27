#!/usr/bin/env python3
"""Source Health Dashboard - checks all data sources and records their status.

Collects every RSS feed, WorldMonitor API endpoint, and procurement API
used by the Meridian intelligence system. Pings each one, records the
HTTP status, response size, and freshness, then writes the results to
the source_health table in intelligence.db.

Runs as a cron job every 6 hours. Prints a summary to stdout and
optionally pushes to the Meridian platform via channel_push.

Usage:
    python3 scripts/agents/shared/source_health.py

Environment:
    INTELLIGENCE_DB - path to intelligence.db (auto-detected if unset)
    WORLDMONITOR_BASE_URL - WorldMonitor API base (default: https://api.worldmonitor.app)
    WORLDMONITOR_API_KEY - optional API key for WorldMonitor
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_TIMEOUT = 5  # seconds per request
_USER_AGENT = "Atrophy/1.0 (Source Health Check)"
_FRESHNESS_HOURS = 48  # RSS items must be within this window to count as fresh

_WORLDMONITOR_BASE = os.environ.get(
    "WORLDMONITOR_BASE_URL", "https://api.worldmonitor.app"
).rstrip("/")

_WORLDMONITOR_KEY = os.environ.get("WORLDMONITOR_API_KEY", "")


def _db_path() -> str:
    """Resolve intelligence.db path."""
    env = os.environ.get("INTELLIGENCE_DB")
    if env:
        return env
    return str(
        Path.home()
        / ".atrophy"
        / "agents"
        / "general_montgomery"
        / "data"
        / "intelligence.db"
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS source_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT NOT NULL,
    http_status INTEGER,
    response_bytes INTEGER,
    is_fresh BOOLEAN,
    error_message TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_source_health_source ON source_health(source_id);
CREATE INDEX IF NOT EXISTS idx_source_health_time ON source_health(checked_at);
"""


def ensure_schema(db: str) -> None:
    """Create the source_health table if it does not exist."""
    con = sqlite3.connect(db, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
        con.executescript(_SCHEMA_SQL)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Source catalog - collected from MCP servers
# ---------------------------------------------------------------------------

# Active RSS feeds from mcp/defence_sources_server.py FEED_CATALOG
RSS_FEEDS: dict[str, dict[str, str]] = {
    "uk_mod": {
        "name": "UK Ministry of Defence",
        "url": "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=ministry-of-defence",
    },
    "us_pentagon": {
        "name": "US Department of Defense",
        "url": "https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10",
    },
    "un_news": {
        "name": "UN News - Peace and Security",
        "url": "https://news.un.org/feed/subscribe/en/news/topic/peace-and-security/feed/rss.xml",
    },
    "breaking_defense": {
        "name": "Breaking Defense",
        "url": "https://breakingdefense.com/feed/",
    },
    "iss_africa": {
        "name": "Institute for Security Studies (Africa)",
        "url": "https://issafrica.org/rss",
    },
    "fiia_finland": {
        "name": "Finnish Institute of International Affairs (FIIA)",
        "url": "https://fiia.fi/feed",
    },
    "acled": {
        "name": "ACLED Research & Analysis",
        "url": "https://www.acleddata.com/feed/",
    },
}

# Disabled RSS feeds - still worth monitoring in case they come back
RSS_DISABLED: dict[str, dict[str, str]] = {
    "nato": {
        "name": "NATO Newsroom (disabled)",
        "url": "https://www.nato.int/cps/en/natolive/news.rss",
    },
    "eda": {
        "name": "European Defence Agency (disabled)",
        "url": "https://eda.europa.eu/news-and-events/news/rss",
    },
    "french_mod": {
        "name": "French Ministry of Defence (disabled)",
        "url": "https://www.defense.gouv.fr/actualites/rss.xml",
    },
    "german_bmvg": {
        "name": "German Federal Ministry of Defence (disabled)",
        "url": "https://www.bundeswehr.de/en/news/press-releases/rss",
    },
    "rusi": {
        "name": "RUSI (disabled)",
        "url": "https://rusi.org/feed/",
    },
    "iiss": {
        "name": "IISS (disabled)",
        "url": "https://www.iiss.org/rss/publications",
    },
    "sipri": {
        "name": "SIPRI (disabled)",
        "url": "https://www.sipri.org/rss.xml",
    },
    "foi_sweden": {
        "name": "Swedish Defence Research Agency (disabled)",
        "url": "https://www.foi.se/en/rss",
    },
    "nupi_norway": {
        "name": "NUPI Norway (disabled)",
        "url": "https://www.nupi.no/feed",
    },
    "diis_denmark": {
        "name": "DIIS Denmark (disabled)",
        "url": "https://www.diis.dk/en/rss",
    },
    "chatham_house": {
        "name": "Chatham House (disabled)",
        "url": "https://www.chathamhouse.org/rss.xml",
    },
    "iiss_military_balance": {
        "name": "IISS Military Balance Blog (disabled)",
        "url": "https://www.iiss.org/rss/blogs",
    },
}

# WorldMonitor API endpoints from mcp/worldmonitor_server.py TIERS
WORLDMONITOR_ENDPOINTS: dict[str, dict[str, str]] = {
    # Fast tier
    "wm_military_flights": {
        "name": "WorldMonitor Military Flights",
        "endpoint": "api/military-flights",
        "params": "",
    },
    "wm_ais_snapshot": {
        "name": "WorldMonitor AIS Snapshot",
        "endpoint": "api/ais-snapshot",
        "params": "candidates=true",
    },
    "wm_oref_alerts": {
        "name": "WorldMonitor OREF Alerts",
        "endpoint": "api/oref-alerts",
        "params": "",
    },
    "wm_telegram_feed": {
        "name": "WorldMonitor Telegram Feed",
        "endpoint": "api/telegram-feed",
        "params": "limit=50",
    },
    "wm_gpsjam": {
        "name": "WorldMonitor GPS Jamming",
        "endpoint": "api/gpsjam",
        "params": "",
    },
    # Medium tier
    "wm_bootstrap_fast": {
        "name": "WorldMonitor Bootstrap (fast)",
        "endpoint": "api/bootstrap",
        "params": "tier=fast",
    },
    "wm_bootstrap_slow": {
        "name": "WorldMonitor Bootstrap (slow)",
        "endpoint": "api/bootstrap",
        "params": "tier=slow",
    },
    "wm_acled_events": {
        "name": "WorldMonitor ACLED Events",
        "endpoint": "api/conflict/v1/list-acled-events",
        "params": "",
    },
    "wm_thermal_escalations": {
        "name": "WorldMonitor Thermal Escalations",
        "endpoint": "api/thermal/v1/list-thermal-escalations",
        "params": "max_items=12",
    },
    # Slow tier
    "wm_bis_policy_rates": {
        "name": "WorldMonitor BIS Policy Rates",
        "endpoint": "api/economic/v1/get-bis-policy-rates",
        "params": "",
    },
    "wm_bis_exchange_rates": {
        "name": "WorldMonitor BIS Exchange Rates",
        "endpoint": "api/economic/v1/get-bis-exchange-rates",
        "params": "",
    },
    "wm_bis_credit": {
        "name": "WorldMonitor BIS Credit",
        "endpoint": "api/economic/v1/get-bis-credit",
        "params": "",
    },
    "wm_energy_prices": {
        "name": "WorldMonitor Energy Prices",
        "endpoint": "api/economic/v1/get-energy-prices",
        "params": "",
    },
    "wm_trade_restrictions": {
        "name": "WorldMonitor Trade Restrictions",
        "endpoint": "api/trade/v1/get-trade-restrictions",
        "params": "countries=&limit=50",
    },
    "wm_trade_barriers": {
        "name": "WorldMonitor Trade Barriers",
        "endpoint": "api/trade/v1/get-trade-barriers",
        "params": "countries=&limit=50",
    },
    "wm_displacement": {
        "name": "WorldMonitor Displacement Summary",
        "endpoint": "api/displacement/v1/get-displacement-summary",
        "params": "flow_limit=50",
    },
    "wm_usni_fleet": {
        "name": "WorldMonitor USNI Fleet Report",
        "endpoint": "api/military/v1/get-usni-fleet-report",
        "params": "",
    },
    "wm_temporal_anomalies": {
        "name": "WorldMonitor Temporal Anomalies",
        "endpoint": "api/infrastructure/v1/list-temporal-anomalies",
        "params": "",
    },
}

# Procurement APIs from mcp/defence_sources_server.py
PROCUREMENT_APIS: dict[str, dict[str, str]] = {
    "contracts_finder": {
        "name": "UK Contracts Finder",
        "url": "https://www.contractsfinder.service.gov.uk/Published/Notices/PublicSearch/Search?NoticeSummaryDelta.Keywords=defence&NoticeSummaryDelta.Status=Published",
    },
    "ted_eu": {
        "name": "EU TED / OJEU",
        "url": "https://ted.europa.eu/api/v3.0/notices/search?q=defence&limit=1",
    },
}


# ---------------------------------------------------------------------------
# Health check logic
# ---------------------------------------------------------------------------

class SourceResult:
    """Result of a single source health check."""
    __slots__ = (
        "source_id", "source_name", "source_type", "url",
        "http_status", "response_bytes", "is_fresh", "error_message",
    )

    def __init__(
        self,
        source_id: str,
        source_name: str,
        source_type: str,
        url: str,
    ) -> None:
        self.source_id = source_id
        self.source_name = source_name
        self.source_type = source_type
        self.url = url
        self.http_status: int | None = None
        self.response_bytes: int | None = None
        self.is_fresh: bool | None = None
        self.error_message: str | None = None

    @property
    def status_label(self) -> str:
        if self.error_message:
            return "DEAD"
        if self.http_status and self.http_status >= 400:
            return "DEAD"
        if self.is_fresh is False:
            return "DEGRADED"
        return "HEALTHY"


def _make_request(url: str, method: str = "GET", headers: dict | None = None) -> tuple[int, bytes]:
    """Make an HTTP request and return (status_code, body_bytes)."""
    hdrs = {"User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = resp.read()
        return resp.getcode(), body


def _check_rss_freshness(body: bytes) -> bool:
    """Check if the latest RSS/Atom item was published within the freshness window."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return False

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    now = datetime.now(timezone.utc)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Look back _FRESHNESS_HOURS from now
    from datetime import timedelta
    cutoff = now - timedelta(hours=_FRESHNESS_HOURS)

    # Try RSS 2.0 pubDate
    for item in root.findall(".//item"):
        pub = item.findtext("pubDate", "").strip()
        if pub:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(pub)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    return True
            except (ValueError, TypeError):
                pass

    # Try Atom updated/published
    for entry in root.findall("atom:entry", ns):
        for tag in ("atom:updated", "atom:published"):
            val = entry.findtext(tag, namespaces=ns, default="").strip()
            if val:
                try:
                    dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    if dt >= cutoff:
                        return True
                except (ValueError, TypeError):
                    pass

    # If we got items but none are fresh
    has_items = bool(root.findall(".//item") or root.findall("atom:entry", ns))
    if has_items:
        return False

    # No items at all - can't determine freshness
    return False


def check_rss(source_id: str, name: str, url: str) -> SourceResult:
    """Check an RSS/Atom feed source."""
    result = SourceResult(source_id, name, "rss", url)
    try:
        status, body = _make_request(url)
        result.http_status = status
        result.response_bytes = len(body)
        if status < 400 and len(body) > 0:
            result.is_fresh = _check_rss_freshness(body)
        else:
            result.is_fresh = False
    except urllib.error.HTTPError as e:
        result.http_status = e.code
        result.response_bytes = 0
        result.error_message = f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        result.error_message = f"URL error: {e.reason}"
    except Exception as e:
        result.error_message = str(e)[:200]
    return result


def check_worldmonitor_endpoint(source_id: str, meta: dict[str, str]) -> SourceResult:
    """Check a WorldMonitor API endpoint."""
    endpoint = meta["endpoint"]
    params = meta["params"]
    url = f"{_WORLDMONITOR_BASE}/{endpoint}"
    if params:
        url = f"{url}?{params}"

    result = SourceResult(source_id, meta["name"], "worldmonitor_api", url)
    try:
        headers: dict[str, str] = {}
        if _WORLDMONITOR_KEY:
            headers["Authorization"] = f"Bearer {_WORLDMONITOR_KEY}"
        headers["Accept"] = "application/json"

        status, body = _make_request(url, headers=headers)
        result.http_status = status
        result.response_bytes = len(body)

        # Fresh if we got a non-empty JSON response
        if status < 400 and len(body) > 2:
            try:
                data = json.loads(body)
                # Non-empty response counts as fresh
                result.is_fresh = bool(data) if isinstance(data, (dict, list)) else len(body) > 2
            except json.JSONDecodeError:
                result.is_fresh = False
        else:
            result.is_fresh = False
    except urllib.error.HTTPError as e:
        result.http_status = e.code
        result.response_bytes = 0
        result.error_message = f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        result.error_message = f"URL error: {e.reason}"
    except Exception as e:
        result.error_message = str(e)[:200]
    return result


def check_procurement_api(source_id: str, meta: dict[str, str]) -> SourceResult:
    """Check a procurement API endpoint."""
    result = SourceResult(source_id, meta["name"], "procurement_api", meta["url"])
    try:
        headers = {"Accept": "application/json"}
        status, body = _make_request(meta["url"], headers=headers)
        result.http_status = status
        result.response_bytes = len(body)

        if status < 400 and len(body) > 2:
            try:
                json.loads(body)
                result.is_fresh = True
            except json.JSONDecodeError:
                # Some procurement APIs return HTML - still alive if 200
                result.is_fresh = status == 200
        else:
            result.is_fresh = False
    except urllib.error.HTTPError as e:
        result.http_status = e.code
        result.response_bytes = 0
        result.error_message = f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        result.error_message = f"URL error: {e.reason}"
    except Exception as e:
        result.error_message = str(e)[:200]
    return result


# ---------------------------------------------------------------------------
# Database write
# ---------------------------------------------------------------------------

def write_results(db: str, results: list[SourceResult]) -> None:
    """Write all check results to the source_health table."""
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(db, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
        for r in results:
            con.execute(
                """INSERT INTO source_health
                   (source_id, source_name, source_type, url,
                    http_status, response_bytes, is_fresh, error_message, checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r.source_id, r.source_name, r.source_type, r.url,
                    r.http_status, r.response_bytes, r.is_fresh, r.error_message,
                    now,
                ),
            )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Channel push
# ---------------------------------------------------------------------------

def push_to_meridian(results: list[SourceResult]) -> None:
    """Push health summary to Meridian platform via channel_push if available."""
    try:
        # Try importing from the shared scripts directory
        script_dir = Path(__file__).resolve().parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        from channel_push import push_briefing
    except ImportError:
        return

    healthy = sum(1 for r in results if r.status_label == "HEALTHY")
    degraded = sum(1 for r in results if r.status_label == "DEGRADED")
    dead = sum(1 for r in results if r.status_label == "DEAD")
    total = len(results)

    # Build body
    lines = [f"**{total} sources checked** - {healthy} healthy, {degraded} degraded, {dead} dead\n"]

    if dead > 0:
        lines.append("### Dead sources")
        for r in results:
            if r.status_label == "DEAD":
                err = r.error_message or f"HTTP {r.http_status}"
                lines.append(f"- {r.source_name} ({r.source_type}): {err}")
        lines.append("")

    if degraded > 0:
        lines.append("### Degraded sources (stale content)")
        for r in results:
            if r.status_label == "DEGRADED":
                lines.append(f"- {r.source_name} ({r.source_type}): HTTP {r.http_status}, {r.response_bytes or 0} bytes, not fresh")
        lines.append("")

    body_md = "\n".join(lines)

    if dead > 0:
        title = f"Source Health: {dead} dead, {degraded} degraded out of {total}"
    elif degraded > 0:
        title = f"Source Health: {degraded} degraded out of {total}"
    else:
        title = f"Source Health: all {total} sources healthy"

    summary = f"{healthy} green / {degraded} amber / {dead} red out of {total} total"

    push_briefing("source_health", title=title, summary=summary, body_md=body_md)


# ---------------------------------------------------------------------------
# Summary output
# ---------------------------------------------------------------------------

def print_summary(results: list[SourceResult]) -> None:
    """Print a formatted summary to stdout."""
    healthy = [r for r in results if r.status_label == "HEALTHY"]
    degraded = [r for r in results if r.status_label == "DEGRADED"]
    dead = [r for r in results if r.status_label == "DEAD"]

    print(f"\n{'='*60}")
    print(f"  SOURCE HEALTH DASHBOARD")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")
    print(f"\n  Total:    {len(results)}")
    print(f"  Healthy:  {len(healthy)}")
    print(f"  Degraded: {len(degraded)}")
    print(f"  Dead:     {len(dead)}")

    # Group by source_type
    by_type: dict[str, list[SourceResult]] = {}
    for r in results:
        by_type.setdefault(r.source_type, []).append(r)

    for stype, items in sorted(by_type.items()):
        print(f"\n  --- {stype.upper().replace('_', ' ')} ---")
        for r in sorted(items, key=lambda x: x.source_name):
            label = r.status_label
            icon = {"HEALTHY": "[OK]", "DEGRADED": "[~~]", "DEAD": "[XX]"}[label]
            status_str = f"HTTP {r.http_status}" if r.http_status else "no response"
            size_str = f"{r.response_bytes:,}B" if r.response_bytes else "0B"
            fresh_str = ""
            if r.is_fresh is True:
                fresh_str = " fresh"
            elif r.is_fresh is False:
                fresh_str = " stale"
            err_str = f" - {r.error_message}" if r.error_message else ""
            print(f"    {icon} {r.source_name}: {status_str}, {size_str}{fresh_str}{err_str}")

    print(f"\n{'='*60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    db = _db_path()
    print(f"Intelligence DB: {db}")

    # Ensure schema exists
    try:
        ensure_schema(db)
    except sqlite3.OperationalError as e:
        print(f"Warning: could not create schema (DB may be locked): {e}", file=sys.stderr)
        print("Will attempt to write results anyway (table may already exist).", file=sys.stderr)

    results: list[SourceResult] = []

    # 1. Active RSS feeds
    print("\nChecking active RSS feeds...")
    for sid, meta in RSS_FEEDS.items():
        print(f"  -> {meta['name']}...", end="", flush=True)
        r = check_rss(sid, meta["name"], meta["url"])
        results.append(r)
        print(f" {r.status_label}")

    # 2. Disabled RSS feeds (check if any have come back)
    print("\nChecking disabled RSS feeds...")
    for sid, meta in RSS_DISABLED.items():
        print(f"  -> {meta['name']}...", end="", flush=True)
        r = check_rss(f"disabled_{sid}", meta["name"], meta["url"])
        r.source_type = "rss_disabled"
        results.append(r)
        print(f" {r.status_label}")

    # 3. WorldMonitor API endpoints
    print("\nChecking WorldMonitor API endpoints...")
    for sid, meta in WORLDMONITOR_ENDPOINTS.items():
        print(f"  -> {meta['name']}...", end="", flush=True)
        r = check_worldmonitor_endpoint(sid, meta)
        results.append(r)
        print(f" {r.status_label}")

    # 4. Procurement APIs
    print("\nChecking procurement APIs...")
    for sid, meta in PROCUREMENT_APIS.items():
        print(f"  -> {meta['name']}...", end="", flush=True)
        r = check_procurement_api(sid, meta)
        results.append(r)
        print(f" {r.status_label}")

    # Print summary
    print_summary(results)

    # Write to DB
    try:
        write_results(db, results)
        print(f"Results written to {db}")
    except sqlite3.OperationalError as e:
        print(f"Warning: could not write results to DB: {e}", file=sys.stderr)
        print("Database may be locked by another process.", file=sys.stderr)

    # Push to Meridian
    push_to_meridian(results)


if __name__ == "__main__":
    main()

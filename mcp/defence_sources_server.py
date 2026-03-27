#!/usr/bin/env python3
"""Defence Sources MCP server for the Atrophy companion agent.

General-purpose primary source access for intelligence production:
  - Feed catalog of official bodies, specialist press, and national institutes
  - Fetch any subset of feeds by source ID (or all)
  - UK procurement: Contracts Finder REST API
  - EU procurement: TED/OJEU REST API

Any agent can call these tools with whatever source selection and keywords
suit their domain. The catalog is the full set; the agent decides the scope.

Protocol: JSON-RPC 2.0 over stdio (MCP standard transport).
stdlib only - no pip dependencies.
Cache: ~/.atrophy/defence_sources_cache.db (SQLite, TTL per type).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
try:
    from defusedxml.ElementTree import fromstring as _safe_fromstring
except ImportError:
    from xml.etree.ElementTree import fromstring as _safe_fromstring
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

_SERVER_VERSION = "1.1.0"
_CACHE_DB_DEFAULT = str(
    __import__("pathlib").Path.home() / ".atrophy" / "defence_sources_cache.db"
)
_TIMEOUT = 20
_USER_AGENT = "Atrophy/1.0 (Defence Sources MCP)"

_TTL_FEEDS   = timedelta(hours=6)
_TTL_PROCURE = timedelta(hours=12)

# ---------------------------------------------------------------------------
# Feed catalog - all available sources
# Each entry: id, name, country/region, type, url
# ---------------------------------------------------------------------------

FEED_CATALOG: dict[str, dict] = {
    # Official government / intergovernmental bodies
    # nato: RSS feed removed, all paths redirect to HTML (404/301 as of 2026-03)
    # "nato": {
    #     "name": "NATO Newsroom",
    #     "region": "NATO",
    #     "type": "official",
    #     "url": "https://www.nato.int/cps/en/natolive/news.rss",
    # },
    # eda: RSS feed removed by eda.europa.eu (404 as of 2026-03)
    # "eda": {
    #     "name": "European Defence Agency",
    #     "region": "EU",
    #     "type": "official",
    #     "url": "https://eda.europa.eu/news-and-events/news/rss",
    # },
    "uk_mod": {
        "name": "UK Ministry of Defence",
        "region": "UK",
        "type": "official",
        "url": "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=ministry-of-defence",
    },
    # french_mod: RSS feed removed by defense.gouv.fr (404 as of 2026-03)
    # "french_mod": {
    #     "name": "French Ministry of Defence (DGA)",
    #     "region": "France",
    #     "type": "official",
    #     "url": "https://www.defense.gouv.fr/actualites/rss.xml",
    # },
    # german_bmvg: RSS feed removed by bundeswehr.de (404 as of 2026-03)
    # "german_bmvg": {
    #     "name": "German Federal Ministry of Defence (BMVg)",
    #     "region": "Germany",
    #     "type": "official",
    #     "url": "https://www.bundeswehr.de/en/news/press-releases/rss",
    # },
    "us_pentagon": {
        "name": "US Department of Defense",
        "region": "US",
        "type": "official",
        "url": "https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10",
    },
    "un_news": {
        "name": "UN News - Peace and Security",
        "region": "Global",
        "type": "official",
        "url": "https://news.un.org/feed/subscribe/en/news/topic/peace-and-security/feed/rss.xml",
    },
    # Specialist defence analysis
    # rusi: RSS feed removed, redirects to 404 (as of 2026-03)
    # "rusi": {
    #     "name": "RUSI - Royal United Services Institute",
    #     "region": "UK",
    #     "type": "analysis",
    #     "url": "https://rusi.org/feed/",
    # },
    # iiss: RSS blocked with 403 (as of 2026-03)
    # "iiss": {
    #     "name": "IISS - International Institute for Strategic Studies",
    #     "region": "UK",
    #     "type": "analysis",
    #     "url": "https://www.iiss.org/rss/publications",
    # },
    "breaking_defense": {
        "name": "Breaking Defense",
        "region": "US/Global",
        "type": "analysis",
        "url": "https://breakingdefense.com/feed/",
    },
    # sipri: RSS feed removed by sipri.org (404 as of 2026-03)
    # "sipri": {
    #     "name": "SIPRI - Stockholm International Peace Research Institute",
    #     "region": "Sweden",
    #     "type": "analysis",
    #     "url": "https://www.sipri.org/rss.xml",
    # },
    "iss_africa": {
        "name": "Institute for Security Studies (Africa)",
        "region": "Africa",
        "type": "analysis",
        "url": "https://issafrica.org/rss",
    },
    # Nordic security institutes
    # foi_sweden: connection errors on all RSS paths (as of 2026-03)
    # "foi_sweden": {
    #     "name": "Swedish Defence Research Agency (FOI)",
    #     "region": "Sweden",
    #     "type": "nordic",
    #     "url": "https://www.foi.se/en/rss",
    # },
    "fiia_finland": {
        "name": "Finnish Institute of International Affairs (FIIA)",
        "region": "Finland",
        "type": "nordic",
        "url": "https://fiia.fi/feed",  # updated 2026-03 - www subdomain redirects
    },
    # nupi_norway: RSS feed removed by nupi.no (404 as of 2026-03)
    # "nupi_norway": {
    #     "name": "Norwegian Institute of International Affairs (NUPI)",
    #     "region": "Norway",
    #     "type": "nordic",
    #     "url": "https://www.nupi.no/feed",
    # },
    # diis_denmark: RSS feed removed by diis.dk (404 as of 2026-03)
    # "diis_denmark": {
    #     "name": "Danish Institute for International Studies (DIIS)",
    #     "region": "Denmark",
    #     "type": "nordic",
    #     "url": "https://www.diis.dk/en/rss",
    # },
    # Regional / thematic
    # chatham_house: RSS blocked with 403 (as of 2026-03)
    # "chatham_house": {
    #     "name": "Chatham House (RIIIA)",
    #     "region": "UK",
    #     "type": "analysis",
    #     "url": "https://www.chathamhouse.org/rss.xml",
    # },
    # iiss_military_balance: RSS blocked with 403 (as of 2026-03)
    # "iiss_military_balance": {
    #     "name": "IISS Military Balance Blog",
    #     "region": "UK",
    #     "type": "analysis",
    #     "url": "https://www.iiss.org/rss/blogs",
    # },
    "acled": {
        "name": "ACLED Research & Analysis",
        "region": "Global",
        "type": "analysis",
        "url": "https://www.acleddata.com/feed/",
    },
}


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

class SourceCache:
    def __init__(self, db_path: str) -> None:
        self._db = db_path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        con = sqlite3.connect(self._db)
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    cache_key  TEXT PRIMARY KEY,
                    source_id  TEXT NOT NULL,
                    response   TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
            """)
            con.commit()
        finally:
            con.close()

    def get(self, key: str, ttl: timedelta) -> str | None:
        con = sqlite3.connect(self._db)
        try:
            cur = con.execute(
                "SELECT response, fetched_at FROM cache WHERE cache_key = ?", (key,)
            )
            row = cur.fetchone()
            if not row:
                return None
            if datetime.now(timezone.utc) - datetime.fromisoformat(row[1]) > ttl:
                return None
            return row[0]
        finally:
            con.close()

    def put(self, key: str, source_id: str, response: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        con = sqlite3.connect(self._db)
        try:
            con.execute(
                """INSERT INTO cache (cache_key, source_id, response, fetched_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET
                     response=excluded.response, fetched_at=excluded.fetched_at""",
                (key, source_id, response, now),
            )
            con.commit()
        finally:
            con.close()


# ---------------------------------------------------------------------------
# RSS fetcher
# ---------------------------------------------------------------------------

def _fetch_rss(url: str) -> list[dict]:
    """Fetch and parse an RSS 2.0 or Atom feed. Returns list of item dicts."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        raw = resp.read()

    root = _safe_fromstring(raw)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = []

    # RSS 2.0
    for item in root.findall(".//item"):
        items.append({
            "title":     (item.findtext("title") or "").strip(),
            "link":      (item.findtext("link") or "").strip(),
            "summary":   (item.findtext("description") or "").strip()[:300],
            "published": (item.findtext("pubDate") or "").strip(),
        })

    # Atom
    if not items:
        for entry in root.findall("atom:entry", ns):
            link_el = entry.find("atom:link", ns)
            items.append({
                "title":     (entry.findtext("atom:title", namespaces=ns) or "").strip(),
                "link":      (link_el.get("href") if link_el is not None else ""),
                "summary":   (entry.findtext("atom:summary", namespaces=ns) or "").strip()[:300],
                "published": (entry.findtext("atom:updated", namespaces=ns) or "").strip(),
            })

    return items[:15]


# ---------------------------------------------------------------------------
# MCP tool handlers
# ---------------------------------------------------------------------------

def handle_feeds_list(cache: SourceCache, args: dict) -> str:
    """Return the full feed catalog with IDs, names, regions, and types."""
    source_type = args.get("type", "")
    region = args.get("region", "")

    entries = []
    for fid, meta in FEED_CATALOG.items():
        if source_type and meta["type"] != source_type:
            continue
        if region and region.lower() not in meta["region"].lower():
            continue
        entries.append({
            "id":     fid,
            "name":   meta["name"],
            "region": meta["region"],
            "type":   meta["type"],
        })

    return json.dumps({
        "count": len(entries),
        "sources": entries,
        "note": "Pass source IDs to defence_sources_feeds_fetch to retrieve items.",
    }, indent=2)


def handle_feeds_fetch(cache: SourceCache, args: dict) -> str:
    """Fetch items from specified feeds (or all), with optional keyword filter."""
    requested_ids = args.get("sources", [])
    keywords = [k.lower() for k in args.get("keywords", [])]
    max_per_feed = int(args.get("limit", 5))

    # Resolve which feeds to fetch
    if requested_ids:
        feeds_to_fetch = {
            fid: FEED_CATALOG[fid]
            for fid in requested_ids
            if fid in FEED_CATALOG
        }
        unknown = [fid for fid in requested_ids if fid not in FEED_CATALOG]
    else:
        feeds_to_fetch = FEED_CATALOG
        unknown = []

    results = []
    statuses = {}

    for fid, meta in feeds_to_fetch.items():
        cached = cache.get(fid, _TTL_FEEDS)
        if cached:
            items = json.loads(cached)
            statuses[fid] = "cached"
        else:
            try:
                items = _fetch_rss(meta["url"])
                cache.put(fid, fid, json.dumps(items))
                statuses[fid] = "live"
            except Exception as exc:
                statuses[fid] = f"error: {exc}"
                items = []

        count = 0
        for item in items:
            if count >= max_per_feed:
                break
            if keywords:
                title_lower = item.get("title", "").lower()
                summary_lower = item.get("summary", "").lower()
                if not any(kw in title_lower or kw in summary_lower for kw in keywords):
                    continue
            results.append({
                "source_id": fid,
                "source":    meta["name"],
                "region":    meta["region"],
                "type":      meta["type"],
                "title":     item.get("title", ""),
                "link":      item.get("link", ""),
                "summary":   item.get("summary", ""),
                "published": item.get("published", ""),
            })
            count += 1

    output = {
        "items":         results,
        "total":         len(results),
        "feed_statuses": statuses,
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
    }
    if unknown:
        output["unknown_ids"] = unknown

    return json.dumps(output, indent=2)


def handle_procurement_uk(cache: SourceCache, args: dict) -> str:
    """UK Contracts Finder - free REST API, no auth required."""
    keywords = args.get("keywords", "defence military")
    cache_key = f"contracts_finder:{keywords}"
    cached = cache.get(cache_key, _TTL_PROCURE)
    if cached:
        results, source = json.loads(cached), "cached"
    else:
        try:
            base = "https://www.contractsfinder.service.gov.uk/Published/Notices/PublicSearch/Search"
            params = {
                "NoticeSummaryDelta.Keywords": keywords,
                "NoticeSummaryDelta.Status": "Published",
            }
            url = f"{base}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(
                url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read())
            notices = data.get("noticeList", data) if isinstance(data, dict) else data
            results = [
                {
                    "title": n.get("title", ""),
                    "buyer": n.get("organisationName") or n.get("buyer", ""),
                    "value": n.get("value") or n.get("contractValue", ""),
                    "date":  n.get("publishedDate") or n.get("publicationDate", ""),
                    "ref":   n.get("noticeIdentifier") or n.get("id", ""),
                }
                for n in (notices if isinstance(notices, list) else [])[:15]
            ]
            cache.put(cache_key, "contracts_finder", json.dumps(results))
            source = "live"
        except Exception as exc:
            return json.dumps({"error": str(exc), "source": "contracts_finder"}, indent=2)

    return json.dumps({
        "source":     f"UK Contracts Finder ({source})",
        "keywords":   keywords,
        "count":      len(results),
        "contracts":  results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


def handle_procurement_eu(cache: SourceCache, args: dict) -> str:
    """EU TED / OJEU - European public procurement notices, open API."""
    keywords = args.get("keywords", "defence military armament")
    cache_key = f"ted:{keywords}"
    cached = cache.get(cache_key, _TTL_PROCURE)
    if cached:
        results, source = json.loads(cached), "cached"
    else:
        try:
            params = {
                "q":         keywords,
                "scope":     "ALL",
                "fields":    "noticeNo,title,publicationDate,buyerDetails,contractType,placeOfPerformance",
                "limit":     "15",
                "sortField": "publicationDate",
                "sortOrder": "desc",
            }
            url = f"https://ted.europa.eu/api/v3.0/notices/search?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(
                url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read())
            notices = data.get("notices", data.get("results", []))
            results = []
            for n in (notices if isinstance(notices, list) else [])[:15]:
                title = n.get("title", {})
                if isinstance(title, dict):
                    title = title.get("en") or next(iter(title.values()), "")
                buyer = n.get("buyerDetails", {})
                if isinstance(buyer, dict):
                    buyer = buyer.get("officialName") or buyer.get("name", "")
                results.append({
                    "ref":    n.get("noticeNo", ""),
                    "title":  title,
                    "buyer":  buyer,
                    "date":   n.get("publicationDate", ""),
                    "type":   n.get("contractType", ""),
                    "region": n.get("placeOfPerformance", ""),
                })
            cache.put(cache_key, "ted", json.dumps(results))
            source = "live"
        except Exception as exc:
            return json.dumps({"error": str(exc), "source": "ted_api"}, indent=2)

    return json.dumps({
        "source":     f"EU TED / OJEU ({source})",
        "keywords":   keywords,
        "count":      len(results),
        "notices":    results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool manifest
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "defence_sources_feeds_list",
        "description": (
            "List all available primary source feeds in the catalog. "
            "Returns IDs, names, regions, and types. "
            "Filter by type ('official', 'analysis', 'nordic') or region keyword. "
            "Use returned IDs with defence_sources_feeds_fetch."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Filter by source type: 'official', 'analysis', 'nordic'",
                },
                "region": {
                    "type": "string",
                    "description": "Filter by region keyword (e.g. 'Nordic', 'UK', 'EU')",
                },
            },
        },
    },
    {
        "name": "defence_sources_feeds_fetch",
        "description": (
            "Fetch items from one or more primary source feeds. "
            "Pass a list of source IDs (from defence_sources_feeds_list) or omit for all. "
            "Optionally filter by keywords. Returns titles, links, summaries, and per-feed status. "
            "Available sources include: UK MoD, US Pentagon, UN News, "
            "Breaking Defense, ISS Africa, FIIA (Finland), ACLED."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of source IDs to fetch (empty = all sources)",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional keywords to filter items by (matched against title and summary)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max items per source (default 5)",
                    "default": 5,
                },
            },
        },
    },
    {
        "name": "defence_sources_procurement_uk",
        "description": (
            "Search UK Contracts Finder for procurement notices. "
            "Free REST API, no auth required. "
            "Returns contract title, buyer organisation, value, and publication date."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "Search keywords (default: 'defence military')",
                    "default": "defence military",
                },
            },
        },
    },
    {
        "name": "defence_sources_procurement_eu",
        "description": (
            "Search EU TED / OJEU for European procurement notices. "
            "Covers German, French, Nordic, and EU-institution contracts. "
            "Returns notice reference, title, buyer, date, contract type, and region."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "Search keywords (default: 'defence military armament')",
                    "default": "defence military armament",
                },
            },
        },
    },
]

HANDLERS = {
    "defence_sources_feeds_list":     handle_feeds_list,
    "defence_sources_feeds_fetch":    handle_feeds_fetch,
    "defence_sources_procurement_uk": handle_procurement_uk,
    "defence_sources_procurement_eu": handle_procurement_eu,
}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 server
# ---------------------------------------------------------------------------

def handle_request(cache: SourceCache, request: dict) -> dict | None:
    method = request.get("method", "")
    params = request.get("params", {}) or {}

    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "defence_sources", "version": _SERVER_VERSION},
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        handler = HANDLERS.get(tool_name)
        if not handler:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            }
        try:
            return {"content": [{"type": "text", "text": handler(cache, arguments)}]}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            }
    return None


def main() -> None:
    cache_db = os.environ.get("DEFENCE_SOURCES_CACHE_DB", _CACHE_DB_DEFAULT)
    cache = SourceCache(cache_db)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        if "id" not in request:
            handle_request(cache, request)
            continue

        result = handle_request(cache, request)
        if result is None:
            continue

        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

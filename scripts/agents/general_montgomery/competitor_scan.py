#!/usr/bin/env python3
"""
Competitor Scan
Runs weekdays 09:00. Monitors RUSI, ISW, IISS, Chatham House, CSIS, RAND
for new publications. Flags to Montgomery for response or differentiated analysis.

Uses RSS feeds where available, falls back to web scraping index pages.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import urllib.request
try:
    from defusedxml.ElementTree import fromstring as _safe_fromstring
except ImportError:
    from xml.etree.ElementTree import fromstring as _safe_fromstring
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.telegram_utils import send_telegram
from shared.credentials import load_telegram_credentials

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON  = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB    = _AGENT_DIR / "data" / "intelligence.db"
_STATE_FILE  = _AGENT_DIR / "data" / "competitor_scan_state.json"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "general_montgomery"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CompScan] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "competitor_scan.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("competitor_scan")

THINK_TANKS = {
    "CSIS": {
        "rss": "https://www.csis.org/rss.xml",
        "label": "CSIS",
        "priority": 1,
    },
    "Atlantic Council": {
        "rss": "https://www.atlanticcouncil.org/feed/",
        "label": "Atlantic Council",
        "priority": 1,
    },
    "The Diplomat": {
        "rss": "https://thediplomat.com/feed/",
        "label": "The Diplomat",
        "priority": 2,
    },
    "ECFR": {
        "rss": "https://ecfr.eu/rss/",
        "label": "ECFR",
        "priority": 2,
    },
    "Bellingcat": {
        "rss": "https://www.bellingcat.com/feed/",
        "label": "Bellingcat",
        "priority": 2,
    },
    "Carnegie": {
        "rss": "https://carnegieendowment.org/rss/solr",
        "label": "Carnegie Endowment",
        "priority": 3,
    },
}

MERIDIAN_KEYWORDS = [
    "ukraine", "russia", "iran", "china", "taiwan", "nato", "nuclear",
    "gulf", "israel", "hamas", "hezbollah", "houthi", "red sea",
    "sudan", "sahel", "indo-pacific", "aukus", "hypersonic", "drone",
    "sanctions", "deterrence", "escalation", "cyber warfare",
    "great power", "hybrid war", "grey zone",
]


def load_state() -> dict:
    if _STATE_FILE.exists():
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"seen_urls": []}


def save_state(state: dict):
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f)


def load_cfg():
    with open(_AGENT_JSON) as f:
        return json.load(f)




def fetch_rss(url: str, label: str) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of {title, url, summary, date}."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Meridian Intelligence Monitor; research)"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()

        root = _safe_fromstring(content)
        ns = ""
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")

        results = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=2)

        for item in items[:20]:
            def get(tag, ns=""):
                el = item.find(f"{ns}{tag}")
                return el.text.strip() if el is not None and el.text else ""

            title = get("title")
            link = get("link") or get("guid")
            summary = get("description") or get("summary")
            pub_date = get("pubDate") or get("updated") or get("published")

            # Try to parse date
            try:
                for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ",
                            "%Y-%m-%dT%H:%M:%S%z"]:
                    try:
                        dt = datetime.strptime(pub_date[:30], fmt)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt < cutoff:
                            continue
                        break
                    except ValueError:
                        continue
            except Exception:
                pass  # include if date parsing fails

            if title and link:
                results.append({
                    "source": label,
                    "title": title,
                    "url": link,
                    "summary": re.sub(r'<[^>]+>', '', summary or "")[:300],
                    "date": pub_date[:10] if pub_date else "",
                })

        return results

    except Exception as e:
        log.debug(f"{label} RSS fetch failed: {e}")
        return []


def score_item(item: dict) -> int:
    text = (item["title"] + " " + item["summary"]).lower()
    score = 0
    for kw in MERIDIAN_KEYWORDS:
        if kw in text:
            score += 1
    return score


def log_to_db(conn: sqlite3.Connection, content: str, new_count: int):
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO briefs (requested_by, date, title, content, created_at)
        VALUES (?, date('now'), ?, ?, ?)
    """, (
        "general_montgomery",
        f"Competitor Scan - {datetime.now().strftime('%Y-%m-%d')}",
        content,
        now
    ))
    conn.commit()


def main():
    log.info("Competitor scan starting")
    cfg = load_cfg()
    state = load_state()
    seen_urls = set(state.get("seen_urls", []))

    all_items = []
    for name, config in THINK_TANKS.items():
        items = fetch_rss(config["rss"], config["label"])
        log.debug(f"{name}: {len(items)} items from RSS")
        all_items.extend(items)

    # Filter to new items only
    new_items = [i for i in all_items if i["url"] not in seen_urls]
    log.info(f"{len(new_items)} new items from {len(THINK_TANKS)} sources")

    if not new_items:
        log.info("Nothing new today")
        return

    # Score and select relevant items
    scored = sorted(
        [i for i in new_items if score_item(i) > 0],
        key=score_item, reverse=True
    )[:10]

    # Update seen URLs
    for item in new_items:
        seen_urls.add(item["url"])
    save_state({"seen_urls": list(seen_urls)[-500:]})  # keep last 500

    if not scored:
        log.info("No items matched Meridian keywords")
        return

    now_str = datetime.now().strftime("%d %b %Y")
    lines = [
        f"*COMPETITOR SCAN - {now_str}*",
        f"_{len(scored)} relevant publications from think tanks_",
        "",
    ]

    for item in scored:
        relevance = score_item(item)
        lines.append(f"*[{item['source']}]* {item['title']}")
        if item["summary"]:
            lines.append(f"_{item['summary'][:200]}_")
        lines.append(f"Relevance: {relevance} | {item['date']}")
        lines.append("")

    conn = sqlite3.connect(_INTEL_DB)

    # Run synthesis layer - compare competitor output against our DB assessments
    synthesis_report = None
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from competitor_synthesis import run_synthesis
        synthesis_report = run_synthesis(scored, conn)
        log.info("Synthesis complete")
    except Exception as e:
        log.warning(f"Synthesis layer failed - falling back to raw scan: {e}")

    # Use synthesis if available, otherwise fall back to raw aggregation
    if synthesis_report:
        report = synthesis_report
    else:
        lines.append("_Sources: RUSI, ISW, IISS, Chatham House, CSIS, RAND_")
        report = "\n".join(lines)

    log_to_db(conn, report, len(scored))
    conn.close()

    try:
        send_telegram(*load_telegram_credentials("general_montgomery"), report)
        log.info(f"Competitor scan sent: {len(scored)} items")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


if __name__ == "__main__":
    main()

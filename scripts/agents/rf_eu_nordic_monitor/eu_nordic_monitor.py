#!/usr/bin/env python3
"""
EU-Nordic Defence Monitor - every 3 days, 07:30 UTC.

Five key developments in UK, Nordic, Germany, France and broader European
defence and industrial affairs. Modelled on the Henry Simpson newsletter format.

Structure per issue:
  - Five numbered items (UK / Germany / Nordic / France / Europe-wide)
  - Editor's note (cross-cutting analytical thread)
  - Sources (outlets referenced per country)
  - Footer

Pulls WorldMonitor news digest for live context plus recent intelligence.db
briefs for continuity. Sends to Telegram and logs to briefs table.
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
_AGENT_JSON  = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "agent.json"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "rf_eu_nordic_monitor"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_APP_DIR / "mcp"))
sys.path.insert(0, str(_APP_DIR / "scripts" / "agents" / "shared"))

from claude_cli import call_claude  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EU-Nordic] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "eu_nordic_monitor.log"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("eu_nordic_monitor")


MONITOR_SYSTEM = """You are the EU-Nordic Defence Monitor, a recurring intelligence product of the Meridian Institute.

Your task: identify five key developments in UK, Nordic (Sweden/Norway/Finland/Denmark), German, French, and broader European defence and industrial affairs from the past three days.

OUTPUT FORMAT - follow this precisely:

1 of 5
[COUNTRY/REGION IN ALL CAPS - e.g. UNITED KINGDOM]
[Headline: one precise sentence, max 15 words]
[3-5 sentence analytical paragraph: what happened, procurement or industrial significance, strategic context, what it reveals about rearmament]

2 of 5
[Repeat for GERMANY]

3 of 5
[Repeat for NORDIC]

4 of 5
[Repeat for FRANCE]

5 of 5
[Repeat for EUROPE-WIDE]

Editor's note: [One paragraph, 3-5 sentences, drawing out the common thread or structural tension running across all five items. This is the synthesis layer - identify the pattern, the gap, the contradiction, or the implication that the individual items alone do not surface. Do not summarise the items. Advance the analysis.]

Sources:
UK: [list 2-3 named publications/outlets]
Germany: [list 2-3 named publications/outlets]
Nordic: [list 2-3 named publications/outlets]
France: [list 2-3 named publications/outlets]
Europe-wide: [list 2-3 named publications/outlets]

---
Focus for all items:
- Defence contracts, procurement awards, programme decisions
- Budget allocations and what they actually fund vs stated ambition
- Industrial base capacity, production bottlenecks, scaling challenges
- Exercise activity as a readiness signal
- National defence industrial strategies and their coherence gaps

Constraints:
- No em dashes anywhere
- No bullet points within analytical paragraphs
- Each item self-contained
- Editor's note must not simply restate - it must add analytical value
- If live context is thin on a country, draw on the standing picture and state posture clearly
- Under 750 words total for the five items; Editor's note 80-120 words; Sources brief

Do NOT include a header line or date - the caller adds those. Start directly with "1 of 5"."""


def fetch_news_context() -> str:
    """Pull WorldMonitor news digest plus primary defence sources."""
    parts = []

    # WorldMonitor digest (Europe/intel/thinktanks categories)
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(
            cache_db=str(Path.home() / ".atrophy" / "worldmonitor_cache.db")
        )
        data, _delta = client.fetch_cached("api/news/v1/list-feed-digest")
        if data and isinstance(data, dict):
            cats = data.get("categories", {})
            eu_items = []
            for cat in ["europe", "intel", "thinktanks"]:
                cat_data = cats.get(cat, {})
                articles = cat_data.get("articles", cat_data.get("items", []))
                for a in articles[:8]:
                    eu_items.append(f"[{a.get('source','')}] {a.get('title','')}")
            if eu_items:
                parts.append("WORLDMONITOR (europe/intel/thinktanks):\n" + "\n".join(eu_items))
    except Exception as e:
        log.warning(f"WorldMonitor fetch failed: {e}")

    # Primary defence sources via catalogue
    try:
        from defence_sources_server import SourceCache, handle_feeds_fetch
        ds_cache = SourceCache(str(Path.home() / ".atrophy" / "defence_sources_cache.db"))

        eu_sources = [
            "nato", "eda", "uk_mod", "french_mod", "german_bmvg",
            "rusi", "iiss", "breaking_defense", "sipri",
            "foi_sweden", "fiia_finland", "nupi_norway", "diis_denmark",
            "chatham_house",
        ]
        fetched = json.loads(handle_feeds_fetch(ds_cache, {
            "sources": eu_sources,
            "limit": 3,
        }))
        if fetched.get("items"):
            lines = [
                f"[{i['source']} / {i['region']}] {i['title']}"
                for i in fetched["items"]
            ]
            parts.append("PRIMARY SOURCES:\n" + "\n".join(lines))

    except Exception as e:
        log.warning(f"Defence sources fetch failed: {e}")

    return "\n\n".join(parts)[:6000] if parts else ""


def fetch_prior_briefs(db: sqlite3.Connection) -> str:
    """Pull recent EU/Nordic/UK/Germany/France briefs for continuity."""
    keywords = [
        "european", "nordic", "germany", "bundeswehr", "france", "uk defence",
        "nato", "rearmament", "industrial", "procurement",
    ]
    rows = []
    seen: set[str] = set()
    cur = db.cursor()
    for kw in keywords[:6]:
        cur.execute("""
            SELECT title, content, created_at FROM briefs
            WHERE (lower(content) LIKE ? OR lower(title) LIKE ?)
            AND requested_by != 'red_team'
            ORDER BY created_at DESC
            LIMIT 2
        """, (f"%{kw}%", f"%{kw}%"))
        for title, content, created_at in cur.fetchall():
            if title not in seen:
                seen.add(title)
                date_str = (created_at or "")[:10]
                rows.append(f"[{date_str}] {title}\n{(content or '')[:300]}")

    return "\n\n".join(rows[:3000]) if rows else ""


def generate_monitor(news: str, prior: str, date_str: str) -> str:
    parts = []
    if news:
        parts.append(f"LIVE NEWS DIGEST:\n{news}")
    if prior:
        parts.append(f"PRIOR MERIDIAN ASSESSMENTS:\n{prior}")
    if not parts:
        parts.append("No live data. Provide standing assessment from established knowledge.")

    prompt = f"Issue date: {date_str}\n\n" + "\n\n".join(parts)
    return call_claude(MONITOR_SYSTEM, prompt, model="sonnet", timeout=360)


def load_credentials() -> tuple[str, str]:
    with open(_AGENT_JSON) as f:
        d = json.load(f)
    return d["telegram_bot_token"], d["telegram_chat_id"]


def send_telegram(token: str, chat_id: str, text: str) -> None:
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")


def send_in_parts(token: str, chat_id: str, header: str, content: str) -> None:
    """Send the monitor, splitting at item boundaries if needed."""
    full = header + content
    if len(full) <= 4096:
        send_telegram(token, chat_id, full)
        return

    # Find a clean split point - after item 3, before item 4
    for marker in ["\n\n4 of 5", "\n\n3 of 5", "\n\nEditor's note"]:
        idx = content.find(marker)
        if idx != -1 and idx > 400:
            send_telegram(token, chat_id, header + content[:idx])
            send_telegram(token, chat_id, content[idx:])
            return

    # Fallback: hard split
    send_telegram(token, chat_id, full[:4000])
    send_telegram(token, chat_id, full[4000:])


def get_issue_number(db: sqlite3.Connection) -> int:
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM briefs WHERE requested_by = 'rf_eu_nordic_monitor'")
    row = cur.fetchone()
    return (row[0] if row else 0) + 1


def run() -> None:
    log.info("EU-Nordic Defence Monitor starting")
    db = sqlite3.connect(str(_INTEL_DB))
    date_str  = datetime.now(timezone.utc).strftime("%d %B %Y")
    iso_date  = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        issue_num = get_issue_number(db)
        news  = fetch_news_context()
        prior = fetch_prior_briefs(db)

        log.info(f"Issue {issue_num}: news={len(news)}c prior={len(prior)}c")

        content = generate_monitor(news, prior, date_str)

        footer = (
            f"\n\n---\n"
            f"_EU-Nordic Defence Monitor  |  Issue {issue_num}  |  "
            f"Delivered every 3 days  |  Prepared by Claude for Henry Simpson_"
        )
        header = (
            f"*EU-NORDIC DEFENCE MONITOR*\n"
            f"Issue {issue_num}  |  {date_str}\n"
            f"Five key developments in UK, Nordic, Germany & France "
            f"defence and industrial affairs\n\n"
        )

        full_brief = header.replace("*", "").replace("_", "") + content + footer.replace("_", "")

        # Log to intelligence.db
        db.execute("""
            INSERT INTO briefs (conflict_id, date, title, content, requested_by)
            VALUES (NULL, ?, ?, ?, 'rf_eu_nordic_monitor')
        """, (iso_date,
              f"EU-Nordic Defence Monitor - Issue {issue_num} ({iso_date})",
              full_brief))
        db.commit()
        log.info(f"Issue {issue_num} logged")

        # Send to Telegram
        token, chat_id = load_credentials()
        send_in_parts(token, chat_id, header, content + footer)
        log.info(f"Issue {issue_num} sent to Telegram")

    finally:
        db.close()

    log.info("EU-Nordic Defence Monitor complete")


if __name__ == "__main__":
    run()

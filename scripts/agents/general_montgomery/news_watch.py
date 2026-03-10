#!/usr/bin/env python3
"""Intelligence watch — fetch, assess, and file news items.

Runs every 30 minutes. Fetches headlines from multiple sources,
deduplicates against previously seen URLs, assesses strategic
significance via inference, and stores structured intelligence
in the database. Critical items are surfaced immediately.

Usage:
    python scripts/agents/general_montgomery/news_watch.py
"""

import json
import os
import sqlite3
import sys
import urllib.request
import defusedxml.ElementTree as ET
from datetime import datetime
from pathlib import Path

# Setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from config import DB_PATH, MESSAGE_QUEUE, AGENT_DISPLAY_NAME
from core.memory import init_db, write_observation
from core.inference import run_inference_oneshot
from core.embeddings import embed_text
from core.queue import queue_message

# ── RSS Sources ──

FEEDS = {
    # BBC World & Regional
    "bbc_world": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc_middle_east": "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    "bbc_europe": "http://feeds.bbci.co.uk/news/world/europe/rss.xml",
    "bbc_asia": "http://feeds.bbci.co.uk/news/world/asia/rss.xml",
    "bbc_us_canada": "http://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",

    # Wire services via Google News proxy
    "reuters": "https://news.google.com/rss/search?q=site:reuters.com+when:1h&hl=en-US&gl=US&ceid=US:en",
    "ap": "https://news.google.com/rss/search?q=site:apnews.com+when:1h&hl=en-US&gl=US&ceid=US:en",

    # Defence & military
    "defense_one": "https://www.defenseone.com/rss/",
    "war_zone": "https://www.thedrive.com/the-war-zone/feed",
    "breaking_defense": "https://breakingdefense.com/feed/",
    "war_on_rocks": "https://warontherocks.com/feed/",

    # Geopolitical
    "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "diplomat": "https://thediplomat.com/feed/",
    "bellingcat": "https://www.bellingcat.com/feed/",

    # Think tanks — UK
    "rusi": "https://www.rusi.org/rss.xml",
    "iiss": "https://www.iiss.org/rss",
    "chatham_house": "https://www.chathamhouse.org/rss.xml",

    # Think tanks — US
    "csis": "https://www.csis.org/rss.xml",
    "isw": "https://www.understandingwar.org/rss.xml",
    "rand": "https://www.rand.org/content/rand/blog.rss.xml",
    "brookings": "https://www.brookings.edu/feed/",
    "carnegie": "https://carnegieendowment.org/rss/solr/?f-content-type=article",

    # Google aggregated military/conflict
    "google_military": "https://news.google.com/rss/search?q=military+OR+defence+OR+conflict+OR+invasion+when:1h&hl=en-US&gl=US&ceid=US:en",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AtrophiedMind/0.1)"}
FETCH_TIMEOUT = 15


def _fetch_feed(name: str, url: str) -> list[dict]:
    """Fetch an RSS feed and return structured items."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  [{name}] fetch failed: {e}")
        return []

    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        print(f"  [{name}] parse failed: {e}")
        return []

    items = []

    # Standard RSS 2.0
    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        desc = item.findtext("description", "").strip()
        pub_date = item.findtext("pubDate", "")

        if not title or not link:
            continue

        # Strip HTML from description
        import re
        desc = re.sub(r"<[^>]+>", "", desc).strip()
        if len(desc) > 300:
            desc = desc[:300] + "..."

        items.append({
            "headline": title,
            "summary": desc,
            "link": link,
            "source": name,
            "published": pub_date,
        })

    # Atom feeds (some sources use these)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns):
        title = entry.findtext("atom:title", "", ns).strip()
        link_el = entry.find("atom:link[@rel='alternate']", ns)
        if link_el is None:
            link_el = entry.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        desc = entry.findtext("atom:summary", "", ns).strip()
        pub_date = entry.findtext("atom:published", "", ns) or entry.findtext("atom:updated", "", ns)

        if not title or not link:
            continue

        import re
        desc = re.sub(r"<[^>]+>", "", desc).strip()
        if len(desc) > 300:
            desc = desc[:300] + "..."

        items.append({
            "headline": title,
            "summary": desc,
            "link": link,
            "source": name,
            "published": pub_date or "",
        })

    return items


def _get_seen_links(conn: sqlite3.Connection) -> set:
    """Get all previously stored links for deduplication."""
    rows = conn.execute("SELECT link FROM intelligence WHERE link IS NOT NULL").fetchall()
    return {row[0] for row in rows}


def _store_item(conn: sqlite3.Connection, item: dict, assessment: str, urgency: str) -> int:
    """Store an intelligence item and create a corresponding observation."""
    # Write observation for memory search
    obs_content = f"[INTEL/{item['source'].upper()}] {item['headline']}"
    if assessment:
        obs_content += f" — {assessment}"
    obs_id = write_observation(obs_content, confidence=0.7, db_path=DB_PATH)

    # Store structured intelligence
    cursor = conn.execute(
        """INSERT INTO intelligence
           (headline, summary, link, source, published_at, urgency, assessed, assessment, observation_id)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (
            item["headline"],
            item["summary"],
            item["link"],
            item["source"],
            item.get("published", ""),
            urgency,
            assessment,
            obs_id,
        ),
    )
    intel_id = cursor.lastrowid

    # Embed the headline + summary for vector search
    try:
        text = f"{item['headline']}. {item['summary']}"
        emb = embed_text(text)
        if emb is not None:
            conn.execute(
                "UPDATE intelligence SET embedding = ? WHERE id = ?",
                (emb.tobytes(), intel_id),
            )
    except Exception:
        pass

    return intel_id


def _assess_batch(items: list[dict]) -> dict:
    """Run inference to assess a batch of headlines for strategic significance.

    Returns a dict mapping item index to {urgency, assessment}.
    """
    if not items:
        return {}

    headlines_text = "\n".join(
        f"{i+1}. [{it['source']}] {it['headline']}"
        + (f" — {it['summary'][:100]}" if it['summary'] else "")
        for i, it in enumerate(items)
    )

    system = (
        f"You are {AGENT_DISPLAY_NAME}. You are conducting an intelligence assessment "
        "of incoming news items. For each item, assess its strategic and military "
        "significance.\n\n"
        "Respond in JSON format. For each item number, provide:\n"
        '- "urgency": one of "routine", "notable", "urgent", "critical"\n'
        '- "assessment": 1-2 sentence analysis (implications, connections, what it means)\n\n'
        "Urgency guide:\n"
        '- "routine": everyday news, no strategic significance\n'
        '- "notable": worth filing, developing situation, shift in posture\n'
        '- "urgent": significant military/geopolitical development — warrants an URGENT BRIEFING\n'
        '- "critical": war declaration, nuclear event, major invasion, assassination of head of state — FOR IMMEDIATE ATTENTION\n\n'
        "Critical and urgent items will be delivered directly to Will. Do not inflate urgency.\n"
        "Most items will be routine. Only flag what genuinely matters.\n\n"
        "Skip routine items entirely — only include notable, urgent, or critical.\n"
        "If nothing is significant, respond with: {}\n\n"
        'Respond ONLY with valid JSON. Example: {"1": {"urgency": "notable", "assessment": "..."}}'
    )

    try:
        result = run_inference_oneshot(
            [{"role": "user", "content": f"Assess these headlines:\n\n{headlines_text}"}],
            system=system,
        )
    except Exception as e:
        print(f"  [assess] inference failed: {e}")
        return {}

    # Parse JSON from response (handle markdown code blocks)
    result = result.strip()
    if result.startswith("```"):
        lines = result.split("\n")
        result = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        import re
        match = re.search(r'\{[\s\S]*\}', result)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                print(f"  [assess] failed to parse response")
                return {}
        else:
            return {}

    # Normalise keys to int
    assessments = {}
    for key, val in parsed.items():
        try:
            idx = int(key) - 1  # 1-indexed to 0-indexed
            if isinstance(val, dict):
                assessments[idx] = val
        except (ValueError, TypeError):
            continue

    return assessments


def _queue_urgent(items: list[dict], assessments: dict):
    """Queue urgent/critical items for immediate delivery."""
    urgent_items = []
    for idx, info in assessments.items():
        urgency = info.get("urgency", "routine")
        if urgency in ("urgent", "critical"):
            if idx < len(items):
                item = items[idx]
                assessment = info.get("assessment", "")
                if urgency == "critical":
                    prefix = "FOR IMMEDIATE ATTENTION"
                else:
                    prefix = "URGENT BRIEFING"
                text = f"[{prefix}]\n\n{item['headline']}"
                if assessment:
                    text += f"\n\n{assessment}"
                text += f"\n\n{item['link']}"
                urgent_items.append(text)

    if not urgent_items:
        return

    # Queue for immediate display (file-locked)
    for text in urgent_items:
        queue_message(MESSAGE_QUEUE, text, source="intelligence")
    print(f"  [intel] Queued {len(urgent_items)} urgent items for immediate delivery")

    # Also try Telegram
    try:
        from channels.telegram import send_message
        for text in urgent_items:
            send_message(text)
        print(f"  [intel] Sent {len(urgent_items)} urgent items via Telegram")
    except Exception as e:
        print(f"  [intel] Telegram delivery failed: {e}")


def run():
    print(f"\n{'='*60}")
    print(f"  INTELLIGENCE WATCH — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    init_db(DB_PATH)

    # Ensure intelligence table exists (for existing DBs)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS intelligence (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            headline      TEXT NOT NULL,
            summary       TEXT,
            link          TEXT,
            source        TEXT,
            published_at  DATETIME,
            urgency       TEXT DEFAULT 'routine',
            assessed      BOOLEAN DEFAULT 0,
            assessment    TEXT,
            observation_id INTEGER,
            embedding     BLOB
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_intelligence_link ON intelligence(link)")
    conn.commit()

    # Fetch all feeds
    all_items = []
    for name, url in FEEDS.items():
        items = _fetch_feed(name, url)
        all_items.extend(items)
        if items:
            print(f"  [{name}] {len(items)} items")

    print(f"\n  Total fetched: {len(all_items)}")

    # Deduplicate against seen links
    seen = _get_seen_links(conn)
    new_items = [it for it in all_items if it["link"] not in seen]
    print(f"  New (unseen): {len(new_items)}")

    if not new_items:
        print("  Nothing new. Standing down.")
        conn.close()
        return

    # Assess in batches (max 25 per inference call)
    BATCH_SIZE = 25
    all_assessments = {}

    for i in range(0, len(new_items), BATCH_SIZE):
        batch = new_items[i:i + BATCH_SIZE]
        print(f"\n  Assessing batch {i // BATCH_SIZE + 1} ({len(batch)} items)...")
        batch_assessments = _assess_batch(batch)

        # Offset indices for this batch
        for idx, info in batch_assessments.items():
            all_assessments[i + idx] = info

    # Store items — batch routine inserts, process notable individually
    notable_count = 0
    routine_batch = []
    for i, item in enumerate(new_items):
        info = all_assessments.get(i, {})
        urgency = info.get("urgency", "routine")
        assessment = info.get("assessment", "")

        # Only store notable+ items (skip routine to avoid noise)
        if urgency == "routine" and not assessment:
            routine_batch.append((item["headline"], item["link"], item["source"]))
            continue

        _store_item(conn, item, assessment, urgency)
        notable_count += 1
        print(f"  [{urgency.upper()}] {item['headline'][:80]}")

    if routine_batch:
        conn.executemany(
            "INSERT INTO intelligence (headline, link, source, urgency) VALUES (?, ?, ?, 'routine')",
            routine_batch,
        )

    conn.commit()

    # Queue urgent/critical for immediate delivery
    _queue_urgent(new_items, all_assessments)

    print(f"\n  Filed: {notable_count} notable+ items, "
          f"{len(new_items) - notable_count} routine (link-only)")

    conn.close()
    print(f"\n  Watch complete.\n")


if __name__ == "__main__":
    run()

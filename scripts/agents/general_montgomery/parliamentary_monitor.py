#!/usr/bin/env python3
"""
Parliamentary Monitor
Runs weekdays 08:00. Fetches recent Hansard proceedings for defence and
foreign affairs content relevant to Meridian tracks. Flags to Montgomery.

Uses the UK Parliament API (api.parliament.uk) - no auth required.
Filters for: defence, foreign affairs, defence procurement, NATO, Ukraine,
Iran, China, Sudan, arms exports, intelligence, AUKUS.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.credentials import load_telegram_credentials

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON  = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB    = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "general_montgomery"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ParliMonitor] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "parliamentary_monitor.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("parliamentary_monitor")

# Hansard search API - public, no key
HANSARD_API = "https://hansard.parliament.uk/api/hansardsearch/searchresults.json"

MERIDIAN_KEYWORDS = [
    "ukraine", "russia", "iran", "china", "taiwan", "sudan", "gaza",
    "nato", "aukus", "defence procurement", "armed forces", "intelligence",
    "cyber", "hypersonic", "nuclear deterrence", "sanctions",
    "arms export", "foreign affairs", "national security",
    "houthi", "red sea", "hormuz", "israel", "hezbollah",
    "special forces", "five eyes", "integrated review",
]

COMMITTEES = [
    "Defence Committee",
    "Foreign Affairs Committee",
    "Intelligence and Security Committee",
    "Joint Committee on National Security Strategy",
]


def load_cfg():
    with open(_AGENT_JSON) as f:
        return json.load(f)


def send_telegram(token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_hansard(keyword: str, days_back: int = 2) -> list[dict]:
    """Query Hansard API for recent mentions of a keyword."""
    try:
        params = urllib.parse.urlencode({
            "searchTerm": keyword,
            "startDate": (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d"),
            "house": "Both",
            "take": 5,
        })
        url = f"{HANSARD_API}?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("Results", []) or data.get("results", [])
    except Exception as e:
        log.debug(f"Hansard fetch '{keyword}': {e}")
        return []


def score_result(result: dict) -> int:
    """Score a Hansard result by relevance to Meridian tracks."""
    score = 0
    text = json.dumps(result).lower()
    for kw in MERIDIAN_KEYWORDS:
        if kw in text:
            score += 1
    for committee in COMMITTEES:
        if committee.lower() in text:
            score += 3
    return score


def deduplicate(results: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for r in results:
        uid = r.get("MemberContribution", {}).get("ItemId", "") or r.get("id", "")
        if uid and uid not in seen:
            seen.add(uid)
            deduped.append(r)
    return deduped


def format_result(result: dict) -> str:
    try:
        contrib = result.get("MemberContribution", result)
        member = contrib.get("MemberName", contrib.get("memberName", "Unknown MP"))
        debate = contrib.get("DebateSection", contrib.get("debate", ""))
        date = contrib.get("SittingDate", contrib.get("date", ""))[:10]
        text = contrib.get("Text", contrib.get("text", ""))
        text = re.sub(r'<[^>]+>', '', text or "").strip()[:200]
        return f"*{member}* ({date}) - _{debate}_\n{text}..."
    except Exception:
        return str(result)[:200]


def log_to_db(conn: sqlite3.Connection, content: str, signal_count: int):
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO briefs (requested_by, date, title, content, created_at)
        VALUES (?, date('now'), ?, ?, ?)
    """, (
        "general_montgomery",
        f"Parliamentary Monitor - {datetime.now().strftime('%Y-%m-%d')}",
        content,
        now
    ))
    if signal_count > 0:
        cur.execute("""
            INSERT INTO signals (agent, content, signal_type, region, severity, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("general_montgomery", content, "parliamentary", "UK", "LOW", now))
    conn.commit()


def main():
    log.info("Parliamentary monitor starting")
    cfg = load_cfg()

    # Sample across key keywords - limit API calls
    sample_keywords = [
        "ukraine defence", "iran nuclear", "china taiwan", "nato defence",
        "sudan crisis", "arms exports", "national security", "red sea houthi"
    ]

    all_results = []
    for kw in sample_keywords:
        results = fetch_hansard(kw, days_back=2)
        all_results.extend(results)
        log.debug(f"'{kw}': {len(results)} results")

    all_results = deduplicate(all_results)
    log.info(f"{len(all_results)} unique Hansard results")

    if not all_results:
        log.info("Nothing to report - no recent Hansard activity on Meridian keywords")
        return

    # Score and take top results
    scored = sorted(all_results, key=score_result, reverse=True)[:8]

    now_str = datetime.now().strftime("%d %b %Y")
    lines = [
        f"*PARLIAMENTARY MONITOR - {now_str}*",
        f"_{len(all_results)} relevant contributions found. Top {len(scored)} shown._",
        "",
    ]
    for r in scored:
        lines.append(format_result(r))
        lines.append("")

    lines.append("_Source: UK Parliament Hansard API_")
    report = "\n".join(lines)

    conn = sqlite3.connect(_INTEL_DB)
    log_to_db(conn, report, len(scored))
    conn.close()

    try:
        send_telegram(*load_telegram_credentials("general_montgomery"), report)
        log.info(f"Parliamentary monitor sent: {len(scored)} items")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


if __name__ == "__main__":
    main()

# Horizon Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a forward-looking "Looking Ahead" intelligence layer - structured calendar events from open sources, plus weekly forward assessments from Research Fellows, synthesised into a 7-day horizon view in Montgomery's brief.

**Architecture:** Two pipelines feed a single `horizon_events` table in `intelligence.db`. Pipeline 1: a new `horizon_scout` agent scrapes structured event calendars (UN, NATO, central banks, parliaments, elections, treaty deadlines). Pipeline 2: each RF agent appends a `## Next 7 Days` section to its weekly output, which a shared extraction script parses into structured horizon events. Montgomery's `render_brief.py` gains a "Looking Ahead" tab rendering a 7-day timeline strip with colour-coded event markers.

**Tech Stack:** Python 3 (scripts), SQLite (intelligence.db), HTML/CSS (render_brief.py), Claude CLI (extraction)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `scripts/agents/horizon_scout/horizon_poll.py` | Calendar source polling, normalisation, DB write |
| Create | `scripts/agents/shared/horizon_extract.py` | Parse RF `## Next 7 Days` sections into horizon_events |
| Modify | `scripts/agents/rf_russia_ukraine/daily_battlefield.py` | Add Next 7 Days to system prompt |
| Modify | `scripts/agents/rf_uk_defence/weekly_posture.py` | Add Next 7 Days to system prompt |
| Modify | `scripts/agents/rf_european_security/weekly_security.py` | Add Next 7 Days to system prompt |
| Modify | `scripts/agents/rf_gulf_iran_israel/monthly_paper.py` | Add Next 7 Days to system prompt |
| Modify | `scripts/agents/rf_indo_pacific/weekly_indopacific.py` | Add Next 7 Days to system prompt |
| Modify | `scripts/agents/rf_eu_nordic_monitor/eu_nordic_monitor.py` | Add Next 7 Days to system prompt |
| Modify | `~/.atrophy/agents/general_montgomery/tools/render_brief.py` | Add "Looking Ahead" tab |
| Modify | `scripts/agents/general_montgomery/dashboard_brief.py` | Query horizon_events, pass to render |
| Modify | `~/.atrophy/agents/general_montgomery/data/agent.json` | Add horizon_poll and horizon_extract jobs |

---

### Task 1: Create horizon_events table

**Files:**
- Modify: `~/.atrophy/agents/general_montgomery/data/intelligence.db` (via script)
- Create: `scripts/agents/shared/horizon_schema.py`

The schema script is idempotent (`CREATE TABLE IF NOT EXISTS`) so it can be imported by any script that needs the table.

- [ ] **Step 1: Create the schema helper**

Create `scripts/agents/shared/horizon_schema.py`:

```python
#!/usr/bin/env python3
"""Horizon events schema - idempotent table creation."""
from __future__ import annotations
import sqlite3
from pathlib import Path

_INTEL_DB = Path.home() / ".atrophy" / "agents" / "general_montgomery" / "data" / "intelligence.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS horizon_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date DATE NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN (
        'diplomatic', 'economic', 'security', 'political'
    )),
    title TEXT NOT NULL,
    description TEXT,
    actors TEXT,                    -- JSON array of actor names
    significance TEXT CHECK(significance IN ('HIGH', 'MEDIUM', 'LOW')),
    confidence TEXT CHECK(confidence IN ('CONFIRMED', 'HIGH', 'MEDIUM', 'SPECULATIVE')),
    source TEXT NOT NULL,           -- 'calendar:<source_name>' or 'rf:<agent_name>'
    source_url TEXT,
    region TEXT,                    -- ISO country code or region slug
    linked_objects TEXT,            -- JSON array of ontology object IDs
    brief_id INTEGER,              -- FK to briefs if extracted from a brief
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at DATE,               -- auto-prune after this date (default: event_date + 1)
    FOREIGN KEY (brief_id) REFERENCES briefs(id)
);

CREATE INDEX IF NOT EXISTS idx_horizon_date ON horizon_events(event_date);
CREATE INDEX IF NOT EXISTS idx_horizon_type ON horizon_events(event_type);
CREATE INDEX IF NOT EXISTS idx_horizon_source ON horizon_events(source);
CREATE INDEX IF NOT EXISTS idx_horizon_confidence ON horizon_events(confidence);
"""

def ensure_table(db_path: str | Path | None = None) -> None:
    """Create horizon_events table if it doesn't exist."""
    db = sqlite3.connect(str(db_path or _INTEL_DB))
    db.executescript(SCHEMA)
    db.close()

if __name__ == "__main__":
    ensure_table()
    print(f"horizon_events table ensured in {_INTEL_DB}")
```

- [ ] **Step 2: Run it to create the table**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && python3 scripts/agents/shared/horizon_schema.py`

Expected: `horizon_events table ensured in ~/.atrophy/agents/general_montgomery/data/intelligence.db`

Verify: `sqlite3 ~/.atrophy/agents/general_montgomery/data/intelligence.db ".schema horizon_events"`

- [ ] **Step 3: Commit**

```bash
git add scripts/agents/shared/horizon_schema.py
git commit -m "feat(horizon): add horizon_events schema to intelligence.db"
```

---

### Task 2: Build horizon_scout calendar poller

**Files:**
- Create: `scripts/agents/horizon_scout/horizon_poll.py`

This script polls structured event calendars and writes normalised events to `horizon_events`. It runs nightly at 03:00. Sources are hardcoded initially - new sources are added by extending the `SOURCES` list.

Calendar sources for v1:
- **Central banks**: FOMC, ECB, BoE, BoJ meeting dates (scraped from known schedule pages)
- **UN Security Council**: programme of work (monthly PDF schedule)
- **NATO**: summit and ministerial meeting calendar
- **UK Parliament**: sitting dates via Hansard API (already integrated in parliamentary_monitor.py)
- **Treaty deadlines**: manual seed data + DB-maintained list
- **ICG CrisisWatch**: monthly forecasts (WorldMonitor already has this)

- [ ] **Step 1: Create the poller script**

Create `scripts/agents/horizon_scout/horizon_poll.py`:

```python
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
```

- [ ] **Step 2: Test the script locally**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && PYTHONPATH="scripts/agents:scripts:$PYTHONPATH" python3 scripts/agents/horizon_scout/horizon_poll.py`

Expected: `Horizon updated: N new events in next 14 days` (central bank meetings at minimum)

Verify: `sqlite3 ~/.atrophy/agents/general_montgomery/data/intelligence.db "SELECT event_date, event_type, title, confidence FROM horizon_events ORDER BY event_date LIMIT 10;"`

- [ ] **Step 3: Commit**

```bash
git add scripts/agents/horizon_scout/horizon_poll.py
git commit -m "feat(horizon): add horizon_scout calendar poller"
```

---

### Task 3: Add Next 7 Days instruction to RF agent prompts

**Files:**
- Modify: `scripts/agents/rf_russia_ukraine/daily_battlefield.py`
- Modify: `scripts/agents/rf_uk_defence/weekly_posture.py`
- Modify: `scripts/agents/rf_european_security/weekly_security.py`
- Modify: `scripts/agents/rf_gulf_iran_israel/monthly_paper.py`
- Modify: `scripts/agents/rf_indo_pacific/weekly_indopacific.py`
- Modify: `scripts/agents/rf_eu_nordic_monitor/eu_nordic_monitor.py`

Each RF agent's system prompt gains a mandatory closing section. The format is fixed so `horizon_extract.py` can reliably parse it.

- [ ] **Step 1: Define the shared prompt suffix**

This exact text is appended to every RF system prompt. It must be identical across all agents for reliable extraction:

```
After your main assessment, add a section:

## Next 7 Days
List 3-5 dated events or developments expected in the next 7 days for your area.
Each line MUST follow this exact format:
- YYYY-MM-DD | CONFIDENCE | Event description (one sentence)

CONFIDENCE is one of: CONFIRMED, HIGH, MEDIUM, SPECULATIVE
CONFIRMED = scheduled event with fixed date. HIGH = very likely based on pattern/intel. MEDIUM = probable. SPECULATIVE = possible but uncertain.

Example:
## Next 7 Days
- 2026-04-02 | CONFIRMED | ECB Governing Council monetary policy decision
- 2026-04-03 | HIGH | Russia likely to intensify Zaporizhzhia shelling ahead of IAEA visit
- 2026-04-05 | SPECULATIVE | Possible Houthi retaliation following Red Sea interdiction
```

- [ ] **Step 2: Modify rf_russia_ukraine/daily_battlefield.py**

Find the system prompt string (line ~79) and append the Next 7 Days instruction:

```python
    system = """You are a Research Fellow at the Meridian Institute specialising in Russia-Ukraine.
Produce a terse daily battlefield summary: frontline status, Black Sea posture, notable strikes or moves,
UK/Western weapons supply status, and one sentence on Russian hybrid operations.
Voice: analytical, factual. No em dashes. Under 300 words.

After your main assessment, add a section:

## Next 7 Days
List 3-5 dated events or developments expected in the next 7 days for your area.
Each line MUST follow this exact format:
- YYYY-MM-DD | CONFIDENCE | Event description (one sentence)

CONFIDENCE is one of: CONFIRMED, HIGH, MEDIUM, SPECULATIVE
CONFIRMED = scheduled event with fixed date. HIGH = very likely based on pattern/intel. MEDIUM = probable. SPECULATIVE = possible but uncertain."""
```

- [ ] **Step 3: Modify rf_uk_defence/weekly_posture.py**

Find the system prompt and append the same Next 7 Days block. The existing prompt ends around line 95 - find the closing `"""` and insert before it.

- [ ] **Step 4: Modify rf_european_security/weekly_security.py**

Same pattern. Find the system prompt, append the Next 7 Days block.

- [ ] **Step 5: Modify rf_gulf_iran_israel/monthly_paper.py**

Same pattern.

- [ ] **Step 6: Modify rf_indo_pacific/weekly_indopacific.py**

Same pattern.

- [ ] **Step 7: Modify rf_eu_nordic_monitor/eu_nordic_monitor.py**

Same pattern.

- [ ] **Step 8: Commit**

```bash
git add scripts/agents/rf_*/
git commit -m "feat(horizon): add Next 7 Days section to all RF agent prompts"
```

---

### Task 4: Build horizon extraction script

**Files:**
- Create: `scripts/agents/shared/horizon_extract.py`

Parses the `## Next 7 Days` section from RF brief content and writes structured events to `horizon_events`. Runs nightly at 04:00 (after RF outputs are in).

- [ ] **Step 1: Create the extraction script**

Create `scripts/agents/shared/horizon_extract.py`:

```python
#!/usr/bin/env python3
"""
Horizon Extract - Parse RF '## Next 7 Days' sections into horizon_events.

Scans recent briefs from RF agents, extracts structured horizon entries,
deduplicates, and writes to intelligence.db.

Runs nightly at 04:00, after RF agents have produced their outputs.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from horizon_schema import ensure_table, _INTEL_DB

_ATROPHY_DIR = Path.home() / ".atrophy"
_LOG_DIR = _ATROPHY_DIR / "logs" / "general_montgomery"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [HorizonExtract] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "horizon_extract.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("horizon_extract")

# RF agents whose briefs we scan
RF_AGENTS = [
    "rf_russia_ukraine", "rf_uk_defence", "rf_european_security",
    "rf_gulf_iran_israel", "rf_indo_pacific", "rf_eu_nordic_monitor",
]

# Regex for the structured line format:
# - YYYY-MM-DD | CONFIDENCE | description
LINE_RE = re.compile(
    r"^-\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(CONFIRMED|HIGH|MEDIUM|SPECULATIVE)\s*\|\s*(.+)$",
    re.MULTILINE,
)

# Map keywords to event types
TYPE_KEYWORDS = {
    "diplomatic": ["summit", "visit", "negotiat", "talks", "diplomat", "ambassador",
                    "UN ", "NATO", "treaty", "ceasefire", "peace"],
    "economic": ["central bank", "rate", "ECB", "FOMC", "BoE", "sanction", "trade",
                 "tariff", "GDP", "inflation", "IMF", "World Bank"],
    "security": ["military", "exercise", "deploy", "strike", "shell", "offensive",
                 "missile", "drone", "naval", "airspace", "threat", "attack"],
    "political": ["election", "vote", "parliament", "speech", "legislation",
                  "referendum", "inaugurat", "resign", "cabinet"],
}


def classify_event_type(title: str) -> str:
    """Classify event type from title keywords."""
    title_lower = title.lower()
    scores = {t: 0 for t in TYPE_KEYWORDS}
    for event_type, keywords in TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                scores[event_type] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "political"  # default


def extract_horizon_from_brief(content: str, agent: str, brief_id: int) -> list[dict]:
    """Extract horizon events from a brief's ## Next 7 Days section."""
    # Find the section
    section_match = re.search(r"## Next 7 Days\s*\n(.*?)(?:\n##|\Z)", content, re.DOTALL)
    if not section_match:
        return []

    section_text = section_match.group(1)
    events = []
    for match in LINE_RE.finditer(section_text):
        date_str, confidence, description = match.groups()
        events.append({
            "event_date": date_str,
            "event_type": classify_event_type(description),
            "title": description.strip(),
            "confidence": confidence,
            "source": f"rf:{agent}",
            "brief_id": brief_id,
            "significance": "HIGH" if confidence in ("CONFIRMED", "HIGH") else "MEDIUM",
        })

    return events


def run():
    log.info("Horizon extraction starting")
    ensure_table()

    db = sqlite3.connect(str(_INTEL_DB))
    today = datetime.now(timezone.utc)
    lookback = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")

    # Get recent briefs from RF agents
    placeholders = ",".join("?" for _ in RF_AGENTS)
    rows = db.execute(
        f"""SELECT id, content, requested_by FROM briefs
        WHERE requested_by IN ({placeholders}) AND date >= ?
        ORDER BY date DESC""",
        (*RF_AGENTS, lookback),
    ).fetchall()

    if not rows:
        log.info("No recent RF briefs found")
        db.close()
        return

    # Track what we've already extracted (by brief_id)
    already_extracted = set()
    for row in db.execute(
        "SELECT DISTINCT brief_id FROM horizon_events WHERE brief_id IS NOT NULL"
    ).fetchall():
        already_extracted.add(row[0])

    # Build existing event keys for dedup
    existing_keys = set()
    for row in db.execute(
        "SELECT event_date, title FROM horizon_events WHERE event_date >= ?",
        (today_str,)
    ).fetchall():
        existing_keys.add(f"{row[0]}:{row[1].lower().strip()}")

    inserted = 0
    for brief_id, content, agent in rows:
        if brief_id in already_extracted:
            continue
        events = extract_horizon_from_brief(content, agent, brief_id)
        for event in events:
            key = f"{event['event_date']}:{event['title'].lower().strip()}"
            if key in existing_keys:
                continue
            db.execute(
                """INSERT INTO horizon_events
                (event_date, event_type, title, significance, confidence,
                 source, brief_id, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, date(?, '+1 day'))""",
                (event["event_date"], event["event_type"], event["title"],
                 event["significance"], event["confidence"],
                 event["source"], event["brief_id"],
                 event["event_date"]),
            )
            existing_keys.add(key)
            inserted += 1

    db.commit()
    db.close()

    log.info(f"Extracted {inserted} new horizon events from {len(rows)} briefs")
    if inserted > 0:
        print(f"Horizon: {inserted} new assessed events extracted from RF briefs")


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Test with existing briefs (dry run)**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && PYTHONPATH="scripts/agents:scripts:$PYTHONPATH" python3 scripts/agents/shared/horizon_extract.py`

Expected: `Extracted 0 new horizon events from N briefs` (existing briefs don't have the section yet - this confirms it runs without error)

- [ ] **Step 3: Commit**

```bash
git add scripts/agents/shared/horizon_extract.py
git commit -m "feat(horizon): add RF brief horizon extraction script"
```

---

### Task 5: Add Looking Ahead tab to render_brief.py

**Files:**
- Modify: `scripts/agents/general_montgomery/dashboard_brief.py` (~line 80+, the `collect_data` function)
- Modify: `~/.atrophy/agents/general_montgomery/tools/render_brief.py` (~line 640, tab bar + new tab content)

This task adds the horizon data to the brief pipeline and renders the 7-day timeline strip.

- [ ] **Step 1: Add horizon query to dashboard_brief.py**

In `dashboard_brief.py`, add a function to query horizon events and include them in the brief data dict. Add after the existing data collection functions:

```python
def collect_horizon() -> dict:
    """Query upcoming horizon events for the brief."""
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
```

In the `collect_data()` function (or wherever the brief data dict is assembled), merge the horizon data:

```python
    # Add horizon events
    data.update(collect_horizon())
```

Also add the required imports at the top if not present: `from datetime import timedelta` (likely already there) and `import sqlite3` (likely already there).

- [ ] **Step 2: Add the Looking Ahead tab to render_brief.py**

In `~/.atrophy/agents/general_montgomery/tools/render_brief.py`, make three changes:

**2a.** Add a new tab button in the tab bar (around line 640-642, after the existing tab buttons):

```html
<button class="tab-btn" onclick="showTab('horizon',this)">Looking Ahead</button>
```

**2b.** Add CSS for the horizon timeline (inside the `<style>` block, around line 470-640):

```css
.horizon-strip{{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:16px}}
.horizon-day{{background:var(--panel);border:1px solid var(--brd);border-radius:6px;padding:8px;min-height:80px}}
.horizon-day-header{{font-size:11px;color:var(--dim);margin-bottom:6px;text-transform:uppercase}}
.horizon-day-today{{border-color:var(--uk)}}
.horizon-marker{{font-size:11px;padding:3px 6px;border-radius:3px;margin-bottom:3px;line-height:1.3}}
.horizon-marker.diplomatic{{background:rgba(100,140,255,0.15);color:#8ab4f8;border-left:2px solid #648cff}}
.horizon-marker.economic{{background:rgba(255,180,50,0.15);color:#ffb432;border-left:2px solid #ffb432}}
.horizon-marker.security{{background:rgba(255,80,80,0.15);color:#ff6b6b;border-left:2px solid #ff5050}}
.horizon-marker.political{{background:rgba(160,160,170,0.15);color:#a0a0aa;border-left:2px solid #888}}
.horizon-confidence{{font-size:9px;opacity:0.6;margin-left:4px}}
.horizon-columns{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.horizon-col h3{{font-size:13px;margin:0 0 8px;color:var(--uk)}}
.horizon-card{{background:var(--panel);border:1px solid var(--brd);border-radius:6px;padding:10px;margin-bottom:8px}}
.horizon-card .date{{font-size:11px;color:var(--dim)}}
.horizon-card .title{{font-size:13px;margin:2px 0}}
.horizon-card .source{{font-size:10px;color:var(--dim);margin-top:4px}}
.horizon-card .conf-badge{{font-size:10px;padding:1px 5px;border-radius:3px;font-weight:600}}
.conf-CONFIRMED{{background:rgba(100,200,100,0.2);color:#6c6}}
.conf-HIGH{{background:rgba(100,140,255,0.2);color:#8ab4f8}}
.conf-MEDIUM{{background:rgba(255,180,50,0.2);color:#ffb432}}
.conf-SPECULATIVE{{background:rgba(255,100,100,0.2);color:#ff6b6b}}
```

**2c.** Add the horizon tab content generation. In the `render(data)` function, after the existing tab content blocks and before the closing `</div>` of the tab container, add a function to generate the horizon HTML:

```python
    # --- Looking Ahead tab ---
    horizon_events = data.get("horizon_events", [])

    # Build 7-day grid
    from datetime import date as date_type, timedelta as td
    today_date = date_type.today()
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days_html = ""
    for i in range(7):
        d = today_date + td(days=i)
        d_str = d.strftime("%Y-%m-%d")
        d_label = d.strftime("%d %b")
        d_name = day_names[d.weekday()]
        is_today = "horizon-day-today" if i == 0 else ""

        # Events for this day
        day_events = [e for e in horizon_events if e["date"] == d_str]
        markers = ""
        for ev in day_events:
            conf_tag = f'<span class="horizon-confidence">{ev["confidence"]}</span>' if ev["confidence"] != "CONFIRMED" else ""
            markers += f'<div class="horizon-marker {ev["type"]}">{ev["title"]}{conf_tag}</div>\n'

        days_html += f"""<div class="horizon-day {is_today}">
            <div class="horizon-day-header">{d_name} {d_label}</div>
            {markers or '<div style="font-size:11px;color:var(--dim)">No events</div>'}
        </div>"""

    # Split into confirmed vs assessed
    confirmed = [e for e in horizon_events if e["confidence"] == "CONFIRMED"]
    assessed = [e for e in horizon_events if e["confidence"] != "CONFIRMED"]

    def render_horizon_card(ev):
        src = ev["source"].replace("calendar:", "").replace("rf:", "RF ")
        return f"""<div class="horizon-card">
            <div class="date">{ev["date"]} <span class="conf-badge conf-{ev["confidence"]}">{ev["confidence"]}</span></div>
            <div class="title">{ev["title"]}</div>
            <div class="source">{src}</div>
        </div>"""

    confirmed_html = "".join(render_horizon_card(e) for e in confirmed) or '<div style="color:var(--dim)">No confirmed events</div>'
    assessed_html = "".join(render_horizon_card(e) for e in assessed) or '<div style="color:var(--dim)">No assessed events yet</div>'

    horizon_tab = f"""<div id="tab-horizon" class="tab-content" style="display:none">
        <h2 style="margin:0 0 12px;font-size:16px">7-Day Horizon</h2>
        <div class="horizon-strip">{days_html}</div>
        <div style="display:flex;gap:8px;margin-bottom:16px;font-size:11px">
            <span class="horizon-marker diplomatic" style="margin:0">Diplomatic</span>
            <span class="horizon-marker economic" style="margin:0">Economic</span>
            <span class="horizon-marker security" style="margin:0">Security</span>
            <span class="horizon-marker political" style="margin:0">Political</span>
        </div>
        <div class="horizon-columns">
            <div><h3>Confirmed Events</h3>{confirmed_html}</div>
            <div><h3>Assessed Likely</h3>{assessed_html}</div>
        </div>
    </div>"""
```

Then insert `{horizon_tab}` into the HTML template alongside the other tab content blocks.

- [ ] **Step 3: Test with dummy data**

Create a temporary test: insert a few dummy horizon events, run the brief pipeline, verify the HTML renders correctly.

```bash
sqlite3 ~/.atrophy/agents/general_montgomery/data/intelligence.db "
INSERT INTO horizon_events (event_date, event_type, title, significance, confidence, source, expires_at)
VALUES
('$(date -v+1d +%Y-%m-%d)', 'economic', 'FOMC rate decision', 'HIGH', 'CONFIRMED', 'calendar:central_banks', '$(date -v+2d +%Y-%m-%d)'),
('$(date -v+2d +%Y-%m-%d)', 'diplomatic', 'UN Security Council session on Iran', 'HIGH', 'HIGH', 'calendar:worldmonitor', '$(date -v+3d +%Y-%m-%d)'),
('$(date -v+3d +%Y-%m-%d)', 'security', 'Possible Houthi retaliation in Red Sea', 'MEDIUM', 'SPECULATIVE', 'rf:rf_gulf_iran_israel', '$(date -v+4d +%Y-%m-%d)')
;"
```

Then run the brief: `python3 scripts/agents/general_montgomery/dashboard_brief.py --mode refresh`

Open `/tmp/montgomery_brief.html` in a browser and verify the Looking Ahead tab renders with the 7-day timeline strip, colour-coded markers, and the two-column split.

- [ ] **Step 4: Remove dummy data**

```bash
sqlite3 ~/.atrophy/agents/general_montgomery/data/intelligence.db "DELETE FROM horizon_events WHERE source IN ('calendar:central_banks','calendar:worldmonitor','rf:rf_gulf_iran_israel') AND title IN ('FOMC rate decision','UN Security Council session on Iran','Possible Houthi retaliation in Red Sea');"
```

- [ ] **Step 5: Commit**

```bash
git add scripts/agents/general_montgomery/dashboard_brief.py
git commit -m "feat(horizon): add Looking Ahead tab to Montgomery brief"
```

Note: `render_brief.py` lives in `~/.atrophy/` (personal scripts, not in git). The changes there are local only.

---

### Task 6: Register cron jobs

**Files:**
- Modify: `~/.atrophy/agents/general_montgomery/data/agent.json`

Add three new jobs to Montgomery's manifest:

- [ ] **Step 1: Add horizon jobs to agent.json**

Open `~/.atrophy/agents/general_montgomery/data/agent.json` and add these entries to the `"jobs"` section:

```json
"horizon_poll": {
    "cron": "0 3 * * *",
    "script": "scripts/agents/horizon_scout/horizon_poll.py",
    "description": "Poll calendar sources for upcoming events",
    "route_output_to": "self",
    "notify_via": "telegram"
},
"horizon_extract": {
    "cron": "0 4 * * *",
    "script": "scripts/agents/shared/horizon_extract.py",
    "description": "Extract horizon events from RF brief Next 7 Days sections",
    "route_output_to": "self",
    "notify_via": "telegram"
}
```

Note: these run under Montgomery's umbrella since he owns `intelligence.db`. No separate `horizon_scout` agent manifest needed for v1 - the scout is just a script, not a full agent with its own memory/prompts/channels.

- [ ] **Step 2: Verify cron registration**

Restart the Atrophy app (or wait for next boot). Check logs for:
```
[cron-scheduler] Registered job: general_montgomery.horizon_poll
[cron-scheduler] Registered job: general_montgomery.horizon_extract
```

- [ ] **Step 3: Commit**

The agent.json is in `~/.atrophy/` (not in git). No git commit needed. The bundled scripts are already committed.

---

### Task 7: Seed initial deadline data

**Files:**
- None (manual DB operations)

Seed the horizon_events table with known upcoming deadlines that the poller can't scrape automatically.

- [ ] **Step 1: Seed deadlines**

```sql
INSERT INTO horizon_events (event_date, event_type, title, description, significance, confidence, source, region)
VALUES
-- Add current known deadlines here. Examples:
('2026-04-06', 'diplomatic', 'Iran nuclear deal compliance pause expires', 'IAEA verification deadline for enrichment commitments', 'HIGH', 'CONFIRMED', 'deadline:iran_nuclear', 'IR');
```

The specific deadlines should be populated based on what Montgomery's brief currently tracks. This is a manual seed - ongoing maintenance happens through Montgomery's MCP tools or manual inserts.

- [ ] **Step 2: Verify**

```bash
sqlite3 ~/.atrophy/agents/general_montgomery/data/intelligence.db "SELECT event_date, title, confidence FROM horizon_events ORDER BY event_date;"
```

---

## Execution Notes

- Tasks 1-4 can run in parallel (schema, poller, RF prompts, extraction are independent)
- Task 5 depends on Task 1 (needs the table to exist)
- Task 6 depends on Tasks 2 and 4 (registers the scripts as jobs)
- Task 7 is manual and can happen any time after Task 1

The RF prompt changes (Task 3) won't produce horizon data until the next scheduled RF run. The poller (Task 2) produces data immediately from central bank calendars. So the Looking Ahead tab will show confirmed calendar events right away, with assessed events populating over the next few days as RF agents run.

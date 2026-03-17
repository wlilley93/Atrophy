# WorldMonitor MCP Integration - Design Spec

**Date:** 2026-03-17
**Status:** Approved
**Scope:** New MCP server + cron job for WorldMonitor API access across Atrophy system

---

## 1. Overview

A shared MCP server (`mcp/worldmonitor_server.py`) that gives any Atrophy agent structured access to WorldMonitor's 37+ open API endpoints. It handles caching, delta detection, and both continuous polling and on-demand queries. A companion cron job polls tiered endpoints and files significant changes as intelligence observations into Montgomery's memory.

### Design Decisions

- **WorldMonitor augments, does not replace** Montgomery's existing `news_watch` pipeline. news_watch provides narrative context from Telegram/news; WorldMonitor provides structured quantitative data (vessel counts, flight tracks, economic indicators, GPS jamming).
- **Hybrid access model:** Continuous background polling files intelligence automatically; on-demand tools let Montgomery drill into live data during conversations.
- **Shared server:** Lives in `mcp/` alongside memory_server.py. Agent-agnostic code - Montgomery's analytical personality comes from his prompts, not the data layer.
- **Tiered polling:** Fast-moving tactical data (flights, vessels, alerts) every 15 mins. Medium-tempo data (conflicts, earthquakes) every 45 mins. Slow structural data (economics, trade) every 4 hours.

---

## 2. Architecture

```
                    +-----------------------------+
                    |     WorldMonitor APIs        |
                    |   api.worldmonitor.app/api/* |
                    +--------------+--------------+
                                   |
                    +--------------v--------------+
                    |  worldmonitor_server.py      |
                    |  (MCP server - stdio)        |
                    |                              |
                    |  - HTTP client layer         |
                    |  - Response cache (SQLite)   |
                    |  - Delta detection engine    |
                    |  - Tool definitions (21)      |
                    +------+-------------+--------+
                           |             |
              +------------v--+   +------v----------+
              | Claude CLI    |   | worldmonitor_    |
              | (on-demand    |   | poll.py          |
              |  tool calls)  |   | (cron job)       |
              +--------------+   +------+-----------+
                                        |
                               +--------v-----------+
                               | memory_server.py    |
                               | observe() calls     |
                               | [INTEL/WM/<DOMAIN>] |
                               +--------------------+
```

---

## 3. Component 1: MCP Server

**File:** `mcp/worldmonitor_server.py`
**Pattern:** Same as `memory_server.py` - Python, JSON-RPC 2.0 over stdio.
**Dependencies:** Python 3.10+, `urllib.request` (stdlib), `sqlite3` (stdlib). No pip dependencies.

### 3.1 Local Cache

SQLite database at `~/.atrophy/worldmonitor_cache.db`.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS cache (
    cache_key   TEXT PRIMARY KEY,     -- full URL with query params (e.g. "api/bootstrap?tier=fast")
    endpoint    TEXT NOT NULL,        -- base endpoint path (for querying by domain)
    response    TEXT NOT NULL,        -- raw JSON response
    fetched_at  TEXT NOT NULL,        -- ISO 8601 timestamp
    prev_response TEXT,               -- previous response (for diffing)
    delta       TEXT                  -- computed delta JSON
);

CREATE INDEX IF NOT EXISTS idx_cache_endpoint ON cache(endpoint);

CREATE TABLE IF NOT EXISTS poll_state (
    tier        TEXT PRIMARY KEY,     -- fast, medium, slow
    last_poll   TEXT NOT NULL         -- ISO 8601 timestamp
);
```

**Cache key format:** Full URL path with query parameters, e.g. `api/bootstrap?tier=fast` and `api/bootstrap?tier=slow` are separate cache entries. This prevents collisions for parameterised endpoints.

**Cache eviction:** On each write, delete `prev_response` values older than 7 days to bound storage growth. The cache DB stores full API payloads (maritime snapshots can be large), so unbounded prev_response accumulation would bloat the DB over weeks.

### 3.2 HTTP Client Layer

- Uses `urllib.request` (no external deps)
- Base URL from env: `WORLDMONITOR_BASE_URL` (default: `https://api.worldmonitor.app`)
- Timeout: 30 seconds per request
- User-Agent: `Atrophy/1.0 (WorldMonitor MCP)`
- For POST endpoints: JSON body via `Content-Type: application/json`
- **Optional auth:** If `WORLDMONITOR_API_KEY` env var is set, send as `Authorization: Bearer <key>` header on all requests. Currently no auth is required, but this provides a forward-compatible hook if WorldMonitor adds authentication later.

### 3.3 Tool Definitions

#### Continuous/cached tools (return cached data + delta summary)

| Tool | Endpoint(s) | Parameters | Returns |
|------|------------|------------|---------|
| `worldmonitor_situation` | `bootstrap?tier=fast`, `bootstrap?tier=slow` | `tier` (optional: fast/slow/both, default: both) | Earthquakes, outages, markets, commodities, chokepoints, service statuses |
| `worldmonitor_maritime` | `ais-snapshot?candidates=true` | `include_candidates` (bool, default: true) | Vessel counts, disruptions, density zones, candidate reports |
| `worldmonitor_military_flights` | `military-flights` | none | Tracked military aircraft with callsigns, positions, operators |
| `worldmonitor_gps_jamming` | `gpsjam` | none | GPS interference hexagons and classification levels |
| `worldmonitor_alerts` | `oref-alerts` | `include_history` (bool, default: false) | Active and historical Israeli alerts |
| `worldmonitor_osint_feed` | `telegram-feed` | `limit` (int, default: 50) | Latest OSINT items from monitored Telegram channels |
| `worldmonitor_conflicts` | `conflict/v1/list-acled-events` | none | Armed conflict events |
| `worldmonitor_thermal` | `thermal/v1/list-thermal-escalations` | `max_items` (int, default: 12) | Satellite thermal anomalies |
| `worldmonitor_get_changes` | (reads cache deltas) | `since_minutes` (int, default: 60), `domains` (optional comma-separated filter) | Pre-diffed summary of changes by domain |

#### On-demand tools (live fetch, cached when polled)

On-demand tools fetch live data when called interactively by the agent. However, the slow-tier polling job also calls economic, trade, displacement, fleet, and anomaly endpoints on a 4-hour cycle. When polled, responses are cached and deltas computed using the same cache DB - this allows `worldmonitor_get_changes` to include slow-tier shifts. When called interactively, these tools always fetch fresh data but update the cache as a side effect.

| Tool | Endpoint(s) | Parameters | Returns |
|------|------------|------------|---------|
| `worldmonitor_economic` | `economic/v1/*` | `series` (enum: fred_batch/bis_policy_rates/bis_exchange_rates/bis_credit/energy_prices), `commodities` (optional) | Selected economic data |
| `worldmonitor_trade` | `trade/v1/*` | `query` (enum: restrictions/tariff_trends/trade_flows/trade_barriers), `reporting_country`, `partner_country`, `years`, `limit` | Trade data |
| `worldmonitor_displacement` | `displacement/v1/*` | `query` (enum: summary/population_exposure), `lat`, `lon`, `radius`, `flow_limit` | Displacement/exposure data |
| `worldmonitor_fleet_report` | `military/v1/get-usni-fleet-report` | none | USNI fleet positions |
| `worldmonitor_aircraft_lookup` | `military/v1/get-aircraft-details-batch` | `hex_codes` (list) | Aircraft detail by hex code |
| `worldmonitor_wingbits` | `military/v1/get-wingbits-status` | none | Wingbits ADS-B detection status |
| `worldmonitor_deduct_situation` | `intelligence/v1/deduct-situation` | `context` (string) | AI-generated situation assessment |
| `worldmonitor_anomalies` | `infrastructure/v1/list-temporal-anomalies` | none | Detected baseline pattern anomalies |
| `worldmonitor_news_summary` | `news/v1/summarize-article` (POST), `news/v1/summarize-article-cache` (GET) | `url` (string), `cache_key` (optional - if provided, checks cache first) | Article summarisation. Checks cache endpoint first if cache_key given, falls back to POST for fresh summarisation. |
| `worldmonitor_news_digest` | `news/v1/list-feed-digest` | `variant` (default: full), `lang` (default: en) | News feed digest |
| `worldmonitor_humanitarian` | `conflict/v1/get-humanitarian-summary-batch` | `regions` (list) | Humanitarian situation summaries |
| `worldmonitor_pizzint` | `intelligence/v1/get-pizzint-status` | `include_gdelt` (bool, default: true) | PIZZINT intelligence status |

### 3.4 Delta Detection Logic

When a cached tool is called:
1. Fetch fresh data from API
2. Load previous response from cache
3. Compute delta based on endpoint type:

| Data type | Delta method | Significance threshold |
|-----------|-------------|----------------------|
| Array of items (flights, vessels, conflicts, alerts) | Diff by ID field - flag new, removed, changed | Any new or removed item |
| Numeric values (markets, commodities, VIX) | Percentage change | >5% move |
| Chokepoint/disruption data | Compare vessel counts per chokepoint | >20% change |
| GPS hexagons | Compare high-classification hex count | Any new high-level hex |
| Thermal escalations | Diff by location/ID | Any new escalation |

4. Store new response + delta in cache
5. Return both current data and delta summary to caller

---

## 4. Component 2: Polling Cron Job

**File:** `scripts/agents/general_montgomery/worldmonitor_poll.py`
**Pattern:** Same as `news_watch.py` - standalone Python script, runs via launchd.

### 4.1 Tiered Schedule

| Tier | Interval | Endpoints polled | launchd plist |
|------|----------|-----------------|---------------|
| **fast** | 15 mins | military-flights, ais-snapshot, oref-alerts, telegram-feed, gpsjam | `com.atrophy.montgomery.worldmonitor.fast.plist` |
| **medium** | 45 mins | bootstrap (fast+slow), conflicts, thermal escalations | `com.atrophy.montgomery.worldmonitor.medium.plist` |
| **slow** | 4 hours | economic/*, trade/*, displacement/*, fleet report, anomalies | `com.atrophy.montgomery.worldmonitor.slow.plist` |

### 4.2 Execution Flow

1. Read tier argument from command line (`--tier fast|medium|slow`)
2. For each endpoint in the tier:
   a. Call the corresponding MCP tool via the worldmonitor server's HTTP client directly (not via Claude CLI - the poll script imports the server's fetch/diff logic as a library)
   b. Compute delta against cached data
3. Filter for significant changes (thresholds from section 3.4)
4. For each significant change, file an observation via memory_server.py:
   - Prefix: `[INTEL/WM/<DOMAIN>]`
   - Domains: MARITIME, MILITARY, ECONOMIC, CONFLICT, ALERTS, GPS, THERMAL, OSINT, TRADE, DISPLACEMENT
   - Example observations:
     - `[INTEL/WM/MARITIME] Dover Strait vessel surge: 69 vessels, +1280% above baseline`
     - `[INTEL/WM/MILITARY] 3 new NATO tanker aircraft detected over Baltic region`
     - `[INTEL/WM/ECONOMIC] VIX up 12% in 45 mins, Fear/Greed index shifted to Extreme Fear`
     - `[INTEL/WM/ALERTS] New OREF alert: rocket sirens in northern Israel`
     - `[INTEL/WM/GPS] 12 new high-level GPS jamming hexagons detected over eastern Mediterranean`
     - `[INTEL/WM/THERMAL] New thermal escalation detected near Zaporizhzhia, Ukraine`
5. Update `poll_state` table with current timestamp for the tier

### 4.3 Library Reuse and Code Structure

The poll script does NOT spawn the MCP server as a subprocess. Instead, `worldmonitor_server.py` is designed with a clean class-based separation from the start:

```python
# worldmonitor_server.py - structured for dual use

class WorldMonitorClient:
    """Stateless API client + cache manager. All state via constructor params."""

    def __init__(self, cache_db: str, base_url: str = "https://api.worldmonitor.app",
                 api_key: str | None = None):
        self.cache_db = cache_db
        self.base_url = base_url
        self.api_key = api_key
        # NO module-level globals, NO env var reads in the class

    def fetch(self, endpoint: str, params: dict = None, method: str = "GET", body: dict = None) -> dict: ...
    def fetch_cached(self, endpoint: str, params: dict = None) -> tuple[dict, dict | None]: ...  # (data, delta)
    def poll_tier(self, tier: str) -> list[dict]: ...  # returns list of significant changes
    def get_changes(self, since_minutes: int = 60, domains: list = None) -> list[dict]: ...

# MCP stdio entry point - only runs when executed directly
def main():
    """JSON-RPC 2.0 stdio loop. Reads env vars, creates WorldMonitorClient, dispatches tools."""
    client = WorldMonitorClient(
        cache_db=os.environ.get("WORLDMONITOR_CACHE_DB", ...),
        base_url=os.environ.get("WORLDMONITOR_BASE_URL", ...),
        api_key=os.environ.get("WORLDMONITOR_API_KEY"),
    )
    # ... stdio JSON-RPC loop using client ...

if __name__ == "__main__":
    main()
```

The poll script imports the class directly:

```python
# worldmonitor_poll.py
import sys, os, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'mcp'))
from worldmonitor_server import WorldMonitorClient

CACHE_DB = os.path.expanduser("~/.atrophy/worldmonitor_cache.db")
MONTGOMERY_DB = os.path.expanduser("~/.atrophy/agents/general_montgomery/data/memory.db")

client = WorldMonitorClient(cache_db=CACHE_DB)
changes = client.poll_tier(sys.argv[2])  # --tier fast|medium|slow

# File observations directly into Montgomery's SQLite memory DB
# This writes to the same observations table that memory_server.py reads
for change in changes:
    file_observation(MONTGOMERY_DB, change)

def file_observation(db_path: str, change: dict):
    """Write an observation directly to the agent's memory.db.

    Same table and format as memory_server.py's handle_observe().
    Uses the observations table with columns: id, content, category,
    created_at, active.
    """
    conn = sqlite3.connect(db_path)
    content = f"[INTEL/WM/{change['domain']}] {change['summary']}"
    conn.execute(
        "INSERT INTO observations (content, category, created_at, active) VALUES (?, ?, ?, 1)",
        (content, "intelligence", change['timestamp'])
    )
    conn.commit()
    conn.close()
```

**Key design constraint:** The poll script writes directly to Montgomery's `memory.db` SQLite file - the same database that `memory_server.py` reads from. This avoids needing to spawn the memory server as a subprocess. SQLite handles concurrent readers/writer safely at this scale (one writer every 15 mins, readers during conversation).

---

## 5. Integration Points

### 5.1 MCP Config Generation

Both apps (Python `inference.py` and Electron `inference.ts`) need two changes:

**1. Add worldmonitor to the MCP config:**

```json
{
  "worldmonitor": {
    "command": "python3",
    "args": ["<bundle_root>/mcp/worldmonitor_server.py"],
    "env": {
      "WORLDMONITOR_CACHE_DB": "/Users/<user>/.atrophy/worldmonitor_cache.db",
      "WORLDMONITOR_BASE_URL": "https://api.worldmonitor.app"
    }
  }
}
```

The server is added for ALL agents (it's shared), but only Montgomery's prompts instruct him to use it actively.

**2. Add `mcp__worldmonitor__*` to the Claude CLI `--allowedTools` string:**

In `inference.ts` (line ~560), the allowed tools are hardcoded:
```
mcp__memory__*,mcp__puppeteer__*,mcp__fal__*,mcp__google__*,mcp__shell__*,mcp__github__*
```

Add `mcp__worldmonitor__*` to this list. Without this, Claude CLI will reject all WorldMonitor tool calls. The equivalent change is needed in the Python app's `inference.py`.

### 5.2 Montgomery's Heartbeat Prompt

Addition to `agents/general_montgomery/prompts/heartbeat.md` and Obsidian `skills/`:

```markdown
## WorldMonitor Intelligence

Before assessing whether to reach out, check your sensor grid.
Call worldmonitor_get_changes to see what has shifted since the
last heartbeat. Cross-reference with your news_watch intelligence.

Significant WorldMonitor changes that warrant contact:
- New military activity in a theatre Will has asked about
- Chokepoint disruptions affecting global trade
- GPS jamming patterns expanding or shifting
- New OREF alerts or thermal escalations
- Market moves that signal structural stress (not noise)

Do not reach out for routine data refreshes. Only if the
picture has changed in a way that alters an assessment.
```

### 5.3 Montgomery's Tools Documentation

Addition to Obsidian `Agent Workspace/general_montgomery/skills/tools.md`:

```markdown
## WorldMonitor Intelligence Tools (mcp__worldmonitor__*)

Your sensor grid. Structured, machine-readable intelligence across
military, maritime, economic, and conflict domains. Data sourced from
ACLED, FRED, BIS, OREF, USNI, Wingbits, GDELT, and satellite thermal
monitoring.

### Continuous (cached, auto-polled)
- worldmonitor_situation - full situation snapshot (earthquakes, markets, outages, chokepoints)
- worldmonitor_maritime - vessel tracking and chokepoint disruptions
- worldmonitor_military_flights - military aircraft currently tracked
- worldmonitor_gps_jamming - GPS interference map
- worldmonitor_alerts - Israeli alert system (OREF)
- worldmonitor_osint_feed - Telegram OSINT channel feed
- worldmonitor_conflicts - ACLED armed conflict events
- worldmonitor_thermal - satellite thermal anomalies
- worldmonitor_get_changes - delta summary since last check

### On-demand (live fetch)
- worldmonitor_economic - FRED series, BIS rates, energy prices
- worldmonitor_trade - trade flows, tariffs, restrictions, barriers
- worldmonitor_displacement - population exposure and displacement data
- worldmonitor_fleet_report - USNI fleet positions
- worldmonitor_aircraft_lookup - aircraft identification by hex code
- worldmonitor_wingbits - ADS-B detection status
- worldmonitor_deduct_situation - AI situation assessment
- worldmonitor_anomalies - temporal baseline anomaly detection
- worldmonitor_news_summary - article summarisation
- worldmonitor_news_digest - news feed digest
- worldmonitor_humanitarian - humanitarian situation summaries
- worldmonitor_pizzint - PIZZINT/GDELT intelligence status
```

### 5.4 Cron Job Registration

Three launchd plists, registered via `cron.py`/`cron.ts`:

| Plist | Schedule | Command |
|-------|----------|---------|
| `com.atrophy.montgomery.worldmonitor.fast.plist` | Every 15 mins | `python3 worldmonitor_poll.py --tier fast` |
| `com.atrophy.montgomery.worldmonitor.medium.plist` | Every 45 mins | `python3 worldmonitor_poll.py --tier medium` |
| `com.atrophy.montgomery.worldmonitor.slow.plist` | Every 4 hours | `python3 worldmonitor_poll.py --tier slow` |

All three respect Montgomery's active hours (7am-10pm) from his agent config.

---

## 6. File Layout

### New files

```
mcp/
  worldmonitor_server.py              # MCP server (shared)

scripts/agents/general_montgomery/
  worldmonitor_poll.py                # Polling cron job
  jobs.json                           # Job definitions for cron system (NEW - Montgomery has no jobs.json yet)

~/.atrophy/
  worldmonitor_cache.db               # Created at runtime (gitignored)
```

**Montgomery's `jobs.json`** (new file - the cron system reads from `scripts/agents/<name>/jobs.json`):

```json
{
  "jobs": [
    {
      "name": "worldmonitor_fast",
      "script": "worldmonitor_poll.py",
      "args": ["--tier", "fast"],
      "interval_mins": 15,
      "active_start": 7,
      "active_end": 22
    },
    {
      "name": "worldmonitor_medium",
      "script": "worldmonitor_poll.py",
      "args": ["--tier", "medium"],
      "interval_mins": 45,
      "active_start": 7,
      "active_end": 22
    },
    {
      "name": "worldmonitor_slow",
      "script": "worldmonitor_poll.py",
      "args": ["--tier", "slow"],
      "interval_mins": 240,
      "active_start": 7,
      "active_end": 22
    }
  ]
}
```

### Modified files

```
# Both Python and Electron apps:
core/inference.py / src/main/inference.ts
  - Add worldmonitor to MCP config generation
  - Add mcp__worldmonitor__* to --allowedTools string

# Montgomery prompts (Obsidian canonical + local fallback):
Agent Workspace/general_montgomery/skills/tools.md
  - Add WorldMonitor tools section

Agent Workspace/general_montgomery/skills/system.md
  - No changes needed (capabilities are general enough)

agents/general_montgomery/prompts/heartbeat.md
  - Add WorldMonitor check instructions

# Cron registration:
scripts/cron.py / src/main/cron.ts
  - Register three new launchd plists (reads from jobs.json)
```

---

## 7. Error Handling

- **API unreachable:** Return cached data with `stale: true` flag and `cached_at` timestamp. Do not file stale data as new observations.
- **API returns error:** Log to `~/.atrophy/logs/general_montgomery/worldmonitor_<tier>.log` (follows existing cron log pattern). MCP server logs to `~/.atrophy/logs/worldmonitor_server.log`. Return cached data if available.
- **Cache DB missing:** Create on first access with schema from section 3.1.
- **Poll job fails:** Log error, exit cleanly. launchd will retry on next interval.
- **Rate limiting:** No auth/rate limiting observed, but if 429 responses appear, implement exponential backoff with max 3 retries.

---

## 8. Testing

- **Unit tests:** Delta detection logic with fixture data (known before/after responses, expected deltas)
- **Integration test:** Hit live WorldMonitor endpoints, verify response parsing
- **Cache test:** Verify cache read/write/diff cycle
- **Poll test:** Verify observation filing with mock memory server

---

## 9. WorldMonitor API Reference

Base URL: `https://api.worldmonitor.app`

All endpoints return JSON. No authentication required.

### Core
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/bootstrap` | `tier=fast\|slow`, `keys=techReadiness` |

### Maritime
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/ais-snapshot` | `candidates=true` |

### Aviation
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/aviation/v1/get-airport-ops-summary` | `airports=IST,ESB,...` |

### Military
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/military-flights` | - |
| GET | `/api/military/v1/get-usni-fleet-report` | - |
| GET | `/api/military/v1/get-wingbits-status` | - |
| POST | `/api/military/v1/get-aircraft-details-batch` | body: hex codes |

### News / OSINT
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/news/v1/list-feed-digest` | `variant=full&lang=en` |
| GET | `/api/news/v1/summarize-article-cache` | `cache_key=...` |
| POST | `/api/news/v1/summarize-article` | body: article URL |
| GET | `/api/telegram-feed` | `limit=50` |

### Intelligence
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/intelligence/v1/get-pizzint-status` | `include_gdelt=true` |
| POST | `/api/intelligence/v1/deduct-situation` | body: context |

### Economic
| Method | Path | Params |
|--------|------|--------|
| POST | `/api/economic/v1/get-fred-series-batch` | body: series list |
| GET | `/api/economic/v1/get-bis-policy-rates` | - |
| GET | `/api/economic/v1/get-bis-exchange-rates` | - |
| GET | `/api/economic/v1/get-bis-credit` | - |
| GET | `/api/economic/v1/get-energy-prices` | `commodities=` |

### Trade
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/trade/v1/get-trade-restrictions` | `countries=&limit=50` |
| GET | `/api/trade/v1/get-tariff-trends` | `reporting_country=840&partner_country=156&years=10` |
| GET | `/api/trade/v1/get-trade-flows` | `reporting_country=840&partner_country=156&years=10` |
| GET | `/api/trade/v1/get-trade-barriers` | `countries=&limit=50` |

### Conflict / Humanitarian
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/conflict/v1/list-acled-events` | - |
| POST | `/api/conflict/v1/get-humanitarian-summary-batch` | body: regions |

### Displacement
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/displacement/v1/get-displacement-summary` | `flow_limit=50` |
| GET | `/api/displacement/v1/get-population-exposure` | `mode=exposure&lat=...&lon=...&radius=50` |

### Thermal / Satellite
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/thermal/v1/list-thermal-escalations` | `max_items=12` |

### Infrastructure / Anomaly
| Method | Path | Params |
|--------|------|--------|
| POST | `/api/infrastructure/v1/record-baseline-snapshot` | body |
| GET | `/api/infrastructure/v1/get-temporal-baseline` | `type=military_flights\|vessels&region=global&count=N` |
| GET | `/api/infrastructure/v1/list-temporal-anomalies` | - |

### Alerts
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/oref-alerts` | `endpoint=history` (optional) |

### GPS
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/gpsjam` | - |

### Giving
| Method | Path | Params |
|--------|------|--------|
| GET | `/api/giving/v1/get-giving-summary` | - |

### Additional endpoints (from JS bundle, not observed in network traffic)
| Path | Likely purpose |
|------|---------------|
| `/api/hotspots` | Geopolitical hotspots |
| `/api/conflicts` | Conflict data |
| `/api/earthquakes` | Seismic events |
| `/api/weather` | Weather data |
| `/api/bases` | Military bases |
| `/api/waterways` | Waterway/chokepoint data |
| `/api/ais` | AIS vessel tracking |
| `/api/protests` | Protest events |
| `/api/flights` | General flight data |
| `/api/cables` | Undersea cables |
| `/api/outages` | Infrastructure outages |
| `/api/datacenters` | Data center locations |
| `/api/tech-events` | Tech events |
| `/api/startups` | Startup data |
| `/api/sanctions` | Sanctions data |
| `/api/radiation` | Radiation monitoring |
| `/api/cyber-threats` | Cyber threat intel |

### Static data endpoints
| URL | Purpose |
|-----|---------|
| `maps.worldmonitor.app/country-boundary-overrides.geojson` | Custom country borders |
| `www.worldmonitor.app/data/countries.geojson` | Country polygons |

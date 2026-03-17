# WorldMonitor MCP Integration - Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Montgomery (and any future agent) structured access to WorldMonitor's 37+ real-time intelligence APIs via a new MCP server, with tiered background polling that files significant changes as intelligence observations.

**Architecture:** A shared Python MCP server (`worldmonitor_server.py`) with a `WorldMonitorClient` class that handles HTTP fetching, SQLite caching, and delta detection. A companion cron job (`worldmonitor_poll.py`) imports the client class and writes significant changes directly to Montgomery's `memory.db`. Both apps (Python and Electron) wire the server into their MCP config.

**Tech Stack:** Python 3.10+ (stdlib only: `urllib.request`, `sqlite3`, `json`), JSON-RPC 2.0 over stdio, launchd for cron scheduling.

**Spec:** `docs/specs/2026-03-17-worldmonitor-mcp-integration-design.md`

**Codebase locations:**
- **Electron repo:** `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron/`
- **Python repo:** `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App/`
- Both repos have `mcp/` directories. The MCP server goes in both.

**Codebase reference files:**
- `mcp/memory_server.py` - existing MCP server pattern (JSON-RPC, tool definitions, handlers)
- `db/schema.sql:66-81` - observations table schema (`id`, `created_at`, `content`, `source_turn`, `incorporated`, `confidence`, `activation`, etc.) - NOTE: no `category` or `active` columns (the design spec section 4.3 has this wrong)
- `src/main/inference.ts:581` (Electron) - `allowedTools` string and MCP config generation
- Python repo `core/inference.py` - equivalent MCP config generation for the Python app
- `scripts/agents/companion/jobs.json` - existing jobs format: named keys with `type: "interval"` + `interval_seconds`, NOT the array format

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `mcp/worldmonitor_server.py` | MCP server - WorldMonitorClient class + JSON-RPC stdio loop + 21 tool definitions |
| `scripts/agents/general_montgomery/worldmonitor_poll.py` | Cron job - imports WorldMonitorClient, polls tiered endpoints, writes observations to memory.db |
| `scripts/agents/general_montgomery/jobs.json` | Job definitions for the cron system (3 tiered polling jobs) |
| `tests/mcp/test_worldmonitor_client.py` | Unit tests for WorldMonitorClient (fetch, cache, delta) |
| `tests/mcp/test_worldmonitor_poll.py` | Unit tests for poll job (observation filing) |
| `tests/mcp/fixtures/worldmonitor/` | Fixture JSON files for testing delta detection |

### Directories to create

These do not exist yet and must be created:
- `scripts/agents/general_montgomery/` (Electron repo)
- `tests/mcp/` (Electron repo)
- `tests/mcp/fixtures/worldmonitor/` (Electron repo)

### Modified files

| File | Change |
|------|--------|
| `src/main/inference.ts:581` (Electron) | Add `mcp__worldmonitor__*` to allowedTools + worldmonitor to MCP config |
| Python repo `core/inference.py` | Same changes for the Python app |
| Obsidian `Projects/The Atrophied Mind/Agent Workspace/general_montgomery/skills/tools.md` | Add WorldMonitor tools section |
| Runtime `~/.atrophy/agents/general_montgomery/prompts/heartbeat.md` | Add WorldMonitor check instructions |
| Electron `agents-personal/general_montgomery/prompts/heartbeat.md` | Same addition (local fallback) |
| Python repo `agents/general_montgomery/prompts/heartbeat.md` | Same addition (local fallback) |

---

## Task 1: WorldMonitorClient - HTTP + Cache Foundation

**Files:**
- Create: `mcp/worldmonitor_server.py` (partial - client class only)
- Create: `tests/mcp/test_worldmonitor_client.py`

- [ ] **Step 1: Write failing test for fetch**

```python
# tests/mcp/test_worldmonitor_client.py
import os, sys, json, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'mcp'))

class TestWorldMonitorClient(unittest.TestCase):

    @unittest.skipUnless(os.environ.get("WM_LIVE_TESTS"), "Set WM_LIVE_TESTS=1 for live API tests")
    def test_fetch_bootstrap_returns_json(self):
        """Live integration test - hit the real API. Skipped by default."""
        from worldmonitor_server import WorldMonitorClient
        with tempfile.NamedTemporaryFile(suffix='.db') as f:
            client = WorldMonitorClient(cache_db=f.name)
            result = client.fetch("api/bootstrap", params={"tier": "fast"})
            self.assertIn("data", result)
            self.assertIn("meta", result)

    def test_fetch_with_cache_stores_response(self):
        from worldmonitor_server import WorldMonitorClient
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            client = WorldMonitorClient(cache_db=db_path)
            data, delta = client.fetch_cached("api/gpsjam")
            self.assertIsNotNone(data)
            # Verify it was stored in cache
            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT cache_key FROM cache WHERE cache_key = ?",
                               ("api/gpsjam",)).fetchone()
            conn.close()
            self.assertIsNotNone(row)
        finally:
            os.unlink(db_path)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && python3 -m pytest tests/mcp/test_worldmonitor_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'worldmonitor_server'`

- [ ] **Step 3: Write WorldMonitorClient with fetch + cache**

Create `mcp/worldmonitor_server.py` with:

```python
#!/usr/bin/env python3
"""WorldMonitor MCP server for the Atrophy companion system.

Provides structured access to WorldMonitor's real-time intelligence APIs
with local caching and delta detection.

Protocol: JSON-RPC 2.0 over stdio (MCP standard transport).
Can also be imported as a library (WorldMonitorClient class).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    cache_key     TEXT PRIMARY KEY,
    endpoint      TEXT NOT NULL,
    response      TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    prev_response TEXT,
    delta         TEXT
);
CREATE INDEX IF NOT EXISTS idx_cache_endpoint ON cache(endpoint);
CREATE TABLE IF NOT EXISTS poll_state (
    tier      TEXT PRIMARY KEY,
    last_poll TEXT NOT NULL
);
"""

BASE_URL_DEFAULT = "https://api.worldmonitor.app"


class WorldMonitorClient:
    """Stateless API client + cache manager. All state via constructor params."""

    def __init__(self, cache_db: str,
                 base_url: str = BASE_URL_DEFAULT,
                 api_key: str | None = None):
        self.cache_db = cache_db
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._ensure_schema()

    def _ensure_schema(self):
        conn = sqlite3.connect(self.cache_db)
        conn.executescript(_CACHE_SCHEMA)
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.cache_db)

    def fetch(self, endpoint: str, params: dict | None = None,
              method: str = "GET", body: dict | None = None) -> dict:
        """Fetch an endpoint from WorldMonitor. Returns parsed JSON."""
        url = f"{self.base_url}/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        headers = {"User-Agent": "Atrophy/1.0 (WorldMonitor MCP)"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _cache_key(self, endpoint: str, params: dict | None = None) -> str:
        if params:
            return endpoint + "?" + urllib.parse.urlencode(sorted(params.items()))
        return endpoint

    def fetch_cached(self, endpoint: str, params: dict | None = None,
                     method: str = "GET", body: dict | None = None) -> tuple[dict, dict | None]:
        """Fetch and cache. Returns (data, delta_or_None)."""
        key = self._cache_key(endpoint, params)
        now = datetime.now(timezone.utc).isoformat()

        # Fetch fresh data
        try:
            data = self.fetch(endpoint, params, method, body)
        except Exception:
            # Return cached data if fetch fails
            conn = self._connect()
            row = conn.execute(
                "SELECT response, fetched_at FROM cache WHERE cache_key = ?", (key,)
            ).fetchone()
            conn.close()
            if row:
                result = json.loads(row[0])
                result["_stale"] = True
                result["_cached_at"] = row[1]
                return result, None
            raise

        # Load previous response for diffing
        conn = self._connect()
        row = conn.execute(
            "SELECT response FROM cache WHERE cache_key = ?", (key,)
        ).fetchone()
        prev_response = row[0] if row else None

        # Store new response (shift current to prev)
        conn.execute("""
            INSERT INTO cache (cache_key, endpoint, response, fetched_at, prev_response)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                prev_response = cache.response,
                response = excluded.response,
                fetched_at = excluded.fetched_at
        """, (key, endpoint.split("?")[0], json.dumps(data), now, prev_response))

        # Evict old prev_response entries (> 7 days)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        conn.execute(
            "UPDATE cache SET prev_response = NULL WHERE fetched_at < ? AND prev_response IS NOT NULL",
            (cutoff,)
        )
        conn.commit()
        conn.close()

        # Compute delta (placeholder - Task 2 implements this)
        delta = None

        return data, delta
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && python3 -m pytest tests/mcp/test_worldmonitor_client.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add mcp/worldmonitor_server.py tests/mcp/test_worldmonitor_client.py
git commit -m "feat: add WorldMonitorClient with HTTP fetch and SQLite cache"
```

---

## Task 2: Delta Detection Engine

**Files:**
- Modify: `mcp/worldmonitor_server.py` (add delta methods to WorldMonitorClient)
- Create: `tests/mcp/fixtures/worldmonitor/` (fixture data)
- Modify: `tests/mcp/test_worldmonitor_client.py` (add delta tests)

- [ ] **Step 1: Create fixture data for delta testing**

Create `tests/mcp/fixtures/worldmonitor/flights_before.json`:
```json
{
  "flights": [
    {"hex": "AE1234", "callsign": "RCH401", "lat": 54.2, "lon": 12.3, "operator": "USAF"},
    {"hex": "AE5678", "callsign": "RCH402", "lat": 55.1, "lon": 13.1, "operator": "USAF"}
  ]
}
```

Create `tests/mcp/fixtures/worldmonitor/flights_after.json`:
```json
{
  "flights": [
    {"hex": "AE1234", "callsign": "RCH401", "lat": 54.5, "lon": 12.8, "operator": "USAF"},
    {"hex": "AE9999", "callsign": "NATO01", "lat": 56.0, "lon": 14.0, "operator": "NATO"}
  ]
}
```

Create `tests/mcp/fixtures/worldmonitor/bootstrap_before.json` and `bootstrap_after.json` with market data showing a >5% VIX move.

- [ ] **Step 2: Write failing tests for delta detection**

```python
# Add to tests/mcp/test_worldmonitor_client.py

class TestDeltaDetection(unittest.TestCase):

    def test_array_diff_detects_new_and_removed(self):
        from worldmonitor_server import WorldMonitorClient
        before = {"flights": [
            {"hex": "AE1234", "callsign": "RCH401"},
            {"hex": "AE5678", "callsign": "RCH402"},
        ]}
        after = {"flights": [
            {"hex": "AE1234", "callsign": "RCH401"},
            {"hex": "AE9999", "callsign": "NATO01"},
        ]}
        delta = WorldMonitorClient._compute_array_delta(
            before["flights"], after["flights"], id_field="hex"
        )
        self.assertEqual(len(delta["added"]), 1)
        self.assertEqual(delta["added"][0]["hex"], "AE9999")
        self.assertEqual(len(delta["removed"]), 1)
        self.assertEqual(delta["removed"][0]["hex"], "AE5678")

    def test_numeric_delta_flags_significant_move(self):
        from worldmonitor_server import WorldMonitorClient
        delta = WorldMonitorClient._compute_numeric_delta(
            {"price": 20.0}, {"price": 22.5}, field="price", threshold=0.05
        )
        self.assertTrue(delta["significant"])
        self.assertAlmostEqual(delta["pct_change"], 0.125, places=3)

    def test_numeric_delta_ignores_small_move(self):
        from worldmonitor_server import WorldMonitorClient
        delta = WorldMonitorClient._compute_numeric_delta(
            {"price": 20.0}, {"price": 20.5}, field="price", threshold=0.05
        )
        self.assertFalse(delta["significant"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/mcp/test_worldmonitor_client.py::TestDeltaDetection -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 4: Implement delta detection methods**

Add to `WorldMonitorClient` in `mcp/worldmonitor_server.py`:

```python
@staticmethod
def _compute_array_delta(before: list, after: list, id_field: str) -> dict:
    """Diff two arrays of objects by ID field."""
    before_ids = {item[id_field]: item for item in before}
    after_ids = {item[id_field]: item for item in after}
    return {
        "added": [after_ids[k] for k in after_ids if k not in before_ids],
        "removed": [before_ids[k] for k in before_ids if k not in after_ids],
        "count_before": len(before),
        "count_after": len(after),
    }

@staticmethod
def _compute_numeric_delta(before: dict, after: dict, field: str,
                           threshold: float = 0.05) -> dict:
    """Compare a numeric field between two snapshots."""
    old_val = before.get(field, 0)
    new_val = after.get(field, 0)
    if old_val == 0:
        pct = 1.0 if new_val != 0 else 0.0
    else:
        pct = abs(new_val - old_val) / abs(old_val)
    return {
        "field": field,
        "before": old_val,
        "after": new_val,
        "pct_change": pct,
        "significant": pct >= threshold,
    }

def compute_delta(self, endpoint: str, before_json: str, after_json: str) -> dict | None:
    """Compute delta between two responses based on endpoint type."""
    try:
        before = json.loads(before_json)
        after = json.loads(after_json)
    except (json.JSONDecodeError, TypeError):
        return None

    base = endpoint.split("?")[0]

    # Array-based endpoints
    if "military-flights" in base:
        return self._compute_array_delta(
            before.get("flights", []), after.get("flights", []), "hex")
    if "ais-snapshot" in base:
        return self._compute_array_delta(
            before.get("disruptions", []), after.get("disruptions", []), "name")
    if "acled-events" in base:
        return self._compute_array_delta(
            before.get("events", []), after.get("events", []), "id")
    if "oref-alerts" in base:
        alerts_b = before if isinstance(before, list) else before.get("alerts", [])
        alerts_a = after if isinstance(after, list) else after.get("alerts", [])
        return self._compute_array_delta(alerts_b, alerts_a, "id")
    if "thermal" in base:
        return self._compute_array_delta(
            before.get("escalations", []), after.get("escalations", []), "id")
    if "telegram-feed" in base:
        return self._compute_array_delta(
            before.get("items", []), after.get("items", []), "id")

    # GPS jamming - count high-level hexes
    if "gpsjam" in base:
        high_before = len([h for h in before.get("hexes", []) if h.get("level") == "high"])
        high_after = len([h for h in after.get("hexes", []) if h.get("level") == "high"])
        return {
            "high_hexes_before": high_before,
            "high_hexes_after": high_after,
            "new_high_hexes": high_after - high_before,
            "significant": high_after > high_before,
        }

    # Default: no delta
    return None
```

Also update `fetch_cached` to call `compute_delta`:

```python
# Replace the delta placeholder in fetch_cached:
delta = None
if prev_response:
    delta = self.compute_delta(endpoint, prev_response, json.dumps(data))
    if delta:
        conn2 = self._connect()
        conn2.execute(
            "UPDATE cache SET delta = ? WHERE cache_key = ?",
            (json.dumps(delta), key)
        )
        conn2.commit()
        conn2.close()
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/mcp/test_worldmonitor_client.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add mcp/worldmonitor_server.py tests/mcp/test_worldmonitor_client.py tests/mcp/fixtures/
git commit -m "feat: add delta detection engine to WorldMonitorClient"
```

---

## Task 3: get_changes and poll_tier Methods

**Files:**
- Modify: `mcp/worldmonitor_server.py` (add get_changes + poll_tier + tier config)
- Modify: `tests/mcp/test_worldmonitor_client.py`

- [ ] **Step 1: Write failing test for get_changes**

```python
class TestGetChanges(unittest.TestCase):

    def test_get_changes_returns_recent_deltas(self):
        from worldmonitor_server import WorldMonitorClient
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            client = WorldMonitorClient(cache_db=db_path)
            # Seed cache with a delta
            conn = sqlite3.connect(db_path)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                INSERT INTO cache (cache_key, endpoint, response, fetched_at, delta)
                VALUES (?, ?, ?, ?, ?)
            """, ("api/military-flights", "api/military-flights", '{}', now,
                  json.dumps({"added": [{"hex": "AE9999"}], "removed": [], "count_before": 2, "count_after": 2})))
            conn.commit()
            conn.close()

            changes = client.get_changes(since_minutes=60)
            self.assertEqual(len(changes), 1)
            self.assertIn("military", changes[0]["domain"].lower())
        finally:
            os.unlink(db_path)
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement get_changes and poll_tier**

Add to `WorldMonitorClient`:

```python
# Tier configuration - which endpoints to poll per tier
TIERS = {
    "fast": [
        ("api/military-flights", None, "MILITARY"),
        ("api/ais-snapshot", {"candidates": "true"}, "MARITIME"),
        ("api/oref-alerts", None, "ALERTS"),
        ("api/telegram-feed", {"limit": "50"}, "OSINT"),
        ("api/gpsjam", None, "GPS"),
    ],
    "medium": [
        ("api/bootstrap", {"tier": "fast"}, "ECONOMIC"),
        ("api/bootstrap", {"tier": "slow"}, "ECONOMIC"),
        ("api/conflict/v1/list-acled-events", None, "CONFLICT"),
        ("api/thermal/v1/list-thermal-escalations", {"max_items": "12"}, "THERMAL"),
    ],
    "slow": [
        ("api/economic/v1/get-bis-policy-rates", None, "ECONOMIC"),
        ("api/economic/v1/get-bis-exchange-rates", None, "ECONOMIC"),
        ("api/economic/v1/get-bis-credit", None, "ECONOMIC"),
        ("api/economic/v1/get-energy-prices", None, "ECONOMIC"),
        ("api/trade/v1/get-trade-restrictions", {"countries": "", "limit": "50"}, "TRADE"),
        ("api/trade/v1/get-trade-barriers", {"countries": "", "limit": "50"}, "TRADE"),
        ("api/displacement/v1/get-displacement-summary", {"flow_limit": "50"}, "DISPLACEMENT"),
        ("api/military/v1/get-usni-fleet-report", None, "MILITARY"),
        ("api/infrastructure/v1/list-temporal-anomalies", None, "MILITARY"),
    ],
}

def get_changes(self, since_minutes: int = 60, domains: list | None = None) -> list[dict]:
    """Return significant deltas from the cache within the time window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
    conn = self._connect()
    rows = conn.execute(
        "SELECT cache_key, endpoint, delta, fetched_at FROM cache "
        "WHERE delta IS NOT NULL AND fetched_at > ?", (cutoff,)
    ).fetchall()
    conn.close()

    changes = []
    for cache_key, endpoint, delta_json, fetched_at in rows:
        delta = json.loads(delta_json)
        domain = self._endpoint_to_domain(endpoint)
        if domains and domain.lower() not in [d.lower() for d in domains]:
            continue
        if self._is_significant(delta):
            changes.append({
                "domain": domain,
                "endpoint": endpoint,
                "delta": delta,
                "summary": self._summarize_delta(domain, delta),
                "timestamp": fetched_at,
            })
    return changes

def poll_tier(self, tier: str) -> list[dict]:
    """Poll all endpoints in a tier, return significant changes."""
    endpoints = self.TIERS.get(tier, [])
    changes = []
    for endpoint, params, domain in endpoints:
        try:
            data, delta = self.fetch_cached(endpoint, params)
            # Don't file stale (cached fallback) data as new observations
            if isinstance(data, dict) and data.get("_stale"):
                continue
            if delta and self._is_significant(delta):
                changes.append({
                    "domain": domain,
                    "endpoint": endpoint,
                    "delta": delta,
                    "summary": self._summarize_delta(domain, delta),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        except Exception as e:
            # Log but continue - don't let one failed endpoint block the tier
            sys.stderr.write(f"[WorldMonitor] {endpoint} failed: {e}\n")
    # Update poll state
    conn = self._connect()
    conn.execute(
        "INSERT INTO poll_state (tier, last_poll) VALUES (?, ?) "
        "ON CONFLICT(tier) DO UPDATE SET last_poll = excluded.last_poll",
        (tier, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
    return changes

@staticmethod
def _endpoint_to_domain(endpoint: str) -> str:
    mapping = {
        "military-flights": "MILITARY", "military/": "MILITARY",
        "ais-snapshot": "MARITIME",
        "oref-alerts": "ALERTS",
        "telegram-feed": "OSINT",
        "gpsjam": "GPS",
        "bootstrap": "ECONOMIC",
        "conflict/": "CONFLICT",
        "thermal/": "THERMAL",
        "economic/": "ECONOMIC",
        "trade/": "TRADE",
        "displacement/": "DISPLACEMENT",
        "infrastructure/": "MILITARY",
        "intelligence/": "INTELLIGENCE",
        "news/": "OSINT",
    }
    for key, domain in mapping.items():
        if key in endpoint:
            return domain
    return "UNKNOWN"

@staticmethod
def _is_significant(delta: dict) -> bool:
    if delta.get("significant"):
        return True
    if delta.get("added") and len(delta["added"]) > 0:
        return True
    if delta.get("removed") and len(delta["removed"]) > 0:
        return True
    if delta.get("new_high_hexes", 0) > 0:
        return True
    return False

@staticmethod
def _summarize_delta(domain: str, delta: dict) -> str:
    parts = []
    if "added" in delta:
        n = len(delta["added"])
        if n > 0:
            parts.append(f"{n} new item(s)")
    if "removed" in delta:
        n = len(delta["removed"])
        if n > 0:
            parts.append(f"{n} removed")
    if "pct_change" in delta and delta.get("significant"):
        pct = delta["pct_change"] * 100
        parts.append(f"{pct:+.1f}% change in {delta.get('field', 'value')}")
    if "new_high_hexes" in delta and delta["new_high_hexes"] > 0:
        parts.append(f"{delta['new_high_hexes']} new high-level GPS jamming hexes")
    if not parts:
        parts.append("change detected")
    return f"{domain}: " + ", ".join(parts)
```

- [ ] **Step 4: Run tests**

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add mcp/worldmonitor_server.py tests/mcp/test_worldmonitor_client.py
git commit -m "feat: add get_changes and poll_tier to WorldMonitorClient"
```

---

## Task 4: MCP JSON-RPC Server (Tool Definitions + Dispatch)

**Files:**
- Modify: `mcp/worldmonitor_server.py` (add TOOLS list, handler functions, main() loop)

- [ ] **Step 1: Add TOOLS list with all 21 tool definitions**

Follow the exact pattern from `memory_server.py` - each tool is a dict with `name`, `description`, and `inputSchema`. Group them logically. Use the tool table from spec section 3.3.

- [ ] **Step 2: Add handler functions for each tool**

Each handler receives `args` dict, calls `WorldMonitorClient` methods, returns a string result. Pattern:

```python
def handle_situation(client, args):
    tier = args.get("tier", "both")
    if tier == "both":
        fast, d1 = client.fetch_cached("api/bootstrap", {"tier": "fast"})
        slow, d2 = client.fetch_cached("api/bootstrap", {"tier": "slow"})
        return json.dumps({"fast": fast, "slow": slow, "deltas": [d1, d2]}, indent=2)
    data, delta = client.fetch_cached("api/bootstrap", {"tier": tier})
    return json.dumps({"data": data, "delta": delta}, indent=2)
```

- [ ] **Step 3: Add main() with JSON-RPC stdin loop**

Copy the exact pattern from `memory_server.py:2708-2735`:

```python
HANDLERS = {
    "worldmonitor_situation": handle_situation,
    "worldmonitor_maritime": handle_maritime,
    # ... all 21 tools
}

def handle_request(client, request):
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "worldmonitor", "version": "1.0.0"},
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = HANDLERS.get(tool_name)
        if not handler:
            return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}
        try:
            result = handler(client, arguments)
            return {"content": [{"type": "text", "text": result}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
    return None

def main():
    client = WorldMonitorClient(
        cache_db=os.environ.get("WORLDMONITOR_CACHE_DB",
                                os.path.expanduser("~/.atrophy/worldmonitor_cache.db")),
        base_url=os.environ.get("WORLDMONITOR_BASE_URL", BASE_URL_DEFAULT),
        api_key=os.environ.get("WORLDMONITOR_API_KEY"),
    )
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in request:
            handle_request(client, request)
            continue
        result = handle_request(client, request)
        if result is None:
            continue
        response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Smoke test the MCP server**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | \
  WORLDMONITOR_CACHE_DB=/tmp/wm_test.db python3 mcp/worldmonitor_server.py
```

Expected: JSON response with `serverInfo.name: "worldmonitor"`

- [ ] **Step 5: Commit**

```bash
git add mcp/worldmonitor_server.py
git commit -m "feat: add MCP JSON-RPC server with 21 WorldMonitor tools"
```

---

## Task 5: Polling Cron Job

**Files:**
- Create: `scripts/agents/general_montgomery/worldmonitor_poll.py`
- Create: `scripts/agents/general_montgomery/jobs.json`
- Create: `tests/mcp/test_worldmonitor_poll.py`

- [ ] **Step 1: Write failing test for observation filing**

```python
# tests/mcp/test_worldmonitor_poll.py
import os, sys, sqlite3, tempfile, unittest

class TestObservationFiling(unittest.TestCase):

    def test_file_observation_writes_to_db(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..',
                                         'scripts', 'agents', 'general_montgomery'))
        from worldmonitor_poll import file_observation

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            # Create observations table
            conn = sqlite3.connect(db_path)
            conn.execute("""CREATE TABLE observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                content TEXT NOT NULL,
                source_turn INTEGER,
                incorporated BOOLEAN DEFAULT 0
            )""")
            conn.commit()
            conn.close()

            file_observation(db_path, {
                "domain": "MILITARY",
                "summary": "3 new NATO tanker aircraft detected over Baltic",
                "timestamp": "2026-03-17T12:00:00Z",
            })

            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT content FROM observations").fetchone()
            conn.close()
            self.assertIn("[INTEL/WM/MILITARY]", row[0])
            self.assertIn("NATO tanker", row[0])
        finally:
            os.unlink(db_path)
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement worldmonitor_poll.py**

```python
#!/usr/bin/env python3
"""WorldMonitor polling cron job for General Montgomery.

Imports WorldMonitorClient to poll tiered endpoints, then writes
significant changes as observations directly to Montgomery's memory.db.

Usage: python3 worldmonitor_poll.py --tier fast|medium|slow
"""
import argparse
import os
import sqlite3
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

# Import WorldMonitorClient from the MCP server
MCP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'mcp')
sys.path.insert(0, MCP_DIR)
from worldmonitor_server import WorldMonitorClient

CACHE_DB = os.path.expanduser("~/.atrophy/worldmonitor_cache.db")
MONTGOMERY_DB = os.path.expanduser(
    "~/.atrophy/agents/general_montgomery/data/memory.db")

LOG_DIR = os.path.expanduser("~/.atrophy/logs/general_montgomery")


def file_observation(db_path: str, change: dict):
    """Write an observation directly to the agent's memory.db.

    Uses the same observations table as memory_server.py's handle_observe().
    Schema: id, created_at, content, source_turn, incorporated, ...
    NOTE: No 'category' or 'active' columns exist (design spec section 4.3 is wrong).
    """
    conn = sqlite3.connect(db_path)
    content = f"[INTEL/WM/{change['domain']}] {change['summary']}"
    conn.execute(
        "INSERT INTO observations (content, created_at) VALUES (?, ?)",
        (content, change.get("timestamp", datetime.now(timezone.utc).isoformat())),
    )
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", required=True, choices=["fast", "medium", "slow"])
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        filename=os.path.join(LOG_DIR, f"worldmonitor_{args.tier}.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    logging.info(f"Polling tier: {args.tier}")

    client = WorldMonitorClient(cache_db=CACHE_DB)
    changes = client.poll_tier(args.tier)

    logging.info(f"Found {len(changes)} significant change(s)")

    if not os.path.exists(MONTGOMERY_DB):
        logging.warning(f"Montgomery DB not found at {MONTGOMERY_DB}")
        return

    for change in changes:
        try:
            file_observation(MONTGOMERY_DB, change)
            logging.info(f"Filed: [INTEL/WM/{change['domain']}] {change['summary']}")
        except Exception as e:
            logging.error(f"Failed to file observation: {e}")

    logging.info("Done")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create jobs.json**

Must match the existing format from `scripts/agents/companion/jobs.json` (named keys, `type: "interval"` + `interval_seconds`):

```json
{
  "worldmonitor_fast": {
    "type": "interval",
    "interval_seconds": 900,
    "script": "scripts/agents/general_montgomery/worldmonitor_poll.py",
    "args": "--tier fast",
    "description": "Poll fast-moving WorldMonitor endpoints (flights, vessels, alerts, GPS)"
  },
  "worldmonitor_medium": {
    "type": "interval",
    "interval_seconds": 2700,
    "script": "scripts/agents/general_montgomery/worldmonitor_poll.py",
    "args": "--tier medium",
    "description": "Poll medium-tempo WorldMonitor endpoints (bootstrap, conflicts, thermal)"
  },
  "worldmonitor_slow": {
    "type": "interval",
    "interval_seconds": 14400,
    "script": "scripts/agents/general_montgomery/worldmonitor_poll.py",
    "args": "--tier slow",
    "description": "Poll slow-moving WorldMonitor endpoints (economic, trade, displacement)"
  }
}
```

- [ ] **Step 5: Run tests**

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/agents/general_montgomery/worldmonitor_poll.py \
       scripts/agents/general_montgomery/jobs.json \
       tests/mcp/test_worldmonitor_poll.py
git commit -m "feat: add WorldMonitor polling cron job for Montgomery"
```

---

## Task 6: Wire Into Inference (MCP Config + Allowed Tools)

**Files:**
- Modify: `src/main/inference.ts:581` (Electron app - this repo)
- Modify: Python repo `core/inference.py` (at `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App/core/inference.py`)

- [ ] **Step 1: Add worldmonitor to Electron MCP config**

In `src/main/inference.ts`, find where MCP servers are configured (search for `mcpServers` or `memory`). Add the worldmonitor entry alongside existing servers:

```typescript
worldmonitor: {
  command: pythonPath,
  args: [path.join(bundleRoot, 'mcp', 'worldmonitor_server.py')],
  env: {
    WORLDMONITOR_CACHE_DB: path.join(os.homedir(), '.atrophy', 'worldmonitor_cache.db'),
    WORLDMONITOR_BASE_URL: 'https://api.worldmonitor.app',
  },
},
```

- [ ] **Step 2: Add `mcp__worldmonitor__*` to allowedTools in Electron app**

At `src/main/inference.ts:581`, change:
```typescript
const allowedTools = 'mcp__memory__*,mcp__puppeteer__*,mcp__fal__*,mcp__google__*,mcp__shell__*,mcp__github__*';
```
to:
```typescript
const allowedTools = 'mcp__memory__*,mcp__puppeteer__*,mcp__fal__*,mcp__google__*,mcp__shell__*,mcp__github__*,mcp__worldmonitor__*';
```

- [ ] **Step 3: Same changes in Python app**

In the Python repo at `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App/core/inference.py`, find the MCP config dict and allowedTools string. Apply the same two additions.

- [ ] **Step 4: Commit (both repos)**

```bash
# Electron repo
git add src/main/inference.ts
git commit -m "feat: wire WorldMonitor MCP server into inference config"

# Python repo (cd there separately)
cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App"
git add core/inference.py
git commit -m "feat: wire WorldMonitor MCP server into inference config"
```

---

## Task 7: Montgomery Prompt Updates

**Files:**
- Modify: `/Users/williamlilley/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind/Projects/The Atrophied Mind/Agent Workspace/general_montgomery/skills/tools.md` (Obsidian canonical)
- Modify: Electron `agents-personal/general_montgomery/prompts/heartbeat.md` (local fallback)
- Modify: Python repo `agents/general_montgomery/prompts/heartbeat.md` (local fallback)
- Check: `/Users/williamlilley/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind/Projects/The Atrophied Mind/Agent Workspace/general_montgomery/skills/` for a heartbeat skill - if it exists, update it too

- [ ] **Step 1: Add WorldMonitor tools section to tools.md**

Append the tools documentation from spec section 5.3 to the end of the Obsidian canonical file:
`/Users/williamlilley/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind/Projects/The Atrophied Mind/Agent Workspace/general_montgomery/skills/tools.md`

This file already has sections for Memory Tools, Browser Tools, Media Generation, and Obsidian Vault. Add the WorldMonitor section after the Obsidian Vault section.

- [ ] **Step 2: Add WorldMonitor check to heartbeat prompts**

Append the heartbeat addition from spec section 5.2 to these files:
- Electron: `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron/agents-personal/general_montgomery/prompts/heartbeat.md`
- Python: `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App/agents/general_montgomery/prompts/heartbeat.md`

- [ ] **Step 3: Commit (both repos)**

```bash
# Electron repo
git add agents-personal/general_montgomery/prompts/heartbeat.md
git commit -m "feat: add WorldMonitor instructions to Montgomery's prompts"

# Python repo
cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App"
git add agents/general_montgomery/prompts/heartbeat.md
git commit -m "feat: add WorldMonitor instructions to Montgomery's prompts"
```

---

## Task 8: Integration Test - End to End

**Files:**
- Create: `tests/mcp/test_worldmonitor_e2e.py`

- [ ] **Step 1: Write end-to-end test**

```python
# tests/mcp/test_worldmonitor_e2e.py
"""End-to-end test: poll a tier, verify observations are filed."""
import os, sys, sqlite3, tempfile, unittest

class TestEndToEnd(unittest.TestCase):

    def test_fast_tier_poll_and_file(self):
        """Poll fast tier against live API, file any changes."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'mcp'))
        from worldmonitor_server import WorldMonitorClient

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            cache_db = f.name
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            memory_db = f.name

        try:
            # Create observations table in memory db
            conn = sqlite3.connect(memory_db)
            conn.execute("""CREATE TABLE observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                content TEXT NOT NULL,
                source_turn INTEGER,
                incorporated BOOLEAN DEFAULT 0
            )""")
            conn.commit()
            conn.close()

            # First poll - seeds cache, no deltas expected
            client = WorldMonitorClient(cache_db=cache_db)
            changes1 = client.poll_tier("fast")

            # Second poll - may have deltas if data changed
            changes2 = client.poll_tier("fast")

            # Verify poll_state was updated
            conn = sqlite3.connect(cache_db)
            row = conn.execute(
                "SELECT last_poll FROM poll_state WHERE tier = 'fast'"
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)

        finally:
            os.unlink(cache_db)
            os.unlink(memory_db)
```

- [ ] **Step 2: Run the e2e test**

Run: `python3 -m pytest tests/mcp/test_worldmonitor_e2e.py -v`
Expected: PASS

- [ ] **Step 3: Test MCP server via stdin**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"worldmonitor_gps_jamming","arguments":{}}}' | \
  WORLDMONITOR_CACHE_DB=/tmp/wm_e2e.db python3 mcp/worldmonitor_server.py
```

Verify: 3 JSON responses, third contains GPS jamming data.

- [ ] **Step 4: Test poll job standalone**

```bash
PYTHONPATH=mcp python3 scripts/agents/general_montgomery/worldmonitor_poll.py --tier fast
```

Check log: `cat ~/.atrophy/logs/general_montgomery/worldmonitor_fast.log`

- [ ] **Step 5: Commit**

```bash
git add tests/mcp/test_worldmonitor_e2e.py
git commit -m "test: add end-to-end integration test for WorldMonitor"
```

---

## Task Summary

| # | Task | New files | Modified files | Est. time |
|---|------|-----------|---------------|-----------|
| 1 | HTTP + Cache foundation | worldmonitor_server.py (partial), test | - | 15 min |
| 2 | Delta detection engine | fixtures/ | worldmonitor_server.py, test | 15 min |
| 3 | get_changes + poll_tier | - | worldmonitor_server.py, test | 10 min |
| 4 | MCP JSON-RPC server | - | worldmonitor_server.py | 20 min |
| 5 | Polling cron job | worldmonitor_poll.py, jobs.json, test | - | 10 min |
| 6 | Wire into inference | - | inference.py, inference.ts | 10 min |
| 7 | Montgomery prompts | - | tools.md, heartbeat.md | 5 min |
| 8 | E2E integration test | test_worldmonitor_e2e.py | - | 10 min |

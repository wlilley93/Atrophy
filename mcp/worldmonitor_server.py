#!/usr/bin/env python3
"""WorldMonitor MCP server for the Atrophy companion agent.

Architecture:
  - WorldMonitorClient  - HTTP fetch + SQLite cache (Task 1) [done]
  - Delta detection     - _compute_array_delta, _compute_numeric_delta,
                          compute_delta (Task 2) [done]
  - get_changes/poll    - get_changes, poll_tier, TIERS, helper statics
                          (Task 3) [done]
  - JSON-RPC server     - Task 4 [done]

Protocol: JSON-RPC 2.0 over stdio (MCP standard transport).
stdlib only - no pip dependencies.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any


# ---------------------------------------------------------------------------
# WorldMonitorClient
# ---------------------------------------------------------------------------

class WorldMonitorClient:
    """HTTP client with SQLite caching for WorldMonitor APIs.

    Parameters
    ----------
    cache_db:
        Path to the SQLite database used for response caching.
    base_url:
        Base URL for WorldMonitor APIs. Defaults to the public endpoint.
    api_key:
        Optional API key. When set, all requests carry an
        ``Authorization: Bearer <key>`` header.
    """

    _BASE_URL_DEFAULT = "https://api.worldmonitor.app"
    _USER_AGENT = "Atrophy/1.0 (WorldMonitor MCP)"
    _TIMEOUT = 30  # seconds
    _PREV_RESPONSE_TTL_DAYS = 7

    def __init__(
        self,
        cache_db: str,
        base_url: str = _BASE_URL_DEFAULT,
        api_key: str | None = None,
    ) -> None:
        self._cache_db = cache_db
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Create cache and poll_state tables if they do not exist."""
        con = sqlite3.connect(self._cache_db)
        try:
            con.executescript(
                """
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
            )
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Cache key
    # ------------------------------------------------------------------

    def _cache_key(self, endpoint: str, params: dict[str, Any] | None) -> str:
        """Build a stable cache key from endpoint and sorted query params.

        Example: ``api/bootstrap?tier=fast``
        """
        if not params:
            return endpoint
        query = urllib.parse.urlencode(sorted(params.items()))
        return f"{endpoint}?{query}"

    # ------------------------------------------------------------------
    # Raw HTTP fetch
    # ------------------------------------------------------------------

    def fetch(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a raw HTTP request and return the parsed JSON response.

        Parameters
        ----------
        endpoint:
            API path relative to base_url (e.g. ``api/bootstrap``).
        params:
            URL query parameters. Ignored for POST when body is provided.
        method:
            HTTP method, either ``"GET"`` or ``"POST"``.
        body:
            Request body for POST requests. Will be JSON-serialised.

        Returns
        -------
        Parsed JSON (dict, list, etc.).

        Raises
        ------
        urllib.error.URLError:
            On network failure or non-2xx HTTP status.
        ValueError:
            If the response body is not valid JSON.
        """
        url = f"{self._base_url}/{endpoint}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        headers: dict[str, str] = {
            "User-Agent": self._USER_AGENT,
            "Accept": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        data: bytes | None = None
        if method.upper() == "POST" and body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())

        with urllib.request.urlopen(req, timeout=self._TIMEOUT) as resp:
            raw = resp.read()

        return json.loads(raw)

    # ------------------------------------------------------------------
    # Cached fetch
    # ------------------------------------------------------------------

    def fetch_cached(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], Any]:
        """Fetch from the API and cache the response.

        On success, the new response is stored and the previous response is
        shifted into ``prev_response``. When a previous response exists,
        ``compute_delta`` is called and the result is persisted in the
        ``delta`` column.

        On fetch failure, the cached response is returned with
        ``_stale: True`` and ``_cached_at`` injected into the data dict.

        Parameters
        ----------
        endpoint:
            API path (e.g. ``api/gpsjam/summary``).
        params:
            Optional query parameters.
        method:
            HTTP method.
        body:
            Optional POST body.

        Returns
        -------
        (data, delta)
            ``data`` is the parsed response dict (or stale cached dict).
            ``delta`` is a dict of changes from the previous response, or
            ``None`` when no previous response exists or the endpoint is
            unrecognised.

        Raises
        ------
        Exception:
            When the API is unreachable AND there is no cached response.
        """
        key = self._cache_key(endpoint, params or {})

        # ---- attempt live fetch ----------------------------------------
        fetch_error: Exception | None = None
        try:
            data = self.fetch(endpoint, params=params, method=method, body=body)
        except Exception as exc:
            fetch_error = exc
            data = None

        if data is not None:
            # Read prev_response BEFORE upserting so we can diff against it
            prev_response_json: str | None = None
            con = sqlite3.connect(self._cache_db)
            try:
                cur = con.execute(
                    "SELECT response FROM cache WHERE cache_key = ?",
                    (key,),
                )
                row = cur.fetchone()
                if row is not None:
                    prev_response_json = row[0]
            finally:
                con.close()

            # Store the new response (shifts current -> prev_response in DB)
            self._upsert_cache(key, endpoint, data)
            self._evict_stale_prev_responses()

            # Compute delta if we have a previous response to compare against
            delta: dict | None = None
            if prev_response_json is not None:
                delta = self.compute_delta(endpoint, prev_response_json, json.dumps(data))

            # Persist the computed delta into the cache row
            if delta is not None:
                con = sqlite3.connect(self._cache_db)
                try:
                    con.execute(
                        "UPDATE cache SET delta = ? WHERE cache_key = ?",
                        (json.dumps(delta), key),
                    )
                    con.commit()
                finally:
                    con.close()

            return data, delta

        # ---- fetch failed - attempt stale fallback ---------------------
        con = sqlite3.connect(self._cache_db)
        try:
            cur = con.execute(
                "SELECT response, fetched_at FROM cache WHERE cache_key = ?",
                (key,),
            )
            row = cur.fetchone()
        finally:
            con.close()

        if row is None:
            # No cached data and API unreachable - nothing we can do
            raise RuntimeError(
                f"WorldMonitor API unreachable and no cached data for '{key}': {fetch_error}"
            ) from fetch_error

        response_text, fetched_at = row
        stale_data: dict[str, Any] = json.loads(response_text)
        stale_data["_stale"] = True
        stale_data["_cached_at"] = fetched_at
        return stale_data, None

    # ------------------------------------------------------------------
    # Delta detection (Task 2)
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_array_delta(before: list, after: list, id_field: str) -> dict:
        """Diff two arrays of objects by id_field.

        Returns a dict with keys: added, removed, count_before, count_after.
        """
        before_by_id = {item[id_field]: item for item in before if id_field in item}
        after_by_id = {item[id_field]: item for item in after if id_field in item}
        before_ids = set(before_by_id.keys())
        after_ids = set(after_by_id.keys())
        added = [after_by_id[k] for k in sorted(after_ids - before_ids, key=str)]
        removed = [before_by_id[k] for k in sorted(before_ids - after_ids, key=str)]
        return {
            "added": added,
            "removed": removed,
            "count_before": len(before),
            "count_after": len(after),
        }

    @staticmethod
    def _compute_numeric_delta(
        before: dict,
        after: dict,
        field: str,
        threshold: float = 0.05,
    ) -> dict:
        """Compute pct change for a numeric field between two dicts.

        Returns: field, before, after, pct_change, significant.
        Significant when abs(pct_change) >= threshold.
        Zero-division is handled: pct_change is 0.0 when before value is 0.
        """
        v_before = before.get(field, 0) or 0
        v_after = after.get(field, 0) or 0
        if v_before == 0:
            pct_change = 0.0
        else:
            pct_change = (v_after - v_before) / abs(v_before)
        return {
            "field": field,
            "before": v_before,
            "after": v_after,
            "pct_change": pct_change,
            "significant": abs(pct_change) >= threshold,
        }

    def compute_delta(
        self,
        endpoint: str,
        before_json: str,
        after_json: str,
    ) -> dict | None:
        """Route to the appropriate delta method based on endpoint.

        Returns a delta dict, or None when the endpoint is unrecognised.
        """
        try:
            before = json.loads(before_json)
            after = json.loads(after_json)
        except (json.JSONDecodeError, TypeError):
            return None

        # Normalise endpoint for matching (strip leading slash, query string)
        ep = endpoint.split("?")[0].rstrip("/")

        if "military-flights" in ep:
            b_flights = before.get("flights", []) if isinstance(before, dict) else []
            a_flights = after.get("flights", []) if isinstance(after, dict) else []
            return self._compute_array_delta(b_flights, a_flights, "hex")

        if "ais-snapshot" in ep:
            b_dis = before.get("disruptions", []) if isinstance(before, dict) else []
            a_dis = after.get("disruptions", []) if isinstance(after, dict) else []
            return self._compute_array_delta(b_dis, a_dis, "name")

        if "acled-events" in ep or "list-acled-events" in ep:
            b_ev = before.get("events", []) if isinstance(before, dict) else []
            a_ev = after.get("events", []) if isinstance(after, dict) else []
            return self._compute_array_delta(b_ev, a_ev, "id")

        if "oref-alerts" in ep:
            # Handle both list and dict-with-alerts-key
            if isinstance(before, list):
                b_alerts = before
            else:
                b_alerts = before.get("alerts", []) if isinstance(before, dict) else []
            if isinstance(after, list):
                a_alerts = after
            else:
                a_alerts = after.get("alerts", []) if isinstance(after, dict) else []
            return self._compute_array_delta(b_alerts, a_alerts, "id")

        if "thermal" in ep or "list-thermal-escalations" in ep:
            b_esc = before.get("escalations", []) if isinstance(before, dict) else []
            a_esc = after.get("escalations", []) if isinstance(after, dict) else []
            return self._compute_array_delta(b_esc, a_esc, "id")

        if "telegram-feed" in ep:
            b_items = before.get("items", []) if isinstance(before, dict) else []
            a_items = after.get("items", []) if isinstance(after, dict) else []
            return self._compute_array_delta(b_items, a_items, "id")

        if "gpsjam" in ep:
            def _count_high(data: Any) -> int:
                hexes = data.get("hexes", []) if isinstance(data, dict) else []
                return sum(1 for h in hexes if h.get("level") == "high")

            high_before = _count_high(before)
            high_after = _count_high(after)
            return {
                "high_hexes_before": high_before,
                "high_hexes_after": high_after,
                "new_high_hexes": max(0, high_after - high_before),
                "significant": high_after > high_before,
            }

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upsert_cache(
        self,
        cache_key: str,
        endpoint: str,
        data: Any,
    ) -> None:
        """Insert or update a cache row, shifting current -> prev_response."""
        now = datetime.now(tz=timezone.utc).isoformat()
        response_text = json.dumps(data)

        con = sqlite3.connect(self._cache_db)
        try:
            con.execute(
                """
                INSERT INTO cache (cache_key, endpoint, response, fetched_at, prev_response, delta)
                VALUES (:key, :endpoint, :response, :now, NULL, NULL)
                ON CONFLICT(cache_key) DO UPDATE SET
                    prev_response = cache.response,
                    response      = :response,
                    fetched_at    = :now,
                    delta         = NULL
                """,
                {"key": cache_key, "endpoint": endpoint, "response": response_text, "now": now},
            )
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Tier definitions (Task 3)
    # ------------------------------------------------------------------

    TIERS: dict[str, list[tuple[str, dict | None, str]]] = {
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

    # ------------------------------------------------------------------
    # get_changes (Task 3)
    # ------------------------------------------------------------------

    def get_changes(
        self,
        since_minutes: int = 60,
        domains: list[str] | None = None,
    ) -> list[dict]:
        """Return cache rows with a non-null delta within the time window.

        Parameters
        ----------
        since_minutes:
            How far back to look (default 60 minutes).
        domains:
            Optional list of domain strings to filter on (e.g. ["MILITARY"]).

        Returns
        -------
        List of dicts with keys: domain, endpoint, delta, summary, timestamp.
        """
        cutoff = (
            datetime.now(tz=timezone.utc) - timedelta(minutes=since_minutes)
        ).isoformat()

        con = sqlite3.connect(self._cache_db)
        try:
            cur = con.execute(
                """
                SELECT endpoint, delta, fetched_at
                FROM cache
                WHERE delta IS NOT NULL
                  AND fetched_at >= ?
                ORDER BY fetched_at DESC
                """,
                (cutoff,),
            )
            rows = cur.fetchall()
        finally:
            con.close()

        results: list[dict] = []
        for endpoint, delta_json, fetched_at in rows:
            try:
                delta = json.loads(delta_json)
            except (json.JSONDecodeError, TypeError):
                continue

            domain = self._endpoint_to_domain(endpoint)
            if domains and domain not in domains:
                continue

            if not self._is_significant(delta):
                continue

            results.append({
                "domain": domain,
                "endpoint": endpoint,
                "delta": delta,
                "summary": self._summarize_delta(domain, delta),
                "timestamp": fetched_at,
            })

        return results

    # ------------------------------------------------------------------
    # poll_tier (Task 3)
    # ------------------------------------------------------------------

    def poll_tier(self, tier: str) -> list[dict]:
        """Poll all endpoints in a tier and return significant changes.

        Skips stale responses. Logs fetch failures to stderr but continues.
        Updates poll_state with the current timestamp after the run.

        Parameters
        ----------
        tier:
            One of "fast", "medium", "slow".

        Returns
        -------
        List of change dicts (same shape as get_changes output).
        """
        endpoints = self.TIERS.get(tier, [])
        changes: list[dict] = []

        for endpoint, params, domain in endpoints:
            try:
                data, delta = self.fetch_cached(endpoint, params=params)
            except Exception as exc:
                print(
                    f"[WorldMonitorClient] poll_tier({tier}): failed to fetch"
                    f" {endpoint}: {exc}",
                    file=sys.stderr,
                )
                continue

            # Skip stale responses
            if data.get("_stale"):
                continue

            if delta is None or not self._is_significant(delta):
                continue

            changes.append({
                "domain": domain,
                "endpoint": endpoint,
                "delta": delta,
                "summary": self._summarize_delta(domain, delta),
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            })

        # Update poll_state
        now = datetime.now(tz=timezone.utc).isoformat()
        con = sqlite3.connect(self._cache_db)
        try:
            con.execute(
                """
                INSERT INTO poll_state (tier, last_poll) VALUES (?, ?)
                ON CONFLICT(tier) DO UPDATE SET last_poll = excluded.last_poll
                """,
                (tier, now),
            )
            con.commit()
        finally:
            con.close()

        return changes

    # ------------------------------------------------------------------
    # Helper statics (Task 3)
    # ------------------------------------------------------------------

    @staticmethod
    def _endpoint_to_domain(endpoint: str) -> str:
        """Map an endpoint path to a domain label."""
        ep = endpoint.lower()
        if "military-flights" in ep or "usni" in ep or "temporal-anomalies" in ep:
            return "MILITARY"
        if "ais-snapshot" in ep:
            return "MARITIME"
        if "oref-alerts" in ep:
            return "ALERTS"
        if "telegram-feed" in ep:
            return "OSINT"
        if "gpsjam" in ep:
            return "GPS"
        if "bootstrap" in ep or "bis-" in ep or "energy-prices" in ep:
            return "ECONOMIC"
        if "acled-events" in ep:
            return "CONFLICT"
        if "thermal" in ep:
            return "THERMAL"
        if "trade-restrictions" in ep or "trade-barriers" in ep:
            return "TRADE"
        if "displacement" in ep:
            return "DISPLACEMENT"
        if "intelligence" in ep:
            return "INTELLIGENCE"
        return "UNKNOWN"

    @staticmethod
    def _is_significant(delta: dict) -> bool:
        """Return True when the delta represents a noteworthy change."""
        if not isinstance(delta, dict):
            return False
        # Array deltas
        if delta.get("added") or delta.get("removed"):
            return True
        # Numeric deltas
        if delta.get("significant"):
            return True
        # GPS hex deltas
        if delta.get("new_high_hexes", 0) > 0:
            return True
        return False

    @staticmethod
    def _summarize_delta(domain: str, delta: dict) -> str:
        """Produce a human-readable one-line summary of a delta."""
        if not isinstance(delta, dict):
            return f"{domain}: change detected"

        # GPS hex summary
        if "new_high_hexes" in delta:
            return (
                f"{domain}: {delta['new_high_hexes']} new high-jamming hex(es)"
                f" (total {delta.get('high_hexes_after', '?')})"
            )

        # Numeric delta summary
        if "field" in delta and "pct_change" in delta:
            pct = delta["pct_change"] * 100
            direction = "up" if pct > 0 else "down"
            return (
                f"{domain}: {delta['field']} moved {direction}"
                f" {abs(pct):.1f}% ({delta.get('before')} -> {delta.get('after')})"
            )

        # Array delta summary
        added = len(delta.get("added", []))
        removed = len(delta.get("removed", []))
        parts: list[str] = []
        if added:
            parts.append(f"+{added}")
        if removed:
            parts.append(f"-{removed}")
        change_str = ", ".join(parts) if parts else "no net change"
        return (
            f"{domain}: {change_str} items"
            f" ({delta.get('count_before', '?')} -> {delta.get('count_after', '?')})"
        )

    def _evict_stale_prev_responses(self) -> None:
        """Null out prev_response entries older than _PREV_RESPONSE_TTL_DAYS days.

        We compare fetched_at (ISO-8601 UTC) against the cutoff. Rows whose
        fetched_at predates the cutoff have their prev_response cleared so
        we do not accumulate unbounded historical data.
        """
        cutoff = (
            datetime.now(tz=timezone.utc) - timedelta(days=self._PREV_RESPONSE_TTL_DAYS)
        ).isoformat()
        con = sqlite3.connect(self._cache_db)
        try:
            con.execute(
                """
                UPDATE cache
                SET prev_response = NULL
                WHERE prev_response IS NOT NULL
                  AND fetched_at < :cutoff
                """,
                {"cutoff": cutoff},
            )
            con.commit()
        finally:
            con.close()


# ---------------------------------------------------------------------------
# TOOLS list - 21 MCP tool definitions (Task 4)
# ---------------------------------------------------------------------------

TOOLS = [
    # ---- Continuous / cached tools (9) ------------------------------------
    {
        "name": "worldmonitor_situation",
        "description": (
            "Bootstrap endpoint returning a structured situational summary for the "
            "requested tier. Use 'fast' for near-real-time ops data, 'slow' for "
            "macro/economic context, or 'both' for a full picture."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tier": {
                    "type": "string",
                    "enum": ["fast", "slow", "both"],
                    "description": "Which bootstrap tier to request (default: fast)",
                    "default": "fast",
                },
            },
            "required": [],
        },
    },
    {
        "name": "worldmonitor_maritime",
        "description": (
            "AIS vessel tracking snapshot. Returns maritime disruptions and optionally "
            "candidate vessels of interest."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_candidates": {
                    "type": "boolean",
                    "description": "Include candidate vessels of interest (default: true)",
                    "default": True,
                },
            },
            "required": [],
        },
    },
    {
        "name": "worldmonitor_military_flights",
        "description": (
            "Real-time military flight tracking. Returns active military aircraft "
            "positions and identifiers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "worldmonitor_gps_jamming",
        "description": (
            "GPS jamming status from GPSJam. Returns hexagonal grid data indicating "
            "jamming intensity levels globally."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "worldmonitor_alerts",
        "description": (
            "Israeli Home Front Command (OREF) rocket and missile alerts. Returns active "
            "alerts and optionally historical alert data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_history": {
                    "type": "boolean",
                    "description": "Include historical alert data (default: false)",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "worldmonitor_osint_feed",
        "description": (
            "OSINT Telegram feed aggregating open-source intelligence from monitored "
            "channels. Returns recent posts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of feed items to return (default: 50)",
                    "default": 50,
                },
            },
            "required": [],
        },
    },
    {
        "name": "worldmonitor_conflicts",
        "description": (
            "ACLED conflict event data. Returns recent armed conflict events including "
            "battles, explosions, and civilian targeting incidents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "worldmonitor_thermal",
        "description": (
            "Thermal escalation events derived from satellite thermal anomalies. "
            "Returns active thermal escalations indicating potential fires or explosions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_items": {
                    "type": "integer",
                    "description": "Maximum number of thermal escalation items (default: 12)",
                    "default": 12,
                },
            },
            "required": [],
        },
    },
    {
        "name": "worldmonitor_get_changes",
        "description": (
            "Read cached delta changes across WorldMonitor domains. Returns significant "
            "changes detected in the last N minutes, optionally filtered by domain."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "since_minutes": {
                    "type": "integer",
                    "description": "Look back window in minutes (default: 60)",
                    "default": 60,
                },
                "domains": {
                    "type": "string",
                    "description": (
                        "Comma-separated domain filter, e.g. 'MILITARY,MARITIME'. "
                        "Leave empty for all domains. Valid domains: MILITARY, MARITIME, "
                        "ALERTS, OSINT, GPS, ECONOMIC, CONFLICT, THERMAL, TRADE, "
                        "DISPLACEMENT, INTELLIGENCE."
                    ),
                },
            },
            "required": [],
        },
    },
    # ---- On-demand tools (12) ---------------------------------------------
    {
        "name": "worldmonitor_economic",
        "description": (
            "Economic and financial data from multiple sources. Select a series: "
            "'fred_batch' (US Federal Reserve economic indicators - requires commodities), "
            "'bis_policy_rates' (BIS central bank policy rates), "
            "'bis_exchange_rates' (BIS FX rates), "
            "'bis_credit' (BIS credit data), "
            "'energy_prices' (global energy price indices)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "series": {
                    "type": "string",
                    "enum": ["fred_batch", "bis_policy_rates", "bis_exchange_rates", "bis_credit", "energy_prices"],
                    "description": "Which economic data series to fetch",
                },
                "commodities": {
                    "type": "string",
                    "description": "Comma-separated FRED series IDs for fred_batch (e.g. 'GDP,UNRATE,CPIAUCSL')",
                },
            },
            "required": ["series"],
        },
    },
    {
        "name": "worldmonitor_trade",
        "description": (
            "International trade data. Queries: "
            "'restrictions' (active trade restrictions by country), "
            "'tariff_trends' (tariff trend data), "
            "'trade_flows' (bilateral trade flow statistics), "
            "'trade_barriers' (non-tariff trade barriers)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "enum": ["restrictions", "tariff_trends", "trade_flows", "trade_barriers"],
                    "description": "Which trade query to run",
                },
                "reporting_country": {
                    "type": "string",
                    "description": "ISO country code for reporting country (trade_flows)",
                },
                "partner_country": {
                    "type": "string",
                    "description": "ISO country code for partner country (trade_flows)",
                },
                "years": {
                    "type": "string",
                    "description": "Comma-separated years (trade_flows, e.g. '2022,2023')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 50)",
                    "default": 50,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "worldmonitor_displacement",
        "description": (
            "Population displacement data. Queries: "
            "'summary' (global displacement summary with flow data), "
            "'population_exposure' (population exposure within a radius of given coordinates)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "enum": ["summary", "population_exposure"],
                    "description": "Which displacement query to run",
                },
                "lat": {
                    "type": "number",
                    "description": "Latitude for population_exposure query",
                },
                "lon": {
                    "type": "number",
                    "description": "Longitude for population_exposure query",
                },
                "radius": {
                    "type": "number",
                    "description": "Radius in km for population_exposure query",
                },
                "flow_limit": {
                    "type": "integer",
                    "description": "Max displacement flows to return (summary, default: 50)",
                    "default": 50,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "worldmonitor_fleet_report",
        "description": (
            "USNI Naval Institute fleet report. Returns current US Navy fleet disposition "
            "and ship locations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "worldmonitor_aircraft_lookup",
        "description": (
            "Batch aircraft details lookup by ICAO hex codes. Returns registration, "
            "operator, type, and military classification for each aircraft."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "hex_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ICAO 24-bit hex codes (e.g. ['AE1234', 'AE5678'])",
                },
            },
            "required": ["hex_codes"],
        },
    },
    {
        "name": "worldmonitor_wingbits",
        "description": (
            "Wingbits crowdsourced ADS-B network status. Returns receiver counts and "
            "coverage quality metrics."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "worldmonitor_deduct_situation",
        "description": (
            "AI-powered situational deduction. Submits context text and returns an "
            "intelligence assessment synthesising current WorldMonitor data streams."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Context or question for situational deduction",
                },
            },
            "required": ["context"],
        },
    },
    {
        "name": "worldmonitor_anomalies",
        "description": (
            "Infrastructure temporal anomalies. Returns detected anomalies in "
            "infrastructure patterns that may indicate unusual activity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "worldmonitor_news_summary",
        "description": (
            "Summarise a news article by URL. Checks the cache first using cache_key "
            "to avoid redundant API calls. Returns an AI-generated summary."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL of the article to summarise",
                },
                "cache_key": {
                    "type": "string",
                    "description": "Cache key for this article (e.g. the URL or a slug)",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "worldmonitor_news_digest",
        "description": (
            "News feed digest. Returns a curated digest of recent news articles "
            "across tracked topics."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "variant": {
                    "type": "string",
                    "description": "Digest variant or category filter",
                },
                "lang": {
                    "type": "string",
                    "description": "Language code for digest (e.g. 'en', 'he')",
                },
            },
            "required": [],
        },
    },
    {
        "name": "worldmonitor_humanitarian",
        "description": (
            "Humanitarian situation summaries for one or more regions. Returns "
            "OCHA-sourced humanitarian data including needs, response, and access."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "regions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of region names or ISO codes (e.g. ['Gaza', 'Sudan'])",
                },
            },
            "required": ["regions"],
        },
    },
    {
        "name": "worldmonitor_pizzint",
        "description": (
            "PIZZINT intelligence status overview. Returns an aggregated intelligence "
            "picture, optionally including GDELT event data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_gdelt": {
                    "type": "boolean",
                    "description": "Include GDELT event data (default: false)",
                    "default": False,
                },
            },
            "required": [],
        },
    },
]


# ---------------------------------------------------------------------------
# Handler functions (Task 4)
# ---------------------------------------------------------------------------

def handle_situation(client: WorldMonitorClient, args: dict) -> str:
    tier = args.get("tier", "fast")
    if tier == "both":
        data_fast, delta_fast = client.fetch_cached("api/bootstrap", params={"tier": "fast"})
        data_slow, delta_slow = client.fetch_cached("api/bootstrap", params={"tier": "slow"})
        result = {
            "fast": data_fast,
            "slow": data_slow,
            "delta_fast": delta_fast,
            "delta_slow": delta_slow,
        }
    else:
        data, delta = client.fetch_cached("api/bootstrap", params={"tier": tier})
        result = {"data": data, "delta": delta}
    return json.dumps(result, indent=2)


def handle_maritime(client: WorldMonitorClient, args: dict) -> str:
    include_candidates = args.get("include_candidates", True)
    params = {"candidates": "true" if include_candidates else "false"}
    data, delta = client.fetch_cached("api/ais-snapshot", params=params)
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_military_flights(client: WorldMonitorClient, args: dict) -> str:
    data, delta = client.fetch_cached("api/military-flights")
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_gps_jamming(client: WorldMonitorClient, args: dict) -> str:
    data, delta = client.fetch_cached("api/gpsjam")
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_alerts(client: WorldMonitorClient, args: dict) -> str:
    include_history = args.get("include_history", False)
    params: dict | None = {"history": "true"} if include_history else None
    data, delta = client.fetch_cached("api/oref-alerts", params=params)
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_osint_feed(client: WorldMonitorClient, args: dict) -> str:
    limit = int(args.get("limit", 50))
    data, delta = client.fetch_cached("api/telegram-feed", params={"limit": str(limit)})
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_conflicts(client: WorldMonitorClient, args: dict) -> str:
    data, delta = client.fetch_cached("api/conflict/v1/list-acled-events")
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_thermal(client: WorldMonitorClient, args: dict) -> str:
    max_items = int(args.get("max_items", 12))
    data, delta = client.fetch_cached(
        "api/thermal/v1/list-thermal-escalations",
        params={"max_items": str(max_items)},
    )
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_get_changes(client: WorldMonitorClient, args: dict) -> str:
    since_minutes = int(args.get("since_minutes", 60))
    domains_raw = args.get("domains", "")
    domains: list[str] | None = None
    if domains_raw:
        domains = [d.strip().upper() for d in domains_raw.split(",") if d.strip()]
    changes = client.get_changes(since_minutes=since_minutes, domains=domains)
    return json.dumps({"changes": changes, "count": len(changes)}, indent=2)


def handle_economic(client: WorldMonitorClient, args: dict) -> str:
    series = args.get("series", "")
    if series == "fred_batch":
        commodities_raw = args.get("commodities", "")
        commodities = [c.strip() for c in commodities_raw.split(",") if c.strip()] if commodities_raw else []
        data, delta = client.fetch_cached(
            "api/economic/v1/get-fred-series-batch",
            method="POST",
            body={"series": commodities},
        )
    elif series == "bis_policy_rates":
        data, delta = client.fetch_cached("api/economic/v1/get-bis-policy-rates")
    elif series == "bis_exchange_rates":
        data, delta = client.fetch_cached("api/economic/v1/get-bis-exchange-rates")
    elif series == "bis_credit":
        data, delta = client.fetch_cached("api/economic/v1/get-bis-credit")
    elif series == "energy_prices":
        data, delta = client.fetch_cached("api/economic/v1/get-energy-prices")
    else:
        return json.dumps({"error": f"Unknown series: {series}"}, indent=2)
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_trade(client: WorldMonitorClient, args: dict) -> str:
    query = args.get("query", "")
    limit = int(args.get("limit", 50))
    if query == "restrictions":
        reporting = args.get("reporting_country", "")
        params: dict = {"limit": str(limit)}
        if reporting:
            params["countries"] = reporting
        data, delta = client.fetch_cached("api/trade/v1/get-trade-restrictions", params=params)
    elif query == "tariff_trends":
        params = {"limit": str(limit)}
        data, delta = client.fetch_cached("api/trade/v1/get-tariff-trends", params=params)
    elif query == "trade_flows":
        params = {"limit": str(limit)}
        reporting = args.get("reporting_country", "")
        partner = args.get("partner_country", "")
        years_raw = args.get("years", "")
        if reporting:
            params["reporting_country"] = reporting
        if partner:
            params["partner_country"] = partner
        if years_raw:
            params["years"] = years_raw
        data, delta = client.fetch_cached("api/trade/v1/get-trade-flows", params=params)
    elif query == "trade_barriers":
        params = {"limit": str(limit)}
        reporting = args.get("reporting_country", "")
        if reporting:
            params["countries"] = reporting
        data, delta = client.fetch_cached("api/trade/v1/get-trade-barriers", params=params)
    else:
        return json.dumps({"error": f"Unknown query: {query}"}, indent=2)
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_displacement(client: WorldMonitorClient, args: dict) -> str:
    query = args.get("query", "")
    if query == "summary":
        flow_limit = int(args.get("flow_limit", 50))
        data, delta = client.fetch_cached(
            "api/displacement/v1/get-displacement-summary",
            params={"flow_limit": str(flow_limit)},
        )
    elif query == "population_exposure":
        params: dict = {}
        if "lat" in args:
            params["lat"] = str(args["lat"])
        if "lon" in args:
            params["lon"] = str(args["lon"])
        if "radius" in args:
            params["radius"] = str(args["radius"])
        data, delta = client.fetch_cached("api/displacement/v1/get-population-exposure", params=params)
    else:
        return json.dumps({"error": f"Unknown query: {query}"}, indent=2)
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_fleet_report(client: WorldMonitorClient, args: dict) -> str:
    data, delta = client.fetch_cached("api/military/v1/get-usni-fleet-report")
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_aircraft_lookup(client: WorldMonitorClient, args: dict) -> str:
    hex_codes = args.get("hex_codes", [])
    data, delta = client.fetch_cached(
        "api/military/v1/get-aircraft-details-batch",
        method="POST",
        body={"hex_codes": hex_codes},
    )
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_wingbits(client: WorldMonitorClient, args: dict) -> str:
    data, delta = client.fetch_cached("api/military/v1/get-wingbits-status")
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_deduct_situation(client: WorldMonitorClient, args: dict) -> str:
    context = args.get("context", "")
    data, delta = client.fetch_cached(
        "api/intelligence/v1/deduct-situation",
        method="POST",
        body={"context": context},
    )
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_anomalies(client: WorldMonitorClient, args: dict) -> str:
    data, delta = client.fetch_cached("api/infrastructure/v1/list-temporal-anomalies")
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_news_summary(client: WorldMonitorClient, args: dict) -> str:
    url = args.get("url", "")
    cache_key_override = args.get("cache_key", url)
    # Check cache first - if we have a recent response for this cache key, return it
    if cache_key_override:
        import sqlite3 as _sqlite3
        try:
            con = _sqlite3.connect(client._cache_db)
            try:
                cur = con.execute(
                    "SELECT response, fetched_at FROM cache WHERE cache_key = ?",
                    (f"api/news/v1/summarize-article?url={cache_key_override}",),
                )
                row = cur.fetchone()
            finally:
                con.close()
            if row is not None:
                cached_data = json.loads(row[0])
                cached_data["_from_cache"] = True
                cached_data["_cached_at"] = row[1]
                return json.dumps({"data": cached_data, "delta": None}, indent=2)
        except Exception:
            pass
    data, delta = client.fetch_cached(
        "api/news/v1/summarize-article",
        method="POST",
        body={"url": url},
    )
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_news_digest(client: WorldMonitorClient, args: dict) -> str:
    params: dict = {}
    variant = args.get("variant", "")
    lang = args.get("lang", "")
    if variant:
        params["variant"] = variant
    if lang:
        params["lang"] = lang
    data, delta = client.fetch_cached("api/news/v1/list-feed-digest", params=params or None)
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_humanitarian(client: WorldMonitorClient, args: dict) -> str:
    regions = args.get("regions", [])
    data, delta = client.fetch_cached(
        "api/conflict/v1/get-humanitarian-summary-batch",
        method="POST",
        body={"regions": regions},
    )
    return json.dumps({"data": data, "delta": delta}, indent=2)


def handle_pizzint(client: WorldMonitorClient, args: dict) -> str:
    include_gdelt = args.get("include_gdelt", False)
    params: dict | None = {"include_gdelt": "true"} if include_gdelt else None
    data, delta = client.fetch_cached("api/intelligence/v1/get-pizzint-status", params=params)
    return json.dumps({"data": data, "delta": delta}, indent=2)


# ---------------------------------------------------------------------------
# HANDLERS dispatch table (Task 4)
# ---------------------------------------------------------------------------

HANDLERS = {
    "worldmonitor_situation": handle_situation,
    "worldmonitor_maritime": handle_maritime,
    "worldmonitor_military_flights": handle_military_flights,
    "worldmonitor_gps_jamming": handle_gps_jamming,
    "worldmonitor_alerts": handle_alerts,
    "worldmonitor_osint_feed": handle_osint_feed,
    "worldmonitor_conflicts": handle_conflicts,
    "worldmonitor_thermal": handle_thermal,
    "worldmonitor_get_changes": handle_get_changes,
    "worldmonitor_economic": handle_economic,
    "worldmonitor_trade": handle_trade,
    "worldmonitor_displacement": handle_displacement,
    "worldmonitor_fleet_report": handle_fleet_report,
    "worldmonitor_aircraft_lookup": handle_aircraft_lookup,
    "worldmonitor_wingbits": handle_wingbits,
    "worldmonitor_deduct_situation": handle_deduct_situation,
    "worldmonitor_anomalies": handle_anomalies,
    "worldmonitor_news_summary": handle_news_summary,
    "worldmonitor_news_digest": handle_news_digest,
    "worldmonitor_humanitarian": handle_humanitarian,
    "worldmonitor_pizzint": handle_pizzint,
}


# ---------------------------------------------------------------------------
# JSON-RPC request dispatcher (Task 4)
# ---------------------------------------------------------------------------

_SERVER_VERSION = "1.0.0"


def handle_request(client: WorldMonitorClient, request: dict) -> dict | None:
    """Dispatch a JSON-RPC request and return a result dict (or None for no reply)."""
    method = request.get("method", "")
    params = request.get("params", {}) or {}

    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "worldmonitor", "version": _SERVER_VERSION},
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
            result_text = handler(client, arguments)
            return {"content": [{"type": "text", "text": result_text}]}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            }

    return None


# ---------------------------------------------------------------------------
# main() - entry point for the MCP JSON-RPC server (Task 4)
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the WorldMonitor MCP server.

    Reads env vars, creates a WorldMonitorClient, then loops on stdin
    line-by-line parsing JSON-RPC 2.0 messages.

    Environment variables:
      WORLDMONITOR_CACHE_DB   - path to SQLite cache (default: worldmonitor.db)
      WORLDMONITOR_BASE_URL   - API base URL (optional)
      WORLDMONITOR_API_KEY    - Bearer token (optional)
    """
    cache_db = os.environ.get("WORLDMONITOR_CACHE_DB", "worldmonitor.db")
    base_url = os.environ.get("WORLDMONITOR_BASE_URL", WorldMonitorClient._BASE_URL_DEFAULT)
    api_key = os.environ.get("WORLDMONITOR_API_KEY") or None

    client = WorldMonitorClient(cache_db=cache_db, base_url=base_url, api_key=api_key)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Notifications (no id field) don't get a response
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

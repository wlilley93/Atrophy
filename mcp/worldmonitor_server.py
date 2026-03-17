#!/usr/bin/env python3
"""WorldMonitor MCP server for the Atrophy companion agent.

Architecture:
  - WorldMonitorClient  - HTTP fetch + SQLite cache (Task 1) [done]
  - Delta detection     - _compute_array_delta, _compute_numeric_delta,
                          compute_delta (Task 2) [done]
  - get_changes/poll    - get_changes, poll_tier, TIERS, helper statics
                          (Task 3) [done]
  - JSON-RPC server     - Task 4

Protocol: JSON-RPC 2.0 over stdio (MCP standard transport).
stdlib only - no pip dependencies.
"""
from __future__ import annotations

import json
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
# main() - entry point for the MCP JSON-RPC server (added in Task 4)
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the WorldMonitor MCP server.

    Full JSON-RPC server implementation is deferred to Task 4.
    Running this module directly will print a placeholder message.
    """
    import sys
    print(
        "WorldMonitor MCP server - JSON-RPC server not yet implemented (Task 4).",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()

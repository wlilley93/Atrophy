#!/usr/bin/env python3
"""WorldMonitor MCP server for the Atrophy companion agent.

Architecture:
  - WorldMonitorClient  - HTTP fetch + SQLite cache (this task)
  - Delta detection     - Task 2
  - get_changes/poll    - Task 3
  - JSON-RPC server     - Task 4

Protocol: JSON-RPC 2.0 over stdio (MCP standard transport).
stdlib only - no pip dependencies.
"""
from __future__ import annotations

import json
import sqlite3
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
        shifted into ``prev_response``. Delta computation is a placeholder
        (returns ``None``) and will be filled in Task 2.

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
            ``delta`` is ``None`` (placeholder until Task 2).

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
            # Success path - store and return fresh data
            self._upsert_cache(key, endpoint, data)
            self._evict_stale_prev_responses()
            delta = None  # placeholder - Task 2 will compute this
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

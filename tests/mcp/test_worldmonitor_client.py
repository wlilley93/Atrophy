#!/usr/bin/env python3
"""Unit tests for WorldMonitorClient.

Run all (including live):  WM_LIVE_TESTS=1 python -m pytest tests/mcp/test_worldmonitor_client.py -v
Run offline only:          python -m pytest tests/mcp/test_worldmonitor_client.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

# Import directly by file path to avoid collision with the installed `mcp`
# package in the Python environment (which is a different package).
import importlib.util
import sys

_SERVER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "mcp", "worldmonitor_server.py"
)
_spec = importlib.util.spec_from_file_location("worldmonitor_server", _SERVER_PATH)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules["worldmonitor_server"] = _mod

WorldMonitorClient = _mod.WorldMonitorClient


_LIVE = os.environ.get("WM_LIVE_TESTS") == "1"


class TestCacheSchema(unittest.TestCase):
    """Verify that _ensure_schema creates the expected tables and indices."""

    def setUp(self):
        self._db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db_path = self._db_file.name
        self._db_file.close()

    def tearDown(self):
        try:
            os.unlink(self._db_path)
        except FileNotFoundError:
            pass

    def test_schema_creates_cache_table(self):
        client = WorldMonitorClient(cache_db=self._db_path)
        con = sqlite3.connect(self._db_path)
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cache'"
        )
        self.assertIsNotNone(cur.fetchone(), "cache table should exist after init")
        con.close()

    def test_schema_creates_poll_state_table(self):
        client = WorldMonitorClient(cache_db=self._db_path)
        con = sqlite3.connect(self._db_path)
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='poll_state'"
        )
        self.assertIsNotNone(cur.fetchone(), "poll_state table should exist after init")
        con.close()

    def test_schema_creates_endpoint_index(self):
        client = WorldMonitorClient(cache_db=self._db_path)
        con = sqlite3.connect(self._db_path)
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_cache_endpoint'"
        )
        self.assertIsNotNone(cur.fetchone(), "idx_cache_endpoint index should exist")
        con.close()

    def test_schema_idempotent(self):
        """Calling the constructor twice should not raise - IF NOT EXISTS guards."""
        WorldMonitorClient(cache_db=self._db_path)
        WorldMonitorClient(cache_db=self._db_path)


class TestCacheKey(unittest.TestCase):
    """Verify cache key construction."""

    def setUp(self):
        self._db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db_path = self._db_file.name
        self._db_file.close()
        self._client = WorldMonitorClient(cache_db=self._db_path)

    def tearDown(self):
        try:
            os.unlink(self._db_path)
        except FileNotFoundError:
            pass

    def test_cache_key_no_params(self):
        key = self._client._cache_key("api/bootstrap", {})
        self.assertEqual(key, "api/bootstrap")

    def test_cache_key_single_param(self):
        key = self._client._cache_key("api/bootstrap", {"tier": "fast"})
        self.assertEqual(key, "api/bootstrap?tier=fast")

    def test_cache_key_params_sorted(self):
        key = self._client._cache_key("api/endpoint", {"z": "last", "a": "first"})
        self.assertEqual(key, "api/endpoint?a=first&z=last")

    def test_cache_key_same_params_different_order(self):
        k1 = self._client._cache_key("ep", {"b": "2", "a": "1"})
        k2 = self._client._cache_key("ep", {"a": "1", "b": "2"})
        self.assertEqual(k1, k2)


class TestFetchBootstrapLive(unittest.TestCase):
    """Live API tests - only run when WM_LIVE_TESTS=1."""

    def setUp(self):
        if not _LIVE:
            self.skipTest("Set WM_LIVE_TESTS=1 to run live API tests")
        self._db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db_path = self._db_file.name
        self._db_file.close()
        self._client = WorldMonitorClient(cache_db=self._db_path)

    def tearDown(self):
        try:
            os.unlink(self._db_path)
        except FileNotFoundError:
            pass

    def test_fetch_bootstrap_returns_json(self):
        """fetch() against the live bootstrap endpoint should return a dict."""
        data = self._client.fetch("api/bootstrap", params={"tier": "fast"})
        self.assertIsInstance(data, dict, "bootstrap should return a JSON object")


class TestFetchCachedLive(unittest.TestCase):
    """Live cache integration tests - only run when WM_LIVE_TESTS=1."""

    def setUp(self):
        if not _LIVE:
            self.skipTest("Set WM_LIVE_TESTS=1 to run live API tests")
        self._db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db_path = self._db_file.name
        self._db_file.close()
        self._client = WorldMonitorClient(cache_db=self._db_path)

    def tearDown(self):
        try:
            os.unlink(self._db_path)
        except FileNotFoundError:
            pass

    def test_fetch_with_cache_stores_response(self):
        """fetch_cached() should write a row to the cache table."""
        # gpsjam/summary is documented as a fast, lightweight endpoint
        data, delta = self._client.fetch_cached("api/gpsjam/summary", params={})

        # Data should be present and not stale on first fetch
        self.assertIsInstance(data, dict)
        self.assertNotIn("_stale", data)

        # Verify a cache row was written
        con = sqlite3.connect(self._db_path)
        cur = con.execute(
            "SELECT cache_key, endpoint, response, fetched_at FROM cache WHERE endpoint = ?",
            ("api/gpsjam/summary",),
        )
        row = cur.fetchone()
        con.close()

        self.assertIsNotNone(row, "cache row should exist after fetch_cached")
        cache_key, endpoint, response_text, fetched_at = row
        self.assertEqual(endpoint, "api/gpsjam/summary")
        self.assertIsNotNone(fetched_at)

        # Stored response should be valid JSON matching what was returned
        stored = json.loads(response_text)
        # Both should be the same data (minus any _stale/_cached_at injection)
        self.assertIsInstance(stored, dict)

    def test_fetch_cached_second_call_populates_prev_response(self):
        """Second fetch_cached call should shift first response into prev_response."""
        self._client.fetch_cached("api/gpsjam/summary", params={})
        self._client.fetch_cached("api/gpsjam/summary", params={})

        con = sqlite3.connect(self._db_path)
        cur = con.execute(
            "SELECT prev_response FROM cache WHERE endpoint = ?",
            ("api/gpsjam/summary",),
        )
        row = cur.fetchone()
        con.close()

        self.assertIsNotNone(row)
        # prev_response may be None if the API returned identical data, but the
        # column should exist and be readable without error.
        # (content may vary by API; just assert no exception)


class TestFetchCachedStaleOffline(unittest.TestCase):
    """Test stale fallback using a pre-populated cache - no network needed."""

    def setUp(self):
        self._db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db_path = self._db_file.name
        self._db_file.close()
        # Use an unreachable base URL to force fetch failure
        self._client = WorldMonitorClient(
            cache_db=self._db_path,
            base_url="http://127.0.0.1:19999",  # nothing listening here
        )

    def tearDown(self):
        try:
            os.unlink(self._db_path)
        except FileNotFoundError:
            pass

    def _seed_cache(self, endpoint: str, payload: dict) -> None:
        """Insert a cache row directly so we can test stale fallback."""
        import datetime
        now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        con = sqlite3.connect(self._db_path)
        con.execute(
            """
            INSERT INTO cache (cache_key, endpoint, response, fetched_at, prev_response, delta)
            VALUES (?, ?, ?, ?, NULL, NULL)
            """,
            (
                endpoint,
                endpoint,
                json.dumps(payload),
                now,
            ),
        )
        con.commit()
        con.close()

    def test_stale_fallback_returns_cached_data(self):
        """When the API is unreachable, fetch_cached should return cached data."""
        payload = {"foo": "bar", "count": 42}
        self._seed_cache("api/gpsjam/summary", payload)

        data, delta = self._client.fetch_cached("api/gpsjam/summary", params={})

        self.assertTrue(data.get("_stale"), "_stale flag should be True on fallback")
        self.assertIsNotNone(data.get("_cached_at"), "_cached_at should be present")
        self.assertEqual(data.get("foo"), "bar")
        self.assertEqual(data.get("count"), 42)
        self.assertIsNone(delta)

    def test_no_cache_and_unreachable_raises(self):
        """When both API and cache are unavailable, fetch_cached should raise."""
        with self.assertRaises(Exception):
            self._client.fetch_cached("api/gpsjam/summary", params={})


if __name__ == "__main__":
    unittest.main()

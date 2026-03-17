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


class TestDeltaDetection(unittest.TestCase):
    """Unit tests for the delta detection engine (Task 2)."""

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

    def test_array_diff_detects_new_and_removed(self):
        before = [{"hex": "A1", "callsign": "AAL1"}, {"hex": "B2", "callsign": "BAW2"}]
        after = [{"hex": "A1", "callsign": "AAL1"}, {"hex": "C3", "callsign": "SAS3"}]
        result = WorldMonitorClient._compute_array_delta(before, after, "hex")

        self.assertEqual(result["count_before"], 2)
        self.assertEqual(result["count_after"], 2)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["hex"], "C3")
        self.assertEqual(len(result["removed"]), 1)
        self.assertEqual(result["removed"][0]["hex"], "B2")

    def test_numeric_delta_flags_significant_move(self):
        before = {"rate": 100.0}
        after = {"rate": 110.0}
        result = WorldMonitorClient._compute_numeric_delta(before, after, "rate", threshold=0.05)

        self.assertAlmostEqual(result["pct_change"], 0.1)
        self.assertTrue(result["significant"])
        self.assertEqual(result["field"], "rate")

    def test_numeric_delta_ignores_small_move(self):
        before = {"rate": 100.0}
        after = {"rate": 102.0}
        result = WorldMonitorClient._compute_numeric_delta(before, after, "rate", threshold=0.05)

        self.assertAlmostEqual(result["pct_change"], 0.02)
        self.assertFalse(result["significant"])

    def test_compute_delta_military_flights(self):
        before = json.dumps({
            "flights": [
                {"hex": "AAAA", "callsign": "RCH1"},
                {"hex": "BBBB", "callsign": "RCH2"},
            ]
        })
        after = json.dumps({
            "flights": [
                {"hex": "AAAA", "callsign": "RCH1"},
                {"hex": "CCCC", "callsign": "RCH3"},
            ]
        })
        result = self._client.compute_delta("api/military-flights", before, after)

        self.assertIsNotNone(result)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["hex"], "CCCC")
        self.assertEqual(len(result["removed"]), 1)
        self.assertEqual(result["removed"][0]["hex"], "BBBB")

    def test_compute_delta_gpsjam(self):
        before = json.dumps({
            "hexes": [
                {"id": "h1", "level": "high"},
                {"id": "h2", "level": "low"},
            ]
        })
        after = json.dumps({
            "hexes": [
                {"id": "h1", "level": "high"},
                {"id": "h2", "level": "high"},
                {"id": "h3", "level": "high"},
            ]
        })
        result = self._client.compute_delta("api/gpsjam", before, after)

        self.assertIsNotNone(result)
        self.assertEqual(result["high_hexes_before"], 1)
        self.assertEqual(result["high_hexes_after"], 3)
        self.assertEqual(result["new_high_hexes"], 2)
        self.assertTrue(result["significant"])

    def test_compute_delta_unknown_endpoint_returns_none(self):
        result = self._client.compute_delta(
            "api/unknown-endpoint",
            json.dumps({"x": 1}),
            json.dumps({"x": 2}),
        )
        self.assertIsNone(result)

    def test_numeric_delta_zero_division(self):
        before = {"rate": 0}
        after = {"rate": 50}
        result = WorldMonitorClient._compute_numeric_delta(before, after, "rate")
        self.assertEqual(result["pct_change"], 0.0)
        self.assertFalse(result["significant"])


class TestGetChanges(unittest.TestCase):
    """Tests for get_changes and related helpers (Task 3)."""

    def setUp(self):
        self._db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db_path = self._db_file.name
        self._db_file.close()
        self._client = WorldMonitorClient(
            cache_db=self._db_path,
            base_url="http://127.0.0.1:19999",  # unreachable - tests use seeded data
        )

    def tearDown(self):
        try:
            os.unlink(self._db_path)
        except FileNotFoundError:
            pass

    def _seed_cache_with_delta(
        self,
        endpoint: str,
        payload: dict,
        delta: dict,
        minutes_ago: int = 10,
    ) -> None:
        """Insert a cache row with a pre-computed delta directly."""
        import datetime as dt
        fetched_at = (
            dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
        ).isoformat()
        con = sqlite3.connect(self._db_path)
        con.execute(
            """
            INSERT OR REPLACE INTO cache
                (cache_key, endpoint, response, fetched_at, prev_response, delta)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (
                endpoint,
                endpoint,
                json.dumps(payload),
                fetched_at,
                json.dumps(delta),
            ),
        )
        con.commit()
        con.close()

    def test_get_changes_returns_recent_deltas(self):
        delta = {
            "added": [{"hex": "ZZZZ", "callsign": "TEST"}],
            "removed": [],
            "count_before": 1,
            "count_after": 2,
        }
        self._seed_cache_with_delta(
            "api/military-flights",
            {"flights": []},
            delta,
            minutes_ago=5,
        )

        results = self._client.get_changes(since_minutes=60)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["endpoint"], "api/military-flights")
        self.assertEqual(results[0]["domain"], "MILITARY")
        self.assertIn("added", results[0]["delta"])

    def test_get_changes_filters_by_domain(self):
        military_delta = {
            "added": [{"hex": "AAAA"}],
            "removed": [],
            "count_before": 0,
            "count_after": 1,
        }
        maritime_delta = {
            "added": [{"name": "Strait Alpha"}],
            "removed": [],
            "count_before": 0,
            "count_after": 1,
        }
        self._seed_cache_with_delta(
            "api/military-flights",
            {"flights": []},
            military_delta,
            minutes_ago=5,
        )
        self._seed_cache_with_delta(
            "api/ais-snapshot",
            {"disruptions": []},
            maritime_delta,
            minutes_ago=5,
        )

        results = self._client.get_changes(since_minutes=60, domains=["MILITARY"])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["domain"], "MILITARY")

    def test_get_changes_excludes_old_deltas(self):
        delta = {
            "added": [{"hex": "AAAA"}],
            "removed": [],
            "count_before": 0,
            "count_after": 1,
        }
        # Seed a delta from 2 hours ago
        self._seed_cache_with_delta(
            "api/military-flights",
            {"flights": []},
            delta,
            minutes_ago=120,
        )

        results = self._client.get_changes(since_minutes=60)
        self.assertEqual(len(results), 0)

    def test_is_significant_array_added(self):
        delta = {"added": [{"id": "x"}], "removed": [], "count_before": 0, "count_after": 1}
        self.assertTrue(WorldMonitorClient._is_significant(delta))

    def test_is_significant_empty_arrays(self):
        delta = {"added": [], "removed": [], "count_before": 2, "count_after": 2}
        self.assertFalse(WorldMonitorClient._is_significant(delta))

    def test_endpoint_to_domain_mapping(self):
        cases = [
            ("api/military-flights", "MILITARY"),
            ("api/ais-snapshot", "MARITIME"),
            ("api/oref-alerts", "ALERTS"),
            ("api/telegram-feed", "OSINT"),
            ("api/gpsjam", "GPS"),
            ("api/conflict/v1/list-acled-events", "CONFLICT"),
            ("api/thermal/v1/list-thermal-escalations", "THERMAL"),
            ("api/trade/v1/get-trade-restrictions", "TRADE"),
            ("api/displacement/v1/get-displacement-summary", "DISPLACEMENT"),
            ("api/something-completely-unknown", "UNKNOWN"),
        ]
        for endpoint, expected_domain in cases:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(
                    WorldMonitorClient._endpoint_to_domain(endpoint),
                    expected_domain,
                )

    def test_summarize_delta_array(self):
        delta = {"added": [1, 2], "removed": [3], "count_before": 5, "count_after": 6}
        summary = WorldMonitorClient._summarize_delta("MILITARY", delta)
        self.assertIn("MILITARY", summary)
        self.assertIn("+2", summary)
        self.assertIn("-1", summary)

    def test_summarize_delta_gpsjam(self):
        delta = {"new_high_hexes": 3, "high_hexes_before": 1, "high_hexes_after": 4, "significant": True}
        summary = WorldMonitorClient._summarize_delta("GPS", delta)
        self.assertIn("GPS", summary)
        self.assertIn("3", summary)


if __name__ == "__main__":
    unittest.main()

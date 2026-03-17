#!/usr/bin/env python3
"""Unit tests for the worldmonitor_poll cron job script.

Test classes:
  TestFileObservation  - file_observation writes to the observations table correctly

Run:  python -m pytest tests/mcp/test_worldmonitor_poll.py -v
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

# Import directly by file path to avoid any package-name collisions.
_POLL_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "scripts",
    "agents",
    "general_montgomery",
    "worldmonitor_poll.py",
)
_spec = importlib.util.spec_from_file_location("worldmonitor_poll", _POLL_PATH)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

file_observation = _mod.file_observation


def _create_observations_db(path: str) -> None:
    """Create a minimal observations table matching Montgomery's memory schema."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS observations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT NOT NULL,
            content     TEXT NOT NULL,
            source_turn INTEGER,
            incorporated INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()


class TestFileObservation(unittest.TestCase):
    """Verify that file_observation writes correctly to the observations table."""

    def setUp(self):
        self._db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db_path = self._db_file.name
        self._db_file.close()
        _create_observations_db(self._db_path)

    def tearDown(self):
        try:
            os.unlink(self._db_path)
        except FileNotFoundError:
            pass

    def _fetch_observations(self):
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute(
            "SELECT id, created_at, content, source_turn, incorporated FROM observations"
        )
        rows = cur.fetchall()
        conn.close()
        return rows

    def test_file_observation_writes_row(self):
        """file_observation should insert exactly one row."""
        change = {
            "domain": "MILITARY",
            "summary": "2 new military flights detected",
            "timestamp": "2026-03-17T10:00:00+00:00",
        }
        file_observation(self._db_path, change)
        rows = self._fetch_observations()
        self.assertEqual(len(rows), 1)

    def test_file_observation_content_prefix(self):
        """Content must start with the [INTEL/WM/DOMAIN] prefix."""
        change = {
            "domain": "GPS",
            "summary": "3 new high-jamming hexes",
            "timestamp": "2026-03-17T10:00:00+00:00",
        }
        file_observation(self._db_path, change)
        rows = self._fetch_observations()
        content = rows[0][2]
        self.assertTrue(
            content.startswith("[INTEL/WM/GPS]"),
            f"Expected content to start with [INTEL/WM/GPS], got: {content!r}",
        )

    def test_file_observation_content_includes_summary(self):
        """Content must include the change summary text."""
        change = {
            "domain": "ALERTS",
            "summary": "Oref alert in northern district",
            "timestamp": "2026-03-17T11:00:00+00:00",
        }
        file_observation(self._db_path, change)
        rows = self._fetch_observations()
        content = rows[0][2]
        self.assertIn("Oref alert in northern district", content)

    def test_file_observation_full_content_format(self):
        """Content should be exactly '[INTEL/WM/DOMAIN] summary'."""
        change = {
            "domain": "MARITIME",
            "summary": "Vessel count change: +5 added, -2 removed",
            "timestamp": "2026-03-17T12:00:00+00:00",
        }
        file_observation(self._db_path, change)
        rows = self._fetch_observations()
        content = rows[0][2]
        self.assertEqual(
            content,
            "[INTEL/WM/MARITIME] Vessel count change: +5 added, -2 removed",
        )

    def test_file_observation_created_at_set(self):
        """created_at must be populated (non-empty)."""
        change = {
            "domain": "CONFLICT",
            "summary": "New ACLED events detected",
            "timestamp": "2026-03-17T09:30:00+00:00",
        }
        file_observation(self._db_path, change)
        rows = self._fetch_observations()
        created_at = rows[0][1]
        self.assertIsNotNone(created_at)
        self.assertNotEqual(created_at, "")

    def test_file_observation_uses_provided_timestamp(self):
        """When change includes 'timestamp', created_at should match it."""
        ts = "2026-03-17T08:00:00+00:00"
        change = {
            "domain": "THERMAL",
            "summary": "Thermal escalation in region X",
            "timestamp": ts,
        }
        file_observation(self._db_path, change)
        rows = self._fetch_observations()
        created_at = rows[0][1]
        self.assertEqual(created_at, ts)

    def test_file_observation_fallback_timestamp(self):
        """When 'timestamp' is absent, created_at should be a non-empty ISO string."""
        change = {
            "domain": "TRADE",
            "summary": "New trade restriction detected",
            # no 'timestamp' key
        }
        file_observation(self._db_path, change)
        rows = self._fetch_observations()
        created_at = rows[0][1]
        self.assertIsNotNone(created_at)
        self.assertGreater(len(created_at), 0)

    def test_file_observation_multiple_changes(self):
        """Each call to file_observation should add a separate row."""
        for i in range(3):
            file_observation(
                self._db_path,
                {
                    "domain": "MILITARY",
                    "summary": f"Change {i}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        rows = self._fetch_observations()
        self.assertEqual(len(rows), 3)

    def test_file_observation_different_domains(self):
        """Observations from different domains should all be written."""
        domains = ["MILITARY", "MARITIME", "ALERTS", "GPS", "OSINT"]
        for domain in domains:
            file_observation(
                self._db_path,
                {
                    "domain": domain,
                    "summary": f"Test change for {domain}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        rows = self._fetch_observations()
        self.assertEqual(len(rows), len(domains))
        contents = [row[2] for row in rows]
        for domain in domains:
            self.assertTrue(
                any(f"[INTEL/WM/{domain}]" in c for c in contents),
                f"No observation found for domain {domain}",
            )


if __name__ == "__main__":
    unittest.main()

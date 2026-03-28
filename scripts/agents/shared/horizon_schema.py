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

#!/usr/bin/env python3
"""Commission Sync - two-way sync between intelligence.db and the Meridian platform.

Reads commissions from intelligence.db and pushes them to the Meridian platform
via /api/commissions/[id] PUT. Also checks the platform for NEW commissions
submitted via the web form and pulls them into intelligence.db.

This means commissions can be submitted from the platform, Telegram, or CLI
and stay in sync everywhere.

Usage:
    python3 scripts/agents/shared/commission_sync.py

Environment:
    INTELLIGENCE_DB      - path to intelligence.db (auto-detected if unset)
    CHANNEL_BASE_URL     - Meridian platform URL (default: https://worldmonitor.atrophy.app)
    CHANNEL_API_KEY      - Required. API key sent as X-Channel-Key header.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_TIMEOUT = 15
_USER_AGENT = "Atrophy/1.0 (Commission Sync)"
_DEFAULT_BASE_URL = "https://worldmonitor.atrophy.app"

# Map between the DB priority values and the platform priority values.
# The DB uses: urgent, high, normal, low (from the schema DEFAULT 'normal').
# The platform uses: urgent, priority, routine.
_DB_TO_PLATFORM_PRIORITY = {
    "urgent": "urgent",
    "high": "priority",
    "URGENT": "urgent",
    "HIGH": "priority",
    "MEDIUM": "routine",
    "LOW": "routine",
    "normal": "routine",
    "low": "routine",
    "priority": "priority",
    "routine": "routine",
}

_PLATFORM_TO_DB_PRIORITY = {
    "urgent": "urgent",
    "priority": "high",
    "routine": "normal",
}


def _base_url() -> str:
    return os.environ.get("CHANNEL_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    return os.environ.get("CHANNEL_API_KEY", "")


def _db_path() -> str:
    env = os.environ.get("INTELLIGENCE_DB")
    if env:
        return env
    return str(
        Path.home()
        / ".atrophy"
        / "agents"
        / "general_montgomery"
        / "data"
        / "intelligence.db"
    )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _request(
    url: str,
    method: str = "GET",
    body: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, bytes]:
    """Make an HTTP request. Returns (status_code, response_body)."""
    hdrs = {"User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)

    api_key = _api_key()
    if api_key:
        hdrs["X-Channel-Key"] = api_key

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.getcode(), resp.read()


def _get_json(url: str) -> Any:
    """GET a URL and parse JSON response."""
    status, body = _request(url, "GET")
    if status >= 400:
        raise RuntimeError(f"HTTP {status} from {url}")
    return json.loads(body)


def _put_json(url: str, payload: dict) -> bool:
    """PUT JSON to a URL. Returns True on 2xx."""
    try:
        status, _ = _request(url, "PUT", body=payload)
        return 200 <= status < 300
    except urllib.error.HTTPError as e:
        log.warning("PUT %s failed: HTTP %d %s", url, e.code, e.reason)
        return False
    except Exception as e:
        log.warning("PUT %s failed: %s", url, e)
        return False


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    return con


def _read_local_commissions(db_path: str) -> list[dict]:
    """Read all commissions from intelligence.db."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT id, title, brief, requestor, priority, assigned_to, "
            "status, output, submitted_at, completed_at FROM commissions"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _insert_commission(db_path: str, c: dict) -> int | None:
    """Insert a new commission from the platform into intelligence.db.

    Returns the new local ID, or None if it already exists (by title match).
    """
    con = _connect(db_path)
    try:
        # Check for duplicates by title (platform commissions use web-N IDs)
        existing = con.execute(
            "SELECT id FROM commissions WHERE title = ?", (c.get("title", ""),)
        ).fetchone()
        if existing:
            return None

        priority = _PLATFORM_TO_DB_PRIORITY.get(
            c.get("priority", "routine"), "normal"
        )

        con.execute(
            """INSERT INTO commissions
               (title, brief, requestor, priority, assigned_to, status,
                output, submitted_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.get("title", "Untitled"),
                c.get("brief", c.get("title", "")),
                c.get("requestor", "web"),
                priority,
                c.get("assigned_to"),
                c.get("status", "open"),
                c.get("output"),
                c.get("submitted_at", datetime.now(timezone.utc).isoformat()),
                c.get("completed_at"),
            ),
        )
        con.commit()
        return con.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Push: local DB -> platform
# ---------------------------------------------------------------------------

def push_commissions(db_path: str) -> tuple[int, int]:
    """Push all local commissions to the Meridian platform.

    Writes each commission as commissions:<id> and rebuilds the commissions:list.

    Returns (pushed_count, error_count).
    """
    base = _base_url()
    commissions = _read_local_commissions(db_path)
    pushed = 0
    errors = 0

    for c in commissions:
        cid = c["id"]
        platform_priority = _DB_TO_PLATFORM_PRIORITY.get(
            c.get("priority", "normal"), "routine"
        )

        payload = {
            "id": cid,
            "title": c["title"],
            "brief": c.get("brief"),
            "requestor": c.get("requestor", "system"),
            "priority": platform_priority,
            "domain_tags": [],
            "assigned_to": c.get("assigned_to"),
            "status": c.get("status", "open"),
            "output": c.get("output"),
            "submitted_at": c.get("submitted_at"),
            "completed_at": c.get("completed_at"),
            "source": "intelligence_db",
        }

        url = f"{base}/api/commissions/{cid}"
        ok = _put_json(url, payload)
        if ok:
            pushed += 1
            log.info("Pushed commission %s: %s", cid, c["title"][:60])
        else:
            errors += 1
            log.warning("Failed to push commission %s", cid)

    log.info("Push complete: %d pushed, %d errors out of %d total",
             pushed, errors, len(commissions))
    return pushed, errors


# ---------------------------------------------------------------------------
# Pull: platform -> local DB
# ---------------------------------------------------------------------------

def pull_commissions(db_path: str) -> tuple[int, int]:
    """Pull new commissions from the platform into intelligence.db.

    Only imports commissions with source='platform' (submitted via web form)
    that do not already exist locally (matched by title).

    Returns (imported_count, skipped_count).
    """
    base = _base_url()
    imported = 0
    skipped = 0

    try:
        data = _get_json(f"{base}/api/commissions/list")
    except Exception as e:
        log.warning("Failed to fetch commissions list from platform: %s", e)
        return 0, 0

    platform_list = data.get("commissions", [])
    log.info("Platform has %d commissions", len(platform_list))

    for summary in platform_list:
        # Only pull commissions that originated from the platform
        if summary.get("source") != "platform":
            skipped += 1
            continue

        cid = summary.get("id", "")

        # Fetch the full commission record
        try:
            full = _get_json(f"{base}/api/commissions/{cid}")
        except Exception as e:
            log.warning("Failed to fetch commission %s: %s", cid, e)
            skipped += 1
            continue

        local_id = _insert_commission(db_path, full)
        if local_id is not None:
            imported += 1
            log.info("Imported commission %s as local ID %d: %s",
                     cid, local_id, full.get("title", "")[:60])
        else:
            skipped += 1

    log.info("Pull complete: %d imported, %d skipped", imported, skipped)
    return imported, skipped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    db_path = _db_path()
    api_key = _api_key()

    if not api_key:
        log.error("CHANNEL_API_KEY not set - cannot sync commissions")
        sys.exit(1)

    if not Path(db_path).exists():
        log.error("Intelligence DB not found at %s", db_path)
        sys.exit(1)

    log.info("Commission sync starting")
    log.info("DB: %s", db_path)
    log.info("Platform: %s", _base_url())

    # Phase 1: Push local commissions to platform
    log.info("")
    log.info("--- PUSH: local -> platform ---")
    pushed, push_errors = push_commissions(db_path)

    # Phase 2: Pull new platform commissions to local
    log.info("")
    log.info("--- PULL: platform -> local ---")
    imported, pull_skipped = pull_commissions(db_path)

    # Summary
    log.info("")
    log.info("=== SYNC COMPLETE ===")
    log.info("Pushed: %d (errors: %d)", pushed, push_errors)
    log.info("Imported: %d (skipped: %d)", imported, pull_skipped)

    # Print a stdout summary for cron output capture
    print(f"Commission sync: {pushed} pushed, {imported} imported")
    if push_errors > 0:
        print(f"  Push errors: {push_errors}")


if __name__ == "__main__":
    main()

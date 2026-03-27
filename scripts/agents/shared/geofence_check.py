#!/usr/bin/env python3
"""Geofence Check - matches geolocated events against watch zones.

Reads active watch zones from intelligence.db and checks recent data from
the WorldMonitor cache (military flights, AIS disruptions, thermal events,
GPS jamming, ACLED events) for events falling inside any zone. Logs alerts
to the zone_alerts table with cooldown enforcement.

Designed to be called from sigint_cycle.py and worldmonitor_poll.py after
they fetch fresh data. Can also run standalone for testing.

Usage:
    python3 scripts/agents/shared/geofence_check.py

Importable:
    from geofence_check import check_geofences
    alerts = check_geofences()  # returns list of alert dicts

Environment:
    INTELLIGENCE_DB - path to intelligence.db (auto-detected if unset)
    WORLDMONITOR_CACHE_DB - path to worldmonitor_cache.db (auto-detected)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _intelligence_db_path() -> str:
    """Resolve intelligence.db path."""
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


def _worldmonitor_cache_path() -> str:
    """Resolve worldmonitor_cache.db path."""
    env = os.environ.get("WORLDMONITOR_CACHE_DB")
    if env:
        return env
    return str(Path.home() / ".atrophy" / "worldmonitor_cache.db")


# ---------------------------------------------------------------------------
# Schema (ensure tables exist)
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS watch_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    center_lat REAL NOT NULL,
    center_lon REAL NOT NULL,
    radius_km REAL NOT NULL,
    assigned_agent TEXT,
    alert_threshold TEXT DEFAULT 'any',
    cooldown_minutes INTEGER DEFAULT 60,
    active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS zone_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id INTEGER NOT NULL,
    event_type TEXT,
    event_data TEXT,
    source TEXT,
    alerted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (zone_id) REFERENCES watch_zones(id)
);
CREATE INDEX IF NOT EXISTS idx_zone_alerts_zone ON zone_alerts(zone_id);
CREATE INDEX IF NOT EXISTS idx_zone_alerts_time ON zone_alerts(alerted_at);
"""


def ensure_schema(db_path: str) -> None:
    """Create watch_zones and zone_alerts tables if they do not exist."""
    con = sqlite3.connect(db_path, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
        con.executescript(_SCHEMA_SQL)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two points."""
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# ---------------------------------------------------------------------------
# Watch zone + cooldown helpers
# ---------------------------------------------------------------------------

def _load_active_zones(db_path: str) -> list[dict]:
    """Load all active watch zones from intelligence.db."""
    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=10000")
        rows = con.execute(
            "SELECT id, name, center_lat, center_lon, radius_km, "
            "assigned_agent, alert_threshold, cooldown_minutes "
            "FROM watch_zones WHERE active = 1"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _zone_on_cooldown(db_path: str, zone_id: int, cooldown_minutes: int) -> bool:
    """Check if a zone has an alert within its cooldown window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).isoformat()
    con = sqlite3.connect(db_path, timeout=10)
    try:
        con.execute("PRAGMA busy_timeout=10000")
        row = con.execute(
            "SELECT COUNT(*) FROM zone_alerts WHERE zone_id = ? AND alerted_at > ?",
            (zone_id, cutoff),
        ).fetchone()
        return row[0] > 0 if row else False
    finally:
        con.close()


def _log_alert(
    db_path: str,
    zone_id: int,
    event_type: str,
    event_data: str,
    source: str,
) -> int:
    """Insert a zone_alert row and return its ID."""
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(db_path, timeout=10)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=10000")
        cur = con.execute(
            "INSERT INTO zone_alerts (zone_id, event_type, event_data, source, alerted_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (zone_id, event_type, event_data, source, now),
        )
        con.commit()
        return cur.lastrowid or 0
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Data extraction from WorldMonitor cache
# ---------------------------------------------------------------------------

GeoEvent = dict  # {lat, lon, event_type, source, summary, raw}


def _extract_military_flights(response: str) -> list[GeoEvent]:
    """Extract geolocated events from military flights cache."""
    events: list[GeoEvent] = []
    try:
        data = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return events

    flights = data.get("flights", [])
    for f in flights:
        lat = f.get("lat")
        lon = f.get("lon")
        if lat is None or lon is None:
            continue
        callsign = f.get("callsign", "unknown")
        operator = f.get("operator", "unknown")
        aircraft_type = f.get("aircraftType", "unknown")
        events.append({
            "lat": float(lat),
            "lon": float(lon),
            "event_type": "military_flight",
            "source": "worldmonitor/military-flights",
            "summary": f"{callsign} ({operator}, {aircraft_type})",
            "raw": {
                "callsign": callsign,
                "operator": operator,
                "aircraftType": aircraft_type,
                "altitude": f.get("altitude"),
                "heading": f.get("heading"),
                "speed": f.get("speed"),
            },
        })
    return events


def _extract_ais_disruptions(response: str) -> list[GeoEvent]:
    """Extract geolocated events from AIS snapshot cache."""
    events: list[GeoEvent] = []
    try:
        data = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return events

    # Disruptions have lat/lon directly
    for d in data.get("disruptions", []):
        lat = d.get("lat")
        lon = d.get("lon")
        if lat is None or lon is None:
            continue
        events.append({
            "lat": float(lat),
            "lon": float(lon),
            "event_type": "ais_disruption",
            "source": "worldmonitor/ais-snapshot",
            "summary": d.get("description", d.get("name", "AIS disruption")),
            "raw": {
                "id": d.get("id"),
                "name": d.get("name"),
                "type": d.get("type"),
                "severity": d.get("severity"),
                "vesselCount": d.get("vesselCount"),
            },
        })

    # Density zones (only high-traffic, could flag anomalies)
    for zone in data.get("density", []):
        lat = zone.get("lat")
        lon = zone.get("lon")
        if lat is None or lon is None:
            continue
        intensity = zone.get("intensity", 0)
        delta = zone.get("deltaPct", 0)
        # Only flag significant density changes (>50% shift)
        if abs(delta) < 50:
            continue
        events.append({
            "lat": float(lat),
            "lon": float(lon),
            "event_type": "ais_density_anomaly",
            "source": "worldmonitor/ais-snapshot",
            "summary": f"Density anomaly: {delta:+d}% change, intensity {intensity:.2f}",
            "raw": {
                "id": zone.get("id"),
                "deltaPct": delta,
                "intensity": intensity,
                "shipsPerDay": zone.get("shipsPerDay"),
            },
        })

    return events


def _extract_thermal_events(response: str) -> list[GeoEvent]:
    """Extract geolocated events from thermal escalation cache."""
    events: list[GeoEvent] = []
    try:
        data = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return events

    for cluster in data.get("clusters", []):
        centroid = cluster.get("centroid", {})
        lat = centroid.get("latitude")
        lon = centroid.get("longitude")
        if lat is None or lon is None:
            continue
        country = cluster.get("countryName", "unknown")
        status = cluster.get("status", "")
        relevance = cluster.get("strategicRelevance", "")
        events.append({
            "lat": float(lat),
            "lon": float(lon),
            "event_type": "thermal_event",
            "source": "worldmonitor/thermal-escalations",
            "summary": f"Thermal cluster in {country} - {status}, relevance: {relevance}",
            "raw": {
                "id": cluster.get("id"),
                "countryCode": cluster.get("countryCode"),
                "countryName": country,
                "status": status,
                "context": cluster.get("context"),
                "confidence": cluster.get("confidence"),
                "strategicRelevance": relevance,
                "zScore": cluster.get("zScore"),
                "observationCount": cluster.get("observationCount"),
                "maxFrp": cluster.get("maxFrp"),
                "totalFrp": cluster.get("totalFrp"),
                "narrativeFlags": cluster.get("narrativeFlags", []),
            },
        })
    return events


def _extract_acled_events(response: str) -> list[GeoEvent]:
    """Extract geolocated events from ACLED conflict data."""
    events: list[GeoEvent] = []
    try:
        data = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return events

    for ev in data.get("events", []):
        lat = ev.get("latitude") or ev.get("lat")
        lon = ev.get("longitude") or ev.get("lon")
        if lat is None or lon is None:
            continue
        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            continue
        event_type_label = ev.get("event_type", ev.get("type", "conflict_event"))
        location = ev.get("location", ev.get("admin1", "unknown"))
        events.append({
            "lat": lat,
            "lon": lon,
            "event_type": "acled_event",
            "source": "worldmonitor/acled-events",
            "summary": f"{event_type_label} at {location}",
            "raw": {k: v for k, v in ev.items() if k not in ("latitude", "longitude", "lat", "lon")},
        })
    return events


def _extract_gpsjam_events(response: str) -> list[GeoEvent]:
    """Extract geolocated GPS jamming events."""
    events: list[GeoEvent] = []
    try:
        data = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return events

    # Only flag high-level GPS jamming hexes
    for h in data.get("hexes", []):
        if h.get("level") != "high":
            continue
        lat = h.get("lat")
        lon = h.get("lon")
        if lat is None or lon is None:
            continue
        events.append({
            "lat": float(lat),
            "lon": float(lon),
            "event_type": "gps_jamming",
            "source": "worldmonitor/gpsjam",
            "summary": f"GPS jamming (high), {h.get('sampleCount', 0)} samples, {h.get('aircraftCount', 0)} aircraft",
            "raw": {
                "h3": h.get("h3"),
                "level": h.get("level"),
                "sampleCount": h.get("sampleCount"),
                "aircraftCount": h.get("aircraftCount"),
                "region": h.get("region"),
            },
        })
    return events


def _extract_oref_alerts(response: str) -> list[GeoEvent]:
    """Extract geolocated OREF (Israel) alerts."""
    events: list[GeoEvent] = []
    try:
        data = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        return events

    alerts = data if isinstance(data, list) else data.get("alerts", [])
    for a in alerts:
        lat = a.get("lat") or a.get("latitude")
        lon = a.get("lon") or a.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            continue
        events.append({
            "lat": lat,
            "lon": lon,
            "event_type": "oref_alert",
            "source": "worldmonitor/oref-alerts",
            "summary": a.get("title", a.get("desc", "OREF alert")),
            "raw": {k: v for k, v in a.items() if k not in ("lat", "lon", "latitude", "longitude")},
        })
    return events


# Map cache_key prefixes to extraction functions
_EXTRACTORS: dict[str, Any] = {
    "api/military-flights": _extract_military_flights,
    "api/ais-snapshot": _extract_ais_disruptions,
    "api/thermal/v1/list-thermal-escalations": _extract_thermal_events,
    "api/conflict/v1/list-acled-events": _extract_acled_events,
    "api/gpsjam": _extract_gpsjam_events,
    "api/oref-alerts": _extract_oref_alerts,
}


def _load_cached_events(cache_db_path: str) -> list[GeoEvent]:
    """Load and parse all geolocated events from the WorldMonitor cache."""
    if not os.path.exists(cache_db_path):
        print(f"  WorldMonitor cache not found at {cache_db_path}", file=sys.stderr)
        return []

    con = sqlite3.connect(cache_db_path, timeout=10)
    try:
        con.execute("PRAGMA busy_timeout=10000")
        all_events: list[GeoEvent] = []

        for endpoint_prefix, extractor in _EXTRACTORS.items():
            # Match cache keys that start with the endpoint prefix
            rows = con.execute(
                "SELECT cache_key, response FROM cache WHERE cache_key LIKE ? ORDER BY fetched_at DESC LIMIT 1",
                (endpoint_prefix + "%",),
            ).fetchall()
            for cache_key, response in rows:
                try:
                    events = extractor(response)
                    all_events.extend(events)
                except Exception as e:
                    print(f"  Warning: failed to extract from {cache_key}: {e}", file=sys.stderr)

        return all_events
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Core geofence check
# ---------------------------------------------------------------------------

def check_geofences(
    intelligence_db: str | None = None,
    cache_db: str | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Run geofence check against all active watch zones.

    Args:
        intelligence_db: Path to intelligence.db (auto-detected if None)
        cache_db: Path to worldmonitor_cache.db (auto-detected if None)
        dry_run: If True, don't write alerts to DB, just return matches

    Returns:
        List of alert dicts with keys: zone_name, zone_id, event_type,
        event_summary, source, lat, lon, distance_km, alert_id, cooled_down
    """
    intel_db = intelligence_db or _intelligence_db_path()
    wm_cache = cache_db or _worldmonitor_cache_path()

    # Ensure schema exists
    try:
        ensure_schema(intel_db)
    except sqlite3.OperationalError as e:
        print(f"Warning: could not ensure schema: {e}", file=sys.stderr)

    # Load watch zones
    zones = _load_active_zones(intel_db)
    if not zones:
        print("No active watch zones found.")
        return []

    # Load cached events
    events = _load_cached_events(wm_cache)

    # Stats
    total_events = len(events)
    zone_hits = 0
    alerts_fired = 0
    alerts_cooled = 0
    results: list[dict] = []

    # Check each event against each zone
    for event in events:
        ev_lat = event["lat"]
        ev_lon = event["lon"]

        for zone in zones:
            dist = haversine_km(
                zone["center_lat"], zone["center_lon"],
                ev_lat, ev_lon,
            )
            if dist > zone["radius_km"]:
                continue

            zone_hits += 1

            # Prepare alert data
            event_data_json = json.dumps(event.get("raw", {}), default=str)
            alert_info = {
                "zone_name": zone["name"],
                "zone_id": zone["id"],
                "assigned_agent": zone.get("assigned_agent"),
                "event_type": event["event_type"],
                "event_summary": event["summary"],
                "source": event["source"],
                "lat": ev_lat,
                "lon": ev_lon,
                "distance_km": round(dist, 1),
                "alert_id": None,
                "cooled_down": False,
            }

            # Check cooldown
            if _zone_on_cooldown(intel_db, zone["id"], zone["cooldown_minutes"]):
                alerts_cooled += 1
                alert_info["cooled_down"] = True
                results.append(alert_info)
                continue

            # Log alert
            if not dry_run:
                alert_id = _log_alert(
                    intel_db,
                    zone["id"],
                    event["event_type"],
                    event_data_json,
                    event["source"],
                )
                alert_info["alert_id"] = alert_id

            alerts_fired += 1
            results.append(alert_info)

            # Once an alert fires for a zone, it enters cooldown -
            # skip further events for this zone in this run
            break

    # Print summary
    print(f"\nGeofence Check Summary")
    print(f"  Watch zones:    {len(zones)}")
    print(f"  Events checked: {total_events}")
    print(f"  Zone hits:      {zone_hits}")
    print(f"  Alerts fired:   {alerts_fired}")
    print(f"  Cooled down:    {alerts_cooled}")

    if alerts_fired > 0:
        print(f"\n  Fired alerts:")
        for a in results:
            if not a["cooled_down"] and a.get("alert_id"):
                print(
                    f"    [{a['zone_name']}] {a['event_type']}: "
                    f"{a['event_summary']} "
                    f"({a['lat']:.2f}, {a['lon']:.2f}) "
                    f"{a['distance_km']}km from center "
                    f"[{a['source']}]"
                )

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Running geofence check...")
    print(f"  Intelligence DB: {_intelligence_db_path()}")
    print(f"  WorldMonitor cache: {_worldmonitor_cache_path()}")

    alerts = check_geofences()

    if not alerts:
        print("\nNo zone hits detected.")
    else:
        fired = [a for a in alerts if not a["cooled_down"]]
        cooled = [a for a in alerts if a["cooled_down"]]
        if fired:
            print(f"\n{len(fired)} new alert(s) logged to zone_alerts table.")
        if cooled:
            print(f"{len(cooled)} hit(s) suppressed by cooldown.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Meridian Ontology - WorldMonitor Auto-Ingestion

Routes WorldMonitor API responses to typed ingestors that upsert objects,
properties, and links into the intelligence ontology.

Usage (standalone):
    python3 ontology_ingest.py [--seed] [--cache-db PATH] [--intel-db PATH]

Usage (as import):
    from ontology_ingest import ingest_worldmonitor_response
    result = ingest_worldmonitor_response(
        "api/military-flights", response_data,
        source="worldmonitor:military-flights"
    )
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Ontology import - graceful fallback if ontology.py is not available
# ---------------------------------------------------------------------------
_SHARED_DIR = os.path.dirname(os.path.abspath(__file__))
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)

try:
    from ontology import Ontology

    _HAS_ONTOLOGY = True
except ImportError:
    _HAS_ONTOLOGY = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_ATROPHY_DIR = Path.home() / ".atrophy"
_DEFAULT_INTEL_DB = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"
_DEFAULT_CACHE_DB = _ATROPHY_DIR / "worldmonitor_cache.db"
_LOG_DIR = _ATROPHY_DIR / "logs" / "general_montgomery"

logger = logging.getLogger("ontology_ingest")


# ---------------------------------------------------------------------------
# Operator/country mapping for military flights
# ---------------------------------------------------------------------------
_OPERATOR_COUNTRY = {
    "usaf": "United States",
    "usn": "United States",
    "usmc": "United States",
    "uscg": "United States",
    "raf": "United Kingdom",
    "rn": "United Kingdom",
    "rcaf": "Canada",
    "raaf": "Australia",
    "rnzaf": "New Zealand",
    "iaf": "India",
    "jasdf": "Japan",
    "jmsdf": "Japan",
    "rokaf": "South Korea",
    "plaaf": "China",
    "plan": "China",
    "vks": "Russia",
    "vmf": "Russia",
    "idf": "Israel",
    "iiaf": "Iran",
    "faf": "France",
    "gaf": "Germany",
    "itaf": "Italy",
    "tuaf": "Turkey",
    "nato": "NATO",
}

# Country code to name for reverse lookups
_CC_TO_COUNTRY = {
    "US": "United States", "GB": "United Kingdom", "CA": "Canada",
    "AU": "Australia", "NZ": "New Zealand", "IN": "India",
    "JP": "Japan", "KR": "South Korea", "CN": "China",
    "RU": "Russia", "IL": "Israel", "IR": "Iran",
    "FR": "France", "DE": "Germany", "IT": "Italy",
    "TR": "Turkey", "UA": "Ukraine", "SA": "Saudi Arabia",
    "AE": "United Arab Emirates", "QA": "Qatar", "PK": "Pakistan",
    "BR": "Brazil", "MX": "Mexico", "SE": "Sweden",
    "NO": "Norway", "NL": "Netherlands", "BE": "Belgium",
    "PL": "Poland", "ES": "Spain", "PT": "Portugal",
    "GR": "Greece", "KP": "North Korea", "TW": "Taiwan",
    "PH": "Philippines", "TH": "Thailand", "VN": "Vietnam",
    "ID": "Indonesia", "MY": "Malaysia", "SG": "Singapore",
    "EG": "Egypt", "SD": "Sudan", "SS": "South Sudan",
    "ET": "Ethiopia", "KE": "Kenya", "NG": "Nigeria",
    "ZA": "South Africa", "DZ": "Algeria", "MA": "Morocco",
    "LY": "Libya", "YE": "Yemen", "IQ": "Iraq", "SY": "Syria",
    "LB": "Lebanon", "JO": "Jordan", "AF": "Afghanistan",
    "MM": "Myanmar", "CO": "Colombia", "VE": "Venezuela",
    "AR": "Argentina", "CL": "Chile", "PE": "Peru",
    "XM": "Euro Area",
}

# GPS jamming region grouping - regions of interest get separate events
_JAMMING_REGIONS = {
    "ukraine-russia": "Ukraine-Russia Conflict Zone",
    "sudan-sahel": "Sudan-Sahel Region",
    "east-asia": "East Asia",
    "middle-east": "Middle East",
    "iran": "Iran",
}


# ===================================================================
# Counters helper
# ===================================================================

class IngestCounters:
    """Track objects/links/events created or updated during an ingest pass."""

    def __init__(self):
        self.objects_created = 0
        self.objects_updated = 0
        self.links_created = 0
        self.events_created = 0
        self.properties_set = 0
        self.skipped = 0
        self.errors = 0

    def as_dict(self) -> dict:
        return {
            "objects_created": self.objects_created,
            "objects_updated": self.objects_updated,
            "links_created": self.links_created,
            "events_created": self.events_created,
            "properties_set": self.properties_set,
            "skipped": self.skipped,
            "errors": self.errors,
        }

    def merge(self, other: "IngestCounters"):
        self.objects_created += other.objects_created
        self.objects_updated += other.objects_updated
        self.links_created += other.links_created
        self.events_created += other.events_created
        self.properties_set += other.properties_set
        self.skipped += other.skipped
        self.errors += other.errors


# ===================================================================
# OntologyWriter - thin wrapper that uses Ontology class if available,
# otherwise falls back to direct SQL
# ===================================================================

class OntologyWriter:
    """Unified interface for ontology writes. Uses Ontology class when
    available, falls back to raw SQL otherwise."""

    def __init__(self, db_path: str):
        self.db_path = os.path.expanduser(db_path)
        self._ont = None
        self._conn = None

        if _HAS_ONTOLOGY:
            self._ont = Ontology(self.db_path)
        else:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._ensure_tables()

    def close(self):
        if self._ont:
            self._ont.close()
        elif self._conn:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # -- Core operations --

    def upsert_object(
        self,
        name: str,
        type: str,
        subtype: str = None,
        aliases: list = None,
        lat: float = None,
        lon: float = None,
        country_code: str = None,
        description: str = None,
        status: str = "active",
        source: str = None,
        agent: str = "ontology_ingest",
    ) -> tuple[int, bool]:
        """Upsert an object. Returns (object_id, was_created)."""
        if self._ont:
            # Check if it exists first to track created vs updated
            existing = self._ont.find_object(name, type)
            obj_id = self._ont.upsert_object(
                name=name, type=type, subtype=subtype, aliases=aliases,
                lat=lat, lon=lon, country_code=country_code,
                description=description, status=status,
                source=source, agent=agent,
            )
            return obj_id, existing is None
        else:
            return self._fallback_upsert_object(
                name, type, subtype, aliases, lat, lon,
                country_code, description, status, source, agent,
            )

    def set_property(
        self,
        object_id: int,
        key: str,
        value: str,
        value_type: str = "string",
        confidence: float = 1.0,
        source: str = None,
    ) -> None:
        if self._ont:
            self._ont.set_property(
                object_id, key, value,
                value_type=value_type, confidence=confidence, source=source,
            )
        else:
            self._fallback_set_property(object_id, key, value, value_type, confidence, source)

    def add_link(
        self,
        from_id: int,
        to_id: int,
        type: str,
        subtype: str = None,
        confidence: float = 0.8,
        source: str = None,
        description: str = None,
    ) -> int:
        if self._ont:
            return self._ont.add_link(
                from_id, to_id, type,
                subtype=subtype, confidence=confidence,
                source=source, description=description,
            )
        else:
            return self._fallback_add_link(from_id, to_id, type, subtype, confidence, source, description)

    def find_object(self, name: str, type: str = None) -> Optional[int]:
        if self._ont:
            return self._ont.find_object(name, type)
        else:
            return self._fallback_find_object(name, type)

    # -- Fallback implementations --

    def _ensure_tables(self):
        """Create ontology tables if they don't exist (fallback mode only)."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                subtype TEXT,
                name TEXT NOT NULL,
                aliases TEXT,
                status TEXT DEFAULT 'active',
                description TEXT,
                lat REAL,
                lon REAL,
                country_code TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                value_type TEXT DEFAULT 'string',
                confidence REAL DEFAULT 1.0,
                source TEXT,
                valid_from TIMESTAMP,
                valid_to TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (object_id) REFERENCES objects(id)
            );
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id INTEGER NOT NULL,
                to_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                subtype TEXT,
                description TEXT,
                confidence REAL DEFAULT 0.8,
                source TEXT,
                valid_from TIMESTAMP,
                valid_to TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (from_id) REFERENCES objects(id),
                FOREIGN KEY (to_id) REFERENCES objects(id)
            );
            CREATE TABLE IF NOT EXISTS changelog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_id INTEGER,
                table_name TEXT NOT NULL,
                record_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                field TEXT,
                old_value TEXT,
                new_value TEXT,
                source TEXT,
                agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_objects_type ON objects(type);
            CREATE INDEX IF NOT EXISTS idx_objects_name ON objects(name);
            CREATE INDEX IF NOT EXISTS idx_properties_object ON properties(object_id);
            CREATE INDEX IF NOT EXISTS idx_links_from ON links(from_id);
            CREATE INDEX IF NOT EXISTS idx_links_to ON links(to_id);
        """)

    def _fallback_find_object(self, name: str, type: str = None) -> Optional[int]:
        if type:
            row = self._conn.execute(
                "SELECT id FROM objects WHERE LOWER(name) = LOWER(?) AND LOWER(type) = LOWER(?)",
                (name, type),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT id FROM objects WHERE LOWER(name) = LOWER(?)",
                (name,),
            ).fetchone()
        if row:
            return row["id"]

        # Alias search
        query = "SELECT id, aliases FROM objects WHERE aliases IS NOT NULL"
        params = []
        if type:
            query += " AND LOWER(type) = LOWER(?)"
            params.append(type)
        for row in self._conn.execute(query, params).fetchall():
            try:
                aliases = json.loads(row["aliases"])
                if isinstance(aliases, list):
                    for a in aliases:
                        if isinstance(a, str) and a.lower() == name.lower():
                            return row["id"]
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _fallback_upsert_object(
        self, name, type, subtype, aliases, lat, lon,
        country_code, description, status, source, agent,
    ) -> tuple[int, bool]:
        existing_id = self._fallback_find_object(name, type)
        if existing_id is not None:
            # Update last_seen and any new fields
            updates = []
            params = []
            if subtype:
                updates.append("subtype = COALESCE(?, subtype)")
                params.append(subtype)
            if lat is not None:
                updates.append("lat = ?")
                params.append(lat)
            if lon is not None:
                updates.append("lon = ?")
                params.append(lon)
            if country_code:
                updates.append("country_code = COALESCE(?, country_code)")
                params.append(country_code)
            if description:
                updates.append("description = COALESCE(?, description)")
                params.append(description)
            updates.append("last_seen = CURRENT_TIMESTAMP")
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(existing_id)
            self._conn.execute(
                f"UPDATE objects SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            # Merge aliases
            if aliases:
                row = self._conn.execute("SELECT aliases FROM objects WHERE id = ?", (existing_id,)).fetchone()
                old = []
                if row and row["aliases"]:
                    try:
                        old = json.loads(row["aliases"])
                    except (json.JSONDecodeError, TypeError):
                        old = []
                merged = list(set(old + aliases))
                self._conn.execute(
                    "UPDATE objects SET aliases = ? WHERE id = ?",
                    (json.dumps(merged), existing_id),
                )
            self._conn.commit()
            return existing_id, False

        aliases_json = json.dumps(aliases) if aliases else None
        cur = self._conn.execute(
            """INSERT INTO objects (type, subtype, name, aliases, status, description,
                                    lat, lon, country_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (type, subtype, name, aliases_json, status or "active", description, lat, lon, country_code),
        )
        self._conn.commit()
        return cur.lastrowid, True

    def _fallback_set_property(self, object_id, key, value, value_type, confidence, source):
        existing = self._conn.execute(
            "SELECT id, value FROM properties WHERE object_id = ? AND key = ? AND valid_to IS NULL",
            (object_id, key),
        ).fetchone()
        if existing:
            if existing["value"] == value:
                return
            self._conn.execute(
                "UPDATE properties SET valid_to = CURRENT_TIMESTAMP WHERE id = ?",
                (existing["id"],),
            )
        self._conn.execute(
            """INSERT INTO properties (object_id, key, value, value_type, confidence, source)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (object_id, key, value, value_type, confidence, source),
        )
        self._conn.commit()

    def _fallback_add_link(self, from_id, to_id, type, subtype, confidence, source, description):
        existing = self._conn.execute(
            """SELECT id FROM links
               WHERE from_id = ? AND to_id = ? AND type = ?
                 AND (source = ? OR (source IS NULL AND ? IS NULL))""",
            (from_id, to_id, type, source, source),
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE links SET confidence = ?, description = COALESCE(?, description) WHERE id = ?",
                (confidence, description, existing["id"]),
            )
            self._conn.commit()
            return existing["id"]

        cur = self._conn.execute(
            """INSERT INTO links (from_id, to_id, type, subtype, description, confidence, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (from_id, to_id, type, subtype, description, confidence, source),
        )
        self._conn.commit()
        return cur.lastrowid


# ===================================================================
# Global writer instance (set by init or seed_from_cache)
# ===================================================================

_writer: Optional[OntologyWriter] = None


def _get_writer(db_path: str = None) -> OntologyWriter:
    global _writer
    if _writer is None:
        _writer = OntologyWriter(db_path or str(_DEFAULT_INTEL_DB))
    return _writer


def _close_writer():
    global _writer
    if _writer is not None:
        _writer.close()
        _writer = None


# ===================================================================
# Helper functions
# ===================================================================

def _safe_float(val, default=None) -> Optional[float]:
    """Safely convert a value to float."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def _safe_str(val, default="") -> str:
    """Safely convert a value to string."""
    if val is None:
        return default
    return str(val)


def _resolve_operator_country(operator: str, operator_country: str = None) -> Optional[str]:
    """Resolve an operator string to a country name."""
    if operator:
        op_lower = operator.lower().strip()
        country = _OPERATOR_COUNTRY.get(op_lower)
        if country:
            return country
    if operator_country:
        country = _CC_TO_COUNTRY.get(operator_country.upper())
        if country:
            return country
        # If it looks like a country name already, return it
        if len(operator_country) > 3:
            return operator_country
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ===================================================================
# Ingestors
# ===================================================================

def ingest_military_flights(data: dict, source: str = None) -> IngestCounters:
    """Ingest military flight tracking data.

    Expected shape: {"flights": [{"hexCode": "...", "operator": "...", ...}]}
    """
    source = source or "worldmonitor:military-flights"
    counters = IngestCounters()
    w = _get_writer()

    flights = data.get("flights", [])
    if not flights:
        return counters

    for flight in flights:
        try:
            hex_code = flight.get("hexCode") or flight.get("hex")
            if not hex_code:
                counters.skipped += 1
                continue

            callsign = flight.get("callsign", "")
            registration = (flight.get("sourceMeta") or {}).get("registration", "")
            aircraft_type = flight.get("aircraftType", "unknown")
            operator = flight.get("operator", "")
            operator_country = flight.get("operatorCountry", "")
            lat = _safe_float(flight.get("lat"))
            lon = _safe_float(flight.get("lon"))
            altitude = _safe_float(flight.get("altitude"))

            # Use hex code as the canonical name for dedup
            name = hex_code.upper()
            aliases = []
            if callsign and callsign != name:
                aliases.append(callsign)
            if registration and registration != name:
                aliases.append(registration)

            # Determine country code from operator
            country_name = _resolve_operator_country(operator, operator_country)

            aircraft_model = (flight.get("sourceMeta") or {}).get("aircraftModel", "")
            type_label = (flight.get("sourceMeta") or {}).get("aircraftTypeLabel", "")
            desc_parts = []
            if aircraft_type and aircraft_type != "unknown":
                desc_parts.append(aircraft_type)
            elif aircraft_model:
                desc_parts.append(aircraft_model)
            elif type_label:
                desc_parts.append(type_label)
            if operator:
                desc_parts.append(f"({operator.upper()})")
            description = " ".join(desc_parts) if desc_parts else None

            # Resolve country code
            cc = None
            if operator_country:
                cc = operator_country.upper() if len(operator_country) <= 3 else None
            if not cc and country_name:
                # Reverse lookup
                for code, name_val in _CC_TO_COUNTRY.items():
                    if name_val == country_name:
                        cc = code
                        break

            obj_id, created = w.upsert_object(
                name=name,
                type="platform",
                subtype="aircraft",
                aliases=aliases if aliases else None,
                lat=lat,
                lon=lon,
                country_code=cc,
                description=description,
                source=source,
            )
            if created:
                counters.objects_created += 1
            else:
                counters.objects_updated += 1

            # Set properties
            if aircraft_type and aircraft_type != "unknown":
                w.set_property(obj_id, "aircraft_type", aircraft_type, source=source)
                counters.properties_set += 1
            if operator:
                w.set_property(obj_id, "operator", operator.upper(), source=source)
                counters.properties_set += 1
            if lat is not None:
                w.set_property(obj_id, "last_position_lat", str(lat), value_type="float", source=source)
                counters.properties_set += 1
            if lon is not None:
                w.set_property(obj_id, "last_position_lon", str(lon), value_type="float", source=source)
                counters.properties_set += 1
            if altitude is not None:
                w.set_property(obj_id, "altitude", str(int(altitude)), value_type="integer", source=source)
                counters.properties_set += 1
            if callsign:
                w.set_property(obj_id, "callsign", callsign, source=source)
                counters.properties_set += 1

            note = flight.get("note", "")
            if note:
                w.set_property(obj_id, "note", note, source=source)
                counters.properties_set += 1

            confidence_level = flight.get("confidence", "medium")
            w.set_property(obj_id, "confidence", confidence_level, source=source)
            counters.properties_set += 1

            # Link aircraft to operator country/org
            if country_name:
                country_id = w.find_object(country_name, "country")
                if country_id is None:
                    # Also check organization (e.g. NATO)
                    country_id = w.find_object(country_name, "organization")
                if country_id is not None:
                    w.add_link(
                        obj_id, country_id, "operated_by",
                        confidence=0.7 if confidence_level == "low" else 0.85,
                        source=source,
                        description=f"Operator: {operator.upper()}" if operator else None,
                    )
                    counters.links_created += 1

        except Exception as exc:
            logger.warning("Failed to ingest flight %s: %s", flight.get("hexCode", "?"), exc)
            counters.errors += 1

    return counters


def ingest_acled_events(data: dict, source: str = None) -> IngestCounters:
    """Ingest ACLED conflict event data.

    Expected shape: {"events": [{"id": "...", "event_type": "...", ...}]}
    """
    source = source or "worldmonitor:acled"
    counters = IngestCounters()
    w = _get_writer()

    events = data.get("events", [])
    if not events:
        return counters

    for event in events:
        try:
            event_id = event.get("id") or event.get("data_id")
            if not event_id:
                counters.skipped += 1
                continue

            event_type = event.get("event_type", "unknown")
            sub_event_type = event.get("sub_event_type", "")
            actor1 = event.get("actor1", "")
            actor2 = event.get("actor2", "")
            country_name = event.get("country", "")
            lat = _safe_float(event.get("latitude"))
            lon = _safe_float(event.get("longitude"))
            fatalities = event.get("fatalities")
            event_date = event.get("event_date", "")
            location_name = event.get("location", "")
            notes = event.get("notes", "")

            # Build event name
            name = f"ACLED-{event_id}"
            description_parts = []
            if event_type:
                description_parts.append(event_type)
            if sub_event_type:
                description_parts.append(f"({sub_event_type})")
            if location_name:
                description_parts.append(f"at {location_name}")
            if country_name:
                description_parts.append(f"in {country_name}")
            description = " ".join(description_parts) if description_parts else None

            # Map event_type to subtype
            subtype_map = {
                "Battles": "battle",
                "Violence against civilians": "violence_against_civilians",
                "Explosions/Remote violence": "remote_violence",
                "Riots": "riot",
                "Protests": "protest",
                "Strategic developments": "strategic_development",
            }
            subtype = subtype_map.get(event_type, event_type.lower().replace(" ", "_") if event_type else "unknown")

            obj_id, created = w.upsert_object(
                name=name,
                type="event",
                subtype=subtype,
                lat=lat,
                lon=lon,
                description=description,
                source=source,
            )
            if created:
                counters.objects_created += 1
                counters.events_created += 1
            else:
                counters.objects_updated += 1

            # Properties
            if event_date:
                w.set_property(obj_id, "event_date", event_date, value_type="date", source=source)
                counters.properties_set += 1
            if fatalities is not None:
                w.set_property(obj_id, "fatalities", str(fatalities), value_type="integer", source=source)
                counters.properties_set += 1
            if notes:
                w.set_property(obj_id, "notes", notes[:500], source=source)
                counters.properties_set += 1
            w.set_property(obj_id, "acled_id", str(event_id), source=source)
            counters.properties_set += 1

            # Upsert actors
            for actor_name, role in [(actor1, "actor1"), (actor2, "actor2")]:
                if not actor_name or not actor_name.strip():
                    continue

                # Determine actor type - factions/forces vs civilian groups
                actor_type = "faction"
                if any(kw in actor_name.lower() for kw in ["civilian", "protester", "unidentified"]):
                    actor_type = "group"

                actor_id, actor_created = w.upsert_object(
                    name=actor_name.strip(),
                    type=actor_type,
                    source=source,
                )
                if actor_created:
                    counters.objects_created += 1

                # Link actor to event
                w.add_link(
                    actor_id, obj_id, "participated_in",
                    subtype=role,
                    confidence=0.9,
                    source=source,
                    description=f"{role}: {actor_name}",
                )
                counters.links_created += 1

            # Upsert location/country and link
            if country_name:
                country_id = w.find_object(country_name, "country")
                if country_id is None:
                    country_id, c_created = w.upsert_object(
                        name=country_name,
                        type="country",
                        source=source,
                    )
                    if c_created:
                        counters.objects_created += 1

                w.add_link(
                    obj_id, country_id, "located_in",
                    confidence=0.95,
                    source=source,
                )
                counters.links_created += 1

            if location_name and location_name != country_name:
                loc_id, loc_created = w.upsert_object(
                    name=location_name,
                    type="location",
                    lat=lat,
                    lon=lon,
                    country_code=None,
                    source=source,
                )
                if loc_created:
                    counters.objects_created += 1

                w.add_link(
                    obj_id, loc_id, "located_at",
                    confidence=0.95,
                    source=source,
                )
                counters.links_created += 1

        except Exception as exc:
            logger.warning("Failed to ingest ACLED event %s: %s", event.get("id", "?"), exc)
            counters.errors += 1

    return counters


def ingest_ais_data(data: dict, source: str = None) -> IngestCounters:
    """Ingest AIS maritime data - disruptions and vessel counts.

    Expected shape varies:
      {"disruptions": [...], "density": [...], "status": {...}}
    """
    source = source or "worldmonitor:ais"
    counters = IngestCounters()
    w = _get_writer()

    # Ingest disruptions (chokepoint congestion events)
    disruptions = data.get("disruptions", [])
    for disruption in disruptions:
        try:
            d_id = disruption.get("id", "")
            name = disruption.get("name") or disruption.get("region") or d_id
            if not name:
                counters.skipped += 1
                continue

            d_type = disruption.get("type", "unknown")
            lat = _safe_float(disruption.get("lat"))
            lon = _safe_float(disruption.get("lon"))
            severity = disruption.get("severity", "low")
            change_pct = _safe_float(disruption.get("changePct"))
            vessel_count = disruption.get("vesselCount")
            desc = disruption.get("description", "")

            # Upsert as a location (chokepoint) rather than event - chokepoints persist
            loc_id, created = w.upsert_object(
                name=name,
                type="location",
                subtype="chokepoint",
                lat=lat,
                lon=lon,
                description=desc,
                source=source,
            )
            if created:
                counters.objects_created += 1
            else:
                counters.objects_updated += 1

            # Set current status properties
            w.set_property(loc_id, "severity", severity, source=source)
            counters.properties_set += 1
            if vessel_count is not None:
                w.set_property(loc_id, "vessel_count", str(vessel_count), value_type="integer", source=source)
                counters.properties_set += 1
            if change_pct is not None:
                w.set_property(loc_id, "traffic_change_pct", str(change_pct), value_type="float", source=source)
                counters.properties_set += 1
            w.set_property(loc_id, "disruption_type", d_type, source=source)
            counters.properties_set += 1

        except Exception as exc:
            logger.warning("Failed to ingest AIS disruption %s: %s", disruption.get("id", "?"), exc)
            counters.errors += 1

    # Ingest vessel data if present (e.g. from specific vessel queries)
    vessels = data.get("vessels", [])
    for vessel in vessels:
        try:
            mmsi = vessel.get("mmsi")
            name = vessel.get("name") or vessel.get("shipname") or f"MMSI-{mmsi}"
            if not name and not mmsi:
                counters.skipped += 1
                continue

            lat = _safe_float(vessel.get("lat") or vessel.get("latitude"))
            lon = _safe_float(vessel.get("lon") or vessel.get("longitude"))
            flag = vessel.get("flag") or vessel.get("flag_state", "")
            vessel_type = vessel.get("vessel_type") or vessel.get("shiptype", "")

            obj_id, created = w.upsert_object(
                name=name,
                type="platform",
                subtype="vessel",
                lat=lat,
                lon=lon,
                description=f"{vessel_type} ({flag})" if vessel_type and flag else None,
                source=source,
            )
            if created:
                counters.objects_created += 1
            else:
                counters.objects_updated += 1

            if mmsi:
                w.set_property(obj_id, "mmsi", str(mmsi), source=source)
                counters.properties_set += 1
            if flag:
                w.set_property(obj_id, "flag_state", flag, source=source)
                counters.properties_set += 1
            if vessel_type:
                w.set_property(obj_id, "vessel_type", vessel_type, source=source)
                counters.properties_set += 1
            if lat is not None:
                w.set_property(obj_id, "last_position_lat", str(lat), value_type="float", source=source)
                counters.properties_set += 1
            if lon is not None:
                w.set_property(obj_id, "last_position_lon", str(lon), value_type="float", source=source)
                counters.properties_set += 1

        except Exception as exc:
            logger.warning("Failed to ingest vessel %s: %s", vessel.get("name", "?"), exc)
            counters.errors += 1

    return counters


def ingest_gps_jamming(data: dict, source: str = None) -> IngestCounters:
    """Ingest GPS jamming data, grouping high-level hexes by region.

    Expected shape: {"hexes": [{"h3": "...", "level": "high", "lat": ..., "lon": ..., "region": "..."}]}
    """
    source = source or "worldmonitor:gpsjam"
    counters = IngestCounters()
    w = _get_writer()

    hexes = data.get("hexes", [])
    if not hexes:
        return counters

    # Filter to high-level only
    high_hexes = [h for h in hexes if h.get("level") == "high"]
    if not high_hexes:
        return counters

    # Group by region to avoid thousands of objects
    region_groups: dict[str, list] = {}
    for h in high_hexes:
        region = h.get("region", "other")
        if region not in region_groups:
            region_groups[region] = []
        region_groups[region].append(h)

    for region, group in region_groups.items():
        try:
            # Compute centroid of the group
            lats = [_safe_float(h.get("lat")) for h in group]
            lons = [_safe_float(h.get("lon")) for h in group]
            lats = [l for l in lats if l is not None]
            lons = [l for l in lons if l is not None]

            if not lats or not lons:
                counters.skipped += len(group)
                continue

            centroid_lat = sum(lats) / len(lats)
            centroid_lon = sum(lons) / len(lons)

            region_label = _JAMMING_REGIONS.get(region, region.replace("-", " ").title())
            name = f"GPS Jamming - {region_label}"

            # Further cluster within large regions - split if spread > 500km
            # For now, one event per region is sufficient
            total_aircraft = sum(h.get("aircraftCount", 0) for h in group)
            total_samples = sum(h.get("sampleCount", 0) for h in group)

            obj_id, created = w.upsert_object(
                name=name,
                type="event",
                subtype="gps_jamming",
                lat=centroid_lat,
                lon=centroid_lon,
                description=f"{len(group)} high-level jamming hexes in {region_label}",
                source=source,
            )
            if created:
                counters.objects_created += 1
                counters.events_created += 1
            else:
                counters.objects_updated += 1

            w.set_property(obj_id, "hex_count", str(len(group)), value_type="integer", source=source)
            counters.properties_set += 1
            w.set_property(obj_id, "region", region, source=source)
            counters.properties_set += 1
            if total_aircraft > 0:
                w.set_property(obj_id, "affected_aircraft", str(total_aircraft), value_type="integer", source=source)
                counters.properties_set += 1
            if total_samples > 0:
                w.set_property(obj_id, "total_samples", str(total_samples), value_type="integer", source=source)
                counters.properties_set += 1

        except Exception as exc:
            logger.warning("Failed to ingest GPS jamming region %s: %s", region, exc)
            counters.errors += 1

    return counters


def ingest_thermal_events(data: dict, source: str = None) -> IngestCounters:
    """Ingest thermal anomaly/escalation data.

    Expected shape: {"clusters": [{"id": "...", "centroid": {"latitude": ..., "longitude": ...}, ...}]}
    """
    source = source or "worldmonitor:thermal"
    counters = IngestCounters()
    w = _get_writer()

    clusters = data.get("clusters", []) or data.get("escalations", [])
    if not clusters:
        return counters

    for cluster in clusters:
        try:
            cluster_id = cluster.get("id", "")
            if not cluster_id:
                counters.skipped += 1
                continue

            centroid = cluster.get("centroid", {})
            lat = _safe_float(centroid.get("latitude"))
            lon = _safe_float(centroid.get("longitude"))
            country_code = cluster.get("countryCode", "")
            country_name = cluster.get("countryName", "")
            region_label = cluster.get("regionLabel", "")
            observation_count = cluster.get("observationCount", 0)
            z_score = _safe_float(cluster.get("zScore"))
            status = cluster.get("status", "")
            confidence = cluster.get("confidence", "")
            relevance = cluster.get("strategicRelevance", "")
            persistence = _safe_float(cluster.get("persistenceHours"))
            max_frp = _safe_float(cluster.get("maxFrp"))
            total_frp = _safe_float(cluster.get("totalFrp"))
            narrative_flags = cluster.get("narrativeFlags", [])
            first_detected = cluster.get("firstDetectedAt", "")
            last_detected = cluster.get("lastDetectedAt", "")

            name = f"Thermal-{cluster_id}"
            desc_parts = []
            if country_name:
                desc_parts.append(f"Thermal anomaly in {country_name}")
            if region_label and region_label != country_name:
                desc_parts.append(f"({region_label})")
            if observation_count:
                desc_parts.append(f"- {observation_count} observations")
            description = " ".join(desc_parts) if desc_parts else None

            obj_id, created = w.upsert_object(
                name=name,
                type="event",
                subtype="thermal_anomaly",
                lat=lat,
                lon=lon,
                country_code=country_code.upper() if country_code else None,
                description=description,
                source=source,
            )
            if created:
                counters.objects_created += 1
                counters.events_created += 1
            else:
                counters.objects_updated += 1

            # Properties
            if observation_count:
                w.set_property(obj_id, "cluster_size", str(observation_count), value_type="integer", source=source)
                counters.properties_set += 1
            if z_score is not None:
                w.set_property(obj_id, "z_score", f"{z_score:.2f}", value_type="float", source=source)
                counters.properties_set += 1
            if status:
                w.set_property(obj_id, "thermal_status", status, source=source)
                counters.properties_set += 1
            if confidence:
                w.set_property(obj_id, "thermal_confidence", confidence, source=source)
                counters.properties_set += 1
            if relevance:
                w.set_property(obj_id, "strategic_relevance", relevance, source=source)
                counters.properties_set += 1
            if persistence is not None:
                w.set_property(obj_id, "persistence_hours", f"{persistence:.1f}", value_type="float", source=source)
                counters.properties_set += 1
            if max_frp is not None:
                w.set_property(obj_id, "max_frp", f"{max_frp:.1f}", value_type="float", source=source)
                counters.properties_set += 1
            if total_frp is not None:
                w.set_property(obj_id, "total_frp", f"{total_frp:.1f}", value_type="float", source=source)
                counters.properties_set += 1
            if first_detected:
                w.set_property(obj_id, "first_detected", first_detected, value_type="datetime", source=source)
                counters.properties_set += 1
            if last_detected:
                w.set_property(obj_id, "last_detected", last_detected, value_type="datetime", source=source)
                counters.properties_set += 1
            if narrative_flags:
                w.set_property(obj_id, "narrative_flags", json.dumps(narrative_flags), value_type="json", source=source)
                counters.properties_set += 1

            # Link to country if known
            if country_name:
                country_id = w.find_object(country_name, "country")
                if country_id is not None:
                    w.add_link(
                        obj_id, country_id, "located_in",
                        confidence=0.95,
                        source=source,
                    )
                    counters.links_created += 1

        except Exception as exc:
            logger.warning("Failed to ingest thermal cluster %s: %s", cluster.get("id", "?"), exc)
            counters.errors += 1

    return counters


def ingest_oref_alerts(data: dict, source: str = None) -> IngestCounters:
    """Ingest OREF (Israeli Home Front Command) alert data.

    Expected shape: {"alerts": [...], "configured": true, "historyCount24h": N}
    """
    source = source or "worldmonitor:oref"
    counters = IngestCounters()
    w = _get_writer()

    alerts = data.get("alerts", [])
    if not alerts:
        return counters

    for alert in alerts:
        try:
            alert_id = alert.get("id") or alert.get("alertId")
            if not alert_id:
                # Generate a synthetic ID from available data
                location = alert.get("location", alert.get("data", ""))
                alert_type = alert.get("type", alert.get("cat", ""))
                alert_id = f"oref-{hash(f'{location}{alert_type}') & 0xFFFFFF:06x}"

            location = alert.get("location") or alert.get("data", "")
            alert_type = alert.get("type") or alert.get("cat", "unknown")
            lat = _safe_float(alert.get("lat") or alert.get("latitude"))
            lon = _safe_float(alert.get("lon") or alert.get("longitude"))
            timestamp = alert.get("timestamp") or alert.get("alertDate", "")

            # Determine subtype
            type_lower = alert_type.lower()
            if "missile" in type_lower or "ballistic" in type_lower:
                subtype = "missile_alert"
            elif "rocket" in type_lower:
                subtype = "rocket_alert"
            elif "uav" in type_lower or "drone" in type_lower:
                subtype = "uav_alert"
            elif "intrusion" in type_lower:
                subtype = "intrusion_alert"
            else:
                subtype = "air_defense_alert"

            name = f"OREF-{alert_id}"
            description = f"{alert_type} alert at {location}" if location else f"{alert_type} alert"

            obj_id, created = w.upsert_object(
                name=name,
                type="event",
                subtype=subtype,
                lat=lat,
                lon=lon,
                country_code="IL",
                description=description,
                source=source,
            )
            if created:
                counters.objects_created += 1
                counters.events_created += 1
            else:
                counters.objects_updated += 1

            if location:
                w.set_property(obj_id, "location_name", location, source=source)
                counters.properties_set += 1
            if alert_type:
                w.set_property(obj_id, "alert_type", alert_type, source=source)
                counters.properties_set += 1
            if timestamp:
                w.set_property(obj_id, "alert_time", str(timestamp), value_type="datetime", source=source)
                counters.properties_set += 1

            # Link to Israel
            israel_id = w.find_object("Israel", "country")
            if israel_id is not None:
                w.add_link(
                    obj_id, israel_id, "located_in",
                    confidence=1.0,
                    source=source,
                )
                counters.links_created += 1

        except Exception as exc:
            logger.warning("Failed to ingest OREF alert %s: %s", alert.get("id", "?"), exc)
            counters.errors += 1

    return counters


def ingest_news(data: dict, source: str = None) -> IngestCounters:
    """Ingest news digest data. Extracts entity mentions from titles
    rather than creating an object per article.

    Expected shape: {"categories": {"politics": {"items": [...]}, ...}}
    """
    source = source or "worldmonitor:news"
    counters = IngestCounters()
    w = _get_writer()

    categories = data.get("categories", {})
    if not categories:
        return counters

    # Collect significant articles (alert-level items with high threat)
    for category_name, category_data in categories.items():
        items = category_data.get("items", []) if isinstance(category_data, dict) else []
        for item in items:
            try:
                is_alert = item.get("isAlert", False)
                threat = item.get("threat", {})
                threat_level = threat.get("level", "THREAT_LEVEL_LOW")

                # Only create document objects for critical/high threat news
                if not is_alert or threat_level not in ("THREAT_LEVEL_CRITICAL", "THREAT_LEVEL_HIGH"):
                    continue

                title = item.get("title", "")
                if not title:
                    continue

                source_name = item.get("source", "")
                link = item.get("link", "")
                published_at = item.get("publishedAt")
                threat_category = threat.get("category", "")

                # Create a document object for significant news
                # Use a truncated title as name to avoid duplicates with different URLs
                name_clean = title[:120].strip()
                obj_id, created = w.upsert_object(
                    name=name_clean,
                    type="document",
                    subtype=f"news_{threat_category}" if threat_category else "news",
                    description=title,
                    source=source,
                )
                if created:
                    counters.objects_created += 1

                if source_name:
                    w.set_property(obj_id, "news_source", source_name, source=source)
                    counters.properties_set += 1
                if link:
                    w.set_property(obj_id, "url", link, source=source)
                    counters.properties_set += 1
                w.set_property(obj_id, "threat_level", threat_level, source=source)
                counters.properties_set += 1
                if published_at:
                    w.set_property(obj_id, "published_at", str(published_at), value_type="integer", source=source)
                    counters.properties_set += 1

                # Try to link to known entities mentioned in the title
                _link_title_entities(w, obj_id, title, source, counters)

            except Exception as exc:
                logger.warning("Failed to ingest news item: %s", exc)
                counters.errors += 1

    return counters


def _link_title_entities(
    w: OntologyWriter, doc_id: int, title: str, source: str, counters: IngestCounters
):
    """Search for known entities in a news title and link the document to them."""
    # Common entity names to check against existing objects
    # This is a lightweight approach - just check if known country/org names appear
    _KNOWN_ENTITY_NAMES = [
        "Russia", "Ukraine", "China", "Iran", "Israel", "United States", "US",
        "NATO", "Taiwan", "North Korea", "South Korea", "Japan",
        "Sudan", "Syria", "Yemen", "Lebanon", "Iraq", "Afghanistan",
        "Turkey", "Egypt", "Saudi Arabia", "India", "Pakistan",
        "United Kingdom", "France", "Germany", "Poland",
    ]

    title_upper = title.upper()
    for entity_name in _KNOWN_ENTITY_NAMES:
        if entity_name.upper() in title_upper:
            # Find the entity in the ontology
            eid = w.find_object(entity_name)
            if eid is not None:
                w.add_link(
                    doc_id, eid, "mentions",
                    confidence=0.7,
                    source=source,
                    description=f"Mentioned in: {title[:80]}",
                )
                counters.links_created += 1


def ingest_economic_data(data: dict, source: str = None) -> IngestCounters:
    """Ingest economic indicators from bootstrap or dedicated economic endpoints.

    Handles:
      - BIS policy rates: {"rates": [{"countryCode": "US", "rate": 3.625, ...}]}
      - BIS exchange rates: {"rates": [...]}
      - BIS credit: {"series": [...]}
      - Bootstrap economic data: {"data": {"macroSignals": {...}, "marketQuotes": {...}, ...}}
    """
    source = source or "worldmonitor:economic"
    counters = IngestCounters()
    w = _get_writer()

    # Handle BIS policy rates
    rates = data.get("rates", [])
    for rate_entry in rates:
        try:
            cc = rate_entry.get("countryCode", "")
            country_name = rate_entry.get("countryName", "")
            rate = rate_entry.get("rate")
            previous_rate = rate_entry.get("previousRate")
            date = rate_entry.get("date", "")
            central_bank = rate_entry.get("centralBank", "")

            if not country_name or rate is None:
                continue

            # Find or create country object
            country_id = w.find_object(country_name, "country")
            if country_id is None:
                country_id, created = w.upsert_object(
                    name=country_name,
                    type="country",
                    country_code=cc.upper() if cc else None,
                    source=source,
                )
                if created:
                    counters.objects_created += 1

            # Set policy rate property
            w.set_property(country_id, "policy_rate", str(rate), value_type="float", source=source)
            counters.properties_set += 1
            if previous_rate is not None:
                w.set_property(country_id, "previous_policy_rate", str(previous_rate), value_type="float", source=source)
                counters.properties_set += 1
            if date:
                w.set_property(country_id, "policy_rate_date", date, value_type="date", source=source)
                counters.properties_set += 1
            if central_bank:
                w.set_property(country_id, "central_bank", central_bank, source=source)
                counters.properties_set += 1

        except Exception as exc:
            logger.warning("Failed to ingest rate for %s: %s", rate_entry.get("countryName", "?"), exc)
            counters.errors += 1

    # Handle exchange rates (similar structure)
    exchange_rates = data.get("exchangeRates", [])
    for ex_entry in exchange_rates:
        try:
            cc = ex_entry.get("countryCode", "")
            country_name = ex_entry.get("countryName", "")
            rate = ex_entry.get("rate")

            if not country_name or rate is None:
                continue

            country_id = w.find_object(country_name, "country")
            if country_id is not None:
                w.set_property(country_id, "exchange_rate_usd", str(rate), value_type="float", source=source)
                counters.properties_set += 1

        except Exception as exc:
            logger.warning("Failed to ingest exchange rate: %s", exc)
            counters.errors += 1

    # Handle market/commodity quotes from bootstrap
    for quote_key in ("marketQuotes", "commodityQuotes"):
        quotes_data = data.get(quote_key, {})
        quotes = quotes_data.get("quotes", []) if isinstance(quotes_data, dict) else []
        for quote in quotes:
            try:
                symbol = quote.get("symbol", "")
                price = _safe_float(quote.get("price"))
                change = _safe_float(quote.get("change"))
                display_name = quote.get("display") or quote.get("name", symbol)

                if not symbol or price is None:
                    continue

                obj_id, created = w.upsert_object(
                    name=symbol,
                    type="financial_instrument",
                    subtype="equity" if quote_key == "marketQuotes" else "commodity",
                    aliases=[display_name] if display_name != symbol else None,
                    description=display_name,
                    source=source,
                )
                if created:
                    counters.objects_created += 1

                w.set_property(obj_id, "price", f"{price:.2f}", value_type="float", source=source)
                counters.properties_set += 1
                if change is not None:
                    w.set_property(obj_id, "change_pct", f"{change:.4f}", value_type="float", source=source)
                    counters.properties_set += 1

            except Exception as exc:
                logger.warning("Failed to ingest quote %s: %s", quote.get("symbol", "?"), exc)
                counters.errors += 1

    # Handle macro signals from bootstrap
    macro = data.get("macroSignals", {})
    if macro and isinstance(macro, dict):
        verdict = macro.get("verdict")
        if verdict:
            # Store as a global indicator - use a synthetic object
            obj_id, created = w.upsert_object(
                name="Global Macro Signal",
                type="indicator",
                subtype="macro_signal",
                description=f"Aggregate macro signal: {verdict}",
                source=source,
            )
            if created:
                counters.objects_created += 1
            w.set_property(obj_id, "verdict", verdict, source=source)
            counters.properties_set += 1
            bullish = macro.get("bullishCount")
            total = macro.get("totalCount")
            if bullish is not None:
                w.set_property(obj_id, "bullish_count", str(bullish), value_type="integer", source=source)
                counters.properties_set += 1
            if total is not None:
                w.set_property(obj_id, "total_signals", str(total), value_type="integer", source=source)
                counters.properties_set += 1

    return counters


def ingest_fleet_report(data: dict, source: str = None) -> IngestCounters:
    """Ingest USNI fleet tracker data.

    Expected shape: {"report": {"vessels": [{"name": "USS ...", "hullNumber": "...", ...}]}}
    """
    source = source or "worldmonitor:usni-fleet"
    counters = IngestCounters()
    w = _get_writer()

    report = data.get("report", {})
    vessels = report.get("vessels", [])
    if not vessels:
        return counters

    for vessel in vessels:
        try:
            name = vessel.get("name", "")
            if not name:
                counters.skipped += 1
                continue

            hull_number = vessel.get("hullNumber", "")
            vessel_type = vessel.get("vesselType", "")
            region = vessel.get("region", "")
            lat = _safe_float(vessel.get("regionLat"))
            lon = _safe_float(vessel.get("regionLon"))
            deployment_status = vessel.get("deploymentStatus", "")
            strike_group = vessel.get("strikeGroup", "")
            activity = vessel.get("activityDescription", "")

            aliases = []
            if hull_number:
                aliases.append(hull_number)

            obj_id, created = w.upsert_object(
                name=name,
                type="platform",
                subtype="vessel",
                aliases=aliases if aliases else None,
                lat=lat,
                lon=lon,
                country_code="US",
                description=activity[:200] if activity else None,
                source=source,
            )
            if created:
                counters.objects_created += 1
            else:
                counters.objects_updated += 1

            if hull_number:
                w.set_property(obj_id, "hull_number", hull_number, source=source)
                counters.properties_set += 1
            if vessel_type:
                w.set_property(obj_id, "vessel_type", vessel_type, source=source)
                counters.properties_set += 1
            if region:
                w.set_property(obj_id, "region", region, source=source)
                counters.properties_set += 1
            if deployment_status:
                w.set_property(obj_id, "deployment_status", deployment_status, source=source)
                counters.properties_set += 1
            if strike_group:
                w.set_property(obj_id, "strike_group", strike_group, source=source)
                counters.properties_set += 1

            # Link to US
            us_id = w.find_object("United States", "country")
            if us_id is not None:
                w.add_link(
                    obj_id, us_id, "operated_by",
                    confidence=1.0,
                    source=source,
                    description=f"USN {hull_number}" if hull_number else "USN",
                )
                counters.links_created += 1

        except Exception as exc:
            logger.warning("Failed to ingest fleet vessel %s: %s", vessel.get("name", "?"), exc)
            counters.errors += 1

    return counters


def ingest_displacement(data: dict, source: str = None) -> IngestCounters:
    """Ingest UNHCR displacement data.

    Expected shape: {"summary": {"countries": [{"code": "SDN", "name": "Sudan", ...}]}}
    """
    source = source or "worldmonitor:displacement"
    counters = IngestCounters()
    w = _get_writer()

    summary = data.get("summary", {})
    countries = summary.get("countries", [])
    if not countries:
        return counters

    for entry in countries:
        try:
            cc = entry.get("code", "")
            country_name = entry.get("name", "")
            if not country_name:
                continue

            lat = _safe_float(entry.get("location", {}).get("latitude"))
            lon = _safe_float(entry.get("location", {}).get("longitude"))

            country_id = w.find_object(country_name, "country")
            if country_id is None:
                country_id, created = w.upsert_object(
                    name=country_name,
                    type="country",
                    country_code=cc.upper() if cc else None,
                    lat=lat,
                    lon=lon,
                    source=source,
                )
                if created:
                    counters.objects_created += 1

            # Set displacement properties
            refugees = entry.get("refugees")
            idps = entry.get("idps")
            asylum_seekers = entry.get("asylumSeekers")
            total_displaced = entry.get("totalDisplaced")
            host_total = entry.get("hostTotal")

            if refugees is not None:
                w.set_property(country_id, "refugees", str(refugees), value_type="integer", source=source)
                counters.properties_set += 1
            if idps is not None:
                w.set_property(country_id, "idps", str(idps), value_type="integer", source=source)
                counters.properties_set += 1
            if asylum_seekers is not None:
                w.set_property(country_id, "asylum_seekers", str(asylum_seekers), value_type="integer", source=source)
                counters.properties_set += 1
            if total_displaced is not None:
                w.set_property(country_id, "total_displaced", str(total_displaced), value_type="integer", source=source)
                counters.properties_set += 1
            if host_total is not None:
                w.set_property(country_id, "host_refugees_total", str(host_total), value_type="integer", source=source)
                counters.properties_set += 1

        except Exception as exc:
            logger.warning("Failed to ingest displacement for %s: %s", entry.get("name", "?"), exc)
            counters.errors += 1

    return counters


def ingest_trade_data(data: dict, source: str = None) -> IngestCounters:
    """Ingest trade barriers and restrictions.

    Expected shape: {"barriers": [...]} or {"restrictions": [...]}
    """
    source = source or "worldmonitor:trade"
    counters = IngestCounters()
    w = _get_writer()

    # Trade barriers
    barriers = data.get("barriers", [])
    for barrier in barriers:
        try:
            country_name = barrier.get("notifyingCountry", "")
            if not country_name:
                continue

            country_id = w.find_object(country_name, "country")
            if country_id is None:
                country_id, created = w.upsert_object(
                    name=country_name,
                    type="country",
                    source=source,
                )
                if created:
                    counters.objects_created += 1

            measure_type = barrier.get("measureType", "")
            status = barrier.get("status", "")
            title = barrier.get("title", "")

            # Store as property - summarize barriers
            if measure_type:
                w.set_property(
                    country_id,
                    f"trade_barrier_{measure_type.lower().replace(' ', '_')[:40]}",
                    title[:200] if title else status,
                    source=source,
                )
                counters.properties_set += 1

        except Exception as exc:
            logger.warning("Failed to ingest trade barrier: %s", exc)
            counters.errors += 1

    # Trade restrictions
    restrictions = data.get("restrictions", [])
    for restriction in restrictions:
        try:
            country_name = restriction.get("country") or restriction.get("reporter", "")
            if not country_name:
                continue

            country_id = w.find_object(country_name, "country")
            if country_id is not None:
                title = restriction.get("title", "")
                r_type = restriction.get("type", "restriction")
                w.set_property(
                    country_id,
                    f"trade_restriction",
                    title[:200] if title else r_type,
                    source=source,
                )
                counters.properties_set += 1

        except Exception as exc:
            logger.warning("Failed to ingest trade restriction: %s", exc)
            counters.errors += 1

    return counters


def ingest_bootstrap(data: dict, source: str = None) -> IngestCounters:
    """Ingest the full bootstrap response, routing sub-sections to appropriate ingestors.

    Expected shape: {"data": {"earthquakes": {...}, "macroSignals": {...}, ...}}
    """
    source = source or "worldmonitor:bootstrap"
    counters = IngestCounters()

    payload = data.get("data", data)
    if not isinstance(payload, dict):
        return counters

    # Economic data (macroSignals, marketQuotes, commodityQuotes)
    econ_data = {}
    for key in ("macroSignals", "marketQuotes", "commodityQuotes"):
        if key in payload:
            econ_data[key] = payload[key]
    if econ_data:
        result = ingest_economic_data(econ_data, source=f"{source}:economic")
        counters.merge(result)

    # Chokepoints -> AIS-like disruptions
    chokepoints = payload.get("chokepoints", {})
    if chokepoints and isinstance(chokepoints, dict):
        cp_list = chokepoints.get("chokepoints", [])
        if cp_list:
            result = ingest_ais_data({"disruptions": cp_list}, source=f"{source}:chokepoints")
            counters.merge(result)

    # Theater posture
    theater_data = payload.get("theaterPosture", {})
    if theater_data and isinstance(theater_data, dict):
        theaters = theater_data.get("theaters", [])
        for theater in theaters:
            try:
                name = theater.get("name", "")
                if not name:
                    continue
                w = _get_writer()
                obj_id, created = w.upsert_object(
                    name=name,
                    type="region",
                    subtype="theater",
                    description=theater.get("summary", ""),
                    source=f"{source}:theater",
                )
                if created:
                    counters.objects_created += 1

                posture = theater.get("posture") or theater.get("level", "")
                if posture:
                    w.set_property(obj_id, "posture", str(posture), source=f"{source}:theater")
                    counters.properties_set += 1
                risk = theater.get("riskScore") or theater.get("risk")
                if risk is not None:
                    w.set_property(obj_id, "risk_score", str(risk), value_type="float", source=f"{source}:theater")
                    counters.properties_set += 1

            except Exception as exc:
                logger.warning("Failed to ingest theater %s: %s", theater.get("name", "?"), exc)
                counters.errors += 1

    # Risk scores
    risk_data = payload.get("riskScores", {})
    if risk_data and isinstance(risk_data, dict):
        strategic_risks = risk_data.get("strategicRisks", [])
        for risk in strategic_risks:
            try:
                name = risk.get("name", "")
                if not name:
                    continue
                w = _get_writer()
                obj_id, created = w.upsert_object(
                    name=name,
                    type="indicator",
                    subtype="strategic_risk",
                    description=risk.get("description", ""),
                    source=f"{source}:risk",
                )
                if created:
                    counters.objects_created += 1

                score = risk.get("score")
                if score is not None:
                    w.set_property(obj_id, "risk_score", str(score), value_type="float", source=f"{source}:risk")
                    counters.properties_set += 1
                trend = risk.get("trend", "")
                if trend:
                    w.set_property(obj_id, "trend", trend, source=f"{source}:risk")
                    counters.properties_set += 1

            except Exception as exc:
                logger.warning("Failed to ingest risk score: %s", exc)
                counters.errors += 1

    return counters


# ===================================================================
# Endpoint router
# ===================================================================

# Maps endpoint path patterns to ingestor functions
_ENDPOINT_MAP = {
    "api/military-flights": ingest_military_flights,
    "api/conflict/v1/list-acled-events": ingest_acled_events,
    "api/ais-snapshot": ingest_ais_data,
    "api/gpsjam": ingest_gps_jamming,
    "api/thermal/v1/list-thermal-escalations": ingest_thermal_events,
    "api/oref-alerts": ingest_oref_alerts,
    "api/news/v1/list-feed-digest": ingest_news,
    "api/economic/v1/get-bis-policy-rates": ingest_economic_data,
    "api/economic/v1/get-bis-exchange-rates": ingest_economic_data,
    "api/economic/v1/get-bis-credit": ingest_economic_data,
    "api/bootstrap": ingest_bootstrap,
    "api/military/v1/get-usni-fleet-report": ingest_fleet_report,
    "api/displacement/v1/get-displacement-summary": ingest_displacement,
    "api/trade/v1/get-trade-barriers": ingest_trade_data,
    "api/trade/v1/get-trade-restrictions": ingest_trade_data,
}

# Endpoints we intentionally skip (no structured data worth ontologizing)
_SKIP_ENDPOINTS = {
    "api/telegram-feed",  # Raw Telegram messages - too noisy
    "api/infrastructure/v1/list-temporal-anomalies",  # Infrastructure anomalies handled by bootstrap
}


def ingest_worldmonitor_response(endpoint: str, data: dict, source: str = None) -> dict:
    """Route a WorldMonitor API response to the appropriate ingestor.

    Args:
        endpoint: The API endpoint path (e.g. "api/military-flights")
        data: Parsed JSON response data
        source: Source string for provenance tracking

    Returns:
        Dict with keys: objects_created, objects_updated, links_created, events_created,
                        properties_set, skipped, errors
    """
    if not isinstance(data, dict):
        logger.warning("Expected dict for endpoint %s, got %s", endpoint, type(data).__name__)
        return IngestCounters().as_dict()

    if endpoint in _SKIP_ENDPOINTS:
        logger.debug("Skipping endpoint %s (in skip list)", endpoint)
        return IngestCounters().as_dict()

    ingestor = _ENDPOINT_MAP.get(endpoint)
    if ingestor is None:
        logger.debug("No ingestor registered for endpoint: %s", endpoint)
        return IngestCounters().as_dict()

    source = source or f"worldmonitor:{endpoint.replace('api/', '').replace('/', '-')}"

    try:
        counters = ingestor(data, source=source)
        return counters.as_dict()
    except Exception as exc:
        logger.error("Ingestor for %s failed: %s", endpoint, exc)
        return IngestCounters().as_dict()


# ===================================================================
# Bulk seed from cache
# ===================================================================

def seed_from_cache(cache_db_path: str = None, intel_db_path: str = None) -> dict:
    """Read all cached WorldMonitor responses and ingest them.

    Used for initial seeding of the ontology from historical data.

    Args:
        cache_db_path: Path to worldmonitor_cache.db (default: ~/.atrophy/worldmonitor_cache.db)
        intel_db_path: Path to intelligence.db (default: ~/.atrophy/agents/general_montgomery/data/intelligence.db)

    Returns:
        Combined counters dict plus metadata.
    """
    global _writer
    cache_path = os.path.expanduser(cache_db_path or str(_DEFAULT_CACHE_DB))
    intel_path = os.path.expanduser(intel_db_path or str(_DEFAULT_INTEL_DB))

    if not os.path.exists(cache_path):
        logger.error("Cache database not found: %s", cache_path)
        return {"error": f"Cache database not found: {cache_path}"}

    if not os.path.exists(intel_path):
        logger.error("Intelligence database not found: %s", intel_path)
        return {"error": f"Intelligence database not found: {intel_path}"}

    # Initialize global writer
    _writer = OntologyWriter(intel_path)

    cache_conn = sqlite3.connect(cache_path)
    cache_conn.row_factory = sqlite3.Row

    rows = cache_conn.execute(
        "SELECT cache_key, endpoint, response, fetched_at FROM cache ORDER BY fetched_at ASC"
    ).fetchall()

    total = IngestCounters()
    processed = 0
    endpoints_processed = set()

    print(f"Seeding ontology from {len(rows)} cached responses...")
    print(f"  Cache DB: {cache_path}")
    print(f"  Intel DB: {intel_path}")
    print(f"  Ontology module: {'ontology.py' if _HAS_ONTOLOGY else 'fallback SQL'}")
    print()

    for row in rows:
        endpoint = row["endpoint"]
        try:
            data = json.loads(row["response"])
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to parse JSON for %s: %s", endpoint, exc)
            total.errors += 1
            continue

        source = f"worldmonitor:{endpoint.replace('api/', '').replace('/', '-')}:seed"
        result = ingest_worldmonitor_response(endpoint, data, source=source)

        # Accumulate
        for key in ("objects_created", "objects_updated", "links_created", "events_created",
                     "properties_set", "skipped", "errors"):
            setattr(total, key, getattr(total, key) + result.get(key, 0))

        processed += 1
        endpoints_processed.add(endpoint)

        # Progress for significant endpoints
        created = result.get("objects_created", 0)
        if created > 0:
            print(f"  [{processed}/{len(rows)}] {endpoint}: +{created} objects, "
                  f"+{result.get('links_created', 0)} links, "
                  f"+{result.get('properties_set', 0)} props")

    cache_conn.close()
    _close_writer()

    result = total.as_dict()
    result["cache_rows_processed"] = processed
    result["endpoints_processed"] = sorted(endpoints_processed)

    print()
    print(f"Seed complete:")
    print(f"  Rows processed:   {processed}")
    print(f"  Endpoints:        {len(endpoints_processed)}")
    print(f"  Objects created:  {total.objects_created}")
    print(f"  Objects updated:  {total.objects_updated}")
    print(f"  Links created:    {total.links_created}")
    print(f"  Events created:   {total.events_created}")
    print(f"  Properties set:   {total.properties_set}")
    print(f"  Skipped:          {total.skipped}")
    print(f"  Errors:           {total.errors}")

    return result


# ===================================================================
# CLI entry point
# ===================================================================

def _setup_logging(verbose: bool = False):
    """Configure logging for CLI use."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOG_DIR / "ontology_ingest.log"

    root = logging.getLogger("ontology_ingest")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    if not root.handlers:
        fh = logging.FileHandler(log_path)
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(fmt)
        root.addHandler(fh)

        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.WARNING if not verbose else logging.INFO)
        sh.setFormatter(fmt)
        root.addHandler(sh)


def main():
    parser = argparse.ArgumentParser(description="Ontology ingest for WorldMonitor data")
    parser.add_argument("--seed", action="store_true", help="Seed ontology from all cached responses")
    parser.add_argument("--cache-db", default=None, help="Path to worldmonitor_cache.db")
    parser.add_argument("--intel-db", default=None, help="Path to intelligence.db")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    if args.seed:
        result = seed_from_cache(
            cache_db_path=args.cache_db,
            intel_db_path=args.intel_db,
        )
        if "error" in result:
            print(f"ERROR: {result['error']}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        print("\nUse --seed to populate the ontology from cached WorldMonitor data.")


if __name__ == "__main__":
    main()

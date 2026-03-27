#!/usr/bin/env python3
"""
Meridian Ontology - Schema Migration

Migrates the intelligence database from the legacy entity/relationship model
to the new ontology model (objects, properties, links, changelog, brief_objects).

Usage:
    python3 scripts/agents/shared/ontology_migrate.py [--db PATH]
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
# Country centroid lookup (lat, lon, ISO 3166-1 alpha-2)
# Covers all countries currently in the intelligence DB plus common extras
# ---------------------------------------------------------------------------
COUNTRY_CENTROIDS = {
    "Sudan":            (15.5007,  32.5599, "SD"),
    "UAE":              (23.4241,  53.8478, "AE"),
    "United Arab Emirates": (23.4241, 53.8478, "AE"),
    "Egypt":            (26.8206,  30.8025, "EG"),
    "Russia":           (61.5240,  105.3188, "RU"),
    "Iran":             (32.4279,  53.6880, "IR"),
    "Eritrea":          (15.1794,  39.7823, "ER"),
    "Chad":             (15.4542,  18.7322, "TD"),
    "Turkey":           (38.9637,  35.2433, "TR"),
    "Ukraine":          (48.3794,  31.1656, "UA"),
    "Israel":           (31.0461,  34.8516, "IL"),
    "United Kingdom":   (55.3781,  -3.4360, "GB"),
    "Poland":           (51.9194,  19.1451, "PL"),
    "Germany":          (51.1657,  10.4515, "DE"),
    "France":           (46.6034,   1.8883, "FR"),
    "United States":    (37.0902, -95.7129, "US"),
    "Baltic States":    (56.8796,  24.6032, "LV"),  # Latvia centroid as proxy
    "Denmark":          (56.2639,   9.5018, "DK"),
    "Spain":            (40.4637,  -3.7492, "ES"),
    "Italy":            (41.8719,  12.5674, "IT"),
    "Malaysia":         ( 4.2105, 101.9758, "MY"),
    "Saudi Arabia":     (23.8859,  45.0792, "SA"),
    "Lebanon":          (33.8547,  35.8623, "LB"),
    "Taiwan":           (23.6978, 120.9605, "TW"),
    "Kazakhstan":       (48.0196,  66.9237, "KZ"),
    "Libya":            (26.3351,  17.2283, "LY"),
    "People's Republic of China (PRC)": (35.8617, 104.1954, "CN"),
    "China":            (35.8617, 104.1954, "CN"),
    # Additional countries for future use
    "Afghanistan":      (33.9391,  67.7100, "AF"),
    "Algeria":          (28.0339,   1.6596, "DZ"),
    "Australia":        (-25.2744, 133.7751, "AU"),
    "Brazil":           (-14.2350, -51.9253, "BR"),
    "Canada":           (56.1304, -106.3468, "CA"),
    "Ethiopia":         ( 9.1450,  40.4897, "ET"),
    "India":            (20.5937,  78.9629, "IN"),
    "Indonesia":        (-0.7893, 113.9213, "ID"),
    "Iraq":             (33.2232,  43.6793, "IQ"),
    "Japan":            (36.2048, 138.2529, "JP"),
    "Jordan":           (30.5852,  36.2384, "JO"),
    "Kenya":            (-0.0236,  37.9062, "KE"),
    "Mali":             (17.5707,  -3.9962, "ML"),
    "Mexico":           (23.6345, -102.5528, "MX"),
    "Morocco":          (31.7917,  -7.0926, "MA"),
    "Myanmar":          (21.9162,  95.9560, "MM"),
    "Niger":            (17.6078,   8.0817, "NE"),
    "Nigeria":          ( 9.0820,   8.6753, "NG"),
    "North Korea":      (40.3399, 127.5101, "KP"),
    "Pakistan":         (30.3753,  69.3451, "PK"),
    "Philippines":      (12.8797, 121.7740, "PH"),
    "Qatar":            (25.3548,  51.1839, "QA"),
    "Somalia":          ( 5.1521,  46.1996, "SO"),
    "South Africa":     (-30.5595, 22.9375, "ZA"),
    "South Korea":      (35.9078, 127.7669, "KR"),
    "South Sudan":      ( 6.8770,  31.3070, "SS"),
    "Syria":            (34.8021,  38.9968, "SY"),
    "Thailand":         (15.8700, 100.9925, "TH"),
    "Tunisia":          (33.8869,   9.5375, "TN"),
    "Vietnam":          (14.0583, 108.2772, "VN"),
    "Yemen":            (15.5527,  48.5164, "YE"),
    "Burkina Faso":     (12.2383,  -1.5616, "BF"),
    "Kosovo":           (42.6026,  20.9020, "XK"),
    "Serbia":           (44.0165,  21.0059, "RS"),
}

# Region centroids for conflicts
REGION_CENTROIDS = {
    "Sub-Saharan Africa":   (15.50, 32.56),
    "Eastern Europe":       (48.38, 31.17),
    "Middle East":          (32.00, 44.00),
    "Indo-Pacific":         (23.70, 120.96),
    "West Africa":          (14.00, -2.00),
    "Middle East/Maritime": (15.55, 42.00),
    "Balkans":              (43.00, 21.00),
}


def backup_database(db_path: str) -> str:
    """Create a timestamped backup of the database."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup-{timestamp}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def create_tables(conn: sqlite3.Connection):
    """Create the new ontology tables."""
    conn.executescript("""
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

        CREATE TABLE IF NOT EXISTS brief_objects (
            brief_id INTEGER NOT NULL,
            object_id INTEGER NOT NULL,
            mention_count INTEGER DEFAULT 1,
            relevance TEXT DEFAULT 'mentioned',
            PRIMARY KEY (brief_id, object_id),
            FOREIGN KEY (brief_id) REFERENCES briefs(id),
            FOREIGN KEY (object_id) REFERENCES objects(id)
        );
    """)


def create_indexes(conn: sqlite3.Connection):
    """Create indexes for the new tables."""
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_objects_type ON objects(type);
        CREATE INDEX IF NOT EXISTS idx_objects_name ON objects(name);
        CREATE INDEX IF NOT EXISTS idx_objects_country ON objects(country_code);
        CREATE INDEX IF NOT EXISTS idx_objects_status ON objects(status);

        CREATE INDEX IF NOT EXISTS idx_properties_object ON properties(object_id);
        CREATE INDEX IF NOT EXISTS idx_properties_key ON properties(key);
        CREATE INDEX IF NOT EXISTS idx_properties_valid ON properties(valid_from, valid_to);

        CREATE INDEX IF NOT EXISTS idx_links_from ON links(from_id);
        CREATE INDEX IF NOT EXISTS idx_links_to ON links(to_id);
        CREATE INDEX IF NOT EXISTS idx_links_type ON links(type);

        CREATE INDEX IF NOT EXISTS idx_changelog_object ON changelog(object_id);
        CREATE INDEX IF NOT EXISTS idx_changelog_table ON changelog(table_name);
        CREATE INDEX IF NOT EXISTS idx_changelog_time ON changelog(created_at);
    """)


def migrate_entities(conn: sqlite3.Connection) -> int:
    """Migrate entities -> objects, preserving IDs."""
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT id, name, aliases, type, subtype, parent_id,
               description, status, created_at, updated_at
        FROM entities
    """).fetchall()

    count = 0
    for row in rows:
        eid, name, aliases, etype, subtype, parent_id, desc, status, created, updated = row

        # Geocode countries
        lat, lon, cc = None, None, None
        if etype == "country":
            centroid = COUNTRY_CENTROIDS.get(name)
            if centroid:
                lat, lon, cc = centroid

        cursor.execute("""
            INSERT INTO objects (id, type, subtype, name, aliases, status,
                                description, lat, lon, country_code,
                                first_seen, last_seen, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (eid, etype, subtype, name, aliases, status,
              desc, lat, lon, cc, created, updated, created, updated))

        # Store parent_id as a property if it exists
        if parent_id is not None:
            cursor.execute("""
                INSERT INTO properties (object_id, key, value, value_type, source, created_at)
                VALUES (?, 'parent_entity_id', ?, 'integer', 'migration', ?)
            """, (eid, str(parent_id), created))

        # Log the migration
        cursor.execute("""
            INSERT INTO changelog (object_id, table_name, record_id, action,
                                   source, agent, created_at)
            VALUES (?, 'objects', ?, 'migrated_from_entities', 'ontology_migrate', 'system', CURRENT_TIMESTAMP)
        """, (eid, eid))

        count += 1

    return count


def migrate_relationships(conn: sqlite3.Connection) -> int:
    """Migrate relationships -> links, preserving IDs."""
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT id, from_id, to_id, type, conflict_id, confidence,
               notes, source, valid_from, valid_to, created_at
        FROM relationships
    """).fetchall()

    count = 0
    for row in rows:
        rid, from_id, to_id, rtype, conflict_id, confidence, notes, source, vfrom, vto, created = row

        # Build description from notes
        desc = notes

        cursor.execute("""
            INSERT INTO links (id, from_id, to_id, type, description,
                               confidence, source, valid_from, valid_to, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (rid, from_id, to_id, rtype, desc, confidence, source, vfrom, vto, created))

        # Store conflict_id as a property on the link if present
        # (We track this via changelog since links don't have properties)
        if conflict_id is not None:
            cursor.execute("""
                INSERT INTO changelog (table_name, record_id, action, field,
                                       new_value, source, agent, created_at)
                VALUES ('links', ?, 'migrated_conflict_context', 'conflict_id',
                        ?, 'ontology_migrate', 'system', CURRENT_TIMESTAMP)
            """, (rid, str(conflict_id)))

        count += 1

    return count


def migrate_conflicts(conn: sqlite3.Connection, next_object_id: int) -> tuple:
    """Migrate conflicts -> objects (type=event, subtype=conflict).

    Returns (objects_created, properties_created, conflict_id_to_object_id mapping).
    """
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT id, name, slug, region, status, started_at, description, created_at
        FROM conflicts
    """).fetchall()

    conflict_map = {}  # conflict.id -> new object.id
    obj_count = 0
    prop_count = 0

    for row in rows:
        cid, name, slug, region, status, started_at, desc, created = row
        new_id = next_object_id + obj_count

        # Get lat/lon from region
        lat, lon = None, None
        region_centroid = REGION_CENTROIDS.get(region)
        if region_centroid:
            lat, lon = region_centroid

        cursor.execute("""
            INSERT INTO objects (id, type, subtype, name, status, description,
                                lat, lon, first_seen, last_seen,
                                created_at, updated_at)
            VALUES (?, 'event', 'conflict', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (new_id, name, status, desc, lat, lon,
              started_at or created, created, created, created))
        obj_count += 1

        conflict_map[cid] = new_id

        # Store conflict metadata as properties
        if slug:
            cursor.execute("""
                INSERT INTO properties (object_id, key, value, value_type, source, created_at)
                VALUES (?, 'slug', ?, 'string', 'migration', ?)
            """, (new_id, slug, created))
            prop_count += 1

        if region:
            cursor.execute("""
                INSERT INTO properties (object_id, key, value, value_type, source, created_at)
                VALUES (?, 'region', ?, 'string', 'migration', ?)
            """, (new_id, region, created))
            prop_count += 1

        if started_at:
            cursor.execute("""
                INSERT INTO properties (object_id, key, value, value_type, source, created_at)
                VALUES (?, 'started_at', ?, 'date', 'migration', ?)
            """, (new_id, started_at, created))
            prop_count += 1

        # Store old conflict ID for reference
        cursor.execute("""
            INSERT INTO properties (object_id, key, value, value_type, source, created_at)
            VALUES (?, 'legacy_conflict_id', ?, 'integer', 'migration', ?)
        """, (new_id, str(cid), created))
        prop_count += 1

        # Changelog
        cursor.execute("""
            INSERT INTO changelog (object_id, table_name, record_id, action,
                                   source, agent, created_at)
            VALUES (?, 'objects', ?, 'migrated_from_conflicts', 'ontology_migrate', 'system', CURRENT_TIMESTAMP)
        """, (new_id, new_id))

    return obj_count, prop_count, conflict_map


def migrate_conflict_actors(conn: sqlite3.Connection, conflict_map: dict, next_link_id: int) -> int:
    """Migrate conflict_actors -> links (entity participated_in conflict-object)."""
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT id, conflict_id, entity_id, alignment, side, notes
        FROM conflict_actors
    """).fetchall()

    count = 0
    for row in rows:
        aid, conflict_id, entity_id, alignment, side, notes = row

        conflict_obj_id = conflict_map.get(conflict_id)
        if conflict_obj_id is None:
            print(f"  WARNING: conflict_id={conflict_id} not found in map, skipping actor {aid}")
            continue

        link_id = next_link_id + count
        desc_parts = []
        if notes:
            desc_parts.append(notes)
        if side:
            desc_parts.append(f"side {side}")
        description = "; ".join(desc_parts) if desc_parts else None

        cursor.execute("""
            INSERT INTO links (id, from_id, to_id, type, subtype, description,
                               confidence, source, created_at)
            VALUES (?, ?, ?, 'participated_in', ?, ?, 0.95, 'migration', CURRENT_TIMESTAMP)
        """, (link_id, entity_id, conflict_obj_id, alignment, description))

        count += 1

    return count


def migrate_brief_entities(conn: sqlite3.Connection) -> int:
    """Migrate brief_entities -> brief_objects."""
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT brief_id, entity_id, mention_count
        FROM brief_entities
    """).fetchall()

    count = 0
    for row in rows:
        brief_id, entity_id, mention_count = row
        cursor.execute("""
            INSERT INTO brief_objects (brief_id, object_id, mention_count, relevance)
            VALUES (?, ?, ?, 'mentioned')
        """, (brief_id, entity_id, mention_count))
        count += 1

    return count


def run_migration(db_path: str):
    """Run the full ontology migration."""
    print(f"Meridian Ontology Migration")
    print(f"Database: {db_path}")
    print(f"{'=' * 60}")

    # Step 1: Backup
    backup_path = backup_database(db_path)
    print(f"\n[1/7] Backup created: {backup_path}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        # Step 2: Create tables
        create_tables(conn)
        create_indexes(conn)
        conn.commit()
        print("[2/7] Tables and indexes created")

        # Step 3: Migrate entities -> objects
        entity_count = migrate_entities(conn)
        conn.commit()
        print(f"[3/7] Entities migrated: {entity_count} objects created")

        # Step 4: Migrate relationships -> links
        rel_count = migrate_relationships(conn)
        conn.commit()
        print(f"[4/7] Relationships migrated: {rel_count} links created")

        # Step 5: Migrate conflicts -> objects
        # Get the next available object ID (after entities)
        max_entity_id = conn.execute("SELECT MAX(id) FROM entities").fetchone()[0] or 0
        next_obj_id = max_entity_id + 1000  # Leave a gap for future entity inserts

        conflict_obj_count, conflict_prop_count, conflict_map = migrate_conflicts(conn, next_obj_id)
        conn.commit()
        print(f"[5/7] Conflicts migrated: {conflict_obj_count} objects, {conflict_prop_count} properties")

        # Step 6: Migrate conflict_actors -> links
        max_link_id = conn.execute("SELECT MAX(id) FROM links").fetchone()[0] or 0
        actor_link_count = migrate_conflict_actors(conn, conflict_map, max_link_id + 1)
        conn.commit()
        print(f"[6/7] Conflict actors migrated: {actor_link_count} links created")

        # Step 7: Migrate brief_entities -> brief_objects
        brief_count = migrate_brief_entities(conn)
        conn.commit()
        print(f"[7/7] Brief entities migrated: {brief_count} brief_objects created")

        # Count parent_id properties separately
        parent_props = conn.execute(
            "SELECT COUNT(*) FROM properties WHERE key='parent_entity_id'"
        ).fetchone()[0]

        # Summary
        total_objects = conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        total_links = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        total_properties = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        total_changelog = conn.execute("SELECT COUNT(*) FROM changelog").fetchone()[0]
        total_brief_objects = conn.execute("SELECT COUNT(*) FROM brief_objects").fetchone()[0]

        print(f"\n{'=' * 60}")
        print(f"Migration complete")
        print(f"{'=' * 60}")
        print(f"  Objects:       {total_objects} ({entity_count} from entities + {conflict_obj_count} from conflicts)")
        print(f"  Links:         {total_links} ({rel_count} from relationships + {actor_link_count} from conflict_actors)")
        print(f"  Properties:    {total_properties} ({conflict_prop_count} from conflicts + {parent_props} parent refs)")
        print(f"  Brief objects: {total_brief_objects}")
        print(f"  Changelog:     {total_changelog} entries")

        # Print conflict object ID mapping
        print(f"\nConflict -> Object ID mapping:")
        for cid, oid in sorted(conflict_map.items()):
            name = conn.execute("SELECT name FROM objects WHERE id=?", (oid,)).fetchone()[0]
            print(f"  conflict {cid} -> object {oid} ({name})")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: Migration failed - {e}")
        print(f"Database restored to pre-migration state (backup at {backup_path})")
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate intelligence DB to Meridian ontology")
    parser.add_argument(
        "--db",
        default=os.path.expanduser("~/.atrophy/agents/general_montgomery/data/intelligence.db"),
        help="Path to the intelligence database",
    )
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: Database not found at {args.db}")
        sys.exit(1)

    run_migration(args.db)


if __name__ == "__main__":
    main()

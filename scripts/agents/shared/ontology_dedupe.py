#!/usr/bin/env python3
"""
Ontology deduplication script for intelligence.db.

Finds and merges:
1. Exact duplicates - same name AND type (case-insensitive) in the objects table
2. Near-duplicates - one object's name matches another's alias (same type)
3. Cross-type duplicates - known misclassified objects (e.g. cities as organizations)
4. Alias-based matches - Trump/Donald Trump, IDF/Israel Defense Forces
5. Orphaned links, properties, brief_objects

For each merge:
- Keep the object with the MOST properties+links (richest data)
- Move all properties from duplicate to keeper (skip if same key+value)
- Move all links from duplicate to keeper (update from_id/to_id)
- Move all brief_objects from duplicate to keeper
- Log all merges in changelog
- Delete the duplicate

Usage:
    python3 ontology_dedupe.py [--dry-run]
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = os.path.expanduser(
    "~/.atrophy/agents/general_montgomery/data/intelligence.db"
)
AGENT = "ontology_dedupe"
SOURCE = "ontology_dedupe"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

DRY_RUN = "--dry-run" in sys.argv
APPLY_REVIEWED = "--apply-reviewed" in sys.argv


# ----------------------------------------------------------------
# Known near-duplicate pairs to merge (curated).
# Each entry: (name_or_alias_a, name_or_alias_b, type_a, type_b)
# If types differ, we pick the more appropriate type.
# ----------------------------------------------------------------

# Cross-type merges: financial_center organizations -> locations
CROSS_TYPE_MERGES = [
    # (org name, org type, location name, location type, keep_type)
    # financial centers that are really locations
    ("New York", "organization", "New York", "location", "location"),
    ("London", "organization", "London", "location", "location"),
    ("Singapore", "organization", "Singapore", "location", "location"),
    ("Hong Kong", "organization", "Hong Kong", "location", "location"),
    ("San Francisco", "organization", "San Francisco", "location", "location"),
    ("Shanghai", "organization", "Shanghai", "location", "location"),
    ("Chicago", "organization", "Chicago", "location", "location"),
    ("Frankfurt", "organization", "Frankfurt", "location", "location"),
    ("Seoul", "organization", "Seoul", "location", "location"),
    ("Mumbai", "organization", "Mumbai", "location", "location"),
    ("Bermuda", "organization", "Bermuda", "country", "country"),
    ("Cayman Islands", "organization", "Cayman Islands", "country", "country"),
    # military entities
    ("Russian Black Sea Fleet", "faction", "Russian Black Sea Fleet", "organization", "organization"),
    # political entities
    ("Hamas", "faction", "Hamas", "organization", "organization"),
    ("Hezbollah", "faction", "Hezbollah", "organization", "organization"),
    ("RSF", "faction", "RSF", "organization", "organization"),
]

# Near-duplicate name pairs within same type
NEAR_DUPES = [
    # (name_a, name_b, type) - merge b into a (a is keeper)
    ("Donald Trump", "Trump", "person"),
    ("Israel Defense Forces", "IDF", "organization"),
    ("The Hacker News", "Hacker News", "organization"),
]


# ----------------------------------------------------------------
# Stats
# ----------------------------------------------------------------

stats = {
    "exact_dupes_found": 0,
    "exact_dupes_merged": 0,
    "near_dupes_found": 0,
    "near_dupes_merged": 0,
    "cross_type_found": 0,
    "cross_type_merged": 0,
    "alias_dupes_found": 0,
    "alias_dupes_merged": 0,
    "geo_dupes_found": 0,
    "geo_dupes_merged": 0,
    "name_dupes_found": 0,
    "name_dupes_merged": 0,
    "reviewed_applied": 0,
    "country_codes_normalized": 0,
    "orphaned_links_fixed": 0,
    "orphaned_properties_fixed": 0,
    "orphaned_brief_objects_fixed": 0,
    "properties_moved": 0,
    "links_moved": 0,
    "brief_objects_moved": 0,
}


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def log(msg):
    print(f"[dedupe] {msg}", flush=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def count_richness(conn, obj_id):
    """Count properties + links for an object. Higher = richer."""
    props = conn.execute(
        "SELECT COUNT(*) FROM properties WHERE object_id = ?", (obj_id,)
    ).fetchone()[0]
    links_from = conn.execute(
        "SELECT COUNT(*) FROM links WHERE from_id = ?", (obj_id,)
    ).fetchone()[0]
    links_to = conn.execute(
        "SELECT COUNT(*) FROM links WHERE to_id = ?", (obj_id,)
    ).fetchone()[0]
    briefs = conn.execute(
        "SELECT COUNT(*) FROM brief_objects WHERE object_id = ?", (obj_id,)
    ).fetchone()[0]
    return props + links_from + links_to + briefs


def merge_objects(conn, keeper_id, dupe_id, reason="duplicate"):
    """Merge dupe_id into keeper_id. Move all relations, delete dupe."""
    keeper = conn.execute("SELECT * FROM objects WHERE id = ?", (keeper_id,)).fetchone()
    dupe = conn.execute("SELECT * FROM objects WHERE id = ?", (dupe_id,)).fetchone()

    if not keeper or not dupe:
        log(f"  SKIP: one of ids {keeper_id}/{dupe_id} not found")
        return False

    log(f"  MERGE: #{dupe_id} '{dupe['name']}' ({dupe['type']}) -> #{keeper_id} '{keeper['name']}' ({keeper['type']}) [{reason}]")

    if DRY_RUN:
        return True

    # 1. Move properties (skip if same key+value already exists on keeper)
    dupe_props = conn.execute(
        "SELECT * FROM properties WHERE object_id = ?", (dupe_id,)
    ).fetchall()
    for prop in dupe_props:
        existing = conn.execute(
            "SELECT id FROM properties WHERE object_id = ? AND key = ? AND value = ?",
            (keeper_id, prop["key"], prop["value"]),
        ).fetchone()
        if not existing:
            conn.execute(
                "UPDATE properties SET object_id = ? WHERE id = ?",
                (keeper_id, prop["id"]),
            )
            stats["properties_moved"] += 1
        else:
            conn.execute("DELETE FROM properties WHERE id = ?", (prop["id"],))

    # 2. Move links (from_id)
    dupe_links_from = conn.execute(
        "SELECT * FROM links WHERE from_id = ?", (dupe_id,)
    ).fetchall()
    for link in dupe_links_from:
        existing = conn.execute(
            "SELECT id FROM links WHERE from_id = ? AND to_id = ? AND type = ?",
            (keeper_id, link["to_id"], link["type"]),
        ).fetchone()
        if not existing:
            conn.execute(
                "UPDATE links SET from_id = ? WHERE id = ?",
                (keeper_id, link["id"]),
            )
            stats["links_moved"] += 1
        else:
            conn.execute("DELETE FROM links WHERE id = ?", (link["id"],))

    # 3. Move links (to_id)
    dupe_links_to = conn.execute(
        "SELECT * FROM links WHERE to_id = ?", (dupe_id,)
    ).fetchall()
    for link in dupe_links_to:
        existing = conn.execute(
            "SELECT id FROM links WHERE from_id = ? AND to_id = ? AND type = ?",
            (link["from_id"], keeper_id, link["type"]),
        ).fetchone()
        if not existing:
            conn.execute(
                "UPDATE links SET to_id = ? WHERE id = ?",
                (keeper_id, link["id"]),
            )
            stats["links_moved"] += 1
        else:
            conn.execute("DELETE FROM links WHERE id = ?", (link["id"],))

    # 4. Move brief_objects
    dupe_briefs = conn.execute(
        "SELECT * FROM brief_objects WHERE object_id = ?", (dupe_id,)
    ).fetchall()
    for bo in dupe_briefs:
        existing = conn.execute(
            "SELECT brief_id FROM brief_objects WHERE brief_id = ? AND object_id = ?",
            (bo["brief_id"], keeper_id),
        ).fetchone()
        if not existing:
            conn.execute(
                "UPDATE brief_objects SET object_id = ? WHERE brief_id = ? AND object_id = ?",
                (keeper_id, bo["brief_id"], dupe_id),
            )
            stats["brief_objects_moved"] += 1
        else:
            conn.execute(
                "DELETE FROM brief_objects WHERE brief_id = ? AND object_id = ?",
                (bo["brief_id"], dupe_id),
            )

    # 4b. Move article_objects (mention links from harvested articles)
    try:
        art_objs = conn.execute(
            "SELECT * FROM article_objects WHERE object_id = ?", (dupe_id,)
        ).fetchall()
        for ao in art_objs:
            existing = conn.execute(
                "SELECT 1 FROM article_objects WHERE article_id = ? AND object_id = ?",
                (ao["article_id"], keeper_id),
            ).fetchone()
            if not existing:
                conn.execute(
                    "UPDATE article_objects SET object_id = ? WHERE article_id = ? AND object_id = ?",
                    (keeper_id, ao["article_id"], dupe_id),
                )
            else:
                conn.execute(
                    "DELETE FROM article_objects WHERE article_id = ? AND object_id = ?",
                    (ao["article_id"], dupe_id),
                )
    except sqlite3.OperationalError:
        pass  # table may not exist on older schemas

    # 4c. Move chat_turn_objects (mention links from chat conversations)
    # Composite PK: (source, source_turn_id, object_id) - we have to handle
    # potential PK collisions when keeper already has the same source/turn link.
    try:
        cto = conn.execute(
            "SELECT source, source_turn_id FROM chat_turn_objects WHERE object_id = ?",
            (dupe_id,),
        ).fetchall()
        for c in cto:
            existing = conn.execute(
                "SELECT 1 FROM chat_turn_objects WHERE source = ? AND source_turn_id = ? AND object_id = ?",
                (c["source"], c["source_turn_id"], keeper_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "DELETE FROM chat_turn_objects WHERE source = ? AND source_turn_id = ? AND object_id = ?",
                    (c["source"], c["source_turn_id"], dupe_id),
                )
            else:
                conn.execute(
                    "UPDATE chat_turn_objects SET object_id = ? WHERE source = ? AND source_turn_id = ? AND object_id = ?",
                    (keeper_id, c["source"], c["source_turn_id"], dupe_id),
                )
    except sqlite3.OperationalError:
        pass

    # 4d. Move change_proposals (pending edits referencing this object)
    try:
        conn.execute(
            "UPDATE change_proposals SET object_id = ? WHERE object_id = ?",
            (keeper_id, dupe_id),
        )
    except sqlite3.OperationalError:
        pass

    # 5. Merge aliases: combine dupe aliases into keeper
    keeper_aliases = []
    dupe_aliases = []
    try:
        if keeper["aliases"]:
            keeper_aliases = json.loads(keeper["aliases"])
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        if dupe["aliases"]:
            dupe_aliases = json.loads(dupe["aliases"])
    except (json.JSONDecodeError, TypeError):
        pass

    # Add dupe's name and aliases to keeper's aliases (if not already present)
    existing_lower = {a.lower() for a in keeper_aliases if isinstance(a, str)}
    existing_lower.add(keeper["name"].lower())

    if dupe["name"].lower() not in existing_lower:
        keeper_aliases.append(dupe["name"])
        existing_lower.add(dupe["name"].lower())

    for alias in dupe_aliases:
        if isinstance(alias, str) and alias.lower() not in existing_lower:
            keeper_aliases.append(alias)
            existing_lower.add(alias.lower())

    conn.execute(
        "UPDATE objects SET aliases = ?, updated_at = ? WHERE id = ?",
        (json.dumps(keeper_aliases) if keeper_aliases else None, NOW, keeper_id),
    )

    # 6. Changelog
    conn.execute(
        """INSERT INTO changelog (object_id, table_name, record_id, action, field,
           old_value, new_value, source, agent, created_at)
           VALUES (?, 'objects', ?, 'merge', 'merged_from',
           ?, ?, ?, ?, ?)""",
        (keeper_id, keeper_id,
         json.dumps({"id": dupe_id, "name": dupe["name"], "type": dupe["type"]}),
         json.dumps({"reason": reason}),
         SOURCE, AGENT, NOW),
    )

    # 7. Delete the duplicate
    conn.execute("DELETE FROM objects WHERE id = ?", (dupe_id,))

    return True


# ----------------------------------------------------------------
# Phase 1: Exact duplicates (same name + same type, case-insensitive)
# ----------------------------------------------------------------

def find_and_merge_exact_dupes(conn):
    log("=== Phase 1: Exact duplicates (same name + type) ===")

    rows = conn.execute("""
        SELECT LOWER(name) as lname, type, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
        FROM objects
        GROUP BY LOWER(name), type
        HAVING cnt > 1
        ORDER BY cnt DESC
    """).fetchall()

    stats["exact_dupes_found"] = len(rows)
    log(f"  Found {len(rows)} exact duplicate groups")

    for row in rows:
        ids = [int(x) for x in row["ids"].split(",")]
        # Pick the one with most data as keeper
        richness = [(obj_id, count_richness(conn, obj_id)) for obj_id in ids]
        richness.sort(key=lambda x: x[1], reverse=True)
        keeper_id = richness[0][0]

        for obj_id, _ in richness[1:]:
            if merge_objects(conn, keeper_id, obj_id, reason="exact_name_type"):
                stats["exact_dupes_merged"] += 1


# ----------------------------------------------------------------
# Phase 2: Alias-based duplicates
# One object's name matches another object's alias (same type)
# ----------------------------------------------------------------

def find_and_merge_alias_dupes(conn):
    log("=== Phase 2: Alias-based duplicates ===")

    # Build alias index: alias_lower -> (object_id, name)
    alias_index = {}
    rows = conn.execute(
        "SELECT id, name, type, aliases FROM objects WHERE aliases IS NOT NULL AND aliases != '[]'"
    ).fetchall()

    for row in rows:
        try:
            aliases = json.loads(row["aliases"])
            if isinstance(aliases, list):
                for alias in aliases:
                    if isinstance(alias, str) and alias.strip():
                        key = (alias.lower().strip(), row["type"])
                        if key not in alias_index:
                            alias_index[key] = []
                        alias_index[key].append(row["id"])
        except (json.JSONDecodeError, TypeError):
            continue

    # For each object, check if its name appears as an alias of another same-type object
    all_objects = conn.execute("SELECT id, name, type FROM objects").fetchall()
    merged_ids = set()
    merge_count = 0

    for obj in all_objects:
        if obj["id"] in merged_ids:
            continue
        key = (obj["name"].lower().strip(), obj["type"])
        if key in alias_index:
            for alias_owner_id in alias_index[key]:
                if alias_owner_id == obj["id"] or alias_owner_id in merged_ids:
                    continue
                # alias_owner has obj's name in its aliases -> they are same entity
                stats["alias_dupes_found"] += 1
                r_obj = count_richness(conn, obj["id"])
                r_owner = count_richness(conn, alias_owner_id)

                if r_owner >= r_obj:
                    keeper, dupe = alias_owner_id, obj["id"]
                else:
                    keeper, dupe = obj["id"], alias_owner_id

                if merge_objects(conn, keeper, dupe, reason="alias_match"):
                    stats["alias_dupes_merged"] += 1
                    merged_ids.add(dupe)
                    merge_count += 1

    log(f"  Found {stats['alias_dupes_found']} alias-based duplicates, merged {stats['alias_dupes_merged']}")


# ----------------------------------------------------------------
# Phase 3: Curated near-duplicate pairs
# ----------------------------------------------------------------

def find_and_merge_near_dupes(conn):
    log("=== Phase 3: Curated near-duplicate pairs ===")

    for name_a, name_b, obj_type in NEAR_DUPES:
        row_a = conn.execute(
            "SELECT id FROM objects WHERE LOWER(name) = LOWER(?) AND type = ?",
            (name_a, obj_type),
        ).fetchone()
        row_b = conn.execute(
            "SELECT id FROM objects WHERE LOWER(name) = LOWER(?) AND type = ?",
            (name_b, obj_type),
        ).fetchone()

        if row_a and row_b:
            stats["near_dupes_found"] += 1
            # Keep the one with the longer/more formal name
            r_a = count_richness(conn, row_a["id"])
            r_b = count_richness(conn, row_b["id"])
            if r_a >= r_b:
                keeper, dupe = row_a["id"], row_b["id"]
            else:
                keeper, dupe = row_b["id"], row_a["id"]
            if merge_objects(conn, keeper, dupe, reason="curated_near_dupe"):
                stats["near_dupes_merged"] += 1
        else:
            names = f"'{name_a}' and/or '{name_b}'"
            log(f"  SKIP curated pair: {names} ({obj_type}) - not both found")


# ----------------------------------------------------------------
# Phase 4: Cross-type duplicates (known misclassifications)
# ----------------------------------------------------------------

def find_and_merge_cross_type(conn):
    log("=== Phase 4: Cross-type duplicates ===")

    for name_a, type_a, name_b, type_b, keep_type in CROSS_TYPE_MERGES:
        row_a = conn.execute(
            "SELECT id, type FROM objects WHERE LOWER(name) = LOWER(?) AND type = ?",
            (name_a, type_a),
        ).fetchone()
        row_b = conn.execute(
            "SELECT id, type FROM objects WHERE LOWER(name) = LOWER(?) AND type = ?",
            (name_b, type_b),
        ).fetchone()

        if row_a and row_b:
            stats["cross_type_found"] += 1
            # Keep the one with the correct type
            if row_a["type"] == keep_type:
                keeper, dupe = row_a["id"], row_b["id"]
            else:
                keeper, dupe = row_b["id"], row_a["id"]
            if merge_objects(conn, keeper, dupe, reason="cross_type_misclassification"):
                stats["cross_type_merged"] += 1
        else:
            log(f"  SKIP cross-type: '{name_a}' ({type_a}) / '{name_b}' ({type_b}) - not both found")


# ----------------------------------------------------------------
# Phase 4a: Apply librarian-reviewed dedupe candidates
# When run with --apply-reviewed, processes all candidates marked
# as 'approved' by the librarian semantic review and merges them.
# ----------------------------------------------------------------

def apply_reviewed_candidates(conn):
    log("=== Phase 4a: Apply librarian-reviewed candidates ===")
    try:
        rows = conn.execute(
            "SELECT id, keeper_id, dupe_id, keeper_name, dupe_name, verdict_reason "
            "FROM dedupe_candidates WHERE status = 'approved' AND applied_at IS NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        log("  dedupe_candidates table not found - skipping")
        return

    if not rows:
        log("  No approved candidates pending application")
        return

    log(f"  Applying {len(rows)} librarian-approved merges")
    applied = 0
    for row in rows:
        if merge_objects(conn, row["keeper_id"], row["dupe_id"], reason=f"librarian_approved: {row['verdict_reason'][:60]}"):
            applied += 1
            if not DRY_RUN:
                conn.execute(
                    "UPDATE dedupe_candidates SET applied_at = ? WHERE id = ?",
                    (NOW, row["id"]),
                )
    stats["reviewed_applied"] = applied
    log(f"  Applied {applied} reviewed merges")


# ----------------------------------------------------------------
# Phase 4b: Geographic duplicates (same coordinates + same type)
# Catches cases like:
#   "Natanz" (lat=33.72, lon=51.73, type=location)
#   "Natanz Nuclear Facility" (lat=33.72, lon=51.73, type=location)
#   "Natanz Enrichment" (lat=33.7244, lon=51.7267, type=location)
# These get the same entity name root in common, point to the same place
# on earth, and should be merged. Tolerance: 0.05 degrees (~5 km).
# ----------------------------------------------------------------

GEO_TOLERANCE = 0.05  # degrees


def find_and_merge_geo_dupes(conn):
    log("=== Phase 4b: Geographic duplicates (same coordinates) ===")

    # Get all objects with valid coordinates, grouped by type.
    # ONLY match within the same type - don't merge a city with a facility
    # or building inside it (e.g. Tehran the city with "Gamma Irradiator - Tehran").
    # Also exclude 'country' from this phase since it's normal for many things
    # to share coordinates with the same country.
    rows = conn.execute("""
        SELECT id, name, type, lat, lon
        FROM objects
        WHERE lat IS NOT NULL AND lon IS NOT NULL
          AND type IN ('location', 'facility', 'base', 'site', 'installation')
        ORDER BY type, lat, lon
    """).fetchall()

    if not rows:
        log("  No georeferenced objects found")
        return

    # Group nearby points by (type, rounded lat, rounded lon) buckets
    # Use a coarser bucket so points just over the tolerance still meet
    buckets = {}
    for row in rows:
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (TypeError, ValueError):
            continue
        # Round to 0.1 degree (~10km) buckets
        key = (row["type"], round(lat, 1), round(lon, 1))
        buckets.setdefault(key, []).append({
            "id": row["id"],
            "name": row["name"],
            "lat": lat,
            "lon": lon,
        })

    geo_dupes_found = 0
    geo_dupes_merged = 0
    merged_ids = set()

    for bucket_key, candidates in buckets.items():
        if len(candidates) < 2:
            continue

        # Within each bucket, find pairs that are within GEO_TOLERANCE
        # AND share at least one significant word (3+ chars) in their names.
        # The word check prevents merging unrelated facilities that happen
        # to be in the same city.
        for i, a in enumerate(candidates):
            if a["id"] in merged_ids:
                continue
            for b in candidates[i + 1:]:
                if b["id"] in merged_ids:
                    continue
                if abs(a["lat"] - b["lat"]) > GEO_TOLERANCE:
                    continue
                if abs(a["lon"] - b["lon"]) > GEO_TOLERANCE:
                    continue

                # Names must share at least one significant word
                a_words = {w.lower() for w in a["name"].split() if len(w) >= 3}
                b_words = {w.lower() for w in b["name"].split() if len(w) >= 3}
                shared = a_words & b_words
                if not shared:
                    continue

                # Skip if shared words are too generic
                generic = {"the", "and", "national", "international", "north",
                           "south", "east", "west", "new", "old", "city",
                           "central", "eastern", "western", "northern", "southern",
                           "tehran", "moscow", "beijing", "washington", "london",
                           "paris", "berlin", "tokyo", "delhi", "cairo", "rome",
                           "kyiv", "ankara", "riyadh", "baghdad", "damascus"}
                if shared.issubset(generic):
                    continue

                # If one of the names contains an "additive qualifier" that the
                # other doesn't, they are NOT the same entity. Includes:
                # - facility types (embassy, building, base)
                # - container types (port, lane, terminal)
                # - military structures (command, brigade)
                # - generic adjectives (military, naval, air)
                # The "port of X" + "X" case is genuinely ambiguous - the port
                # facility is geographically inside the city - but for dedupe
                # safety we treat them as distinct.
                qualifiers = {"embassy", "consulate", "office", "building",
                              "brigade", "battalion", "regiment", "division",
                              "center", "centre", "station", "depot", "warehouse",
                              "headquarters", "branch", "subsidiary",
                              "reactor", "irradiator", "factory", "plant",
                              "compound", "residence", "ministry", "department",
                              "port", "harbour", "harbor", "terminal", "wharf",
                              "command", "base", "facility", "installation",
                              "lane", "shipping", "airfield", "airbase", "airport",
                              "military", "naval", "air", "joint", "operations",
                              "center", "training", "academy", "school",
                              "institute", "lab", "laboratory", "research"}
                a_has_qual = a_words & qualifiers
                b_has_qual = b_words & qualifiers
                if (a_has_qual and not b_has_qual) or (b_has_qual and not a_has_qual):
                    continue
                # Both have qualifiers but different ones -> different entities
                if a_has_qual and b_has_qual and a_has_qual != b_has_qual:
                    continue

                # Numeric suffix difference (Unit 1 vs Unit 2, Block A vs Block B)
                # means distinct sub-entities even at the same location.
                import re as _re
                a_nums = _re.findall(r'\b(\d+|[ivxIVX]+)\b', a["name"])
                b_nums = _re.findall(r'\b(\d+|[ivxIVX]+)\b', b["name"])
                if a_nums != b_nums:
                    continue

                # Final safety: if EITHER side has substantive non-shared words
                # that are PROPER NOUNS or distinct identifiers (not stopwords,
                # qualifiers, or generic words), the names refer to distinct
                # entities. e.g.:
                #   "Tel Aviv" vs "Mossad HQ Tel Aviv" -> 'mossad', 'hq' are
                #   substantive extras
                #   "US Embassy Canberra" vs "Chinese Embassy Canberra" ->
                #   both have substantive prefixes
                #   "Canberra" vs "ASD Canberra" -> ASD is substantive
                # The only safe merge through geo is when ONE side is a pure
                # subset of the other AND the extras are only qualifiers/generic.
                a_all = {w.lower() for w in a["name"].split() if w}
                b_all = {w.lower() for w in b["name"].split() if w}
                shared_all = a_all & b_all
                stopwords = qualifiers | generic | {"of", "for", "from", "at", "in", "on", "by", "with", "the", "a", "an"}
                a_extra = {w for w in a_all - shared_all if w not in stopwords}
                b_extra = {w for w in b_all - shared_all if w not in stopwords}
                # If EITHER side has substantive extras, they're distinct
                if a_extra or b_extra:
                    continue

                geo_dupes_found += 1
                # Pick keeper by richness, then by longer name (more descriptive)
                r_a = count_richness(conn, a["id"])
                r_b = count_richness(conn, b["id"])
                if r_a > r_b:
                    keeper_id, dupe_id = a["id"], b["id"]
                elif r_b > r_a:
                    keeper_id, dupe_id = b["id"], a["id"]
                elif len(a["name"]) >= len(b["name"]):
                    keeper_id, dupe_id = a["id"], b["id"]
                else:
                    keeper_id, dupe_id = b["id"], a["id"]

                log(f"  GEO match: '{a['name']}' ({a['id']}) and '{b['name']}' ({b['id']}) at ({a['lat']:.3f}, {a['lon']:.3f}) - shared: {shared}")
                if merge_objects(conn, keeper_id, dupe_id, reason="geo_coord_match"):
                    geo_dupes_merged += 1
                    merged_ids.add(dupe_id)

    stats["geo_dupes_found"] = geo_dupes_found
    stats["geo_dupes_merged"] = geo_dupes_merged
    log(f"  Found {geo_dupes_found} geographic duplicates, merged {geo_dupes_merged}")


# ----------------------------------------------------------------
# Phase 4c: Name-similarity duplicates (same type, name overlap)
# Catches "Natanz" / "Natanz Nuclear Facility" / "Natanz Enrichment"
# where one name is a clear superset/extension of another within the
# same type. Stricter than alias matching - requires the shorter name
# to be a contained subsequence of the longer one's tokens.
# ----------------------------------------------------------------

def find_and_merge_name_similarity(conn):
    log("=== Phase 4c: Name-similarity duplicates ===")

    # Words that indicate the longer name is a SUB-entity, not a different
    # spelling of the shorter name. If the longer name has any of these and
    # the shorter doesn't, treat them as distinct entities.
    sub_entity_qualifiers = {
        "brigade", "battalion", "regiment", "division", "corps", "squadron",
        "fleet", "wing", "company", "platoon",
        "embassy", "consulate", "office", "building", "department", "ministry",
        "branch", "subsidiary", "affiliate",
        "watch", "monitor", "tracker", "reporter", "report", "review", "status",
        "afro", "emro", "euro", "pahio", "searo", "wpro",  # WHO regional offices
        "spetsnaz",  # specific GRU sub-units
        "north", "south", "east", "west", "northern", "southern", "eastern", "western",
        "command", "section", "unit", "group", "team",
    }

    # Walk all objects sorted by name length, find shorter names
    # that are root names of longer ones within the same type.
    rows = conn.execute(
        "SELECT id, name, type FROM objects ORDER BY length(name)"
    ).fetchall()

    # Index by type for fast lookup
    by_type = {}
    for row in rows:
        by_type.setdefault(row["type"], []).append({
            "id": row["id"], "name": row["name"], "type": row["type"],
        })

    found = 0
    merged = 0
    merged_ids = set()

    for type_name, objs in by_type.items():
        # Only run on types where extending a name typically means same entity
        # Skip orgs, persons, events - too many sub-entities and namesakes
        if type_name not in ("location", "facility", "base", "site", "installation", "country"):
            continue
        for i, short in enumerate(objs):
            if short["id"] in merged_ids:
                continue
            short_lower = short["name"].lower().strip()
            short_words = [w for w in short_lower.split() if len(w) >= 3]
            if not short_words:
                continue

            for long in objs[i + 1:]:
                if long["id"] in merged_ids:
                    continue
                long_lower = long["name"].lower().strip()
                if long_lower == short_lower:
                    continue  # exact match handled by phase 1

                long_words = long_lower.split()

                # Match: short name appears as contiguous prefix of long
                if not long_lower.startswith(short_lower + " "):
                    continue
                if not all(w in long_words for w in short_words):
                    continue

                # Skip if the longer name has ANY substantive extras beyond
                # the short name. The deterministic phase only handles trivial
                # extensions like "Cebu" -> "Cebu City" or "Sao Paulo" ->
                # "Sao Paulo Brazil". For semantic judgment (city vs base
                # in city, country vs facility in country) we delegate to the
                # librarian semantic review.
                long_extra = set(long_words) - set(short_lower.split())
                # Allow only generic trailing words (City, Strip, Islands)
                allowed_trailing = {"city", "strip", "islands", "island",
                                    "republic", "republic", "kingdom"}
                if long_extra - allowed_trailing:
                    continue

                # Skip if the longer name has numeric suffixes the shorter
                # doesn't (Unit 1, Block A, Phase 2)
                import re as _re
                long_nums = _re.findall(r'\b(\d+|[ivxIVX]+)\b', long["name"])
                short_nums = _re.findall(r'\b(\d+|[ivxIVX]+)\b', short["name"])
                if long_nums != short_nums:
                    continue

                found += 1
                r_short = count_richness(conn, short["id"])
                r_long = count_richness(conn, long["id"])
                if r_long >= r_short:
                    keeper_id, dupe_id = long["id"], short["id"]
                else:
                    keeper_id, dupe_id = short["id"], long["id"]
                log(f"  NAME match: '{short['name']}' ({short['id']}) and '{long['name']}' ({long['id']}) [{type_name}]")
                if merge_objects(conn, keeper_id, dupe_id, reason="name_root_match"):
                    merged += 1
                    merged_ids.add(dupe_id)

    stats["name_dupes_found"] = found
    stats["name_dupes_merged"] = merged
    log(f"  Found {found} name-similarity duplicates, merged {merged}")


# ----------------------------------------------------------------
# Phase 4d: Country code normalization
# Atrophy ingests country codes from multiple sources - some use ISO-2
# ('IR'), some use ISO-3 ('IRN'), some use the full name. Normalize all
# to ISO-2 so the same country isn't split across rows.
# ----------------------------------------------------------------

# Curated mapping: alpha-3 -> alpha-2 for the countries we actually track
ISO3_TO_ISO2 = {
    "AFG": "AF", "ALB": "AL", "DZA": "DZ", "AND": "AD", "AGO": "AO",
    "ARG": "AR", "ARM": "AM", "AUS": "AU", "AUT": "AT", "AZE": "AZ",
    "BHR": "BH", "BGD": "BD", "BLR": "BY", "BEL": "BE", "BLZ": "BZ",
    "BEN": "BJ", "BTN": "BT", "BOL": "BO", "BIH": "BA", "BWA": "BW",
    "BRA": "BR", "BRN": "BN", "BGR": "BG", "BFA": "BF", "BDI": "BI",
    "KHM": "KH", "CMR": "CM", "CAN": "CA", "CPV": "CV", "CAF": "CF",
    "TCD": "TD", "CHL": "CL", "CHN": "CN", "COL": "CO", "COM": "KM",
    "COG": "CG", "COD": "CD", "CRI": "CR", "CIV": "CI", "HRV": "HR",
    "CUB": "CU", "CYP": "CY", "CZE": "CZ", "DNK": "DK", "DJI": "DJ",
    "DMA": "DM", "DOM": "DO", "ECU": "EC", "EGY": "EG", "SLV": "SV",
    "GNQ": "GQ", "ERI": "ER", "EST": "EE", "SWZ": "SZ", "ETH": "ET",
    "FJI": "FJ", "FIN": "FI", "FRA": "FR", "GAB": "GA", "GMB": "GM",
    "GEO": "GE", "DEU": "DE", "GHA": "GH", "GRC": "GR", "GRD": "GD",
    "GTM": "GT", "GIN": "GN", "GNB": "GW", "GUY": "GY", "HTI": "HT",
    "HND": "HN", "HUN": "HU", "ISL": "IS", "IND": "IN", "IDN": "ID",
    "IRN": "IR", "IRQ": "IQ", "IRL": "IE", "ISR": "IL", "ITA": "IT",
    "JAM": "JM", "JPN": "JP", "JOR": "JO", "KAZ": "KZ", "KEN": "KE",
    "KIR": "KI", "PRK": "KP", "KOR": "KR", "KWT": "KW", "KGZ": "KG",
    "LAO": "LA", "LVA": "LV", "LBN": "LB", "LSO": "LS", "LBR": "LR",
    "LBY": "LY", "LIE": "LI", "LTU": "LT", "LUX": "LU", "MDG": "MG",
    "MWI": "MW", "MYS": "MY", "MDV": "MV", "MLI": "ML", "MLT": "MT",
    "MHL": "MH", "MRT": "MR", "MUS": "MU", "MEX": "MX", "FSM": "FM",
    "MDA": "MD", "MCO": "MC", "MNG": "MN", "MNE": "ME", "MAR": "MA",
    "MOZ": "MZ", "MMR": "MM", "NAM": "NA", "NRU": "NR", "NPL": "NP",
    "NLD": "NL", "NZL": "NZ", "NIC": "NI", "NER": "NE", "NGA": "NG",
    "MKD": "MK", "NOR": "NO", "OMN": "OM", "PAK": "PK", "PLW": "PW",
    "PSE": "PS", "PAN": "PA", "PNG": "PG", "PRY": "PY", "PER": "PE",
    "PHL": "PH", "POL": "PL", "PRT": "PT", "QAT": "QA", "ROU": "RO",
    "RUS": "RU", "RWA": "RW", "KNA": "KN", "LCA": "LC", "VCT": "VC",
    "WSM": "WS", "SMR": "SM", "STP": "ST", "SAU": "SA", "SEN": "SN",
    "SRB": "RS", "SYC": "SC", "SLE": "SL", "SGP": "SG", "SVK": "SK",
    "SVN": "SI", "SLB": "SB", "SOM": "SO", "ZAF": "ZA", "SSD": "SS",
    "ESP": "ES", "LKA": "LK", "SDN": "SD", "SUR": "SR", "SWE": "SE",
    "CHE": "CH", "SYR": "SY", "TWN": "TW", "TJK": "TJ", "TZA": "TZ",
    "THA": "TH", "TLS": "TL", "TGO": "TG", "TON": "TO", "TTO": "TT",
    "TUN": "TN", "TUR": "TR", "TKM": "TM", "TUV": "TV", "UGA": "UG",
    "UKR": "UA", "ARE": "AE", "GBR": "GB", "USA": "US", "URY": "UY",
    "UZB": "UZ", "VUT": "VU", "VAT": "VA", "VEN": "VE", "VNM": "VN",
    "YEM": "YE", "ZMB": "ZM", "ZWE": "ZW",
}


def normalize_country_codes(conn):
    log("=== Phase 4d: Country code normalization (ISO-3 -> ISO-2) ===")

    rows = conn.execute(
        "SELECT id, name, country_code FROM objects WHERE country_code IS NOT NULL AND country_code != ''"
    ).fetchall()

    updated = 0
    for row in rows:
        cc = (row["country_code"] or "").strip().upper()
        if cc in ISO3_TO_ISO2:
            new_cc = ISO3_TO_ISO2[cc]
            if not DRY_RUN:
                conn.execute(
                    "UPDATE objects SET country_code = ? WHERE id = ?",
                    (new_cc, row["id"]),
                )
            updated += 1

    stats["country_codes_normalized"] = updated
    log(f"  Normalized {updated} country codes from ISO-3 to ISO-2")


# ----------------------------------------------------------------
# Phase 5: Fix orphaned records
# ----------------------------------------------------------------

def fix_orphans(conn):
    log("=== Phase 5: Fix orphaned records ===")

    if DRY_RUN:
        # Just count
        count = conn.execute(
            "SELECT COUNT(*) FROM links WHERE from_id NOT IN (SELECT id FROM objects) OR to_id NOT IN (SELECT id FROM objects)"
        ).fetchone()[0]
        log(f"  {count} orphaned links (dry run)")

        count = conn.execute(
            "SELECT COUNT(*) FROM properties WHERE object_id NOT IN (SELECT id FROM objects)"
        ).fetchone()[0]
        log(f"  {count} orphaned properties (dry run)")

        count = conn.execute(
            "SELECT COUNT(*) FROM brief_objects WHERE object_id NOT IN (SELECT id FROM objects)"
        ).fetchone()[0]
        log(f"  {count} orphaned brief_objects (dry run)")
        return

    # Orphaned links
    result = conn.execute(
        "DELETE FROM links WHERE from_id NOT IN (SELECT id FROM objects) OR to_id NOT IN (SELECT id FROM objects)"
    )
    stats["orphaned_links_fixed"] = result.rowcount
    log(f"  Deleted {result.rowcount} orphaned links")

    # Orphaned properties
    result = conn.execute(
        "DELETE FROM properties WHERE object_id NOT IN (SELECT id FROM objects)"
    )
    stats["orphaned_properties_fixed"] = result.rowcount
    log(f"  Deleted {result.rowcount} orphaned properties")

    # Orphaned brief_objects
    result = conn.execute(
        "DELETE FROM brief_objects WHERE object_id NOT IN (SELECT id FROM objects)"
    )
    stats["orphaned_brief_objects_fixed"] = result.rowcount
    log(f"  Deleted {result.rowcount} orphaned brief_objects")


# ----------------------------------------------------------------
# Phase 6: Fix orphans in old schema (entities/relationships)
# ----------------------------------------------------------------

def fix_old_schema_orphans(conn):
    log("=== Phase 6: Fix orphaned records in old schema (entities/relationships) ===")

    if DRY_RUN:
        count = conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE from_id NOT IN (SELECT id FROM entities) OR to_id NOT IN (SELECT id FROM entities)"
        ).fetchone()[0]
        log(f"  {count} orphaned relationships in old schema (dry run)")
        return

    result = conn.execute(
        "DELETE FROM relationships WHERE from_id NOT IN (SELECT id FROM entities) OR to_id NOT IN (SELECT id FROM entities)"
    )
    log(f"  Deleted {result.rowcount} orphaned relationships in old schema")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------

def main():
    if DRY_RUN:
        log("*** DRY RUN MODE - no changes will be made ***")

    log(f"Opening database: {DB_PATH}")
    conn = get_conn()

    # Pre-counts
    obj_count = conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
    prop_count = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
    link_count = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    log(f"Before: {obj_count} objects, {prop_count} properties, {link_count} links")

    # If --apply-reviewed, only run the reviewed candidate phase + orphan cleanup
    if APPLY_REVIEWED:
        log("APPLY-REVIEWED MODE: only processing librarian-approved candidates")
        apply_reviewed_candidates(conn)
        fix_orphans(conn)
    else:
        # Normalize country codes first so subsequent phases compare apples to apples
        normalize_country_codes(conn)
        find_and_merge_exact_dupes(conn)
        find_and_merge_alias_dupes(conn)
        find_and_merge_near_dupes(conn)
        find_and_merge_cross_type(conn)
        find_and_merge_geo_dupes(conn)
        find_and_merge_name_similarity(conn)
        # Apply any reviewed candidates from previous librarian runs
        apply_reviewed_candidates(conn)
        fix_orphans(conn)
        fix_old_schema_orphans(conn)

    if not DRY_RUN:
        conn.commit()

    # Post-counts
    obj_count_after = conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
    prop_count_after = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
    link_count_after = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]

    log("")
    log("=== REPORT ===")
    log(f"Country codes normalized: {stats['country_codes_normalized']}")
    log(f"Exact duplicates: found {stats['exact_dupes_found']} groups, merged {stats['exact_dupes_merged']}")
    log(f"Alias duplicates: found {stats['alias_dupes_found']}, merged {stats['alias_dupes_merged']}")
    log(f"Near duplicates (curated): found {stats['near_dupes_found']}, merged {stats['near_dupes_merged']}")
    log(f"Cross-type duplicates: found {stats['cross_type_found']}, merged {stats['cross_type_merged']}")
    log(f"Geographic duplicates: found {stats['geo_dupes_found']}, merged {stats['geo_dupes_merged']}")
    log(f"Name-similarity duplicates: found {stats['name_dupes_found']}, merged {stats['name_dupes_merged']}")
    log(f"Librarian-reviewed merges applied: {stats['reviewed_applied']}")
    log(f"Properties moved: {stats['properties_moved']}")
    log(f"Links moved: {stats['links_moved']}")
    log(f"Brief objects moved: {stats['brief_objects_moved']}")
    log(f"Orphaned links deleted: {stats['orphaned_links_fixed']}")
    log(f"Orphaned properties deleted: {stats['orphaned_properties_fixed']}")
    log(f"Orphaned brief_objects deleted: {stats['orphaned_brief_objects_fixed']}")
    log(f"")
    log(f"Objects: {obj_count} -> {obj_count_after} (removed {obj_count - obj_count_after})")
    log(f"Properties: {prop_count} -> {prop_count_after}")
    log(f"Links: {link_count} -> {link_count_after}")

    conn.close()


if __name__ == "__main__":
    main()

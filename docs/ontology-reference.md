# Ontology Reference - intelligence.db

The ontology is a research-grade knowledge graph stored in SQLite at `~/.atrophy/agents/general_montgomery/data/intelligence.db`. It replaced the original flat entity table with a rich schema of typed objects, structured properties with provenance, temporal links, and a full audit trail.

As of 2026-03-27: 543+ objects, 2285+ properties, 254+ links.

---

## Schema

### Objects

Everything is an object. Objects have a type that determines their property schema.

```sql
CREATE TABLE objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    subtype TEXT,
    name TEXT NOT NULL,
    aliases TEXT,               -- JSON array
    status TEXT DEFAULT 'active',
    description TEXT,
    lat REAL,                   -- primary geographic position
    lon REAL,
    country_code TEXT,          -- ISO 3166-1 alpha-2
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Indexes: `type`, `name`, `country_code`, `status`, `(lat, lon)`.

### Properties

Key-value pairs with provenance and temporal validity. Every fact about an object is a property.

```sql
CREATE TABLE properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'string',  -- string, number, boolean, json, date
    confidence REAL DEFAULT 1.0,
    source TEXT,                        -- brief:34, worldmonitor:acled, seed:restcountries
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,                 -- NULL = still current
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (object_id) REFERENCES objects(id)
);
```

Indexes: `object_id`, `key`, `source`.

### Links

Typed relationships between objects with provenance and temporal validity.

```sql
CREATE TABLE links (
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
```

Indexes: `from_id`, `to_id`, `type`, `source`. Unique constraint on `(from_id, to_id, type, source)`.

### Changelog

Full audit trail of all ontology changes - every create, update, delete, and merge.

```sql
CREATE TABLE changelog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER,
    table_name TEXT NOT NULL,     -- objects, properties, links
    record_id INTEGER NOT NULL,
    action TEXT NOT NULL,         -- create, update, delete, merge
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    source TEXT,
    agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Indexes: `object_id`, `created_at`, `source`.

### Brief-Object Linking

Join table between briefs and objects with relevance scoring.

```sql
CREATE TABLE brief_objects (
    brief_id INTEGER NOT NULL,
    object_id INTEGER NOT NULL,
    mention_count INTEGER DEFAULT 1,
    relevance TEXT DEFAULT 'mentioned',  -- mentioned, primary_subject, source
    PRIMARY KEY (brief_id, object_id),
    FOREIGN KEY (brief_id) REFERENCES briefs(id),
    FOREIGN KEY (object_id) REFERENCES objects(id)
);
```

---

## Object Types

| Type | Subtypes | Example properties |
|------|----------|-------------------|
| `person` | head_of_state, commander, diplomat, minister, intelligence_officer, analyst | title, nationality, birth_year, party, portfolio, last_known_location |
| `organization` | government, military, intelligence_service, ngo, think_tank, media, corporation | headquarters, founding_year, member_count, parent_org |
| `faction` | armed_group, coalition, paramilitary, militia, separatist | ideology, strength_estimate, territory_held |
| `country` | sovereign, disputed, territory, autonomous_region | population, gdp_usd, military_budget_usd, government_type, capital, nuclear_status, un_member |
| `location` | city, base, port, chokepoint, infrastructure, border_crossing | population, elevation_m, facility_type, capacity |
| `platform` | vessel, aircraft, weapons_system, satellite, missile | imo_number/mmsi (vessels), icao_hex/registration (aircraft), operator, displacement_tonnes, last_position_lat/lon |
| `unit` | army, navy, air_force, brigade, fleet, division, special_forces | strength, equipment_count, operational_status |
| `event` | strike, battle, election, agreement, deployment, incident, exercise, test | date, end_date, casualties, weapons_used, damage_assessment |
| `document` | brief, treaty, resolution, report, sanction_order | publication_date, issuing_body, product_type |

---

## Link Types

| Type | Description | Example |
|------|-------------|---------|
| `leads` | Person leads org/country/unit | Putin leads Russia |
| `commands` | Military command | Gerasimov commands Russian Armed Forces |
| `member_of` | Membership | Turkey member_of NATO |
| `located_at` | Geographic location | Incirlik located_at Turkey |
| `operates` | Org operates platform/unit | Russia operates Black Sea Fleet |
| `deployed_to` | Unit/platform deployed to location | USS Ford deployed_to Eastern Med |
| `allied_with` | Alliance relationship | UAE allied_with SAF |
| `opposes` | Adversarial relationship | RSF opposes SAF |
| `funds` | Financial support | UAE funds RSF |
| `arms` | Weapons supply | Iran arms Houthis |
| `sanctions` | Sanctions relationship | US sanctions Iran |
| `participated_in` | Participation in event | Israel participated_in Isfahan strike |
| `targets` | Targeting relationship | Strike targets facility |
| `mediates` | Mediation role | Turkey mediates grain corridor |
| `trades_with` | Trade relationship | China trades_with Iran |
| `subsidiary_of` | Org hierarchy | IRGC-Navy subsidiary_of IRGC |
| `borders` | Geographic adjacency | Ukraine borders Russia |
| `controls` | Territorial control | Russia controls Crimea |
| `hosts` | Basing/hosting | Turkey hosts Incirlik |
| `produced_by` | Document authorship | Brief produced_by rf_russia_ukraine |

---

## Auto-Ingestion Pipeline

### From WorldMonitor feeds

The `ontology_ingest.py` script routes WorldMonitor API responses to 8 typed ingestors:

| Feed | Cadence | Extracts | Object types |
|------|---------|----------|-------------|
| Military flights | Every 15 min | Aircraft, positions, operators | platform (aircraft), event (detection) |
| ACLED conflict events | Every 45 min | Battles, explosions, protests, actors | event, faction/organization, location |
| AIS maritime | Every 15 min | Vessels, positions, disruptions | platform (vessel), event |
| GPS jamming | Every 15 min | Jamming zones, locations | event (jamming) |
| OREF alerts | Every 15 min | Missile/rocket alerts, locations | event (alert) |
| Thermal escalations | Every 45 min | Thermal anomaly clusters | event (thermal_anomaly) |
| News digest | Every 3 hours | Entity mentions from articles | Various (via LLM extraction) |
| Bootstrap/economic | Every 4 hours | Country indicators, energy prices | Properties on country/location objects |

### From briefs

Every new brief triggers:
1. Entity extraction - identify mentioned objects
2. Relationship extraction - extract links via Claude Haiku
3. Event extraction - identify events described in text
4. Property updates - extract factual claims as properties
5. Brief-object linking - populate `brief_objects` table

### Upsert logic

Objects are matched by (in order):
1. Exact ID (if updating a known object)
2. Name + type (case-insensitive)
3. Alias match (check aliases JSON array)
4. Identifier match (ICAO hex for aircraft, MMSI for vessels, ISO code for countries)

If no match: create new object. If match found: update properties, bump last_seen, log changes.

---

## Seeding

Objects are seeded from multiple external sources:

### Country data
- **REST Countries API** - all sovereign nations with ISO codes, capitals, regions, population
- **World Bank** - GDP, military expenditure, government effectiveness indicators
- Links generated: capital `located_at` country, country `borders` country

### Leadership
- Heads of state extracted from country data
- Links: leader `leads` country, leader `member_of` party

### Military
- Major military units for key countries (army, navy, air force, special forces)
- Weapons systems (aircraft, vessels, missiles, air defence)
- Military bases and installations
- Links: unit `subsidiary_of` armed_forces, unit `located_at` base, country `operates` unit

### Geography
- Strategic chokepoints (Strait of Hormuz, Bab el-Mandeb, Malacca, Taiwan Strait, etc.)
- Critical infrastructure (pipelines, cables, ports, power plants)
- Links: chokepoint `located_at` region, infrastructure `located_at` country

### Government
- Full org charts for key countries (ministries, agencies, intelligence services)
- Links: agency `subsidiary_of` ministry, person `leads` agency

---

## Querying the Ontology

### Basic object queries

```sql
-- All objects of a type
SELECT id, name, subtype, status, description
FROM objects WHERE type = 'country' ORDER BY name;

-- Search by name (fuzzy)
SELECT id, name, type, subtype
FROM objects WHERE name LIKE '%iran%' OR aliases LIKE '%iran%';

-- Objects in a geographic area
SELECT name, type, subtype, lat, lon
FROM objects
WHERE lat BETWEEN 25 AND 40 AND lon BETWEEN 44 AND 63
ORDER BY type, name;
```

### Property queries

```sql
-- All properties for an object
SELECT key, value, value_type, confidence, source, valid_from, valid_to
FROM properties WHERE object_id = ? ORDER BY key;

-- Current properties only (not expired)
SELECT key, value, confidence, source
FROM properties
WHERE object_id = ? AND (valid_to IS NULL OR valid_to > datetime('now'))
ORDER BY key;

-- Find objects by property value
SELECT o.name, o.type, p.key, p.value
FROM properties p JOIN objects o ON p.object_id = o.id
WHERE p.key = 'nuclear_status' AND p.value = 'yes';
```

### Relationship queries

```sql
-- All current relationships for an entity
SELECT o2.name, l.type, l.confidence, l.source
FROM links l JOIN objects o2 ON l.to_id = o2.id
WHERE l.from_id = ? AND (l.valid_to IS NULL OR l.valid_to > datetime('now'));

-- Bidirectional relationships
SELECT
  CASE WHEN l.from_id = ? THEN o2.name ELSE o1.name END as related,
  l.type, l.confidence
FROM links l
JOIN objects o1 ON l.from_id = o1.id
JOIN objects o2 ON l.to_id = o2.id
WHERE l.from_id = ? OR l.to_id = ?;

-- Two-hop network (entity's relationships' relationships)
SELECT o3.name, l2.type, l2.confidence
FROM links l1
JOIN links l2 ON l1.to_id = l2.from_id
JOIN objects o3 ON l2.to_id = o3.id
WHERE l1.from_id = ? AND l1.from_id != o3.id;
```

### Graph queries

```sql
-- All events in a region (bounding box)
SELECT o.name, o.subtype, o.lat, o.lon, o.first_seen
FROM objects o
WHERE o.type = 'event'
AND abs(o.lat - ?) < ? AND abs(o.lon - ?) < ?
ORDER BY o.first_seen DESC;

-- Conflict actor network
SELECT
  o1.name as actor, o2.name as related_to,
  l.type as relationship, l.confidence
FROM links l
JOIN objects o1 ON l.from_id = o1.id
JOIN objects o2 ON l.to_id = o2.id
WHERE o1.type IN ('faction', 'country', 'organization')
AND o2.type IN ('faction', 'country', 'organization')
ORDER BY l.confidence DESC;

-- Entity with most relationships
SELECT o.name, o.type, COUNT(*) as link_count
FROM objects o
JOIN (
  SELECT from_id as oid FROM links
  UNION ALL
  SELECT to_id as oid FROM links
) combined ON o.id = combined.oid
GROUP BY o.id ORDER BY link_count DESC LIMIT 20;
```

### Changelog queries

```sql
-- Recent changes
SELECT c.action, c.table_name, c.field, c.old_value, c.new_value, c.source, c.agent, c.created_at
FROM changelog c ORDER BY c.created_at DESC LIMIT 50;

-- Changes to a specific object
SELECT action, field, old_value, new_value, source, created_at
FROM changelog WHERE object_id = ? ORDER BY created_at DESC;

-- Changes by source
SELECT action, COUNT(*) FROM changelog
WHERE source LIKE 'worldmonitor:%' GROUP BY action;
```

---

## Migration History

The ontology was migrated from the original flat schema:

1. `entities` (88 rows) -> `objects` (543+ rows, enriched with seeded data)
2. `relationships` (7 rows) -> `links` (254+ rows, expanded by automated extraction)
3. `brief_entities` -> `brief_objects` (204 links)
4. `conflict_actors` -> `links` (entity participated_in conflict, alignment as subtype)
5. Conflicts themselves became `event` type objects with subtype `conflict`

All original IDs were preserved during migration.

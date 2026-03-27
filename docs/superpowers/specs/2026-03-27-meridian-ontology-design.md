# Meridian Ontology - Intelligence Knowledge Graph

Replace intelligence.db's flat entity table with a proper ontology - typed objects, structured properties, temporal tracking, source provenance, and auto-ingestion from all data feeds. The goal: a research-grade knowledge base that grows autonomously from every brief, feed, and API response.

## Schema

### Core Object Table

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
CREATE INDEX idx_objects_type ON objects(type);
CREATE INDEX idx_objects_name ON objects(name);
CREATE INDEX idx_objects_country ON objects(country_code);
CREATE INDEX idx_objects_status ON objects(status);
CREATE INDEX idx_objects_geo ON objects(lat, lon);
```

### Object Types

| Type | Subtypes | Examples |
|------|----------|---------|
| `person` | head_of_state, commander, diplomat, minister, intelligence_officer, analyst | Putin, Zelensky, Erdogan |
| `organization` | government, military, intelligence_service, ngo, think_tank, media, corporation | CIA, NATO, RUSI, Wagner |
| `faction` | armed_group, coalition, paramilitary, militia, separatist | RSF, Houthis, Hamas, PKK |
| `country` | sovereign, disputed, territory, autonomous_region | Iran, Taiwan, Kosovo, Crimea |
| `location` | city, base, port, chokepoint, infrastructure, border_crossing | Strait of Hormuz, Incirlik, Sevastopol |
| `platform` | vessel, aircraft, weapons_system, satellite, missile | USS Gerald Ford, Tu-95, S-400, Shahed-136 |
| `unit` | army, navy, air_force, brigade, fleet, division, special_forces | 72nd Mechanized Brigade, Black Sea Fleet |
| `event` | strike, battle, election, agreement, deployment, incident, exercise, test | Isfahan strike, Grain corridor deal |
| `document` | brief, treaty, resolution, report, sanction_order | UNSCR 2231, Meridian Weekly Digest |

### Properties (Key-Value with Provenance)

```sql
CREATE TABLE properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'string',  -- string, number, boolean, json, date
    confidence REAL DEFAULT 1.0,
    source TEXT,                        -- brief:34, worldmonitor:acled, feed:nato
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,                 -- NULL = still current
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (object_id) REFERENCES objects(id)
);
CREATE INDEX idx_props_object ON properties(object_id);
CREATE INDEX idx_props_key ON properties(key);
CREATE INDEX idx_props_source ON properties(source);
```

Example properties per type:

**Person:** title, nationality, birth_year, party, portfolio, last_known_location
**Country:** population, gdp_usd, military_budget_usd, government_type, capital, nuclear_status, un_member
**Platform/vessel:** imo_number, mmsi, flag_state, vessel_type, operator, displacement_tonnes, last_position_lat, last_position_lon
**Platform/aircraft:** icao_hex, registration, aircraft_type, operator, military_branch
**Location:** population, elevation_m, facility_type, capacity
**Event:** date, end_date, casualties, weapons_used, damage_assessment

### Links (Typed Relationships with Provenance)

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
CREATE INDEX idx_links_from ON links(from_id);
CREATE INDEX idx_links_to ON links(to_id);
CREATE INDEX idx_links_type ON links(type);
CREATE INDEX idx_links_source ON links(source);
CREATE UNIQUE INDEX idx_links_dedup ON links(from_id, to_id, type, source);
```

Link types:

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
| `targets` | Targeting relationship | Strike targets Isfahan facility |
| `mediates` | Mediation role | Turkey mediates grain corridor |
| `trades_with` | Trade relationship | China trades_with Iran |
| `subsidiary_of` | Org hierarchy | IRGC-Navy subsidiary_of IRGC |
| `borders` | Geographic adjacency | Ukraine borders Russia |
| `controls` | Territorial control | Russia controls Crimea |
| `hosts` | Basing/hosting | Turkey hosts Incirlik |
| `produced_by` | Document authorship | Brief produced_by rf_russia_ukraine |

### Change Log (Full Audit Trail)

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
CREATE INDEX idx_changelog_object ON changelog(object_id);
CREATE INDEX idx_changelog_time ON changelog(created_at);
CREATE INDEX idx_changelog_source ON changelog(source);
```

### Brief-Object Linking (replaces brief_entities)

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

## Migration from Current Schema

The current entities, relationships, brief_entities tables migrate into the new schema:

1. `entities` -> `objects` (direct mapping, preserve IDs)
2. `relationships` -> `links` (map from_id/to_id, preserve types)
3. `brief_entities` -> `brief_objects`
4. `conflict_actors` -> `links` (entity participated_in conflict, with alignment as subtype)
5. Conflicts themselves become `event` type objects with subtype `conflict`

Migration script preserves all existing data and IDs.

## Auto-Ingestion Pipeline

### From WorldMonitor Feeds

Each WorldMonitor poll already fetches structured data. The ingestion layer extracts objects and links:

**Military flights** (every 15 min):
- Each flight -> `platform` object (type=aircraft, icao_hex, registration, operator)
- Position -> property update (last_position_lat/lon, last_seen)
- If near a watch zone -> `event` object (type=event, subtype=detection)
- Link: aircraft `operated_by` operator (org/country)

**ACLED conflict events** (every 45 min):
- Each event -> `event` object (type=event, subtype=battle/explosion/protest/etc)
- Actors -> `faction`/`organization` objects (upsert by name)
- Location -> `location` object (upsert by name + coordinates)
- Links: actor `participated_in` event, event `located_at` location

**AIS maritime data** (every 15 min):
- Each vessel -> `platform` object (type=vessel, mmsi, imo, flag_state)
- Position -> property update
- Disruptions -> `event` objects

**GPS jamming** (every 15 min):
- High-jamming zones -> `event` objects (type=event, subtype=jamming)
- Location derived from hex coordinates

**OREF alerts** (every 15 min):
- Each alert -> `event` object (type=event, subtype=missile_alert/rocket_alert)
- Location from alert data

**Thermal escalations** (every 45 min):
- Each cluster -> `event` object (type=event, subtype=thermal_anomaly)
- Location from centroid

**News digest** (every 3 hours):
- Articles -> entity extraction via Haiku (persons, orgs, locations mentioned)
- Upsert objects, create brief_objects links

**Bootstrap/economic data** (every 4 hours):
- Country economic indicators -> properties on country objects
- Energy prices -> properties on location objects (infrastructure)

### From Briefs

Every new brief triggers:
1. Entity extraction (existing entity-extract.ts pattern)
2. Relationship extraction (existing relationship_extract.py pattern)
3. Event extraction (NEW - identify events described in brief text)
4. Property updates (NEW - extract factual claims as properties)
5. Brief-object linking

### Ingestion Script

`scripts/agents/shared/ontology_ingest.py`:

```python
def ingest_worldmonitor_response(endpoint: str, data: dict, source: str) -> IngestResult:
    """Route WorldMonitor API response to the appropriate extractor."""

    if 'military-flights' in endpoint:
        return ingest_military_flights(data, source)
    elif 'acled-events' in endpoint or 'list-acled-events' in endpoint:
        return ingest_acled_events(data, source)
    elif 'ais-snapshot' in endpoint:
        return ingest_ais_data(data, source)
    elif 'gpsjam' in endpoint:
        return ingest_gps_jamming(data, source)
    elif 'oref-alerts' in endpoint:
        return ingest_oref_alerts(data, source)
    elif 'thermal' in endpoint:
        return ingest_thermal_events(data, source)
    elif 'bootstrap' in endpoint:
        return ingest_economic_data(data, source)
    elif 'news' in endpoint or 'digest' in endpoint:
        return ingest_news(data, source)
    ...

def ingest_brief(brief_id: int, text: str, agent: str) -> IngestResult:
    """Extract objects, links, and properties from a brief."""
    ...
```

Called from:
- `worldmonitor_poll.py` after each tier poll (passes raw API response)
- Brief publication pipeline (after any brief is written to DB)
- `three_hour_update.py` after fetching data
- Any script that fetches WorldMonitor data

### Upsert Logic

Objects are matched by:
1. **Exact ID** (if updating a known object)
2. **Name + type** (case-insensitive)
3. **Alias match** (check aliases JSON array)
4. **Identifier match** (ICAO hex for aircraft, MMSI for vessels, ISO code for countries)

If no match: create new object.
If match found: update properties, bump last_seen, log changes.

## Querying the Ontology

### Graph Traversal

```sql
-- All relationships for an entity
SELECT o2.name, l.type, l.confidence, l.source
FROM links l JOIN objects o2 ON l.to_id = o2.id
WHERE l.from_id = ? AND (l.valid_to IS NULL OR l.valid_to > datetime('now'));

-- Two-hop network (entity's relationships' relationships)
SELECT o3.name, l2.type
FROM links l1
JOIN links l2 ON l1.to_id = l2.from_id
JOIN objects o3 ON l2.to_id = o3.id
WHERE l1.from_id = ? AND l1.from_id != o3.id;

-- All events in a region (within radius)
SELECT o.name, o.subtype, o.lat, o.lon, o.first_seen
FROM objects o
WHERE o.type = 'event'
AND abs(o.lat - ?) < ? AND abs(o.lon - ?) < ?
ORDER BY o.first_seen DESC;

-- Entity timeline (all changes over time)
SELECT cl.action, cl.field, cl.old_value, cl.new_value, cl.created_at, cl.source
FROM changelog cl
WHERE cl.object_id = ?
ORDER BY cl.created_at;

-- Find connections between two entities
SELECT o_mid.name, l1.type, l2.type
FROM links l1
JOIN links l2 ON l1.to_id = l2.from_id
JOIN objects o_mid ON l1.to_id = o_mid.id
WHERE l1.from_id = ? AND l2.to_id = ?;
```

### Search

```sql
-- Full-text search across objects
SELECT id, name, type, subtype, description
FROM objects
WHERE name LIKE ? OR description LIKE ?
ORDER BY last_seen DESC;

-- Properties search (find all countries with nuclear capability)
SELECT o.name, p.value
FROM objects o JOIN properties p ON o.id = p.object_id
WHERE o.type = 'country' AND p.key = 'nuclear_status' AND p.value != 'none';
```

## Platform Integration

The Meridian platform gets new pages:

| Page | Content |
|------|---------|
| `/graph` | Interactive force-directed graph visualization |
| `/object/<id>` | Object dossier - all properties, links, timeline, briefs |
| `/search` | Search across all objects |
| `/events` | Recent events with map overlay |
| `/network/<id>` | Ego network visualization for an object |

The graph page uses d3-force or vis.js for interactive network visualization. Objects are nodes colored by type, links are edges colored by relationship type. Click to expand, filter by type/region/time.

## Build Order

1. **Schema migration** - Create new tables, migrate existing data, preserve IDs
2. **Ontology core** (`scripts/agents/shared/ontology.py`) - CRUD operations, upsert logic, graph queries
3. **WorldMonitor ingestors** - One function per data type (flights, ACLED, AIS, etc.)
4. **Brief ingestor** - Extract objects/links/events from brief text
5. **Wire into existing scripts** - worldmonitor_poll.py calls ingest after fetch
6. **Seed from WorldMonitor** - Bulk ingest from all cached data
7. **Platform graph page** - Interactive visualization
8. **Platform object dossier page** - Full object view

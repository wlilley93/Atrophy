# Meridian Eye - Living Architecture Reference

The intelligence platform at worldmonitor.atrophy.app. This document is the single source of truth for how Meridian works - its data flow, schema, cron schedule, MCP tools, and file locations.

Last updated: 2026-03-27

---

## Implementation Status

This document mixes three kinds of Meridian information. Treat them differently:

- **Shipped now**: channel APIs, chat/webhook routes, Montgomery cron/pipeline scripts, ontology/vector/search infrastructure, and the docs in this repo.
- **Implemented locally but not yet deployed**: the current Phase 1 globe-first Meridian UI work in `~/.atrophy/services/worldmonitor/` (full-screen globe shell, floating HUD, orbital descent, map entity support APIs).
- **Roadmap / target state**: cinematic briefings, unit figurines, dossier/chat UX, `/graph`, video export, and the later game-style systems described below unless a section explicitly says otherwise.

Counts and runtime state in this file are snapshots from March 27, 2026. The live ontology and article pipeline continue to mutate outside git.

---

## System Overview

```
                          worldmonitor.atrophy.app (Vercel)
                         +---------------------------------+
                         |  TypeScript + Preact + deck.gl   |
                         |  60+ Edge Functions              |
                         |  Upstash Redis (state)           |
                         +-------^-----------^--------------+
                                 |           |
                        channel_push    API reads
                                 |           |
    +----------------------------+-----------+-----------------------------+
    |                     Atrophy App (Electron)                           |
    |  +----------------+  +-------------+  +-----------+  +------------+ |
    |  | Cron Scheduler |  | Switchboard |  | MCP       |  | Agent      | |
    |  | (31 jobs)      |->| (routing)   |->| Registry  |  | Manager    | |
    |  +-------+--------+  +-------------+  +-----------+  +------------+ |
    |          |                                                           |
    |          v                                                           |
    |  +----------------------------------------------+                    |
    |  |           Python Scripts                      |                   |
    |  |  worldmonitor_poll.py  article_harvest.py     |                   |
    |  |  ontology_ingest.py    article_to_ontology.py |                   |
    |  |  research_context.py   vectorize_articles.py  |                   |
    |  |  dashboard_brief.py    flash_report.py        |                   |
    |  |  channel_push.py       + 20 more              |                   |
    |  +-------------------+---------------------------+                   |
    |                      |                                               |
    +----------------------|-----------------------------------------------+
                           v
    +----------------------------------------------+
    |          intelligence.db (SQLite)             |
    |  objects: 6,326  |  links: 7,218             |
    |  properties: 28,988  |  changelog: 24,681    |
    |  articles: 294  |  vectors: 5,059 docs       |
    +----------------------------------------------+
```

---

## Data Flow

### WorldMonitor -> Ontology -> Vectors -> Briefs -> Platform

1. **WorldMonitor polling** - `worldmonitor_poll.py` fetches 3 tiers of data (fast/medium/slow) from the WorldMonitor API
2. **Auto-ingestion** - `ontology_ingest.py` extracts objects, links, and properties from each API response
3. **Article harvesting** - `article_harvest.py` pulls from 7 RSS feeds every 4 hours; blocked sources get browser-scraped
4. **Article-to-ontology** - `article_to_ontology.py` extracts entities and relationships from harvested articles via Claude Haiku
5. **Vectorization** - `vectorize_articles.py` creates TF-IDF 384-dim embeddings for all articles and briefs
6. **Research context** - `research_context.py` assembles relevant articles + briefs + ontology objects for brief generation
7. **Brief generation** - Agent scripts produce briefs grounded in research context
8. **Channel push** - `channel_push.py` pushes briefing + map state to the platform API
9. **Platform renders** - Vercel site displays channel state, briefings, and live data layers

### Article Pipeline Detail

```
RSS Feeds (7 sources)                Browser Scraper (blocked sources)
  ICG, Atlantic Council,               Sources behind paywalls
  MEE, Al-Monitor, Carnegie,           or aggressive anti-bot
  Stimson, WotR, FP, FA
         |                                      |
         v                                      v
  article_harvest.py (every 4h) --------> articles table (294 articles)
                                                |
                                                v
                                    article_to_ontology.py
                                    (Haiku entity extraction)
                                                |
                                                v
                                    ontology: objects + links
                                                |
                                                v
                                    vectorize_articles.py
                                    (TF-IDF 384-dim embeddings)
                                                |
                                                v
                                    research_context.py
                                    (semantic search for briefs)
```

---

## Ontology Schema (intelligence.db)

Location: `~/.atrophy/agents/general_montgomery/data/intelligence.db`

### Tables

**`objects`** - 6,326 objects across 11 types

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| type | TEXT NOT NULL | Object type (see below) |
| subtype | TEXT | Further classification |
| name | TEXT NOT NULL | Primary name |
| aliases | TEXT | JSON array of alternate names |
| status | TEXT | active/inactive/destroyed/disputed |
| description | TEXT | Free-text description |
| lat | REAL | Primary latitude |
| lon | REAL | Primary longitude |
| country_code | TEXT | ISO 3166-1 alpha-2 |
| first_seen | TIMESTAMP | When first observed |
| last_seen | TIMESTAMP | When last updated |
| created_at | TIMESTAMP | Record creation |
| updated_at | TIMESTAMP | Record modification |

Object type distribution:

| Type | Count | Subtypes |
|------|-------|----------|
| location | 1,782 | city, base, port, chokepoint, infrastructure, border_crossing |
| organization | 1,519 | government, military, intelligence_service, ngo, think_tank, media, corporation |
| event | 1,017 | strike, battle, election, agreement, deployment, incident, exercise, detection, jamming, missile_alert, thermal_anomaly |
| document | 469 | brief, treaty, resolution, report, sanction_order |
| platform | 465 | vessel, aircraft, weapons_system, satellite, missile |
| person | 448 | head_of_state, commander, diplomat, minister, intelligence_officer, analyst |
| country | 263 | sovereign, disputed, territory, autonomous_region |
| faction | 184 | armed_group, coalition, paramilitary, militia, separatist |
| financial_instrument | - | currency, commodity, index, bond |
| region | - | geographic/political grouping |
| indicator | - | economic/security metric |

**`properties`** - 28,988 key-value pairs with provenance

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| object_id | INTEGER FK | References objects(id) |
| key | TEXT NOT NULL | Property name |
| value | TEXT NOT NULL | Property value |
| value_type | TEXT | string, number, boolean, json, date |
| confidence | REAL | 0.0-1.0 confidence score |
| source | TEXT | Provenance (e.g. worldmonitor:acled, brief:34, seed:restcountries) |
| valid_from | TIMESTAMP | When this value became true |
| valid_to | TIMESTAMP | NULL = still current |
| created_at | TIMESTAMP | Record creation |

**`links`** - 7,218 typed relationships with provenance

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| from_id | INTEGER FK | Source object |
| to_id | INTEGER FK | Target object |
| type | TEXT NOT NULL | Relationship type (see below) |
| subtype | TEXT | Further classification |
| description | TEXT | Contextual description |
| confidence | REAL | 0.0-1.0 |
| source | TEXT | Provenance |
| valid_from | TIMESTAMP | When relationship started |
| valid_to | TIMESTAMP | NULL = still active |
| created_at | TIMESTAMP | Record creation |

Link types (20): leads, commands, member_of, located_at, operates, deployed_to, allied_with, opposes, funds, arms, sanctions, participated_in, targets, mediates, trades_with, subsidiary_of, borders, controls, hosts, produced_by

**`changelog`** - 24,681 audit trail entries

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| object_id | INTEGER | Referenced object |
| table_name | TEXT NOT NULL | objects, properties, links |
| record_id | INTEGER NOT NULL | Row ID in target table |
| action | TEXT NOT NULL | create, update, delete, merge |
| field | TEXT | Column that changed |
| old_value | TEXT | Previous value |
| new_value | TEXT | New value |
| source | TEXT | What triggered the change |
| agent | TEXT | Which agent made the change |
| created_at | TIMESTAMP | When the change occurred |

**`brief_objects`** - Brief-to-object linking with relevance

| Column | Type | Description |
|--------|------|-------------|
| brief_id | INTEGER FK | References briefs(id) |
| object_id | INTEGER FK | References objects(id) |
| mention_count | INTEGER | How many times mentioned |
| relevance | TEXT | mentioned, primary_subject, source |

**`articles`** - 294 harvested articles

Stores full text, source, URL, publication date, and extracted metadata from RSS feeds and browser scraping.

**`vectors`** - 5,059 TF-IDF embeddings (384-dim)

Covers all articles, briefs, and key ontology objects. Used by `research_context.py` for semantic retrieval during brief generation.

### Indexes

```sql
CREATE INDEX idx_objects_type ON objects(type);
CREATE INDEX idx_objects_name ON objects(name);
CREATE INDEX idx_objects_country ON objects(country_code);
CREATE INDEX idx_objects_status ON objects(status);
CREATE INDEX idx_objects_geo ON objects(lat, lon);
CREATE INDEX idx_props_object ON properties(object_id);
CREATE INDEX idx_props_key ON properties(key);
CREATE INDEX idx_props_source ON properties(source);
CREATE INDEX idx_links_from ON links(from_id);
CREATE INDEX idx_links_to ON links(to_id);
CREATE INDEX idx_links_type ON links(type);
CREATE INDEX idx_links_source ON links(source);
CREATE UNIQUE INDEX idx_links_dedup ON links(from_id, to_id, type, source);
CREATE INDEX idx_changelog_object ON changelog(object_id);
CREATE INDEX idx_changelog_time ON changelog(created_at);
CREATE INDEX idx_changelog_source ON changelog(source);
```

---

## Channel System

### Concept

Each defence org agent gets a channel - a curated view of the intelligence picture. The site opens on Montgomery's combined picture by default. Channels hold map state, briefings, alert levels, and feed filters.

### 10 Agent Channels

| Agent | Channel | Region Focus |
|-------|---------|-------------|
| general_montgomery | Editor-in-chief | Global combined picture |
| rf_russia_ukraine | Russia-Ukraine | Frontline map, ACLED, thermal, flights |
| rf_gulf_iran_israel | Gulf/Iran/Israel | Maritime (Hormuz, Red Sea), OREF, strikes |
| rf_european_security | European Security | NATO posture, Baltic/Nordic, energy |
| rf_indo_pacific | Indo-Pacific | South China Sea, Taiwan Strait, flights |
| rf_uk_defence | UK Defence | Procurement, fleet disposition |
| rf_eu_nordic_monitor | EU/Nordic | EU policy, Nordic security |
| economic_io | Economic Intelligence | Energy, trade, BIS rates, sanctions |
| sigint_analyst | SIGINT | Military flights, GPS jamming, AIS dark |
| librarian | Entity Taxonomy | Entity network graphs, brief-entity links |

### Channel State Structure

Stored in Upstash Redis under key `channel:<agent_name>`:

```json
{
  "agent": "rf_russia_ukraine",
  "display_name": "Russia-Ukraine",
  "updated_at": "2026-03-27T14:30:00Z",
  "alert_level": "normal|elevated|critical",
  "briefing": {
    "title": "...",
    "summary": "One-line summary",
    "body_md": "Full markdown analysis",
    "sources": ["ACLED", "WorldMonitor thermal"]
  },
  "map": {
    "center": [48.5, 35.0],
    "zoom": 6,
    "bearing": 0,
    "pitch": 30,
    "layers": ["military-flights", "acled-events"],
    "markers": [{ "lat": 46.6, "lon": 32.6, "label": "Kherson", "type": "event" }],
    "regions": ["UA", "RU"]
  },
  "feeds": {
    "categories": ["conflict", "military"],
    "keywords": ["ukraine", "russia"]
  }
}
```

### Push Mechanism

Agent scripts push state via `channel_push.py`:

```python
from channel_push import push_channel_state
push_channel_state(
    agent="rf_russia_ukraine",
    briefing={"title": "...", "summary": "...", "body_md": "...", "sources": [...]},
    map={"center": [48.5, 35.0], "zoom": 6, "layers": ["acled-events"]},
    alert_level="elevated"
)
```

The `CHANNEL_API_KEY` environment variable is passed to all cron jobs by the runner.

### Platform API Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `api/channels/list` | GET | List all channels with metadata |
| `api/channels/[name]` | GET | Get full channel state |
| `api/channels/[name]` | PUT | Update full channel state (auth) |
| `api/channels/[name]/briefing` | PUT | Update briefing only (auth) |
| `api/channels/[name]/map` | PUT | Update map state only (auth) |
| `api/commissions` | GET/POST | Commission portal |
| `api/commissions/[id]` | PUT | Update commission status (auth) |

### Live Data Layer

70+ channel layer names mapped to WorldMonitor internal data layer IDs. Agents control which layers appear on their channel via the `map.layers` array:

- `military-flights` - WorldMonitor military aviation layer
- `acled-events` - ACLED conflict events
- `ais-vessels` - AIS maritime tracking
- `gps-jamming` - GPS jamming zones
- `oref-alerts` - Israeli alert system
- `thermal-escalations` - Thermal/fire data
- `energy-prices` - Economic energy layer
- `trade-flows` - Trade restriction data
- Plus 60+ more mapped to WorldMonitor's data sources

---

## Intelligence Capabilities (14 Systems)

| # | System | Script(s) | Cadence | Description |
|---|--------|-----------|---------|-------------|
| 1 | Prediction Ledger | `prediction_extract.py`, `prediction_review.py` | Extract on publish, review monthly | Extracts predictions from briefs, tracks accuracy over 30-day review cycles |
| 2 | Cross-Agent Synthesis | `cross_agent_synthesis.py` | Nightly 02:00 | Reads all channels, identifies convergence patterns across domains |
| 3 | Source Health Dashboard | `source_health.py` | Every 6 hours | Monitors 39 sources (RSS, APIs, WorldMonitor endpoints) for availability and freshness |
| 4 | Entity Resolution | `entity_resolve.py` | On demand | Haiku-driven deduplication, alias population, brief-entity linking |
| 5 | Temporal Situation Tracking | `timeline_update.py` | On brief publish | Timeline entries per active conflict with trajectory assessment (escalating/stable/de-escalating) |
| 6 | Automated Relationship Extraction | `relationship_extract.py` | Hourly | Extracts typed relationships from briefs via Claude Haiku |
| 7 | Commission Portal | `commission_sync.py` | Every 30 min | Two-way sync between intelligence.db commissions table and platform |
| 8 | Systematic Red Team Review | `red_team_review.py` | On high-priority briefs | Four-part adversarial challenge: evidential, alternative, historical, verdict |
| 9 | Live Data Layer | Built into platform | Continuous | Channel-driven activation of 70+ WorldMonitor data layers |
| 10 | Briefing Audio | `generate_brief_audio.py` | On brief publish | ElevenLabs TTS briefing narration |
| 11 | Agent Performance Metrics | `agent_metrics.py` | Monthly | Review across 7 categories |
| 12 | Geofencing | `geofence_check.py` | Every 15 min | 8 watch zones with haversine distance alerting |
| 13 | Structured Intelligence Products | `product_templates.py` | Built into brief pipeline | 8 templates: SITREP, FLASH, WARNING, INTSUM, PROFILE, WEEKLY_DIGEST, ASSESSMENT, SYNTHESIS |
| 14 | Multi-Source Verification | `verify_brief.py` | Post-brief generation | Cross-reference claims against multiple sources, assign corroboration score |

---

## Cron Schedule (31 Jobs)

### Montgomery (general_montgomery)

| Job | Cadence | Script | Description |
|-----|---------|--------|-------------|
| worldmonitor_fast | Every 15 min | `worldmonitor_poll.py --tier fast` | Military flights, OREF, GPS jamming, AIS |
| worldmonitor_medium | Every 45 min | `worldmonitor_poll.py --tier medium` | ACLED, thermal, news |
| worldmonitor_slow | Every 4 hours | `worldmonitor_poll.py --tier slow` | Economic, country data |
| dashboard_refresh | Every 15 min | `dashboard_brief.py --mode refresh` | Refresh dashboard state |
| dashboard_brief | Every 4 hours | `dashboard_brief.py --mode send` | Generate and push full briefing |
| article_harvest | Every 4 hours | `article_harvest.py` | Pull from 7 RSS feeds + browser scrape |
| vectorize | Every 4 hours | `vectorize_articles.py` | TF-IDF embedding of new articles/briefs |
| ontology_expand | Daily 03:00 | `ontology_expand.py` | Haiku-driven ontology growth and enrichment |
| ship_track_alert | Every 30 min | `ship_track_alert.py` | Maritime vessel alerting |
| flash_report | Every 15 min | `flash_report.py` | Detect and publish flash events |
| weekly_digest | Mon 07:00 | `weekly_digest.py` | Weekly intelligence digest |
| weekly_conflicts | Mon 08:00 | `weekly_conflicts.py` | Weekly conflict summary |
| parliamentary_monitor | Weekdays 08:00 | `parliamentary_monitor.py` | UK parliament monitoring |
| competitor_scan | Weekdays 09:00 | `competitor_scan.py` | Scan competitor intelligence products |
| process_audit | First Mon 10:00 | `process_audit.py` | Monthly process review |

### Shared Intelligence Scripts

| Job | Cadence | Script | Description |
|-----|---------|--------|-------------|
| source_health | Every 6 hours | `source_health.py` | Monitor 39 source endpoints |
| cross_agent_synthesis | Daily 02:00 | `cross_agent_synthesis.py` | Cross-domain convergence report |
| commission_sync | Every 30 min | `commission_sync.py` | Two-way commission DB/platform sync |
| geofence_check | Every 15 min | `geofence_check.py` | Watch zone alerting |
| relationship_extract | Hourly | `relationship_extract.py` | Extract relationships from new briefs |
| prediction_review | Monthly | `prediction_review.py` | Review prediction accuracy |
| agent_metrics | Monthly | `agent_metrics.py` | Agent performance review |
| entity_enrichment | Daily 04:00 | `entity_enrichment.py` | Enrich sparse ontology objects |

### Research Fellows

| Agent | Cadence | Script | Description |
|-------|---------|--------|-------------|
| rf_uk_defence | Thursday 06:00 | `weekly_posture.py` | UK defence posture assessment |
| rf_european_security | Thursday 06:00 | `weekly_security.py` | European security roundup |
| rf_russia_ukraine | Weekdays 06:30 | `daily_battlefield.py` | Daily battlefield update |
| rf_gulf_iran_israel | 1st of month 07:00 | `monthly_paper.py` | Monthly regional paper |
| rf_indo_pacific | Friday 06:00 | `weekly_indopacific.py` | Weekly Indo-Pacific roundup |

### Other Agents

| Agent | Cadence | Script | Description |
|-------|---------|--------|-------------|
| librarian | Hourly | `entity_resolve.py` | Entity resolution and deduplication |
| sigint_analyst | Every 15 min | `sigint_cycle.py` | SIGINT collection cycle |
| economic_io | Every 4 hours | `economic_scan.py` | Economic indicator monitoring |

---

## MCP Ontology Tools

7 tools exposed via the `ontology` action group in `mcp/memory_server.py`. Available to any agent with `memory` in their MCP include list.

| Tool | Action | Description |
|------|--------|-------------|
| Search | `ontology.search` | Full-text search across objects by name, type, country, or free query |
| Get Object | `ontology.get_object` | Full dossier for an object - all properties, links, changelog, related briefs |
| Get Network | `ontology.get_network` | Ego network for an object - all first-hop relationships with targets |
| Find Connections | `ontology.find_connections` | Path-finding between two objects (1-2 hops) |
| Recent Events | `ontology.recent_events` | Latest events by type, region, or time window |
| Country Profile | `ontology.country_profile` | Full country dossier - government, economy, military, relationships |
| Statistics | `ontology.statistics` | Ontology counts by type, link counts, total properties, coverage metrics |

These tools query `intelligence.db` directly. They are read-only - writes to the ontology happen through Python scripts (ontology_ingest.py, article_to_ontology.py, entity_resolve.py, etc.).

---

## Auto-Ingestion Pipeline

### WorldMonitor Ingestors (ontology_ingest.py)

8 typed ingestors in `ontology_ingest.py` process WorldMonitor API responses:

| Ingestor | Source | Creates |
|----------|--------|---------|
| `ingest_military_flights` | Military flights API | platform (aircraft) objects + position properties |
| `ingest_acled_events` | ACLED conflict data | event objects + faction/location objects + participated_in links |
| `ingest_ais_data` | AIS maritime tracking | platform (vessel) objects + position properties |
| `ingest_gps_jamming` | GPS jamming zones | event (jamming) objects + location |
| `ingest_oref_alerts` | Israeli alert system | event (missile_alert/rocket_alert) objects |
| `ingest_thermal_events` | Thermal escalation data | event (thermal_anomaly) objects |
| `ingest_news` | News digest | entity extraction via Haiku + brief_objects links |
| `ingest_economic_data` | Economic/bootstrap data | property updates on country objects |

Called from `worldmonitor_poll.py` after each tier poll.

### Article Ingestors (article_to_ontology.py)

Processes harvested articles through Claude Haiku:
1. Extract named entities (persons, orgs, locations, events)
2. Match against existing ontology objects (upsert logic)
3. Extract relationships between entities
4. Create brief_objects links
5. Log all changes to changelog

### Upsert Logic

Objects matched by (in order):
1. Exact ID (if updating known object)
2. Name + type (case-insensitive)
3. Alias match (check aliases JSON array)
4. Identifier match (ICAO hex for aircraft, MMSI for vessels, ISO code for countries)

No match: create new object. Match found: update properties, bump last_seen, log changes.

---

## File Locations

### Databases
- `~/.atrophy/agents/general_montgomery/data/intelligence.db` - Ontology, articles, vectors

### Platform
- `~/.atrophy/services/worldmonitor/` - Vercel fork repo (GitHub: wlilley93/worldmonitor)
- Domain: worldmonitor.atrophy.app

### Personal Scripts (not in git)
Located at `~/.atrophy/scripts/agents/`:

**Shared (`agents/shared/`):**
- `channel_push.py` - Push channel state to platform API
- `source_health.py` - Source availability monitoring
- `verify_brief.py` - Multi-source verification
- `red_team_review.py` - Adversarial brief review
- `product_templates.py` - Structured intelligence templates
- `timeline_update.py` - Temporal situation tracking
- `cross_agent_synthesis.py` - Cross-domain convergence
- `prediction_extract.py` - Prediction extraction from briefs
- `prediction_review.py` - Prediction accuracy review
- `agent_metrics.py` - Agent performance metrics
- `generate_brief_audio.py` - ElevenLabs TTS briefing audio
- `geofence_check.py` - Watch zone haversine alerting
- `commission_sync.py` - Commission two-way sync
- `ontology.py` - Ontology CRUD and graph queries
- `ontology_migrate.py` - Schema migration
- `ontology_ingest.py` - WorldMonitor auto-ingestion
- `article_harvest.py` - RSS feed harvesting
- `article_to_ontology.py` - Article entity extraction
- `vectorize_articles.py` - TF-IDF vectorization
- `research_context.py` - Semantic retrieval for brief generation
- `ontology_expand.py` - Haiku-driven ontology enrichment
- `entity_enrichment.py` - Sparse object enrichment

**Librarian (`agents/librarian/`):**
- `entity_resolve.py` - Deduplication and alias population
- `relationship_extract.py` - Typed relationship extraction from briefs

### Config
- `~/.atrophy/.env` - Contains `CHANNEL_API_KEY`, API keys
- Agent manifest at `~/.atrophy/agents/general_montgomery/data/agent.json` - channels, mcp, jobs, router, org

### Documentation
- `docs/meridian-platform.md` - Platform reference
- `docs/ontology-reference.md` - Ontology reference
- `docs/superpowers/specs/2026-03-27-worldmonitor-integration-design.md` - Platform design spec
- `docs/superpowers/specs/2026-03-27-meridian-ontology-design.md` - Ontology schema spec
- `docs/superpowers/specs/2026-03-27-meridian-improvements-spec.md` - 14 capability specs
- `docs/superpowers/specs/2026-03-27-meridian-site-redesign.md` - Site redesign vision (1,000+ lines, not yet built)

---

## Platform Infrastructure

### Vercel Deployment

- Fork of open-source WorldMonitor (koala73/worldmonitor)
- TypeScript + Preact frontend, deck.gl/MapLibre/globe.gl maps
- 60+ Edge Functions for data fetching and caching
- Upstash Redis for channel state, briefings, commissions
- Auth via `X-Channel-Key` header (shared secret)
- Domain: worldmonitor.atrophy.app (CNAME via GoDaddy -> Vercel)
- Auto-deploys from GitHub on push

### Frontend Modifications (added to fork)

1. Channel switcher sidebar - agent cards with name, region, alert level, last updated
2. Briefing panel - slide-out with rendered markdown, sources, timestamp
3. State-driven rendering - on channel switch, animate globe to camera position, toggle layers
4. Default channel - Montgomery's combined view on first visit
5. URL routing - `worldmonitor.atrophy.app/channel/<agent_name>` deep-links

### Commission Portal

1. Commission submitted via platform API or auto-filed by cross-agent synthesis
2. Stored in both `commissions` table (intelligence.db) and Upstash Redis
3. Two-way sync via `commission_sync.py` (every 30 min)
4. Assigned agent processes and produces output
5. Output synced back to platform

---

## Vector Search and Research Context

### TF-IDF Vectorization

- 384-dimensional TF-IDF vectors
- 5,059 documents vectorized (articles + briefs + key ontology descriptions)
- `vectorize_articles.py` runs every 4 hours to process new content
- Vectors stored in intelligence.db

### Research Context Assembly

`research_context.py` provides semantic retrieval for brief generation:

1. Takes a query/topic and retrieves the top-k most relevant documents
2. Combines results from articles, prior briefs, and ontology objects
3. Assembles a research context block that agents use as grounding material
4. Enables briefs to cite specific articles and reference prior analysis

---

## Site Redesign (Specced, Not Yet Built)

Full spec at `docs/superpowers/specs/2026-03-27-meridian-site-redesign.md` (1,051 lines).

Vision: transform the platform from a dashboard into an interactive intelligence environment. Key features:

- **Orbital descent entry** - satellite view dives through atmosphere on load
- **Game-style campaign map** - dark 3D globe with free camera, WASD navigation
- **Cinematic briefings** - letterbox bars, scripted camera sweeps, unit animations, voice narration
- **3D unit figurines** - military units as clickable miniatures on deployment locations
- **Fog of war** - animated fog over areas with poor ontology coverage
- **Territory control** - faction-colored regions from ontology `controls` links
- **Convergence rings** - visual signal overlap detection
- **Connection lines on hover** - ontology relationships as colored arcs
- **Entity glow** - network centrality as luminosity
- **Time scrub** - slider to replay historical positions
- **Chat interface** - click any entity to converse with the relevant analyst
- **Briefing export** - headless browser renders cinematics as MP4

Color temperature reflects global threat level (cool blues for NORMAL, amber for ELEVATED, red for CRITICAL).

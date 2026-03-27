# Meridian Intelligence Platform - Improvement Spec

14 improvements to the Meridian system across agents, knowledge graph, platform, and delivery.

**Platform home:** `meridian.atrophy.app` (currently `worldmonitor.atrophy.app` - to be renamed)
The platform is Meridian's home for ALL visual output - not just maps. Briefs, timelines, entity graphs, performance metrics, commission portal, audio briefings, health dashboards all live here.

---

## Dependency Order

```
Foundation (do first):
  6. Relationship Extraction  ─┐
  4. Entity Resolution        ─┤── Knowledge graph must work before anything references it
  3. Source Health Dashboard   ─┘── Agents need to know source status

Core intelligence:
  5. Temporal Tracking         ─┐
  13. Structured Products      ─┤── Brief quality infrastructure
  14. Verification Pipeline    ─┤
  8. Red Team Review           ─┘

Synthesis and analysis:
  2. Cross-Agent Synthesis     ── Needs working graph + quality briefs
  1. Prediction Ledger         ── Needs structured briefs to extract predictions from
  11. Performance Metrics      ── Needs prediction ledger + brief metadata

Platform features:
  9. Live Data Layer           ── Independent, enhances map
  7. Commission Portal         ── Independent, new workflow
  10. Briefing Audio           ── Independent, enhances delivery
  12. Geofencing               ── Needs live data layer
```

## Build Waves

### Wave 1: Knowledge Foundation (tasks 6, 4, 3)

**6. Automated Relationship Extraction**
- Run `relationship_extract.py` against all 34 existing briefs
- Register as librarian cron job (every 30 min)
- Target: 200+ relationships from existing briefs
- **Where:** Atrophy repo (script exists, just needs running + cron registration)

**4. Entity Resolution and Linking**
- Haiku-driven deduplication pass over 123 entities
- Merge duplicates, populate aliases field
- Add `brief_entities` join table to intelligence.db schema
- Auto-scan briefs for entity mentions, populate join table
- **Where:** Atrophy repo (new script + schema migration)

**3. Source Health Dashboard**
- New script: `scripts/agents/shared/source_health.py`
- Pings all data sources every 6 hours: RSS feeds, WorldMonitor endpoints, API endpoints
- Records HTTP status, response size, freshness to `source_health` table in intelligence.db
- Publishes health matrix to Meridian platform via channel push or dedicated API route
- **Where:** Atrophy repo (script) + Meridian platform (health page)

### Wave 2: Brief Quality (tasks 13, 14, 8, 5)

**13. Structured Intelligence Products**
- Define product templates in a config file: SITREP, INTSUM, WARNING, PROFILE, WEEKLY_DIGEST, FLASH
- Each template has: required fields, structure, formatting rules
- Agent system prompts updated to use templates when generating briefs
- Briefs table gets a `product_type` column
- Meridian platform renders each type with distinct visual treatment
- **Where:** Atrophy repo (templates, prompts, schema) + Meridian platform (renderers)

**14. Multi-Source Verification Pipeline**
- Post-processing step after brief generation
- Cross-reference key claims against: ACLED data, OSINT Telegram feed, news digest, WorldMonitor cache
- Assign corroboration score: 0 (unverified) to 3+ (multi-source confirmed)
- Briefs get a `verification` field: score, sources checked, corroborating sources found
- **Where:** Atrophy repo (new verification script called after brief generation)

**8. Systematic Red Team Review**
- High-priority briefs (FLASH, WEEKLY_DIGEST) auto-routed to red_team agent
- Red team runs adversarial prompts: alternative explanations, bias check, source quality
- Appends confidence assessment section to the brief
- Brief published only after red team review (or after 10 min timeout)
- **Where:** Atrophy repo (red team workflow in brief pipeline)

**5. Temporal Situation Tracking**
- New `situation_timeline` table: conflict_slug, date, assessment (escalating/stable/de-escalating/crisis), summary, agent, brief_id
- Weekly digest writes a timeline entry per active conflict
- Flash reports write timeline entries marked as events
- Meridian platform: timeline view per conflict showing trajectory over weeks/months
- **Where:** Atrophy repo (schema, script updates) + Meridian platform (timeline component)

### Wave 3: Synthesis (tasks 2, 1, 11)

**2. Cross-Agent Synthesis Engine**
- Nightly job (02:00): reads all channels' latest briefings + recent briefs from intelligence.db
- Uses Claude Sonnet to identify convergence patterns across domains
- Outputs: convergence report highlighting cross-domain signals
- Published as a SYNTHESIS product type on Montgomery's channel
- Example: "SIGINT detected increased military flights over Black Sea (sigint_analyst) coinciding with thermal signatures near Crimea bridge (rf_russia_ukraine) and energy price spike (economic_io)"
- **Where:** Atrophy repo (new synthesis script)

**1. Prediction Ledger**
- Extract forward-looking statements from briefs using Haiku
- Store in `assessment_outcomes` table (already exists, schema ready)
- 30-day auto-review: Haiku re-reads the prediction against current data, scores CORRECT/INCORRECT/PARTIAL/PENDING
- Publish accuracy dashboard on Meridian platform: per-agent, per-domain, per-conflict
- Backfill from all 34 existing briefs
- **Where:** Atrophy repo (extraction + review scripts) + Meridian platform (accuracy page)

**11. Agent Performance Metrics**
- Track per agent: brief count, average source count, prediction accuracy, commission response time, data freshness at brief time, entity coverage breadth
- Monthly summary generated by chief_of_staff agent
- Published on Meridian platform as PERFORMANCE product type
- Montgomery uses this for prompt revision decisions
- **Where:** Atrophy repo (metrics collection script) + Meridian platform (metrics page)

### Wave 4: Platform Features (tasks 9, 7, 10, 12)

**9. Live Data Layer**
- Meridian platform frontend polls WorldMonitor API endpoints directly
- Layers: military flights (15s refresh), ACLED events (5min), thermal (5min), GPS jamming (1min), AIS vessels (30s)
- Channel state controls which layers are visible and camera position
- Data is live, not snapshots from cron runs
- **Where:** Meridian platform fork (frontend polling + deck.gl layers)

**7. Commission Portal**
- New page on Meridian platform: `/commissions`
- Form: question text, priority (routine/priority/urgent), domain tags
- Submits to `/api/commissions` route which writes to intelligence.db commissions table
- Commission dispatcher agent (already exists) routes to appropriate RF agent
- Response published as a brief on the platform, linked back to the commission
- Requester sees status: submitted -> assigned -> in_progress -> published
- Auth: same X-Channel-Key or a separate commission key
- **Where:** Meridian platform fork (page + API routes) + Atrophy repo (commission dispatcher updates)

**10. Briefing Audio**
- After a brief is published, generate TTS audio using the authoring agent's ElevenLabs voice
- Store audio file (MP3) - either locally and serve via API, or upload to a CDN
- Meridian platform: "Listen to briefing" button on each brief page, audio player
- Telegram delivery: send as voice message for morning briefs and flash reports
- Montgomery's voice for his channel, distinct voices for other agents if configured
- **Where:** Atrophy repo (TTS generation script) + Meridian platform (audio player) + Telegram daemon update

**12. Geofencing and Alerting**
- Define watch zones in intelligence.db: name, geometry (center + radius or polygon), alert threshold, assigned agent
- Initial zones: Strait of Hormuz (50nm), Ukraine contact line (20km buffer), Taiwan Strait (50nm), Suez Canal (20nm), Baltic approaches (30nm)
- SIGINT cycle and WorldMonitor poll check events against zones
- Event inside zone: immediate flash report trigger, Telegram alert, channel goes critical, marker placed
- Cooldown period (1 hour) to prevent alert storms
- **Where:** Atrophy repo (geofence check in existing scripts) + schema for zones

---

## Platform Pages (Meridian site)

The Meridian platform at `meridian.atrophy.app` becomes a full intelligence product:

| Page | Content |
|------|---------|
| `/` | Montgomery's current situation picture (map + briefing) |
| `/channels` | Channel switcher with all agent views |
| `/channel/<name>` | Individual agent's map + briefing |
| `/meridian` | Brief index - all published intelligence products |
| `/meridian/brief/<id>` | Individual brief with full text, entity links, verification score |
| `/timeline/<conflict>` | Temporal situation tracker per conflict |
| `/graph` | Interactive entity-relationship knowledge graph |
| `/health` | Source health dashboard - red/amber/green matrix |
| `/accuracy` | Prediction ledger - accuracy scores per agent/domain |
| `/metrics` | Agent performance metrics dashboard |
| `/commissions` | Intelligence commission portal |

---

## Schema Additions to intelligence.db

```sql
-- Brief-entity linking (Wave 1)
CREATE TABLE brief_entities (
    brief_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    mention_count INTEGER DEFAULT 1,
    PRIMARY KEY (brief_id, entity_id),
    FOREIGN KEY (brief_id) REFERENCES briefs(id),
    FOREIGN KEY (entity_id) REFERENCES entities(id)
);

-- Source health (Wave 1)
CREATE TABLE source_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    http_status INTEGER,
    response_bytes INTEGER,
    is_fresh BOOLEAN,
    error_message TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Situation timeline (Wave 2)
CREATE TABLE situation_timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conflict_slug TEXT NOT NULL,
    date DATE NOT NULL,
    assessment TEXT NOT NULL CHECK(assessment IN ('escalating','stable','de-escalating','crisis')),
    summary TEXT,
    key_events TEXT,
    agent TEXT,
    brief_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (brief_id) REFERENCES briefs(id)
);

-- Geofence zones (Wave 4)
CREATE TABLE watch_zones (
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

-- Geofence alert log (Wave 4)
CREATE TABLE zone_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id INTEGER NOT NULL,
    event_type TEXT,
    event_data TEXT,
    source TEXT,
    alerted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (zone_id) REFERENCES watch_zones(id)
);

-- Add columns to briefs table (Wave 2)
ALTER TABLE briefs ADD COLUMN product_type TEXT DEFAULT 'brief';
ALTER TABLE briefs ADD COLUMN verification_score INTEGER DEFAULT 0;
ALTER TABLE briefs ADD COLUMN verification_details TEXT;
ALTER TABLE briefs ADD COLUMN red_team_review TEXT;
ALTER TABLE briefs ADD COLUMN audio_url TEXT;
```

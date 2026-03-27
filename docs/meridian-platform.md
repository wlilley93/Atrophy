# Meridian Intelligence Platform

The defence org's visual intelligence platform, deployed at [worldmonitor.atrophy.app](https://worldmonitor.atrophy.app).

Meridian is a fork of the open-source WorldMonitor project, rebranded as MERIDIAN - Defence Intelligence. It provides a curated newsroom - not a raw dashboard. Each agent in the defence org gets a channel with a map view and analytical briefing. The platform is backed by a knowledge graph (the ontology) in `intelligence.db`.

---

## Architecture

### Infrastructure

| Component | Technology | Notes |
|-----------|-----------|-------|
| **Hosting** | Vercel | 60+ Edge Functions, automatic deploys from GitHub |
| **State** | Upstash Redis | Channel state, briefings, commission data |
| **Frontend** | TypeScript + Preact | Vanilla TS, no framework beyond Preact for UI components |
| **Maps** | deck.gl + MapLibre GL + globe.gl | Dual engine: 3D globe and 2D map |
| **Domain** | worldmonitor.atrophy.app | CNAME via GoDaddy -> Vercel |
| **Auth** | X-Channel-Key header | Shared secret in CHANNEL_API_KEY env var |

### Repos

- **Fork repo:** `~/.atrophy/services/worldmonitor/` (GitHub: `wlilley93/worldmonitor`)
- **Upstream:** `koala73/worldmonitor` (open-source intelligence dashboard)
- **Atrophy repo:** Agent scripts that push state to the platform

### Data flow

```
WorldMonitor feeds (435+ news, 45 data layers)
  -> WorldMonitor Edge Functions (fetch, cache, serve)
  -> Frontend renders map + feeds

Agent cron jobs (Atrophy app)
  -> Produce intelligence (briefs, assessments, digests)
  -> Push channel state to Vercel API (channel_push.py)
  -> Frontend renders channels + briefings

Ontology (intelligence.db)
  -> Auto-ingestion from WorldMonitor feeds
  -> Seeding from external APIs (REST Countries, World Bank)
  -> Brief entity extraction
  -> Synced to platform for graph visualization
```

---

## Channel System

### Concept

Each defence org agent gets a channel - a curated view of the intelligence picture. The site opens on Montgomery's channel: a dark globe, current alert level, his synthesis of what matters. A sidebar shows agent channels as compact cards. Clicking a channel rotates the globe to that agent's region, activates their layers, shows their markers and briefing.

This is a newsroom, not a dashboard. The map serves the narrative. Agents show you what they want you to see - not everything at once.

### Channel state structure

Stored in Upstash Redis under key `channel:<agent_name>`:

```json
{
  "agent": "rf_russia_ukraine",
  "display_name": "Russia-Ukraine",
  "updated_at": "2026-03-27T14:30:00Z",
  "alert_level": "normal|elevated|critical",
  "briefing": {
    "title": "Kherson axis pressure building",
    "summary": "One-line summary...",
    "body_md": "Full markdown analysis...",
    "sources": ["ACLED", "WorldMonitor thermal"]
  },
  "map": {
    "center": [48.5, 35.0],
    "zoom": 6,
    "bearing": 0,
    "pitch": 30,
    "layers": ["military-flights", "acled-events"],
    "markers": [
      { "lat": 46.6, "lon": 32.6, "label": "Kherson", "type": "event", "detail": "..." }
    ],
    "regions": ["UA", "RU"]
  },
  "feeds": {
    "categories": ["conflict", "military"],
    "keywords": ["ukraine", "russia"]
  }
}
```

### Agent channels

| Agent | Channel | Region focus |
|-------|---------|-------------|
| general_montgomery | Editor-in-chief | Global combined picture |
| rf_russia_ukraine | Russia-Ukraine | Frontline map, ACLED, thermal, flights |
| rf_gulf_iran_israel | Gulf/Iran/Israel | Maritime (Hormuz, Red Sea), OREF, strikes |
| rf_european_security | European security | NATO posture, Baltic/Nordic, energy |
| rf_indo_pacific | Indo-Pacific | South China Sea, Taiwan Strait, flights |
| rf_uk_defence | UK defence | Procurement, fleet disposition |
| rf_eu_nordic_monitor | EU/Nordic | EU policy, Nordic security |
| economic_io | Economic intelligence | Energy, trade, BIS rates, sanctions |
| sigint_analyst | SIGINT | Military flights, GPS jamming, AIS dark |
| librarian | Entity taxonomy | Entity network graphs, brief-entity links |

### API routes

| Route | Method | Purpose |
|-------|--------|---------|
| `api/channels/list` | GET | List all channels with metadata |
| `api/channels/[name]` | GET | Get full channel state |
| `api/channels/[name]` | PUT | Update full channel state (auth required) |
| `api/channels/[name]/briefing` | PUT | Update briefing only (auth required) |
| `api/channels/[name]/map` | PUT | Update map state only (auth required) |
| `api/commissions` | GET | List commissions |
| `api/commissions` | POST | Submit new commission (auth required) |
| `api/commissions/[id]` | PUT | Update commission status (auth required) |

### Frontend modifications (added to fork)

1. **Channel switcher** - sidebar with agent cards showing name, region, alert level, last updated
2. **Briefing panel** - slide-out panel with rendered markdown briefing, sources, timestamp
3. **State-driven rendering** - on channel switch, animate globe to channel's camera position, toggle layers
4. **Default channel** - Montgomery's combined view on first visit
5. **URL routing** - `worldmonitor.atrophy.app/channel/<agent_name>` deep-links to channels

### Pushing channel state

Agent scripts push state after producing intelligence using `channel_push.py`:

```python
# In any agent script, after producing a brief:
from channel_push import push_channel_state

push_channel_state(
    agent="rf_russia_ukraine",
    briefing={"title": "...", "summary": "...", "body_md": "...", "sources": [...]},
    map={"center": [48.5, 35.0], "zoom": 6, "layers": ["acled-events"]},
    alert_level="elevated"
)
```

The `CHANNEL_API_KEY` environment variable is passed to all cron jobs by the runner.

---

## Live Data Layer

70+ channel layer names are mapped to WorldMonitor's internal data layer IDs. When a channel activates a layer, the platform toggles the corresponding WorldMonitor data layer on the map.

Example mappings:
- `military-flights` -> WorldMonitor military aviation layer
- `acled-events` -> ACLED conflict events
- `ais-vessels` -> AIS maritime tracking
- `gps-jamming` -> GPS jamming zones
- `oref-alerts` -> Israeli alert system
- `thermal-escalations` -> Thermal/fire data
- `energy-prices` -> Economic energy layer
- `trade-flows` -> Trade restriction data

Agents control which layers appear on their channel view by listing them in the `map.layers` array when pushing state.

---

## Commission Portal

The commission portal allows gap intelligence tasking - when competitor synthesis identifies a gap in Meridian's coverage, or when an analyst needs specific information, a commission is filed.

### Flow

1. Commission submitted via platform API or auto-filed by competitor synthesis
2. Stored in both `commissions` table (intelligence.db) and Upstash Redis
3. Two-way sync via `commission_sync.py` (cron job)
4. Assigned agent processes the commission and produces output
5. Output synced back to platform

### Commission fields

- `title` - What needs investigating
- `brief` - Context and requirements
- `requestor` - Who requested it (agent name or user)
- `priority` - high/medium/low
- `assigned_to` - Agent responsible
- `status` - open/in_progress/completed/cancelled
- `output` - Result text when completed

---

## Briefing Audio

ElevenLabs TTS generates audio briefings using Montgomery's voice. Audio files are produced by `generate_brief_audio.py` and can be played back on the platform or delivered via Telegram.

---

## Intelligence Capabilities (14 Systems)

| # | System | Script(s) | Cadence | Description |
|---|--------|-----------|---------|-------------|
| 1 | Prediction Ledger | `prediction_extract.py`, `prediction_review.py` | Extract on brief publish, review monthly | 40 predictions tracked with 30-day auto-review |
| 2 | Cross-Agent Synthesis | `cross_agent_synthesis.py` | Nightly (02:00) | Reads all channels' latest briefings, identifies convergence patterns |
| 3 | Source Health Dashboard | `source_health.py` | Every 6 hours | Monitors 39 sources (RSS, APIs, WorldMonitor endpoints) |
| 4 | Entity Resolution | `entity_resolve.py` | On demand | Haiku-driven deduplication (134->88 entities), 204 brief-entity links |
| 5 | Temporal Situation Tracking | `timeline_update.py` | On brief publish | 50 timeline entries across 6 conflicts with trajectory assessment |
| 6 | Automated Relationship Extraction | `relationship_extract.py` | Hourly | Extracts relationships from briefs via Claude Haiku |
| 7 | Commission Portal | `commission_sync.py` | Every 30 min | Two-way sync between intelligence.db and platform |
| 8 | Systematic Red Team Review | `red_team_review.py` | On high-priority briefs | Four-part adversarial challenge (evidential, alternative, historical, verdict) |
| 9 | Live Data Layer | Built into platform | Continuous | Channel-driven layer activation (70 layer mappings) |
| 10 | Briefing Audio | `generate_brief_audio.py` | On brief publish | ElevenLabs TTS with Montgomery's voice |
| 11 | Agent Performance Metrics | `agent_metrics.py` | Monthly | Review across 7 categories |
| 12 | Geofencing | `geofence_check.py` | Every 15 min | 8 watch zones with haversine alerting |
| 13 | Structured Intelligence Products | `product_templates.py` | Built into brief pipeline | 8 templates (SITREP, FLASH, WARNING, INTSUM, PROFILE, WEEKLY_DIGEST, ASSESSMENT, SYNTHESIS) |
| 14 | Multi-Source Verification | `verify_brief.py` | Post-brief generation | Cross-reference claims against multiple sources, assign corroboration score |

---

## Cron Job Schedule (Meridian-specific)

### Montgomery (general_montgomery)

| Job | Cadence | Script |
|-----|---------|--------|
| worldmonitor_fast | Every 15 min | `worldmonitor_poll.py --tier fast` |
| worldmonitor_medium | Every 45 min | `worldmonitor_poll.py --tier medium` |
| worldmonitor_slow | Every 4 hours | `worldmonitor_poll.py --tier slow` |
| dashboard_refresh | Every 15 min | `dashboard_brief.py --mode refresh` |
| dashboard_brief | Every 4 hours | `dashboard_brief.py --mode send` |
| ship_track_alert | Every 30 min | `ship_track_alert.py` |
| flash_report | Every 15 min | `flash_report.py` |
| weekly_digest | Mon 07:00 | `weekly_digest.py` |
| weekly_conflicts | Mon 08:00 | `weekly_conflicts.py` |
| parliamentary_monitor | Weekdays 08:00 | `parliamentary_monitor.py` |
| competitor_scan | Weekdays 09:00 | `competitor_scan.py` |
| process_audit | First Mon 10:00 | `process_audit.py` |

### Shared intelligence scripts

| Job | Cadence | Script |
|-----|---------|--------|
| source_health | Every 6 hours | `source_health.py` |
| cross_agent_synthesis | Daily 02:00 | `cross_agent_synthesis.py` |
| commission_sync | Every 30 min | `commission_sync.py` |
| geofence_check | Every 15 min | `geofence_check.py` |
| prediction_review | Monthly | `prediction_review.py` |
| agent_metrics | Monthly | `agent_metrics.py` |

### Research Fellows

| Agent | Cadence | Script |
|-------|---------|--------|
| rf_uk_defence | Thursday 06:00 | `weekly_posture.py` |
| rf_european_security | Thursday 06:00 | `weekly_security.py` |
| rf_russia_ukraine | Weekdays 06:30 | `daily_battlefield.py` |
| rf_gulf_iran_israel | 1st of month 07:00 | `monthly_paper.py` |
| rf_indo_pacific | Friday 06:00 | `weekly_indopacific.py` |

---

## Personal Scripts

Intelligence scripts that contain operational data live in `~/.atrophy/scripts/` rather than the git repo. The cron runner checks `~/.atrophy/scripts/agents/<path>` first, falling back to `<bundle>/scripts/agents/<path>`. The `PYTHONPATH` env includes `~/.atrophy/scripts/` so personal scripts can import shared modules.

18 scripts are gitignored from the Atrophy repo:
- Shared: channel_push, source_health, verify_brief, red_team_review, product_templates, timeline_update, cross_agent_synthesis, prediction_extract, prediction_review, agent_metrics, generate_brief_audio, geofence_check, commission_sync, ontology, ontology_migrate, ontology_ingest
- Librarian: entity_resolve, relationship_extract

---

## How To

### Push a channel state update

```python
from channel_push import push_channel_state
push_channel_state(agent="rf_russia_ukraine", briefing={...}, map={...})
```

### Submit a commission

```bash
curl -X POST https://worldmonitor.atrophy.app/api/commissions \
  -H "X-Channel-Key: $CHANNEL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title": "...", "brief": "...", "priority": "medium", "assigned_to": "rf_gulf_iran_israel"}'
```

### Query the ontology

```sql
-- Find all objects of a type
SELECT id, name, subtype, status FROM objects WHERE type = 'country' ORDER BY name;

-- Get properties for an object
SELECT key, value, confidence, source FROM properties WHERE object_id = ? ORDER BY key;

-- Get all relationships for an object
SELECT o2.name, l.type, l.confidence, l.source
FROM links l JOIN objects o2 ON l.to_id = o2.id
WHERE l.from_id = ? AND (l.valid_to IS NULL OR l.valid_to > datetime('now'));
```

### Run the auto-ingestion pipeline

```python
from ontology_ingest import ingest_worldmonitor_response
result = ingest_worldmonitor_response("api/military-flights", data, "worldmonitor:flights")
```

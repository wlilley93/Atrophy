# WorldMonitor - Defence Org Intelligence Platform

Montgomery's defence org deploys WorldMonitor (github.com/koala73/worldmonitor) as its public intelligence platform at `worldmonitor.atrophy.app`. Three systems converge on a single surface: the WorldMonitor map/data engine, the Meridian Institute's analytical papers, and the intelligence.db knowledge graph. Each agent in the org gets a channel. The result is a curated newsroom, not a raw dashboard.

## Context

**WorldMonitor** is an open-source intelligence dashboard: 435+ news feeds across 15 categories, dual map engine (globe.gl 3D + deck.gl/MapLibre 2D), 45 data layers, military flight tracking, AIS maritime, GPS jamming, ACLED conflict events, economic indicators, and more. Built for Vercel deployment (60+ Edge Functions), Vite frontend, vanilla TypeScript.

**Meridian Institute** is Montgomery's six-track analytical operation. It produces weekly digests, conflict deep-dives, flash reports, economic assessments, parliamentary monitoring, competitor synthesis, and red team reviews. 34 briefs in the database so far, delivered to Telegram as text.

**intelligence.db** is a SQL-based knowledge graph. 123 entities (countries, orgs, factions, persons), 8 tracked conflicts, conflict actor mappings with alignments, and a relationship table - but only 7 relationships populated. The schema is sophisticated; the data is sparse. Automated relationship extraction doesn't exist yet.

The defence org currently has 16+ scripts producing intelligence. That output goes to Telegram as text walls. The missing piece: a visual, interactive, shareable surface the agents control, backed by the knowledge graph.

### Defence org agents

| Agent | Role | What they'd show |
|-------|------|-------------------|
| general_montgomery | Editor-in-chief | Combined picture, flash alerts, weekly digest, knowledge graph overview |
| rf_russia_ukraine | Russia-Ukraine RF | Frontline map, ACLED events, thermal data, flight tracks |
| rf_gulf_iran_israel | Gulf/Iran/Israel RF | Maritime (Hormuz, Red Sea), OREF alerts, strike events |
| rf_european_security | European security RF | NATO posture, Baltic/Nordic layers, energy infrastructure |
| rf_indo_pacific | Indo-Pacific RF | South China Sea maritime, Taiwan Strait, flight tracks |
| rf_uk_defence | UK defence RF | UK procurement, posture, fleet disposition |
| rf_eu_nordic_monitor | EU/Nordic monitor | EU policy, Nordic security feeds |
| economic_io | Economic intelligence | Energy prices, trade flows, BIS rates, sanctions |
| sigint_analyst | SIGINT | Military flights, GPS jamming zones, AIS dark events |
| librarian | Entity taxonomy | Entity network graphs, brief-to-entity links |

---

## 1. Deployment

### Infrastructure

- **Hosting:** Vercel (project already built for it)
- **Domain:** `worldmonitor.atrophy.app` - CNAME on GoDaddy pointing to Vercel
- **Repo:** Fork `koala73/worldmonitor` to Will's GitHub, deploy from that fork
- **State:** Vercel KV (Redis-compatible) for channel state and briefing content
- **Data:** WorldMonitor's own external data sources + intelligence.db synced from local

### GoDaddy DNS setup

Add CNAME record:
- Type: CNAME
- Name: worldmonitor
- Value: cname.vercel-dns.com
- TTL: 600

### Vercel setup

1. Import the forked repo
2. Add custom domain `worldmonitor.atrophy.app`
3. Framework preset: Vite
4. Environment variables: `NODE_ENV=production`, `CHANNEL_API_KEY=<generated>`
5. Enable Vercel KV store
6. Deploy

---

## 2. Agent Channel System

### Concept

Each defence org agent gets a channel - a curated view of the intelligence picture. The site opens on Montgomery's channel: a dark globe, current alert level, his synthesis of what matters. A sidebar shows agent channels as compact cards. Clicking a channel rotates the globe to that agent's region, activates their layers, shows their markers and briefing.

**This is a newsroom, not a dashboard.** The map serves the narrative. Agents show you what they want you to see - not everything at once.

### Channel state

Stored in Vercel KV:

```
Key: channel:<agent_name>
Value: {
  "agent": "rf_russia_ukraine",
  "display_name": "Russia-Ukraine",
  "updated_at": "2026-03-27T14:30:00Z",
  "alert_level": "normal|elevated|critical",
  "briefing": {
    "title": "Kherson axis pressure building",
    "summary": "Thermal signatures along...",
    "body_md": "Full markdown analysis...",
    "sources": ["ACLED", "WorldMonitor thermal", "Telegram OSINT"]
  },
  "map": {
    "center": [48.5, 35.0],
    "zoom": 6,
    "bearing": 0,
    "pitch": 30,
    "layers": ["military-flights", "acled-events", "thermal-escalations"],
    "markers": [
      {
        "lat": 46.6, "lon": 32.6,
        "label": "Kherson",
        "type": "event",
        "detail": "Thermal cluster - 3 new signatures in 6 hours",
        "entity_id": null
      }
    ],
    "regions": ["UA", "RU"],
    "highlight_entities": [42, 67, 89]
  },
  "feeds": {
    "categories": ["conflict", "military"],
    "keywords": ["ukraine", "russia", "kherson"]
  }
}
```

### API routes (added to the fork)

| Route | Method | Purpose |
|-------|--------|---------|
| `api/channels/list` | GET | List all channels with metadata |
| `api/channels/[name]` | GET | Get channel state |
| `api/channels/[name]` | PUT | Update channel state (auth required) |
| `api/channels/[name]/briefing` | PUT | Update briefing only |
| `api/channels/[name]/map` | PUT | Update map state only |
| `api/channels/[name]/entities` | GET | Get entities relevant to this channel |
| `api/knowledge/entities` | GET | Full entity list with relationships |
| `api/knowledge/entity/[id]` | GET | Single entity with relationships + briefs |
| `api/knowledge/conflicts` | GET | Conflict watchlist with actor networks |
| `api/knowledge/conflict/[slug]` | GET | Single conflict with full actor graph |
| `api/knowledge/graph` | GET | Full graph data (nodes + edges) for visualization |
| `api/meridian/briefs` | GET | List Meridian briefs (paginated) |
| `api/meridian/brief/[id]` | GET | Single brief with linked entities and conflict |
| `api/meridian/latest` | GET | Latest brief per track |
| `api/knowledge/sync` | PUT | Bulk sync from intelligence.db (auth required) |
| `api/meridian/sync` | PUT | Bulk sync briefs from intelligence.db (auth required) |

Auth for PUT/sync routes: `X-Channel-Key` header with shared secret. Set in Vercel env vars and `~/.atrophy/.env`.

### Frontend modifications (to the fork)

1. **Channel switcher** - sidebar with agent cards showing name, region, alert level, last updated, one-line status. Colored pip for recent updates.
2. **Briefing panel** - slide-out panel showing the current channel's briefing: title, body (rendered markdown), sources, timestamp. This is the PRIMARY content - the map illustrates it.
3. **State-driven rendering** - on channel switch, animate globe/map to the channel's camera position, toggle layers, place markers, highlight regions.
4. **Default channel** - Montgomery's view on first visit. Shows all agents' markers simultaneously, his synthesis briefing.
5. **URL routing** - `worldmonitor.atrophy.app/channel/rf_russia_ukraine` deep-links to a channel.

---

## 3. Knowledge Graph Integration

### The problem

intelligence.db has 123 entities and 7 relationships. The schema supports confidence-scored, temporally-valid relationships with conflict scoping. But automated relationship extraction doesn't exist. The librarian enriches entities (descriptions, subtypes) but never extracts connections.

### Automated relationship extraction

Upgrade the librarian with a new script: `scripts/agents/librarian/relationship_extract.py`

Runs after each new brief is filed (triggered by taxonomy_filing or as a separate hourly job):

1. Read unprocessed briefs from `briefs` table
2. For each brief, call Claude Haiku with the brief text and a structured extraction prompt:
   ```
   Extract all relationships between named entities in this text.
   For each relationship, provide:
   - from_entity: name
   - to_entity: name
   - type: one of [funds, arms, allied_with, opposes, mediates, sanctions, commands, deploys, hosts, threatens, negotiates]
   - confidence: 0.0-1.0
   - notes: brief context
   ```
3. Resolve entity names to IDs (fuzzy match against entities table)
4. INSERT OR IGNORE into relationships table
5. Mark brief as processed in a state tracking column or separate table

### Relationship types (expanded)

Current: funds, arms, allied_with

Expanded set for the extraction prompt:
- `funds` - financial support
- `arms` - weapons/materiel supply
- `allied_with` - formal or informal alliance
- `opposes` - adversarial relationship
- `mediates` - diplomatic mediation role
- `sanctions` - sanctions imposed
- `commands` - military command relationship
- `deploys` - force deployment
- `hosts` - basing/hosting arrangement
- `threatens` - explicit threat/escalation
- `negotiates` - active negotiation/talks
- `trades` - significant trade relationship
- `intelligence_shares` - intelligence cooperation

### Knowledge graph on the newsroom

The graph data syncs from intelligence.db to Vercel KV periodically (every 30 minutes or on brief publication):

**Map layer: Entity network**
- Entities placed geographically (countries at centroid, orgs at HQ/primary location, persons at last known location)
- Relationship lines between entities, colored by type, thickness by confidence
- Click an entity: popup shows description, type, all relationships, all briefs mentioning it
- Click a relationship line: shows type, confidence, source brief, temporal validity

**Conflict network view**
- Per-conflict: all actors shown in a force-directed graph (like conflict_network.py but interactive)
- Nodes: entities colored by alignment (belligerent red, backer orange, mediator blue, neutral grey)
- Edges: relationship types between actors
- Side-a vs side-b spatial grouping
- Accessible from the conflict section of each channel

**Entity search**
- Search bar on the site: type an entity name, jump to its location on the map with relationships shown
- Autocomplete from the entities table

### Sync mechanism

A new script `scripts/agents/shared/knowledge_sync.py` pushes intelligence.db data to the Vercel API:

1. Read entities, relationships, conflicts, conflict_actors from intelligence.db
2. Serialize to JSON
3. PUT to `api/knowledge/sync` with auth header
4. Vercel stores in KV

Triggered by:
- After librarian runs (entity enrichment, taxonomy filing, relationship extraction)
- After any brief is published
- On a 30-minute cron as a safety net

---

## 4. Meridian Papers on the Site

### Concept

Meridian Institute papers are the analytical product. Currently they exist only as rows in the briefs table and Telegram messages. On the newsroom, they become published articles.

### Brief pages

Each brief gets a page: `worldmonitor.atrophy.app/meridian/brief/<id>`

Page layout:
- Title, date, requesting agent
- Track indicator (which of the 6 tracks)
- Conflict linkage (if applicable)
- Full markdown body
- Sidebar: linked entities (clickable, jump to map), sources
- "View on map" button: switches to the relevant channel with the brief's context highlighted

### Meridian index

`worldmonitor.atrophy.app/meridian/` shows:
- Latest brief per track (6 cards)
- Recent briefs chronologically
- Filter by track, conflict, date range

### Sync mechanism

Briefs sync from intelligence.db to Vercel KV via the same `knowledge_sync.py` script. Each brief is stored as:

```
Key: meridian:brief:<id>
Value: {
  "id": 34,
  "title": "Weekly Digest - Six-Track Assessment",
  "date": "2026-03-24",
  "track": "digest",
  "conflict_slug": null,
  "requested_by": "chief_of_staff",
  "content_md": "...",
  "sources": ["WorldMonitor", "ACLED", "OREF"],
  "linked_entities": [12, 45, 67, 89],
  "created_at": "2026-03-24T07:15:00Z"
}
```

---

## 5. Desktop and Telegram Integration

### Desktop (Artefact)

When an agent references the map or a brief in a response, the Atrophy desktop app shows it as an artefact:

- Channel URL: `https://worldmonitor.atrophy.app/channel/<agent_name>`
- Brief URL: `https://worldmonitor.atrophy.app/meridian/brief/<id>`
- Entity URL: `https://worldmonitor.atrophy.app/entity/<id>`
- Rendered in the Artefact webview overlay (already exists)
- Interactive - user can pan, zoom, click markers, follow entity links

### Telegram

When agents share updates:

1. **Link with preview** - Telegram auto-generates a card from OG tags
2. **Per-channel OG tags** - `og:title` = agent display name + briefing title, `og:description` = briefing summary, `og:image` = generated map thumbnail
3. **OG image generation** - Vercel OG (satori) renders a branded card with map snapshot, alert level indicator, and briefing title

Example Telegram message from Montgomery:
> Situation update - Kherson axis pressure building. Three thermal clusters detected along the contact line correlate with ammunition depot positioning observed in SIGINT flight tracks.
>
> https://worldmonitor.atrophy.app

The link renders with a preview card. Clicking it shows the full interactive map with Montgomery's current markers and briefing.

### Canvas overlay

The existing Canvas component in the desktop app can load any channel URL for full-screen interactive viewing during conversations.

---

## 6. Agent Push Mechanism

### Shared utility

`scripts/agents/shared/channel_push.py`:

```python
def push_channel_state(agent_name: str, state: dict) -> bool:
    """Push channel state to worldmonitor.atrophy.app."""
    url = f"https://worldmonitor.atrophy.app/api/channels/{agent_name}"
    data = json.dumps(state).encode()
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Channel-Key", os.environ.get("CHANNEL_API_KEY", ""))
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception:
        return False

def push_briefing(agent_name: str, title: str, summary: str, body: str, sources: list) -> bool:
    """Push just the briefing text for a channel."""
    ...

def push_map_state(agent_name: str, center: list, zoom: int, layers: list, markers: list, regions: list) -> bool:
    """Push just the map state for a channel."""
    ...
```

### MCP tool

New tool in `worldmonitor_server.py`:

```python
{
    "name": "worldmonitor_push_channel",
    "description": (
        "Update the agent's channel on worldmonitor.atrophy.app. "
        "Set map layers, markers, camera position, briefing text, "
        "and alert level. Use this when delivering intelligence "
        "updates to make them visual and shareable."
    ),
    ...
}
```

This lets agents push state during inference, not just from cron scripts.

### Per-agent integration points

Each agent's existing scripts get a `push_channel_state()` call after producing output:

| Script | Channel updated | What changes |
|--------|----------------|--------------|
| `three_hour_update.py` | general_montgomery | Combined picture, all markers |
| `flash_report.py` | general_montgomery | Alert level -> critical, map recenters |
| `weekly_digest.py` | general_montgomery | Briefing text, layer selection |
| `daily_battlefield.py` | rf_russia_ukraine | Frontline markers, ACLED layer |
| `sigint_cycle.py` | sigint_analyst | Flight tracks, GPS jamming hexes |
| `economic_weekly.py` | economic_io | Trade flow data, energy markers |
| `ship_track_alert.py` | rf_gulf_iran_israel / sigint_analyst | Maritime events |
| `relationship_extract.py` | (triggers knowledge sync) | Entity graph updates |

---

## 7. Data Flow

```
Intelligence cycle:
  cron job fires (e.g. three_hour_update.py)
    -> fetches WorldMonitor API data
    -> produces briefing + map state
    -> writes brief to intelligence.db
    -> pushes channel state to worldmonitor.atrophy.app/api/channels/general_montgomery
    -> sends Telegram message with site URL
    -> site reflects new state for anyone viewing

Knowledge graph cycle:
  librarian runs (entity enrichment, taxonomy filing)
    -> new entities + relationships written to intelligence.db
    -> knowledge_sync.py pushes to worldmonitor.atrophy.app/api/knowledge/sync
    -> entity network layer updates on the map

Relationship extraction:
  new brief filed to intelligence.db
    -> relationship_extract.py reads brief text
    -> Claude Haiku extracts entity relationships
    -> relationships written to intelligence.db
    -> knowledge_sync.py pushes updated graph

Meridian publication:
  brief written to intelligence.db by any script
    -> knowledge_sync.py pushes brief to worldmonitor.atrophy.app/api/meridian/sync
    -> brief appears on the Meridian index page
    -> linked to entities and conflict on the map

Desktop:
  Montgomery references the situation in conversation
    -> calls worldmonitor_push_channel MCP tool (updates site)
    -> returns URL as artefact for desktop display
    -> user sees interactive map in artefact overlay

Telegram:
  Agent sends update with URL
    -> Telegram renders OG preview card with map thumbnail
    -> Recipient clicks through to live interactive map
```

---

## 8. Fork Modifications

Changes to the WorldMonitor fork (not the Atrophy repo):

### New files

| File | Purpose |
|------|---------|
| `api/channels/list.ts` | List channels |
| `api/channels/[name].ts` | Get/update channel state |
| `api/channels/[name]/briefing.ts` | Update briefing only |
| `api/channels/[name]/map.ts` | Update map state only |
| `api/channels/[name]/entities.ts` | Get channel-relevant entities |
| `api/knowledge/entities.ts` | Full entity list |
| `api/knowledge/entity/[id].ts` | Entity detail with relationships + briefs |
| `api/knowledge/conflicts.ts` | Conflict watchlist |
| `api/knowledge/conflict/[slug].ts` | Conflict detail with actor graph |
| `api/knowledge/graph.ts` | Full graph export (nodes + edges) |
| `api/knowledge/sync.ts` | Bulk sync endpoint |
| `api/meridian/briefs.ts` | Brief listing |
| `api/meridian/brief/[id].ts` | Brief detail |
| `api/meridian/latest.ts` | Latest per track |
| `api/meridian/sync.ts` | Bulk brief sync |
| `src/lib/channels.ts` | Channel state management (KV) |
| `src/lib/knowledge.ts` | Knowledge graph KV operations |
| `src/lib/meridian.ts` | Brief KV operations |
| `src/components/ChannelSwitcher.svelte` | Channel selection sidebar |
| `src/components/BriefingPanel.svelte` | Briefing text display |
| `src/components/EntityPopup.svelte` | Entity detail on map click |
| `src/components/ConflictGraph.svelte` | Interactive conflict actor network |
| `src/components/MeridianIndex.svelte` | Brief listing page |
| `src/components/MeridianBrief.svelte` | Single brief page |
| `src/components/EntitySearch.svelte` | Entity search with autocomplete |

### Modified files

| File | Change |
|------|--------|
| Root app component | Add channel switcher, briefing panel, state-driven layer control |
| `api/og-story.js` | Channel-specific OG tag generation |
| Map component | Entity network layer, conflict graph overlay, marker type rendering |

---

## 9. Atrophy Repo Changes

### New files

| File | Purpose |
|------|---------|
| `scripts/agents/shared/channel_push.py` | Push channel state to site |
| `scripts/agents/shared/knowledge_sync.py` | Sync intelligence.db to site |
| `scripts/agents/librarian/relationship_extract.py` | Automated relationship extraction from briefs |

### Modified files

| File | Change |
|------|--------|
| `src/main/config.ts` | Add `CHANNEL_API_KEY` to allowed env keys |
| `mcp/worldmonitor_server.py` | Add `worldmonitor_push_channel` tool |
| `scripts/agents/general_montgomery/three_hour_update.py` | Add channel push after output |
| `scripts/agents/general_montgomery/flash_report.py` | Add channel push with critical alert |
| `scripts/agents/general_montgomery/weekly_digest.py` | Add channel push |
| `scripts/agents/rf_russia_ukraine/daily_battlefield.py` | Add channel push |
| `scripts/agents/sigint_analyst/sigint_cycle.py` | Add channel push |
| `scripts/agents/economic_io/economic_weekly.py` | Add channel push |
| Other RF agent scripts | Add channel push calls |
| `~/.atrophy/agents/general_montgomery/data/agent.json` | Add knowledge_sync and relationship_extract jobs |

---

## 10. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Vercel KV costs | Free tier: 256MB, 30k requests/day - sufficient for this scale |
| Fork diverges from upstream | Keep modifications isolated to new files. Periodic merge from upstream. |
| Channel API key leaks | Rotate via Vercel env vars. Never commit. |
| Relationship extraction hallucinations | Confidence threshold (>0.6 to store). Haiku is conservative. Review via red_team agent. |
| intelligence.db grows large | Already 248KB with 123 entities. SQLite handles millions of rows. Not a concern. |
| Knowledge sync fails | 30-minute cron as safety net. Stale data is acceptable - the graph doesn't change that fast. |
| Map tiles need internet | Yes - the site requires internet. This is a web-hosted product. |
| WorldMonitor upstream removes features | We fork, we control. Can always pin to a working commit. |

---

## 11. Build Order

### Phase 1: Deploy and verify (day 1)
1. Fork WorldMonitor repo
2. Deploy to Vercel
3. Add CNAME on GoDaddy
4. Verify `worldmonitor.atrophy.app` loads with full WorldMonitor features
5. Set up Vercel KV store

### Phase 2: Channel system (day 2-3)
6. Build channel API routes (list, get, put)
7. Add auth middleware (X-Channel-Key)
8. Build channel switcher frontend component
9. Build briefing panel component
10. State-driven map rendering (apply layers, camera, markers on channel switch)
11. URL routing for deep links
12. Build `channel_push.py` shared utility
13. Test: push state from script, verify site updates

### Phase 3: Knowledge graph (day 3-4)
14. Build knowledge API routes (entities, relationships, conflicts, graph, sync)
15. Build `knowledge_sync.py` - sync intelligence.db to Vercel KV
16. Build `relationship_extract.py` - automated extraction from briefs
17. Entity network map layer (geographic placement, relationship lines)
18. Entity popup component (click for detail)
19. Entity search with autocomplete
20. Conflict network graph component (force-directed, interactive)

### Phase 4: Meridian papers (day 4)
21. Build Meridian API routes (briefs, latest, sync)
22. Meridian index page
23. Meridian brief page (markdown render, entity links, conflict link)
24. Brief sync in knowledge_sync.py
25. "View on map" button linking briefs to channels

### Phase 5: Agent integration (day 5)
26. Add channel push calls to Montgomery's scripts
27. Add channel push calls to RF agent scripts
28. Add `worldmonitor_push_channel` MCP tool
29. Add `CHANNEL_API_KEY` to config and .env
30. Register knowledge_sync and relationship_extract as librarian cron jobs
31. Test: full cycle from cron fire to site update to Telegram link

### Phase 6: Desktop + Telegram polish (day 5-6)
32. OG tag generation per channel (map thumbnail + briefing title)
33. Artefact integration - agent responses include channel/brief URLs
34. Canvas overlay for full-screen map viewing
35. Test end-to-end: cron fires, state pushes, site updates, Telegram shows preview, desktop shows artefact

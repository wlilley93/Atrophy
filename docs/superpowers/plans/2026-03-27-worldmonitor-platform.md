# WorldMonitor Intelligence Platform - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy WorldMonitor as Montgomery's defence org intelligence platform at `worldmonitor.atrophy.app`, with agent channels, knowledge graph visualization, and Meridian paper publishing.

**Architecture:** Fork the WorldMonitor open-source repo (vanilla TypeScript + Preact, deck.gl maps, Vercel Edge Functions). Add a channel system backed by Upstash Redis, where each defence org agent pushes curated map state and briefings. Intelligence.db data syncs to the platform for entity graph and brief publishing. Agent scripts push state after producing intelligence.

**Tech Stack:** TypeScript, Preact, deck.gl, MapLibre GL, Upstash Redis, Vercel Edge Functions, Python (agent scripts), SQLite (intelligence.db)

**Spec:** `docs/superpowers/specs/2026-03-27-worldmonitor-integration-design.md`

**Repos involved:**
- **Fork repo** (new): `wlilley93/worldmonitor` - forked from `koala73/worldmonitor`, deployed to Vercel
- **Atrophy repo** (this): agent scripts, MCP server, config changes

---

## Phase 1: Deploy + Foundation

### Task 1: Fork and deploy WorldMonitor

**Files:**
- Fork: `koala73/worldmonitor` -> `wlilley93/worldmonitor`
- No file changes yet - deploy the stock app first

- [ ] **Step 1: Fork the repo**

```bash
gh repo fork koala73/worldmonitor --clone=false
```

- [ ] **Step 2: Clone the fork locally**

```bash
git clone https://github.com/wlilley93/worldmonitor.git ~/.atrophy/services/worldmonitor
cd ~/.atrophy/services/worldmonitor
npm install
```

- [ ] **Step 3: Verify local dev server works**

```bash
cd ~/.atrophy/services/worldmonitor
npm run dev
```

Open `http://localhost:5173` - verify the full WorldMonitor dashboard loads with map, feeds, data.

- [ ] **Step 4: Deploy to Vercel**

```bash
cd ~/.atrophy/services/worldmonitor
npx vercel --prod
```

Follow prompts - link to Vercel account, accept defaults. Note the deployment URL.

- [ ] **Step 5: Add custom domain on Vercel**

In Vercel dashboard: Settings > Domains > Add `worldmonitor.atrophy.app`

Vercel will show the required DNS record.

- [ ] **Step 6: Add CNAME on GoDaddy**

GoDaddy DNS > Add record:
- Type: CNAME
- Name: worldmonitor
- Value: cname.vercel-dns.com
- TTL: 600

- [ ] **Step 7: Verify deployment**

Wait for DNS propagation (up to 30 minutes), then open `https://worldmonitor.atrophy.app`. Verify the full app loads with HTTPS.

- [ ] **Step 8: Commit nothing** - this is infrastructure setup, no code changes.

---

### Task 2: Set up Upstash Redis

**Files:** None - this is service configuration

- [ ] **Step 1: Create Upstash Redis database**

Go to [console.upstash.com](https://console.upstash.com), create a new Redis database. Region: US East (closest to Vercel). Name: `worldmonitor-channels`.

Note the REST URL and REST Token.

- [ ] **Step 2: Add environment variables to Vercel**

In Vercel dashboard > Settings > Environment Variables:
- `UPSTASH_REDIS_REST_URL` = (from Upstash)
- `UPSTASH_REDIS_REST_TOKEN` = (from Upstash)
- `CHANNEL_API_KEY` = (generate with `openssl rand -hex 32`)

- [ ] **Step 3: Add CHANNEL_API_KEY to local env**

```bash
echo "CHANNEL_API_KEY=$(openssl rand -hex 32)" >> ~/.atrophy/.env
```

Use the SAME key value that was set in Vercel.

- [ ] **Step 4: Add CHANNEL_API_KEY to Atrophy config whitelist**

In `src/main/config.ts`, the `ALLOWED_ENV_KEYS` set already has `WORLDMONITOR_API_KEY` (added earlier this session). Add `CHANNEL_API_KEY`:

```typescript
const ALLOWED_ENV_KEYS = new Set([
  'ELEVENLABS_API_KEY',
  'FAL_KEY',
  'TELEGRAM_BOT_TOKEN',
  'TELEGRAM_CHAT_ID',
  'OPENAI_API_KEY',
  'ANTHROPIC_API_KEY',
  'WORLDMONITOR_API_KEY',
  'CHANNEL_API_KEY',
]);
```

- [ ] **Step 5: Commit Atrophy change**

```bash
cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron"
git add src/main/config.ts
git commit -m "feat: add CHANNEL_API_KEY to allowed env keys"
```

---

### Task 3: Channel API routes

All work in the **fork repo** (`~/.atrophy/services/worldmonitor`).

**Files:**
- Create: `api/channels/list.js`
- Create: `api/channels/[name].js`
- Create: `api/channels/[name]/briefing.js`
- Create: `api/channels/[name]/map.js`
- Create: `api/_channel-auth.js`

- [ ] **Step 1: Create auth middleware**

File: `api/_channel-auth.js`

```javascript
export function validateChannelKey(req) {
  const key = req.headers.get('X-Channel-Key');
  const validKey = process.env.CHANNEL_API_KEY;
  if (!validKey || !key || key !== validKey) {
    return { valid: false, error: 'Invalid or missing X-Channel-Key' };
  }
  return { valid: true };
}
```

- [ ] **Step 2: Create channel list route**

File: `api/channels/list.js`

```javascript
import { readJsonFromUpstash } from '../_upstash-json.js';
import { corsHeaders, handleCors } from '../_cors.js';

export const config = { runtime: 'edge' };

export default async function handler(req) {
  if (req.method === 'OPTIONS') return handleCors(req);

  try {
    const url = process.env.UPSTASH_REDIS_REST_URL;
    const token = process.env.UPSTASH_REDIS_REST_TOKEN;

    // Get all channel keys
    const keysResp = await fetch(`${url}/keys/channel:*`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const keysData = await keysResp.json();
    const keys = keysData.result || [];

    // Fetch each channel's metadata
    const channels = [];
    for (const key of keys) {
      const data = await readJsonFromUpstash(key);
      if (data) {
        channels.push({
          agent: data.agent,
          display_name: data.display_name,
          alert_level: data.alert_level || 'normal',
          updated_at: data.updated_at,
          briefing_title: data.briefing?.title || '',
        });
      }
    }

    return new Response(JSON.stringify({ channels }), {
      status: 200,
      headers: { ...corsHeaders(req), 'Content-Type': 'application/json' },
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500,
      headers: { ...corsHeaders(req), 'Content-Type': 'application/json' },
    });
  }
}
```

- [ ] **Step 3: Create channel get/put route**

File: `api/channels/[name].js`

```javascript
import { readJsonFromUpstash } from '../_upstash-json.js';
import { validateChannelKey } from '../_channel-auth.js';
import { corsHeaders, handleCors } from '../_cors.js';

export const config = { runtime: 'edge' };

export default async function handler(req) {
  if (req.method === 'OPTIONS') return handleCors(req);

  const url = new URL(req.url);
  const segments = url.pathname.split('/').filter(Boolean);
  const name = segments[segments.length - 1];
  const kvKey = `channel:${name}`;

  if (req.method === 'GET') {
    const data = await readJsonFromUpstash(kvKey);
    if (!data) {
      return new Response(JSON.stringify({ error: 'Channel not found' }), {
        status: 404,
        headers: { ...corsHeaders(req), 'Content-Type': 'application/json' },
      });
    }
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { ...corsHeaders(req), 'Content-Type': 'application/json' },
    });
  }

  if (req.method === 'PUT') {
    const auth = validateChannelKey(req);
    if (!auth.valid) {
      return new Response(JSON.stringify({ error: auth.error }), {
        status: 401,
        headers: { ...corsHeaders(req), 'Content-Type': 'application/json' },
      });
    }

    const body = await req.json();
    body.updated_at = new Date().toISOString();

    const redisUrl = process.env.UPSTASH_REDIS_REST_URL;
    const token = process.env.UPSTASH_REDIS_REST_TOKEN;

    await fetch(`${redisUrl}/set/${kvKey}`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    return new Response(JSON.stringify({ ok: true, channel: name }), {
      status: 200,
      headers: { ...corsHeaders(req), 'Content-Type': 'application/json' },
    });
  }

  return new Response('Method not allowed', { status: 405 });
}
```

- [ ] **Step 4: Create briefing-only update route**

File: `api/channels/[name]/briefing.js`

```javascript
import { readJsonFromUpstash } from '../../_upstash-json.js';
import { validateChannelKey } from '../../_channel-auth.js';
import { corsHeaders, handleCors } from '../../_cors.js';

export const config = { runtime: 'edge' };

export default async function handler(req) {
  if (req.method === 'OPTIONS') return handleCors(req);
  if (req.method !== 'PUT') return new Response('Method not allowed', { status: 405 });

  const auth = validateChannelKey(req);
  if (!auth.valid) {
    return new Response(JSON.stringify({ error: auth.error }), {
      status: 401,
      headers: { ...corsHeaders(req), 'Content-Type': 'application/json' },
    });
  }

  const url = new URL(req.url);
  const segments = url.pathname.split('/').filter(Boolean);
  // segments: ['api', 'channels', '<name>', 'briefing']
  const name = segments[2];
  const kvKey = `channel:${name}`;

  const redisUrl = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;

  // Read existing state
  const existing = await readJsonFromUpstash(kvKey) || { agent: name };

  // Merge briefing update
  const briefingUpdate = await req.json();
  existing.briefing = { ...existing.briefing, ...briefingUpdate };
  existing.updated_at = new Date().toISOString();

  await fetch(`${redisUrl}/set/${kvKey}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(existing),
  });

  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { ...corsHeaders(req), 'Content-Type': 'application/json' },
  });
}
```

- [ ] **Step 5: Create map-only update route**

File: `api/channels/[name]/map.js` - same pattern as briefing.js but merges `existing.map` instead of `existing.briefing`.

```javascript
import { readJsonFromUpstash } from '../../_upstash-json.js';
import { validateChannelKey } from '../../_channel-auth.js';
import { corsHeaders, handleCors } from '../../_cors.js';

export const config = { runtime: 'edge' };

export default async function handler(req) {
  if (req.method === 'OPTIONS') return handleCors(req);
  if (req.method !== 'PUT') return new Response('Method not allowed', { status: 405 });

  const auth = validateChannelKey(req);
  if (!auth.valid) {
    return new Response(JSON.stringify({ error: auth.error }), {
      status: 401,
      headers: { ...corsHeaders(req), 'Content-Type': 'application/json' },
    });
  }

  const url = new URL(req.url);
  const segments = url.pathname.split('/').filter(Boolean);
  const name = segments[2];
  const kvKey = `channel:${name}`;

  const redisUrl = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;

  const existing = await readJsonFromUpstash(kvKey) || { agent: name };
  const mapUpdate = await req.json();
  existing.map = { ...existing.map, ...mapUpdate };
  existing.updated_at = new Date().toISOString();

  await fetch(`${redisUrl}/set/${kvKey}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(existing),
  });

  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { ...corsHeaders(req), 'Content-Type': 'application/json' },
  });
}
```

- [ ] **Step 6: Test channel API locally**

```bash
cd ~/.atrophy/services/worldmonitor
npm run dev
```

In a separate terminal:

```bash
# Create a channel
curl -X PUT http://localhost:5173/api/channels/general_montgomery \
  -H "Content-Type: application/json" \
  -H "X-Channel-Key: test-key" \
  -d '{"agent":"general_montgomery","display_name":"General Montgomery","alert_level":"normal","briefing":{"title":"Test briefing","summary":"Testing the channel system"}}'

# Read it back
curl http://localhost:5173/api/channels/general_montgomery

# List all channels
curl http://localhost:5173/api/channels/list
```

Note: Local dev requires `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` in a `.env` file in the WorldMonitor repo root (or set `CHANNEL_API_KEY=test-key` for local auth testing).

- [ ] **Step 7: Commit and deploy**

```bash
cd ~/.atrophy/services/worldmonitor
git add api/_channel-auth.js api/channels/
git commit -m "feat: add channel API routes for agent state management"
git push origin main
```

Vercel auto-deploys on push. Verify at `https://worldmonitor.atrophy.app/api/channels/list`.

---

### Task 4: Channel push utility (Atrophy repo)

**Files:**
- Create: `scripts/agents/shared/channel_push.py`

- [ ] **Step 1: Create channel_push.py**

File: `scripts/agents/shared/channel_push.py`

```python
"""Push channel state to worldmonitor.atrophy.app.

Usage:
    from channel_push import push_channel, push_briefing, push_map_state

Each function returns True on success, False on failure. Failures are
logged but never raise - the caller's primary job (brief generation,
Telegram delivery) should not be blocked by a push failure.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

_BASE_URL = os.environ.get(
    "CHANNEL_BASE_URL", "https://worldmonitor.atrophy.app"
)
_API_KEY = os.environ.get("CHANNEL_API_KEY", "")
_TIMEOUT = 15


def _put(path: str, data: dict) -> bool:
    """PUT JSON to the channel API. Returns True on 2xx."""
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Channel-Key", _API_KEY)
    try:
        resp = urllib.request.urlopen(req, timeout=_TIMEOUT)
        return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError) as exc:
        log.warning("Channel push failed for %s: %s", path, exc)
        return False


def push_channel(agent_name: str, state: dict) -> bool:
    """Push full channel state (briefing + map + metadata)."""
    state.setdefault("agent", agent_name)
    return _put(f"api/channels/{agent_name}", state)


def push_briefing(
    agent_name: str,
    title: str,
    summary: str,
    body_md: str = "",
    sources: list[str] | None = None,
) -> bool:
    """Push just the briefing text for a channel."""
    data = {"title": title, "summary": summary}
    if body_md:
        data["body_md"] = body_md
    if sources:
        data["sources"] = sources
    return _put(f"api/channels/{agent_name}/briefing", data)


def push_map_state(
    agent_name: str,
    center: list[float] | None = None,
    zoom: int | None = None,
    layers: list[str] | None = None,
    markers: list[dict] | None = None,
    regions: list[str] | None = None,
) -> bool:
    """Push just the map state for a channel."""
    data: dict = {}
    if center is not None:
        data["center"] = center
    if zoom is not None:
        data["zoom"] = zoom
    if layers is not None:
        data["layers"] = layers
    if markers is not None:
        data["markers"] = markers
    if regions is not None:
        data["regions"] = regions
    return _put(f"api/channels/{agent_name}/map", data)
```

- [ ] **Step 2: Test it manually**

```bash
cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron"
CHANNEL_API_KEY="<your-key>" python3 -c "
import sys; sys.path.insert(0, 'scripts/agents/shared')
from channel_push import push_briefing
ok = push_briefing('general_montgomery', 'Test', 'Testing push from CLI')
print('OK' if ok else 'FAIL')
"
```

- [ ] **Step 3: Commit**

```bash
git add scripts/agents/shared/channel_push.py
git commit -m "feat: add channel_push.py for pushing state to worldmonitor.atrophy.app"
```

---

### Task 5: Wire channel push into Montgomery's scripts

**Files:**
- Modify: `scripts/agents/general_montgomery/three_hour_update.py`
- Modify: `scripts/agents/general_montgomery/flash_report.py`
- Modify: `scripts/agents/general_montgomery/weekly_digest.py`
- Modify: `scripts/agents/rf_russia_ukraine/daily_battlefield.py`
- Modify: `scripts/agents/sigint_analyst/sigint_cycle.py`

For each script, the pattern is the same: import channel_push at the top, call it after the script produces its output.

- [ ] **Step 1: Read each script to find the right insertion point**

For each script, find where it writes output (prints to stdout, or calls a delivery function). The channel push goes right after.

- [ ] **Step 2: Add push calls**

Each script gets a block like this near the end of its main function, after output is produced but before the script exits:

```python
# Push to worldmonitor.atrophy.app
try:
    from channel_push import push_channel
    push_channel("<agent_name>", {
        "agent": "<agent_name>",
        "display_name": "<Display Name>",
        "alert_level": "normal",
        "briefing": {
            "title": "<brief title from this run>",
            "summary": "<summary text>",
        },
        "map": {
            "center": [<lat>, <lon>],
            "zoom": <level>,
            "layers": [<relevant layers>],
            "markers": <markers_list>,
            "regions": [<ISO codes>],
        },
    })
except Exception:
    pass  # channel push is best-effort
```

The exact values differ per script:

**three_hour_update.py** (Montgomery):
- center: [30, 30] (global), zoom: 2
- layers: from the WorldMonitor data fetched in the script
- markers: derived from OREF alerts, flight tracks, thermal events
- alert_level: derived from the data (critical if OREF active, elevated if thermal clusters, normal otherwise)

**flash_report.py** (Montgomery):
- alert_level: "critical"
- map recenters to the event location
- single marker at the flash event

**daily_battlefield.py** (RF Russia-Ukraine):
- center: [48.5, 35.0], zoom: 6
- layers: ["acled-events", "thermal-escalations"]
- markers: from ACLED event data
- regions: ["UA", "RU"]

**sigint_cycle.py** (SIGINT):
- center: [30, 30], zoom: 2 (global)
- layers: ["military-flights", "gps-jamming"]
- markers: from flight track data and GPS jamming hexes

- [ ] **Step 3: Add CHANNEL_API_KEY to cron runner environment**

In `src/main/channels/cron/runner.ts`, the environment passed to spawned scripts needs `CHANNEL_API_KEY`. Read the current runner.ts to find where env is built, then add:

```typescript
env.CHANNEL_API_KEY = process.env.CHANNEL_API_KEY || '';
```

- [ ] **Step 4: Test with a manual cron trigger**

```bash
cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron"
CHANNEL_API_KEY="<key>" AGENT=general_montgomery PYTHONPATH=".:$HOME/.atrophy/src" \
  python3 scripts/agents/general_montgomery/three_hour_update.py
```

Check `https://worldmonitor.atrophy.app/api/channels/general_montgomery` for the pushed state.

- [ ] **Step 5: Commit**

```bash
git add scripts/agents/general_montgomery/three_hour_update.py \
  scripts/agents/general_montgomery/flash_report.py \
  scripts/agents/general_montgomery/weekly_digest.py \
  scripts/agents/rf_russia_ukraine/daily_battlefield.py \
  scripts/agents/sigint_analyst/sigint_cycle.py \
  src/main/channels/cron/runner.ts
git commit -m "feat: wire channel push into agent scripts"
```

---

### Task 6: Channel switcher frontend component

All work in the **fork repo**.

**Files:**
- Create: `src/components/ChannelSwitcher.ts`
- Create: `src/components/BriefingPanel.ts`
- Modify: `src/App.ts` (add channel components to init)
- Modify: `src/config/panels.ts` (register if panel-based)

- [ ] **Step 1: Create ChannelSwitcher component**

File: `src/components/ChannelSwitcher.ts`

This component renders a sidebar with agent channel cards. Each card shows:
- Agent display name
- Alert level indicator (dot: green/amber/red)
- Last updated relative time
- One-line briefing title

Clicking a card:
1. Fetches the channel state from `/api/channels/<name>`
2. Applies map state (center, zoom, layers, markers)
3. Shows the briefing in the BriefingPanel

Follow the existing Panel pattern from `src/components/Panel.ts`. Use `h()` from `src/utils/dom-utils.ts` for DOM creation. Use the existing i18n system for labels.

The component should:
- Fetch `/api/channels/list` on init
- Render a vertical list of channel cards
- Highlight the active channel
- Poll for updates every 60 seconds (or use a manual refresh button)
- Default to `general_montgomery` channel on load

- [ ] **Step 2: Create BriefingPanel component**

File: `src/components/BriefingPanel.ts`

A slide-out panel showing the current channel's briefing. Uses `marked` (already a dependency) to render markdown. Shows:
- Title (large)
- Alert level badge
- Last updated timestamp
- Summary paragraph
- Full body (rendered markdown, scrollable)
- Sources list

The panel is initially hidden. Shows when a channel is selected. Can be dismissed with a close button.

- [ ] **Step 3: Wire into App.ts**

In `src/App.ts`, after the app initializes, create and mount the ChannelSwitcher and BriefingPanel. The exact integration point depends on the App's init pattern - follow how existing panels are added.

The channel switcher needs a reference to the map component (`DeckGLMap.ts`) to apply camera and layer changes. Check how other components interact with the map - likely through a shared app context or event bus.

- [ ] **Step 4: Add channel-aware map state**

When a channel is selected, apply its map state:
- `map.flyTo({ center, zoom, bearing, pitch })` for camera
- Toggle layers on/off based on `channel.map.layers`
- Add markers from `channel.map.markers` as a new deck.gl ScatterplotLayer or IconLayer
- Highlight regions from `channel.map.regions` using the existing GeoJSON country boundary layer

This requires understanding how `DeckGLMap.ts` manages layers. Read it first. The markers should be a new layer added on top of existing layers, not replacing them.

- [ ] **Step 5: Test locally**

```bash
cd ~/.atrophy/services/worldmonitor
npm run dev
```

Push some test channel data, then reload the page. Verify:
- Channel switcher appears in the sidebar
- Clicking a channel moves the map and shows the briefing
- Default channel loads on page open

- [ ] **Step 6: Commit and deploy**

```bash
cd ~/.atrophy/services/worldmonitor
git add src/components/ChannelSwitcher.ts src/components/BriefingPanel.ts src/App.ts
git commit -m "feat: add channel switcher and briefing panel"
git push origin main
```

---

## Phase 2: Knowledge Graph

### Task 7: Automated relationship extraction

**Files (Atrophy repo):**
- Create: `scripts/agents/librarian/relationship_extract.py`

- [ ] **Step 1: Write the extraction script**

```python
#!/usr/bin/env python3
"""Extract entity relationships from briefs using Claude Haiku.

Reads unprocessed briefs from intelligence.db, extracts relationships
between named entities, and stores them in the relationships table.

Tracks processed brief IDs in a state file to avoid re-processing.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_AGENT = os.environ.get("AGENT", "librarian")
_DB_PATH = Path.home() / ".atrophy" / "agents" / "general_montgomery" / "data" / "intelligence.db"
_STATE_PATH = Path.home() / ".atrophy" / "agents" / "general_montgomery" / "data" / "relationship_extract_state.json"
_CLAUDE = Path.home() / ".local" / "bin" / "claude"

RELATIONSHIP_TYPES = [
    "funds", "arms", "allied_with", "opposes", "mediates",
    "sanctions", "commands", "deploys", "hosts", "threatens",
    "negotiates", "trades", "intelligence_shares",
]

EXTRACTION_PROMPT = f"""Extract all relationships between named entities in this intelligence brief.

For each relationship found, output a JSON array of objects with these fields:
- "from_entity": exact entity name as it appears in the text
- "to_entity": exact entity name as it appears in the text
- "type": one of {json.dumps(RELATIONSHIP_TYPES)}
- "confidence": 0.0 to 1.0 (how confident you are this relationship exists based on the text)
- "notes": one sentence of context from the brief

Only include relationships explicitly stated or strongly implied. Do not speculate.
Output ONLY the JSON array, no other text. If no relationships found, output [].
"""


def load_state() -> set[int]:
    """Load set of already-processed brief IDs."""
    if _STATE_PATH.exists():
        try:
            return set(json.loads(_STATE_PATH.read_text()))
        except (json.JSONDecodeError, TypeError):
            pass
    return set()


def save_state(processed: set[int]) -> None:
    """Persist processed brief IDs."""
    _STATE_PATH.write_text(json.dumps(sorted(processed)))


def get_unprocessed_briefs(db: sqlite3.Connection, processed: set[int]) -> list[dict]:
    """Fetch briefs not yet processed for relationship extraction."""
    cur = db.execute("SELECT id, title, content FROM briefs ORDER BY id")
    briefs = []
    for row in cur.fetchall():
        if row[0] not in processed:
            briefs.append({"id": row[0], "title": row[1], "content": row[2]})
    return briefs


def resolve_entity(db: sqlite3.Connection, name: str) -> int | None:
    """Find entity ID by exact or fuzzy name match."""
    # Exact match first
    cur = db.execute("SELECT id FROM entities WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    # Case-insensitive match
    cur = db.execute("SELECT id FROM entities WHERE LOWER(name) = LOWER(?)", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    # Substring match (entity name contains the search term or vice versa)
    cur = db.execute(
        "SELECT id FROM entities WHERE LOWER(name) LIKE ? OR ? LIKE '%' || LOWER(name) || '%' LIMIT 1",
        (f"%{name.lower()}%", name.lower()),
    )
    row = cur.fetchone()
    return row[0] if row else None


def extract_relationships(brief_text: str) -> list[dict]:
    """Call Claude Haiku to extract relationships from brief text."""
    prompt = f"{EXTRACTION_PROMPT}\n\n---\nBRIEF:\n{brief_text[:8000]}"
    try:
        result = subprocess.run(
            [str(_CLAUDE), "--model", "haiku", "--print", "--no-input", "-p", prompt],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            log.warning("Claude call failed: %s", result.stderr[:200])
            return []
        # Parse JSON from output
        output = result.stdout.strip()
        # Handle markdown code blocks
        if output.startswith("```"):
            output = output.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(output)
    except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("Extraction failed: %s", exc)
        return []


def store_relationships(db: sqlite3.Connection, brief_id: int, relationships: list[dict]) -> int:
    """Store extracted relationships in intelligence.db. Returns count stored."""
    stored = 0
    for rel in relationships:
        confidence = rel.get("confidence", 0.5)
        if confidence < 0.6:
            continue  # skip low-confidence extractions

        from_id = resolve_entity(db, rel.get("from_entity", ""))
        to_id = resolve_entity(db, rel.get("to_entity", ""))
        if not from_id or not to_id or from_id == to_id:
            continue

        rel_type = rel.get("type", "")
        if rel_type not in RELATIONSHIP_TYPES:
            continue

        try:
            db.execute(
                """INSERT OR IGNORE INTO relationships
                   (from_id, to_id, type, confidence, notes, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (from_id, to_id, rel_type, confidence, rel.get("notes", ""), f"brief:{brief_id}"),
            )
            stored += 1
        except sqlite3.IntegrityError:
            pass

    db.commit()
    return stored


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not _DB_PATH.exists():
        log.error("intelligence.db not found at %s", _DB_PATH)
        return

    processed = load_state()
    db = sqlite3.connect(str(_DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")

    try:
        briefs = get_unprocessed_briefs(db, processed)
        if not briefs:
            log.info("No unprocessed briefs")
            return

        log.info("Processing %d unprocessed briefs", len(briefs))
        total_stored = 0

        for brief in briefs:
            log.info("Extracting from brief %d: %s", brief["id"], brief["title"][:60])
            rels = extract_relationships(brief["content"])
            if rels:
                count = store_relationships(db, brief["id"], rels)
                total_stored += count
                log.info("  -> %d relationships extracted, %d stored", len(rels), count)
            processed.add(brief["id"])

        save_state(processed)
        log.info("Done. %d new relationships stored from %d briefs", total_stored, len(briefs))
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test with existing briefs**

```bash
cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron"
AGENT=librarian PYTHONPATH="." python3 scripts/agents/librarian/relationship_extract.py
```

Check the output - should process 34 existing briefs and extract relationships. Verify in the database:

```bash
sqlite3 ~/.atrophy/agents/general_montgomery/data/intelligence.db "SELECT COUNT(*) FROM relationships"
```

- [ ] **Step 3: Register as a librarian cron job**

Add to Montgomery's manifest (`~/.atrophy/agents/general_montgomery/data/agent.json`) or to the librarian's jobs if it has a separate manifest. For now, add to the defence org's librarian config:

```json
"relationship_extract": {
  "cron": "30 * * * *",
  "script": "scripts/agents/librarian/relationship_extract.py",
  "description": "Extract entity relationships from new briefs - runs half-hourly"
}
```

- [ ] **Step 4: Commit**

```bash
git add scripts/agents/librarian/relationship_extract.py
git commit -m "feat: automated relationship extraction from briefs"
```

---

### Task 8: Knowledge sync utility

**Files (Atrophy repo):**
- Create: `scripts/agents/shared/knowledge_sync.py`

- [ ] **Step 1: Write the sync script**

```python
#!/usr/bin/env python3
"""Sync intelligence.db entities, relationships, conflicts, and briefs
to worldmonitor.atrophy.app for visualization.

Pushes to /api/knowledge/sync and /api/meridian/sync endpoints.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".atrophy" / "agents" / "general_montgomery" / "data" / "intelligence.db"
_BASE_URL = os.environ.get("CHANNEL_BASE_URL", "https://worldmonitor.atrophy.app")
_API_KEY = os.environ.get("CHANNEL_API_KEY", "")
_TIMEOUT = 30


def _put(path: str, data: dict) -> bool:
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Channel-Key", _API_KEY)
    try:
        resp = urllib.request.urlopen(req, timeout=_TIMEOUT)
        return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError) as exc:
        log.warning("Sync push failed for %s: %s", path, exc)
        return False


def export_knowledge(db: sqlite3.Connection) -> dict:
    """Export entities, relationships, conflicts, conflict_actors as JSON."""
    entities = []
    for row in db.execute("SELECT id, name, aliases, type, subtype, parent_id, description, status FROM entities").fetchall():
        entities.append({
            "id": row[0], "name": row[1],
            "aliases": json.loads(row[2]) if row[2] else [],
            "type": row[3], "subtype": row[4],
            "parent_id": row[5], "description": row[6], "status": row[7],
        })

    relationships = []
    for row in db.execute("SELECT id, from_id, to_id, type, confidence, notes, source FROM relationships").fetchall():
        relationships.append({
            "id": row[0], "from_id": row[1], "to_id": row[2],
            "type": row[3], "confidence": row[4], "notes": row[5], "source": row[6],
        })

    conflicts = []
    for row in db.execute("SELECT id, name, slug, region, status, description FROM conflicts").fetchall():
        conflicts.append({
            "id": row[0], "name": row[1], "slug": row[2],
            "region": row[3], "status": row[4], "description": row[5],
        })

    conflict_actors = []
    for row in db.execute("SELECT conflict_id, entity_id, alignment, side FROM conflict_actors").fetchall():
        conflict_actors.append({
            "conflict_id": row[0], "entity_id": row[1],
            "alignment": row[2], "side": row[3],
        })

    return {
        "entities": entities,
        "relationships": relationships,
        "conflicts": conflicts,
        "conflict_actors": conflict_actors,
    }


def export_briefs(db: sqlite3.Connection) -> dict:
    """Export briefs as JSON."""
    briefs = []
    for row in db.execute("SELECT id, conflict_id, date, title, content, requested_by, sources, created_at FROM briefs").fetchall():
        briefs.append({
            "id": row[0], "conflict_id": row[1], "date": row[2],
            "title": row[3], "content": row[4], "requested_by": row[5],
            "sources": json.loads(row[6]) if row[6] else [],
            "created_at": row[7],
        })
    return {"briefs": briefs}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not _DB_PATH.exists():
        log.error("intelligence.db not found")
        return

    db = sqlite3.connect(str(_DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")

    try:
        knowledge = export_knowledge(db)
        log.info(
            "Exporting: %d entities, %d relationships, %d conflicts",
            len(knowledge["entities"]),
            len(knowledge["relationships"]),
            len(knowledge["conflicts"]),
        )

        if _put("api/knowledge/sync", knowledge):
            log.info("Knowledge sync OK")
        else:
            log.error("Knowledge sync FAILED")

        briefs = export_briefs(db)
        log.info("Exporting: %d briefs", len(briefs["briefs"]))

        if _put("api/meridian/sync", briefs):
            log.info("Meridian sync OK")
        else:
            log.error("Meridian sync FAILED")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/agents/shared/knowledge_sync.py
git commit -m "feat: knowledge and meridian sync to worldmonitor.atrophy.app"
```

---

### Task 9: Knowledge API routes (fork repo)

**Files (fork repo):**
- Create: `api/knowledge/sync.js`
- Create: `api/knowledge/entities.js`
- Create: `api/knowledge/graph.js`
- Create: `api/knowledge/conflicts.js`
- Create: `api/meridian/sync.js`
- Create: `api/meridian/briefs.js`
- Create: `api/meridian/latest.js`

These follow the same pattern as the channel routes. Auth required for PUT/sync. GET routes are public.

Each sync route:
1. Validates `X-Channel-Key`
2. Reads the JSON body
3. Stores in Upstash KV under `knowledge:entities`, `knowledge:relationships`, `knowledge:conflicts`, `knowledge:conflict_actors`, `meridian:briefs`
4. Returns `{ ok: true }`

Each GET route:
1. Reads from Upstash KV
2. Returns JSON

The graph endpoint assembles nodes + edges from entities + relationships for force-directed visualization.

- [ ] **Step 1: Build sync routes** - follow the channel route pattern, just different KV keys
- [ ] **Step 2: Build GET routes** - read from KV, return JSON
- [ ] **Step 3: Test** - run knowledge_sync.py locally, then fetch from the API
- [ ] **Step 4: Commit and deploy**

```bash
cd ~/.atrophy/services/worldmonitor
git add api/knowledge/ api/meridian/
git commit -m "feat: knowledge graph and meridian API routes"
git push origin main
```

---

### Task 10: Entity network map layer (fork repo)

**Files (fork repo):**
- Create: `src/components/EntityNetworkLayer.ts`
- Modify: `src/components/DeckGLMap.ts` (add entity layer)

This adds a new deck.gl layer to the map that renders:
- Entity nodes as labeled circles at geographic coordinates (country centroids for countries, estimated coordinates for orgs)
- Relationship edges as arc lines between entities, colored by type
- Click handler for entity popup (name, type, description, relationships, linked briefs)

This requires:
1. Fetching `/api/knowledge/graph` for nodes + edges
2. Geocoding entities (countries have known centroids; for orgs, use the country they're associated with)
3. Rendering as deck.gl `ScatterplotLayer` (nodes) + `ArcLayer` (edges)

The layer toggles on/off via the channel state - each channel can include `"entity-network"` in its layers list.

- [ ] **Step 1: Create the layer component** - follows deck.gl layer patterns in DeckGLMap.ts
- [ ] **Step 2: Add entity popup** - on click, show entity detail card
- [ ] **Step 3: Wire into the channel system** - channel state controls which entities/relationships are shown
- [ ] **Step 4: Test and deploy**

---

## Phase 3: Meridian + Polish

### Task 11: Meridian pages (fork repo)

**Files (fork repo):**
- Create: `src/components/MeridianIndex.ts`
- Create: `src/components/MeridianBrief.ts`

The Meridian section is accessible via URL: `worldmonitor.atrophy.app/meridian/`

Since WorldMonitor uses URL-state routing (no traditional router), the App.ts needs to detect `/meridian/` paths and render the appropriate component instead of the map view.

**MeridianIndex**: Grid of brief cards showing title, date, track, requesting agent. Filterable by track and date. Links to individual briefs.

**MeridianBrief**: Full brief page with markdown rendering (using `marked`), sidebar with linked entities (clickable), conflict context, and a "View on map" button that switches to the relevant channel.

- [ ] **Step 1: Build index component**
- [ ] **Step 2: Build brief component**
- [ ] **Step 3: Add URL routing in App.ts**
- [ ] **Step 4: Test and deploy**

---

### Task 12: OG image generation (fork repo)

**Files (fork repo):**
- Create: `api/og-channel.js`
- Modify: `index.html` (dynamic OG tags)

When Telegram or other platforms crawl `worldmonitor.atrophy.app/channel/<name>`, they should get a preview card with:
- Map thumbnail showing the channel's current view
- Briefing title overlaid
- Alert level indicator

Use Vercel OG Image Generation (`@vercel/og`) to render a branded card server-side.

- [ ] **Step 1: Create OG image route**
- [ ] **Step 2: Add dynamic OG meta tags** - detect channel from URL, inject per-channel OG tags
- [ ] **Step 3: Test with Telegram** - send a channel URL, verify preview card renders
- [ ] **Step 4: Deploy**

---

### Task 13: MCP tool for channel push

**Files (Atrophy repo):**
- Modify: `mcp/worldmonitor_server.py`

Add `worldmonitor_push_channel` tool so agents can push channel state during inference (not just from cron scripts).

- [ ] **Step 1: Add tool definition to TOOLS list**

```python
{
    "name": "worldmonitor_push_channel",
    "description": (
        "Update the agent's channel on worldmonitor.atrophy.app. "
        "Set map layers, markers, camera position, briefing text, "
        "and alert level. The channel is the agent's public intelligence "
        "view. Use when delivering intelligence updates to make them "
        "visual and shareable. Returns the channel URL."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Briefing title"},
            "summary": {"type": "string", "description": "Brief summary (1-2 sentences)"},
            "body": {"type": "string", "description": "Full briefing text (markdown)"},
            "alert_level": {
                "type": "string",
                "enum": ["normal", "elevated", "critical"],
                "description": "Current alert level",
            },
            "center": {
                "type": "array", "items": {"type": "number"},
                "description": "Map center [lat, lon]",
            },
            "zoom": {"type": "integer", "description": "Map zoom level (1-18)"},
            "layers": {
                "type": "array", "items": {"type": "string"},
                "description": "Active map layer IDs",
            },
            "markers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lon": {"type": "number"},
                        "label": {"type": "string"},
                        "type": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                },
                "description": "Map markers to display",
            },
            "regions": {
                "type": "array", "items": {"type": "string"},
                "description": "ISO country codes to highlight",
            },
        },
        "required": ["title"],
    },
}
```

- [ ] **Step 2: Add handler function**

```python
def handle_push_channel(client: WorldMonitorClient, args: dict) -> str:
    agent = os.environ.get("AGENT", "unknown")
    api_key = os.environ.get("CHANNEL_API_KEY", "")
    base_url = os.environ.get("CHANNEL_BASE_URL", "https://worldmonitor.atrophy.app")

    state = {
        "agent": agent,
        "alert_level": args.get("alert_level", "normal"),
        "briefing": {
            "title": args.get("title", ""),
            "summary": args.get("summary", ""),
            "body_md": args.get("body", ""),
        },
        "map": {},
    }

    if "center" in args:
        state["map"]["center"] = args["center"]
    if "zoom" in args:
        state["map"]["zoom"] = args["zoom"]
    if "layers" in args:
        state["map"]["layers"] = args["layers"]
    if "markers" in args:
        state["map"]["markers"] = args["markers"]
    if "regions" in args:
        state["map"]["regions"] = args["regions"]

    url = f"{base_url}/api/channels/{agent}"
    data = json.dumps(state).encode()
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Channel-Key", api_key)

    try:
        urllib.request.urlopen(req, timeout=15)
        channel_url = f"{base_url}/channel/{agent}"
        return json.dumps({
            "ok": True,
            "url": channel_url,
            "message": f"Channel updated: {channel_url}",
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})
```

- [ ] **Step 3: Register in HANDLERS dict**

```python
HANDLERS["worldmonitor_push_channel"] = handle_push_channel
```

- [ ] **Step 4: Pass CHANNEL_API_KEY in MCP registry**

In `src/main/mcp-registry.ts`, the worldmonitor case:

```typescript
case 'worldmonitor':
  env.WORLDMONITOR_CACHE_DB = path.join(os.homedir(), '.atrophy', 'worldmonitor_cache.db');
  if (process.env.WORLDMONITOR_LOCAL === 'true') {
    env.WORLDMONITOR_BASE_URL = 'http://localhost:5174';
    env.WORLDMONITOR_LOCAL = 'true';
  } else {
    env.WORLDMONITOR_BASE_URL = 'https://api.worldmonitor.app';
    env.WORLDMONITOR_API_KEY = process.env.WORLDMONITOR_API_KEY || '';
  }
  env.CHANNEL_API_KEY = process.env.CHANNEL_API_KEY || '';
  env.CHANNEL_BASE_URL = 'https://worldmonitor.atrophy.app';
  break;
```

- [ ] **Step 5: Commit**

```bash
git add mcp/worldmonitor_server.py src/main/mcp-registry.ts
git commit -m "feat: add worldmonitor_push_channel MCP tool"
```

---

### Task 14: Desktop artefact integration

**Files (Atrophy repo):**
- No new files - agents naturally return URLs in their responses

When Montgomery calls `worldmonitor_push_channel`, it returns a URL like `https://worldmonitor.atrophy.app/channel/general_montgomery`. The existing artefact system in Atrophy detects URLs in agent responses and can render them as clickable links or embedded webviews.

The agent's system prompt should be updated to tell it to include the channel URL when delivering map briefings. This goes in Montgomery's `prompts/system.md`.

- [ ] **Step 1: Add map briefing guidance to Montgomery's system prompt**

Append to `~/.atrophy/agents/general_montgomery/prompts/system.md`:

```markdown
## Map Briefings

When delivering situational updates, use the worldmonitor_push_channel tool to update your channel
on worldmonitor.atrophy.app. Include the channel URL in your response so Will can view the
interactive map. Set appropriate markers, layers, and alert levels to illustrate your briefing.

Your channel URL: https://worldmonitor.atrophy.app/channel/general_montgomery
```

- [ ] **Step 2: Add similar guidance to RF agent prompts** - each agent gets a note about their channel URL

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| Phase 1 (Tasks 1-6) | Deploy, channels, push utility, frontend | Working site with agent channels, live data push |
| Phase 2 (Tasks 7-10) | Relationship extraction, knowledge sync, graph layer | Entity network on map, automated relationship population |
| Phase 3 (Tasks 11-14) | Meridian pages, OG images, MCP tool, prompts | Brief publishing, Telegram previews, inference-driven map updates |

Each phase produces independently working software. Phase 1 is the foundation. Phases 2 and 3 can be built in either order.

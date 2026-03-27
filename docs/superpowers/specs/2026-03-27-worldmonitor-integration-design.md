# WorldMonitor Local Integration

Montgomery's intelligence infrastructure - self-hosted WorldMonitor instance providing API data and an interactive briefing map.

## Context

WorldMonitor (github.com/koala73/worldmonitor) is an open-source intelligence dashboard with 435+ news feeds, military flight tracking, AIS maritime data, GPS jamming, conflict events, economic indicators, and a multi-layer map. The hosted API at api.worldmonitor.app requires an API key. By self-hosting locally, all endpoints become available without auth (localhost is a trusted origin in dev mode).

12 of 16 agent scripts already call WorldMonitor for data. Montgomery manages the instance but all defence org agents benefit.

## 1. Service Lifecycle

### Location

`~/.atrophy/services/worldmonitor/` - shared infrastructure, not agent-scoped.

### First-time setup

1. `git clone https://github.com/koala73/worldmonitor.git ~/.atrophy/services/worldmonitor/`
2. `cd ~/.atrophy/services/worldmonitor && npm install`
3. Write a marker file `.atrophy/services/worldmonitor/.installed` with timestamp

### Boot sequence

On app start (in `src/main/app.ts` boot flow, after MCP discovery):

1. Check if `~/.atrophy/services/worldmonitor/.installed` exists
2. If not installed, skip (user can trigger install via settings or IPC)
3. If installed, spawn `npm run dev -- --port 5174` as a detached child process
4. Health-check loop: poll `http://localhost:5174/api/health` every 2s, up to 30s
5. Once healthy, set `process.env.WORLDMONITOR_LOCAL = 'true'`
6. On app shutdown, send SIGTERM to the process

### Process management

New file: `src/main/services/worldmonitor.ts`

```typescript
export interface WorldMonitorService {
  start(): Promise<boolean>;   // returns true if healthy
  stop(): void;
  isRunning(): boolean;
  getPort(): number;
  install(): Promise<void>;    // clone + npm install
  update(): Promise<void>;     // git pull + npm install if changed
}
```

- Fixed port: 5174 (avoids conflict with Vite dev server on 5173)
- Stdout/stderr piped to `~/.atrophy/logs/worldmonitor.log` (rotated, 5MB cap)
- Auto-restart on crash, max 3 retries then disable until next app launch
- `git pull --ff-only` on boot (before starting) to stay current - skip if offline

### IPC handlers

- `worldmonitor:install` - triggers first-time setup
- `worldmonitor:status` - returns { installed, running, port, pid }
- `worldmonitor:restart` - stop + start
- `worldmonitor:update` - git pull + restart

## 2. MCP Server Update

### Base URL resolution

In `mcp/worldmonitor_server.py`, change the URL resolution order:

1. `WORLDMONITOR_BASE_URL` env var (if explicitly set)
2. `http://localhost:5174` (if `WORLDMONITOR_LOCAL=true`)
3. `https://api.worldmonitor.app` (fallback, requires API key)

### Origin header

When hitting localhost, add `Origin: http://localhost:5174` to all requests. WorldMonitor's API key validator trusts localhost origins in dev mode, so no API key is needed.

### MCP registry update

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
  break;
```

### Python server changes

In `worldmonitor_server.py`:
- Read `WORLDMONITOR_LOCAL` env var
- When local, add `Origin` header to requests
- No API key needed for local requests

## 3. Map Briefing System

### Concept

Montgomery uses the WorldMonitor map as a briefing tool. The map starts blank (or with minimal base layers). When delivering intelligence - via Telegram or desktop - Montgomery can open the map with specific markers, regions, and annotations to illustrate the briefing.

### Canvas integration

The existing Canvas component loads a URL in a webview. For map briefings:

1. Main process builds a briefing URL with query parameters encoding what to show
2. Canvas webview loads `http://localhost:5174?briefing=<encoded>`
3. WorldMonitor's frontend reads the briefing params and renders accordingly

However, WorldMonitor may not support arbitrary query-param-driven rendering out of the box. More reliable approach:

### Briefing overlay (preferred approach)

New file: `src/main/services/worldmonitor-briefing.ts`

1. Montgomery calls a new MCP tool `worldmonitor_show_map` with structured data:
   ```json
   {
     "markers": [
       {"lat": 32.08, "lon": 51.68, "label": "Isfahan", "type": "strike"},
       {"lat": 35.69, "lon": 51.42, "label": "Tehran", "type": "capital"}
     ],
     "regions": ["IR", "IL"],
     "layers": ["military-flights", "oref-alerts"],
     "title": "Israeli strike on Iranian nuclear facility",
     "zoom": { "lat": 33, "lon": 51, "level": 5 }
   }
   ```

2. The briefing system generates a self-contained HTML page:
   - Uses MapLibre GL JS (same as WorldMonitor) with a dark basemap
   - Renders the markers, region highlights, and annotations
   - Includes a title bar with Montgomery's briefing title
   - Optionally pulls live data layers from the local WorldMonitor API

3. The HTML is written to `~/.atrophy/tmp/briefing-<timestamp>.html`

4. Canvas webview loads `file://` path to the briefing HTML

### Why not inject JS into WorldMonitor's webview?

WorldMonitor's frontend is complex (globe.gl, deck.gl, 45 layers, Svelte state). Injecting JS to manipulate its internal state is fragile and would break on updates. A standalone briefing page using the same map library (MapLibre GL) is more reliable and gives us full control over what's displayed.

### MCP tool definition

Add to `mcp/worldmonitor_server.py`:

```python
{
    "name": "worldmonitor_show_map",
    "description": (
        "Open an interactive map briefing in the desktop Canvas overlay. "
        "Pass markers with lat/lon/label/type, region ISO codes to highlight, "
        "data layers to overlay, and a briefing title. The map renders in "
        "the app's Canvas webview."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Briefing title"},
            "markers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lon": {"type": "number"},
                        "label": {"type": "string"},
                        "type": {"type": "string", "enum": ["strike", "capital", "base", "event", "vessel", "flight", "alert"]}
                    },
                    "required": ["lat", "lon", "label"]
                }
            },
            "regions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "ISO country codes to highlight"
            },
            "layers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Data layers to overlay from WorldMonitor API"
            },
            "zoom": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "level": {"type": "number"}
                }
            }
        },
        "required": ["title"]
    }
}
```

### Map rendering

The briefing HTML template uses:
- **MapLibre GL JS** via CDN (same renderer WorldMonitor uses for its 2D map)
- **Dark basemap** matching Atrophy's aesthetic (e.g., CartoDB Dark Matter tiles)
- **Marker types** with distinct icons/colors:
  - `strike` - red pulse
  - `capital` - white diamond
  - `base` - blue square
  - `event` - orange circle
  - `vessel` - cyan triangle
  - `flight` - green arrow
  - `alert` - yellow flash
- **Region highlighting** - GeoJSON country boundaries with semi-transparent fill
- **Data layer overlays** - fetched from local WorldMonitor API and rendered as additional map layers (military flights as moving dots, thermal events as heat markers, etc.)
- **Title bar** - semi-transparent overlay at top with briefing title and timestamp

### Telegram delivery

When Montgomery sends a map briefing via Telegram, the same briefing data is used to generate a static image:
1. Briefing HTML is loaded in a headless webview (or Puppeteer if available)
2. Screenshot taken at 1200x800
3. Sent as a Telegram photo with the briefing title as caption
4. Desktop users also get the interactive Canvas version

If Puppeteer isn't available, fall back to a text description of the map content.

## 4. Data Flow

```
Boot:
  app.ts -> worldmonitor.start() -> npm run dev on :5174
  app.ts -> mcpRegistry (WORLDMONITOR_LOCAL=true)
  app.ts -> wireAgent (worldmonitor MCP server gets localhost URL)

Intelligence cycle:
  cron job fires (e.g. three_hour_update.py)
    -> imports WorldMonitorClient
    -> fetch_cached("api/military-flights") hits localhost:5174
    -> data returned, delta computed
    -> output routed to Montgomery via switchboard

Briefing:
  Montgomery decides to brief (via inference response)
    -> calls worldmonitor_show_map MCP tool
    -> briefing HTML generated with MapLibre GL
    -> IPC: canvas:show with file:// URL
    -> Canvas webview renders interactive map
    -> (optional) screenshot for Telegram delivery
```

## 5. Files to Create/Modify

### New files

| File | Purpose |
|------|---------|
| `src/main/services/worldmonitor.ts` | Service lifecycle - install, start, stop, health check |
| `src/main/services/worldmonitor-briefing.ts` | Map briefing HTML generation |
| `src/main/ipc/worldmonitor.ts` | IPC handlers for install/status/restart |

### Modified files

| File | Change |
|------|--------|
| `src/main/app.ts` | Add worldmonitor.start() to boot sequence |
| `src/main/ipc/system.ts` | Register worldmonitor IPC handlers |
| `mcp/worldmonitor_server.py` | Add Origin header for local, add show_map tool handler, update base URL resolution |
| `src/main/mcp-registry.ts` | Pass WORLDMONITOR_LOCAL env to MCP server |

### Not modified (no changes needed)

All 16 agent scripts - they already use `WorldMonitorClient.fetch_cached()` which respects the base URL from env. Once the service is running on localhost, they work automatically.

## 6. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| npm install takes minutes on first run | Show progress in settings UI, non-blocking |
| WorldMonitor updates break API | Pin to a known-good commit tag, update manually |
| Port 5174 conflicts | Make port configurable via config.json |
| Large disk footprint (~200MB node_modules) | Document in setup, user's choice to install |
| Map tiles need internet | MapLibre uses online tile servers - map is blank offline |

## 7. Build Order

1. Service lifecycle (`worldmonitor.ts`) - install, start, stop
2. MCP server updates - Origin header, local URL resolution
3. Boot sequence integration - start on launch
4. Map briefing HTML generator
5. show_map MCP tool + IPC wiring
6. Canvas integration for map display
7. Telegram static image fallback (stretch goal)

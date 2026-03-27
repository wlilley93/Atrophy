# Meridian Institute - A Living Intelligence Map

The map breathes. It shows a living picture of the world as understood by an intelligence team that never sleeps. Every pulse, every glow, every connection line reflects real analytical work happening underneath - cron jobs polling, agents analyzing, the ontology growing.

---

## Core Experience

You open meridian.atrophy.app. A dark globe fills the screen edge to edge. Hotspots pulse where things are happening - warmer where multiple signals converge. Montgomery's one-line assessment floats at the top. The overall color temperature of the map IS the threat level - you feel it before you read anything.

Click a hotspot. A drawer doesn't show you a wiki page - it loads Montgomery's context and you're in conversation with the analyst who owns that domain. "That's the 72nd Mechanized Brigade. They've been in this position since February. Three briefs mention them." You follow up. He pulls from the graph. The map highlights what he's talking about.

Switch channels. The globe rotates to a new theater. Different layers light up. Different hotspots appear. The analyst quote changes. You're looking through a different analyst's eyes at their piece of the world.

The map never leaves. Everything else serves it.

---

## Visual Language

### The Map Breathes

The map is not a static picture. It has a metabolism.

**Pulse:** Hotspots pulse with activity - faster when events are recent, slower as they age. A fresh ACLED event pulses rapidly. Yesterday's event hums gently. Last week's is a faint glow.

**Color temperature:** The global color palette shifts with threat level. NORMAL: cool blues and dark greys. ELEVATED: amber warmth creeps in. CRITICAL: red heat blooms from conflict zones. You feel the state of the world in the color of the map before reading a single word.

**Flow:** Flight tracks leave fading contrails - ghostly traces showing where aircraft have been. Vessel tracks show directional flow with animated particles. Arms transfer arcs pulse with flowing light showing direction. The map has movement even when nothing is happening right now.

**Stillness:** When a region is calm, it's genuinely dark and still. The contrast makes active zones pop. Silence is information too.

### Convergence Rings

When multiple signals overlap geographically - military flights + thermal signatures + ACLED events in the same area - the map draws a convergence ring. Concentric circles ripple outward from the overlap zone. This is the cross-agent synthesis made visible. If SIGINT sees flights, RF sees conflicts, and the thermal layer shows heat - all in the same 50km radius - that convergence ring appears automatically. Montgomery's nightly synthesis might confirm what the map already showed.

### Connection Lines

Hover over any entity and faint lines connect it to its ontology relationships:
- **Red:** arms supply, adversarial
- **Amber:** alliance, cooperation
- **Blue:** membership, command hierarchy
- **Gold:** economic, trade
- **White:** neutral (borders, located_at)

Lines are directional (animated flow particles). Thickness reflects confidence score. The map becomes the knowledge graph rendered geographically. Iran lights up like a spiderweb - arms to Houthis, alliance with Russia, opposition to Israel, nuclear tensions with the US. All visible in one hover.

### Entity Glow

Objects with more ontology connections glow brighter on the map. Iran (4 conflicts, dozens of relationships) burns hotter than an isolated airbase. Network centrality as luminosity. The most connected, most important nodes are visually obvious without reading any text.

### Threat Rings

The 8 geofence watch zones render as subtle sonar-like concentric rings on the map. Hormuz, Taiwan Strait, the contact line, Suez, Baltic approaches, Red Sea, Black Sea, Kaliningrad. When the geofencing system detects an event inside a zone, the rings pulse outward like sonar. Dormant zones are barely visible. Active zones pulse.

### Ghost Trails

Time slider at the bottom of the map. Scrub backwards and see where things were:
- Flight paths that faded
- Vessel positions from last week
- Conflict events that appeared and resolved
- Troop positions that shifted

The map has memory. You can watch a situation develop over days. Play it forward at speed and see the pattern. This is how you spot slow-moving changes that individual snapshots miss.

### Prediction Markers

Different from confirmed events. Rendered as dashed circles, translucent, with a confidence percentage label. "We assessed 3 weeks ago that Kherson would escalate - here's the prediction zone." As time passes and evidence accumulates, the marker either solidifies (becoming opaque, turning solid) or fades away (wrong). The map shows what you THINK as well as what you KNOW. Open predictions from the prediction ledger are placed geographically.

### Intelligence Density

Areas where the ontology has more objects glow subtly warmer in the basemap. Areas with less coverage stay genuinely dark. You can literally see your blind spots. Central Asia is dark? That's a gap. The Sahel has three dots? That's underweight coverage. This naturally drives commission requests for more intelligence.

---

## The Chat - Not a Sidebar, the Map's Voice

This is the interaction model that makes Meridian different from every other map tool.

### Click to Converse

Click any entity on the map (base, chokepoint, vessel, conflict event, person marker, city, infrastructure). The system:

1. **Fetches the full ontology profile** - object + all properties + all links + all briefs mentioning it + recent events nearby
2. **Injects into a conversation context** - "User clicked on [entity]. Full profile: [data]. Related briefs: [summaries]. Active channel: [current channel]. Answer their questions using this context, the ontology, and your analytical judgment."
3. **Chat panel slides up from the bottom of the map** - compact, 30% height, transparent background. The map is still visible above.
4. **The analyst speaks** - Montgomery (or the relevant channel's agent) responds with live analysis grounded in the ontology. Not canned text. Real inference.

### Follow-up is Natural

"What happened here last month?" - agent queries the timeline.
"Who commands this unit?" - agent traverses the ontology graph.
"Is this related to the Hormuz situation?" - agent finds connections.
"Write me a brief on this." - agent generates a SITREP, posts to the reading room, pushes to the channel.

### Desktop Integration

When meridian.atrophy.app is loaded in the Atrophy desktop app's Canvas/Artefact overlay:
- Clicking an entity sends the context back to the main conversation via IPC
- Montgomery responds in the desktop chat, not a web panel
- The map highlights what he's discussing
- Two-way: Montgomery can push map state during conversation ("let me show you") and the Canvas updates

### Telegram Integration

Montgomery can share a map view via Telegram:
- Generates a static image (screenshot of current map state with markers and briefing overlay)
- Sends as photo with briefing text as caption
- Link to the live interactive version at meridian.atrophy.app/channel/...
- OG preview card shows the map thumbnail

---

## Briefing Mode

Montgomery can "present" - the globe auto-animates through a sequence of views.

1. Montgomery writes a briefing with geographic waypoints
2. The map steps through each waypoint: globe rotates, layers change, markers appear
3. At each stop, the analyst quote updates with the assessment for that region
4. Timing: 5-8 seconds per waypoint, smooth transitions

Use cases:
- **Morning brief delivery** - the three-hour update becomes a visual walkthrough
- **Flash report** - map snaps to the event, zooms in, shows the impact radius
- **Weekly digest** - a 2-minute tour of all six tracks with globe rotation

For Telegram: render the briefing mode as a short video (headless browser screenshot sequence -> ffmpeg). Send as video message with summary caption.

---

## Sound Design (Optional, Toggleable)

Subtle ambient audio that reflects the map's state. Off by default. Toggle via gear icon.

- **Baseline:** Very low ambient hum. Barely perceptible. Changes pitch slightly with global threat level.
- **New ACLED event:** Low percussive tone. Deeper for higher fatalities.
- **OREF alert:** Sharp ascending ping. Urgent.
- **Thermal cluster detected:** Deep vibration, like distant thunder.
- **GPS jamming zone:** Electronic warble, subtle.
- **New brief published:** A soft chime, like a document being placed on a desk.
- **Channel switch:** Subtle whoosh, like adjusting a radio dial.
- **Convergence ring:** Resonant harmonic - two tones merging.

The site can be "listened to" in the background. You're working on something else and hear the pitch shift. Something happened.

---

## Typewriter Briefing Delivery

When a new brief publishes (cron job fires, agent produces output):
- The channel tab pulses gently
- The analyst quote fades out and types in the new assessment, character by character
- New markers fade in on the map at their locations
- The mini briefing card updates with a slide transition

It feels like someone just walked into the briefing room with a report. Not a notification. A presence.

---

## Night Watch Mode

After midnight (user's timezone or configurable), the interface shifts:
- Map dims further - only CRITICAL items glow
- Channel tabs collapse to just alert dots
- Analyst quote only shows if alert level is ELEVATED or CRITICAL
- Layer toggles hidden
- The screen is almost entirely dark globe with occasional pulses

This is "would I wake someone up for this" mode. If a flash report fires at 3am, the map blooms with red and the OREF ping sounds. Otherwise, silence and darkness.

At dawn, the interface gradually unfolds back to full situational awareness. The morning brief types in.

---

## Layout

### Default State (map only)

```
+------------------------------------------------------------------+
|  MERIDIAN INSTITUTE         [____search____]  [ELEVATED] [G] [S] |
+------------------------------------------------------------------+
|  MONTGOMERY | RU-UA | GULF | SIGINT | ECON | EU | INDOPAC | ...  |
+------------------------------------------------------------------+
|                                                                   |
|  "Kherson axis under pressure.          (analyst quote, top-left) |
|   Three thermal clusters detected."                               |
|                                                                   |
|                                                                   |
|                    FULL SCREEN MAP                                |
|               deck.gl / MapLibre / globe.gl                       |
|                                                                   |
|          [hotspots pulsing]  [flight contrails]                   |
|          [convergence rings] [threat sonar]                       |
|                                                                   |
|                                                                   |
|                                        +------------------------+|
|                                        | Latest: 14:30 UTC      ||
|                                        | Kherson Axis Update    ||
|                                        | [expand v]             ||
|                                        +------------------------+|
+------------------------------------------------------------------+
|  [mil flights] [conflicts] [thermal] [GPS jam] [vessels] [+more] |
+------------------------------------------------------------------+
```

### Briefing Drawer Open

```
+------------------------------------------------------------------+
|  MERIDIAN INSTITUTE         [____search____]  [ELEVATED] [G] [S] |
+------------------------------------------------------------------+
|  MONTGOMERY | RU-UA | GULF | SIGINT | ECON | EU | INDOPAC | ...  |
+------------------------------------------------------------------+
|                                    |                              |
|                                    |  BRIEFING                [x]|
|                                    |  ========================   |
|           MAP                      |  [ELEVATED] 14:30 UTC      |
|      (shifts left,                 |                              |
|       still interactive)           |  Kherson Axis Update         |
|                                    |                              |
|                                    |  Three thermal clusters      |
|                                    |  detected along the contact  |
|                                    |  line correlating with       |
|                                    |  ammunition depot activity   |
|                                    |  observed in SIGINT...       |
|                                    |                              |
|                                    |  [Listen] [Full brief]       |
|                                    |  ========================   |
|                                    |  ENTITIES                    |
|                                    |  [72nd Mech Bde] [Kherson]  |
|                                    |  [Russia] [Ukraine]          |
|                                    |  ========================   |
|                                    |  RECENT EVENTS               |
|                                    |  - Thermal cluster (2h ago)  |
|                                    |  - ACLED: Shelling (5h ago)  |
+------------------------------------------------------------------+
|  [mil flights] [conflicts] [thermal] [GPS jam] [vessels] [+more] |
+------------------------------------------------------------------+
```

### Chat Active (entity clicked)

```
+------------------------------------------------------------------+
|  MERIDIAN INSTITUTE         [____search____]  [ELEVATED] [G] [S] |
+------------------------------------------------------------------+
|  MONTGOMERY | RU-UA | GULF | SIGINT | ECON | EU | INDOPAC | ...  |
+------------------------------------------------------------------+
|                                                                   |
|                                                                   |
|                    MAP (full width, upper 70%)                    |
|                                                                   |
|                    [clicked entity highlighted]                   |
|                    [connection lines radiating]                   |
|                                                                   |
+------------------------------------------------------------------+
|  MONTGOMERY on 72nd Mechanized Brigade                           |
|  "That's the 72nd Mech. They've held this position since Feb.   |
|   Three briefs mention them. Latest assessment from RF            |
|   Russia-Ukraine suggests staging for a push north."             |
|                                                                   |
|  [You]: What's their current strength?                           |
|  [Montgomery]: According to the ontology, the 72nd is a          |
|   brigade-level unit subordinate to the Ukrainian Ground Forces...|
|                                                                   |
|  [____type a question____________________________] [send]        |
+------------------------------------------------------------------+
```

---

## Pages

### / (Home)
The map. Montgomery's channel. The default experience described above.

### /channel/:name
Same map, different channel active. URL-shareable.

### /meridian (Reading Room)
Full-page overlay (map dims behind). Grid of published intelligence products.
- Filter: product type, agent, conflict, date range, verification score
- Cards: title, type badge (SITREP/FLASH/WARNING/etc), agent, date, first line, verification score, audio icon
- Click: opens full brief

### /meridian/brief/:id
Full brief page with markdown rendering, entity chips (clickable - highlights on map), red team review, audio player, "View on map" button.

### /graph
Full-screen force-directed knowledge graph. Nodes colored by type, edges by relationship. Search + filter. Click node to expand. "View on map" for geolocated entities.

### /graph/entity/:id
Entity dossier. Properties table, relationship list, changelog timeline, linked briefs, location on map.

### /timeline/:conflict
Horizontal timeline of situation assessments. Color-coded trajectory. Click entries for detail.

### /health
Source health grid. Green/amber/red status for all data sources.

### /accuracy
Prediction ledger. Outcomes, per-agent accuracy, trend charts.

### /metrics
Agent performance scorecards.

### /commissions
Submit intelligence questions. Track status. View responses.

---

## What to Strip from WorldMonitor

Remove entirely: Bloomberg TV, webcams (both), Pro banner, Discord widget, variant switcher, GitHub badge, author credits, blog links, download buttons, Clerk auth, Umami analytics, stock analysis, backtesting, crypto/stablecoins/BTC ETF, layoffs tracker, AI/ML panel, Big Mac/grocery/fuel/consumer prices, world clock, earnings/economic calendar, COT positioning, Gulf economies, daily market brief, fear and greed, financial stress, yield curve, sector heatmap, My Monitors.

Keep: map engine (deck.gl, MapLibre, globe.gl), military/conflict/intelligence data layers, country click, intel feed (in drawer), CORS/API infrastructure, dark theme, responsive foundations.

---

## Implementation Phases

### Phase 1: Strip and map-first (2 days)
1. Remove everything from the strip list
2. Map 100% viewport, edge to edge
3. Floating header: "MERIDIAN INSTITUTE" + search + alert level
4. Channel tabs floating below header
5. Analyst quote overlay (top-left)
6. Mini briefing card (bottom-right)
7. Layer toggles as floating bottom bar
8. Deploy clean

### Phase 2: Briefing drawer + interactions (2 days)
9. Briefing drawer slides from right on expand/hotspot click
10. Full markdown rendering with entity chips
11. Entity popup on map click (properties + links summary)
12. Connection lines on hover (ontology relationships rendered as arcs)
13. Country click loads ontology profile
14. Linked entity highlighting from drawer
15. Audio player in drawer

### Phase 3: Living map visuals (2 days)
16. Hotspot pulse animation (decay over time)
17. Color temperature shift with threat level
18. Flight contrails (fading trails)
19. Convergence ring detection and rendering
20. Entity glow (network centrality as luminosity)
21. Threat ring sonar around watch zones
22. Prediction markers (dashed, translucent, with confidence)
23. Intelligence density subtle heatmap on basemap

### Phase 4: Chat interface (2 days)
24. Chat panel slides up from bottom on entity click
25. Ontology context injection into prompt
26. Streaming response rendering
27. Map highlights what analyst discusses
28. Desktop IPC bridge (Canvas -> main conversation)
29. Follow-up conversation flow

### Phase 5: Time and motion (1 day)
30. Ghost trails (time slider scrub)
31. Briefing mode (auto-animated waypoint tour)
32. Typewriter briefing delivery animation
33. Night watch mode (time-of-day adaptation)

### Phase 6: Reading room + graph (2 days)
34. /meridian reading room index
35. /meridian/brief/:id full brief page
36. /graph force-directed visualization
37. /graph/entity/:id dossier page
38. Ontology search autocomplete in header

### Phase 7: Dashboards + polish (2 days)
39. /timeline/:conflict
40. /health source dashboard
41. /accuracy prediction ledger
42. /metrics performance scorecards
43. /commissions portal
44. OG images for Telegram previews
45. Sound design (optional, toggleable)
46. Keyboard shortcuts
47. Mobile responsive
48. Performance optimization

---

## Technical Notes

### Map Rendering

The living visual effects (pulse, glow, convergence, contrails) are deck.gl custom layers or post-processing effects. deck.gl supports:
- `ScatterplotLayer` with animated radius for pulsing
- `ArcLayer` with animated flow for connection lines and arms transfers
- `PathLayer` with trail decay for flight contrails
- `HeatmapLayer` for intelligence density
- Custom shaders for glow effects
- `TripsLayer` for temporal animation (ghost trails)

The color temperature shift can be done via a CSS filter on the map container or by adjusting the basemap opacity/tint.

### Chat Backend

The chat on the web needs a backend to run inference. Options:
- **Claude API directly** - the site calls Claude API with the ontology context. Requires an API key server-side (Vercel Edge Function).
- **Proxy through Atrophy** - the site sends the question to a Vercel function that proxies to the Atrophy HTTP server (if running), which runs inference through the existing Claude CLI.
- **MCP proxy** - WorldMonitor already has an `api/mcp-proxy.js` route. Could proxy to the MCP memory server.

Simplest: a Vercel Edge Function (`api/chat.js`) that takes the entity context + user question, calls Claude API (Haiku for speed), returns the response. The ANTHROPIC_API_KEY goes in Vercel env vars.

### Performance

With 5,600+ objects potentially on the map, clustering is essential:
- Use Supercluster (already a WorldMonitor dependency) for marker clustering at low zoom
- Only render detail markers when zoomed in enough
- Entity glow computed once per data refresh, not per frame
- Ghost trails use pre-computed path data, not real-time queries
- Connection lines only render on hover (not all 6,000 links at once)

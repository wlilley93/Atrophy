# Meridian Eye - A Living Intelligence Map

The map is a game. Not a dashboard you read - an environment you move through. Free camera, clickable units, game-style HUD, your intelligence advisor in a portrait frame telling you what matters. Think Empire Total War's campaign map meets a classified briefing room.

Briefings are cinematic. Letterbox bars slide in, the camera sweeps across theaters, units animate along their historical paths showing time passing, and Montgomery narrates over the top. When it ends, the bars retract and you're back in control.

The map breathes. It shows a living picture of the world as understood by an intelligence team that never sleeps. Every pulse, every glow, every connection line reflects real analytical work - cron jobs polling, agents analyzing, the ontology growing, 6,322 objects linked by 7,218 relationships.

---

## Core Experience

### Entry: Orbital Descent

You load meridian.atrophy.app. You don't see a map. You see Earth from space - a satellite view, slowly rotating. Data feeds stream down from orbit like faint rain. You click or scroll and the camera DIVES through the atmosphere, punching through clouds, and lands on Montgomery's current focus area. Every session starts with this 3-second descent. It sets the tone: you're looking down at the world from above.

### Default: The Campaign Map

A dark 3D globe fills the screen edge to edge. Free camera - orbit, zoom, tilt, rotate with mouse/trackpad. WASD to pan. Hotspots pulse where things are happening. Units sit on their deployment locations as clickable figurines. Montgomery's portrait glows in the corner. His one-line assessment floats at the top.

The overall color temperature of the map IS the threat level. NORMAL: cool blues and dark greys. ELEVATED: amber warmth creeps in. CRITICAL: red heat blooms from conflict zones. You feel the state of the world in the color before reading anything.

### Interaction: Click to Converse

Click any entity on the map. Montgomery's portrait activates. The entity's full ontology profile loads silently. You're in conversation with the analyst who owns that domain. "That's the 72nd Mechanized Brigade. They've held this position since February. Three briefs mention them." You follow up. He pulls from the graph. The map highlights what he's discussing.

This is not a tooltip. Not a wiki popup. A conversation with a commander who knows the entire knowledge graph.

---

## Cinematic Briefings

The signature feature. When a briefing plays, the map becomes a movie.

### How it works

1. **Letterbox bars** slide in from top and bottom (16:9 cinematic crop)
2. **Camera begins moving** - smooth, cinematic pans across the globe following a scripted path
3. **Montgomery's voice narrates** (ElevenLabs TTS) - the briefing text plays as audio
4. **Units animate** - military formations slide along paths showing movements over the briefing period. Fleets reposition. Aircraft trace routes. The map shows time passing.
5. **Events pop** as the camera passes them - ACLED events spark, thermal clusters bloom, OREF alerts flash
6. **Entity cards** slide in from the edge when mentioned - a country card, a unit card, a leader card. Brief on-screen appearances synced to the narration.
7. **Connection lines** draw themselves between entities as relationships are discussed - "Iran supplies..." and an arc lights up from Tehran to Sanaa
8. **Convergence rings** ripple when the narration identifies pattern overlaps
9. **At each waypoint**, the camera holds for 3-5 seconds while the relevant assessment plays. Markers and layers for that region activate.
10. **Ending:** Camera pulls back to full globe view, letterbox bars retract, you're in control again - positioned at the highest-alert theater

### Briefing data structure

Each briefing defines waypoints that drive the cinematic:

```json
{
  "waypoints": [
    {
      "lat": 48.5, "lon": 37.0, "zoom": 6, "bearing": 30, "pitch": 45,
      "duration_sec": 8,
      "narration": "The contact line near Kherson shows three new thermal clusters...",
      "layers": ["thermal-escalations", "acled-events"],
      "markers": [{"lat": 46.6, "lon": 32.6, "label": "Kherson", "type": "event"}],
      "entities": [72, 89, 45],
      "unit_movements": [
        {"unit_id": 234, "from": [48.0, 36.5], "to": [48.3, 37.1], "type": "advance"}
      ]
    },
    {
      "lat": 26.5, "lon": 56.2, "zoom": 7, "bearing": -20, "pitch": 40,
      "duration_sec": 6,
      "narration": "In the Strait of Hormuz, SIGINT detected increased IRGC-Navy activity...",
      "layers": ["military-flights", "ais-vessels"],
      "entities": [156, 78],
      "connections": [{"from": 156, "to": 78, "type": "operates"}]
    }
  ],
  "ending": {
    "lat": 30, "lon": 30, "zoom": 2,
    "summary": "Global threat level: ELEVATED. Primary concern: Kherson convergence."
  }
}
```

### When briefings play

- **Morning brief** (07:00) - auto-plays on page load if the brief is fresh
- **Flash reports** - play immediately when they arrive, interrupting whatever you're doing
- **Three-hour updates** - available as a "Play briefing" button, don't auto-play
- **On demand** - click "Play" on any brief in the reading room
- **Daily debrief** (configurable) - 60-second automated flyover of all active theaters

### Generating briefing cinematics

When an agent produces a brief:
1. The brief text is parsed for geographic references (entity names with known lat/lon)
2. Waypoints are generated automatically from the sequence of locations mentioned
3. Unit movements are derived from ontology changes (positions that shifted between the last two data polls)
4. Entity cards are queued for any entities mentioned in the text
5. Connection lines are drawn from any relationships referenced
6. The camera path is smoothed with bezier curves between waypoints

For flash reports, the cinematic is simpler: camera snaps to the event location, zooms in fast, holds, Montgomery speaks the alert. No leisurely tour - urgent.

### Export

Briefing cinematics can be exported as video:
- Headless browser renders the WebGL canvas frame by frame
- TTS audio mixed in
- Output: MP4, 1080p, 30fps
- Duration: 30-120 seconds depending on waypoint count
- Sent to Telegram as a video message
- Also available as a shareable link that auto-plays the cinematic

---

## Visual Language

### The Map Breathes

**Pulse:** Hotspots pulse with activity - faster when events are recent, slower as they age. A fresh ACLED event pulses rapidly. Yesterday's event hums gently. Last week's is a faint glow.

**Color temperature:** Global palette shifts with threat level. NORMAL: cool blues and dark greys. ELEVATED: amber warmth creeps in. CRITICAL: red heat blooms. You feel the state of the world before reading.

**Flow:** Flight tracks leave fading contrails. Vessel tracks show directional flow with animated particles. Arms transfer arcs pulse with flowing light. The map has movement even in quiet times.

**Stillness:** Calm regions are genuinely dark and still. The contrast makes active zones pop. Silence is information.

### Fog of War

Areas where the ontology has poor coverage are fogged. Animated fog/clouds rolling over regions. Full intelligence coverage = clear terrain. Sparse coverage = thick fog. The Sahel is foggy with 3 objects. Western Europe is crystal clear. Blind spots are viscerally obvious. Drives commission requests naturally: "Why is Central Asia fogged? Can we get coverage there?"

### Unit Figurines

Military units rendered as miniature figurines on deployment locations. Infantry icons for ground forces, ship silhouettes for naval, aircraft profiles for air bases. Grouped by allegiance color (blue for allied, red for adversary, gold for neutral). Click a figurine to get the unit's ontology profile loaded into conversation. During cinematic briefings, figurines animate along movement paths.

### Territory Control

Countries and regions colored by faction control. Russia-controlled in one shade, Ukrainian-controlled in another, disputed zones in crosshatch. Sahel shows junta vs government zones. Gaza/West Bank shows the patchwork. Uses the ontology's `controls` links. Control changes between briefings animate as color washing across territory.

### Convergence Rings

When multiple signal types overlap geographically (military flights + thermal + ACLED in the same 50km), concentric rings ripple outward from the overlap. Cross-agent synthesis made visible. If SIGINT sees flights, RF sees conflicts, thermal layer shows heat - all same area - the ring appears automatically.

### Connection Lines on Hover

Hover any entity and faint lines connect to its ontology relationships:
- Red: arms supply, adversarial
- Amber: alliance, cooperation
- Blue: membership, command hierarchy
- Gold: economic, trade
- White: neutral (borders, located_at)

Directional flow particles. Thickness by confidence. Iran lights up like a spiderweb.

### Entity Glow

Objects with more connections glow brighter. Iran burns hotter than an isolated airbase. Network centrality as luminosity. The most important nodes are visually obvious.

### Threat Ring Sonar

The 8 geofence watch zones render as subtle sonar rings. When an event fires inside, rings pulse outward. Dormant zones barely visible. Active zones pulse.

### Ghost Trails (Time Scrub)

Time slider at the bottom. Scrub backwards to see where things were. Flight paths that faded, vessel positions from last week, conflict events that resolved. Watch a situation develop over days. Play forward at speed to spot slow-moving patterns.

### Prediction Markers

Dashed circles, translucent, with confidence percentage. "We assessed 3 weeks ago Kherson would escalate - here's the prediction zone." Markers solidify when confirmed, fade when wrong. The map shows what you THINK as well as what you KNOW.

### Gravity Wells

Conflicts warp the map subtly. More severe conflicts create deeper visual distortion. Active conflicts pull surrounding entities' labels toward them. Kashmir is a dimple. Ukraine is a crater. Visual weight of a crisis felt in how it distorts space.

### Network Pulse

Click an entity and expand its relationships - connections pulse outward like a shockwave. First-hop lights up, then second, then third. Click Iran and watch the pulse reach Hezbollah, then Hamas, then Gaza, then the Red Sea. The ontology as a living nervous system.

---

## Montgomery - The Commander

### Portrait PiP

Bottom-left of the map. Gilded frame (subtle, not gaudy). Shows Montgomery's avatar. When a briefing arrives, the portrait activates - subtle glow, image shifts. When TTS plays, the portrait "speaks." Click the portrait to open the briefing drawer.

Switch channels and the portrait changes to that agent's avatar. Each agent has a presence.

### Speaks Unprompted

Montgomery doesn't wait. When a significant event occurs (flash report, convergence detected, geofence breach), his portrait activates, alert sound plays, voice delivers the assessment: "Attention. OREF alert - three rocket launches from southern Lebanon. Adjusting the map." The map auto-pans to the event.

He's not a tool you use. He's a presence in the room.

### Chat Interface

Click any entity. Chat panel slides up from the bottom (30% height, semi-transparent). Montgomery (or the relevant channel's agent) responds with live analysis grounded in the ontology. Not canned text. Real inference.

"What happened here last month?" - queries timeline.
"Who commands this unit?" - traverses graph.
"Is this related to Hormuz?" - finds connections.
"Write me a brief on this." - generates SITREP, posts to reading room, pushes to channel.

---

## Game-Style HUD

### Top Bar
- "MERIDIAN EYE" logo (left)
- Search bar (center) - searches ontology
- Alert level badge with label (right)
- Graph icon, settings gear (right)

### Channel Tabs (below header)
Agent channels as tabs. Each: short name + alert dot. Active tab highlighted. Click to switch: globe rotates, layers change, portrait changes, briefing updates.

### Bottom Bar (resource indicators)
Like a strategy game resource bar:
- Active channels: 8/10
- Alert level: ELEVATED
- Ontology: 6,322 objects
- Last update: 14 min ago
- Active missions: 3
- Coverage: 78% (inverse of fog)

### Layer Toggles (bottom, above resource bar)
Compact toggle chips. Only layers relevant to active channel. Icon + name + count badge.

### Action Buttons (context-sensitive)
When an entity is selected, action buttons appear near it:
- [Brief] - generate a SITREP about this entity
- [Track] - add to watchlist
- [Network] - show relationship graph
- [History] - show timeline
- [Commission] - request deeper analysis

Game-style buttons - compact, icon-driven, hover tooltips.

---

## Entity Cards - Collectable Intelligence

Every ontology object has a card. Like a dossier card or trading card.

- **Front:** Portrait/flag/insignia, name, type badge, key stats (2-3 properties)
- **Back:** Full relationship web, brief count, last mentioned date
- **Quality rating:** Bronze (few properties), Silver (well-linked), Gold (comprehensive with briefs)

Cards slide in during cinematic briefings when entities are mentioned. In the entity gallery (/cards), you can browse your full collection. Ontology expansion literally levels up cards from bronze to gold.

Click a card on the map: loads the entity into conversation with Montgomery.

---

## Theater of Operations Mode

Click a conflict and enter "theater mode." The camera transitions to tactical view:
- Terrain elevation becomes visible
- Unit positions render at higher fidelity
- Supply lines appear
- Frontline boundaries draw themselves
- Theater-specific HUD:
  - Force balance bar (like tug-of-war)
  - Days since escalation counter
  - Casualty ticker
  - Active units count
  - Threat trajectory (escalating/stable/de-escalating arrow)

Like zooming from the grand campaign map into a battle in Total War.

---

## Intelligence Missions

Commissions framed as missions. The commission portal becomes a mission board.

Each mission:
- Objective (the intelligence question)
- Assigned agent
- Status: BRIEFED / IN PROGRESS / COMPLETE
- Reward: the published brief

Active missions show on the map as objective markers - dashed circles around the area of interest. When complete, the circle fills in and the brief "unlocks" with a card reveal animation.

---

## Split Screen Comparison

Drag two channels side by side. Map splits - left half one theater, right half another. Or split by time - left shows last week, right shows today. Same geography, different moment. Reveals what changed.

---

## The Daily Debrief

Every day at 07:00, an automated 60-second cinematic debrief:
1. Camera flies preprogrammed route across all active theaters
2. Montgomery narrates each stop (from morning brief)
3. New events animate on
4. Changed threat levels pulse
5. Ends at highest-alert theater
6. You're in control, ready to dig in

Exportable as video for Telegram.

---

## Sound Design (Optional, Toggleable)

Off by default. Toggle via gear icon.

- **Baseline:** Low ambient hum. Pitch shifts with threat level.
- **ACLED event:** Low percussive tone. Deeper for higher fatalities.
- **OREF alert:** Sharp ascending ping. Urgent.
- **Thermal cluster:** Deep vibration, distant thunder.
- **GPS jamming:** Electronic warble.
- **New brief:** Soft chime. Document placed on desk.
- **Channel switch:** Subtle whoosh. Radio dial.
- **Convergence ring:** Resonant harmonic - two tones merging.
- **Cinematic briefing:** Subtle orchestral underscore. Low strings.

---

## Night Watch Mode

After midnight, the interface shifts:
- Map dims. Only CRITICAL items glow.
- Channel tabs collapse to alert dots.
- Analyst quote only if ELEVATED or CRITICAL.
- Layer toggles hidden.
- Almost entirely dark globe with occasional pulses.

Flash report at 3am: map blooms red, OREF ping sounds, Montgomery speaks.

At dawn, interface gradually unfolds. Morning debrief types in.

---

## Pages

### / (Home)
The globe. Orbital descent entry. Montgomery's channel. Full game experience.

### /channel/:name
Same globe, different channel active. URL-shareable.

### /meridian (Reading Room)
Full-page overlay (globe dims behind). Published intelligence products grid.
- Filter: product type, agent, conflict, date, verification score
- Each brief has a "Play Cinematic" button
- Cards: title, type badge, agent, date, verification score

### /meridian/brief/:id
Full brief with cinematic playback option. Markdown render. Entity cards inline.

### /graph
Force-directed knowledge graph. Full screen. Nodes by type, edges by relationship. Search + filter. Click to expand. "View on map" for geolocated entities.

### /graph/entity/:id
Entity dossier + full card view. Properties, relationships, changelog, briefs, map location.

### /cards
Entity card gallery. Browse collection. Filter by type, quality tier, conflict. See coverage gaps.

### /timeline/:conflict
Campaign timeline. Turn-style markers. Assessment trajectory. Click for detail.

### /missions
Mission board. Active commissions as objectives. Status tracking. Brief rewards.

### /health
Source health grid. Green/amber/red.

### /accuracy
Prediction ledger. Outcome tracking. Per-agent accuracy.

### /metrics
Agent performance scorecards.

---

## What to Strip from WorldMonitor

Remove: Bloomberg TV, webcams, Pro banner, Discord, variant switcher, GitHub badge, author credits, blog, download buttons, Clerk auth, analytics, stock/crypto/finance panels, consumer price panels, world clock, all non-intelligence panels.

Keep: globe.gl 3D engine, deck.gl layers, MapLibre, data layer system, country click, CORS/API infrastructure, dark theme.

---

## Game Interaction Layer

We don't need Unity or a full game engine. We need a thin interaction layer (~800 lines of TypeScript) on top of the existing rendering stack that makes data feel like a strategy game.

### What it does

```
Ontology data (6,322 objects, 7,218 links)
    |
    v
Game Entity Manager (new)
    - Converts ontology objects into "game entities" with:
      - Position (lat/lon from ontology)
      - Faction (derived from country/allegiance links)
      - Strength (derived from unit composition/property count)
      - Rank (derived from command hierarchy depth)
      - Status (from ontology status field)
      - Icon type (from object type/subtype)
    |
    v
Renderer (deck.gl custom layers)
    - Flag/banner markers with strength bars and stars
    - Faction-colored sprites
    - Hover tooltips (game-style panels)
    - Click -> composition panels
    |
    v
Camera Controller (globe.gl + GSAP)
    - Free orbit (WASD + mouse)
    - Cinematic paths (briefing mode)
    - Snap-to on entity select
    - Smooth transitions between views
    |
    v
UI Overlay (HTML/CSS game-style)
    - HUD elements floating over WebGL
    - Game-style buttons (not web forms)
    - Sliders with custom styling
    - Panel system (slide in/out)
```

### Unit Markers (The Total War Flags)

Every military entity on the map gets a flag-style marker. Not a dot. A banner.

**Anatomy of a unit marker:**

```
    [*****]          <- Star rating (commander rank)
    |     |
    |  US |          <- Faction color fill
    | NAVY|          <- Abbreviated name
    |     |
    [|||||||||  ]    <- Strength bar (filled portion)
    |     |
    [carrier icon]   <- Silhouette by unit type
```

**How strength is calculated:**
- Fleet/CSG: vessels in group / expected complement
- Army unit: from ontology properties (personnel count / authorized strength)
- Air wing: aircraft count / wing capacity
- If no specific data: property count / 10 (more intel = stronger appearance)

**How stars are calculated:**
- 5 stars: COCOM-level or national command (CENTCOM, Pacific Fleet)
- 4 stars: Corps/Fleet/numbered air force level
- 3 stars: Division/carrier strike group level
- 2 stars: Brigade/squadron level
- 1 star: Battalion/ship level
- Derived from command hierarchy depth in the ontology (links of type `subsidiary_of`)

**Faction colors:**
- Blue: NATO/allied (US, UK, France, etc.)
- Red: Adversary (Russia, Iran, North Korea)
- Green: China/PLA (distinct from red)
- Gold: Neutral/non-aligned
- Orange: Non-state actors (Houthis, RSF, etc.)
- Purple: UN/international missions
- Derived from the entity's country allegiance and its relationship to the user's configured perspective

**Icon silhouettes by subtype:**
- Carrier: flat-top ship profile
- Destroyer/frigate: angled bow ship
- Submarine: cigar with conning tower
- Infantry/army: soldier figure
- Armor: tank silhouette
- Special forces: dagger
- Air base: aircraft on runway
- Fighter squadron: jet profile
- Bomber: heavy aircraft profile
- Missile system: launcher silhouette
- Nuclear facility: atom symbol

### The USS Gerald Ford Example

The ontology has:
- Object: "USS Gerald Ford" (type=platform, subtype=aircraft_carrier)
- Properties: hull_number=CVN-78, displacement=100000, commissioned=2017
- Links: `operated_by` US Navy, `deployed_to` Eastern Mediterranean, `subsidiary_of` CSG-12

The game layer renders:
1. **Flag marker** at the Eastern Med coordinates
2. **Faction:** Blue (US Navy -> NATO aligned)
3. **Strength:** Query all objects linked to CSG-12 via `subsidiary_of` -> count vessels -> 9/11 = 82%
4. **Stars:** CSG-12 is a strike group (3-star level), but Ford is a national asset (bumped to 4)
5. **Icon:** Aircraft carrier silhouette
6. **Label:** "CSG-12"

**Hover tooltip (game panel style):**
Dark panel with gold border, faction-colored header stripe
```
CSG-12 - CARRIER STRIKE GROUP 12
USS Gerald Ford (CVN-78)
****  RADM Erik Eslich, USN
━━━━━━━━━━━━━━━━━━━━━━━━━━
LOCATION    Eastern Mediterranean
STATUS      Deployed
STRENGTH    ████████░░ 82% (9/11 vessels)
AIR WING    CVW-8 | 74 aircraft
LAST INTEL  2h ago
━━━━━━━━━━━━━━━━━━━━━━━━━━
[View Composition] [Track] [Brief]
```

**Click -> Composition panel (slides from right):**
Full breakdown of every vessel in the group, each with its own mini strength bar, like Total War's army composition view.

### Time Control (Game-Style Slider)

Not a web range input. A game-style time control:

```
[|<]  [<]  [||]  [>]  [>|]     [===========|====] 27 Mar 2026
 rew  slow  pause play  fast     ^^^^ scrub handle
```

- Rewind: jump back 24h
- Slow: play history at 10x
- Pause: freeze at current time
- Play: real-time
- Fast: play history at 60x
- Scrub: drag to any point in the last 30 days

When scrubbing: unit positions animate to their historical locations. Events pop and fade. The map comes alive showing the passage of time.

### Settings (Game Menu Style)

Not a web settings page. A game-style overlay menu:

```
+------------------------------------------+
|  MERIDIAN EYE - SETTINGS                 |
|  ========================================|
|                                          |
|  DISPLAY                                 |
|  [===========|====] Globe detail    HIGH |
|  [=========|======] Label density   MED  |
|  [ON ] Fog of war                        |
|  [ON ] Unit figurines                    |
|  [OFF] Gravity wells                     |
|  [ON ] Connection lines on hover         |
|                                          |
|  AUDIO                                   |
|  [=========|======] Master volume   60%  |
|  [ON ] Event sounds                      |
|  [OFF] Ambient hum                       |
|  [ON ] Briefing narration                |
|                                          |
|  BRIEFINGS                               |
|  [ON ] Auto-play morning debrief         |
|  [ON ] Flash report cinematics           |
|  [==|================] Cinematic speed   |
|                                          |
|  CAMERA                                  |
|  [ON ] Orbital entry on load             |
|  [===========|====] Rotation speed       |
|  [ON ] Auto-rotate when idle             |
|                                          |
|  DATA                                    |
|  [ON ] Night watch mode                  |
|  [===|===============] Update interval   |
|  [ON ] Show prediction markers           |
|                                          |
|  [APPLY]                    [DEFAULTS]   |
+------------------------------------------+
```

Sliders are custom-styled (not native HTML range). Toggle switches are game-style (not checkbox). Categories are collapsible. Dark panel with subtle glow border.

### Layer Buttons (Ability Bar Style)

Like ability buttons in a strategy game, bottom of screen:

```
[Q]        [W]        [E]        [R]        [T]
MIL       CONFLICT   THERMAL    GPS JAM    VESSELS
FLIGHTS    ACLED                            AIS
[128]      [47]       [12]       [3]        [891]
 ON         ON        OFF        OFF         ON
```

Each button:
- Hotkey letter (Q/W/E/R/T/Y for first 6, numbers for rest)
- Icon
- Layer name
- Item count badge
- Active state (glowing border when on)
- Click or press hotkey to toggle

### Keyboard Shortcuts (Game Controls)

```
WASD          - Pan camera
Scroll        - Zoom
Right-drag    - Rotate/tilt
Space         - Play/pause current briefing
Esc           - Close panel/drawer
Tab           - Cycle through channels
1-9           - Jump to channel by number
Q/W/E/R/T/Y  - Toggle layers
F             - Enter theater mode (on selected conflict)
G             - Toggle globe/flat
M             - Toggle mission board
C             - Open cards gallery
/             - Focus search
B             - Play latest briefing cinematic
N             - Night watch toggle
```

## Technical Stack

- **globe.gl** - 3D globe with free camera (orbit, zoom, tilt, rotate). Already in codebase.
- **deck.gl** - WebGL layers: ScatterplotLayer (pulsing hotspots), ArcLayer (connection lines), PathLayer (contrails), IconLayer (unit figurines), HeatmapLayer (intel density), TripsLayer (ghost trails).
- **Three.js** - Post-processing: bloom (entity glow), vignette, color grading (temperature shift). Camera animation (cinematic paths). Already in codebase via globe.gl.
- **GSAP** - Animation: letterbox bars, card reveals, dispatch effects, typewriter text, camera waypoint sequencing.
- **Howler.js** - Spatial audio: ambient sound, event pings, cinematic underscore.
- **Supercluster** - Marker clustering at low zoom levels. Already in codebase.
- **ElevenLabs API** - TTS for Montgomery's voice in cinematics and unprompted alerts.
- **Claude API** - Chat responses when entities are clicked. Vercel Edge Function proxy.

---

## Deep Intelligence - The Nerdy Professor

The database isn't just a reference. It's institutional memory. When Montgomery talks about the Strait of Hormuz, he doesn't just say "IRGC-Navy active." He says "IRGC-Navy activity is up 40% from last month. The last time we saw this pattern was August 2024 before the tanker seizures. Three briefs from rf_gulf_iran_israel flagged this trend. The prediction ledger has an open forecast from 12 days ago assessing 65% likelihood of an escalatory incident within 30 days."

Every interaction draws from:
- **The ontology** (6,322 objects, 28,976 properties, 7,218 links)
- **Briefs** (36 intelligence products with full text)
- **Timeline** (50 situation assessments showing trajectory)
- **Predictions** (40 open forecasts with confidence scores)
- **Relationships** (who funds who, who arms who, who opposes who)
- **Source health** (which feeds are live, which are stale)
- **Verification scores** (how well corroborated is this claim)

When you click the USS Gerald Ford on the map, Montgomery doesn't give you a Wikipedia summary. He gives you the intelligence picture: where it's been (ghost trail), who else is in the area (nearby units), what it was last mentioned in (brief #29: "CSG-12 repositioned to Eastern Med following OREF escalation"), what the current threat environment is (from the channel state), and what his assessment is (real-time inference using all of this context).

That's what makes this different from Google Maps with dots. Every dot has a story. Every story connects to other stories. Montgomery knows all of them.

## 3D Assets - Not Dots on a Map

The visual identity is critical. This is not a web map with colored circles. Every entity type has a custom 3D asset rendered via Three.js on the globe.

### Asset Types

**Naval vessels:**
- Aircraft carrier: full 3D model (simplified low-poly, recognizable silhouette)
- Destroyer/frigate: angular warship profile
- Submarine: cigar shape, partially submerged effect
- Commercial vessel: container ship or tanker depending on type
- Each has faction-colored hull markings

**Aircraft:**
- Fighter jet: swept-wing profile, faction roundel
- Bomber: large profile, distinct from fighter
- Transport: bulky, high-wing
- Drone/UAV: distinctive profile (Bayraktar, Shahed different shapes)
- Helicopter: rotor disc
- Aircraft on patrol draw dotted predicted-path lines ahead of them

**Ground forces:**
- Infantry: small formation of figure silhouettes (like Total War unit cards)
- Armor: tank silhouette cluster
- Artillery: gun battery
- Special forces: dagger emblem
- Missile battery: launcher on transporter
- Size of the formation visual scales with unit strength

**Bases and facilities:**
- Military base: fortification icon with flag
- Naval base: dockyard with crane silhouettes
- Air base: runway with hangar
- Nuclear facility: cooling tower silhouette
- Embassy: small building with flag
- Chokepoint: channel markers (like nautical buoys)
- Pipeline: line with flow particles
- Undersea cable: dashed line on ocean floor

**Leaders and persons:**
- Head of state: portrait pin with country flag backdrop
- Military commander: pin with rank insignia
- Intelligence chief: pin with agency seal
- Only rendered when zoomed in close enough (LOD system)

### Level of Detail (LOD)

Zoomed out (global): simplified icons, clustering, only major units visible
Zoomed mid (regional): individual unit markers with strength bars, no 3D models
Zoomed in (theater): full 3D assets, labels, formation details
Zoomed very close: building-level detail where available

### Asset Library

The 3D assets can be created with:
- **Three.js primitives** for simple shapes (cylinders for submarines, boxes for ships)
- **Low-poly GLTF models** from free asset libraries (Sketchfab has CC0 military models)
- **Procedurally generated** silhouettes from SVG outlines extruded to 3D
- **Sprite-based** at medium zoom (2D images that always face the camera - billboards)

The key insight: at strategic zoom levels (which is 90% of use), you're looking at styled 2D sprites on the 3D globe, not detailed 3D models. The models only matter when you zoom into a specific theater. This keeps performance manageable.

### Asset Rendering Pipeline

```
Ontology object (USS Gerald Ford, type=platform, subtype=aircraft_carrier)
    |
    v
Asset Resolver: subtype -> asset definition
    {model: 'carrier', faction: 'blue', scale: 1.2, lodDistances: [100, 500, 2000]}
    |
    v
LOD Manager: camera distance -> render mode
    - Far: 2D icon sprite (billboard)
    - Mid: 2D sprite with strength bar overlay
    - Near: 3D low-poly model with faction textures
    |
    v
Three.js scene: instanced rendering for performance
    - Same model type batched together
    - Frustum culling (don't render what's off-screen)
    - Max 500 visible entities at any time (cluster the rest)
```

## Additional Features (The Extra 10)

### Intelligence Radar Sweep
A rotating radar sweep line on the globe. As it passes regions, recent events flash bright. Sweep speed varies with polling frequency. Visual confirmation the system is watching. Originates from the user's configured home location.

### Diplomatic Weather
Geopolitical climate as literal weather metaphors. Stormy clouds over conflict zones. Lightning for flash events. Cold fronts for sanctions. Clear skies for stable regions. Not realistic weather - metaphorical atmosphere.

### Red Lines
Montgomery can define threshold conditions that render as literal red lines on the map. "If forces cross this line..." The line pulses as activity approaches. Turns critical red if breached.

### Whisper Network
Multi-source intelligence renders as converging whisper lines on verified entities. 5-source entity has dense whispers. Single-source has one faint line. Verification quality made visible.

### The Situation Room
Toggle from globe to multi-panel operations center: mini-maps per theater, briefing feed, entity ticker, alert log, mission status. Like walking into a command center with screens.

### Asset Tracking Watchlist
Tag specific entities (vessel MMSI, aircraft hex, person). They get permanent highlights, movement trails, and automatic alerts on status change. Surveillance mode.

### Butterfly Effect Chains
After a major event, visualize the cascade: Iran strike -> oil prices (energy layer flickers) -> Hormuz disruption (threat ring) -> EU energy impact (connection arc) -> market reaction (indicators flash). Branching consequence tree rendered sequentially.

### Dead Drops
Agents can geolocate raw intelligence notes on the map. Small pins. Clusters of dead drops signal emerging importance before formal analysis catches up. The gap between signals and finished intel.

### Historical Overlay Ghosts
Toggle to see ghost images from significant past moments. The 2014 Crimea map ghosted over today's. The pre-October 7 Gaza map overlaid on current. Historical precedent made visual.

### Threat Constellations
At max zoom-out, connect related threats into constellation lines. The "Iran axis" constellation: Tehran-Hezbollah-Houthis-Hamas-PMF. The "Arctic race" constellation: Russia-NATO Nordic-Svalbard-Northern Fleet. Dissolve as you zoom in.

## Implementation Phases

### Phase 1: Strip + Globe First (3 days)
1. Remove all WorldMonitor consumer panels
2. Globe.gl as default view (not flat map)
3. Free camera controls (orbit, zoom, tilt)
4. Floating HUD: header, channel tabs, resource bar
5. Montgomery portrait PiP (static for now)
6. Orbital descent entry animation
7. Basic layer toggles
8. Deploy clean

### Phase 2: Units + Interactions (3 days)
9. Unit figurines on map (IconLayer with faction colors)
10. Entity click -> chat panel slides up
11. Connection lines on hover
12. Territory control coloring
13. Country click -> ontology profile
14. Action buttons on selected entity
15. Channel switching drives camera + layers

### Phase 3: Living Map Effects (3 days)
16. Hotspot pulse animation (decay over time)
17. Color temperature shift with threat level
18. Flight contrails (fading trails)
19. Convergence ring detection and rendering
20. Entity glow (network centrality as luminosity)
21. Threat ring sonar around watch zones
22. Fog of war (intelligence density driven)
23. Gravity wells around active conflicts

### Phase 4: Cinematic Briefings (4 days)
24. Letterbox bar animation
25. Camera waypoint sequencing (bezier curves between points)
26. Unit movement animation along paths
27. Entity card slide-in synced to narration
28. Connection line draw-on during relationship mentions
29. TTS audio playback synced to camera movement
30. Convergence ring triggers during narration
31. Auto-generate waypoints from brief text + ontology geo data
32. Flash report snap-to cinematic
33. Morning debrief auto-play

### Phase 5: Game Features (3 days)
34. Entity cards (front/back, quality tiers)
35. Card gallery page (/cards)
36. Intelligence missions (commission -> mission board)
37. Mission markers on map
38. Theater of operations mode
39. Split screen comparison
40. Ghost trails (time scrub)
41. Prediction markers (dashed, translucent)

### Phase 6: Reading Room + Graph (2 days)
42. /meridian reading room with cinematic play buttons
43. /meridian/brief/:id with inline entity cards
44. /graph force-directed visualization
45. /graph/entity/:id dossier page
46. Network pulse animation on graph
47. Ontology search autocomplete

### Phase 7: Ops Console (4 days)
48. /ops - Agent management dashboard
49. /ops/agents - List all agents with status, last activity, brief count, alert level
50. /ops/agents/:name - Full agent config editor (manifest JSON, prompts, soul)
51. /ops/agents/create - Agent creation wizard (mirrors Atrophy desktop SetupWizard)
52. /ops/jobs - Cron job manager (all jobs, status, last run, next run, enable/disable/trigger)
53. /ops/jobs/:agent/:job - Job detail (history, logs, circuit breaker status, edit schedule)
54. /ops/mcp - MCP server manager (list servers, enable/disable per agent, probe health)
55. /ops/llm - LLM backend configuration (Claude CLI local, hosted Claude Code, API key management)
56. /ops/org - Organisation chart (defence org hierarchy, drag-drop restructure)
57. /ops/sources - Data source manager (feeds, WorldMonitor endpoints, think tank scrapers)
58. /ops/ontology - Ontology admin (object counts, health, run dedupe, trigger expansion, import/export)
59. /ops/logs - Live log streaming (cron output, agent errors, MCP failures)

### Phase 8: Polish + Export (3 days)
60. Sound design system (Howler.js, toggleable)
61. Night watch mode
62. Briefing video export (headless render -> MP4)
63. Telegram video delivery
64. OG images for link previews
65. Daily debrief automation
66. Montgomery speaks unprompted on events
67. Keyboard shortcuts (WASD, space for briefing, esc to dismiss)
68. Performance optimization (clustering, LOD, lazy load)
69. Mobile: touch controls, simplified HUD

---

## Ops Console - System Management

The Meridian Eye is also the control room for the entire Atrophy agent system. Not just consuming intelligence - managing the machine that produces it.

### Architecture: Site <-> App Communication

The Meridian site runs on Vercel. The Atrophy desktop app runs on the user's Mac. For the site to control the app, two channels:

**Read-only (site can always do):** Query the ontology, read briefs, view agent manifests, see job history - all via Vercel API routes that read from Upstash Redis (synced from the app).

**Write commands (site -> app):** The site writes command messages to an Upstash Redis queue. The Atrophy app polls this queue every 30 seconds and executes commands. This handles: trigger a job, restart an agent, change a setting, update a prompt.

```
Site (Vercel)                     App (Electron on Mac)
    |                                    |
    |-- PUT /api/ops/command -->         |
    |   {type: "trigger_job",            |
    |    agent: "general_montgomery",    |
    |    job: "three_hour_update"}       |
    |                                    |
    |   Stored in Redis queue            |
    |                                    |
    |                  <-- App polls --  |
    |                  every 30 seconds  |
    |                                    |
    |                  Executes command   |
    |                  Updates status     |
    |                                    |
    |   <-- Status update in Redis --    |
    |                                    |
    |   Site shows result                |
```

### /ops - Dashboard

Overview of the entire system at a glance:

```
+------------------------------------------------------------------+
| MERIDIAN EYE - OPERATIONS                                        |
+------------------------------------------------------------------+
|                                                                   |
| SYSTEM STATUS: OPERATIONAL          UPTIME: 14d 6h 23m           |
|                                                                   |
| AGENTS          JOBS           SOURCES        ONTOLOGY            |
| 10 active       47 scheduled   39 monitored   6,322 objects      |
| 0 errored       3 running      21 healthy     7,218 links        |
| 2 disabled      2 disabled     15 dead        28,976 properties  |
|                                                                   |
| RECENT ACTIVITY                                                   |
| 14:30  three_hour_update completed (42s)                         |
| 14:15  harvest_articles: 12 new articles from 9 sources          |
| 14:00  worldmonitor_fast: 3 flight changes, 1 ACLED event       |
| 13:45  vectorize: 48 documents re-embedded                       |
| 13:30  ontology_expand: +87 objects (Thursday: locations focus)   |
|                                                                   |
| ALERTS                                                            |
| [!] 3 defence_sources feeds returning 404 for 48h+               |
| [!] prediction_review has 12 overdue predictions                  |
| [i] ontology_expand added 87 objects in last run                  |
+------------------------------------------------------------------+
```

### /ops/agents/:name - Agent Editor

Full control over an agent's configuration:

**Identity:** name, display name, description, voice settings, avatar
**Prompts:** system.md, soul.md, heartbeat.md - editable text areas with save
**Manifest:** channels (telegram tokens, desktop enabled), MCP servers (toggle on/off), router config (accept_from, reject_from), org hierarchy (tier, reports_to)
**Jobs:** all cron jobs with schedule, script path, description, enable/disable toggle, "Run Now" button, last 10 run history
**Performance:** brief count, prediction accuracy, entity coverage, verification scores
**Actions:** [Restart Session] [Clear Circuit Breakers] [Rebuild MCP Config] [Delete Agent]

### /ops/jobs - Job Manager

All cron jobs across all agents in one view:

| Agent | Job | Schedule | Last Run | Duration | Status | Actions |
|-------|-----|----------|----------|----------|--------|---------|
| montgomery | three_hour_update | */3h | 14:30 | 42s | OK | [Run] [Disable] [Edit] |
| montgomery | harvest_articles | */4h | 14:00 | 2m12s | OK | [Run] [Disable] [Edit] |
| sigint | sigint_cycle | */15m | 14:45 | 18s | OK | [Run] [Disable] [Edit] |
| librarian | relationship_extract | */1h | 14:15 | 3m45s | OK | [Run] [Disable] [Edit] |
| montgomery | cross_agent_synthesis | 02:00 | 02:00 | 1m30s | OK | [Run] [Disable] [Edit] |

Click [Edit] to change cron expression, script path, description. Changes write to Redis queue -> app updates the manifest.

Click [Run] to trigger immediately. Command goes to Redis queue -> app executes -> result streams back.

### /ops/llm - LLM Backend

This is where you change what powers the agents:

**Current backend:** Claude CLI (local)
- Path: ~/.local/bin/claude
- Model: claude-sonnet-4-20250514 (default), claude-haiku-4-5-20251001 (fast tasks)
- Session management: per-agent session IDs

**Available backends:**
- [x] Claude CLI (local) - current
- [ ] Hosted Claude Code (remote) - for running when laptop is closed
- [ ] Claude API direct (via Anthropic SDK)
- [ ] Custom endpoint (OpenAI-compatible)

Switching backends:
1. Select new backend
2. Configure credentials (API key, endpoint URL)
3. Test connection
4. Apply - updates the inference engine config
5. All agents restart with new backend

This is critical for the transition to hosted Claude Code - when that becomes available, you flip the switch here and the entire agent system moves to cloud inference. Jobs run 24/7, not just when the laptop is open.

### /ops/org - Organisation Chart

Visual org chart of the defence org:

```
                    [Xan - System]
                         |
              [Montgomery - Defence Chief]
                    /    |    \
         [RF Russia]  [SIGINT]  [RF Gulf]  [Economic]  [EU]  [IndoPac]  [UK]
              |
      [QC Agent]  [Librarian]  [Red Team]  [Viz Agent]
                                    |
                          [Ambassador x10]
```

Each node clickable -> opens agent editor. Drag and drop to restructure reporting lines. Add new agents via a creation wizard. Shows alert status dots on each node.

### /ops/sources - Source Manager

All data sources in one place:

**WorldMonitor endpoints:** status, last poll, response time
**Defence sources RSS:** status, last fetch, item count
**Think tank RSS feeds:** status, articles harvested today
**Think tank browser scrapers:** status, last scrape, articles found
**Ontology expansion:** today's focus area, objects added

Toggle sources on/off. Change poll frequency. Add new RSS feeds. View article quality (relevance score distribution).

### /ops/ontology - Ontology Admin

Database administration:

**Stats:** object counts by type, link counts by type, property distribution, growth rate chart
**Health:** orphaned records, duplicate detection, missing indexes
**Actions:** [Run Dedupe] [Trigger Expansion] [Rebuild Vectors] [Export JSON] [Import JSON]
**Schema:** view all tables, row counts, recent changelog entries
**Query:** raw SQL query interface for ad-hoc investigation (read-only)

### API Routes for Ops

New Vercel API routes:

| Route | Method | Purpose |
|-------|--------|---------|
| `api/ops/status` | GET | System overview stats |
| `api/ops/agents` | GET | List all agents with status |
| `api/ops/agents/[name]` | GET/PUT | Read/update agent config |
| `api/ops/agents/[name]/manifest` | GET/PUT | Read/update manifest JSON |
| `api/ops/agents/[name]/prompts` | GET/PUT | Read/update prompt files |
| `api/ops/jobs` | GET | List all jobs across agents |
| `api/ops/jobs/[agent]/[job]` | GET/PUT | Job detail and config |
| `api/ops/jobs/[agent]/[job]/trigger` | POST | Trigger job immediately |
| `api/ops/jobs/[agent]/[job]/history` | GET | Job run history |
| `api/ops/command` | POST | Queue a command for the app |
| `api/ops/command/status/[id]` | GET | Check command execution status |
| `api/ops/llm` | GET/PUT | LLM backend config |
| `api/ops/sources` | GET | All data sources with status |
| `api/ops/ontology/stats` | GET | Ontology statistics |
| `api/ops/ontology/query` | POST | Read-only SQL query |
| `api/ops/logs` | GET | Recent log entries (SSE stream) |

All ops routes require auth (X-Channel-Key) and a separate ops permission flag.

### State Sync: App -> Site

The Atrophy app periodically syncs its state to Upstash Redis so the ops console has current data:

- Agent manifests: synced on change
- Job schedules and history: synced every minute
- MCP server status: synced on probe
- Recent logs: last 100 entries synced every 30 seconds
- LLM backend config: synced on change

New cron job in the app:
```json
"ops_sync": {
  "type": "interval",
  "interval_seconds": 60,
  "script": "internal",
  "description": "Sync app state to Meridian ops console"
}
```

This is a TypeScript function in the app, not a Python script. It runs in the main process and pushes state to Redis.

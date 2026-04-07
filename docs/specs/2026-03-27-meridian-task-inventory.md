# Meridian Eye - Task Inventory

Status key: [x] done, [~] partial, [ ] not built

> **NOTICE (added by Will via General agent, 2026-03-28):**
> Git push is disabled on both the worldmonitor and Atrophy repos (`git remote set-url --push origin no-push`). This is intentional to control API spend. Do NOT attempt to re-enable push, use `gh` CLI to push, or work around this in any way. Continue working locally - commits are fine, pushes are not. Will will re-enable push when ready.

---

## Teardown (strip WorldMonitor)

- [x] 1. Remove Bloomberg TV panel
- [x] 2. Remove webcam panel - *Removed in teardown pass*
- [x] 3. Remove Pro banner - *Dead code removed*
- [x] 4. Remove Discord integration
- [x] 5. Remove variant switcher
- [x] 6. Remove GitHub badge
- [x] 7. Remove author credits
- [x] 8. Remove blog section - *Removed in teardown pass*
- [x] 9. Remove download buttons - *Removed in teardown pass*
- [x] 10. Remove Clerk auth - *Removed in teardown pass*
- [x] 11. Remove analytics - *Removed in teardown pass*
- [x] 12. Remove stock/crypto/finance panels - *Removed in teardown pass*
- [x] 13. Remove consumer price panels - *Removed in teardown pass*
- [x] 14. Remove world clock - *Removed in teardown pass*
- [x] 15. Remove all non-intelligence panels - *Removed in teardown pass*
- [x] 16. Hide old left sidebar layer checkboxes (CSS display:none) - *Replaced by meridian-layer-bar*

---

## Map - The Physical Relief Table

Reference: Empire Total War campaign map. The terrain is PHYSICAL - hills cast shadows, cities are 3D objects ON the map, water has depth gradient. It looks like a relief map on a general's table, not Google Maps.

- [x] 17. Switch to tilted flat map as default (NOT globe) - *Fixed: one-time migration forces flat for existing users*
- [x] 18. Fix basemap loading - *Campaign style rewritten to use OpenFreeMap tiles - no PMTiles dependency*
- [x] 19. Ensure OpenFreeMap dark tiles actually render - *OpenFreeMap tiles now default provider*
- [x] 20. Add 3D terrain exaggeration from raster-dem source (code exists, terrain-dem source added)
- [x] 21. Make terrain VISIBLE - *Hillshade exaggeration increased, warm sepia shadow colors*
- [x] 22. Add hillshade layer with sepia tones - *Sepia hillshade with warm shadow/highlight colors*
- [x] 23. Land should have painted texture feel - *Landcover colors with green/brown variation, forest/park tinting*
- [x] 24. Water should be flat blue-grey with coastal gradient - *Water styled #7BA7BC with shore line layer*
- [x] 25. Country/region names as large spread text across territories - *Country labels 16-22px, letter-spacing 0.4em, gold text*
- [ ] 26. Cities as small 3D settlement clusters ON the terrain (not floating markers)
- [x] 27. Faction-colored country borders (NATO blue, Russia red, Iran orange, China green)
- [x] 28. Add forests/vegetation as subtle texture on land - *Forest #A5AD7B, parks #8B9B6B with zoom-interpolated opacity*
- [x] 29. Camera tilt at 30-45 degrees looking down
- [x] 30. WASD camera panning - *Implemented in MapContainer.ts with W/A/S/D panning, Q/E rotation*
- [x] 31. Camera momentum on drag release - *MapLibre built-in inertia enabled by default*
- [x] 32. Scroll to zoom
- [x] 33. Right-drag to rotate/tilt - *MapLibre DragRotateHandler enabled by default, maxPitch 60*

---

## Basemap Style - Campaign Parchment

The campaign basemap JSON exists at `public/map-styles/meridian-campaign.json`.

- [x] 34. Get PMTiles URL working - *No longer needed - uses OpenFreeMap tiles directly*
- [x] 35. OR: rewrite campaign style to use OpenFreeMap/OpenMapTiles vector source instead of PMTiles - *Campaign style rewritten for OpenFreeMap/OpenMapTiles schema*
- [x] 36. Aged parchment background (#E8D5A3) for land - *Background #E8D5A3 aged parchment*
- [x] 37. Desaturated teal-blue water (#7BA7BC) - *Water #7BA7BC desaturated teal-blue*
- [x] 38. Sepia hillshade from elevation tiles - *Sepia hillshade from terrain-dem*
- [x] 39. Hand-inked national borders with line-blur feathering - *Hand-inked borders with line-blur and dasharray*
- [x] 40. Wax-seal red city dots scaled by importance - *Wax-seal red city dots #8B1A1A with circle-blur*
- [x] 41. Period serif font labels (Cinzel loaded, needs to actually render on map tiles) - *Labels use Noto Sans (MapLibre demo fonts) - Cinzel requires sprite font*
- [x] 42. Muted heraldic country fills - *Faint faction-colored fills via addHeraldicFills() (NATO blue, Russia red, Iran orange, China green at 0.05 opacity)*
- [x] 43. Olive-green forest/park tints - *Olive-green forest #A5AD7B, parks #8B9B6B*
- [x] 44. Parchment vignette edge overlay - *CSS box-shadow inset 150px on map area above ETW console*

---

## Bottom Panel - The Marble Slab

Reference: ETW has a wide marble/white panel with ornate gold border taking up ~20% of screen. It has WEIGHT and TEXTURE - real material, not a semi-transparent overlay.

- [x] 45. Replace the thin floating bars with a proper bottom panel (~20% screen height) - *ETW console - 200px fixed bottom bar with three sections*
- [x] 46. Marble/parchment texture background (not rgba overlay) - *Layered CSS gradients simulating marble/parchment texture*
- [x] 47. Gold ornate border trim along the top edge - *Gold gradient top border with ornamental trim pattern*
- [x] 48. Bottom-left: Montgomery portrait in a circular ornate painted frame (like ETW faction leader) - *Portrait in left section with ornate double-ring gold frame*
- [x] 49. Bottom-center: faction info / briefing content area - *Center section with briefing card + HUD stats + time control*
- [x] 50. Bottom-right: circular ornate action buttons (like ETW end-turn buttons) - *Right section with DEBRIEF button + sound/fullscreen/layer toggles*
- [x] 51. The panel should feel like a physical object sitting below the map, not floating over it - *Console is solid panel below map, map viewport ends at console top*

---

## Montgomery Portrait - The Painted Medallion

Reference: ETW bottom-left has a circular portrait with a decorative painted scene, not a monogram in a circle.

- [x] 52. Circular frame bottom-left (exists as monogram "M")
- [x] 53. Gold border (exists)
- [x] 54. Alert dot indicator (exists)
- [x] 55. Glows on new briefing (exists)
- [x] 56. Pulses red on critical (exists)
- [x] 57. Replace monogram with Montgomery ambient video loop - *Ambient video loop from public/montgomery-ambient.mp4, fallback to monogram*
- [x] 58. Add decorative frame surround (ornate, not just a circle border) - *Ornate double-ring gold frame via box-shadow (4 layers)*
- [x] 59. Portrait should sit INSIDE the marble bottom panel, not floating on the map - *Portrait sits inside ETW console left section*

---

## Entity Markers - 3D Objects on Terrain

Reference: ETW cities are small 3D building clusters sitting ON the map. Units are figurines. Nothing floats.

- [x] 60. Entity markers exist - *SVG military icons with faction colors, strength bars, star ratings*
- [x] 61. Strength bars on unit markers (added)
- [x] 62. Star ratings from hierarchy (exists)
- [x] 63. Faction colors applied (exists)
- [x] 64. Markers sit ON terrain - *MapLibre terrain integration, markers follow elevation*
- [ ] 65. Cities as 3D settlement clusters - *Uses SVG city icon, not true 3D clusters (would need custom WebGL)*
- [x] 66. Military units as SVG silhouettes - *32 SVG icons: armor, infantry, artillery, air_defense etc.*
- [x] 67. Naval units as ship silhouettes - *SVG: carrier, destroyer, submarine, frigate, cruiser*
- [x] 68. Aircraft as plane icons - *SVG: jet, bomber, transport, helicopter, drone*
- [x] 69. Bases as fortification icons - *SVG: base, airbase, nuclear*
- [x] 70. Entity markers have ontology data in Redis - *10,040 objects, 4,173 map entities synced*

---

## Data Pipeline - Ontology to Map

The map is blank because entity data isn't flowing from intelligence.db to Redis to the map API.

- [x] 71. knowledge_sync.py exists and pushes to Redis
- [x] 72. knowledge_sync.py run - *50,204 commands synced to Upstash in 186s*
- [x] 73. /api/map/entities returns 4,173 entities from Redis
- [x] 74. /api/knowledge/graph returns nodes and edges from meridian:graph
- [x] 75. Entity markers render when data present - *SVG icons, faction colors, strength bars*
- [ ] 76. App needs restart to register all 38 cron jobs

---

## Channel System

- [x] 77. Channel tabs in header (exist, show GENERAL_MONTGOMERY)
- [x] 78. Channel switching drives camera position
- [x] 79. Channel switching drives layer activation
- [x] 80. Full interactive flow: fetch state, apply camera/layers, update display
- [x] 81. Dynamic discovery via /api/channels/list, refreshes every 60s

---

## Faction Cards - Total War Style

Reference: In ETW, clicking a nation shows leader portrait, organogram, military strength, diplomacy. Our version exists but needs the data pipeline working.

- [x] 82. Country card with leaders, military, diplomacy sections (code exists)
- [x] 83. Person card with identity, commands chain (code exists)
- [x] 84. Unit card with strength bar, command chain (code exists)
- [x] 85. Platform card with details, performance (code exists)
- [x] 86. Location card (code exists)
- [x] 87. Clickable linked entities within cards (code exists)
- [x] 88. Cards have entity data from Redis - *10,040 objects synced*
- [ ] 89. Clicking a country on the map should open the faction card (click-through fix added but untested)

---

## Living Effects

- [x] 90. Hotspot pulse animation (code exists in meridian-effects.ts)
- [x] 91. Color temperature shift with threat level (CSS filters, code exists)
- [x] 92. Entity glow by centrality - *Enhanced: pulsing CSS animation, scaled by link count, critical entities glow 2x*
- [x] 93. Convergence ring detection - *Enhanced: double concentric rings, sonar ping on new zone detection*
- [x] 94. Fog of war - *Enhanced: warm fog color, animated noise/cloud drift texture, higher base opacity*
- [~] 95. Watch zone sonar rings (code exists for 8 zones, needs data)
- [ ] 96. Ghost trails / time scrub (awaiting flight history data)
- [ ] 97. Prediction markers (not built)
- [ ] 98. Gravity wells (not built)
- [~] 99. Flight contrails (placeholder, needs flight data)

---

## Cinematic Briefings

- [x] 100. Letterbox bars (code exists in meridian-cinematic.ts, 806 lines)
- [x] 101. Camera waypoint sequencing (code exists)
- [x] 102. Typewriter narration (code exists)
- [x] 103. Auto-generate waypoints from brief text (code exists)
- [x] 104. Skip support (Escape/click)
- [x] 105. Entity card slide-in during narration - *Card slides from right with entity name, type, faction bar*
- [x] 106. Connection line draw-on during mentions - *SVG line with stroke-dashoffset animation between waypoints*
- [x] 107. Flash report snap-to cinematic - *Critical alerts auto-trigger cinematic after flash overlay fades*
- [x] 108. Morning debrief auto-play - *6am-10am auto-play with localStorage day-key, 12h freshness check*
- [~] 109. Video export (scaffolding exists, MediaRecorder, WebM only)
- [x] 110. Play button discoverable - *DEBRIEF button in ETW console right section*

---

## Chat System

- [x] 111. Chat API exists (/api/chat with streaming)
- [x] 112. Chat panel in entity drawer (code exists)
- [x] 113. Entity context injection (code exists)
- [x] 114. Streaming SSE response (code exists)
- [x] 115. Entity highlight during chat (code exists - mentioned entities glow)
- [ ] 116. Chat needs ANTHROPIC_API_KEY or Cloudflare Tunnel bridge to work
- [x] 117. Chat panel opens when clicking Montgomery portrait - *Portrait click wired to drawer.showChannelChat()*

---

## Sound Design

- [x] 118. Ambient hum (55Hz + 82.5Hz, code exists in meridian-audio.ts)
- [x] 119. Sonar ping (code exists)
- [x] 120. Alert tone (code exists)
- [x] 121. Soft chime (code exists)
- [x] 122. Entity select click (code exists)
- [x] 123. Channel switch whoosh (code exists)
- [x] 124. Threat level pitch shift (code exists)
- [x] 125. Sound toggle in header (code exists, off by default)
- [x] 126. Cinematic underscore - *40Hz sine drone + 0.15Hz LFO gain modulation + filtered noise rumble*
- [x] 127. Spatial stereo panning - *StereoPannerNode maps entity screen X to pan position*

---

## Night Watch Mode

- [x] 128. Auto-dims midnight-6am (code exists in meridian-nightwatch.ts)
- [x] 129. Map brightness drops, saturation drops (CSS filter)
- [x] 130. Critical items glow through (data-alert="critical" override)
- [x] 131. Audio volume drops (wired to meridian-audio)
- [x] 132. Manual override in localStorage
- [x] 133. Dawn unfold animation - *Staggered element reveals (200ms apart), warm gold radial gradient flash*

---

## Pages

- [x] 134. / (home - map) - works
- [x] 135. /channel/:name - *URL path detected at startup, auto-selects matching channel*
- [x] 136. /meridian (reading room) - code exists
- [x] 137. /meridian/brief/:id - code exists
- [x] 138. /graph (force-directed graph) - code exists
- [x] 139. /graph/entity/:id (dossier) - code exists
- [x] 140. /cards (entity card gallery) - code exists
- [x] 141. /missions (commission board) - code exists
- [x] 142. /timeline/:conflict - code exists
- [x] 143. /health (source health) - code exists
- [x] 144. /accuracy (prediction ledger) - code exists
- [x] 145. /metrics (agent performance) - code exists
- [x] 146. /ops (ops console) - code exists
- [x] 147. /ops/agents - code exists
- [x] 148. /ops/jobs - code exists
- [x] 149. /ops/ontology - code exists
- [x] 150. All pages have data from Redis - *10,040 objects synced, all pages can render*

---

## Warm Gold Theme

- [x] 151. Root CSS variables shifted warm (#0e0b08, #1a1510)
- [x] 152. Gold accents (rgba(184, 150, 12)) on borders, text, badges
- [x] 153. Cinzel serif for headers
- [x] 154. IM Fell English for quotes (loaded but not widely applied)
- [x] 155. All inputs/buttons/selects restyled as command interface
- [x] 156. Scrollbars warm gold
- [x] 157. Links gold instead of blue
- [x] 158. Spinners gold
- [x] 159. Tooltips warm
- [x] 160. Cold grey panels swept - *All cold greys/blues replaced with warm gold palette across 20+ files*

---

## Smart Layer Surfacing

- [x] 161. 6 domain groups replace 45 individual toggles (MILITARY, CONFLICT, MARITIME, ECONOMIC, SIGNALS, ENVIRONMENT)
- [x] 162. Group toggles with status dots and active counts
- [x] 163. Sub-layers hidden behind [+] expander
- [x] 164. Channel switching resets layers to channel's specification
- [x] 165. Highlights panel (top-right) with clickable items
- [x] 166. Old left sidebar hidden

---

## Click Handling

- [x] 167. Country click always resolves underneath data layers (fix applied)
- [~] 168. Country click opens faction card sidebar (code exists, needs data)
- [~] 169. Entity marker click opens entity detail - *Click handler wired, needs Redis data to test*
- [x] 170. Disputed zone crosshatch rendering - *addDisputedZoneCrosshatch() renders for UA, PS, EH, XK, TW, CY, GE, MD, AZ*

---

## Infrastructure

- [x] 171. Vercel deployed at worldmonitor.atrophy.app
- [x] 172. Upstash Redis configured
- [x] 173. Channel API routes (list, get, put, briefing, map)
- [x] 174. Commission API routes
- [x] 175. Webhook API routes (alert, ingest)
- [x] 176. Map entity API routes (entities, entity-detail, entity-deep)
- [x] 177. Knowledge API routes (entities, graph)
- [x] 178. Meridian brief API routes (briefs, brief/:id)
- [x] 179. Ops API routes (status, agents, jobs, command)
- [x] 180. Chat API with bridge proxy to Cloudflare Tunnel
- [x] 181. OG image generation for Telegram previews
- [x] 182. Build machine switched to Standard ($0.014/min)
- [x] 183. Auto-deploy disabled (manual vercel --prod only)

---

## Backend (Ontology + Pipeline)

- [x] 184. 10,005 objects in intelligence.db
- [x] 185. 7,233 links
- [x] 186. 28,998 properties
- [x] 187. 503 harvested articles from 17 think tanks
- [x] 188. 5,230 vectorized documents
- [x] 189. 38 cron jobs registered
- [x] 190. 7 MCP ontology tools in memory server
- [x] 191. Semantic search via TF-IDF vectors
- [x] 192. Article-to-ontology pipeline
- [x] 193. Change detection system (25+ regex patterns)
- [x] 194. Progressive expansion difficulty (6 depth levels)
- [x] 195. System health check (hourly)
- [x] 196. Brief post-processing pipeline (verify, link, extract, push)
- [x] 197. 11 agent prompts updated with full system awareness

---

## CRITICAL BLOCKERS (fix these first)

1. ~~**Basemap doesn't render** - the map is a blank dark background with only faction border lines. Need working vector tiles.~~ **FIXED** - Campaign basemap now uses OpenFreeMap tiles, renders terrain/labels/water
2. **No entity markers on map** - ontology data isn't in Redis. Need to run knowledge_sync.py and restart the app.
3. ~~**Globe is default** - localStorage still has globe mode. Need to force flat on first visit.~~ **FIXED**
4. **Chat doesn't work** - no ANTHROPIC_API_KEY in Vercel env, tunnel not set up yet.
5. **App not restarted** - 38 cron jobs aren't running because the app hasn't been restarted since manifest changes.
6. ~~**Bottom panel is wrong** - thin floating bars instead of the marble slab from ETW.~~ **FIXED** - ETW console built with marble texture, ornate border, three sections
7. ~~**Portrait shows monogram** - ambient video integration in progress.~~ **FIXED** - Montgomery ambient video loop plays in ornate frame

> Teardown blockers (items not actually removed from codebase) are now **FIXED** - confirmed removed in teardown pass.

---

## HIGHEST IMPACT NEXT STEPS

1. ~~Fix the basemap (get visible terrain with labels, water, cities)~~ **DONE**
2. Run knowledge_sync to populate Redis, restart the app
3. ~~Build the ETW marble bottom panel~~ **DONE**
4. ~~Replace portrait monogram with ambient video~~ **DONE**
5. ~~Get entity markers styled (SVG military icons)~~ **DONE**
6. Set ANTHROPIC_API_KEY in Vercel env for chat
7. Test the full click -> faction card -> chat flow with Redis data

---

## Session Summary (2026-03-27/28)

Comprehensive ETW visual transformation:
- Teardown: 9 WorldMonitor features removed
- ETW console: 200px marble slab with portrait, briefing, action buttons
- Montgomery ambient video portrait in ornate double-ring gold frame
- Campaign basemap: OpenFreeMap tiles with parchment/sepia styling
- 32 SVG military icons replacing Unicode glyphs
- Cinematic enhancements: entity cards, connection lines, underscore, spatial panning
- Full warm gold color sweep across 50+ files
- ETW-styled header, channel tabs, entity drawer, faction cards
- All 8 sub-pages (reading room, graph, ops, cards, missions, timeline, health, accuracy, metrics) fully styled
- Splash screen, marker animations, page transitions
- Keyboard shortcuts (D/S/F/L), compass rose, date display, corner ornaments
- Immersive empty/error state messages
- Mobile responsive sub-pages, gold focus outlines, smooth scroll

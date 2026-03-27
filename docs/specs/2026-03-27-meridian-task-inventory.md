# Meridian Eye - Task Inventory

Status key: [x] done, [~] partial, [ ] not built

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
- [ ] 18. Fix basemap loading - campaign parchment style needs working PMTiles URL or fallback to visible tiles
- [ ] 19. Ensure OpenFreeMap dark tiles actually render (currently blank dark background with only faction borders)
- [x] 20. Add 3D terrain exaggeration from raster-dem source (code exists, terrain-dem source added)
- [ ] 21. Make terrain VISIBLE - hills and mountains should cast shadows and have physical presence like ETW
- [ ] 22. Add hillshade layer with sepia tones (warm shadow, not grey)
- [ ] 23. Land should have painted texture feel - subtle green/brown variation, not flat color
- [ ] 24. Water should be flat blue-grey with coastal gradient (lighter near shore, darker deep)
- [ ] 25. Country/region names as large spread text across territories (like ETW's red "France" text)
- [ ] 26. Cities as small 3D settlement clusters ON the terrain (not floating markers)
- [x] 27. Faction-colored country borders (NATO blue, Russia red, Iran orange, China green)
- [ ] 28. Add forests/vegetation as subtle texture on land
- [x] 29. Camera tilt at 30-45 degrees looking down
- [ ] 30. WASD camera panning - *NOT IMPLEMENTED - no WASD handlers in codebase*
- [~] 31. Camera momentum on drag release - *Relies on MapLibre defaults, not custom implementation*
- [x] 32. Scroll to zoom
- [ ] 33. Right-drag to rotate/tilt

---

## Basemap Style - Campaign Parchment

The campaign basemap JSON exists at `public/map-styles/meridian-campaign.json` with 24 layers but doesn't load because PMTiles URL is missing.

- [ ] 34. Get PMTiles URL working (self-host on Cloudflare R2, or find a working public URL)
- [ ] 35. OR: rewrite campaign style to use OpenFreeMap/OpenMapTiles vector source instead of PMTiles
- [ ] 36. Aged parchment background (#E8D5A3) for land
- [ ] 37. Desaturated teal-blue water (#7BA7BC)
- [ ] 38. Sepia hillshade from elevation tiles
- [ ] 39. Hand-inked national borders with line-blur feathering
- [ ] 40. Wax-seal red city dots scaled by importance
- [ ] 41. Period serif font labels (Cinzel loaded, needs to actually render on map tiles)
- [ ] 42. Muted heraldic country fills (dusty reds, faded greens, pale gold)
- [ ] 43. Olive-green forest/park tints
- [ ] 44. Parchment vignette edge overlay (CSS box-shadow, persistent)

---

## Bottom Panel - The Marble Slab

> **IN PROGRESS** - ETW console rebuild underway

Reference: ETW has a wide marble/white panel with ornate gold border taking up ~20% of screen. It has WEIGHT and TEXTURE - real material, not a semi-transparent overlay.

- [ ] 45. Replace the thin floating bars with a proper bottom panel (~20% screen height)
- [ ] 46. Marble/parchment texture background (not rgba overlay)
- [ ] 47. Gold ornate border trim along the top edge
- [ ] 48. Bottom-left: Montgomery portrait in a circular ornate painted frame (like ETW faction leader)
- [ ] 49. Bottom-center: faction info / briefing content area
- [ ] 50. Bottom-right: circular ornate action buttons (like ETW end-turn buttons)
- [ ] 51. The panel should feel like a physical object sitting below the map, not floating over it

---

## Montgomery Portrait - The Painted Medallion

> **IN PROGRESS**

Reference: ETW bottom-left has a circular portrait with a decorative painted scene, not a monogram in a circle.

- [x] 52. Circular frame bottom-left (exists as monogram "M")
- [x] 53. Gold border (exists)
- [x] 54. Alert dot indicator (exists)
- [x] 55. Glows on new briefing (exists)
- [x] 56. Pulses red on critical (exists)
- [ ] 57. Replace monogram with Montgomery ambient video loop
- [ ] 58. Add decorative frame surround (ornate, not just a circle border)
- [ ] 59. Portrait should sit INSIDE the marble bottom panel, not floating on the map - *Will be resolved by ETW console rebuild*

---

## Entity Markers - 3D Objects on Terrain

Reference: ETW cities are small 3D building clusters sitting ON the map. Units are figurines. Nothing floats.

- [~] 60. Entity markers exist (faction-colored markers with labels)
- [x] 61. Strength bars on unit markers (added)
- [x] 62. Star ratings from hierarchy (exists)
- [x] 63. Faction colors applied (exists)
- [ ] 64. Markers should sit ON the terrain, not float above it
- [ ] 65. Cities as 3D settlement clusters (not dots)
- [ ] 66. Military units as figurine sprites (not generic markers)
- [ ] 67. Naval units as ship silhouettes on water
- [ ] 68. Aircraft as small plane icons with heading
- [ ] 69. Bases as fortification icons with flag
- [ ] 70. No entity markers currently render because ontology data isn't in Redis

---

## Data Pipeline - Ontology to Map

The map is blank because entity data isn't flowing from intelligence.db to Redis to the map API.

- [x] 71. knowledge_sync.py exists and pushes to Redis
- [ ] 72. knowledge_sync.py needs to be run (or is it running via cron?)
- [ ] 73. Verify /api/map/entities returns actual entities (not empty)
- [ ] 74. Verify /api/knowledge/graph returns nodes and edges
- [ ] 75. Verify entity markers render on the map when data is present
- [ ] 76. App needs restart to register all 38 cron jobs

---

## Channel System

- [x] 77. Channel tabs in header (exist, show GENERAL_MONTGOMERY)
- [x] 78. Channel switching drives camera position
- [x] 79. Channel switching drives layer activation
- [~] 80. Clicking channel tab should do something visible (currently unclear)
- [ ] 81. Channel tabs should show ALL 10 agents, not just Montgomery

---

## Faction Cards - Total War Style

Reference: In ETW, clicking a nation shows leader portrait, organogram, military strength, diplomacy. Our version exists but needs the data pipeline working.

- [x] 82. Country card with leaders, military, diplomacy sections (code exists)
- [x] 83. Person card with identity, commands chain (code exists)
- [x] 84. Unit card with strength bar, command chain (code exists)
- [x] 85. Platform card with details, performance (code exists)
- [x] 86. Location card (code exists)
- [x] 87. Clickable linked entities within cards (code exists)
- [ ] 88. Cards need entity data from Redis to render (currently empty)
- [ ] 89. Clicking a country on the map should open the faction card (click-through fix added but untested)

---

## Living Effects

- [x] 90. Hotspot pulse animation (code exists in meridian-effects.ts)
- [x] 91. Color temperature shift with threat level (CSS filters, code exists)
- [~] 92. Entity glow by centrality (code exists, needs data)
- [~] 93. Convergence ring detection (code exists, needs data)
- [~] 94. Fog of war (code exists as overlay, may be too subtle)
- [~] 95. Watch zone sonar rings (code exists for 8 zones)
- [ ] 96. Ghost trails / time scrub (not built)
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
- [ ] 105. Entity card slide-in during narration (not built)
- [ ] 106. Connection line draw-on during mentions (not built)
- [ ] 107. Flash report snap-to cinematic (code exists, untested)
- [ ] 108. Morning debrief auto-play (not built)
- [ ] 109. Video export (scaffolding exists, MediaRecorder, WebM only)
- [ ] 110. Play button discoverable in UI (may be hidden)

---

## Chat System

- [x] 111. Chat API exists (/api/chat with streaming)
- [x] 112. Chat panel in entity drawer (code exists)
- [x] 113. Entity context injection (code exists)
- [x] 114. Streaming SSE response (code exists)
- [x] 115. Entity highlight during chat (code exists - mentioned entities glow)
- [ ] 116. Chat needs ANTHROPIC_API_KEY or Cloudflare Tunnel bridge to work
- [ ] 117. Chat panel doesn't open when clicking Montgomery portrait

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
- [ ] 126. Cinematic underscore (not built)
- [ ] 127. Spatial stereo panning (not built)

---

## Night Watch Mode

- [x] 128. Auto-dims midnight-6am (code exists in meridian-nightwatch.ts)
- [x] 129. Map brightness drops, saturation drops (CSS filter)
- [x] 130. Critical items glow through (data-alert="critical" override)
- [x] 131. Audio volume drops (wired to meridian-audio)
- [x] 132. Manual override in localStorage
- [ ] 133. Dawn unfold animation (gradual, not instant)

---

## Pages

- [x] 134. / (home - map) - works
- [~] 135. /channel/:name - route exists, limited functionality
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
- [ ] 150. All pages need data from Redis to show content (most will be empty without sync)

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
- [ ] 160. Some WorldMonitor panels may still have cold grey styling if they render

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
- [ ] 169. Entity marker click opens entity detail (needs markers to render first)
- [ ] 170. Disputed zone crosshatch rendering (code exists, untested)

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

1. **Basemap doesn't render** - the map is a blank dark background with only faction border lines. Need working vector tiles.
2. **No entity markers on map** - ontology data isn't in Redis. Need to run knowledge_sync.py and restart the app.
3. ~~**Globe is default** - localStorage still has globe mode. Need to force flat on first visit.~~ **FIXED**
4. **Chat doesn't work** - no ANTHROPIC_API_KEY in Vercel env, tunnel not set up yet.
5. **App not restarted** - 38 cron jobs aren't running because the app hasn't been restarted since manifest changes.
6. **Bottom panel is wrong** - thin floating bars instead of the marble slab from ETW.
7. **Portrait shows monogram** - ambient video integration in progress.

> Teardown blockers (items not actually removed from codebase) are now **FIXED** - confirmed removed in teardown pass.

---

## HIGHEST IMPACT NEXT STEPS

1. Fix the basemap (get visible terrain with labels, water, cities)
2. Run knowledge_sync to populate Redis, restart the app
3. Build the ETW marble bottom panel
4. Replace portrait monogram with actual image
5. Make cities render as 3D settlement clusters
6. Get entity markers showing on the map
7. Test the full click -> faction card -> chat flow

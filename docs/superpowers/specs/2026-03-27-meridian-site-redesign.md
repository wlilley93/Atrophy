# Meridian Eye - A Living Intelligence Map

The map is a game. Not a dashboard you read - an environment you move through. Free camera, clickable units, game-style HUD, your intelligence advisor in a portrait frame telling you what matters. Think Empire Total War's campaign map meets a classified briefing room.

Briefings are cinematic. Letterbox bars slide in, the camera sweeps across theaters, units animate along their historical paths showing time passing, and Montgomery narrates over the top. When it ends, the bars retract and you're back in control.

The map breathes. It shows a living picture of the world as understood by an intelligence team that never sleeps. Every pulse, every glow, every connection line reflects real analytical work - cron jobs polling, agents analyzing, the ontology growing, 6,322 objects linked by 7,218 relationships and described by 28,976 properties.

This specification describes the complete transformation of the WorldMonitor fork at `worldmonitor.atrophy.app` into Meridian Eye - an intelligence experience that feels more like a military strategy game than a web dashboard. The platform already has globe.gl for 3D rendering, deck.gl for WebGL data layers, MapLibre for 2D tiles, and 60+ Vercel Edge Functions serving live data. What it lacks is soul. The data is there. The analytical depth is there. What is missing is the feeling that you are standing in a command center, looking down at the world through the eyes of a team that has been watching it for months.

The document that follows describes every feature, every visual effect, every interaction, every technical implementation detail, and every integration point needed to build this experience. It is written so that someone reading it cold could implement the entire system without any other context. Nothing is left to imagination. Every shader is sketched. Every animation curve is specified. Every data flow is traced from database to pixel.

## Status Note

This is a target-state build spec, not a claim that every section is already live.

- **Shipped now**: the backend Meridian plumbing already in production or committed locally around channels, chat, webhooks, and the intelligence pipeline.
- **Implemented locally but not yet deployed**: the current Phase 1 Meridian `full` experience baseline in the `worldmonitor` fork, including the globe-first shell, floating HUD, orbital descent wiring, and map entity support endpoints.
- **Roadmap / later phases**: everything below covering unit figurines, cinematic briefings, game systems, graph pages, export, and other advanced interactions unless explicitly called out as already delivered elsewhere.

---

## Core Experience

### Entry: Orbital Descent

You load meridian.atrophy.app. You do not see a map. You see Earth from space - a satellite view, slowly rotating. Data feeds stream down from orbit like faint rain. You click or scroll and the camera dives through the atmosphere, punching through clouds, and lands on Montgomery's current focus area. Every session starts with this 3-second descent. It sets the tone: you are looking down at the world from above.

The orbital descent is not a loading screen. It is a psychological transition. The user is moving from their world into the intelligence picture. The descent communicates scale - you are seeing the whole planet, and you are about to zoom into the places that matter. It communicates authority - you are not at ground level scrambling for information, you are observing from above with the full picture available.

The technical implementation uses globe.gl's camera system with a GSAP timeline to orchestrate the transition. On initial page load, the globe renders at an altitude of approximately 35,000 kilometers - high enough that the Earth fills about 60% of the viewport. The globe rotates slowly at 0.05 degrees per frame. A custom Three.js particle system renders the data feed rain: 200 small particles (2px, white, opacity 0.15) falling in straight vertical lines from the top of the viewport toward the globe surface, each with a randomized x-position and a fall speed of 3-5 pixels per frame. The particles fade to zero opacity as they approach the globe surface, creating the illusion of data being absorbed into the planet.

When the user scrolls or clicks, a GSAP timeline fires with the following sequence. Over the first 0.8 seconds, the camera altitude drops from 35,000km to 8,000km using an `power2.inOut` easing curve. During this phase, the data rain particles accelerate and spread, creating a sense of rushing through them. Over the next 1.2 seconds, the camera continues descending from 8,000km to the target altitude (typically 2,000-4,000km depending on the current channel's zoom level), while simultaneously rotating to match the channel's bearing and pitch. The camera also translates laterally to center on the channel's focus coordinates. During this phase, cloud layers (rendered as a semi-transparent white noise texture on a sphere at 12km altitude) rush past the camera. Over the final 1.0 second, the camera settles into the channel's exact camera position with a gentle `power1.out` ease, and the HUD elements fade in from zero opacity.

The GSAP timeline definition looks approximately like this:

```typescript
const descentTimeline = gsap.timeline({ paused: true });

descentTimeline
  .to(camera, {
    altitude: 8000,
    duration: 0.8,
    ease: 'power2.inOut',
    onUpdate: () => {
      particleSystem.setSpeed(camera.altitude / 5000);
      globe.pointOfView({ altitude: camera.altitude });
    }
  })
  .to(camera, {
    altitude: targetAltitude,
    lat: targetLat,
    lng: targetLng,
    duration: 1.2,
    ease: 'power2.out',
    onUpdate: () => {
      globe.pointOfView({
        altitude: camera.altitude,
        lat: camera.lat,
        lng: camera.lng
      });
    }
  }, '-=0.2')
  .to(hudContainer, {
    opacity: 1,
    duration: 0.6,
    ease: 'power1.out'
  }, '-=0.4')
  .to(particleSystem, {
    opacity: 0,
    duration: 0.5
  }, '-=0.6');
```

The cloud layer is a Three.js `SphereGeometry` with radius slightly larger than the globe, textured with a tileable cloud noise texture. The shader for the clouds uses a simple fragment shader that takes a noise texture and applies it as alpha, with the cloud opacity increasing between 8,000km and 15,000km altitude:

```glsl
uniform sampler2D cloudTexture;
uniform float cameraAltitude;
varying vec2 vUv;

void main() {
  float cloudAlpha = texture2D(cloudTexture, vUv).r;
  float altitudeFade = smoothstep(8000.0, 15000.0, cameraAltitude);
  gl_FragColor = vec4(1.0, 1.0, 1.0, cloudAlpha * altitudeFade * 0.4);
}
```

If the user has visited before (checked via `localStorage.getItem('meridian-visited')`), the descent is shortened to 1.5 seconds total and skips the initial orbital rotation. The camera starts at 15,000km instead of 35,000km. A settings toggle allows disabling the descent entirely, in which case the page loads directly at the channel's camera position with a simple 0.5-second fade-in.

### Default: The Campaign Map

Once the descent completes, the user sees the campaign map - the primary interface they will spend most of their time in. A dark 3D globe fills the screen edge to edge, rendered by globe.gl with a custom dark basemap. The globe occupies the full browser viewport with no margins. All UI elements float on top of the WebGL canvas as absolutely-positioned HTML elements.

The camera is fully free. The user can orbit the globe by clicking and dragging. Scrolling zooms in and out. Right-click dragging adjusts the pitch (tilt angle) and bearing (rotation). WASD keys pan the camera - W moves the camera north, A west, S south, D east, with the speed proportional to the current zoom level so that movement feels consistent regardless of how close you are. The camera has smooth momentum - releasing a drag does not stop the camera instantly but allows it to coast for 0.3 seconds with a deceleration curve. This is achieved by tracking the mouse velocity over the last 3 frames and applying that velocity with exponential decay after mouse-up.

Hotspots pulse where things are happening. Every object in the ontology that has geographic coordinates and has been updated in the last 7 days renders as a subtle glow on the map. The glow intensity and pulse speed reflect recency. An event that happened in the last hour pulses at 1.0 Hz with full intensity. An event from yesterday pulses at 0.5 Hz at 60% intensity. An event from 3 days ago pulses at 0.2 Hz at 30% intensity. Events older than 7 days do not pulse - they are static dim glows that serve as historical markers.

The pulse is implemented using deck.gl's `ScatterplotLayer` with a custom `getRadius` accessor that varies with time:

```typescript
new ScatterplotLayer({
  id: 'hotspot-pulse',
  data: activeEvents,
  getPosition: d => [d.lon, d.lat],
  getRadius: d => {
    const ageHours = (Date.now() - d.timestamp) / 3600000;
    const baseRadius = 5000 + d.severity * 2000;
    const pulseFreq = Math.max(0.2, 1.0 - ageHours / 168);
    const pulseAmp = Math.max(0.1, 1.0 - ageHours / 168);
    const pulse = 1 + Math.sin(Date.now() / 1000 * pulseFreq * Math.PI * 2) * 0.3 * pulseAmp;
    return baseRadius * pulse;
  },
  getFillColor: d => {
    const ageHours = (Date.now() - d.timestamp) / 3600000;
    const alpha = Math.max(30, 200 - ageHours * 1.2);
    return [255, 100, 50, alpha];
  },
  radiusMinPixels: 3,
  radiusMaxPixels: 40,
  parameters: { blend: true, blendFunc: [GL.SRC_ALPHA, GL.ONE] }
});
```

The additive blend mode (`blendFunc: [SRC_ALPHA, ONE]`) is critical - it makes overlapping hotspots glow brighter rather than occluding each other. This creates the effect of conflict zones appearing as bright pools of light while isolated events are dim sparks.

Units sit on their deployment locations as clickable figurines. Every military entity in the ontology - units, platforms, bases - renders at its geographic position with a faction-colored marker. At the default zoom level (showing a continent), these are small 2D sprites rendered via deck.gl's `IconLayer`. As the user zooms in, the sprites transition to larger, more detailed representations. The figurine system is described in full detail in the Unit Markers section below.

Montgomery's portrait glows in the corner. A 120x120 pixel frame sits in the bottom-left of the viewport, showing Montgomery's avatar image. The frame has a subtle gold border (2px, `rgba(200, 170, 100, 0.4)`) that pulses gently at 0.3 Hz when a fresh briefing is available. When TTS audio is playing, the border brightens and a subtle animated ring effect pulses outward from the frame at the cadence of the speech. When idle and no fresh briefing exists, the frame dims to 60% opacity with no animation.

His one-line assessment floats at the top of the screen. Below the MERIDIAN EYE header, a single line of text in `rgba(255, 255, 255, 0.7)` at 14px displays Montgomery's current top-line assessment. This text is pulled from the active channel's `briefing.summary` field. It fades in with a typewriter effect on page load (each character appearing over 30ms) and transitions with a crossfade when the channel switches.

The overall color temperature of the map is the threat level. This is not a badge or a label - it is a pervasive visual atmosphere that colors everything on the screen. At NORMAL threat level, the globe's base color temperature is cool blue-grey. The basemap tiles have a slight blue tint applied via a CSS filter on the canvas: `filter: hue-rotate(-10deg) saturate(0.8) brightness(0.9)`. The HUD elements use cool blue accents (`rgba(100, 160, 255, 0.3)` for borders, `rgba(80, 140, 220, 0.2)` for backgrounds).

At ELEVATED threat level, the color temperature shifts to amber. The CSS filter transitions over 2 seconds to `filter: hue-rotate(15deg) saturate(1.1) brightness(0.95) sepia(0.15)`. HUD accents shift to amber (`rgba(255, 180, 60, 0.3)`). The pulse of hotspots takes on a warmer hue. The effect is subtle but unmistakable - the world feels warmer, tenser.

At CRITICAL threat level, red heat blooms from conflict zones. The CSS filter shifts to `filter: hue-rotate(0deg) saturate(1.3) brightness(1.0) sepia(0.1)`. But the main effect is not a global filter - it is localized. The `ScatterplotLayer` for CRITICAL events uses much larger radii and brighter colors. A second layer, a `HeatmapLayer`, activates only at CRITICAL level, creating pools of red-orange heat around the critical zones. The HUD border color shifts to red (`rgba(255, 60, 40, 0.4)`). Montgomery's portrait frame pulses faster (0.8 Hz) with a red glow.

The transitions between threat levels use GSAP to tween CSS custom properties over 2 seconds:

```typescript
function setThreatLevel(level: 'normal' | 'elevated' | 'critical') {
  const themes = {
    normal: { hue: -10, sat: 0.8, bright: 0.9, sepia: 0, accent: 'rgba(100,160,255,0.3)' },
    elevated: { hue: 15, sat: 1.1, bright: 0.95, sepia: 0.15, accent: 'rgba(255,180,60,0.3)' },
    critical: { hue: 0, sat: 1.3, bright: 1.0, sepia: 0.1, accent: 'rgba(255,60,40,0.4)' }
  };
  const t = themes[level];
  gsap.to(document.documentElement, {
    '--hue': t.hue,
    '--saturation': t.sat,
    '--brightness': t.bright,
    '--sepia': t.sepia,
    '--accent': t.accent,
    duration: 2,
    ease: 'power2.inOut'
  });
}
```

The canvas element has its filter driven by these properties: `filter: hue-rotate(var(--hue)deg) saturate(var(--saturation)) brightness(var(--brightness)) sepia(var(--sepia))`.

You feel the state of the world in the color before reading anything. That is the design intent. A user who glances at the screen for half a second should immediately sense whether the world is calm, tense, or on fire.

### Interaction: Click to Converse

Click any entity on the map. Montgomery's portrait activates. The entity's full ontology profile loads silently. You are in conversation with the analyst who owns that domain. "That's the 72nd Mechanized Brigade. They've held this position since February. Three briefs mention them." You follow up. He pulls from the graph. The map highlights what he is discussing.

This is not a tooltip. Not a wiki popup. A conversation with a commander who knows the entire knowledge graph.

When the user clicks an entity marker on the map, three things happen simultaneously. First, the chat panel slides up from the bottom of the viewport. It occupies the bottom 35% of the screen height, with a semi-transparent dark background (`rgba(10, 10, 15, 0.92)`) and a 1px top border in the current accent color. The slide-up animation takes 0.3 seconds with `power2.out` easing. Second, the entity's full ontology data is fetched from the platform API - the object itself, all its properties, all its links (both inbound and outbound), all briefs that mention it, and its changelog. Third, this data is assembled into a context payload that will be sent alongside the user's messages to the Claude API for inference.

The chat panel has a simple layout. On the left side (30% width), the entity's card is displayed - its name, type badge, key properties, faction color, and a miniature relationship graph showing first-hop connections. On the right side (70% width), the chat interface renders with a message history area and a text input at the bottom. The input field has a placeholder that reads "Ask Montgomery about [entity name]..." in dim text.

When the user types a question and presses Enter, the message is sent to a Vercel Edge Function at `/api/chat`. This function constructs a Claude API call with a system prompt that includes the entity's full ontology context:

```typescript
const systemPrompt = `You are General Montgomery, intelligence analyst.
You are discussing ${entity.name} (${entity.type}/${entity.subtype}).

ENTITY CONTEXT:
${JSON.stringify(entityData, null, 2)}

RELATIONSHIPS:
${relationships.map(r => `${r.type}: ${r.relatedName} (confidence: ${r.confidence})`).join('\n')}

RECENT BRIEFS MENTIONING THIS ENTITY:
${briefs.map(b => `[Brief #${b.id}] ${b.title} (${b.date}): ${b.content.substring(0, 500)}...`).join('\n\n')}

RELEVANT ARTICLES FROM THINK TANKS:
${articles.map(a => `[${a.source}] ${a.title} (${a.date}): ${a.summary}`).join('\n\n')}

ONTOLOGY STATS: ${ontologyStats.objects} objects, ${ontologyStats.links} links.

Respond as Montgomery would - terse, analytical, grounded in the data.
Reference specific briefs, relationships, and timeline events.
Never hallucinate data not present in the context above.`;
```

The inference response streams back via Server-Sent Events. As tokens arrive, they render in the chat panel with a typing effect. When Montgomery's response references another entity (detected by matching entity names against the ontology), those names become clickable links that, when clicked, pan the map to the referenced entity's location and highlight it with a pulse effect.

When Montgomery's response mentions a relationship ("Iran funds the Houthis"), the corresponding connection line on the map lights up - drawing an animated arc from Iran to Yemen's Houthi-controlled territory. This is achieved by parsing the assistant's response for relationship verbs that match link types in the ontology (`funds`, `arms`, `opposes`, `commands`, etc.) and then activating the corresponding `ArcLayer` arcs.

The chat panel can be dismissed by pressing Escape, clicking outside it, or clicking the close button in its top-right corner. When dismissed, it slides back down over 0.2 seconds and the entity's highlight on the map fades out.

---

## Cinematic Briefings

The signature feature. When a briefing plays, the map becomes a movie.

A cinematic briefing is an orchestrated sequence of camera movements, entity animations, audio narration, and visual effects that transforms the static intelligence map into a time-sequenced narrative. It is the difference between reading a report and watching a documentary. The user sees the world as Montgomery sees it - a connected series of events unfolding across geography and time, narrated by the analyst who produced the assessment.

### How It Works

The cinematic plays in a defined sequence that transforms the map interface into a letterboxed movie. Here is the complete step-by-step flow from the moment a briefing is triggered to the moment control returns to the user.

First, the letterbox bars animate in. Two black rectangles (100% viewport width, initially 0px height) slide in from the top and bottom of the screen over 0.4 seconds with `power2.inOut` easing. Their final height is calculated to crop the viewport to a 2.39:1 aspect ratio (standard cinematic widescreen). On a 1920x1080 display, each bar is approximately 120px tall. The bars have a subtle gradient - solid black at the edge, fading to transparent over the last 10px - so they blend softly into the map rather than cutting hard. During this animation, the HUD elements (header bar, resource bar, layer toggles, chat panel) fade to zero opacity over 0.3 seconds. Montgomery's portrait remains visible but repositions to the lower-left corner just above the bottom letterbox bar, framed by a subtle gold glow.

Second, the camera begins moving along a scripted path. The path is defined by the briefing's waypoint array. Between each waypoint, the camera follows a cubic Bezier curve calculated from the two endpoints and two control points. The control points are generated automatically: the first control point is offset from the start position by 30% of the total distance at a bearing perpendicular to the direct line between start and end, and the second control point mirrors this from the end position. This creates gentle S-curves between waypoints rather than straight lines, which feels cinematic rather than mechanical. The camera movement uses GSAP's timeline system with each waypoint transition as a tween:

```typescript
function buildCameraPath(waypoints: Waypoint[]): gsap.core.Timeline {
  const tl = gsap.timeline();

  for (let i = 0; i < waypoints.length; i++) {
    const wp = waypoints[i];
    const transitionDuration = i === 0 ? 2.0 : calculateTransitionTime(waypoints[i-1], wp);

    // Camera transition to this waypoint
    tl.to(cameraState, {
      lat: wp.lat,
      lng: wp.lon,
      altitude: zoomToAltitude(wp.zoom),
      bearing: wp.bearing,
      pitch: wp.pitch,
      duration: transitionDuration,
      ease: 'power1.inOut',
      onUpdate: () => {
        globe.pointOfView({
          lat: cameraState.lat,
          lng: cameraState.lng,
          altitude: cameraState.altitude
        });
      }
    });

    // Hold at this waypoint while narration plays
    tl.to({}, {
      duration: wp.duration_sec,
      onStart: () => {
        activateLayers(wp.layers);
        showMarkers(wp.markers);
        highlightEntities(wp.entities);
        if (wp.unit_movements) animateUnitMovements(wp.unit_movements);
        if (wp.connections) drawConnections(wp.connections);
        startNarrationSegment(wp.narration);
      }
    });
  }

  return tl;
}

function calculateTransitionTime(from: Waypoint, to: Waypoint): number {
  const distance = haversineDistance(from.lat, from.lon, to.lat, to.lon);
  // Aim for 40-80 degrees per second of camera travel
  const baseDuration = distance / 60;
  return Math.max(1.5, Math.min(4.0, baseDuration));
}

function generateBezierControlPoints(
  start: [number, number],
  end: [number, number]
): { cp1: [number, number]; cp2: [number, number] } {
  const midLat = (start[0] + end[0]) / 2;
  const midLon = (start[1] + end[1]) / 2;
  const dx = end[1] - start[1];
  const dy = end[0] - start[0];
  const perpDx = -dy * 0.3;
  const perpDy = dx * 0.3;

  return {
    cp1: [start[0] + (end[0] - start[0]) * 0.33 + perpDy, start[1] + (end[1] - start[1]) * 0.33 + perpDx],
    cp2: [start[0] + (end[0] - start[0]) * 0.67 - perpDy, start[1] + (end[1] - start[1]) * 0.67 - perpDx]
  };
}
```

Third, Montgomery's voice narrates. The narration text for each waypoint is sent to the ElevenLabs API for TTS generation. Audio is fetched as an MP3 stream and played through an HTML5 Audio element. The audio playback is synchronized with the camera hold duration at each waypoint. If the narration is longer than the hold duration, the hold extends to match. If it is shorter, the camera holds in silence for the remaining time before transitioning. The audio system pre-fetches the next waypoint's narration during the current hold to eliminate gaps.

Fourth, units animate along their movement paths. When a waypoint includes `unit_movements`, each specified unit's marker smoothly interpolates from its `from` position to its `to` position over the hold duration. The interpolation uses linear easing for military precision - units move at constant speed. A fading trail renders behind the moving unit using deck.gl's `TripsLayer`, showing the path it has taken. The trail color matches the unit's faction color at 40% opacity and fades to transparent over 3 seconds. Multiple units can move simultaneously if the waypoint specifies several movements.

```typescript
function animateUnitMovements(movements: UnitMovement[], duration: number) {
  movements.forEach(m => {
    const unitMarker = entityMarkers.get(m.unit_id);
    if (!unitMarker) return;

    // Create trail path
    const trailPath = {
      path: [m.from, m.to],
      timestamps: [0, duration * 1000],
      color: getFactionColor(unitMarker.faction)
    };
    trailPaths.push(trailPath);

    // Animate marker position
    gsap.to(unitMarker.position, {
      0: m.to[0], // lat
      1: m.to[1], // lon
      duration: duration * 0.8, // Move in 80% of hold time, settle for 20%
      ease: 'none', // Linear - military units move at constant speed
      onUpdate: () => updateMarkerPosition(m.unit_id, unitMarker.position)
    });
  });
}
```

Fifth, events pop as the camera passes them. ACLED events in the current viewport spark with a bright flash when the camera arrives at a waypoint. The flash is a rapid expansion of the event's ScatterplotLayer point from its normal radius to 3x its radius over 0.2 seconds, followed by a contraction back to normal over 0.5 seconds, with brightness spiking and then decaying. Thermal clusters bloom - a heat gradient expands from their center over 1 second. OREF alerts flash with a sharp white-to-red pulse. Each event type has a distinct pop animation that makes it visually identifiable even at a glance.

Sixth, entity cards slide in from the edge of the screen when entities are mentioned in the narration. The cards are 280px wide and 180px tall, with a dark semi-transparent background, faction-colored left border (4px), and contain the entity's name, type, and 2-3 key properties. They slide in from the right edge over 0.3 seconds, hold for 4-6 seconds (timed to the narration segment that mentions them), and then slide out to the right over 0.2 seconds. No more than 2 cards are visible simultaneously. If a third entity is mentioned while two cards are showing, the oldest card slides out to make room. The timing is calculated from word count: the narration text is split by entity mentions, and each segment's word count is multiplied by 0.4 seconds (average speaking speed of 150 words per minute) to estimate when that entity's card should appear.

```typescript
function scheduleEntityCards(narration: string, entities: number[], holdDuration: number) {
  const words = narration.split(/\s+/);
  const totalWords = words.length;

  entities.forEach(entityId => {
    const entity = ontology.getObject(entityId);
    if (!entity) return;

    // Find where this entity is first mentioned in the narration
    const entityNames = [entity.name, ...(entity.aliases || [])];
    let mentionWordIndex = totalWords; // Default to end
    for (const name of entityNames) {
      const idx = narration.toLowerCase().indexOf(name.toLowerCase());
      if (idx >= 0) {
        const wordsBeforeMention = narration.substring(0, idx).split(/\s+/).length;
        mentionWordIndex = Math.min(mentionWordIndex, wordsBeforeMention);
      }
    }

    const appearTime = (mentionWordIndex / totalWords) * holdDuration;
    const displayDuration = Math.min(5, holdDuration - appearTime);

    setTimeout(() => showEntityCard(entity, displayDuration), appearTime * 1000);
  });
}
```

Seventh, connection lines draw themselves between entities as relationships are discussed. When the narration mentions a relationship ("Iran supplies weapons to the Houthis"), an `ArcLayer` arc animates from the source entity to the target entity. The arc starts as a point at the source and extends to the target over 1.5 seconds, with a glowing leading edge. The arc color reflects the relationship type (red for arms/adversarial, amber for alliance, blue for command hierarchy, gold for economic). The arc remains visible for the rest of the waypoint's hold duration and then fades out over 0.5 seconds during the transition to the next waypoint.

```typescript
function drawConnection(fromId: number, toId: number, type: string) {
  const from = ontology.getObject(fromId);
  const to = ontology.getObject(toId);
  if (!from?.lat || !to?.lat) return;

  const arcData = {
    source: [from.lon, from.lat],
    target: [to.lon, to.lat],
    color: getRelationshipColor(type),
    progress: 0 // Animated from 0 to 1
  };

  connectionArcs.push(arcData);

  gsap.to(arcData, {
    progress: 1,
    duration: 1.5,
    ease: 'power2.out'
  });
}

// The ArcLayer uses getTargetPosition with progress interpolation:
new ArcLayer({
  id: 'cinematic-connections',
  data: connectionArcs,
  getSourcePosition: d => d.source,
  getTargetPosition: d => [
    d.source[0] + (d.target[0] - d.source[0]) * d.progress,
    d.source[1] + (d.target[1] - d.source[1]) * d.progress
  ],
  getSourceColor: d => [...d.color, 200],
  getTargetColor: d => [...d.color, 255],
  getWidth: 2,
  greatCircle: true
});
```

Eighth, convergence rings ripple when the narration identifies pattern overlaps. If a waypoint's narration discusses the convergence of multiple signal types (detected by keywords like "convergence", "overlap", "multiple signals", "pattern"), concentric rings animate outward from the waypoint's center coordinates. Three rings expand from radius 0 to 200km over 2 seconds at 0.3 second intervals, each with decreasing opacity (0.4, 0.25, 0.15). The rings are rendered using deck.gl's `ScatterplotLayer` with `filled: false` and `stroked: true`.

Ninth, at each waypoint, the camera holds for the specified duration while the relevant assessment plays. Markers and layers for that region activate at the start of the hold. Layers activate by toggling their visibility in the deck.gl layer stack. Markers appear by adding them to the marker dataset with an entrance animation (scale from 0 to 1 over 0.2 seconds). When the camera transitions away from a waypoint, markers that are specific to that waypoint (not part of the persistent dataset) fade out over 0.5 seconds.

Tenth, the ending. After the final waypoint's narration completes, the camera pulls back to a full globe view over 3 seconds. The pull-back uses `power2.inOut` easing and targets the globe at approximately 20,000km altitude, centered on the highest-alert theater. During the pull-back, all cinematic-specific layers (unit movement trails, connection arcs, convergence rings, waypoint-specific markers) fade out. The letterbox bars retract over 0.4 seconds. The HUD elements fade back to full opacity over 0.3 seconds. A brief summary text appears at the bottom center of the screen for 5 seconds - the briefing's `ending.summary` field - then fades out. The user is back in control, positioned at the highest-alert theater so they can immediately begin exploring the most important area.

### Briefing Data Structure

Each briefing defines waypoints that drive the cinematic. The complete data structure stored in Upstash Redis alongside the channel state:

```json
{
  "id": "brief-2026-03-27-morning",
  "title": "Morning Assessment - 27 March 2026",
  "agent": "general_montgomery",
  "product_type": "WEEKLY_DIGEST",
  "created_at": "2026-03-27T07:00:00Z",
  "audio_url": "https://cdn.meridian.atrophy.app/audio/brief-2026-03-27.mp3",
  "waypoints": [
    {
      "lat": 48.5,
      "lon": 37.0,
      "zoom": 6,
      "bearing": 30,
      "pitch": 45,
      "duration_sec": 8,
      "narration": "The contact line near Kherson shows three new thermal clusters since yesterday evening. Combined with increased military flight activity over the Sea of Azov, this suggests preparation for a renewed push along the southern axis.",
      "layers": ["thermal-escalations", "acled-events", "military-flights"],
      "markers": [
        {"lat": 46.6, "lon": 32.6, "label": "Kherson thermal cluster", "type": "event", "severity": "high"},
        {"lat": 46.9, "lon": 33.1, "label": "New positions detected", "type": "movement"}
      ],
      "entities": [72, 89, 45],
      "unit_movements": [
        {"unit_id": 234, "from": [48.0, 36.5], "to": [48.3, 37.1], "type": "advance"},
        {"unit_id": 235, "from": [47.5, 36.8], "to": [47.8, 37.0], "type": "advance"}
      ],
      "connections": []
    },
    {
      "lat": 26.5,
      "lon": 56.2,
      "zoom": 7,
      "bearing": -20,
      "pitch": 40,
      "duration_sec": 6,
      "narration": "In the Strait of Hormuz, SIGINT detected increased IRGC-Navy activity. Two fast attack craft squadrons sortied from Bandar Abbas at 0340 local time. This correlates with an uptick in GPS jamming across the strait. The IRGC has form for pre-positioning before tanker harassment operations.",
      "layers": ["military-flights", "ais-vessels", "gps-jamming"],
      "entities": [156, 78, 203],
      "connections": [
        {"from": 156, "to": 78, "type": "operates"},
        {"from": 78, "to": 203, "type": "deployed_to"}
      ]
    }
  ],
  "ending": {
    "lat": 30,
    "lon": 30,
    "zoom": 2,
    "summary": "Global threat level: ELEVATED. Primary concern: Kherson convergence. Secondary: Hormuz IRGC surge."
  }
}
```

### When Briefings Play

Different types of briefings trigger at different times and with different behaviors.

The morning brief at 07:00 auto-plays on page load if the brief is fresh (created within the last 2 hours). When the user loads the page and a fresh morning brief exists, the orbital descent leads directly into the cinematic without stopping at the free-camera state. The descent's final position targets the first waypoint of the morning brief, and the letterbox bars slide in as the descent concludes. If the user has already viewed the morning brief (tracked via localStorage), it does not auto-play on subsequent visits that day.

Flash reports play immediately when they arrive, interrupting whatever the user is doing. Flash reports are pushed to the platform via the channel API and detected by the frontend through a polling mechanism (every 15 seconds) or, if WebSocket support is added, via real-time push. When a flash report arrives, the current state is saved (camera position, active layers, open panels), the letterbox bars slide in, and the flash cinematic plays. Flash cinematics are simpler than standard briefings: the camera snaps to the event location with a rapid 1-second zoom (no graceful Bezier curve - urgency demands speed), Montgomery speaks the alert in his most terse voice, and the briefing ends after a single waypoint. The snap-to effect uses `power4.out` easing for a sharp deceleration that communicates urgency.

Three-hour updates are available as a "Play briefing" button in the briefing panel but do not auto-play. The user clicks a triangular play icon (styled like a media player button, not a web button) and the cinematic begins from the current camera position, transitioning to the first waypoint.

On-demand playback is available for any briefing in the reading room (`/meridian`). Each brief card has a play button. Clicking it transitions the viewport from the reading room page back to the globe view and begins the cinematic.

The daily debrief at a configurable time (default 07:00) is a special 60-second automated flyover of all active theaters. It is generated automatically from the latest channel states without agent involvement. The debrief script reads all channels, orders them by alert level (CRITICAL first, then ELEVATED, then NORMAL), generates a waypoint for each active channel's camera position, and assembles narration from each channel's `briefing.summary`. The result is a rapid tour of the entire intelligence picture.

### Generating Briefing Cinematics

When an agent produces a brief, the cinematic waypoints are generated automatically from the brief text and the ontology. This is the pipeline that turns prose intelligence into a visual experience.

Step one: the brief text is parsed for geographic references. Every entity name in the text is matched against the ontology (using name and alias matching). For each matched entity that has lat/lon coordinates, a geographic reference is recorded with its position in the text (character offset) and its coordinates. Location names that are not in the ontology are geocoded using a simple lookup table of major cities and geographic features stored in the platform.

Step two: waypoints are generated from the sequence of geographic references. The text is segmented by geography - when the narrative moves from discussing one region to another, a new waypoint is created. Two geographic references within 500km of each other are considered the same waypoint. The waypoint's center is the centroid of all references within that cluster. The zoom level is calculated from the bounding box of the cluster - a tight cluster (all references within 100km) gets zoom 8, a wide cluster (500km spread) gets zoom 5. The bearing is set to 0 by default but rotated to face the direction of the next waypoint if one exists. The pitch is set to 45 degrees for standard waypoints and 60 degrees for close-up waypoints (zoom >= 8).

Step three: unit movements are derived from ontology changes. The system compares the current positions of military entities (from their `last_position_lat/last_position_lon` properties) against their positions at the time of the previous brief or data poll. Any entity whose position changed by more than 10km generates a unit movement animation. The movement `type` is classified by direction relative to the conflict frontline: toward the frontline is `advance`, away is `retreat`, lateral is `reposition`.

Step four: entity cards are queued for any ontology objects mentioned in the narration text. The queuing algorithm identifies which entities are mentioned in each waypoint's narration segment and schedules their card appearances as described in the entity card timing section above.

Step five: connection lines are drawn from any relationships referenced in the text. The system scans the narration for relationship verbs (funds, arms, opposes, commands, deploys, supplies, targets, allies) and attempts to match the surrounding entity names to ontology links. If a match is found, the connection is added to the waypoint.

Step six: the camera path is smoothed. The raw waypoint sequence is processed to ensure camera transitions are smooth. If two consecutive waypoints are on opposite sides of the globe, an intermediate waypoint is inserted at the midpoint with a high altitude (global view) to prevent the camera from clipping through the Earth. If two consecutive waypoints are very close (within 200km), the transition time is shortened to 1 second to maintain pacing.

```typescript
interface BriefCinematicGenerator {
  generateFromBrief(brief: Brief, ontology: OntologyStore): CinematicData;
  parseGeographicReferences(text: string, ontology: OntologyStore): GeoReference[];
  clusterReferencesIntoWaypoints(refs: GeoReference[]): Waypoint[];
  deriveUnitMovements(ontology: OntologyStore, since: Date): UnitMovement[];
  extractRelationshipMentions(text: string, ontology: OntologyStore): ConnectionDraw[];
  smoothCameraPath(waypoints: Waypoint[]): Waypoint[];
  estimateNarrationTiming(text: string): number; // seconds
}
```

For flash reports, the cinematic generation is simpler. A flash report has a single geographic focus. The generator creates one waypoint at the event location with a tight zoom, the full flash text as narration, and any entities mentioned in the text as card appearances. No unit movements or connection lines - flash reports are about a moment, not a narrative.

### Export

Briefing cinematics can be exported as video. This enables sharing intelligence briefings as self-contained video files that can be sent to Telegram, embedded in presentations, or archived.

The export pipeline works by rendering the WebGL canvas frame by frame using a headless browser. A Vercel serverless function (or, more practically, a local Node.js script on the Atrophy host machine) launches Puppeteer with a headless Chromium instance, navigates to a special export URL (`/export/cinematic/:briefId`), and captures frames. The export page loads the same cinematic playback code but with a frame-stepping mode enabled: instead of running in real-time, the cinematic advances one frame at a time, the canvas is captured via `canvas.toDataURL('image/png')`, and the frame is written to a temporary directory.

The frame capture rate is 30fps. For a 60-second cinematic, this produces 1,800 frames. After capture, ffmpeg assembles the frames into an MP4 with the H.264 codec. The TTS audio (already generated as MP3) is mixed in as the audio track using ffmpeg's audio overlay. The output is a 1920x1080 MP4 file at 30fps with AAC audio.

```bash
ffmpeg -framerate 30 -i frames/%04d.png -i narration.mp3 \
  -c:v libx264 -preset medium -crf 23 \
  -c:a aac -b:a 128k \
  -pix_fmt yuv420p \
  -movflags +faststart \
  output.mp4
```

The export takes approximately 2-5 minutes for a 60-second cinematic depending on scene complexity. The resulting file is typically 15-40MB. Once generated, the video is sent to Telegram as a video message via the Telegram Bot API's `sendVideo` method, and also stored at a shareable URL that auto-plays the cinematic in-browser (the live version, not the video file) for recipients who prefer the interactive experience.

The export can also generate a shorter preview (10 seconds, first and last waypoints only) for use as an OG video preview when the briefing URL is shared on social media or messaging platforms.

---

## Visual Language

### The Map Breathes

The map is alive. Even when no briefing is playing and no user is interacting, the map has movement, pulse, and flow. This ambient animation communicates that the system is active - data is flowing, agents are watching, the intelligence picture is continuously updating.

Pulse is the heartbeat of events. Every event in the ontology with geographic coordinates renders as a glowing point on the map. The glow pulses - brighter and larger, then dimmer and smaller, in a sinusoidal cycle. The pulse frequency and amplitude decay with the event's age. A fresh ACLED event that occurred in the last hour pulses rapidly at 1.0 Hz with full amplitude - the point expands and contracts visibly, demanding attention. Yesterday's event hums gently at 0.5 Hz with 60% amplitude - present but not urgent. Last week's event is a faint glow pulsing at 0.2 Hz with 20% amplitude - historical context, not breaking news. Events older than 30 days do not pulse at all but remain as static dim points at 10% opacity, creating a historical heat map of activity.

The pulse implementation uses a time-varying radius in the `ScatterplotLayer`. The radius function takes the current timestamp and the event's age to calculate the instantaneous radius:

```typescript
const pulseRadius = (baseRadius: number, ageMs: number, now: number): number => {
  const ageHours = ageMs / 3600000;
  const frequency = Math.max(0.1, 1.0 - ageHours / 168); // 1Hz fresh, 0.1Hz at 7 days
  const amplitude = Math.max(0.05, 0.3 * (1.0 - ageHours / 168));
  return baseRadius * (1 + Math.sin(now * frequency * Math.PI * 2 / 1000) * amplitude);
};
```

Color temperature is the atmosphere. As described in the Core Experience section, the entire color palette of the map shifts with the global threat level. But the color temperature also varies locally. Active conflict zones emanate warm colors (amber/red) in their immediate vicinity, while calm regions remain cool blue-grey. This local temperature variation is achieved with a `HeatmapLayer` that renders warm colors around recent high-severity events. The heatmap intensity is driven by event severity and recency:

```typescript
new HeatmapLayer({
  id: 'local-temperature',
  data: recentEvents.filter(e => e.severity >= 3),
  getPosition: d => [d.lon, d.lat],
  getWeight: d => {
    const ageHours = (Date.now() - d.timestamp) / 3600000;
    return d.severity * Math.max(0.1, 1.0 - ageHours / 72);
  },
  radiusPixels: 60,
  intensity: 0.3,
  threshold: 0.05,
  colorRange: [
    [255, 200, 100, 0],    // transparent yellow
    [255, 150, 50, 80],    // warm amber
    [255, 80, 30, 120],    // orange-red
    [255, 40, 20, 160]     // red
  ]
});
```

Flow gives the map directionality and movement even in quiet times. Flight tracks leave fading contrails - implemented as `TripsLayer` paths where each flight's historical positions over the last hour are rendered as a fading line. The trail head (current position) is bright white, and the trail fades to transparent over its length. The `trailLength` parameter is set to 30 seconds of travel at the current animation speed, creating visible contrails behind each aircraft.

Vessel tracks show directional flow with animated particles. Instead of simple dots for vessels, each vessel track renders as a dashed line with particles flowing along the direction of travel. This is achieved using a custom `PathLayer` with an animated `getDashArray` offset that creates the illusion of flowing particles along the path. The animation cycles the dash offset by 1 pixel per frame, creating a steady flow.

Arms transfer arcs pulse with flowing light. When the user hovers an entity and its relationship lines appear, the lines that represent arms supplies or funding have animated particles flowing along them from source to destination. This uses a custom deck.gl layer that extends `ArcLayer` with a time-varying color gradient - a bright spot travels from source to target over 2 seconds, loops, and repeats. The effect looks like light flowing along the arc.

Stillness is information. Calm regions are genuinely dark and still. There are no ambient effects, no particles, no glows in regions where nothing has happened. The Sahara, central Siberia, the open Pacific - these are dark, quiet voids on the map. The contrast between active zones and still zones is critical. It makes the active zones pop by providing visual silence around them. A user's eye is naturally drawn to movement and light, so by keeping inactive regions truly dark, the map communicates the geography of tension without any labels or legends.

### Fog of War

Areas where the ontology has poor coverage are fogged. This is one of the most important visual features because it turns a data quality metric into a visceral experience. Instead of a percentage number saying "coverage: 23% in Central Asia", the user sees actual fog rolling over Central Asia. Full intelligence coverage means clear terrain. Sparse coverage means thick fog. Blind spots are viscerally obvious.

The fog density at any geographic point is calculated from the ontology's object density in that region. The calculation works on a grid: the globe surface is divided into cells of approximately 2 degrees latitude by 2 degrees longitude (roughly 200km at the equator). For each cell, the system counts the number of ontology objects with coordinates within that cell, weighted by recency (objects updated in the last week count as 1.0, older objects as 0.5, objects with no recent data as 0.2). The count is then normalized against the expected density for that region type (urban areas are expected to have more objects than oceans, for example). The resulting value between 0.0 (no coverage) and 1.0 (full coverage) drives the fog opacity: 0.0 coverage means fog opacity 0.7 (thick fog), 1.0 coverage means fog opacity 0.0 (clear).

The fog itself is rendered as an animated noise texture applied to a semi-transparent polygon layer. The noise texture is generated using Simplex noise at multiple octaves to create a natural cloud-like appearance:

```typescript
function generateFogTexture(width: number, height: number): ImageData {
  const data = new ImageData(width, height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const nx = x / width * 4;
      const ny = y / height * 4;
      // Multi-octave simplex noise for cloud-like texture
      let noise = simplex2(nx, ny) * 0.5
        + simplex2(nx * 2, ny * 2) * 0.25
        + simplex2(nx * 4, ny * 4) * 0.125;
      noise = (noise + 1) / 2; // Normalize to 0-1
      const idx = (y * width + x) * 4;
      data.data[idx] = 180;     // R - light grey
      data.data[idx+1] = 190;   // G
      data.data[idx+2] = 200;   // B
      data.data[idx+3] = Math.floor(noise * 255); // A - noise-driven opacity
    }
  }
  return data;
}
```

The fog animates by slowly scrolling the noise texture coordinates over time (offset by 0.001 per frame), creating the effect of clouds rolling across the map. The fog layer is rendered using a deck.gl `BitmapLayer` for each fogged grid cell, with the bitmap being the noise texture and the opacity modulated by the coverage score.

The Sahel is foggy with 3 objects. Western Europe is crystal clear with hundreds. The contrast drives commission requests naturally: "Why is Central Asia fogged? Can we get coverage there?" This turns the fog of war from a cosmetic feature into a functional one - it makes intelligence gaps actionable.

### Unit Figurines

Military units are rendered as miniature figurines on their deployment locations. Not dots. Not circles. Figurines - small iconic representations that communicate type, faction, and importance at a glance, like the pieces on a strategy game board.

At the strategic zoom level (continental view, zoom 2-5), units render as small 2D sprites via deck.gl's `IconLayer`. Each sprite is a 32x32 pixel PNG showing the unit's silhouette in its faction color on a transparent background. The silhouette shapes are: infantry (soldier figure), armor (tank profile), naval vessel (ship profile varying by class), aircraft (jet profile), base (fortification icon), missile battery (launcher silhouette). The sprites always face the camera (billboard rendering).

At the regional zoom level (zoom 5-8), the sprites enlarge to 48x48 and gain a label (unit designation), a strength bar (a thin horizontal bar below the sprite showing filled vs. empty proportion), and a star rating (small star icons above the sprite indicating command level). These additional elements are rendered as HTML overlays positioned via deck.gl's `HTMLOverlay` or as additional `TextLayer` and `IconLayer` instances.

At the theater zoom level (zoom 8+), full unit markers replace the sprites. These are the Total War-style flag banners described in detail in the Unit Markers section below.

During cinematic briefings, figurines animate along movement paths as described in the cinematic section. The movement animation maintains the figurine's rendering style (sprite, label, strength bar) throughout the movement.

### Territory Control

Countries and regions are colored by faction control. This is rendered using deck.gl's `GeoJsonLayer` with country boundary polygons from Natural Earth data. Each polygon's fill color is determined by the `controls` link type in the ontology. If the ontology records "Russia controls Crimea", the Crimea polygon fills with the Russian faction color (red, 15% opacity). Disputed zones - regions where multiple factions have `controls` links - render with a crosshatch pattern. The crosshatch is achieved by overlaying two `PathLayer` instances with diagonal lines in each faction's color.

The Sahel shows junta vs. government zones. Gaza and the West Bank show their patchwork of control. Ukraine shows the evolving contact line. Each conflict's control map updates when ontology data changes - when a territorial change is detected (new `controls` link or existing link marked `valid_to`), the territory coloring animates. The old color washes out over 1 second and the new color washes in, creating a visible representation of territorial change.

### Convergence Rings

When multiple signal types overlap geographically, the system detects the convergence and renders concentric rings rippling outward from the overlap point. This makes cross-domain synthesis visible - when SIGINT sees military flights, the RF layer shows conflict events, and the thermal layer shows heat signatures, all in the same area, the convergence ring appears automatically.

The convergence detection algorithm runs on the client whenever layer data updates. It divides the visible viewport into a grid of cells (approximately 50km per cell) and counts the number of distinct data types present in each cell. A cell with only ACLED events scores 1. A cell with ACLED events and military flights scores 2. A cell with ACLED events, military flights, and thermal clusters scores 3. Any cell scoring 3 or higher triggers a convergence ring.

The ring animation is three concentric circles expanding from the convergence center. The first ring starts at radius 0 and expands to 200km over 2 seconds with `power2.out` easing, starting at opacity 0.4 and fading to 0. The second ring starts 0.3 seconds after the first with opacity 0.25. The third starts 0.6 seconds after the first with opacity 0.15. The ring color matches the current threat level accent (blue for normal, amber for elevated, red for critical).

The rings are rendered using deck.gl's `ScatterplotLayer` with `filled: false` and `stroked: true`, with animated radius and opacity values:

```typescript
function createConvergenceRings(center: [number, number]): ConvergenceRingData[] {
  return [0, 1, 2].map(i => ({
    center,
    startTime: Date.now() + i * 300,
    maxRadius: 200000, // 200km in meters
    duration: 2000,
    maxOpacity: 0.4 - i * 0.1
  }));
}

// In the render loop:
rings.forEach(ring => {
  const elapsed = Date.now() - ring.startTime;
  if (elapsed < 0 || elapsed > ring.duration) return;
  const progress = elapsed / ring.duration;
  const radius = ring.maxRadius * easeOutPower2(progress);
  const opacity = ring.maxOpacity * (1 - progress);
  // Render ring with current radius and opacity
});
```

Convergence rings repeat every 10 seconds as long as the convergence condition persists. They do not repeat if the data has not changed.

### Connection Lines on Hover

Hovering any entity on the map reveals its ontology relationships as glowing lines connecting to related entities. The lines appear over 0.3 seconds (fading in from transparent) and are colored by relationship type.

Red lines represent arms supply and adversarial relationships (link types: `arms`, `opposes`, `targets`). These are rendered with a pulsing glow effect - the line width oscillates between 1.5px and 2.5px at 0.5 Hz, suggesting tension and danger.

Amber lines represent alliance and cooperation (link types: `allied_with`, `member_of`, `mediates`). These are steady, warm, and slightly thicker (2px base width) to suggest stability.

Blue lines represent command hierarchy and military structure (link types: `commands`, `subsidiary_of`, `operates`). These are crisp, thin (1.5px), and have directional flow particles (small dots traveling along the line from commander to subordinate at 50px/second).

Gold lines represent economic relationships (link types: `funds`, `trades_with`, `sanctions`). These pulse slowly (0.3 Hz) and have medium thickness (1.8px).

White lines represent neutral relationships (link types: `borders`, `located_at`, `hosts`, `deployed_to`). These are thin (1px), static, and at 50% opacity.

All lines use `ArcLayer` for rendering, with `greatCircle: true` to draw geodesic arcs on the globe. The arc height is proportional to the distance between entities - nearby entities have flat arcs (height factor 0.1), distant entities have tall arcs (height factor 0.3). Directional flow particles (for command hierarchy lines) are implemented by overlaying a `ScatterplotLayer` with small dots (3px) whose positions are interpolated along the arc path and advance over time.

Line thickness scales with confidence. A relationship with confidence 1.0 renders at full thickness. Confidence 0.5 renders at 60% thickness. This makes well-established relationships visually prominent and tentative ones subtle.

Iran lights up like a spiderweb. With connections to Hezbollah, Hamas, Houthis, PMF, various proxies, sanctioning nations, and trade partners, hovering Iran creates a dense web of colored lines radiating outward. The visual density itself communicates Iran's centrality in the regional network.

### Entity Glow

Objects with more connections glow brighter. Network centrality is rendered as luminosity. The glow intensity of each entity's map marker is proportional to its degree centrality (total number of inbound and outbound links) in the ontology graph.

The calculation is straightforward: for each entity, count total links. Normalize against the maximum link count in the ontology. Apply as a glow intensity multiplier on the entity's marker. An entity with 1 link (isolated airbase) has glow intensity 0.1 - barely visible. An entity with 50 links (Iran, Russia, USA) has glow intensity 1.0 - a bright beacon on the map.

The glow effect is implemented using a `ScatterplotLayer` behind the main icon layer. Each entity gets a large, soft, semi-transparent circle with radius 3x the icon size and opacity equal to `0.05 + 0.15 * normalizedDegree`. The fill color matches the entity's faction color. The result is that heavily connected entities have visible auras around their markers, while isolated entities are just their icon with no ambient glow.

```typescript
new ScatterplotLayer({
  id: 'entity-glow',
  data: entities,
  getPosition: d => [d.lon, d.lat],
  getRadius: d => getIconSize(d) * 3,
  getFillColor: d => {
    const [r, g, b] = getFactionColor(d);
    const alpha = Math.floor(15 + 40 * (d.linkCount / maxLinkCount));
    return [r, g, b, alpha];
  },
  radiusMinPixels: 10,
  radiusMaxPixels: 80,
  parameters: { blend: true, blendFunc: [GL.SRC_ALPHA, GL.ONE] }
});
```

### Threat Ring Sonar

The 8 geofence watch zones (Strait of Hormuz, Ukraine contact line, Taiwan Strait, Suez Canal, Baltic approaches, Red Sea/Bab el-Mandeb, South China Sea, Kashmir LOC) render as subtle sonar rings on the map. Each watch zone's circle (defined by center + radius in the `watch_zones` table) renders as a thin dashed circle on the globe. When the zone is dormant (no recent alerts), the circle is barely visible - a thin white dashed line at 10% opacity. When an event fires inside the zone, the zone activates with sonar rings pulsing outward.

### Ghost Trails (Time Scrub)

A time slider at the bottom of the screen allows the user to scrub backwards through the last 30 days of data. Scrubbing backwards reveals where things were - flight paths that faded, vessel positions from last week, conflict events that resolved. Watch a situation develop over days. Play forward at speed to spot slow-moving patterns.

Ghost trails are the visual residue of historical positions. When the time scrub is active (not at "now"), entities that have moved since the scrub time show a ghosted trail from their historical position to their current position. The trail is rendered using `TripsLayer` with decreasing opacity toward the current-time end, creating a fading afterimage effect.

### Prediction Markers

The prediction ledger's 40 open forecasts render on the map as dashed circles at the predicted location. Each circle is translucent, with the border style and opacity reflecting the prediction's confidence score. A 90% confidence prediction renders as a nearly-solid dashed circle with 60% opacity. A 50% confidence prediction renders as a widely-spaced dash pattern with 30% opacity.

Inside the circle, a small text label shows the confidence percentage and a countdown to the prediction's review date. "72nd Mech Brigade escalation - 65% - 18 days". Markers solidify when confirmed, fade when wrong. The map shows what you THINK as well as what you KNOW.

### Gravity Wells

Conflicts warp the map subtly. More severe conflicts create deeper visual distortion. Active conflicts pull surrounding entities' labels toward them. Kashmir is a dimple. Ukraine is a crater. Visual weight of a crisis felt in how it distorts space.

The implementation uses a post-processing shader applied to the WebGL canvas:

```glsl
uniform vec2 conflictCenters[8];
uniform float conflictStrengths[8];
uniform int numConflicts;

varying vec2 vUv;

void main() {
  vec2 displaced = vUv;
  for (int i = 0; i < 8; i++) {
    if (i >= numConflicts) break;
    vec2 toConflict = conflictCenters[i] - vUv;
    float dist = length(toConflict);
    float pull = conflictStrengths[i] * 0.02 / (dist * dist + 0.01);
    displaced += normalize(toConflict) * min(pull, 0.005);
  }
  gl_FragColor = texture2D(sceneTexture, displaced);
}
```

The effect is deliberately subtle - maximum displacement of about 5 pixels. Toggleable in settings.

### Network Pulse

Click an entity and expand its relationships - connections pulse outward like a shockwave. First-hop lights up, then second, then third. Click Iran and watch the pulse reach Hezbollah, then Hamas, then Gaza, then the Red Sea. The ontology as a living nervous system.

The pulse is implemented by performing a breadth-first search from the clicked entity, with each hop's connections illuminated at a 300ms stagger.

---

## Montgomery - The Commander

### Portrait PiP

Bottom-left of the map. 120px square. Gilded frame (subtle, not gaudy). Shows Montgomery's avatar. When a briefing arrives, the portrait activates - subtle glow, image shifts. When TTS plays, the portrait "speaks." Click the portrait to open the briefing drawer.

Switch channels and the portrait changes to that agent's avatar. Each agent has a presence.

```css
.commander-portrait {
  position: fixed;
  bottom: 24px;
  left: 24px;
  width: 120px;
  height: 120px;
  border: 2px solid rgba(200, 170, 100, 0.4);
  border-radius: 4px;
  box-shadow: 0 0 15px rgba(200, 170, 100, 0.1), inset 0 0 10px rgba(200, 170, 100, 0.05);
  overflow: hidden;
  z-index: 100;
  cursor: pointer;
  transition: all 0.3s ease;
}

.commander-portrait.speaking {
  animation: speak-pulse 0.8s ease-in-out infinite;
}

@keyframes speak-pulse {
  0%, 100% { box-shadow: 0 0 15px rgba(200, 170, 100, 0.2); }
  50% { box-shadow: 0 0 30px rgba(200, 170, 100, 0.4), 0 0 60px rgba(200, 170, 100, 0.1); }
}
```

### Speaks Unprompted

Montgomery does not wait. When a significant event occurs (flash report, convergence detected, geofence breach), his portrait activates, alert sound plays, voice delivers the assessment: "Attention. OREF alert - three rocket launches from southern Lebanon. Adjusting the map." The map auto-pans to the event.

He is not a tool you use. He is a presence in the room.

### Chat Interface

Click any entity. Chat panel slides up from the bottom (35% height, semi-transparent). Montgomery responds with live analysis grounded in the ontology. Not canned text. Real inference.

"What happened here last month?" - queries timeline.
"Who commands this unit?" - traverses graph.
"Is this related to Hormuz?" - finds connections.
"Write me a brief on this." - generates SITREP, posts to reading room, pushes to channel.

---

## Game-Style HUD

### Top Bar

The top bar spans the full viewport width, 48px tall, with a semi-transparent dark background and a 1px bottom border in the accent color.

- "MERIDIAN EYE" logo (left) - letterspaced uppercase, subtle text-shadow
- Search bar (center) - 320px, dark input, monospace, searches ontology with autocomplete
- Alert level badge (right) - colored badge with threat level label
- Graph icon, settings gear (right) - 18px SVG icons

```css
.hud-topbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 48px;
  background: rgba(10, 10, 18, 0.85);
  border-bottom: 1px solid var(--accent);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  z-index: 200;
  backdrop-filter: blur(10px);
}
```

### Channel Tabs (below header)

Agent channels as compact pill tabs. Each: short name + colored alert dot (green/amber/red) + update indicator. Active tab has brighter border and filled background. Click to switch: globe rotates, layers change, portrait changes, briefing updates. Transition takes 1.5 seconds with GSAP.

### Bottom Bar (resource indicators)

Strategy game-style resource bar. Compact key-value pairs in monospace:
- Active channels: 8/10
- Alert level: ELEVATED
- Ontology: 6,322 objects
- Last update: 14 min ago
- Active missions: 3
- Coverage: 78% (inverse of fog)

Values update via API polling every 30 seconds. Changes flash briefly.

### Layer Toggles (ability bar style)

Compact toggle chips above the bottom bar. Only layers relevant to active channel. Each: hotkey letter (Q/W/E/R/T/Y), icon, name, count badge, active glow when on. Press hotkey or click to toggle.

### Action Buttons (context-sensitive)

When an entity is selected, action buttons appear near it:
- [Brief] - generate a SITREP about this entity
- [Track] - add to watchlist
- [Network] - show relationship graph
- [History] - show timeline
- [Commission] - request deeper analysis

Game-style buttons - 32px square, compact, icon-driven, hover tooltips.

---

## Entity Cards - Collectable Intelligence

Every ontology object has a card. Like a dossier card or trading card.

- **Front:** Portrait/flag/insignia, name, type badge, key stats (2-3 properties)
- **Back:** Full relationship web, brief count, last mentioned date
- **Quality rating:** Bronze (few properties, few links), Silver (well-linked, 5-15 properties), Gold (comprehensive with briefs, 15+ properties, 10+ links)

Cards slide in during cinematic briefings when entities are mentioned. In the entity gallery (/cards), you can browse your full collection. Ontology expansion literally levels up cards from bronze to gold - a "level up" animation plays when a card's tier increases.

Cards use CSS 3D transform for the flip animation (0.5s rotateY).

---

## Theater of Operations Mode

Click a conflict and press F to enter theater mode. The camera transitions to tactical view over 2 seconds:
- Terrain elevation becomes visible
- Unit positions render at higher fidelity
- Supply lines appear
- Frontline boundaries draw themselves
- Theater-specific HUD panel (300px, right side):
  - Force balance bar (tug-of-war between sides)
  - Days since escalation counter
  - Casualty ticker
  - Active units count
  - Threat trajectory arrow (escalating/stable/de-escalating)

Like zooming from the grand campaign map into a battle in Total War.

---

## Intelligence Missions

Commissions framed as missions. The commission portal becomes a mission board at `/missions`.

Each mission: objective (the intelligence question), assigned agent, status (BRIEFED / IN PROGRESS / COMPLETE), and the published brief as reward.

Active missions show on the map as objective markers - dashed circles around the area of interest with a slow rotation animation. When complete, the circle fills in and the brief "unlocks" with a card reveal animation.

---

## Split Screen Comparison

Drag two channels side by side. Map splits - left half one theater, right half another. Or split by time - left shows last week, right shows today. Same geography, different moment. Reveals what changed.

Technical implementation uses two separate deck.gl `Deck` instances in MapLibre 2D mode (globe.gl does not support split). A draggable divider bar allows adjusting the split ratio.

---

## The Daily Debrief

Every day at 07:00, an automated 60-second cinematic debrief:
1. Camera flies preprogrammed route across all active theaters
2. Montgomery narrates each stop (from channel briefing summaries)
3. New events animate on
4. Changed threat levels pulse
5. Ends at highest-alert theater
6. You're in control, ready to dig in

Exportable as video for Telegram.

---

## Sound Design (Optional, Toggleable)

Off by default. Toggle via gear icon. All audio via Howler.js with spatial stereo panning.

- **Baseline:** Low ambient hum (60Hz, synthesized). Pitch shifts with threat level.
- **ACLED event:** Low percussive tone. Deeper for higher fatalities.
- **OREF alert:** Sharp ascending ping (800Hz to 1200Hz, 200ms). Urgent.
- **Thermal cluster:** Deep vibration, distant thunder (40Hz, 1.5s).
- **GPS jamming:** Electronic warble (frequency-swept sine, 400-800Hz).
- **New brief:** Soft chime (523Hz bell tone, 0.5s with reverb).
- **Channel switch:** Subtle whoosh (filtered white noise, 0.3s).
- **Convergence ring:** Resonant harmonic - two tones merging (300Hz + 450Hz).
- **Cinematic briefing:** Subtle orchestral underscore. Low strings loop at 0.15 volume.

---

## Night Watch Mode

After midnight, the interface shifts gradually over 5 minutes:
- Map dims (dark overlay at 40% opacity)
- Only CRITICAL items glow through
- Channel tabs collapse to alert dots
- Assessment only shown if ELEVATED or CRITICAL
- Layer toggles hidden
- Almost entirely dark globe with occasional pulses

Flash report at 3am: dim overlay snaps off, map blooms red, OREF ping sounds, Montgomery speaks.

At dawn (06:00), interface gradually unfolds over 15 minutes. Morning debrief types in.

---

## Deep Intelligence - The Knowledge Engine

The database is not just a reference. It is institutional memory. When Montgomery talks about the Strait of Hormuz, he does not just say "IRGC-Navy active." He says "IRGC-Navy activity is up 40% from last month. The last time we saw this pattern was August 2024 before the tanker seizures. Three briefs from rf_gulf_iran_israel flagged this trend. The prediction ledger has an open forecast from 12 days ago assessing 65% likelihood of an escalatory incident within 30 days. A recent Chatham House analysis corroborates our assessment, noting similar historical parallels."

This depth comes from the convergence of four data systems: the ontology (objects, properties, and links), the brief archive (intelligence products with full text), the articles database (harvested think tank analysis), and the prediction and verification systems (accountability tracking). Every interaction on the map draws from all four.

### The Ontology as Foundation

The ontology in `intelligence.db` contains 6,322 objects across 9 types (person, organization, faction, country, location, platform, unit, event, document), described by 28,976 properties and connected by 7,218 links across 21 relationship types. Every object has a geographic position (where applicable), a temporal range (first_seen to last_seen), provenance tracking (which source created or updated each data point), and confidence scores on all relationships.

When the user clicks an entity on the map, the platform fetches the entity's full context: the object itself, all current properties, all relationships (inbound and outbound), linked objects up to 2 hops, all briefs that mention it, relevant articles from think tanks (via semantic search), the complete changelog, and involvement in predictions. This assembled context is what makes the chat interaction feel like talking to an analyst rather than querying a database.

### The Brief Archive

The briefs table contains all intelligence products generated by the Meridian Institute - weekly digests, daily battlefield assessments, flash reports, economic analyses, monthly deep-dives, and structured products (SITREPs, INTSUMs, WARNINGs). Each brief has full text content, source attribution, conflict linkage, entity linkage (via `brief_objects`), a product type classification, a verification score, and optional red team review text.

Briefs provide temporal narrative context. They show how the system's understanding of an entity evolved over time. The first brief to mention the 72nd Mechanized Brigade might be a detection report. The second might assess its operational readiness. The third might discuss its involvement in a specific operation. Reading these in sequence reveals the intelligence story.

### The Articles Database - Think Tank Harvesting

Articles from 17+ think tanks and analytical outlets flow into the database every 4 hours via the `competitor_scan.py` script and its extensions. These articles are not raw news - they are analysis written by domain experts at premier institutions. They serve three purposes: intelligence context (referenced in briefs and conversations), style calibration (setting the quality bar for Meridian's output), and gap detection (identifying topics Meridian has not covered).

The sources are divided into two tiers based on ingestion method.

RSS-accessible sources (ingested directly via feed parsing): International Crisis Group (ICG), Atlantic Council, Middle East Eye, Al-Monitor, Carnegie Endowment for International Peace, Stimson Center, War on the Rocks, Foreign Policy, Foreign Affairs, The Diplomat, ECFR, and Bellingcat.

Browser-scraped sources (ingested via headless browser): Chatham House, RAND Corporation, IISS, RUSI, CSIS, CFR, WINEP, and ISW. These sources block RSS access or do not publish feeds.

Articles are stored in the `articles` table in `intelligence.db`:

```sql
CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    author TEXT,
    published_at TIMESTAMP,
    summary TEXT,
    full_text TEXT,
    relevance_score REAL,
    topics TEXT,            -- JSON array
    regions TEXT,           -- JSON array
    entities_mentioned TEXT, -- JSON array
    synthesis_result TEXT,   -- CONFIRM, DIVERGE, GAP
    embedding BLOB,         -- 384-dim float32 vector
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

When a new article is ingested, `competitor_synthesis.py` classifies it against Meridian's existing coverage using Claude Haiku. CONFIRM means the article aligns with Meridian's assessment. DIVERGE means it contradicts or presents an alternative. GAP means it covers a topic Meridian has not addressed. GAPs automatically generate commissions.

The three purposes of the articles database: first, intelligence context - when Montgomery discusses a topic, the system finds relevant external analysis via semantic search and includes it in the prompt. Second, style calibration - Montgomery's prompts include instructions to write at the analytical quality level of these publications. Third, gap detection - the CONFIRM/DIVERGE/GAP classification creates a continuous feedback loop that drives coverage expansion.

Agent prompts reference the article database explicitly: "Before writing, check recent analysis from ICG and Carnegie on this topic. Note any alignment or divergence with their assessments."

### Semantic and Vector Search Across All Content

The system uses embeddings generated by `@xenova/transformers` (all-MiniLM-L6-v2, 384 dimensions) to enable semantic search across all textual content. This is how Montgomery finds "the most relevant Chatham House article from 2 weeks ago about exactly this topic."

```sql
CREATE TABLE vectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type TEXT NOT NULL,   -- article, brief, object_description, property
    content_id INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    vector BLOB NOT NULL,        -- 384-dim float32 (1536 bytes)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(content_type, content_id)
);
```

Content that gets embedded: all article summaries and full texts, all brief content, all ontology object descriptions, and all descriptive properties longer than 50 characters.

Semantic search computes cosine similarity between the query embedding and all stored vectors:

```python
def semantic_search(query_vector: np.ndarray, content_types: list[str], top_k: int = 10) -> list:
    db = sqlite3.connect(intelligence_db_path)
    cursor = db.execute(
        "SELECT id, content_type, content_id, vector FROM vectors WHERE content_type IN ({})".format(
            ','.join('?' * len(content_types))
        ), content_types
    )
    results = []
    for row_id, content_type, content_id, vector_blob in cursor:
        stored_vector = np.frombuffer(vector_blob, dtype=np.float32)
        similarity = np.dot(query_vector, stored_vector) / (
            np.linalg.norm(query_vector) * np.linalg.norm(stored_vector)
        )
        results.append((similarity, content_type, content_id))
    results.sort(reverse=True)
    return results[:top_k]
```

For approximately 7,000-8,000 embeddings, each search takes approximately 50-100ms in Python - fast enough for interactive use.

### Prediction Tracking and Accountability

The prediction ledger creates accountability. 40 predictions tracked with a 30-day auto-review cycle. On the map, predictions render as dashed circles. In conversations, Montgomery references them: "We have an open prediction from 12 days ago assessing 65% likelihood of an escalatory incident in the Strait of Hormuz within 30 days. So far, today's IRGC sortie is consistent with the predicted pattern."

The accuracy dashboard at `/accuracy` shows per-agent, per-domain, per-conflict accuracy rates. Over time, this data enables confidence calibration.

### Verification Scores and Trust

The multi-source verification pipeline assigns corroboration scores to key claims. A claim corroborated by 3+ independent sources receives a high verification score. On the map, high-confidence data glows brighter. Relationship lines with high confidence are thicker. Prediction markers with high verification scores are more opaque. The entire visual language communicates not just what is known, but how well it is known.

### How the Brief Generation Pipeline Uses All of This

When an agent produces a brief, the generation pipeline draws from every data source in sequence:

1. **Fetch WorldMonitor data** - latest from relevant endpoints (flights, ACLED, thermal, AIS, GPS jamming, OREF, economic)
2. **Query the ontology** - all objects relevant to the brief's topic, their properties, relationships, and recent changes
3. **Search for relevant articles** - semantic search across the articles database using the brief's topic as the query. Top 5 most relevant think tank articles included.
4. **Retrieve relevant prior briefs** - last 5 from the same domain plus any with high semantic similarity to the current topic
5. **Check the prediction ledger** - any open predictions related to the brief's topic
6. **Generate with full context** - all of the above assembled into a structured prompt
7. **Post-processing** - entity extraction, relationship extraction, verification scoring, optional red team review
8. **Publication** - write to intelligence.db, sync to Upstash Redis, push to Telegram, generate cinematic waypoints

This pipeline is what makes Meridian's output different from news aggregation. Every brief is informed by the full depth of the knowledge graph, calibrated against external expert analysis, and accountable through prediction tracking.

---

## 3D Assets - Not Dots on a Map

Every entity type has a custom visual representation. The system uses progressive level-of-detail: at strategic zoom, entities are simple 2D sprites; at regional zoom, they gain labels and metadata; at theater zoom, they become detailed 3D models.

### Asset Types - Full Inventory

**Naval vessels:**
- Aircraft carrier: 500 polygons, flat-top flight deck silhouette, 1.2 units long, faction-colored hull
- Destroyer/frigate: 300 polygons, angular bow profile, 0.8 units long
- Submarine: 200 polygons, cigar shape with conning tower, partial transparency below waterline
- Commercial vessel: 300 polygons (container) or 200 polygons (tanker), neutral grey

**Aircraft:**
- Fighter jet: 400 polygons, swept-wing profile, faction roundel
- Bomber: 500 polygons, wider wings, bulkier fuselage
- Transport: 400 polygons, high-wing, slab-sided
- Drone/UAV: 200-300 polygons (distinct shapes per type: Bayraktar high-aspect-ratio, Shahed delta wing)
- Helicopter: 300 polygons plus flat rotor disc
- Aircraft on patrol draw dotted predicted-path lines ahead of them

**Ground forces:**
- Infantry: 400 polygons total (3-5 figure silhouettes in V formation), size scales with strength
- Armor: 500 polygons (2-3 tank silhouettes clustered)
- Artillery: 300 polygons (2 howitzers in firing position)
- Special forces: 200 polygon stylized dagger emblem
- Missile battery: 400 polygons (TEL with raised missiles)

**Bases and facilities:**
- Military base: 400 polygons (building cluster with wall and flag pole)
- Naval base: 500 polygons (pier with crane silhouettes)
- Air base: 400 polygons (runway strip with hangar)
- Nuclear facility: 300 polygons (cooling tower hyperbolic curve)
- Embassy: 200 polygons (rectangular building with flag)
- Chokepoint: 100 polygons each (4 nautical buoys)
- Pipeline: PathLayer line with flow particles
- Undersea cable: dashed PathLayer on ocean floor

**Leaders and persons:**
- Head of state: 40x40 portrait pin with country flag, renders at zoom 8+
- Military commander: pin with rank insignia in faction color
- Intelligence chief: pin with agency seal, renders at zoom 10+

### Level of Detail (LOD) System

- **LOD 0** (zoom 1-4): Clustering active, 16-24px sprites, no labels, max 200 markers
- **LOD 1** (zoom 4-7): Individual markers, 24-48px sprites with labels and strength bars, max 500 markers
- **LOD 2** (zoom 7-10): Detailed sprites, key entities transition to 3D models via crossfade
- **LOD 3** (zoom 10+): All entities as 3D models, person pins appear, building-level detail

### Instanced Rendering for Performance

Three.js `InstancedMesh` batches entities of the same type into single draw calls. Faction colors applied via instance color tinting. Frustum culling handled automatically. Visibility budget of 500 entities maximum at any zoom level - least important culled when budget exceeded.

Strength bars and star ratings rendered as HTML overlays for crisp rendering at all zoom levels.

---

## Game Interaction Layer

Approximately 800 lines of TypeScript that sits between ontology data and the rendering stack. Converts raw intelligence objects into renderable game entities, manages the camera, and provides the game-style UI overlay.

### Unit Markers (The Total War Flags)

Every military entity gets a flag-style marker at LOD 1+:

```
    [*****]          <- Star rating (command hierarchy depth)
    |     |
    |  US |          <- Faction color fill, abbreviated name
    | NAVY|
    |     |
    [|||||||||  ]    <- Strength bar (filled portion)
    |     |
    [carrier icon]   <- Silhouette by unit type
```

**Strength calculation by type:**
- Fleet/CSG: vessels in group / expected complement (CSG-12: 9/11 = 82%)
- Army unit: personnel / authorized_strength (fallback: property_count / 10)
- Air wing: aircraft_count / wing capacity

**Star calculation from hierarchy depth:**
- 5 stars: COCOM/national command (depth 0 from top)
- 4 stars: Corps/Fleet (depth 1)
- 3 stars: Division/CSG (depth 2)
- 2 stars: Brigade/squadron (depth 3)
- 1 star: Battalion/ship (depth 4+)

**Faction colors:**
- Blue [70,130,230]: NATO/allied
- Red [220,60,50]: Russia/Russian-aligned
- Green [40,180,80]: China/PLA
- Gold [220,180,60]: Neutral/non-aligned
- Orange [230,140,40]: Non-state armed groups
- Purple [140,100,200]: UN/international

**Hover tooltip (game panel):**
```
CSG-12 - CARRIER STRIKE GROUP 12
USS Gerald Ford (CVN-78)
****  RADM Erik Eslich, USN
--------------------------------------
LOCATION    Eastern Mediterranean
STATUS      Deployed
STRENGTH    ||||||||--  82% (9/11 vessels)
AIR WING    CVW-8 | 74 aircraft
LAST INTEL  2h ago
--------------------------------------
[View Composition] [Track] [Brief]
```

Dark panel, gold border, faction-colored header stripe, monospace text at 11px. Click opens composition panel from right (350px) showing every subordinate unit.

### Time Control (Game-Style Slider)

```
[|<]  [<]  [||]  [>]  [>|]     [===========|====] 27 Mar 2026
 rew  slow  pause play  fast     ^^^^ scrub handle
```

Transport buttons: 28px square. Rewind (jump -24h), Slow (10x), Pause (default), Play (real-time), Fast (60x). Custom slider: 400px wide, 6px tall, 14px circular handle. Maps to 30-day range.

### Settings (Game Menu Style)

Full-screen overlay, dark panel (600px wide, centered), categories (DISPLAY, AUDIO, BRIEFINGS, CAMERA, DATA) with custom sliders (200px track, accent-colored fill) and game-style on/off toggles (36x18px rounded rectangles). [APPLY] and [DEFAULTS] buttons.

### Keyboard Shortcuts

```
WASD            Pan camera
Scroll          Zoom
Right-drag      Rotate/tilt
Space           Play/pause briefing
Escape          Close panel / exit theater
Tab             Cycle channels
1-9             Jump to channel by number
Q/W/E/R/T/Y    Toggle layers
F               Enter/exit theater mode
G               Toggle globe/flat
M               Toggle mission board
C               Card gallery
/               Focus search
B               Play latest briefing
N               Night watch toggle
P               Toggle prediction markers
H               Help overlay
```

---

## Additional Features

### Intelligence Radar Sweep

Rotating radar sweep line on the globe originating from the user's configured home location. Completes one rotation every 30 seconds. Recent events flash bright as the sweep passes them (classic radar "blip"). Sweep speed increases during active data polls.

Rendered as a PolygonLayer forming a narrow wedge (5 degrees wide) with gradient opacity.

### Diplomatic Weather

Geopolitical climate as literal weather. Stormy clouds (Three.js particle system) over conflict zones. Lightning flashes for flash events. Cold fronts (wavy PathLayer) for sanctions. Clear skies for stable regions.

### Red Lines

Montgomery can define threshold conditions that render as literal red lines on the map. The line pulses as activity approaches. Turns solid and fully opaque if breached.

### Whisper Network

Multi-source intelligence renders as converging whisper lines on verified entities. 5-source entity has dense whispers. Single-source has one faint line. Verification quality made visible.

### The Situation Room

Ctrl+Shift+S toggles from globe to multi-panel operations center: 4 mini-maps (theater views), briefing feed, entity ticker, alert log, mission status. Like walking into a command center.

### Asset Tracking Watchlist

Tag specific entities for permanent highlights, movement trails, and automatic alerts on status change. Stored in localStorage and synced to platform API.

### Butterfly Effect Chains

After a major event, visualize the cascade: triggering event pulses, first-order consequences animate outward at 1s, second-order at 2s. Each consequence derived from ontology links.

### Dead Drops

Agents can geolocate raw intelligence notes as small pins. Clusters of dead drops signal emerging importance before formal analysis catches up.

### Historical Overlay Ghosts

Toggle to see ghost images from past moments. The 2014 Crimea map ghosted over today's. Pre-October 7 Gaza overlaid on current. Rendered via duplicated entity layers at 20% opacity with desaturated colors and `mix-blend-mode: screen`.

### Threat Constellations

At max zoom-out, connect related threats into constellation lines. "Iran axis" constellation: Tehran-Hezbollah-Hamas-Houthis-PMF-IRGC. "Arctic race": Northern Fleet-NATO Nordic-Svalbard. Dissolve as you zoom in past zoom 3.

---

## Pages

### / (Home)
The globe. Orbital descent entry. Montgomery's channel. Full game experience.

### /channel/:name
Same globe, different channel active. URL-shareable.

### /meridian (Reading Room)
Full-page overlay (globe dims behind). Published intelligence products grid. Filter by product type, agent, conflict, date, verification score. Each brief has a "Play Cinematic" button.

### /meridian/brief/:id
Full brief with cinematic playback option. Markdown render. Entity cards inline in the right margin. Listen button for TTS audio. View on Map button.

### /graph
Force-directed knowledge graph (d3-force). Full screen. Nodes by type, edges by relationship. Search + filter. Click to expand. "View on map" for geolocated entities.

### /graph/entity/:id
Entity dossier. Properties table, relationships table, timeline (changelog), briefs, map location.

### /cards
Entity card gallery. Filter by type, quality tier, conflict. Coverage gap highlighting.

### /timeline/:conflict
Campaign timeline. Turn-style markers colored by assessment trajectory. Click for detail.

### /missions
Mission board. Active commissions as objectives. Status tracking. Brief rewards.

### /health
Source health grid. 39 sources. Green/amber/red per source with 7-day sparkline.

### /accuracy
Prediction ledger. Outcome tracking. Per-agent accuracy. Calibration chart.

### /metrics
Agent performance scorecards. 7 categories per agent. Game-style stat cards.

---

## What to Strip from WorldMonitor

Remove: Bloomberg TV, webcams, Pro banner, Discord, variant switcher, GitHub badge, author credits, blog, download buttons, Clerk auth, analytics, stock/crypto/finance panels, consumer price panels, world clock, weather data, sports data, tourism data, newsletter signup, social links, all non-intelligence panels.

Keep: globe.gl 3D engine, deck.gl layers, MapLibre, data layer system, country click, CORS/API infrastructure, dark theme, Vercel API route framework, Upstash Redis integration.

---

## Technical Stack

- **globe.gl** - 3D globe with free camera. Custom dark basemap, custom camera controller with WASD and momentum.
- **deck.gl** - 13 layer types in the render stack: GeoJsonLayer, HeatmapLayer, BitmapLayer, ScatterplotLayer (x3 for glow/hotspots/rings), TripsLayer, ArcLayer (x2 for relationships/arms), PathLayer, IconLayer, TextLayer.
- **Three.js** - Post-processing (UnrealBloomPass for glow, ShaderPass for color grading), 3D models (InstancedMesh), cloud layer, weather particle systems. Accessed through globe.gl's scene.
- **GSAP** - All non-WebGL animation: camera transitions, UI panel animations, letterbox bars, card reveals, cinematic timeline orchestration. Chosen over CSS animations for precise sequencing and per-frame callbacks.
- **Howler.js** - Spatial audio: ambient sound, event pings, cinematic underscore. Web Audio API stereo panning based on screen position.
- **Supercluster** - Marker clustering at low zoom. Already in codebase.
- **d3-force** - Force-directed graph layout for the `/graph` page.
- **ElevenLabs API** - TTS for Montgomery's voice. Called from Vercel Edge Function.
- **Claude API** - Chat responses on entity click. Vercel Edge Function proxy with streaming SSE.

---

## Implementation Phases

### Phase 1: Strip + Globe First (3 days)
1. Remove all WorldMonitor consumer panels
2. Globe.gl as default view with dark basemap
3. Free camera controls (orbit, zoom, tilt, WASD)
4. Floating HUD: header, channel tabs, resource bar
5. Montgomery portrait PiP (static)
6. Orbital descent entry animation (GSAP timeline + cloud layer)
7. Basic layer toggles
8. Deploy clean

### Phase 2: Units + Interactions (3 days)
9. Entity data pipeline (ontology API + Game Entity Manager)
10. Unit figurines on map (IconLayer with sprite atlas and faction colors)
11. Entity click -> chat panel slides up with Claude API integration
12. Connection lines on hover (ArcLayer with relationship colors)
13. Territory control coloring (GeoJsonLayer with ontology controls links)
14. Country/entity click -> ontology profile
15. Action buttons on selected entity
16. Channel switching drives camera + layers + portrait

### Phase 3: Living Map Effects (3 days)
17. Hotspot pulse animation (time-varying ScatterplotLayer)
18. Color temperature shift with threat level (CSS filter + GSAP)
19. Local temperature variation (HeatmapLayer)
20. Flight contrails (TripsLayer)
21. Convergence ring detection and rendering
22. Entity glow (ScatterplotLayer with additive blending)
23. Threat ring sonar around watch zones
24. Fog of war (noise texture + BitmapLayer + coverage density)
25. Gravity wells (post-processing displacement shader)

### Phase 4: Cinematic Briefings (4 days)
26. Letterbox bar animation (CSS transform)
27. Camera waypoint sequencing (GSAP timeline with Bezier curves)
28. Unit movement animation along paths (TripsLayer trails)
29. Entity card slide-in synced to narration (word count timing)
30. Connection line draw-on during relationship mentions (progress ArcLayer)
31. TTS audio playback synced to camera holds (ElevenLabs API)
32. Convergence ring triggers during narration
33. Auto-generate waypoints from brief text + ontology geocoding
34. Flash report snap-to cinematic
35. Morning debrief auto-play

### Phase 5: Game Features (3 days)
36. Entity cards (front/back, quality tiers, flip animation)
37. Card gallery page (/cards) with filtering
38. Intelligence missions (commission -> mission board)
39. Mission markers on map (rotating dashed circles)
40. Theater of operations mode (tactical HUD + force balance)
41. Split screen comparison (dual Deck instances, MapLibre 2D)
42. Ghost trails (time scrub with TripsLayer historical paths)
43. Prediction markers (dashed ScatterplotLayer circles)

### Phase 6: Reading Room + Graph (2 days)
44. /meridian reading room with cinematic play buttons
45. /meridian/brief/:id with inline entity cards
46. /graph force-directed visualization (d3-force)
47. /graph/entity/:id dossier page
48. Network pulse animation on graph
49. Ontology search autocomplete wired to graph

### Phase 7: Polish + Export (3 days)
50. Sound design system (Howler.js, all audio assets, spatial positioning)
51. Night watch mode (time-based CSS overlay, flash report override, dawn unfold)
52. Briefing video export (Puppeteer frame capture -> ffmpeg -> MP4)
53. Telegram video delivery
54. OG images for link previews (Vercel OG / satori)
55. Daily debrief automation
56. Montgomery speaks unprompted on events
57. Keyboard shortcuts (WASD, space, esc, tab, layer hotkeys, help overlay)
58. Performance optimization (clustering, LOD, frustum culling budget, lazy load)
59. Mobile: touch controls, simplified HUD

### Total Estimated Effort

- 21 working days (approximately 4 weeks)
- Approximately 110 new files
- Approximately 4,000-6,000 lines of new TypeScript/CSS
- 3 new npm dependencies: gsap, howler, d3-force
- All other dependencies already in WorldMonitor codebase

# War Room Panorama - Design Spec

**Date:** 2026-03-30
**Status:** Approved
**Project:** Meridian Eye / WorldMonitor (`~/.atrophy/services/worldmonitor/`)

## Summary

Replace the black/dark void visible above the horizon on the 2D DeckGL/MapLibre map with an equirectangular panorama of a general's command tent interior with a mahogany desk. When the map is pitched (tilted), the tent interior is visible above the map tiles. The panorama tracks the camera bearing and pitch via existing CSS custom properties.

## Current State

- `DeckGLMap.ts` uses MapLibre GL + DeckGL overlay for the 2D map
- Map has `maxPitch: 60` - tilting reveals the void above the horizon
- Background is forced to `#3A2418` (dark mahogany) via:
  - `basemapEl.style.backgroundColor = '#3A2418'` (line 755)
  - MapLibre background layer paint: `'background-color', '#3A2418'` (line 572)
  - WebGL clear color override every frame: `gl.clearColor(58/255, 36/255, 24/255, 1)` (line 577)
- `war-room.css` has a `::before` pseudo-element on `.meridian-map-viewport` with CSS gradient tent approximation, but it's invisible behind the opaque canvas
- `DeckGLMap.ts` already pushes `--room-bearing` and `--room-pitch` CSS vars on every camera move (lines 942-947)

## Design

### Approach

1. Make the MapLibre canvas transparent above the map tiles so the CSS backdrop shows through
2. Replace the CSS gradient stack in `war-room.css::before` with an equirectangular panorama image
3. The existing `--room-bearing`/`--room-pitch` transform keeps the panorama tracking the camera

### Step 1: Transparent Canvas Above Horizon

Remove the opaque overrides in `DeckGLMap.ts`:

- Remove `basemapEl.style.backgroundColor = '#3A2418'` (or set to transparent)
- Remove the `background-color` paint property override on the MapLibre background layer (or set to transparent)
- Remove the `gl.clearColor` per-frame override (or set alpha to 0)

Then the area above the map tiles (the void) becomes transparent, revealing whatever is behind the canvas - which is the `::before` pseudo-element from `war-room.css`.

**Risk:** The map tiles themselves must remain opaque. Only the area with no tiles (above horizon, beyond world bounds) should be transparent. MapLibre supports this - when the background layer is transparent and there are no tiles to render, the canvas is clear.

### Step 2: Panorama Image in war-room.css

Replace the gradient stack in `.meridian-map-viewport::before` with the panorama image:

```css
.meridian-map-viewport::before {
  content: '';
  position: absolute;
  inset: -20%; /* oversize for panning */
  z-index: -1;
  background: url('/textures/war-room-panorama.jpg') center / cover no-repeat;
  transform: translate(
    calc(var(--room-bearing) * 0.3),
    calc((var(--room-pitch) - 50%) * -0.2)
  );
  transition: transform 0.1s linear;
}
```

The `inset: -20%` oversize ensures the image covers the viewport even when transformed by the bearing/pitch offsets.

### Step 3: Camera Sync (already exists)

`DeckGLMap.ts` lines 939-948 already update `--room-bearing` and `--room-pitch` on every `move` event. No changes needed.

### Asset

One equirectangular (or wide-angle) panorama image stored at `public/textures/war-room-panorama.jpg`.

**Subject:** Interior of a military general's command tent. Mahogany campaign desk prominent. Canvas tent walls. Oil lanterns with warm amber lighting. Campaign maps pinned to tent walls. Brass instruments, leather-bound books.

**Generation:** AI image tool (Blockade Labs / Skybox AI for true equirectangular, or Midjourney/DALL-E for wide-angle). Target resolution 4096x2048 or higher. JPEG, ~2-4MB.

**Tone:** Dark, warm, atmospheric. Rich browns and ambers. Should not compete visually with the map data layers - the tent is backdrop, not the focus.

### Performance

- Single image load on page init (~2-4MB JPEG, cacheable)
- CSS transform on `::before` per frame - negligible (already happening with gradients)
- No JavaScript overhead beyond what already exists

## Files Changed

| File | Change |
|------|--------|
| `src/map/DeckGLMap.ts` | Remove opaque background overrides (3 locations) |
| `src/styles/map/war-room.css` | Replace gradient stack with panorama image |
| `public/textures/war-room-panorama.jpg` | New asset - panorama image |

## Edge Cases

| Case | Behavior |
|------|----------|
| Image fails to load | Falls back to transparent void (or keep `#3A2418` as CSS fallback behind the image) |
| Low pitch (map nearly flat) | Panorama barely visible - just a sliver above the horizon. This is fine. |
| High pitch (60 degrees) | Large portion of tent visible above the map. The primary use case. |
| Bearing rotation | Panorama shifts horizontally via `--room-bearing`, parallax effect |
| Fallback basemap style | Same transparent approach applies to the fallback map init path (line 780+) |

## Non-goals

- No changes to the globe view (GlobeMap.ts) in this spec
- No changes to map tiles, data layers, or DeckGL overlays
- No changes to orbit/pan/zoom controls
- No procedural 3D tent geometry - single panorama image only
- No interactive elements in the tent scene

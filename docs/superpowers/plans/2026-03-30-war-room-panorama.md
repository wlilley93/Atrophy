# War Room Panorama Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the opaque dark void above the 2D map horizon with an equirectangular panorama of a general's command tent interior.

**Architecture:** Make the MapLibre canvas transparent where no tiles exist (above horizon), then place a panorama image behind it via the existing `war-room.css` `::before` pseudo-element. The existing `--room-bearing`/`--room-pitch` CSS variable sync keeps the panorama tracking the camera.

**Tech Stack:** MapLibre GL, DeckGL, CSS, equirectangular panorama image (AI-generated)

**Spec:** `docs/superpowers/specs/2026-03-30-war-room-panorama-design.md`

**Working directory:** `~/.atrophy/services/worldmonitor/`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/map/DeckGLMap.ts` | Modify | Remove 3 opaque background overrides (primary + fallback paths) |
| `src/styles/map/war-room.css` | Modify | Replace CSS gradient stack with panorama image |
| `public/textures/war-room-panorama.jpg` | Create | Equirectangular panorama asset |

---

### Task 1: Generate the panorama asset

**Files:**
- Create: `public/textures/war-room-panorama.jpg`

This task is manual - it requires an external AI image generation tool.

- [ ] **Step 1: Generate the equirectangular panorama**

Use Blockade Labs (https://skybox.blockadelabs.com/) or similar tool. Prompt:

```
Interior of a military general's command tent at night. Large mahogany campaign desk in the center.
Canvas tent walls with warm amber oil lantern lighting. Campaign maps pinned to tent fabric walls.
Brass instruments, leather-bound books, wooden map stands. Dark, atmospheric, rich browns and ambers.
Military command post aesthetic. Low ambient light.
```

Settings: Equirectangular output, highest available resolution (4096x2048 minimum).

- [ ] **Step 2: Save to public/textures/**

Save as `public/textures/war-room-panorama.jpg`. Target file size 2-4MB. If larger, compress with quality 85.

- [ ] **Step 3: Verify the image**

Open the image and confirm:
- It's equirectangular (2:1 aspect ratio, wraps seamlessly left-to-right)
- Dark/warm tone that won't overpower map data
- Tent interior with mahogany desk visible

---

### Task 2: Make MapLibre canvas transparent above horizon

**Files:**
- Modify: `src/map/DeckGLMap.ts:570-578` (primary init path)
- Modify: `src/map/DeckGLMap.ts:795-801` (fallback init path)

- [ ] **Step 1: Remove opaque background in primary init path**

In `src/map/DeckGLMap.ts`, find the primary `on('load')` handler (around line 567). Replace the background overrides:

```typescript
// BEFORE (lines 570-578):
      // Force warm desk color in the 3D scene AND the WebGL clear color
      if (this.maplibreMap?.getLayer('background')) {
        this.maplibreMap.setPaintProperty('background', 'background-color', '#3A2418');
      }
      // Override WebGL clear color every frame (MapLibre resets it)
      this.maplibreMap?.on('render', () => {
        const gl = this.maplibreMap?.getCanvas()?.getContext('webgl2') || this.maplibreMap?.getCanvas()?.getContext('webgl');
        if (gl) gl.clearColor(58/255, 36/255, 24/255, 1); // #3A2418
      });

// AFTER:
      // Make above-horizon void transparent so war-room panorama shows through
      if (this.maplibreMap?.getLayer('background')) {
        this.maplibreMap.setPaintProperty('background', 'background-color', 'rgba(0,0,0,0)');
      }
      this.maplibreMap?.on('render', () => {
        const gl = this.maplibreMap?.getCanvas()?.getContext('webgl2') || this.maplibreMap?.getCanvas()?.getContext('webgl');
        if (gl) gl.clearColor(0, 0, 0, 0);
      });
```

- [ ] **Step 2: Remove opaque background in fallback init path**

In `src/map/DeckGLMap.ts`, find the fallback `on('load')` handler (around line 792). Apply the same change:

```typescript
// BEFORE (lines 795-801):
        if (this.maplibreMap?.getLayer('background')) {
          this.maplibreMap.setPaintProperty('background', 'background-color', '#3A2418');
        }
        this.maplibreMap?.on('render', () => {
          const gl = this.maplibreMap?.getCanvas()?.getContext('webgl2') || this.maplibreMap?.getCanvas()?.getContext('webgl');
          if (gl) gl.clearColor(58/255, 36/255, 24/255, 1);
        });

// AFTER:
        if (this.maplibreMap?.getLayer('background')) {
          this.maplibreMap.setPaintProperty('background', 'background-color', 'rgba(0,0,0,0)');
        }
        this.maplibreMap?.on('render', () => {
          const gl = this.maplibreMap?.getCanvas()?.getContext('webgl2') || this.maplibreMap?.getCanvas()?.getContext('webgl');
          if (gl) gl.clearColor(0, 0, 0, 0);
        });
```

- [ ] **Step 3: Update container background**

Find the container background color set before map init (around line 755):

```typescript
// BEFORE:
    basemapEl.style.backgroundColor = '#3A2418';

// AFTER:
    basemapEl.style.backgroundColor = 'transparent';
```

- [ ] **Step 4: Verify transparency**

Run: `npm run dev`

Tilt the map (hold right-click and drag up to increase pitch). The void above the horizon should now show whatever is behind the canvas - which at this point will be the existing CSS gradient tent from `war-room.css` (dark browns, faint lamp glows). If you see the gradients, transparency is working.

- [ ] **Step 5: Commit**

```bash
git add src/map/DeckGLMap.ts
git commit -m "feat: make map canvas transparent above horizon for war-room panorama"
```

---

### Task 3: Replace CSS gradients with panorama image

**Files:**
- Modify: `src/styles/map/war-room.css`

- [ ] **Step 1: Replace the gradient stack with panorama image**

Replace the entire contents of `src/styles/map/war-room.css`:

```css
/* War room panoramic background - responds to map camera */
.meridian-map-viewport {
  --room-bearing: 0deg;
  --room-pitch: 50%;
}

.meridian-map-viewport::before {
  content: '';
  position: absolute;
  inset: -20%; /* oversize for panning */
  z-index: -1;
  background:
    /* Panorama image */
    url('/textures/war-room-panorama.jpg') center / cover no-repeat,
    /* Fallback if image fails to load */
    radial-gradient(ellipse at 50% 60%, #2A1A0E 0%, #1A1008 40%, #0A0604 100%);
  /* Pan with map bearing, tilt with pitch */
  transform: translate(
    calc(var(--room-bearing) * 0.3),
    calc((var(--room-pitch) - 50%) * -0.2)
  );
  transition: transform 0.1s linear;
}
```

The fallback gradient (last line of the `background` shorthand) ensures a dark warm tone if the image fails to load.

- [ ] **Step 2: Verify the panorama renders**

Run: `npm run dev`

1. Load the 2D map (not globe mode)
2. Tilt the map by holding right-click and dragging up
3. Above the horizon, you should see the tent panorama instead of black/brown
4. Pan the map left/right (bearing change) - the panorama should shift subtly
5. Increase/decrease pitch - the panorama should shift vertically

- [ ] **Step 3: Check low-pitch state**

At low pitch (map nearly flat), the panorama should be barely visible - just a thin sliver above the horizon. Confirm it doesn't bleed into the map area or cause visual artifacts.

- [ ] **Step 4: Commit**

```bash
git add src/styles/map/war-room.css
git commit -m "feat: replace CSS gradient war room with panorama image"
```

---

### Task 4: Visual tuning

**Files:**
- Modify: `src/styles/map/war-room.css` (if needed)
- Modify: `src/map/DeckGLMap.ts` (if needed)

- [ ] **Step 1: Evaluate parallax intensity**

With the panorama visible, test whether the parallax multipliers feel right:
- `var(--room-bearing) * 0.3` controls horizontal shift with bearing
- `(var(--room-pitch) - 50%) * -0.2` controls vertical shift with pitch

If the panorama moves too much or too little relative to the map, adjust these multipliers in `war-room.css`. The current values were tuned for the CSS gradients and may need different values for a detailed image.

- [ ] **Step 2: Evaluate image brightness**

If the panorama competes visually with map data (markers, labels, lines), add an opacity or brightness filter:

```css
.meridian-map-viewport::before {
  /* ... existing properties ... */
  filter: brightness(0.6); /* darken if needed */
}
```

Only add this if the panorama is too bright. Try without it first.

- [ ] **Step 3: Check edge coverage**

Pan and rotate to extremes. The `inset: -20%` oversize should prevent the panorama from showing its edges during transforms. If edges are visible at extreme bearings, increase to `inset: -30%` or `-40%`.

- [ ] **Step 4: Commit if any tuning was needed**

```bash
git add src/styles/map/war-room.css src/map/DeckGLMap.ts
git commit -m "fix: tune war-room panorama parallax and brightness"
```

---

### Task 5: Final verification and cleanup

- [ ] **Step 1: Test both map init paths**

1. Load the site normally (primary basemap) - verify panorama works
2. If possible, trigger the fallback path (block the primary tile server or use a bad style URL) - verify the same behavior

- [ ] **Step 2: Test globe mode unaffected**

Switch to globe mode. The globe should render as before (black void or star field, depending on enhanced visuals setting). The panorama CSS only applies to `.meridian-map-viewport::before` which is behind the globe canvas and not visible.

- [ ] **Step 3: Test image-load failure**

Temporarily rename `war-room-panorama.jpg`. The map should fall back to the dark gradient defined in the CSS `background` shorthand. Rename it back.

- [ ] **Step 4: Final commit**

If any fixes were made during verification:

```bash
git add -A
git commit -m "fix: war-room panorama edge cases"
```

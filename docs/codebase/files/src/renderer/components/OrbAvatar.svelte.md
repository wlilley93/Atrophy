# src/renderer/components/OrbAvatar.svelte - Procedural Orb Avatar

**Line count:** ~579 lines  
**Dependencies:** `svelte`, store imports, `../api`  
**Purpose:** Render procedural orb avatar with video loops and canvas fallback

## Overview

This component displays the agent's avatar as either a video loop (if available) or a procedural canvas animation (fallback). The orb changes colour based on emotional state and supports multiple video clips for different emotions.

## Props

```typescript
interface Props {
  pip?: boolean;         // Picture-in-picture mode
  ambientMode?: boolean; // Play ambient video, skip emotion clips
}
```

## State Variables

### Video State

```typescript
let videoEl = $state<HTMLVideoElement | null>(null);
let videoSrc = $state('');
let videoReady = $state(false);
let videoError = $state(false);
let allLoops = $state<string[]>([]);
let currentLoopIndex = 0;
let loadedAgent = '';
let loadedEmotion: string | null = null;
let showingAmbient = $state(false);
let loadGeneration = 0;  // Monotonic counter for stale detection
```

### Download State

```typescript
let downloading = $state(false);
let downloadPercent = $state(0);
```

### Canvas Fallback

```typescript
let canvas = $state<HTMLCanvasElement | null>(null);
let ctx: CanvasRenderingContext2D | null = null;
let time = 0;
let animFrame = 0;
let canvasRunning = false;
let blendFactor = 0;
const BLEND_SPEED = 0.04;
```

## Video Loading

### loadAmbient

```typescript
async function loadAmbient(generation: number) {
  if (!api?.getAvatarAmbientPath) return false;
  try {
    const filePath = await api.getAvatarAmbientPath();
    if (generation !== loadGeneration) return false;
    if (filePath) {
      const newSrc = `file://${filePath}`;
      if (newSrc !== videoSrc) {
        videoSrc = newSrc;
        videoReady = false;
      }
      videoError = false;
      showingAmbient = true;
      return true;
    }
  } catch {
    if (generation !== loadGeneration) return false;
  }
  return false;
}
```

**Purpose:** Load agent's ambient video loop.

### loadVideo

```typescript
async function loadVideo(generation: number, colour = 'blue', clip = 'idle_hover') {
  if (!api) return;
  try {
    const filePath = await api.getAvatarVideoPath(colour, clip);
    if (generation !== loadGeneration) return;  // Stale - agent switched
    if (filePath) {
      const newSrc = `file://${filePath}`;
      if (newSrc !== videoSrc) {
        videoSrc = newSrc;
        videoReady = false;
      }
      videoError = false;
      showingAmbient = false;
    } else {
      videoError = true;
    }
  } catch {
    if (generation !== loadGeneration) return;
    videoError = true;
  }
}
```

**Purpose:** Load specific emotion clip.

**Stale detection:** Uses `loadGeneration` counter to discard results from switched agents.

### loadAllLoops

```typescript
async function loadAllLoops(generation: number) {
  if (!api?.listAvatarLoops) return;
  try {
    const loops: string[] = await api.listAvatarLoops();
    if (generation !== loadGeneration) return;
    allLoops = loops;
    currentLoopIndex = 0;
    if (loops.length > 0) {
      const newSrc = `file://${loops[0]}`;
      if (newSrc !== videoSrc) {
        videoSrc = newSrc;
        videoReady = false;
      }
      videoError = false;
      showingAmbient = false;
    }
  } catch {
    // API unavailable - caller falls back to single-clip loadVideo
  }
}
```

**Purpose:** Fetch all available loops and load first one.

## Video Event Handlers

### onVideoEnded

```typescript
function onVideoEnded() {
  videoEl?.play().catch(() => {});
}
```

**Purpose:** Loop video when it ends.

### onVideoCanPlay

```typescript
function onVideoCanPlay() {
  console.log('[OrbAvatar] video canplay', videoSrc.split('/').slice(-2).join('/'));
  videoReady = true;
  downloading = false;
  stopCanvas();
  videoEl?.play().catch((e) => console.warn('[OrbAvatar] play() rejected:', e));
}
```

**Purpose:** Start playback when video is ready, stop canvas fallback.

### onVideoError

```typescript
function onVideoError() {
  const el = videoEl;
  const code = el?.error?.code;
  const msg = el?.error?.message;
  console.error('[OrbAvatar] video error', { src: videoSrc, code, msg });
  videoError = true;
  startCanvas();
}
```

**Purpose:** Fall back to canvas on video error.

## Canvas Fallback

### startCanvas

```typescript
function startCanvas() {
  if (canvasRunning || !canvas) return;
  const rect = canvas.getBoundingClientRect();
  // Defer if layout hasn't happened (zero-size on first mount)
  if (rect.width === 0 || rect.height === 0) {
    requestAnimationFrame(() => startCanvas());
    return;
  }
  ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx?.scale(dpr, dpr);
  canvasRunning = true;
  draw();
}
```

**Purpose:** Start procedural canvas animation.

**DPI scaling:** Scales canvas for high-DPI displays.

### stopCanvas

```typescript
function stopCanvas() {
  canvasRunning = false;
  cancelAnimationFrame(animFrame);
  animFrame = 0;
}
```

**Purpose:** Stop canvas animation when video is ready.

### orbColor

```typescript
function orbColor(): { h: number; s: number; l: number } {
  const conn = emotionalState.connection;
  const warm = emotionalState.warmth;
  const play = emotionalState.playfulness;
  const frust = emotionalState.frustration;

  // Base colour from emotional state
  let h = 220 + (warm - 0.5) * -40 + (play - 0.3) * 20;
  let s = 55 + conn * 25;
  let l = 25 + warm * 15;

  // Frustration shifts toward red
  if (frust > 0.3) {
    h = h + (frust - 0.3) * 100;
    s = s + frust * 20;
  }

  // Blend toward active emotion colour when one is set
  const target = activeEmotion.type !== null ? 1 : 0;
  blendFactor += (target - blendFactor) * BLEND_SPEED;

  if (blendFactor > 0.01) {
    const ec = activeEmotion.colour;
    h = h + (ec.h - h) * blendFactor;
    s = s + (ec.s - s) * blendFactor;
    l = l + (ec.l - l) * blendFactor;
  }

  return { h, s, l };
}
```

**Purpose:** Calculate orb colour from emotional state.

**Colour formula:**
- Base hue: 220 (blue)
- Warmth shift: -40 per warmth unit (toward red/orange)
- Playfulness shift: +20 per playfulness unit (toward green)
- Connection increases saturation
- Frustration > 0.3 shifts toward red
- Blends to active emotion colour over time

**Blend speed:** 0.04 per frame (~2.4 per second)

### draw

```typescript
function draw() {
  if (!canvasRunning || !ctx) return;
  
  const rect = canvas.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) / 2;
  
  // Clear
  ctx.fillStyle = 'rgba(0, 0, 0, 0.1)';
  ctx.fillRect(0, 0, width, height);
  
  // Get colour
  const colour = orbColor();
  
  // Draw orb with radial gradient
  const gradient = ctx.createRadialGradient(
    centerX, centerY, 0,
    centerX, centerY, radius
  );
  gradient.addColorStop(0, `hsla(${colour.h}, ${colour.s}%, ${colour.l + 30}%, 0.8)`);
  gradient.addColorStop(0.5, `hsla(${colour.h}, ${colour.s}%, ${colour.l}%, 0.6)`);
  gradient.addColorStop(1, `hsla(${colour.h}, ${colour.s}%, ${colour.l - 10}%, 0)`);
  
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
  ctx.fill();
  
  // Continue animation
  time += 0.016;
  animFrame = requestAnimationFrame(draw);
}
```

**Purpose:** Draw procedural orb animation.

**Animation:**
- Fade trail effect (rgba 0.1 opacity clear)
- Radial gradient from center to edge
- Continuous requestAnimationFrame loop

## Template

```svelte
<div class="orb-avatar" class:pip>
  {#if videoError || (!videoReady && !downloading)}
    <canvas bind:this={canvas} class="orb-canvas"></canvas>
  {/if}
  
  <video
    bind:this={videoEl}
    src={videoSrc}
    on:ended={onVideoEnded}
    on:canplay={onVideoCanPlay}
    on:error={onVideoError}
    muted
    playsinline
    class="orb-video"
  />
  
  {#if downloading}
    <div class="download-progress">
      <div class="bar" style="width: {downloadPercent}%"></div>
      <span>{downloadPercent}%</span>
    </div>
  {/if}
</div>
```

**Structure:**
1. Canvas fallback (when video unavailable)
2. Video element
3. Download progress overlay

## Styling

```css
.orb-avatar {
  position: absolute;
  inset: 0;
  z-index: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.orb-avatar.pip {
  position: fixed;
  bottom: 100px;
  right: 20px;
  width: 200px;
  height: 200px;
  border-radius: 50%;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  z-index: 100;
}

.orb-canvas, .orb-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.orb-video {
  opacity: 0;
  transition: opacity 0.3s ease;
}

.orb-video.ready {
  opacity: 1;
}

.download-progress {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.7);
  padding: 10px 20px;
  border-radius: 20px;
  color: white;
}

.bar {
  display: block;
  height: 4px;
  background: #4CAF50;
  border-radius: 2px;
  margin-bottom: 5px;
  transition: width 0.2s;
}
```

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/stores/emotional-state.svelte.ts` - Emotional state store
- `src/renderer/stores/emotion-colours.svelte.ts` - Emotion colour mapping
- `src/main/avatar-downloader.ts` - Avatar asset downloading

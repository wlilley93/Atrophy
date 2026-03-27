# src/renderer/components/OrbAvatar.svelte - Procedural Orb Avatar

**Dependencies:** `../stores/session.svelte`, `../stores/emotional-state.svelte`, `../stores/emotion-colours.svelte`, `../stores/agents.svelte`, `../api`  
**Purpose:** Render procedural orb avatar with video loops and canvas fallback

## Overview

This component renders the agent's avatar as either a video loop (if available) or a procedural canvas animation (fallback). The orb changes colour based on the agent's emotional state and supports multiple video clips for different emotions.

## Props

```typescript
interface Props {
  pip?: boolean;         // Picture-in-picture mode
  ambientMode?: boolean; // Play ambient video, skip emotion clips
}
```

**Defaults:**
- `pip: false` - Full size in main window
- `ambientMode: false` - Show emotion-specific clips

## State Variables

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

let downloading = $state(false);
let downloadPercent = $state(0);

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
    if (generation !== loadGeneration) return false;  // Stale
    if (filePath) {
      videoSrc = `file://${filePath}`;
      videoReady = false;
      videoError = false;
      showingAmbient = true;
      return true;
    }
  } catch { /* ignore */ }
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
    if (generation !== loadGeneration) return;  // Stale
    if (filePath) {
      videoSrc = `file://${filePath}`;
      videoReady = false;
      videoError = false;
      showingAmbient = false;
    } else {
      videoError = true;
    }
  } catch {
    videoError = true;
  }
}
```

**Purpose:** Load specific emotion clip.

### loadAllLoops

```typescript
async function loadAllLoops(generation: number) {
  if (!api?.listAvatarLoops) return;
  try {
    const loops: string[] = await api.listAvatarLoops();
    if (generation !== loadGeneration) return;  // Stale
    allLoops = loops;
    currentLoopIndex = 0;
    if (loops.length > 0) {
      videoSrc = `file://${loops[0]}`;
      videoReady = false;
      showingAmbient = false;
    }
  } catch { /* API unavailable - caller falls back to single-clip load */ }
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
  console.log('[OrbAvatar] video canplay', videoSrc);
  videoReady = true;
  downloading = false;
  stopCanvas();
  videoEl?.play().catch((e) => console.warn('[OrbAvatar] play() rejected:', e));
}
```

**Purpose:** Start playback when video is ready.

### onVideoError

```typescript
function onVideoError() {
  const code = videoEl?.error?.code;
  const msg = videoEl?.error?.message;
  console.error('[OrbAvatar] video error', { code, msg });
  videoError = true;
  startCanvas();  // Fall back to procedural canvas
}
```

**Purpose:** Fall back to canvas on video error.

## Canvas Fallback

### startCanvas

```typescript
function startCanvas() {
  if (canvasRunning) return;
  canvasRunning = true;
  animate();
}

function animate() {
  if (!canvasRunning || !ctx) return;
  
  time += 0.016;  // ~60fps
  
  // Clear with emotion-blended colour
  const baseColour = activeEmotion.colour;
  const targetColour = emotionalState.connection > 0.7 
    ? { h: 200, s: 60, l: 25 }  // More vibrant when connected
    : baseColour;
  
  // Smooth blend
  blendFactor = Math.min(1, blendFactor + BLEND_SPEED);
  const r = lerp(baseColour.l, targetColour.l, blendFactor);
  
  ctx.fillStyle = `hsl(${baseColour.h}, ${baseColour.s}%, ${r}%)`;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  
  // Draw procedural orb
  drawOrb(ctx, time);
  
  animFrame = requestAnimationFrame(animate);
}
```

**Purpose:** Start procedural canvas animation.

### stopCanvas

```typescript
function stopCanvas() {
  canvasRunning = false;
  if (animFrame) cancelAnimationFrame(animFrame);
}
```

**Purpose:** Stop canvas animation when video is ready.

## Emotion Reactivity

```svelte
<!-- React to emotion changes -->
$effect(() => {
  if (ambientMode || !activeEmotion.type) return;
  
  const colourDir = getColourDirName(activeEmotion.type);
  const clip = EMOTIONS[activeEmotion.type]?.clip || 'idle_hover';
  
  loadGeneration++;
  loadVideo(loadGeneration, colourDir, clip);
});

<!-- React to agent changes -->
$effect(() => {
  if (!agents.current) return;
  
  loadGeneration++;
  loadedAgent = agents.current;
  
  if (ambientMode) {
    loadAmbient(loadGeneration);
  } else {
    loadAllLoops(loadGeneration);
  }
});
```

**Purpose:** Load appropriate video when emotion or agent changes.

## Avatar Download

```svelte
async function downloadAvatar() {
  downloading = true;
  downloadPercent = 0;
  
  const unsubProgress = api.onAvatarDownloadProgress((data) => {
    downloadPercent = data.percent;
  });
  
  try {
    await api.downloadAvatarAssets();
  } finally {
    unsubProgress();
    downloading = false;
  }
}
```

**Purpose:** Download avatar assets if missing.

## Template Structure

```svelte
<div class="orb-avatar" class:pip>
  {#if videoError || (!videoReady && !downloading)}
    <!-- Canvas fallback -->
    <canvas bind:this={canvas} />
  {/if}
  
  <video
    bind:this={videoEl}
    src={videoSrc}
    on:ended={onVideoEnded}
    on:canplay={onVideoCanPlay}
    on:error={onVideoError}
    muted
    playsinline
  />
  
  {#if downloading}
    <div class="download-progress">
      <div class="bar" style="width: {downloadPercent}%" />
      <span>{downloadPercent}%</span>
    </div>
  {/if}
</div>
```

## Styling

```svelte
<style>
  .orb-avatar {
    position: relative;
    width: 100%;
    height: 100%;
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
  }
  
  video, canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
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
</style>
```

## Stale Detection Pattern

```typescript
let loadGeneration = 0;

async function loadVideo(generation: number) {
  const filePath = await api.getAvatarVideoPath(colour, clip);
  if (generation !== loadGeneration) return;  // Stale - agent switched during await
  // ... proceed with load
}

// When agent switches:
$effect(() => {
  loadGeneration++;  // Invalidate pending loads
  loadVideo(loadGeneration);
});
```

**Purpose:** Discard stale async results when agent switches mid-load.

## Exported API

None - component is self-contained.

## See Also

- [`emotion-colours.svelte.ts`](../stores/emotion-colours.svelte.md) - Emotion classification
- [`emotional-state.svelte.ts`](../stores/emotional-state.svelte.md) - Inner life state
- `src/main/avatar-downloader.ts` - Avatar asset downloading

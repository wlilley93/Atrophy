# src/renderer/components/ThinkingIndicator.svelte - Thinking Brain Animation

**Line count:** ~50 lines  
**Dependencies:** `svelte`  
**Purpose:** Animated brain icon indicating inference in progress

## Overview

This component displays an animated brain icon during inference. It cycles through 10 brain frame images (brain_00.png to brain_09.png) with a gentle opacity pulse.

## Brain Frames

```typescript
const brainFramePaths: string[] = [];
const frameModules = import.meta.glob(
  '../../../resources/icons/brain_frames/brain_*.png',
  { eager: true, query: '?url', import: 'default' }
);
const sortedKeys = Object.keys(frameModules).sort();
for (const key of sortedKeys) {
  brainFramePaths.push(frameModules[key] as string);
}
```

**Source:** `resources/icons/brain_frames/brain_*.png`

**Frame count:** 10 frames (00-09)

**Meaning:**
- Frame 00: Healthy/active
- Frame 09: Most decayed

## State Variables

```typescript
let currentFrame = $state(0);
let opacity = $state(0.5);
let tick = 0;
```

**Purpose:**
- `currentFrame`: Current frame index (0-9)
- `opacity`: Pulse opacity (0.35-0.7)
- `tick`: Animation tick counter

## Animation

```typescript
onMount(() => {
  const interval = setInterval(() => {
    tick++;
    currentFrame = tick % brainFramePaths.length;
    // Gentle pulse between 0.35 and 0.7
    opacity = 0.35 + 0.35 * Math.sin(tick * 0.2);
  }, 250);

  return () => clearInterval(interval);
});
```

**Animation details:**
- Frame cycle: Every 250ms (4fps)
- Opacity pulse: Sine wave with amplitude 0.35, offset 0.35
- Pulse frequency: 0.2 radians per tick

**Visual effect:**
- Brain cycles through 10 frames continuously
- Opacity pulses between 35% and 70%
- Creates "thinking" visual feedback

## Template

```svelte
{#if brainFramePaths.length > 0}
  <div class="thinking-brain" style="opacity: {opacity}">
    <img
      src={brainFramePaths[currentFrame]}
      alt=""
      class="brain-frame"
      draggable="false"
    />
  </div>
{/if}
```

**Conditional rendering:** Only shown if brain frames exist.

## Styling

```css
.thinking-brain {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  padding: 4px 0;
  will-change: opacity;
}

.brain-frame {
  width: 24px;
  height: 24px;
  object-fit: contain;
  filter: grayscale(0.3) brightness(0.85);
  pointer-events: none;
  user-select: none;
}
```

**Key styles:**
- Fixed 24x24px size
- Grayscale 30% + brightness 85% filter
- Non-interactive (pointer-events: none)
- Opacity will-change for smooth animation

## Usage

```svelte
{#if session.inferenceState === 'thinking'}
  <ThinkingIndicator />
{/if}
```

**Shown when:** Inference state is 'thinking'

## File I/O

None - uses Vite glob import for frame paths.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/stores/session.svelte.ts` - InferenceState type
- `src/renderer/components/Window.svelte` - Parent component
- `resources/icons/brain_frames/` - Brain frame images

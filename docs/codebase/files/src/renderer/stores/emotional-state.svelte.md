# src/renderer/stores/emotional-state.svelte.ts - Inner Life Store

**Line count:** ~35 lines  
**Dependencies:** None (Svelte 5 built-in runes)  
**Purpose:** Reactive emotional state store mirroring the agent's inner life

## Overview

This module exports the agent's emotional state as module-level reactive state using Svelte 5's `$state` rune. The state is updated via IPC from the main process and drives visual feedback (orb colors, UI indicators).

## Types

### EmotionalState

```typescript
export interface EmotionalState {
  connection: number;    // 0.0-1.0
  curiosity: number;     // 0.0-1.0
  confidence: number;    // 0.0-1.0
  warmth: number;        // 0.0-1.0
  frustration: number;   // 0.0-1.0
  playfulness: number;   // 0.0-1.0
}
```

**Dimensions:**

| Dimension | Range | Default | Meaning |
|-----------|-------|---------|---------|
| `connection` | 0-1 | 0.5 | Engagement depth with user |
| `curiosity` | 0-1 | 0.6 | Interest, wanting to explore |
| `confidence` | 0-1 | 0.5 | Certainty in own read |
| `warmth` | 0-1 | 0.5 | Affection, care |
| `frustration` | 0-1 | 0.1 | Irritation, blocked goals |
| `playfulness` | 0-1 | 0.3 | Lightness, humor |

### TrustState

```typescript
export interface TrustState {
  emotional: number;     // 0.0-1.0
  intellectual: number;  // 0.0-1.0
  creative: number;      // 0.0-1.0
  practical: number;     // 0.0-1.0
}
```

**Dimensions:**

| Dimension | Range | Default | Meaning |
|-----------|-------|---------|---------|
| `emotional` | 0-1 | 0.5 | Safe to be vulnerable |
| `intellectual` | 0-1 | 0.5 | User respects agent thinking |
| `creative` | 0-1 | 0.5 | User values agent ideas |
| `practical` | 0-1 | 0.5 | User relies on agent to deliver |

## Reactive State

### emotionalState

```typescript
export const emotionalState = $state<EmotionalState>({
  connection: 0.5,
  curiosity: 0.6,
  confidence: 0.5,
  warmth: 0.5,
  frustration: 0.1,
  playfulness: 0.3,
});
```

**Purpose:** Current emotional state values.

**Updates:** Via IPC from main process when `update_emotional_state` MCP tool is called.

### trustState

```typescript
export const trustState = $state<TrustState>({
  emotional: 0.5,
  intellectual: 0.5,
  creative: 0.5,
  practical: 0.5,
});
```

**Purpose:** Current trust values per domain.

**Updates:** Via IPC from main process when trust changes.

## Usage in Components

```svelte
<script lang="ts">
  import { emotionalState, trustState } from '../stores/emotional-state.svelte';
  
  // Reactively compute derived values
  $: overallMood = emotionalState.frustration > 0.5 
    ? 'stressed' 
    : emotionalState.connection > 0.7 
      ? 'connected' 
      : 'neutral';
  
  $: orbColor = computeOrbColor(emotionalState);
</script>

<div class="emotion-display">
  <div>Connection: {Math.round(emotionalState.connection * 100)}%</div>
  <div>Frustration: {Math.round(emotionalState.frustration * 100)}%</div>
</div>
```

## Orb Color Mapping

The emotional state drives the procedural orb's appearance:

```typescript
// In emotion-colours.svelte.ts
function computeOrbColor(state: EmotionalState): HSL {
  let hue = 220;  // Base blue
  let saturation = 50;
  let lightness = 20;
  
  // Warmth shifts toward red/orange
  if (state.warmth > 0.6) {
    hue = 30 + (1 - state.warmth) * 190;
  }
  
  // Connection increases saturation
  saturation = 30 + state.connection * 30;
  
  // Frustration introduces red shift
  if (state.frustration > 0.3) {
    hue = 0 + (1 - state.frustration) * 30;
  }
  
  return { h: hue, s: saturation, l: lightness };
}
```

## IPC Integration

Main process pushes state updates via IPC:

```typescript
// In main process (ipc/inference.ts or similar)
ipcMain.handle('inner-life:update', (_event, state: EmotionalState) => {
  emotionalState.connection = state.connection;
  emotionalState.curiosity = state.curiosity;
  // ... etc
});

// In renderer (Window.svelte or similar)
onMount(() => {
  const unsub = api.onInnerLifeUpdate((state) => {
    emotionalState.connection = state.connection;
    emotionalState.curiosity = state.curiosity;
    // ... etc
  });
  return unsub;
});
```

## State Visualization

```
┌─────────────────────────────────────────────────────────────┐
│                    Emotional State Radar                      │
│                                                               │
│                    curiosity (0.6)                            │
│                         ▲                                     │
│                        / \                                    │
│                       /   \                                   │
│              connection   confidence                          │
│                (0.5)▲     ▲(0.5)                              │
│                    /       \                                  │
│                   /         \                                 │
│    frustration ◄─┼───────────┼─► warmth                       │
│       (0.1)      │           │  (0.5)                        │
│                   \         /                                 │
│                    \       /                                  │
│                     \     /                                   │
│                      \   /                                    │
│                       \ /                                     │
│                        ▼                                      │
│                   playfulness (0.3)                           │
└─────────────────────────────────────────────────────────────┘
```

## Default Values Rationale

| Dimension | Default | Rationale |
|-----------|---------|-----------|
| `connection: 0.5` | Neutral starting point |
| `curiosity: 0.6` | Slightly above neutral (agent is inherently curious) |
| `confidence: 0.5` | Neutral, builds with interaction |
| `warmth: 0.5` | Neutral, responsive to user |
| `frustration: 0.1` | Low baseline (agent is patient) |
| `playfulness: 0.3` | Below neutral (serious but can be playful) |

## Exported API

| Export | Type | Purpose |
|--------|------|---------|
| `EmotionalState` | interface | Emotional state interface |
| `TrustState` | interface | Trust state interface |
| `emotionalState` | reactive object | Module-level emotional state |
| `trustState` | reactive object | Module-level trust state |

## See Also

- [`session.svelte.ts`](session.svelte.md) - App lifecycle state
- `src/main/inner-life.ts` - Main process emotional state engine
- `src/renderer/components/OrbAvatar.svelte` - Orb visualization using emotional state

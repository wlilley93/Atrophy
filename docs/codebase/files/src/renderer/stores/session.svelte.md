# src/renderer/stores/session.svelte.ts - Session State Store

**Line count:** ~15 lines  
**Dependencies:** None (Svelte 5 built-in runes)  
**Purpose:** Reactive session state for app lifecycle and inference status

## Overview

This module exports module-level reactive state using Svelte 5's `$state` rune. The state is shared across all components that import it, providing a single source of truth for the app's current phase and inference state.

## Types

### AppPhase

```typescript
export type AppPhase = 'boot' | 'setup' | 'ready' | 'shutdown';
```

**Values:**
- `'boot'` - App is initializing
- `'setup'` - First-launch setup wizard is active
- `'ready'` - App is fully operational
- `'shutdown'` - App is shutting down

### InferenceState

```typescript
export type InferenceState = 'idle' | 'thinking' | 'streaming' | 'compacting';
```

**Values:**
- `'idle'` - No inference in progress
- `'thinking'` - Waiting for Claude CLI to start responding
- `'streaming'` - Receiving streaming response
- `'compacting'` - Context window is being compacted

## Reactive State

### session

```typescript
export const session = $state({
  phase: 'boot' as AppPhase,
  inferenceState: 'idle' as InferenceState,
  isRecording: false,
  idleSeconds: 0,
});
```

**Fields:**

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `phase` | `AppPhase` | `'boot'` | Current app lifecycle phase |
| `inferenceState` | `InferenceState` | `'idle'` | Current inference state |
| `isRecording` | `boolean` | `false` | Whether push-to-talk recording is active |
| `idleSeconds` | `number` | `0` | Seconds since last user interaction |

## Usage in Components

```svelte
<script lang="ts">
  import { session } from '../stores/session.svelte';
  
  // Reactively read state
  $: isInferenceActive = session.inferenceState !== 'idle';
  $: isAppReady = session.phase === 'ready';
</script>

{#if session.phase === 'boot'}
  <SplashScreen />
{/if}

{#if session.inferenceState === 'thinking'}
  <ThinkingIndicator />
{/if}
```

## State Transitions

### Boot Sequence

```
boot ──▶ setup (if first launch) ──▶ ready
   └──▶ ready (if already configured)
```

### Inference Flow

```
idle ──▶ thinking ──▶ streaming ──▶ idle
              │
              └──▶ compacting ──▶ streaming
```

## Module-Level Reactivity

Svelte 5's `$state` rune creates module-level reactive state. This means:

1. **Single instance:** All imports share the same state object
2. **Fine-grained updates:** Components only re-render when accessed fields change
3. **No store subscriptions:** Direct property access, no `.subscribe()` needed

```typescript
// All these imports reference the same state object
import { session } from './session.svelte';  // Component A
import { session } from './session.svelte';  // Component B
import { session } from './session.svelte';  // Component C

// Mutation in Component A is visible in B and C
session.phase = 'ready';  // All components see the change
```

## Exported API

| Export | Type | Purpose |
|--------|------|---------|
| `AppPhase` | type | App lifecycle phase union type |
| `InferenceState` | type | Inference state union type |
| `session` | reactive object | Module-level reactive state |

## See Also

- [`transcript.svelte.ts`](transcript.svelte.md) - Message history store
- [`agents.svelte.ts`](agents.svelte.md) - Agent list store
- [`audio.svelte.ts`](audio.svelte.md) - TTS playback state
- `src/renderer/components/Window.svelte` - Primary consumer of session state

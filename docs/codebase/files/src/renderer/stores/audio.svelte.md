# src/renderer/stores/audio.svelte.ts - TTS Playback State Store

**Line count:** ~10 lines  
**Dependencies:** None (Svelte 5 built-in runes)  
**Purpose:** Reactive TTS playback queue state

## Overview

This module exports module-level reactive state for TTS playback using Svelte 5's `$state` rune. The state tracks the audio queue, playback status, and visual effects.

## Reactive State

### audio

```typescript
export const audio = $state({
  queue: [] as string[],
  isPlaying: false,
  vignetteOpacity: 0,
});
```

**Fields:**

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `queue` | `string[]` | `[]` | Array of pending audio file paths |
| `isPlaying` | `boolean` | `false` | Whether TTS audio is currently playing |
| `vignetteOpacity` | `number` | `0` | Opacity for warm vignette overlay |

## Visual Feedback

The `vignetteOpacity` field drives a warm radial gradient overlay during speech playback:

```svelte
<!-- In Window.svelte -->
<div 
  class="vignette"
  style="opacity: {audio.vignetteOpacity}"
/>

<style>
  .vignette {
    position: fixed;
    inset: 0;
    background: radial-gradient(
      circle at center,
      transparent 50%,
      rgba(255, 200, 100, 0.15) 100%
    );
    pointer-events: none;
  }
</style>
```

**Effect:** Warm amber glow during speech, creating a sense of presence.

## Usage in Components

```svelte
<script lang="ts">
  import { audio } from '../stores/audio.svelte';
  import { api } from '../api';
  
  // Reactively display playback state
  $: playbackIndicator = audio.isPlaying ? '🔊' : '🔇';
  
  // Mute/unmute toggle
  function toggleMute() {
    api.setMuted(!audio.isPlaying);
  }
</script>

<div class="audio-status">
  {playbackIndicator}
  {#if audio.queue.length > 0}
    <span class="queue-length">{audio.queue.length} pending</span>
  {/if}
</div>
```

## IPC Integration

Main process updates state via IPC events:

```typescript
// In main process (ipc/inference.ts)
ipcMain.handle('inference:send', async () => {
  // ... inference logic ...
  
  emitter.on('event', (evt: InferenceEvent) => {
    switch (evt.type) {
      case 'SentenceReady':
        // Notify renderer about sentence boundary
        mainWindow.webContents.send(
          'inference:sentenceReady', 
          evt.sentence, 
          evt.index, 
          ttsActive  // Renderer sets audio.isPlaying = ttsActive
        );
        break;
    }
  });
});

// In renderer (Window.svelte)
onMount(() => {
  const unsubTtsStarted = api.onTtsStarted((index) => {
    audio.isPlaying = true;
    audio.vignetteOpacity = 0.15;
  });
  
  const unsubTtsDone = api.onTtsDone((index) => {
    // Check if more audio pending
    if (/* no more pending */) {
      audio.isPlaying = false;
      audio.vignetteOpacity = 0;
    }
  });
  
  return () => {
    unsubTtsStarted();
    unsubTtsDone();
  };
});
```

## State Transitions

```
┌─────────────────────────────────────────────────────────────┐
│                    Audio Playback Flow                       │
│                                                               │
│  idle ──▶ TTS starts ──▶ isPlaying=true, vignette=0.15      │
│   ▲            │                                             │
│   │            ▼                                             │
│   │     Sentence plays                                       │
│   │            │                                             │
│   │            ▼                                             │
│   └──── TTS queue empty ──▶ isPlaying=false, vignette=0     │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Module-Level Reactivity

Svelte 5's `$state` rune creates module-level reactive state:

1. **Single instance:** All imports share the same state object
2. **Fine-grained updates:** Components only re-render when accessed fields change
3. **No store subscriptions:** Direct property access, no `.subscribe()` needed

## Exported API

| Export | Type | Purpose |
|--------|------|---------|
| `audio` | reactive object | Module-level audio state |

## See Also

- [`session.svelte.ts`](session.svelte.md) - App lifecycle state
- `src/main/tts.ts` - TTS synthesis and playback queue
- `src/renderer/components/Window.svelte` - Vignette overlay rendering

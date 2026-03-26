# src/renderer/stores/emotion-colours.svelte.ts - Emotion-to-Colour Mapping

**Line count:** ~180 lines  
**Dependencies:** None (Svelte 5 built-in runes)  
**Purpose:** Classify response text into emotions and map to HSL colours for orb avatar

## Overview

This module implements emotion classification for the procedural orb avatar. It classifies response text into discrete emotion types, each with an associated HSL colour and video clip. The classification uses a score-based keyword matching algorithm.

## Types

### EmotionType

```typescript
export type EmotionType =
  | 'thinking'
  | 'alert'
  | 'frustrated'
  | 'positive'
  | 'cautious'
  | 'reflective';
```

### EmotionSpec

```typescript
export interface EmotionSpec {
  colour: HSLColour;
  clip: string;      // Video clip name for avatar
  keywords: string[]; // Keywords for classification
}
```

### HSLColour

```typescript
export interface HSLColour {
  h: number;  // Hue (0-360)
  s: number;  // Saturation (0-100)
  l: number;  // Lightness (0-100)
}
```

## Colour Palette

```typescript
const COLOURS: Record<string, HSLColour> = {
  blue: { h: 220, s: 50, l: 20 },      // Default ambient
  dark_blue: { h: 230, s: 40, l: 15 }, // Thinking
  red: { h: 0, s: 60, l: 25 },         // Alert, frustrated
  green: { h: 140, s: 45, l: 22 },     // Positive
  orange: { h: 30, s: 55, l: 25 },     // Cautious
  purple: { h: 270, s: 45, l: 22 },    // Reflective
};
```

**Colour meanings:**

| Colour | HSL | Emotion | Meaning |
|--------|-----|---------|---------|
| Blue | 220°, 50%, 20% | Default | Neutral, ambient |
| Dark Blue | 230°, 40%, 15% | Thinking | Processing, focused |
| Red | 0°, 60%, 25% | Alert/Frustrated | Warning, error |
| Green | 140°, 45%, 22% | Positive | Success, completion |
| Orange | 30°, 55%, 25% | Cautious | Note, consideration |
| Purple | 270°, 45%, 22% | Reflective | Philosophical, deep |

## Emotion Definitions

```typescript
export const EMOTIONS: Record<EmotionType, EmotionSpec> = {
  thinking: {
    colour: COLOURS.dark_blue,
    clip: 'idle_hover',
    keywords: [],  // Triggered programmatically
  },
  alert: {
    colour: COLOURS.red,
    clip: 'pulse_intense',
    keywords: [
      'warning', 'danger', 'urgent', 'critical', 'alert',
      'stop', 'protect', 'threat', 'security', 'emergency',
      'do not', 'must not', 'cannot allow',
    ],
  },
  frustrated: {
    colour: COLOURS.red,
    clip: 'itch',
    keywords: [
      'error', 'failed', 'broken', 'crash', 'bug',
      "can't", "won't work", 'frustrat', 'damn',
    ],
  },
  positive: {
    colour: COLOURS.green,
    clip: 'drift_close',
    keywords: [
      'done', 'complete', 'success', 'great', 'excellent',
      'ready', 'confirmed', 'yes', 'perfect', 'resolved',
      'happy', 'glad', 'proud', 'love',
    ],
  },
  cautious: {
    colour: COLOURS.orange,
    clip: 'drift_lateral',
    keywords: [
      'note', 'caution', 'cost', 'price', 'budget',
      'careful', 'watch out', 'heads up', 'however',
      'but', 'although', 'risk',
    ],
  },
  reflective: {
    colour: COLOURS.purple,
    clip: 'crystal_shimmer',
    keywords: [
      'interesting', 'philosophical', 'wonder', 'meaning',
      'reflects', 'deeper', 'soul', 'evolve', 'growth',
      'remember when', 'looking back', 'pattern', 'insight',
      'beautiful', 'strange',
    ],
  },
};
```

## Constants

```typescript
export const DEFAULT_COLOUR: HSLColour = COLOURS.blue;
export const REVERT_TIMEOUT_MS = 12_000;  // 12 seconds
```

## classifyEmotion

```typescript
export function classifyEmotion(text: string): EmotionType | null {
  if (!text) return null;

  const lower = text.toLowerCase();
  const scores = new Map<EmotionType, number>();

  for (const [emotion, spec] of Object.entries(EMOTIONS) as [EmotionType, EmotionSpec][]) {
    if (spec.keywords.length === 0) continue;

    let score = 0;
    for (const kw of spec.keywords) {
      let count = 0;
      let idx = lower.indexOf(kw);
      while (idx !== -1) {
        count++;
        idx = lower.indexOf(kw, idx + 1);
      }
      if (count > 0) {
        // Weight longer phrases higher
        score += count * (1 + kw.length / 10);
      }
    }

    if (score > 0) {
      scores.set(emotion, score);
    }
  }

  if (scores.size === 0) return null;

  let best: EmotionType | null = null;
  let bestScore = 0;
  for (const [emotion, score] of scores) {
    if (score > bestScore) {
      bestScore = score;
      best = emotion;
    }
  }

  // Minimum threshold to filter weak matches
  if (bestScore < 2.0) return null;
  return best;
}
```

**Scoring algorithm:**
1. Count keyword occurrences in text
2. Weight longer phrases higher: `count * (1 + keyword.length / 10)`
3. Select emotion with highest score
4. Return null if best score < 2.0 (weak match filter)

**Example scoring:**
```
Text: "I'm warning you, this is urgent and dangerous"

alert keywords:
  - "warning": 1 hit → 1 * (1 + 7/10) = 1.7
  - "urgent": 1 hit → 1 * (1 + 6/10) = 1.6
  - "dangerous" contains "danger": 1 hit → 1 * (1 + 6/10) = 1.6
  
Total alert score: 4.9 → exceeds 2.0 threshold → classified as 'alert'
```

## Reactive State

### activeEmotion

```typescript
export const activeEmotion = $state<{ type: EmotionType | null; colour: HSLColour }>({
  type: null,
  colour: DEFAULT_COLOUR,
});
```

**Purpose:** Currently active emotion for orb rendering.

## setEmotionFromText

```typescript
let revertTimer: ReturnType<typeof setTimeout> | null = null;

export function setEmotionFromText(text: string): void {
  const emotion = classifyEmotion(text);
  if (emotion) {
    setEmotion(emotion);
  }
}
```

**Purpose:** Classify text and set emotion, starting revert timer.

## setEmotion

```typescript
export function setEmotion(emotion: EmotionType): void {
  const spec = EMOTIONS[emotion];
  if (!spec) return;

  activeEmotion.type = emotion;
  activeEmotion.colour = spec.colour;

  // Reset revert timer
  if (revertTimer !== null) {
    clearTimeout(revertTimer);
  }
  revertTimer = setTimeout(revertToDefault, REVERT_TIMEOUT_MS);
}
```

**Purpose:** Set specific emotion directly (e.g., 'thinking' during inference).

**Revert timer:** After 12 seconds, automatically returns to default blue.

## revertToDefault

```typescript
export function revertToDefault(): void {
  if (revertTimer !== null) {
    clearTimeout(revertTimer);
    revertTimer = null;
  }
  activeEmotion.type = null;
  activeEmotion.colour = DEFAULT_COLOUR;
}
```

**Purpose:** Immediately revert to default ambient colour.

## Usage in Components

```svelte
<script lang="ts">
  import { activeEmotion, setEmotionFromText, revertToDefault } from '../stores/emotion-colours.svelte';
  import { api } from '../api';
  
  onMount(() => {
    // Set 'thinking' when inference starts
    const unsubThinking = api.onInferenceStart(() => {
      setEmotion('thinking');
    });
    
    // Classify emotion from response text
    const unsubDone = api.onDone((text) => {
      setEmotionFromText(text);
    });
    
    return () => {
      unsubThinking();
      unsubDone();
      revertToDefault();
    };
  });
</script>
```

## Emotion Flow

```
Agent response text
         │
         ▼
┌─────────────────┐
| classifyEmotion()|
└─────────────────┘
         │
         ▼
    Score keywords
         │
         ▼
    Best score >= 2.0?
         │
    ┌────┴────┐
    │         │
   Yes       No
    │         │
    ▼         ▼
┌────────┐  ┌──────────┐
| Set    │  │ Keep     │
| emotion│  │ default  │
└────────┘  └──────────┘
    │
    ▼
Start 12s revert timer
    │
    ▼
Revert to default blue
```

## Exported API

| Function | Purpose |
|----------|---------|
| `classifyEmotion(text)` | Classify text into emotion type |
| `getReaction(emotion)` | Get colour and clip for emotion |
| `getColourDirName(emotion)` | Get directory name for emotion colour |
| `setEmotionFromText(text)` | Set emotion from response text |
| `setEmotion(emotion)` | Set specific emotion directly |
| `revertToDefault()` | Revert to default ambient colour |
| `EmotionType` | Emotion type union |
| `EmotionSpec` | Emotion specification interface |
| `HSLColour` | HSL colour interface |
| `EMOTIONS` | Emotion definitions map |
| `DEFAULT_COLOUR` | Default ambient colour |
| `REVERT_TIMEOUT_MS` | Revert timer duration (12s) |
| `activeEmotion` | Reactive active emotion state |

## See Also

- [`emotional-state.svelte.ts`](emotional-state.svelte.md) - Inner life emotional state
- `src/renderer/components/OrbAvatar.svelte` - Orb rendering using emotion colours
- `src/main/inner-life.ts` - Main process emotional state engine

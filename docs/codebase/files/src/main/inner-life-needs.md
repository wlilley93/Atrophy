# src/main/inner-life-needs.ts - Needs System

**Line count:** ~120 lines  
**Dependencies:** `./inner-life-types`, `./inner-life`  
**Purpose:** Need satisfaction, depletion, and drive computation from unmet needs

## Overview

This module implements the needs subsystem of the inner life v2 model. It provides functions to satisfy/deplete needs and compute active motivational drives from unmet needs combined with personality, emotions, and trust.

**Scale:** Needs are 0-10; "low" means below 3-4. Drive strength is 0-1.

## Helper Functions

### clampNeeds

```typescript
function clampNeeds(v: number): number {
  return Math.max(0, Math.min(10, v));
}
```

**Purpose:** Clamp need value to valid [0, 10] range.

## satisfyNeed

```typescript
export function satisfyNeed(
  state: FullState,
  need: keyof Needs,
  amount: number,
): FullState {
  const needs = { ...state.needs };
  needs[need] = clampNeeds(needs[need] + amount);
  const updated = { ...state, needs };
  saveState(updated);
  return updated;
}
```

**Purpose:** Increase a need's value, persist state, return updated state.

**Example:**
```typescript
// User sends encouraging message
state = satisfyNeed(state, 'recognition', 2);
// recognition: 5 → 7
```

## depleteNeed

```typescript
export function depleteNeed(
  state: FullState,
  need: keyof Needs,
  amount: number,
): FullState {
  const needs = { ...state.needs };
  needs[need] = clampNeeds(needs[need] - amount);
  const updated = { ...state, needs };
  saveState(updated);
  return updated;
}
```

**Purpose:** Decrease a need's value, persist state, return updated state.

**Example:**
```typescript
// Long conversation without break
state = depleteNeed(state, 'rest', 3);
// rest: 5 → 2 (now unmet, will appear in compressed context)
```

## computeDrives

```typescript
export function computeDrives(state: FullState): Drive[] {
  const { needs, personality, emotions, trust } = state;
  const drives: Drive[] = [];

  // Rule 1: Low stimulation + high curiosity -> "seeking-new-topics"
  if (needs.stimulation <= 3) {
    const strength = (1 - needs.stimulation / 10) * emotions.curiosity;
    if (strength > 0.3) {
      drives.push({ name: 'seeking-new-topics', strength });
    }
  }

  // Rule 2: Low purpose + high initiative -> "offering-to-help"
  if (needs.purpose <= 3) {
    const strength = (1 - needs.purpose / 10) * personality.initiative;
    if (strength > 0.3) {
      drives.push({ name: 'offering-to-help', strength });
    }
  }

  // Rule 3: Low novelty + high restlessness -> "changing-the-subject"
  if (needs.novelty <= 3) {
    const strength = (1 - needs.novelty / 10) * emotions.restlessness;
    if (strength > 0.3) {
      drives.push({ name: 'changing-the-subject', strength });
    }
  }

  // Rule 4: Low recognition + low assertiveness -> "quietly-withdrawn"
  if (needs.recognition <= 3) {
    const strength = (1 - needs.recognition / 10) * (1 - personality.assertiveness);
    if (strength > 0.3) {
      drives.push({ name: 'quietly-withdrawn', strength });
    }
  }

  // Rule 5: Low social + high warmth_default -> "reaching-out-unprompted"
  if (needs.social <= 3) {
    const strength = (1 - needs.social / 10) * personality.warmth_default;
    if (strength > 0.3) {
      drives.push({ name: 'reaching-out-unprompted', strength });
    }
  }

  // Rule 6: Low rest -> "conserving-energy"
  if (needs.rest <= 3) {
    const strength = (1 - needs.rest / 10);
    if (strength > 0.3) {
      drives.push({ name: 'conserving-energy', strength });
    }
  }

  // Rule 7: Low expression + high creative trust -> "wanting-to-create"
  if (needs.expression <= 3) {
    const strength = (1 - needs.expression / 10) * trust.creative;
    if (strength > 0.3) {
      drives.push({ name: 'wanting-to-create', strength });
    }
  }

  // Rule 8: Low autonomy + high operational trust -> "acting-independently"
  if (needs.autonomy <= 3) {
    const strength = (1 - needs.autonomy / 10) * trust.operational;
    if (strength > 0.3) {
      drives.push({ name: 'acting-independently', strength });
    }
  }

  // Sort by strength descending
  drives.sort((a, b) => b.strength - a.strength);

  return drives;
}
```

## Drive Rules

| # | Condition | Amplifier | Drive |
|---|-----------|-----------|-------|
| 1 | stimulation ≤ 3 | curiosity | seeking-new-topics |
| 2 | purpose ≤ 3 | initiative | offering-to-help |
| 3 | novelty ≤ 3 | restlessness | changing-the-subject |
| 4 | recognition ≤ 3 | (1 - assertiveness) | quietly-withdrawn |
| 5 | social ≤ 3 | warmth_default | reaching-out-unprompted |
| 6 | rest ≤ 3 | none | conserving-energy |
| 7 | expression ≤ 3 | creative trust | wanting-to-create |
| 8 | autonomy ≤ 3 | operational trust | acting-independently |

**Strength formula:** `(1 - need/10) * amplifier`

**Threshold:** Only drives with strength > 0.3 are included.

## Example Drive Computations

### Example 1: Seeking new topics

```typescript
state.needs.stimulation = 2  // Low (unmet)
state.emotions.curiosity = 0.8  // High

strength = (1 - 2/10) * 0.8 = 0.8 * 0.8 = 0.64

// Drive included: { name: 'seeking-new-topics', strength: 0.64 }
```

### Example 2: Quietly withdrawn

```typescript
state.needs.recognition = 1  // Very low
state.personality.assertiveness = 0.2  // Low

strength = (1 - 1/10) * (1 - 0.2) = 0.9 * 0.8 = 0.72

// Drive included: { name: 'quietly-withdrawn', strength: 0.72 }
```

### Example 3: No drives active

```typescript
state.needs = {
  stimulation: 7,    // All above threshold
  purpose: 6,
  novelty: 5,
  recognition: 8,
  social: 6,
  rest: 7,
  expression: 5,
  autonomy: 6,
}

// No drives computed - all needs are met
```

## Usage in Context Compression

```typescript
// In inner-life-compress.ts
import { computeDrives } from './inner-life-needs';

export function compressForContext(state: FullState): string {
  const parts: string[] = [];
  
  // ... emotions, trust, needs ...
  
  // Drives: top 3 by strength
  const drives = computeDrives(state).slice(0, 3);
  if (drives.length > 0) {
    parts.push(`drives: ${drives.map((d) => d.name).join(', ')}`);
  }
  
  return `[state] ${parts.join(' | ')}`;
}
```

## Exported API

| Function | Purpose |
|----------|---------|
| `satisfyNeed(state, need, amount)` | Increase need value |
| `depleteNeed(state, need, amount)` | Decrease need value |
| `computeDrives(state)` | Compute active drives from unmet needs |

## See Also

- [`inner-life.ts`](inner-life.md) - Inner life engine
- [`inner-life-types.ts`](inner-life-types.md) - Type definitions
- [`inner-life-compress.ts`](inner-life-compress.md) - Compressed context formatter

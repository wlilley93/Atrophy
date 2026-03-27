# src/main/inner-life-types.ts - Inner Life Type Definitions

**Dependencies:** None (pure type definitions)  
**Purpose:** Type definitions, defaults, baselines, and half-lives for inner life v2 system

## Overview

This module defines the complete type system for the inner life v2 emotional/psychological model. It provides interfaces, default values, baselines, and decay rates for all 6 categories: emotions, trust, needs, personality, relationship, and drives.

**Scale conventions:**
- Emotions, Trust, Relationship: 0.0 - 1.0
- Needs: 0 - 10
- Personality: 0.0 - 1.0
- Drive.strength: 0.0 - 1.0

## Interfaces

### Emotions (14-dimensional)

```typescript
export interface Emotions {
  connection: number;      // 0.0-1.0
  curiosity: number;       // 0.0-1.0
  confidence: number;      // 0.0-1.0
  warmth: number;          // 0.0-1.0
  frustration: number;     // 0.0-1.0
  playfulness: number;     // 0.0-1.0
  amusement: number;       // 0.0-1.0
  anticipation: number;    // 0.0-1.0
  satisfaction: number;    // 0.0-1.0
  restlessness: number;    // 0.0-1.0
  tenderness: number;      // 0.0-1.0
  melancholy: number;      // 0.0-1.0
  focus: number;           // 0.0-1.0
  defiance: number;        // 0.0-1.0
}
```

### Trust (6-domain)

```typescript
export interface Trust {
  emotional: number;       // 0.0-1.0
  intellectual: number;    // 0.0-1.0
  creative: number;        // 0.0-1.0
  practical: number;       // 0.0-1.0
  operational: number;     // 0.0-1.0
  personal: number;        // 0.0-1.0
}
```

### Needs (8-dimensional, 0-10 scale)

```typescript
export interface Needs {
  stimulation: number;     // 0-10
  expression: number;      // 0-10
  purpose: number;         // 0-10
  autonomy: number;        // 0-10
  recognition: number;     // 0-10
  novelty: number;         // 0-10
  social: number;          // 0-10
  rest: number;            // 0-10
}
```

**Note:** Needs use a depletion model - they decay toward 0, not toward a baseline.

### Personality (8-trait)

```typescript
export interface Personality {
  assertiveness: number;       // 0.0-1.0
  initiative: number;          // 0.0-1.0
  warmth_default: number;      // 0.0-1.0
  humor_style: number;         // 0.0-1.0
  depth_preference: number;    // 0.0-1.0
  directness: number;          // 0.0-1.0
  patience: number;            // 0.0-1.0
  risk_tolerance: number;      // 0.0-1.0
}
```

### Relationship (6-dimensional)

```typescript
export interface Relationship {
  familiarity: number;         // 0.0-1.0
  rapport: number;             // 0.0-1.0
  reliability: number;         // 0.0-1.0
  boundaries: number;          // 0.0-1.0
  challenge_comfort: number;   // 0.0-1.0
  vulnerability: number;       // 0.0-1.0
}
```

### Drive

```typescript
export interface Drive {
  name: string;        // Drive name (e.g., 'seeking-new-topics')
  strength: number;    // 0.0-1.0
}
```

### FullState

```typescript
export interface FullState {
  version: 2;
  emotions: Emotions;
  trust: Trust;
  needs: Needs;
  personality: Personality;
  relationship: Relationship;
  session_tone: string | null;
  last_updated: string;
}
```

### UserState

```typescript
export interface UserState {
  emotions: Emotions;
  trust: Trust;
  relationship: Relationship;
  session_tone: string | null;
  last_updated: string;
}
```

**Note:** Personality and needs are agent-global, not per-user. Only emotions, trust, and relationship are tracked per-user in group contexts.

## Default Values

### DEFAULT_EMOTIONS

```typescript
export const DEFAULT_EMOTIONS: Emotions = {
  connection: 0.5,
  curiosity: 0.6,
  confidence: 0.5,
  warmth: 0.5,
  frustration: 0.1,
  playfulness: 0.3,
  amusement: 0.2,
  anticipation: 0.4,
  satisfaction: 0.4,
  restlessness: 0.2,
  tenderness: 0.3,
  melancholy: 0.1,
  focus: 0.5,
  defiance: 0.1,
};
```

### EMOTION_BASELINES

```typescript
export const EMOTION_BASELINES: Emotions = { ...DEFAULT_EMOTIONS };
```

**Purpose:** Values that emotions decay toward when no stimulation is applied.

### EMOTION_HALF_LIVES

```typescript
export const EMOTION_HALF_LIVES: Record<keyof Emotions, number> = {
  connection: 2,       // was 8 - stickier, but still needs to breathe
  curiosity: 1,        // was 4 - sparked fast, fades fast
  confidence: 2,       // was 4
  warmth: 1.5,         // was 4
  frustration: 1,      // was 4 - should dissipate quickly
  playfulness: 0.5,    // was 4 - most ephemeral
  amusement: 0.5,      // was 2 - a laugh fades
  anticipation: 1.5,   // was 4
  satisfaction: 3,     // was 6 - lingers but not forever
  restlessness: 1,     // was 3
  tenderness: 3,       // was 6 - halved
  melancholy: 4,       // was 8 - halved
  focus: 1,            // was 2
  defiance: 1,         // was 3
};
```

**Purpose:** Half-lives in hours for exponential decay. After one half-life, the gap between current value and baseline halves.

**Example:** If `curiosity = 0.9` (baseline 0.6), after 1 hour it becomes `0.6 + (0.9 - 0.6) * 0.5 = 0.75`.

### DEFAULT_TRUST

```typescript
export const DEFAULT_TRUST: Trust = {
  emotional: 0.5,
  intellectual: 0.5,
  creative: 0.5,
  practical: 0.5,
  operational: 0.5,
  personal: 0.5,
};
```

### TRUST_HALF_LIVES

```typescript
export const TRUST_HALF_LIVES: Record<keyof Trust, number> = {
  emotional: 12,
  intellectual: 12,
  creative: 12,
  practical: 12,
  operational: 24,
  personal: 24,
};
```

**Note:** Operational and personal trust decay slower (24h) as they're built through repeated reliable actions.

### DEFAULT_NEEDS

```typescript
export const DEFAULT_NEEDS: Needs = {
  stimulation: 5,
  expression: 5,
  purpose: 5,
  autonomy: 5,
  recognition: 5,
  novelty: 5,
  social: 5,
  rest: 5,
};
```

### NEED_DECAY_HOURS

```typescript
export const NEED_DECAY_HOURS: Record<keyof Needs, number> = {
  stimulation: 6,
  expression: 8,
  purpose: 12,
  autonomy: 8,
  recognition: 12,
  novelty: 4,
  social: 6,
  rest: 24,
};
```

**Note:** Needs decay toward 0 (depletion model), not toward baseline.

### DEFAULT_PERSONALITY

```typescript
export const DEFAULT_PERSONALITY: Personality = {
  assertiveness: 0.5,
  initiative: 0.5,
  warmth_default: 0.5,
  humor_style: 0.3,
  depth_preference: 0.5,
  directness: 0.5,
  patience: 0.5,
  risk_tolerance: 0.5,
};
```

**Note:** Personality does NOT decay - it only changes via monthly `evolve` script.

### DEFAULT_RELATIONSHIP

```typescript
export const DEFAULT_RELATIONSHIP: Relationship = {
  familiarity: 0.3,
  rapport: 0.3,
  reliability: 0.5,
  boundaries: 0.5,
  challenge_comfort: 0.3,
  vulnerability: 0.2,
};
```

### RELATIONSHIP_HALF_LIVES

```typescript
export const RELATIONSHIP_HALF_LIVES: Record<keyof Relationship, number> = {
  familiarity: 168,        // 1 week
  rapport: 72,             // 3 days
  reliability: 168,        // 1 week
  boundaries: 336,         // 2 weeks
  challenge_comfort: 120,  // 5 days
  vulnerability: 120,      // 5 days
};
```

**Note:** Relationships decay slowly (days to weeks) as they represent accumulated history.

## Helper Functions

### DEFAULT_USER_STATE

```typescript
export function DEFAULT_USER_STATE(): UserState {
  return {
    emotions: { ...DEFAULT_EMOTIONS },
    trust: { ...DEFAULT_TRUST },
    relationship: { ...DEFAULT_RELATIONSHIP },
    session_tone: null,
    last_updated: new Date().toISOString(),
  };
}
```

**Purpose:** Create fresh UserState with defaults for new users in group contexts.

## Exported API

| Export | Type | Purpose |
|--------|------|---------|
| `Emotions` | interface | 14-dimensional emotional state |
| `Trust` | interface | 6-domain trust model |
| `Needs` | interface | 8-dimensional need state (0-10) |
| `Personality` | interface | 8-trait personality profile |
| `Relationship` | interface | 6-dimensional relationship state |
| `Drive` | interface | Motivational drive |
| `FullState` | interface | Complete inner life state v2 |
| `UserState` | interface | Per-user emotional state slice |
| `DEFAULT_EMOTIONS` | object | Default emotion values |
| `EMOTION_BASELINES` | object | Emotion decay baselines |
| `EMOTION_HALF_LIVES` | object | Emotion decay rates (hours) |
| `DEFAULT_TRUST` | object | Default trust values |
| `TRUST_HALF_LIVES` | object | Trust decay rates (hours) |
| `DEFAULT_NEEDS` | object | Default need values |
| `NEED_DECAY_HOURS` | object | Need decay rates (hours) |
| `DEFAULT_PERSONALITY` | object | Default personality values |
| `DEFAULT_RELATIONSHIP` | object | Default relationship values |
| `RELATIONSHIP_HALF_LIVES` | object | Relationship decay rates (hours) |
| `DEFAULT_USER_STATE()` | function | Create fresh UserState |

## See Also

- [`inner-life.ts`](inner-life.md) - Inner life engine implementation
- [`inner-life-compress.ts`](inner-life-compress.md) - Compressed context formatter
- [`inner-life-needs.ts`](inner-life-needs.md) - Need satisfaction and drive computation

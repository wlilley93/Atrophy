# src/main/inner-life.ts - Emotional State Engine

**Dependencies:** `./config`, `./memory`, `./inner-life-types`  
**Purpose:** Multi-dimensional emotional state with decay, trust, needs, personality, and relationship tracking

## Overview

This module implements the v2 inner life system - a comprehensive emotional state engine with six categories:

1. **Emotions** (14 dimensions): connection, curiosity, confidence, warmth, frustration, playfulness, amusement, anticipation, satisfaction, restlessness, tenderness, melancholy, focus, defiance
2. **Trust** (6 domains): emotional, intellectual, creative, practical, operational, personal
3. **Needs** (8 dimensions): stimulation, expression, purpose, autonomy, recognition, novelty, social, rest
4. **Personality** (8 traits): assertiveness, initiative, warmth_default, humor_style, depth_preference, directness, patience, risk_tolerance
5. **Relationship** (6 dimensions): familiarity, rapport, reliability, boundaries, challenge_comfort, vulnerability
6. **Drives** (future): Reserved for motivational systems

## State Structure

```typescript
interface FullState {
  version: 2;
  emotions: Emotions;      // 14 dimensions, 0.0-1.0
  trust: Trust;            // 6 domains, 0.0-1.0
  needs: Needs;            // 8 dimensions, 0-10
  personality: Personality; // 8 traits, 0.0-1.0
  relationship: Relationship; // 6 dimensions, 0.0-1.0
  session_tone: string | null;
  last_updated: string;
}
```

**Storage:** Persisted to `<agent_dir>/data/.emotional_state.json`

## Default Values

### Emotions (decay toward baselines)

```typescript
const DEFAULT_EMOTIONS = {
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

const EMOTION_BASELINES = { ...DEFAULT_EMOTIONS };  // Same as defaults

const EMOTION_HALF_LIVES = {
  connection: 2,      // hours
  curiosity: 1,
  confidence: 2,
  warmth: 1.5,
  frustration: 1,
  playfulness: 0.5,
  amusement: 0.5,
  anticipation: 1.5,
  satisfaction: 3,
  restlessness: 1,
  tenderness: 3,
  melancholy: 4,
  focus: 1,
  defiance: 1,
};
```

### Trust (decay toward baselines)

```typescript
const DEFAULT_TRUST = {
  emotional: 0.5,
  intellectual: 0.5,
  creative: 0.5,
  practical: 0.5,
  operational: 0.5,
  personal: 0.5,
};

const TRUST_HALF_LIVES = {
  emotional: 12,
  intellectual: 12,
  creative: 12,
  practical: 12,
  operational: 24,
  personal: 24,
};
```

### Needs (decay toward 0 - depletion model)

```typescript
const DEFAULT_NEEDS = {
  stimulation: 5,
  expression: 5,
  purpose: 5,
  autonomy: 5,
  recognition: 5,
  novelty: 5,
  social: 5,
  rest: 5,
};

const NEED_DECAY_HOURS = {
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

### Personality (NO decay - glacial change via evolve.py only)

```typescript
const DEFAULT_PERSONALITY = {
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

**Note:** Personality is seeded from agent manifest on first boot, then only changes via monthly `evolve.py` script.

### Relationship (decay toward baselines)

```typescript
const DEFAULT_RELATIONSHIP = {
  familiarity: 0.3,
  rapport: 0.3,
  reliability: 0.5,
  boundaries: 0.5,
  challenge_comfort: 0.3,
  vulnerability: 0.2,
};

const RELATIONSHIP_HALF_LIVES = {
  familiarity: 168,     // 1 week
  rapport: 72,          // 3 days
  reliability: 168,     // 1 week
  boundaries: 336,      // 2 weeks
  challenge_comfort: 120, // 5 days
  vulnerability: 120,   // 5 days
};
```

## Decay System

```typescript
function applyDecay(state: FullState): FullState {
  const now = Date.now();
  const lastUpdated = new Date(state.last_updated).getTime();
  const hoursElapsed = (now - lastUpdated) / (1000 * 60 * 60);
  if (hoursElapsed < 0.01) return state;

  // Emotions: decay toward EMOTION_BASELINES
  const emotions = { ...state.emotions };
  for (const key of Object.keys(emotions) as (keyof Emotions)[]) {
    const baseline = EMOTION_BASELINES[key];
    const halfLife = EMOTION_HALF_LIVES[key];
    const decay = Math.pow(0.5, hoursElapsed / halfLife);
    const oldValue = emotions[key];
    emotions[key] = baseline + (oldValue - baseline) * decay;
    
    // Log significant decay
    const delta = emotions[key] - oldValue;
    if (Math.abs(delta) > 0.005) {
      try {
        writeStateLog('emotion', key, delta, emotions[key], `decay over ${hoursElapsed.toFixed(1)}h`, 'decay');
      } catch { /* non-fatal */ }
    }
  }

  // Trust: decay toward DEFAULT_TRUST baselines
  const trust = { ...state.trust };
  for (const key of Object.keys(trust) as (keyof Trust)[]) {
    const baseline = DEFAULT_TRUST[key];
    const halfLife = TRUST_HALF_LIVES[key];
    const decay = Math.pow(0.5, hoursElapsed / halfLife);
    const oldValue = trust[key];
    trust[key] = baseline + (oldValue - baseline) * decay;
    
    // Log significant decay
    const delta = trust[key] - oldValue;
    if (Math.abs(delta) > 0.001) {
      try {
        writeTrustLog(key, delta, trust[key], `decay over ${hoursElapsed.toFixed(1)}h`, 'decay');
      } catch { /* non-fatal */ }
    }
  }

  // Needs: decay toward 0 (depletion model)
  const needs = { ...state.needs };
  for (const key of Object.keys(needs) as (keyof Needs)[]) {
    const halfLife = NEED_DECAY_HOURS[key];
    const decay = Math.pow(0.5, hoursElapsed / halfLife);
    needs[key] = needs[key] * decay;
  }

  // Personality: NO decay (glacial)

  // Relationship: decay toward DEFAULT_RELATIONSHIP baselines
  const relationship = { ...state.relationship };
  for (const key of Object.keys(relationship) as (keyof Relationship)[]) {
    const baseline = DEFAULT_RELATIONSHIP[key];
    const halfLife = RELATIONSHIP_HALF_LIVES[key];
    const decay = Math.pow(0.5, hoursElapsed / halfLife);
    relationship[key] = baseline + (relationship[key] - baseline) * decay;
  }

  return {
    ...state,
    emotions,
    trust,
    needs,
    relationship,
  };
}
```

**Decay formula:** `newValue = baseline + (oldValue - baseline) * 0.5^(hoursElapsed / halfLife)`

**Logging:** Significant decay events are logged to `state_log` and `trust_log` tables for trajectory tracking.

## Load/Save with Cache

```typescript
let _stateCache: { state: FullState; ts: number } | null = null;
const STATE_CACHE_TTL_MS = 5_000;

export function loadState(): FullState {
  if (_stateCache && Date.now() - _stateCache.ts < STATE_CACHE_TTL_MS) {
    return _stateCache.state;
  }

  const config = getConfig();
  const filePath = config.EMOTIONAL_STATE_FILE;
  let state: FullState = DEFAULT_FULL_STATE();

  try {
    if (fs.existsSync(filePath)) {
      const raw = JSON.parse(fs.readFileSync(filePath, 'utf-8'));

      // v1 files have no version field - merge with v2 defaults
      const defaults = DEFAULT_FULL_STATE();

      // Seed personality from agent manifest if not in saved state
      let personalityBase = defaults.personality;
      if (!raw.personality) {
        try {
          const manifestPath = `${config.AGENT_DIR}/data/agent.json`;
          if (fs.existsSync(manifestPath)) {
            const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
            if (manifest.personality && typeof manifest.personality === 'object') {
              personalityBase = { ...defaults.personality, ...manifest.personality };
            }
          }
        } catch { /* fall back to generic defaults */ }
      }

      state = {
        version: 2,
        emotions: { ...defaults.emotions, ...raw.emotions },
        trust: { ...defaults.trust, ...raw.trust },
        needs: { ...defaults.needs, ...raw.needs },
        personality: { ...personalityBase, ...raw.personality },
        relationship: { ...defaults.relationship, ...raw.relationship },
        session_tone: raw.session_tone || null,
        last_updated: raw.last_updated || new Date().toISOString(),
      };
    } else {
      // No state file yet - seed personality from agent manifest
      try {
        const manifestPath = `${config.AGENT_DIR}/data/agent.json`;
        if (fs.existsSync(manifestPath)) {
          const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
          if (manifest.personality && typeof manifest.personality === 'object') {
            state = { ...state, personality: { ...state.personality, ...manifest.personality } };
          }
        }
      } catch { /* use generic defaults */ }
    }
  } catch { /* use defaults */ }

  state = applyDecay(state);
  _stateCache = { state, ts: Date.now() };
  return state;
}

export function saveState(state: FullState): void {
  const config = getConfig();
  state.last_updated = new Date().toISOString();
  try {
    fs.writeFileSync(config.EMOTIONAL_STATE_FILE, JSON.stringify(state, null, 2));
  } catch { /* silent */ }
  _stateCache = { state, ts: Date.now() };
}

export function invalidateStateCache(): void {
  _stateCache = null;
}
```

**Cache TTL:** 5 seconds to avoid redundant file reads within a single turn.

**v1 compatibility:** Merges v1 state files (no version field) with v2 defaults, preserving existing emotion/trust values while adding new categories.

**Personality seeding:** On first boot or v1 migration, personality is seeded from agent manifest.

## Update Functions

### updateEmotions

```typescript
export function updateEmotions(state: FullState, deltas: Partial<Emotions>): FullState {
  const emotions = { ...state.emotions };
  for (const [key, delta] of Object.entries(deltas) as [keyof Emotions, number][]) {
    if (key in emotions) {
      emotions[key] = Math.round(clamp(emotions[key] + delta) * 1000) / 1000;
    }
  }
  const updated = { ...state, emotions };
  saveState(updated);
  return updated;
}
```

### updateTrust

```typescript
export function updateTrust(
  state: FullState,
  domain: keyof Trust,
  delta: number,
  reason = '',
  source = 'unknown',
): FullState {
  // Max +/-0.05 per call
  const clamped = clamp(delta, -0.05, 0.05);
  const trust = { ...state.trust };
  trust[domain] = Math.round(clamp(trust[domain] + clamped) * 1000) / 1000;
  const updated = { ...state, trust };
  saveState(updated);
  try {
    writeTrustLog(domain, clamped, trust[domain], reason, source);
  } catch (err) {
    console.warn(`[inner-life] trust_log write failed for ${domain}: ${err}`);
  }
  return updated;
}
```

**Clamping:** Trust changes limited to ±0.05 per call to prevent wild swings.

### updateRelationship

```typescript
export function updateRelationship(
  state: FullState,
  dimension: keyof Relationship,
  delta: number,
): FullState {
  const relationship = { ...state.relationship };
  relationship[dimension] = Math.round(clamp(relationship[dimension] + delta) * 1000) / 1000;
  const updated = { ...state, relationship };
  saveState(updated);
  return updated;
}
```

### updateNeeds

```typescript
export function updateNeeds(state: FullState, deltas: Partial<Needs>): FullState {
  const needs = { ...state.needs };
  for (const [key, delta] of Object.entries(deltas) as [keyof Needs, number][]) {
    if (key in needs) {
      needs[key] = Math.round(clamp(needs[key] + delta, 0, 10) * 1000) / 1000;
    }
  }
  const updated = { ...state, needs };
  saveState(updated);
  return updated;
}
```

**Range:** Needs are 0-10 (not 0-1) for finer granularity.

## Trust Reconciliation

```typescript
export function reconcileTrustFromDb(): void {
  try {
    const dbTrust = getLatestTrustValues();
    if (!Object.keys(dbTrust).length) return;

    const state = loadState();
    let changed = false;

    for (const [domain, dbValue] of Object.entries(dbTrust)) {
      const currentStateValue = state.trust[domain as keyof Trust];
      // If DB shows higher earned trust than decayed state, use DB value
      if (dbValue > currentStateValue) {
        state.trust[domain as keyof Trust] = dbValue;
        changed = true;
      }
    }

    if (changed) {
      saveState(state);
    }
  } catch { /* non-fatal */ }
}
```

**Purpose:** Recover trust values that may have been lost to decay. Called on session start.

**Rationale:** Trust earned should not be silently eroded by decay - the DB audit trail is the source of truth.

## Emotion Labels

```typescript
function emotionLabel(name: string, value: number): string {
  const labels: Record<string, [number, string][]> = {
    connection: [
      [0.85, 'deeply present'],
      [0.7, 'present, engaged'],
      [0.5, 'steady'],
      [0.3, 'distant'],
      [0.0, 'withdrawn'],
    ],
    curiosity: [
      [0.8, 'something caught your attention'],
      [0.6, 'curious'],
      [0.4, 'neutral'],
      [0.2, 'flat'],
      [0.0, 'disengaged'],
    ],
    // ... more emotions
  };

  const thresholds = labels[name] || [[0, name]];
  for (const [threshold, label] of thresholds) {
    if (value >= threshold) return label;
  }
  return thresholds[thresholds.length - 1][1];
}
```

**Purpose:** Convert numeric emotion values to human-readable labels for context injection.

## User State (Group Mode)

```typescript
interface UserState {
  emotions: Emotions;
  trust: Trust;
  needs: Needs;
  relationship: Relationship;
  last_updated: string;
}

const _userStateCache = new Map<string, { state: UserState; ts: number }>();

export function loadUserState(userId: string): UserState {
  const cacheKey = sanitizeUserId(userId);
  const cached = _userStateCache.get(cacheKey);
  if (cached && Date.now() - cached.ts < STATE_CACHE_TTL_MS) {
    return cached.state;
  }

  const config = getConfig();
  const filePath = path.join(
    path.dirname(config.EMOTIONAL_STATE_FILE),
    `.emotional_state.${cacheKey}.json`,
  );

  let state: UserState = DEFAULT_USER_STATE();

  try {
    if (fs.existsSync(filePath)) {
      const raw = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      const defaults = DEFAULT_USER_STATE();
      state = {
        ...defaults,
        ...raw,
        emotions: { ...defaults.emotions, ...raw.emotions },
        trust: { ...defaults.trust, ...raw.trust },
        needs: { ...defaults.needs, ...raw.needs },
        relationship: { ...defaults.relationship, ...raw.relationship },
      };
    }
  } catch { /* use defaults */ }

  state = applyDecay(state);
  _userStateCache.set(cacheKey, { state, ts: Date.now() });
  return state;
}

export function saveUserState(userId: string, state: UserState): void {
  const config = getConfig();
  const cacheKey = sanitizeUserId(userId);
  state.last_updated = new Date().toISOString();
  const filePath = path.join(
    path.dirname(config.EMOTIONAL_STATE_FILE),
    `.emotional_state.${cacheKey}.json`,
  );
  try {
    fs.writeFileSync(filePath, JSON.stringify(state, null, 2));
  } catch { /* silent */ }
  _userStateCache.set(cacheKey, { state, ts: Date.now() });
}
```

**Purpose:** Per-user emotional state for group chat contexts. Each user has separate emotions, trust, needs, and relationship dimensions.

**File naming:** `.emotional_state.<userId>.json` where userId is sanitized to alphanumeric + underscores.

## Signal Application (Group Mode)

```typescript
export function applySignalsToUserState(
  userState: UserState,
  agentState: FullState,
  signals: Record<string, number>,
): { userState: UserState; agentState: FullState; needsChanged: boolean } {
  let needsChanged = false;

  // Apply trust signals
  for (const [key, val] of Object.entries(signals)) {
    if (key.startsWith('_trust_')) {
      const domain = key.replace('_trust_', '') as keyof Trust;
      userState.trust[domain] = clamp(userState.trust[domain] + val);
    } else if (key.startsWith('_need_')) {
      const need = key.replace('_need_', '') as keyof Needs;
      agentState.needs[need] = clamp(agentState.needs[need] + val, 0, 10);
      needsChanged = true;
    } else if (key.startsWith('_rel_')) {
      const dim = key.replace('_rel_', '') as keyof Relationship;
      userState.relationship[dim] = clamp(userState.relationship[dim] + val);
    } else if (key in userState.emotions) {
      userState.emotions[key as keyof Emotions] += val;
    }
  }

  return { userState, agentState, needsChanged };
}
```

**Purpose:** Apply emotional signals from user message to per-user state in group mode.

## Exported API Summary

| Function | Purpose |
|----------|---------|
| `loadState()` | Load full emotional state with decay |
| `saveState(state)` | Save emotional state to disk |
| `invalidateStateCache()` | Invalidate load cache |
| `updateEmotions(state, deltas)` | Apply emotion deltas |
| `updateTrust(state, domain, delta, reason, source)` | Apply trust delta with logging |
| `updateRelationship(state, dimension, delta)` | Apply relationship delta |
| `updateNeeds(state, deltas)` | Apply need deltas |
| `reconcileTrustFromDb()` | Recover trust from DB audit trail |
| `loadUserState(userId)` | Load per-user state (group mode) |
| `saveUserState(userId, state)` | Save per-user state |
| `applySignalsToUserState(userState, agentState, signals)` | Apply signals in group mode |
| `formatForContext(state)` | Format state for context injection |
| `formatUserStateForContext(userId, state)` | Format per-user state for context |
| `compressForContext(state, opts)` | Compressed state for token efficiency |

## See Also

- `src/main/inner-life-types.ts` - Type definitions and defaults
- `src/main/inner-life-compress.ts` - State compression for context
- `src/main/inner-life-needs.ts` - Need satisfaction functions
- `src/main/memory.ts` - Trust log and state log database functions

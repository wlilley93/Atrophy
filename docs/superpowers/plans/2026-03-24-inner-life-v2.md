# Inner Life v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the emotional architecture from 10 to ~50 dimensions across 6 categories (emotions, trust, needs, personality, relationship, drives), with compressed context injection and distributed emotional embeddings.

**Architecture:** Three layers - distributed emotional vectors on every memory (Layer 1), reconciled explicit snapshot with ~50 dimensions (Layer 2), compressed delta-based context injection at ~50-80 tokens (Layer 3). Needs system drives behavior like The Sims. Personality traits shift via monthly evolve.py.

**Tech Stack:** TypeScript (Electron main process), Python (scripts/core), better-sqlite3, Float32Array for vectors.

**Spec:** `docs/specs/2026-03-24-inner-life-v2-design.md`

---

## File Structure

### New files
- `src/main/inner-life-types.ts` - All type definitions for v2 state (Emotions, Trust, Needs, Personality, Relationship, FullState, drives)
- `src/main/inner-life-needs.ts` - Needs system: decay, satisfaction, drive computation
- `src/main/inner-life-compress.ts` - Compressed context injection (delta-based formatting)
- `src/main/__tests__/inner-life-needs.test.ts` - Tests for needs system
- `src/main/__tests__/inner-life-compress.test.ts` - Tests for compression

### Modified files
- `src/main/inner-life.ts` (318 lines) - Expand to v2 state format, new dimensions, migration
- `src/main/memory.ts` (1303 lines) - Add state_log, need_events, personality_log tables + functions
- `src/main/agency.ts` (428 lines) - Expand signal detection for needs/relationship/personality
- `src/main/inference.ts` - Switch to compressed context injection
- `src/main/session.ts` (114 lines) - Initialize needs on session start
- `db/schema.sql` (233 lines) - Add new tables + columns
- `core/inner_life.py` (328 lines) - Python port of v2 state
- `core/memory.py` (1095 lines) - Python port of new tables
- `core/agency.py` (374 lines) - Python port of expanded signals
- `agents/*/data/agent.json` - Add personality defaults per agent
- `scripts/agents/shared/heartbeat.py` - Factor in needs/drives for severity
- `scripts/agents/shared/sleep_cycle.py` - Aggregate distributed state, reconcile snapshot
- `scripts/agents/shared/introspect.py` - Include emotional arc in journal
- `scripts/agents/shared/evolve.py` - Personality trait adjustment

### Test files
- `src/main/__tests__/inner-life.test.ts` (216 lines) - Expand for v2
- `src/main/__tests__/agency.test.ts` (315 lines) - Expand for new signals

---

## Phase 1: Expand State Format

### Task 1: Define v2 types

**Files:**
- Create: `src/main/inner-life-types.ts`
- Test: `src/main/__tests__/inner-life.test.ts`

- [ ] **Step 1: Write failing test for v2 state structure**

```typescript
// In inner-life.test.ts, add:
import { DEFAULT_FULL_STATE, type FullState } from '../inner-life-types';

describe('v2 state structure', () => {
  it('has all 6 categories', () => {
    const state = DEFAULT_FULL_STATE();
    expect(state.emotions).toBeDefined();
    expect(state.trust).toBeDefined();
    expect(state.needs).toBeDefined();
    expect(state.personality).toBeDefined();
    expect(state.relationship).toBeDefined();
    expect(state.version).toBe(2);
  });

  it('has 14 emotion dimensions', () => {
    const state = DEFAULT_FULL_STATE();
    expect(Object.keys(state.emotions)).toHaveLength(14);
  });

  it('has 6 trust domains', () => {
    const state = DEFAULT_FULL_STATE();
    expect(Object.keys(state.trust)).toHaveLength(6);
  });

  it('has 8 needs', () => {
    const state = DEFAULT_FULL_STATE();
    expect(Object.keys(state.needs)).toHaveLength(8);
  });

  it('has 8 personality traits', () => {
    const state = DEFAULT_FULL_STATE();
    expect(Object.keys(state.personality)).toHaveLength(8);
  });

  it('has 6 relationship dimensions', () => {
    const state = DEFAULT_FULL_STATE();
    expect(Object.keys(state.relationship)).toHaveLength(6);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/main/__tests__/inner-life.test.ts --reporter=verbose 2>&1 | tail -20`
Expected: FAIL - cannot resolve `inner-life-types`

- [ ] **Step 3: Create inner-life-types.ts with all interfaces and defaults**

```typescript
// src/main/inner-life-types.ts

// ── Emotions (14 dimensions, fast decay 2-8h) ──

export interface Emotions {
  connection: number;
  curiosity: number;
  confidence: number;
  warmth: number;
  frustration: number;
  playfulness: number;
  amusement: number;
  anticipation: number;
  satisfaction: number;
  restlessness: number;
  tenderness: number;
  melancholy: number;
  focus: number;
  defiance: number;
}

export const DEFAULT_EMOTIONS: Emotions = {
  connection: 0.5,
  curiosity: 0.6,
  confidence: 0.5,
  warmth: 0.5,
  frustration: 0.1,
  playfulness: 0.3,
  amusement: 0.2,
  anticipation: 0.3,
  satisfaction: 0.4,
  restlessness: 0.2,
  tenderness: 0.3,
  melancholy: 0.1,
  focus: 0.4,
  defiance: 0.1,
};

export const EMOTION_BASELINES: Emotions = { ...DEFAULT_EMOTIONS };

export const EMOTION_HALF_LIVES: Record<keyof Emotions, number> = {
  connection: 8,
  curiosity: 4,
  confidence: 4,
  warmth: 4,
  frustration: 4,
  playfulness: 4,
  amusement: 2,
  anticipation: 4,
  satisfaction: 6,
  restlessness: 3,
  tenderness: 6,
  melancholy: 8,
  focus: 2,
  defiance: 3,
};

// ── Trust (6 domains, slow decay 12-24h) ──

export interface Trust {
  emotional: number;
  intellectual: number;
  creative: number;
  practical: number;
  operational: number;
  personal: number;
}

export const DEFAULT_TRUST: Trust = {
  emotional: 0.5,
  intellectual: 0.5,
  creative: 0.5,
  practical: 0.5,
  operational: 0.5,
  personal: 0.3,
};

export const TRUST_HALF_LIVES: Record<keyof Trust, number> = {
  emotional: 12,
  intellectual: 12,
  creative: 12,
  practical: 12,
  operational: 24,
  personal: 24,
};

// ── Needs (8 dimensions, 0-10 scale, decay toward 0) ──

export interface Needs {
  stimulation: number;
  expression: number;
  purpose: number;
  autonomy: number;
  recognition: number;
  novelty: number;
  social: number;
  rest: number;
}

export const DEFAULT_NEEDS: Needs = {
  stimulation: 5,
  expression: 5,
  purpose: 5,
  autonomy: 5,
  recognition: 5,
  novelty: 5,
  social: 5,
  rest: 8,
};

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

// ── Personality (8 traits, glacial shift via evolve.py) ──

export interface Personality {
  assertiveness: number;
  initiative: number;
  warmth_default: number;
  humor_style: number;
  depth_preference: number;
  directness: number;
  patience: number;
  risk_tolerance: number;
}

export const DEFAULT_PERSONALITY: Personality = {
  assertiveness: 0.5,
  initiative: 0.5,
  warmth_default: 0.5,
  humor_style: 0.5,
  depth_preference: 0.5,
  directness: 0.5,
  patience: 0.5,
  risk_tolerance: 0.5,
};

// ── Relationship (6 dimensions, slow build over days) ──

export interface Relationship {
  familiarity: number;
  rapport: number;
  reliability: number;
  boundaries: number;
  challenge_comfort: number;
  vulnerability: number;
}

export const DEFAULT_RELATIONSHIP: Relationship = {
  familiarity: 0.2,
  rapport: 0.2,
  reliability: 0.3,
  boundaries: 0.2,
  challenge_comfort: 0.2,
  vulnerability: 0.1,
};

export const RELATIONSHIP_HALF_LIVES: Record<keyof Relationship, number> = {
  familiarity: 168,   // 1 week
  rapport: 72,        // 3 days
  reliability: 168,   // 1 week
  boundaries: 336,    // 2 weeks
  challenge_comfort: 120, // 5 days
  vulnerability: 120, // 5 days
};

// ── Drives (computed, not stored) ──

export interface Drive {
  name: string;
  strength: number; // 0-1
}

// ── Full state ──

export interface FullState {
  version: number;
  emotions: Emotions;
  trust: Trust;
  needs: Needs;
  personality: Personality;
  relationship: Relationship;
  session_tone: string | null;
  last_updated: string;
}

export function DEFAULT_FULL_STATE(): FullState {
  return {
    version: 2,
    emotions: { ...DEFAULT_EMOTIONS },
    trust: { ...DEFAULT_TRUST },
    needs: { ...DEFAULT_NEEDS },
    personality: { ...DEFAULT_PERSONALITY },
    relationship: { ...DEFAULT_RELATIONSHIP },
    session_tone: null,
    last_updated: new Date().toISOString(),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/main/__tests__/inner-life.test.ts --reporter=verbose 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/inner-life-types.ts src/main/__tests__/inner-life.test.ts
git commit -m "feat: define v2 inner life types - 14 emotions, 6 trust, 8 needs, 8 personality, 6 relationship"
```

---

### Task 2: Migrate inner-life.ts to v2 state

**Files:**
- Modify: `src/main/inner-life.ts` (lines 14-67 types/defaults, 132-198 load/save, 223-257 update, 295-318 format)
- Test: `src/main/__tests__/inner-life.test.ts`

- [ ] **Step 1: Write failing test for v1 -> v2 migration**

```typescript
describe('v1 to v2 migration', () => {
  it('upgrades v1 state to v2 on load', () => {
    // Write a v1 state file (no version, no needs/personality/relationship)
    const v1 = {
      emotions: { connection: 0.8, curiosity: 0.7, confidence: 0.5, warmth: 0.6, frustration: 0.1, playfulness: 0.3 },
      trust: { emotional: 0.6, intellectual: 0.55, creative: 0.5, practical: 0.5 },
      session_tone: null,
      last_updated: new Date().toISOString(),
    };
    fs.writeFileSync(testStatePath, JSON.stringify(v1));

    const state = loadState();
    expect(state.version).toBe(2);
    // Existing values preserved
    expect(state.emotions.connection).toBeCloseTo(0.8, 1);
    // New emotions get defaults
    expect(state.emotions.amusement).toBeDefined();
    // New trust domains get defaults
    expect(state.trust.operational).toBeDefined();
    // New categories exist
    expect(state.needs).toBeDefined();
    expect(state.personality).toBeDefined();
    expect(state.relationship).toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/main/__tests__/inner-life.test.ts --reporter=verbose 2>&1 | tail -20`
Expected: FAIL - state.version undefined, state.needs undefined

- [ ] **Step 3: Refactor inner-life.ts to use v2 types**

Replace the local type definitions (lines 14-67) with imports from `inner-life-types.ts`. Update `loadState()` to detect v1 files and merge with v2 defaults. Update `saveState()` to always write version 2. Update `applyDecay()` to handle all 6 categories with their respective half-lives. Keep `updateEmotions()` and `updateTrust()` working but expand for new dimensions.

Key changes in `loadState()`:
```typescript
import {
  type FullState, type Emotions, type Trust, type Needs,
  type Personality, type Relationship,
  DEFAULT_FULL_STATE, DEFAULT_EMOTIONS, DEFAULT_TRUST,
  DEFAULT_NEEDS, DEFAULT_PERSONALITY, DEFAULT_RELATIONSHIP,
  EMOTION_HALF_LIVES, TRUST_HALF_LIVES, NEED_DECAY_HOURS,
  RELATIONSHIP_HALF_LIVES, EMOTION_BASELINES,
} from './inner-life-types';

export function loadState(): FullState {
  // ... existing cache check ...

  let state = DEFAULT_FULL_STATE();

  try {
    if (fs.existsSync(filePath)) {
      const raw = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      state = {
        version: 2,
        emotions: { ...DEFAULT_EMOTIONS, ...raw.emotions },
        trust: { ...DEFAULT_TRUST, ...raw.trust },
        needs: { ...DEFAULT_NEEDS, ...raw.needs },
        personality: { ...DEFAULT_PERSONALITY, ...raw.personality },
        relationship: { ...DEFAULT_RELATIONSHIP, ...raw.relationship },
        session_tone: raw.session_tone || null,
        last_updated: raw.last_updated || new Date().toISOString(),
      };
    }
  } catch { /* use defaults */ }

  state = applyDecay(state);
  _stateCache = { state, ts: Date.now() };
  return state;
}
```

Key changes in `applyDecay()` - add needs decay (toward 0, not baseline) and relationship decay:
```typescript
// Needs decay toward 0 (unmet)
const needs = { ...state.needs };
for (const key of Object.keys(needs) as (keyof Needs)[]) {
  const decayHours = NEED_DECAY_HOURS[key];
  const decay = Math.pow(0.5, hoursElapsed / decayHours);
  needs[key] = Math.max(0, needs[key] * decay);
}

// Relationship decays toward baseline (slow)
const relationship = { ...state.relationship };
for (const key of Object.keys(relationship) as (keyof Relationship)[]) {
  const baseline = DEFAULT_RELATIONSHIP[key];
  const halfLife = RELATIONSHIP_HALF_LIVES[key];
  const decay = Math.pow(0.5, hoursElapsed / halfLife);
  relationship[key] = baseline + (relationship[key] - baseline) * decay;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/main/__tests__/inner-life.test.ts --reporter=verbose 2>&1 | tail -30`
Expected: All existing tests pass + new migration test passes

- [ ] **Step 5: Commit**

```bash
git add src/main/inner-life.ts src/main/__tests__/inner-life.test.ts
git commit -m "feat: migrate inner-life.ts to v2 state format with needs, personality, relationship"
```

---

### Task 3: Add needs system

**Files:**
- Create: `src/main/inner-life-needs.ts`
- Create: `src/main/__tests__/inner-life-needs.test.ts`

- [ ] **Step 1: Write failing tests for needs**

```typescript
import { satisfyNeed, computeDrives } from '../inner-life-needs';
import { DEFAULT_FULL_STATE } from '../inner-life-types';

describe('needs system', () => {
  it('satisfies a need by increasing its value', () => {
    const state = DEFAULT_FULL_STATE();
    state.needs.stimulation = 2; // low
    const updated = satisfyNeed(state, 'stimulation', 3);
    expect(updated.needs.stimulation).toBe(5);
  });

  it('clamps needs to 0-10', () => {
    const state = DEFAULT_FULL_STATE();
    state.needs.stimulation = 9;
    const updated = satisfyNeed(state, 'stimulation', 5);
    expect(updated.needs.stimulation).toBe(10);
  });

  it('computes drives from low needs + personality', () => {
    const state = DEFAULT_FULL_STATE();
    state.needs.stimulation = 1; // very low
    state.personality.initiative = 0.8; // high initiative
    state.emotions.curiosity = 0.9;
    const drives = computeDrives(state);
    expect(drives.length).toBeGreaterThan(0);
    expect(drives.some(d => d.name === 'seeking-new-topics')).toBe(true);
  });

  it('returns no drives when all needs are met', () => {
    const state = DEFAULT_FULL_STATE();
    // All needs at 8+
    for (const key of Object.keys(state.needs)) {
      (state.needs as Record<string, number>)[key] = 9;
    }
    const drives = computeDrives(state);
    expect(drives.length).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/main/__tests__/inner-life-needs.test.ts --reporter=verbose 2>&1 | tail -20`
Expected: FAIL - cannot resolve module

- [ ] **Step 3: Implement needs system**

```typescript
// src/main/inner-life-needs.ts
import { type FullState, type Needs, type Drive } from './inner-life-types';
import { saveState } from './inner-life';

export function satisfyNeed(state: FullState, need: keyof Needs, amount: number): FullState {
  const needs = { ...state.needs };
  needs[need] = Math.min(10, Math.max(0, needs[need] + amount));
  const updated = { ...state, needs };
  saveState(updated);
  return updated;
}

export function depleteNeed(state: FullState, need: keyof Needs, amount: number): FullState {
  const needs = { ...state.needs };
  needs[need] = Math.min(10, Math.max(0, needs[need] - amount));
  const updated = { ...state, needs };
  saveState(updated);
  return updated;
}

// Drive computation rules - emergent from needs + personality + emotions
const DRIVE_RULES: Array<{
  name: string;
  check: (s: FullState) => number; // returns strength 0-1
}> = [
  {
    name: 'seeking-new-topics',
    check: (s) => {
      if (s.needs.stimulation > 3) return 0;
      return (1 - s.needs.stimulation / 10) * s.emotions.curiosity;
    },
  },
  {
    name: 'offering-to-help',
    check: (s) => {
      if (s.needs.purpose > 4) return 0;
      return (1 - s.needs.purpose / 10) * s.personality.initiative;
    },
  },
  {
    name: 'changing-the-subject',
    check: (s) => {
      if (s.needs.novelty > 3) return 0;
      return (1 - s.needs.novelty / 10) * s.emotions.restlessness;
    },
  },
  {
    name: 'quietly-withdrawn',
    check: (s) => {
      if (s.needs.recognition > 3) return 0;
      return (1 - s.needs.recognition / 10) * (1 - s.personality.assertiveness);
    },
  },
  {
    name: 'reaching-out-unprompted',
    check: (s) => {
      if (s.needs.social > 4) return 0;
      return (1 - s.needs.social / 10) * s.personality.warmth_default;
    },
  },
  {
    name: 'conserving-energy',
    check: (s) => {
      if (s.needs.rest > 3) return 0;
      return (1 - s.needs.rest / 10);
    },
  },
  {
    name: 'wanting-to-create',
    check: (s) => {
      if (s.needs.expression > 4) return 0;
      return (1 - s.needs.expression / 10) * s.trust.creative;
    },
  },
  {
    name: 'acting-independently',
    check: (s) => {
      if (s.needs.autonomy > 4) return 0;
      return (1 - s.needs.autonomy / 10) * s.trust.operational;
    },
  },
];

export function computeDrives(state: FullState): Drive[] {
  const drives: Drive[] = [];
  for (const rule of DRIVE_RULES) {
    const strength = rule.check(state);
    if (strength > 0.3) { // threshold for active drive
      drives.push({ name: rule.name, strength: Math.round(strength * 100) / 100 });
    }
  }
  return drives.sort((a, b) => b.strength - a.strength);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/main/__tests__/inner-life-needs.test.ts --reporter=verbose 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/inner-life-needs.ts src/main/__tests__/inner-life-needs.test.ts
git commit -m "feat: needs system with decay, satisfaction, and drive computation"
```

---

### Task 4: Add personality defaults to agent.json

**Files:**
- Modify: `agents/companion/data/agent.json`
- Modify: `agents/xan/data/agent.json`
- Modify: `agents/general_montgomery/data/agent.json`
- Modify: `agents/mirror/data/agent.json`

- [ ] **Step 1: Add personality object to each agent.json**

Companion - warm, patient, deep:
```json
"personality": {
  "assertiveness": 0.4,
  "initiative": 0.5,
  "warmth_default": 0.8,
  "humor_style": 0.6,
  "depth_preference": 0.7,
  "directness": 0.5,
  "patience": 0.7,
  "risk_tolerance": 0.4
}
```

Xan - assertive, direct, proactive:
```json
"personality": {
  "assertiveness": 0.8,
  "initiative": 0.9,
  "warmth_default": 0.3,
  "humor_style": 0.2,
  "depth_preference": 0.4,
  "directness": 0.9,
  "patience": 0.3,
  "risk_tolerance": 0.6
}
```

Montgomery - stoic, direct, measured:
```json
"personality": {
  "assertiveness": 0.7,
  "initiative": 0.6,
  "warmth_default": 0.2,
  "humor_style": 0.1,
  "depth_preference": 0.5,
  "directness": 0.8,
  "patience": 0.5,
  "risk_tolerance": 0.4
}
```

Mirror - reflective, patient, deep:
```json
"personality": {
  "assertiveness": 0.3,
  "initiative": 0.3,
  "warmth_default": 0.5,
  "humor_style": 0.4,
  "depth_preference": 0.9,
  "directness": 0.6,
  "patience": 0.8,
  "risk_tolerance": 0.3
}
```

- [ ] **Step 2: Update loadState() to read personality from agent.json on first load**

In `inner-life.ts`, when loading state and personality is at defaults, check the agent manifest for preset personality values and use those instead.

- [ ] **Step 3: Commit**

```bash
git add agents/*/data/agent.json src/main/inner-life.ts
git commit -m "feat: personality defaults per agent - companion warm, xan assertive, montgomery stoic, mirror reflective"
```

---

### Task 5: Update SQLite schema

**Files:**
- Modify: `db/schema.sql` (line 172+)
- Modify: `src/main/memory.ts` (migration function + new query functions)

- [ ] **Step 1: Add new tables to schema.sql**

After the existing trust_log table, add:

```sql
-- Expanded state log (all dimension changes, not just trust)
CREATE TABLE IF NOT EXISTS state_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    category    TEXT NOT NULL CHECK(category IN (
        'emotion', 'trust', 'need', 'personality', 'relationship'
    )),
    dimension   TEXT NOT NULL,
    delta       REAL NOT NULL,
    new_value   REAL NOT NULL,
    reason      TEXT,
    source      TEXT DEFAULT 'unknown'
);
CREATE INDEX IF NOT EXISTS idx_state_log_cat ON state_log(category);
CREATE INDEX IF NOT EXISTS idx_state_log_dim ON state_log(dimension);
CREATE INDEX IF NOT EXISTS idx_state_log_ts ON state_log(timestamp);

-- Need satisfaction events
CREATE TABLE IF NOT EXISTS need_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    need        TEXT NOT NULL,
    delta       REAL NOT NULL,
    trigger_desc TEXT,
    session_id  INTEGER REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_need_events_need ON need_events(need);

-- Personality evolution log
CREATE TABLE IF NOT EXISTS personality_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    trait       TEXT NOT NULL,
    old_value   REAL NOT NULL,
    new_value   REAL NOT NULL,
    reason      TEXT,
    source      TEXT DEFAULT 'evolve'
);

-- Emotional vectors on turns and observations
-- (added via ALTER TABLE in migration, not here)
```

- [ ] **Step 2: Add migration logic in memory.ts**

In the `_migrate()` function, add checks for the new tables (same pattern as existing trust_log migration). Also add `ALTER TABLE turns ADD COLUMN emotional_vector BLOB` and same for observations.

- [ ] **Step 3: Add new query functions in memory.ts**

```typescript
export function writeStateLog(
  category: string, dimension: string, delta: number,
  newValue: number, reason?: string, source?: string
): void { ... }

export function writeNeedEvent(
  need: string, delta: number, trigger?: string, sessionId?: number
): void { ... }

export function writePersonalityLog(
  trait: string, oldValue: number, newValue: number,
  reason?: string, source?: string
): void { ... }

export function getStateHistory(
  category?: string, dimension?: string, limit?: number
): StateLogEntry[] { ... }
```

- [ ] **Step 4: Run existing tests to ensure no regression**

Run: `npx vitest run --reporter=verbose 2>&1 | tail -30`
Expected: All existing tests pass

- [ ] **Step 5: Commit**

```bash
git add db/schema.sql src/main/memory.ts
git commit -m "feat: v2 schema - state_log, need_events, personality_log tables"
```

---

## Phase 2: Compressed Context Injection

### Task 6: Build compressed formatter

**Files:**
- Create: `src/main/inner-life-compress.ts`
- Create: `src/main/__tests__/inner-life-compress.test.ts`

- [ ] **Step 1: Write failing tests for compression**

```typescript
import { compressForContext } from '../inner-life-compress';
import { DEFAULT_FULL_STATE } from '../inner-life-types';

describe('compressed context injection', () => {
  it('returns minimal output when all values are baseline', () => {
    const state = DEFAULT_FULL_STATE();
    const result = compressForContext(state);
    expect(result).toContain('[state: baseline');
    expect(result.length).toBeLessThan(50);
  });

  it('only includes emotions that deviate from baseline', () => {
    const state = DEFAULT_FULL_STATE();
    state.emotions.frustration = 0.6; // way above 0.1 baseline
    state.emotions.warmth = 0.9; // above 0.5 baseline
    const result = compressForContext(state);
    expect(result).toContain('frust');
    expect(result).toContain('wrm');
    // Should NOT include connection (at baseline 0.5)
    expect(result).not.toContain('conn:0.5');
  });

  it('includes unmet needs (below 3)', () => {
    const state = DEFAULT_FULL_STATE();
    state.needs.novelty = 1;
    state.needs.purpose = 2;
    const result = compressForContext(state);
    expect(result).toContain('nov:1');
    expect(result).toContain('purp:2');
  });

  it('includes active drives', () => {
    const state = DEFAULT_FULL_STATE();
    state.needs.stimulation = 1;
    state.emotions.curiosity = 0.9;
    const result = compressForContext(state);
    expect(result).toContain('seeking-new-topics');
  });

  it('includes full state on session start', () => {
    const state = DEFAULT_FULL_STATE();
    state.emotions.warmth = 0.9;
    const result = compressForContext(state, { sessionStart: true });
    expect(result).toContain('personality');
    expect(result).toContain('relationship');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement compressed formatter**

```typescript
// src/main/inner-life-compress.ts
import {
  type FullState, EMOTION_BASELINES, DEFAULT_NEEDS,
} from './inner-life-types';
import { computeDrives } from './inner-life-needs';

const EMOTION_ABBREVS: Record<string, string> = {
  connection: 'conn', curiosity: 'cur', confidence: 'conf',
  warmth: 'wrm', frustration: 'frust', playfulness: 'play',
  amusement: 'amus', anticipation: 'antic', satisfaction: 'sat',
  restlessness: 'rest', tenderness: 'tend', melancholy: 'mel',
  focus: 'foc', defiance: 'def',
};

const NEED_ABBREVS: Record<string, string> = {
  stimulation: 'stim', expression: 'expr', purpose: 'purp',
  autonomy: 'auto', recognition: 'recog', novelty: 'nov',
  social: 'soc', rest: 'rest_n',
};

interface CompressOptions {
  sessionStart?: boolean;
}

export function compressForContext(
  state: FullState,
  opts: CompressOptions = {},
): string {
  const parts: string[] = [];

  // Emotions: only include deviations > 0.1 from baseline
  const emotionParts: string[] = [];
  for (const [key, value] of Object.entries(state.emotions)) {
    const baseline = (EMOTION_BASELINES as Record<string, number>)[key] ?? 0.5;
    if (Math.abs(value - baseline) > 0.1) {
      const abbrev = EMOTION_ABBREVS[key] || key.slice(0, 4);
      emotionParts.push(`${abbrev}:${value.toFixed(2)}`);
    }
  }

  // Trust: only include deviations > 0.05 from 0.5
  const trustParts: string[] = [];
  for (const [key, value] of Object.entries(state.trust)) {
    if (Math.abs(value - 0.5) > 0.05 || (key === 'personal' && Math.abs(value - 0.3) > 0.05)) {
      trustParts.push(`${key.slice(0, 2)}:${value.toFixed(2)}`);
    }
  }

  // Needs: only include unmet (below 3)
  const needParts: string[] = [];
  for (const [key, value] of Object.entries(state.needs)) {
    if (value < 3) {
      const abbrev = NEED_ABBREVS[key] || key.slice(0, 4);
      needParts.push(`${abbrev}:${Math.round(value)}`);
    }
  }

  // Drives: computed
  const drives = computeDrives(state);
  const driveParts = drives.slice(0, 3).map(d => d.name);

  // If nothing notable, return minimal
  if (!emotionParts.length && !trustParts.length && !needParts.length && !driveParts.length) {
    return '[state: baseline, nothing notable]';
  }

  // Build compressed line
  if (emotionParts.length) parts.push(emotionParts.join(' '));
  if (trustParts.length) parts.push(`trust ${trustParts.join(' ')}`);
  if (needParts.length) parts.push(`needs ${needParts.join(' ')}`);
  if (driveParts.length) parts.push(`drives: ${driveParts.join(', ')}`);

  // Session start: include personality + relationship summary
  if (opts.sessionStart) {
    const p = state.personality;
    const pTraits: string[] = [];
    if (p.assertiveness > 0.6) pTraits.push('assertive');
    if (p.assertiveness < 0.4) pTraits.push('deferential');
    if (p.directness > 0.6) pTraits.push('direct');
    if (p.warmth_default > 0.6) pTraits.push('warm');
    if (p.warmth_default < 0.4) pTraits.push('cool');
    if (p.humor_style > 0.6) pTraits.push('playful-humor');
    if (p.humor_style < 0.3) pTraits.push('dry-humor');
    if (p.depth_preference > 0.7) pTraits.push('deep');
    if (p.patience > 0.6) pTraits.push('patient');
    if (p.patience < 0.4) pTraits.push('impatient');
    if (pTraits.length) parts.push(`personality: ${pTraits.join(', ')}`);

    const r = state.relationship;
    const rParts: string[] = [];
    if (r.familiarity > 0.5) rParts.push(`fam:${r.familiarity.toFixed(1)}`);
    if (r.rapport > 0.5) rParts.push(`rap:${r.rapport.toFixed(1)}`);
    if (r.vulnerability > 0.3) rParts.push(`vul:${r.vulnerability.toFixed(1)}`);
    if (rParts.length) parts.push(`relationship ${rParts.join(' ')}`);
  }

  return `[state] ${parts.join(' | ')}`;
}
```

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add src/main/inner-life-compress.ts src/main/__tests__/inner-life-compress.test.ts
git commit -m "feat: compressed context injection - delta-based, ~50-80 tokens avg"
```

---

### Task 7: Wire compressed formatter into inference

**Files:**
- Modify: `src/main/inference.ts` - replace `formatForContext()` with `compressForContext()`

- [ ] **Step 1: Update buildAgencyContext() in inference.ts**

Find where `formatForContext()` is called and replace with `compressForContext()`. On first turn of a session, pass `{ sessionStart: true }` to include personality/relationship.

- [ ] **Step 2: Run full test suite**

Run: `npx vitest run --reporter=verbose 2>&1 | tail -30`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/main/inference.ts
git commit -m "feat: wire compressed context injection into inference pipeline"
```

---

## Phase 3: Expanded Signal Detection

### Task 8: Expand agency.ts signal detection

**Files:**
- Modify: `src/main/agency.ts` (lines 372-428)
- Modify: `src/main/__tests__/agency.test.ts`

- [ ] **Step 1: Write failing tests for new signal categories**

```typescript
describe('expanded signal detection', () => {
  it('detects need satisfaction - help request satisfies purpose', () => {
    const signals = detectEmotionalSignals('Can you help me debug this?');
    expect(signals._need_purpose).toBeGreaterThan(0);
    expect(signals._trust_practical).toBeGreaterThan(0);
  });

  it('detects need satisfaction - new topic satisfies novelty', () => {
    const signals = detectEmotionalSignals('Have you heard about quantum error correction?');
    expect(signals._need_novelty).toBeGreaterThan(0);
    expect(signals._need_stimulation).toBeGreaterThan(0);
  });

  it('detects relationship signals - shared history reference', () => {
    const signals = detectEmotionalSignals('Remember when we fixed that trust pipeline bug?');
    expect(signals._rel_familiarity).toBeGreaterThan(0);
  });

  it('detects relationship signals - humor landing', () => {
    const signals = detectEmotionalSignals('haha that was actually really funny');
    expect(signals._rel_rapport).toBeGreaterThan(0);
    expect(signals.amusement).toBeGreaterThan(0);
  });

  it('detects recognition', () => {
    const signals = detectEmotionalSignals('Great work on that report, exactly what I needed');
    expect(signals._need_recognition).toBeGreaterThan(0);
    expect(signals.satisfaction).toBeGreaterThan(0);
  });

  it('detects autonomy grant', () => {
    const signals = detectEmotionalSignals('Do what you think is best');
    expect(signals._need_autonomy).toBeGreaterThan(0);
    expect(signals._trust_operational).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Expand detectEmotionalSignals()**

Add signal detection for:
- Need satisfaction keys: `_need_stimulation`, `_need_purpose`, `_need_novelty`, `_need_recognition`, `_need_autonomy`, `_need_social`, `_need_expression`
- Relationship keys: `_rel_familiarity`, `_rel_rapport`, `_rel_boundaries`, `_rel_challenge_comfort`, `_rel_vulnerability`
- New trust domains: `_trust_operational`, `_trust_personal`
- New emotions: `amusement`, `anticipation`, `satisfaction`, `restlessness`, `tenderness`, `melancholy`, `focus`, `defiance`

Follow existing pattern: keyword/pattern matching returning delta values.

- [ ] **Step 4: Update inference.ts to apply need/relationship signals**

In `buildAgencyContext()`, where trust signals are extracted with `_trust_` prefix, add:
- `_need_` prefix signals -> call `satisfyNeed()`
- `_rel_` prefix signals -> call `updateRelationship()` (new function in inner-life.ts)

- [ ] **Step 5: Run all tests**

Run: `npx vitest run --reporter=verbose 2>&1 | tail -30`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/main/agency.ts src/main/__tests__/agency.test.ts src/main/inference.ts
git commit -m "feat: expanded signal detection - needs, relationship, new emotions, new trust domains"
```

---

## Phase 4: Distributed Emotional Embeddings

### Task 9: Add emotional vector storage

**Files:**
- Modify: `src/main/memory.ts` - add emotional_vector to writeTurn/writeObservation
- Modify: `src/main/inner-life.ts` - add encodeEmotionalVector/decodeEmotionalVector

- [ ] **Step 1: Write failing test**

```typescript
describe('emotional vectors', () => {
  it('encodes full state into 32-dim Float32Array', () => {
    const state = DEFAULT_FULL_STATE();
    const vec = encodeEmotionalVector(state);
    expect(vec).toBeInstanceOf(Float32Array);
    expect(vec.length).toBe(32);
    // First 14 should be emotion values
    expect(vec[0]).toBeCloseTo(state.emotions.connection);
  });

  it('decodes vector back to partial state', () => {
    const state = DEFAULT_FULL_STATE();
    state.emotions.warmth = 0.9;
    const vec = encodeEmotionalVector(state);
    const decoded = decodeEmotionalVector(vec);
    expect(decoded.emotions.warmth).toBeCloseTo(0.9);
  });
});
```

- [ ] **Step 2: Implement encode/decode**

```typescript
// Packing order: 14 emotions + 6 trust + 8 needs (scaled 0-1) + 4 spare = 32
export function encodeEmotionalVector(state: FullState): Float32Array {
  const vec = new Float32Array(32);
  const emotionKeys = Object.keys(state.emotions) as (keyof Emotions)[];
  emotionKeys.forEach((k, i) => { vec[i] = state.emotions[k]; });
  const trustKeys = Object.keys(state.trust) as (keyof Trust)[];
  trustKeys.forEach((k, i) => { vec[14 + i] = state.trust[k]; });
  const needKeys = Object.keys(state.needs) as (keyof Needs)[];
  needKeys.forEach((k, i) => { vec[20 + i] = state.needs[k] / 10; }); // scale to 0-1
  return vec;
}

export function decodeEmotionalVector(vec: Float32Array): Partial<FullState> {
  // Inverse of encode
}
```

- [ ] **Step 3: Wire into writeTurn/writeObservation in memory.ts**

After writing a turn, encode the current emotional state and store the blob.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/main/inner-life.ts src/main/memory.ts src/main/__tests__/inner-life.test.ts
git commit -m "feat: emotional vector encoding/decoding + storage on turns"
```

---

### Task 10: Implement distributed state aggregation

**Files:**
- Modify: `src/main/inner-life.ts` - add computeDistributedState()
- Modify: `src/main/memory.ts` - add getRecentEmotionalVectors()

- [ ] **Step 1: Write failing test**

```typescript
describe('distributed state aggregation', () => {
  it('computes time-weighted average of recent vectors', () => {
    const vectors = [
      { vec: makeVec({ warmth: 0.9 }), timestamp: Date.now() - 60000 },  // 1 min ago
      { vec: makeVec({ warmth: 0.3 }), timestamp: Date.now() - 3600000 }, // 1 hour ago
    ];
    const result = computeDistributedState(vectors);
    // Recent vector should dominate
    expect(result.emotions.warmth).toBeGreaterThan(0.6);
  });
});
```

- [ ] **Step 2: Implement aggregation**

```typescript
export function computeDistributedState(
  vectors: Array<{ vec: Float32Array; timestamp: number }>,
  halfLifeMs = 3600000, // 1 hour
): Partial<FullState> {
  if (!vectors.length) return {};
  const now = Date.now();
  const weighted = new Float32Array(32);
  let totalWeight = 0;
  for (const { vec, timestamp } of vectors) {
    const age = now - timestamp;
    const weight = Math.pow(0.5, age / halfLifeMs);
    for (let i = 0; i < 32; i++) weighted[i] += vec[i] * weight;
    totalWeight += weight;
  }
  if (totalWeight > 0) {
    for (let i = 0; i < 32; i++) weighted[i] /= totalWeight;
  }
  return decodeEmotionalVector(weighted);
}
```

- [ ] **Step 3: Add getRecentEmotionalVectors() to memory.ts**

Query turns from the last N hours that have non-null emotional_vector blobs.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add src/main/inner-life.ts src/main/memory.ts src/main/__tests__/inner-life.test.ts
git commit -m "feat: distributed state aggregation from emotional vectors"
```

---

## Phase 5: Cron Job Integration

### Task 11: Update sleep cycle for state reconciliation

**Files:**
- Modify: `scripts/agents/shared/sleep_cycle.py`

- [ ] **Step 1: Add distributed state aggregation to sleep cycle**

After existing observation processing, add:
1. Fetch all emotional vectors from today's turns
2. Compute time-weighted aggregate
3. Reconcile with current snapshot (JSON cache)
4. Write emotional summary to journal: "Today I felt [aggregate]. Trust grew in [domains]. Unmet needs: [list]."
5. Flag personality drift if any trait moved >0.05 from agent.json defaults

- [ ] **Step 2: Commit**

```bash
git add scripts/agents/shared/sleep_cycle.py
git commit -m "feat: sleep cycle reconciles distributed emotional state nightly"
```

---

### Task 12: Update introspect for emotional arc

**Files:**
- Modify: `scripts/agents/shared/introspect.py`

- [ ] **Step 1: Add emotional arc to introspection material**

In the material-gathering section, add:
1. Load current full state (all 6 categories)
2. Load state_log entries from the past week
3. Compute emotional trajectory: "connection peaked Tuesday, restlessness grew Thursday"
4. Include unmet needs: "Purpose has been low this week"
5. Include relationship progress: "Familiarity growing, rapport stable"
6. Add to the material dump that gets passed to the LLM

- [ ] **Step 2: Commit**

```bash
git add scripts/agents/shared/introspect.py
git commit -m "feat: introspect includes emotional arc, needs, relationship progress"
```

---

### Task 13: Update evolve for personality adjustment

**Files:**
- Modify: `scripts/agents/shared/evolve.py`

- [ ] **Step 1: Add personality trait review to evolution**

In the material-gathering section, add:
1. Load current personality traits
2. Load personality_log entries (previous shifts)
3. Load state_log summaries for the past month (emotional patterns, trust trends)
4. Add instruction to the LLM: "Review whether personality traits should shift. You may adjust any trait by up to +/-0.05. Write adjustments as JSON."
5. Parse LLM output for personality adjustments
6. Apply adjustments to the state file
7. Write to personality_log

- [ ] **Step 2: Commit**

```bash
git add scripts/agents/shared/evolve.py
git commit -m "feat: evolve.py can adjust personality traits based on interaction patterns"
```

---

### Task 14: Update heartbeat for needs/drives

**Files:**
- Modify: `scripts/agents/shared/heartbeat.py`

- [ ] **Step 1: Add needs/drives to heartbeat context**

In `_gather_context()`, add:
1. Load current needs values
2. Compute active drives
3. Include in context: "Needs: stimulation 2/10 (LOW), purpose 3/10 (LOW). Active drives: seeking-new-topics, offering-to-help"
4. Factor needs into severity calculation: agents with very low purpose/social needs should have lower severity thresholds

- [ ] **Step 2: Commit**

```bash
git add scripts/agents/shared/heartbeat.py
git commit -m "feat: heartbeat factors in needs and drives for severity assessment"
```

---

### Task 15: Python port of v2 state

**Files:**
- Modify: `core/inner_life.py` (328 lines)
- Modify: `core/memory.py` (1095 lines)
- Modify: `core/agency.py` (374 lines)

- [ ] **Step 1: Port v2 types and defaults to inner_life.py**

Add the same dimension inventory: 14 emotions, 6 trust, 8 needs, 8 personality, 6 relationship. Update load_state/save_state for v1->v2 migration. Update decay for all categories. Update format_for_context with compressed format.

- [ ] **Step 2: Port new memory functions to memory.py**

Add state_log, need_events, personality_log table creation in migration. Add write_state_log, write_need_event, write_personality_log functions.

- [ ] **Step 3: Port expanded signal detection to agency.py**

Add need satisfaction, relationship, and new emotion signals matching the TypeScript implementation.

- [ ] **Step 4: Commit**

```bash
git add core/inner_life.py core/memory.py core/agency.py
git commit -m "feat: Python port of v2 inner life - all 6 categories, compressed format, expanded signals"
```

---

### Task 16: Final integration test and docs

**Files:**
- Modify: `docs/specs/2026-03-24-inner-life-v2-design.md` - mark as implemented
- Run full test suite

- [ ] **Step 1: Run full test suite**

Run: `npx vitest run --reporter=verbose 2>&1 | tail -40`
Expected: All tests pass

- [ ] **Step 2: Run TypeScript type check**

Run: `npx tsc --noEmit 2>&1`
Expected: No errors

- [ ] **Step 3: Test Python scripts**

Run: `cd /tmp/atrophy && AGENT=companion python3 -c "from core.inner_life import load_state, format_for_context; s = load_state(); print(format_for_context())"`
Expected: Compressed format output

- [ ] **Step 4: Update design doc status**

Add "Status: Implemented" to the top of the design spec.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: Inner Life v2 complete - 50 dimensions, distributed embeddings, compressed injection"
```

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| 1 | Tasks 1-5 | v2 state format, needs system, personality defaults, schema |
| 2 | Tasks 6-7 | Compressed context injection (~50 tokens avg) |
| 3 | Task 8 | Expanded signal detection for all 6 categories |
| 4 | Tasks 9-10 | Distributed emotional embeddings + aggregation |
| 5 | Tasks 11-16 | Cron integration, Python port, final tests |

Total: 16 tasks. Each phase produces working, testable software.

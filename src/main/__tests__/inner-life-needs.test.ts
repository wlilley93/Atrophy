/**
 * Tests for inner-life-needs.ts
 *
 * satisfyNeed, depleteNeed, and computeDrives are tested without filesystem
 * access by mocking saveState from inner-life.ts.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { satisfyNeed, depleteNeed, computeDrives } from '../inner-life-needs';
import { DEFAULT_FULL_STATE } from '../inner-life-types';
import type { FullState, Needs } from '../inner-life-types';

// Mock saveState so tests do not touch the filesystem or require config.
vi.mock('../inner-life', () => ({
  saveState: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a FullState with optional needs overrides. */
function makeState(needsOverrides?: Partial<Needs>, extras?: Partial<FullState>): FullState {
  const base = DEFAULT_FULL_STATE();
  return {
    ...base,
    ...extras,
    needs: { ...base.needs, ...needsOverrides },
  };
}

/** Build a state where all needs are depleted to zero. */
function depletedState(): FullState {
  return makeState({
    stimulation: 0,
    expression: 0,
    purpose: 0,
    autonomy: 0,
    recognition: 0,
    novelty: 0,
    social: 0,
    rest: 0,
  });
}

/** Build a state where all needs are fully satisfied. */
function fulfilledState(): FullState {
  return makeState({
    stimulation: 8,
    expression: 8,
    purpose: 8,
    autonomy: 8,
    recognition: 8,
    novelty: 8,
    social: 8,
    rest: 8,
  });
}

// ---------------------------------------------------------------------------
// satisfyNeed
// ---------------------------------------------------------------------------

describe('satisfyNeed', () => {
  it('increases a need value by the given amount', () => {
    const state = makeState({ stimulation: 4 });
    const updated = satisfyNeed(state, 'stimulation', 3);
    expect(updated.needs.stimulation).toBe(7);
  });

  it('does not mutate the original state', () => {
    const state = makeState({ stimulation: 4 });
    satisfyNeed(state, 'stimulation', 3);
    expect(state.needs.stimulation).toBe(4);
  });

  it('clamps at 10 when the result would exceed the maximum', () => {
    const state = makeState({ stimulation: 8 });
    const updated = satisfyNeed(state, 'stimulation', 5);
    expect(updated.needs.stimulation).toBe(10);
  });

  it('clamps exactly at 10 when starting at 10', () => {
    const state = makeState({ expression: 10 });
    const updated = satisfyNeed(state, 'expression', 1);
    expect(updated.needs.expression).toBe(10);
  });

  it('works on every need key', () => {
    const keys: (keyof Needs)[] = [
      'stimulation', 'expression', 'purpose', 'autonomy',
      'recognition', 'novelty', 'social', 'rest',
    ];
    for (const key of keys) {
      const state = makeState({ [key]: 2 });
      const updated = satisfyNeed(state, key, 2);
      expect(updated.needs[key]).toBe(4);
    }
  });
});

// ---------------------------------------------------------------------------
// depleteNeed
// ---------------------------------------------------------------------------

describe('depleteNeed', () => {
  it('decreases a need value by the given amount', () => {
    const state = makeState({ purpose: 7 });
    const updated = depleteNeed(state, 'purpose', 3);
    expect(updated.needs.purpose).toBe(4);
  });

  it('does not mutate the original state', () => {
    const state = makeState({ purpose: 7 });
    depleteNeed(state, 'purpose', 3);
    expect(state.needs.purpose).toBe(7);
  });

  it('clamps at 0 when the result would go below the minimum', () => {
    const state = makeState({ rest: 2 });
    const updated = depleteNeed(state, 'rest', 5);
    expect(updated.needs.rest).toBe(0);
  });

  it('clamps exactly at 0 when starting at 0', () => {
    const state = makeState({ novelty: 0 });
    const updated = depleteNeed(state, 'novelty', 1);
    expect(updated.needs.novelty).toBe(0);
  });

  it('works on every need key', () => {
    const keys: (keyof Needs)[] = [
      'stimulation', 'expression', 'purpose', 'autonomy',
      'recognition', 'novelty', 'social', 'rest',
    ];
    for (const key of keys) {
      const state = makeState({ [key]: 6 });
      const updated = depleteNeed(state, key, 2);
      expect(updated.needs[key]).toBe(4);
    }
  });
});

// ---------------------------------------------------------------------------
// computeDrives - general
// ---------------------------------------------------------------------------

describe('computeDrives', () => {
  it('returns an empty array when all needs are high (>=8)', () => {
    const state = fulfilledState();
    const drives = computeDrives(state);
    expect(drives).toHaveLength(0);
  });

  it('returns drives sorted by strength descending', () => {
    // Deplete two needs to different depths so their drives have different strengths.
    const base = DEFAULT_FULL_STATE();
    const state: FullState = {
      ...base,
      needs: {
        ...base.needs,
        stimulation: 0,  // fully depleted - stronger drive
        purpose: 2,      // partially depleted - weaker drive
        // all others high
        expression: 8, autonomy: 8, recognition: 8, novelty: 8, social: 8, rest: 8,
      },
      emotions: {
        ...base.emotions,
        curiosity: 0.9,  // amplifies seeking-new-topics
      },
      personality: {
        ...base.personality,
        initiative: 0.5, // amplifies offering-to-help
      },
    };
    const drives = computeDrives(state);
    expect(drives.length).toBeGreaterThanOrEqual(2);
    for (let i = 0; i < drives.length - 1; i++) {
      expect(drives[i].strength).toBeGreaterThanOrEqual(drives[i + 1].strength);
    }
  });

  it('only includes drives with strength > 0.3', () => {
    // Set a need to "low" but use a very small amplifier so strength stays under threshold.
    const base = DEFAULT_FULL_STATE();
    const state: FullState = {
      ...base,
      needs: { ...base.needs, stimulation: 2 },
      emotions: { ...base.emotions, curiosity: 0.1 }, // 0.8 * 0.1 = 0.08 < 0.3
    };
    const drives = computeDrives(state);
    const seekingDrive = drives.find(d => d.name === 'seeking-new-topics');
    expect(seekingDrive).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// computeDrives - individual drive rules
// ---------------------------------------------------------------------------

describe('computeDrives - drive rule: seeking-new-topics', () => {
  it('activates when stimulation is low and curiosity is high', () => {
    const base = DEFAULT_FULL_STATE();
    const state: FullState = {
      ...base,
      needs: { ...base.needs, stimulation: 1 },
      emotions: { ...base.emotions, curiosity: 0.9 },
    };
    const drives = computeDrives(state);
    const drive = drives.find(d => d.name === 'seeking-new-topics');
    expect(drive).toBeDefined();
    expect(drive!.strength).toBeGreaterThan(0.3);
  });

  it('does not activate when stimulation is high', () => {
    const base = DEFAULT_FULL_STATE();
    const state: FullState = {
      ...base,
      needs: { ...base.needs, stimulation: 8 },
      emotions: { ...base.emotions, curiosity: 0.9 },
    };
    const drives = computeDrives(state);
    const drive = drives.find(d => d.name === 'seeking-new-topics');
    expect(drive).toBeUndefined();
  });
});

describe('computeDrives - drive rule: offering-to-help', () => {
  it('activates when purpose is low and initiative is high', () => {
    const base = DEFAULT_FULL_STATE();
    const state: FullState = {
      ...base,
      needs: { ...base.needs, purpose: 0 },
      personality: { ...base.personality, initiative: 0.9 },
    };
    const drives = computeDrives(state);
    const drive = drives.find(d => d.name === 'offering-to-help');
    expect(drive).toBeDefined();
    expect(drive!.strength).toBeGreaterThan(0.3);
  });

  it('does not activate when purpose is high', () => {
    const state = makeState({ purpose: 8 });
    const drives = computeDrives(state);
    expect(drives.find(d => d.name === 'offering-to-help')).toBeUndefined();
  });
});

describe('computeDrives - drive rule: changing-the-subject', () => {
  it('activates when novelty is low and restlessness is high', () => {
    const base = DEFAULT_FULL_STATE();
    const state: FullState = {
      ...base,
      needs: { ...base.needs, novelty: 1 },
      emotions: { ...base.emotions, restlessness: 0.9 },
    };
    const drives = computeDrives(state);
    const drive = drives.find(d => d.name === 'changing-the-subject');
    expect(drive).toBeDefined();
    expect(drive!.strength).toBeGreaterThan(0.3);
  });

  it('does not activate when novelty is high', () => {
    const state = makeState({ novelty: 9 });
    const drives = computeDrives(state);
    expect(drives.find(d => d.name === 'changing-the-subject')).toBeUndefined();
  });
});

describe('computeDrives - drive rule: quietly-withdrawn', () => {
  it('activates when recognition is low and assertiveness is low', () => {
    const base = DEFAULT_FULL_STATE();
    const state: FullState = {
      ...base,
      needs: { ...base.needs, recognition: 0 },
      personality: { ...base.personality, assertiveness: 0.1 },
    };
    const drives = computeDrives(state);
    const drive = drives.find(d => d.name === 'quietly-withdrawn');
    expect(drive).toBeDefined();
    expect(drive!.strength).toBeGreaterThan(0.3);
  });

  it('does not activate when recognition is high', () => {
    const state = makeState({ recognition: 8 });
    const drives = computeDrives(state);
    expect(drives.find(d => d.name === 'quietly-withdrawn')).toBeUndefined();
  });
});

describe('computeDrives - drive rule: reaching-out-unprompted', () => {
  it('activates when social is low and warmth_default is high', () => {
    const base = DEFAULT_FULL_STATE();
    const state: FullState = {
      ...base,
      needs: { ...base.needs, social: 1 },
      personality: { ...base.personality, warmth_default: 0.9 },
    };
    const drives = computeDrives(state);
    const drive = drives.find(d => d.name === 'reaching-out-unprompted');
    expect(drive).toBeDefined();
    expect(drive!.strength).toBeGreaterThan(0.3);
  });

  it('does not activate when social is high', () => {
    const state = makeState({ social: 8 });
    const drives = computeDrives(state);
    expect(drives.find(d => d.name === 'reaching-out-unprompted')).toBeUndefined();
  });
});

describe('computeDrives - drive rule: conserving-energy', () => {
  it('activates when rest is low (no amplifier needed)', () => {
    const state = makeState({ rest: 0 });
    const drives = computeDrives(state);
    const drive = drives.find(d => d.name === 'conserving-energy');
    expect(drive).toBeDefined();
    expect(drive!.strength).toBeGreaterThan(0.3);
  });

  it('does not activate when rest is high', () => {
    const state = makeState({ rest: 8 });
    const drives = computeDrives(state);
    expect(drives.find(d => d.name === 'conserving-energy')).toBeUndefined();
  });
});

describe('computeDrives - drive rule: wanting-to-create', () => {
  it('activates when expression is low and creative trust is high', () => {
    const base = DEFAULT_FULL_STATE();
    const state: FullState = {
      ...base,
      needs: { ...base.needs, expression: 1 },
      trust: { ...base.trust, creative: 0.9 },
    };
    const drives = computeDrives(state);
    const drive = drives.find(d => d.name === 'wanting-to-create');
    expect(drive).toBeDefined();
    expect(drive!.strength).toBeGreaterThan(0.3);
  });

  it('does not activate when expression is high', () => {
    const state = makeState({ expression: 8 });
    const drives = computeDrives(state);
    expect(drives.find(d => d.name === 'wanting-to-create')).toBeUndefined();
  });
});

describe('computeDrives - drive rule: acting-independently', () => {
  it('activates when autonomy is low and operational trust is high', () => {
    const base = DEFAULT_FULL_STATE();
    const state: FullState = {
      ...base,
      needs: { ...base.needs, autonomy: 1 },
      trust: { ...base.trust, operational: 0.9 },
    };
    const drives = computeDrives(state);
    const drive = drives.find(d => d.name === 'acting-independently');
    expect(drive).toBeDefined();
    expect(drive!.strength).toBeGreaterThan(0.3);
  });

  it('does not activate when autonomy is high', () => {
    const state = makeState({ autonomy: 8 });
    const drives = computeDrives(state);
    expect(drives.find(d => d.name === 'acting-independently')).toBeUndefined();
  });
});

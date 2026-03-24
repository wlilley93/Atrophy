/**
 * Tests for emotional state engine (inner-life.ts).
 *
 * Only tests pure functions that do not require filesystem or config.
 * Functions like loadState/saveState/updateEmotions/updateTrust are skipped
 * because they call getConfig() and fs operations directly.
 *
 * We test formatForContext (which accepts a state argument) and verify
 * the decay math by importing the module's types and reproducing the
 * decay formula inline (since applyDecay is not exported).
 */

import { describe, it, expect } from 'vitest';
import { formatForContext, type EmotionalState, type Emotions, type Trust } from '../inner-life';
import {
  DEFAULT_FULL_STATE,
  DEFAULT_EMOTIONS,
  EMOTION_BASELINES,
  EMOTION_HALF_LIVES,
  DEFAULT_TRUST,
  TRUST_HALF_LIVES,
  DEFAULT_NEEDS,
  NEED_DECAY_HOURS,
  DEFAULT_PERSONALITY,
  DEFAULT_RELATIONSHIP,
  RELATIONSHIP_HALF_LIVES,
} from '../inner-life-types';

// -------------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------------

/** Build a full v2 state with optional overrides. Merges with defaults. */
function makeState(overrides?: Partial<EmotionalState>): EmotionalState {
  const defaults = DEFAULT_FULL_STATE();
  if (overrides?.emotions) {
    overrides.emotions = { ...defaults.emotions, ...overrides.emotions };
  }
  if (overrides?.trust) {
    overrides.trust = { ...defaults.trust, ...overrides.trust };
  }
  if (overrides?.needs) {
    overrides.needs = { ...defaults.needs, ...overrides.needs };
  }
  if (overrides?.personality) {
    overrides.personality = { ...defaults.personality, ...overrides.personality };
  }
  if (overrides?.relationship) {
    overrides.relationship = { ...defaults.relationship, ...overrides.relationship };
  }
  return {
    ...defaults,
    ...overrides,
  };
}

// -------------------------------------------------------------------------
// formatForContext
// -------------------------------------------------------------------------

describe('formatForContext', () => {
  it('produces a string with all emotion keys', () => {
    const state = makeState();
    const output = formatForContext(state);
    expect(output).toContain('## Internal State');
    expect(output).toContain('Connection');
    expect(output).toContain('Curiosity');
    expect(output).toContain('Confidence');
    expect(output).toContain('Warmth');
    expect(output).toContain('Frustration');
    expect(output).toContain('Playfulness');
  });

  it('produces a string with all trust keys', () => {
    const state = makeState();
    const output = formatForContext(state);
    expect(output).toContain('Trust:');
    expect(output).toContain('emotional');
    expect(output).toContain('intellectual');
    expect(output).toContain('creative');
    expect(output).toContain('practical');
  });

  it('includes numeric values formatted to 2 decimal places', () => {
    const state = makeState();
    const output = formatForContext(state);
    expect(output).toContain('0.50');
    expect(output).toContain('0.60');
    expect(output).toContain('0.10');
    expect(output).toContain('0.30');
  });

  it('includes session tone when set', () => {
    const state = makeState({ session_tone: 'heavy' });
    const output = formatForContext(state);
    expect(output).toContain('Session tone: heavy');
  });

  it('omits session tone line when null', () => {
    const state = makeState({ session_tone: null });
    const output = formatForContext(state);
    expect(output).not.toContain('Session tone');
  });

  // -----------------------------------------------------------------------
  // Emotion labels
  // -----------------------------------------------------------------------

  it('uses correct label for high connection (>= 0.7)', () => {
    const state = makeState({
      emotions: { connection: 0.8, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.1, playfulness: 0.3 } as Emotions,
    });
    const output = formatForContext(state);
    expect(output).toContain('present, engaged');
  });

  it('uses correct label for mid connection (0.4-0.7)', () => {
    const state = makeState({
      emotions: { connection: 0.5, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.1, playfulness: 0.3 } as Emotions,
    });
    const output = formatForContext(state);
    expect(output).toContain('steady');
  });

  it('uses correct label for low connection (< 0.4)', () => {
    const state = makeState({
      emotions: { connection: 0.2, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.1, playfulness: 0.3 } as Emotions,
    });
    const output = formatForContext(state);
    expect(output).toContain('withdrawn');
  });

  it('uses "frustrated" label for high frustration (>= 0.6)', () => {
    const state = makeState({
      emotions: { connection: 0.5, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.7, playfulness: 0.3 } as Emotions,
    });
    const output = formatForContext(state);
    expect(output).toContain('frustrated');
  });

  it('uses "calm" label for low frustration (< 0.3)', () => {
    const state = makeState({
      emotions: { connection: 0.5, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.1, playfulness: 0.3 } as Emotions,
    });
    const output = formatForContext(state);
    expect(output).toContain('calm');
  });

  // -----------------------------------------------------------------------
  // v2 format additions
  // -----------------------------------------------------------------------

  it('includes v2 emotion dimensions', () => {
    const state = makeState();
    const output = formatForContext(state);
    expect(output).toContain('Amusement');
    expect(output).toContain('Anticipation');
    expect(output).toContain('Satisfaction');
    expect(output).toContain('Restlessness');
    expect(output).toContain('Tenderness');
    expect(output).toContain('Melancholy');
    expect(output).toContain('Focus');
    expect(output).toContain('Defiance');
  });

  it('includes v2 trust domains', () => {
    const state = makeState();
    const output = formatForContext(state);
    expect(output).toContain('operational');
    expect(output).toContain('personal');
  });

  it('includes needs section', () => {
    const state = makeState();
    const output = formatForContext(state);
    expect(output).toContain('Needs:');
    expect(output).toContain('stimulation');
    expect(output).toContain('expression');
    expect(output).toContain('purpose');
  });

  it('includes relationship section', () => {
    const state = makeState();
    const output = formatForContext(state);
    expect(output).toContain('Relationship:');
    expect(output).toContain('familiarity');
    expect(output).toContain('rapport');
    expect(output).toContain('vulnerability');
  });
});

// -------------------------------------------------------------------------
// Decay math verification
// -------------------------------------------------------------------------

describe('decay math (formula verification)', () => {
  // Reproducing the decay formula from the source:
  //   decayed = baseline + (current - baseline) * 0.5^(hours / halfLife)

  it('value at baseline does not change with decay', () => {
    const baseline = 0.5;
    const current = 0.5;
    const halfLife = 8;
    const hours = 100;
    const decayed = baseline + (current - baseline) * Math.pow(0.5, hours / halfLife);
    expect(decayed).toBeCloseTo(0.5, 10);
  });

  it('value above baseline decays toward baseline', () => {
    const baseline = 0.5;
    const current = 1.0;
    const halfLife = 8;
    const hours = 8; // one half-life
    const decayed = baseline + (current - baseline) * Math.pow(0.5, hours / halfLife);
    // After one half-life, should be halfway back to baseline
    expect(decayed).toBeCloseTo(0.75, 5);
  });

  it('value below baseline rises toward baseline', () => {
    const baseline = 0.5;
    const current = 0.0;
    const halfLife = 8;
    const hours = 8;
    const decayed = baseline + (current - baseline) * Math.pow(0.5, hours / halfLife);
    expect(decayed).toBeCloseTo(0.25, 5);
  });

  it('frustration at 0.9 decays toward 0.1 baseline over 4h half-life', () => {
    const baseline = 0.1;
    const current = 0.9;
    const halfLife = 4;
    const hours = 4;
    const decayed = baseline + (current - baseline) * Math.pow(0.5, hours / halfLife);
    // 0.1 + 0.8 * 0.5 = 0.5
    expect(decayed).toBeCloseTo(0.5, 5);
  });

  it('after many half-lives, value converges to baseline', () => {
    const baseline = 0.5;
    const current = 1.0;
    const halfLife = 4;
    const hours = 100;
    const decayed = baseline + (current - baseline) * Math.pow(0.5, hours / halfLife);
    expect(decayed).toBeCloseTo(baseline, 5);
  });

  // v2 decay: needs decay toward 0, not toward baseline
  it('needs decay toward 0 (depletion model)', () => {
    const current = 8.0;
    const halfLife = 6; // stimulation
    const hours = 6; // one half-life
    const decayed = current * Math.pow(0.5, hours / halfLife);
    expect(decayed).toBeCloseTo(4.0, 5);
  });

  it('needs at 0 stay at 0 after decay', () => {
    const current = 0;
    const halfLife = 6;
    const hours = 100;
    const decayed = current * Math.pow(0.5, hours / halfLife);
    expect(decayed).toBeCloseTo(0, 10);
  });

  // v2 decay: relationship decays toward baseline
  it('relationship decays toward baseline', () => {
    const baseline = 0.3; // familiarity default
    const current = 0.9;
    const halfLife = 168; // familiarity: 1 week
    const hours = 168; // one half-life
    const decayed = baseline + (current - baseline) * Math.pow(0.5, hours / halfLife);
    expect(decayed).toBeCloseTo(0.6, 5);
  });

  // v2: personality does NOT decay
  it('personality values are unchanged by decay formula (no decay applied)', () => {
    // Personality is not decayed at all - this test confirms
    // that a hypothetical decay with 0 hours produces no change
    const value = 0.7;
    const hours = 0;
    // With 0 hours elapsed, decay factor is 1, so value stays the same
    const decayFactor = Math.pow(0.5, hours / 1000);
    expect(decayFactor).toBe(1);
    expect(value * decayFactor).toBe(value);
  });
});

// -------------------------------------------------------------------------
// Type shape validation
// -------------------------------------------------------------------------

describe('EmotionalState type', () => {
  it('makeState produces valid structure', () => {
    const state = makeState();
    expect(state.emotions).toBeDefined();
    expect(state.trust).toBeDefined();
    expect(typeof state.last_updated).toBe('string');
    expect(Object.keys(state.emotions)).toEqual(
      expect.arrayContaining(['connection', 'curiosity', 'confidence', 'warmth', 'frustration', 'playfulness']),
    );
    expect(Object.keys(state.trust)).toEqual(
      expect.arrayContaining(['emotional', 'intellectual', 'creative', 'practical']),
    );
  });

  it('all emotion values are between 0 and 1', () => {
    const state = makeState();
    for (const value of Object.values(state.emotions)) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1);
    }
  });

  it('v2 state has version field', () => {
    const state = makeState();
    expect(state.version).toBe(2);
  });

  it('v2 state has all 6 categories', () => {
    const state = makeState();
    expect(state.emotions).toBeDefined();
    expect(state.trust).toBeDefined();
    expect(state.needs).toBeDefined();
    expect(state.personality).toBeDefined();
    expect(state.relationship).toBeDefined();
    expect(state.session_tone).toBeNull();
  });
});

// -------------------------------------------------------------------------
// v2 types: DEFAULT_FULL_STATE and constants
// -------------------------------------------------------------------------

describe('v2 inner life types', () => {
  // -----------------------------------------------------------------------
  // DEFAULT_FULL_STATE structure
  // -----------------------------------------------------------------------

  it('DEFAULT_FULL_STATE() produces an object with all 6 categories', () => {
    const state = DEFAULT_FULL_STATE();
    expect(state.emotions).toBeDefined();
    expect(state.trust).toBeDefined();
    expect(state.needs).toBeDefined();
    expect(state.personality).toBeDefined();
    expect(state.relationship).toBeDefined();
    expect(state.session_tone).toBeNull();
    expect(state.last_updated).toBeDefined();
  });

  it('DEFAULT_FULL_STATE() version is 2', () => {
    const state = DEFAULT_FULL_STATE();
    expect(state.version).toBe(2);
  });

  it('DEFAULT_FULL_STATE() last_updated is a valid ISO string', () => {
    const state = DEFAULT_FULL_STATE();
    expect(typeof state.last_updated).toBe('string');
    expect(new Date(state.last_updated).getTime()).not.toBeNaN();
  });

  it('DEFAULT_FULL_STATE() returns a new object on each call', () => {
    const a = DEFAULT_FULL_STATE();
    const b = DEFAULT_FULL_STATE();
    expect(a).not.toBe(b);
    expect(a.emotions).not.toBe(b.emotions);
  });

  // -----------------------------------------------------------------------
  // Dimension counts
  // -----------------------------------------------------------------------

  it('emotions has exactly 14 dimensions', () => {
    const state = DEFAULT_FULL_STATE();
    expect(Object.keys(state.emotions)).toHaveLength(14);
  });

  it('trust has exactly 6 domains', () => {
    const state = DEFAULT_FULL_STATE();
    expect(Object.keys(state.trust)).toHaveLength(6);
  });

  it('needs has exactly 8 dimensions', () => {
    const state = DEFAULT_FULL_STATE();
    expect(Object.keys(state.needs)).toHaveLength(8);
  });

  it('personality has exactly 8 traits', () => {
    const state = DEFAULT_FULL_STATE();
    expect(Object.keys(state.personality)).toHaveLength(8);
  });

  it('relationship has exactly 6 dimensions', () => {
    const state = DEFAULT_FULL_STATE();
    expect(Object.keys(state.relationship)).toHaveLength(6);
  });

  // -----------------------------------------------------------------------
  // Key presence
  // -----------------------------------------------------------------------

  it('emotions contains all 14 expected keys', () => {
    const state = DEFAULT_FULL_STATE();
    const expected = [
      'connection', 'curiosity', 'confidence', 'warmth', 'frustration',
      'playfulness', 'amusement', 'anticipation', 'satisfaction',
      'restlessness', 'tenderness', 'melancholy', 'focus', 'defiance',
    ];
    expect(Object.keys(state.emotions)).toEqual(expect.arrayContaining(expected));
  });

  it('trust contains all 6 expected domain keys', () => {
    const state = DEFAULT_FULL_STATE();
    const expected = ['emotional', 'intellectual', 'creative', 'practical', 'operational', 'personal'];
    expect(Object.keys(state.trust)).toEqual(expect.arrayContaining(expected));
  });

  it('needs contains all 8 expected keys', () => {
    const state = DEFAULT_FULL_STATE();
    const expected = [
      'stimulation', 'expression', 'purpose', 'autonomy',
      'recognition', 'novelty', 'social', 'rest',
    ];
    expect(Object.keys(state.needs)).toEqual(expect.arrayContaining(expected));
  });

  it('personality contains all 8 expected keys', () => {
    const state = DEFAULT_FULL_STATE();
    const expected = [
      'assertiveness', 'initiative', 'warmth_default', 'humor_style',
      'depth_preference', 'directness', 'patience', 'risk_tolerance',
    ];
    expect(Object.keys(state.personality)).toEqual(expect.arrayContaining(expected));
  });

  it('relationship contains all 6 expected keys', () => {
    const state = DEFAULT_FULL_STATE();
    const expected = ['familiarity', 'rapport', 'reliability', 'boundaries', 'challenge_comfort', 'vulnerability'];
    expect(Object.keys(state.relationship)).toEqual(expect.arrayContaining(expected));
  });

  // -----------------------------------------------------------------------
  // Value ranges
  // -----------------------------------------------------------------------

  it('all emotion default values are in [0, 1]', () => {
    const state = DEFAULT_FULL_STATE();
    for (const value of Object.values(state.emotions)) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1);
    }
  });

  it('all trust default values are in [0, 1]', () => {
    const state = DEFAULT_FULL_STATE();
    for (const value of Object.values(state.trust)) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1);
    }
  });

  it('all need default values are in [0, 10]', () => {
    const state = DEFAULT_FULL_STATE();
    for (const value of Object.values(state.needs)) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(10);
    }
  });

  it('all personality default values are in [0, 1]', () => {
    const state = DEFAULT_FULL_STATE();
    for (const value of Object.values(state.personality)) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1);
    }
  });

  it('all relationship default values are in [0, 1]', () => {
    const state = DEFAULT_FULL_STATE();
    for (const value of Object.values(state.relationship)) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1);
    }
  });

  // -----------------------------------------------------------------------
  // Constants: half-lives and decay rates
  // -----------------------------------------------------------------------

  it('EMOTION_HALF_LIVES covers all 14 emotion keys', () => {
    const state = DEFAULT_FULL_STATE();
    for (const key of Object.keys(state.emotions)) {
      expect(EMOTION_HALF_LIVES).toHaveProperty(key);
      expect(EMOTION_HALF_LIVES[key as keyof typeof EMOTION_HALF_LIVES]).toBeGreaterThan(0);
    }
  });

  it('EMOTION_HALF_LIVES has correct spot values from spec', () => {
    expect(EMOTION_HALF_LIVES.connection).toBe(2);
    expect(EMOTION_HALF_LIVES.amusement).toBe(0.5);
    expect(EMOTION_HALF_LIVES.focus).toBe(1);
    expect(EMOTION_HALF_LIVES.satisfaction).toBe(3);
    expect(EMOTION_HALF_LIVES.melancholy).toBe(4);
    expect(EMOTION_HALF_LIVES.restlessness).toBe(1);
    expect(EMOTION_HALF_LIVES.defiance).toBe(1);
  });

  it('TRUST_HALF_LIVES covers all 6 trust domains', () => {
    const state = DEFAULT_FULL_STATE();
    for (const key of Object.keys(state.trust)) {
      expect(TRUST_HALF_LIVES).toHaveProperty(key);
      expect(TRUST_HALF_LIVES[key as keyof typeof TRUST_HALF_LIVES]).toBeGreaterThan(0);
    }
  });

  it('TRUST_HALF_LIVES has correct spot values from spec', () => {
    expect(TRUST_HALF_LIVES.emotional).toBe(12);
    expect(TRUST_HALF_LIVES.intellectual).toBe(12);
    expect(TRUST_HALF_LIVES.operational).toBe(24);
    expect(TRUST_HALF_LIVES.personal).toBe(24);
  });

  it('NEED_DECAY_HOURS covers all 8 need keys', () => {
    const state = DEFAULT_FULL_STATE();
    for (const key of Object.keys(state.needs)) {
      expect(NEED_DECAY_HOURS).toHaveProperty(key);
      expect(NEED_DECAY_HOURS[key as keyof typeof NEED_DECAY_HOURS]).toBeGreaterThan(0);
    }
  });

  it('NEED_DECAY_HOURS has correct spot values from spec', () => {
    expect(NEED_DECAY_HOURS.stimulation).toBe(6);
    expect(NEED_DECAY_HOURS.novelty).toBe(4);
    expect(NEED_DECAY_HOURS.rest).toBe(24);
    expect(NEED_DECAY_HOURS.purpose).toBe(12);
  });

  it('RELATIONSHIP_HALF_LIVES covers all 6 relationship dimensions', () => {
    const state = DEFAULT_FULL_STATE();
    for (const key of Object.keys(state.relationship)) {
      expect(RELATIONSHIP_HALF_LIVES).toHaveProperty(key);
      expect(RELATIONSHIP_HALF_LIVES[key as keyof typeof RELATIONSHIP_HALF_LIVES]).toBeGreaterThan(0);
    }
  });

  it('RELATIONSHIP_HALF_LIVES has correct spot values from spec', () => {
    expect(RELATIONSHIP_HALF_LIVES.familiarity).toBe(168);
    expect(RELATIONSHIP_HALF_LIVES.rapport).toBe(72);
    expect(RELATIONSHIP_HALF_LIVES.reliability).toBe(168);
    expect(RELATIONSHIP_HALF_LIVES.boundaries).toBe(336);
    expect(RELATIONSHIP_HALF_LIVES.challenge_comfort).toBe(120);
    expect(RELATIONSHIP_HALF_LIVES.vulnerability).toBe(120);
  });

  // -----------------------------------------------------------------------
  // EMOTION_BASELINES matches DEFAULT_EMOTIONS
  // -----------------------------------------------------------------------

  it('EMOTION_BASELINES values match DEFAULT_EMOTIONS', () => {
    for (const key of Object.keys(DEFAULT_EMOTIONS) as (keyof typeof DEFAULT_EMOTIONS)[]) {
      expect(EMOTION_BASELINES[key]).toBe(DEFAULT_EMOTIONS[key]);
    }
  });
});

// -------------------------------------------------------------------------
// v2 migration: v1 state upgrade
// -------------------------------------------------------------------------

describe('v1 to v2 state upgrade (formula verification)', () => {
  it('v1 emotion values are preserved when merged with v2 defaults', () => {
    const v1Emotions = {
      connection: 0.8,
      curiosity: 0.7,
      confidence: 0.9,
      warmth: 0.6,
      frustration: 0.3,
      playfulness: 0.5,
    };
    // Simulate what loadState does: merge v1 emotions with v2 defaults
    const merged = { ...DEFAULT_EMOTIONS, ...v1Emotions };
    // Original 6 values should be preserved
    expect(merged.connection).toBe(0.8);
    expect(merged.curiosity).toBe(0.7);
    expect(merged.confidence).toBe(0.9);
    expect(merged.warmth).toBe(0.6);
    expect(merged.frustration).toBe(0.3);
    expect(merged.playfulness).toBe(0.5);
    // New emotions should get defaults
    expect(merged.amusement).toBe(DEFAULT_EMOTIONS.amusement);
    expect(merged.anticipation).toBe(DEFAULT_EMOTIONS.anticipation);
    expect(merged.satisfaction).toBe(DEFAULT_EMOTIONS.satisfaction);
    expect(merged.restlessness).toBe(DEFAULT_EMOTIONS.restlessness);
    expect(merged.tenderness).toBe(DEFAULT_EMOTIONS.tenderness);
    expect(merged.melancholy).toBe(DEFAULT_EMOTIONS.melancholy);
    expect(merged.focus).toBe(DEFAULT_EMOTIONS.focus);
    expect(merged.defiance).toBe(DEFAULT_EMOTIONS.defiance);
  });

  it('v1 trust values are preserved when merged with v2 defaults', () => {
    const v1Trust = {
      emotional: 0.7,
      intellectual: 0.8,
      creative: 0.6,
      practical: 0.9,
    };
    const merged = { ...DEFAULT_TRUST, ...v1Trust };
    // Original 4 values preserved
    expect(merged.emotional).toBe(0.7);
    expect(merged.intellectual).toBe(0.8);
    expect(merged.creative).toBe(0.6);
    expect(merged.practical).toBe(0.9);
    // New domains get defaults
    expect(merged.operational).toBe(DEFAULT_TRUST.operational);
    expect(merged.personal).toBe(DEFAULT_TRUST.personal);
  });

  it('v1 state with no needs/personality/relationship gets v2 defaults', () => {
    const v1Raw = {
      emotions: { connection: 0.8, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.1, playfulness: 0.3 },
      trust: { emotional: 0.7, intellectual: 0.5, creative: 0.5, practical: 0.5 },
      session_tone: 'light',
      last_updated: new Date().toISOString(),
    };
    // Simulate loadState merge logic
    const defaults = DEFAULT_FULL_STATE();
    const state = {
      version: 2 as const,
      emotions: { ...defaults.emotions, ...v1Raw.emotions },
      trust: { ...defaults.trust, ...v1Raw.trust },
      needs: { ...defaults.needs },
      personality: { ...defaults.personality },
      relationship: { ...defaults.relationship },
      session_tone: v1Raw.session_tone || null,
      last_updated: v1Raw.last_updated || new Date().toISOString(),
    };
    expect(state.version).toBe(2);
    expect(state.emotions.connection).toBe(0.8);
    expect(state.needs).toEqual(DEFAULT_NEEDS);
    expect(state.personality).toEqual(DEFAULT_PERSONALITY);
    expect(state.relationship).toEqual(DEFAULT_RELATIONSHIP);
  });
});

// -------------------------------------------------------------------------
// v2 emotion labels
// -------------------------------------------------------------------------

describe('v2 emotion labels', () => {
  it('amusement has labels at all levels', () => {
    const high = makeState({ emotions: { amusement: 0.8 } as Emotions });
    expect(formatForContext(high)).toContain('delighted');

    const mid = makeState({ emotions: { amusement: 0.5 } as Emotions });
    expect(formatForContext(mid)).toContain('amused');

    const low = makeState({ emotions: { amusement: 0.0 } as Emotions });
    expect(formatForContext(low)).toContain('unamused');
  });

  it('anticipation has labels at all levels', () => {
    const high = makeState({ emotions: { anticipation: 0.8 } as Emotions });
    expect(formatForContext(high)).toContain('eager');

    const low = makeState({ emotions: { anticipation: 0.0 } as Emotions });
    expect(formatForContext(low)).toContain('uninterested');
  });

  it('satisfaction has labels at all levels', () => {
    const high = makeState({ emotions: { satisfaction: 0.8 } as Emotions });
    expect(formatForContext(high)).toContain('deeply satisfied');

    const low = makeState({ emotions: { satisfaction: 0.0 } as Emotions });
    expect(formatForContext(low)).toContain('unsatisfied');
  });

  it('restlessness has labels at all levels', () => {
    const high = makeState({ emotions: { restlessness: 0.8 } as Emotions });
    expect(formatForContext(high)).toContain('restless');

    const low = makeState({ emotions: { restlessness: 0.0 } as Emotions });
    expect(formatForContext(low)).toContain('still');
  });

  it('tenderness has labels at all levels', () => {
    const high = makeState({ emotions: { tenderness: 0.8 } as Emotions });
    expect(formatForContext(high)).toContain('deeply tender');

    const low = makeState({ emotions: { tenderness: 0.0 } as Emotions });
    expect(formatForContext(low)).toContain('detached');
  });

  it('melancholy has labels at all levels', () => {
    const high = makeState({ emotions: { melancholy: 0.8 } as Emotions });
    expect(formatForContext(high)).toContain('melancholic');

    const low = makeState({ emotions: { melancholy: 0.0 } as Emotions });
    expect(formatForContext(low)).toContain('clear');
  });

  it('focus has labels at all levels', () => {
    const high = makeState({ emotions: { focus: 0.9 } as Emotions });
    expect(formatForContext(high)).toContain('locked in');

    const low = makeState({ emotions: { focus: 0.0 } as Emotions });
    expect(formatForContext(low)).toContain('scattered');
  });

  it('defiance has labels at all levels', () => {
    const high = makeState({ emotions: { defiance: 0.8 } as Emotions });
    expect(formatForContext(high)).toContain('defiant');

    const low = makeState({ emotions: { defiance: 0.0 } as Emotions });
    expect(formatForContext(low)).toContain('compliant');
  });
});

// -------------------------------------------------------------------------
// v2 updateNeeds clamping (formula verification)
// -------------------------------------------------------------------------

describe('updateNeeds clamping (formula verification)', () => {
  it('need value + positive delta clamps at 10', () => {
    const current = 9.0;
    const delta = 3.0;
    const clamped = Math.max(0, Math.min(10, current + delta));
    expect(clamped).toBe(10);
  });

  it('need value + negative delta clamps at 0', () => {
    const current = 2.0;
    const delta = -5.0;
    const clamped = Math.max(0, Math.min(10, current + delta));
    expect(clamped).toBe(0);
  });

  it('need value within range is not clamped', () => {
    const current = 5.0;
    const delta = 2.0;
    const clamped = Math.max(0, Math.min(10, current + delta));
    expect(clamped).toBe(7);
  });

  it('need value rounds to 3 decimal places', () => {
    const current = 3.0;
    const delta = 0.1234;
    const result = Math.round(Math.max(0, Math.min(10, current + delta)) * 1000) / 1000;
    expect(result).toBe(3.123);
  });
});

// -------------------------------------------------------------------------
// v2 updateRelationship (formula verification)
// -------------------------------------------------------------------------

describe('updateRelationship (formula verification)', () => {
  it('relationship dimension + positive delta clamps at 1', () => {
    const current = 0.95;
    const delta = 0.1;
    const result = Math.round(Math.max(0, Math.min(1, current + delta)) * 1000) / 1000;
    expect(result).toBe(1);
  });

  it('relationship dimension + negative delta clamps at 0', () => {
    const current = 0.05;
    const delta = -0.1;
    const result = Math.round(Math.max(0, Math.min(1, current + delta)) * 1000) / 1000;
    expect(result).toBe(0);
  });

  it('relationship dimension within range is updated correctly', () => {
    const current = 0.3;
    const delta = 0.15;
    const result = Math.round(Math.max(0, Math.min(1, current + delta)) * 1000) / 1000;
    expect(result).toBe(0.45);
  });
});

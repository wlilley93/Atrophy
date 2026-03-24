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

function makeState(overrides?: Partial<EmotionalState>): EmotionalState {
  return {
    emotions: {
      connection: 0.5,
      curiosity: 0.6,
      confidence: 0.5,
      warmth: 0.5,
      frustration: 0.1,
      playfulness: 0.3,
    },
    trust: {
      emotional: 0.5,
      intellectual: 0.5,
      creative: 0.5,
      practical: 0.5,
    },
    session_tone: null,
    last_updated: new Date().toISOString(),
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
      emotions: { connection: 0.8, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.1, playfulness: 0.3 },
    });
    const output = formatForContext(state);
    expect(output).toContain('present, engaged');
  });

  it('uses correct label for mid connection (0.4-0.7)', () => {
    const state = makeState({
      emotions: { connection: 0.5, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.1, playfulness: 0.3 },
    });
    const output = formatForContext(state);
    expect(output).toContain('steady');
  });

  it('uses correct label for low connection (< 0.4)', () => {
    const state = makeState({
      emotions: { connection: 0.2, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.1, playfulness: 0.3 },
    });
    const output = formatForContext(state);
    expect(output).toContain('withdrawn');
  });

  it('uses "frustrated" label for high frustration (>= 0.6)', () => {
    const state = makeState({
      emotions: { connection: 0.5, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.7, playfulness: 0.3 },
    });
    const output = formatForContext(state);
    expect(output).toContain('frustrated');
  });

  it('uses "calm" label for low frustration (< 0.3)', () => {
    const state = makeState({
      emotions: { connection: 0.5, curiosity: 0.6, confidence: 0.5, warmth: 0.5, frustration: 0.1, playfulness: 0.3 },
    });
    const output = formatForContext(state);
    expect(output).toContain('calm');
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
    expect(EMOTION_HALF_LIVES.connection).toBe(8);
    expect(EMOTION_HALF_LIVES.amusement).toBe(2);
    expect(EMOTION_HALF_LIVES.focus).toBe(2);
    expect(EMOTION_HALF_LIVES.satisfaction).toBe(6);
    expect(EMOTION_HALF_LIVES.melancholy).toBe(8);
    expect(EMOTION_HALF_LIVES.restlessness).toBe(3);
    expect(EMOTION_HALF_LIVES.defiance).toBe(3);
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

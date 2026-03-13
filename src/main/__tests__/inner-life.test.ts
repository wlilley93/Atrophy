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

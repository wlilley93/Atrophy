/**
 * Tests for inner-life-compress.ts
 *
 * compressForContext is tested without filesystem access by mocking
 * saveState from inner-life.ts (transitively required by inner-life-needs.ts).
 */

import { describe, it, expect, vi } from 'vitest';
import { compressForContext } from '../inner-life-compress';
import { DEFAULT_FULL_STATE } from '../inner-life-types';
import type { FullState } from '../inner-life-types';

// Mock saveState so tests do not touch the filesystem or require config.
vi.mock('../inner-life', () => ({
  saveState: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeState(overrides?: Partial<FullState>): FullState {
  return { ...DEFAULT_FULL_STATE(), ...overrides };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('compressForContext', () => {
  it('returns baseline string when all values are at defaults', () => {
    const state = makeState();
    const result = compressForContext(state);
    expect(result).toBe('[state: baseline, nothing notable]');
  });

  it('includes only emotions that deviate > 0.1 from baseline', () => {
    // connection baseline is 0.5; set to 0.85 (deviation of 0.35)
    const state = makeState({
      emotions: { ...DEFAULT_FULL_STATE().emotions, connection: 0.85 },
    });
    const result = compressForContext(state);
    expect(result).toContain('conn:0.85');
  });

  it('does NOT include emotions at baseline', () => {
    // connection baseline is 0.5; set to 0.55 (deviation of 0.05, within threshold)
    const state = makeState({
      emotions: { ...DEFAULT_FULL_STATE().emotions, connection: 0.55 },
    });
    const result = compressForContext(state);
    expect(result).not.toContain('conn:');
    expect(result).toBe('[state: baseline, nothing notable]');
  });

  it('includes unmet needs (value < 3)', () => {
    const state = makeState({
      needs: { ...DEFAULT_FULL_STATE().needs, novelty: 2 },
    });
    const result = compressForContext(state);
    expect(result).toContain('needs');
    expect(result).toContain('nov:2');
  });

  it('does NOT include met needs (value >= 3)', () => {
    // Default needs are all 5, which is met
    const state = makeState();
    const result = compressForContext(state);
    expect(result).not.toContain('needs');
  });

  it('includes active drives derived from unmet needs', () => {
    // Low stimulation (<=3) + high curiosity triggers "seeking-new-topics"
    const state = makeState({
      needs: { ...DEFAULT_FULL_STATE().needs, stimulation: 1 },
      emotions: { ...DEFAULT_FULL_STATE().emotions, curiosity: 0.9 },
    });
    const result = compressForContext(state);
    expect(result).toContain('drives:');
    expect(result).toContain('seeking-new-topics');
  });

  it('does not include drives when all needs are met', () => {
    // All needs at 5, no drives should fire
    const state = makeState();
    const result = compressForContext(state);
    expect(result).not.toContain('drives:');
  });

  it('includes personality and relationship on session start', () => {
    // Default personality has warmth_default: 0.6 (exactly 0.6, NOT > 0.6, so no "warm")
    // and depth_preference: 0.7 (exactly 0.7, NOT > 0.7, so no "deep")
    // assertiveness: 0.6 (NOT > 0.6), directness: 0.65 (> 0.6 -> "direct")
    // patience: 0.6 (NOT > 0.6)
    // So we expect "direct" at minimum from defaults.
    // relationship defaults: familiarity 0.3 (NOT > 0.3), rapport 0.3 (NOT > 0.3),
    //   reliability 0.5 (> 0.3), boundaries 0.5 (> 0.3)
    const state = makeState();
    const result = compressForContext(state, { sessionStart: true });
    // Should contain personality section
    expect(result).toContain('personality:');
    // directness 0.65 > 0.6 -> "direct"
    expect(result).toContain('direct');
    // reliability 0.5 > 0.3 -> in relationship section
    expect(result).toContain('relationship');
    expect(result).toContain('rel:0.5');
  });

  it('omits personality and relationship on non-session-start', () => {
    // Elevate an emotion so we don't hit the baseline fallback
    const state = makeState({
      emotions: { ...DEFAULT_FULL_STATE().emotions, connection: 0.85 },
    });
    const result = compressForContext(state);
    expect(result).not.toContain('personality:');
    expect(result).not.toContain('relationship');
  });

  it('output is under 100 chars for typical active conversation', () => {
    const state = makeState({
      emotions: { ...DEFAULT_FULL_STATE().emotions, connection: 0.85, warmth: 0.90 },
      needs: { ...DEFAULT_FULL_STATE().needs, novelty: 2 },
    });
    const result = compressForContext(state);
    expect(result.length).toBeLessThan(100);
  });

  it('limits drives to top 3', () => {
    // Deplete many needs to trigger multiple drives
    const base = DEFAULT_FULL_STATE();
    const state = makeState({
      needs: {
        ...base.needs,
        stimulation: 1,
        purpose: 1,
        novelty: 1,
        social: 1,
        rest: 1,
        expression: 1,
        autonomy: 1,
        recognition: 1,
      },
      emotions: {
        ...base.emotions,
        curiosity: 0.9,
        restlessness: 0.9,
      },
    });
    const result = compressForContext(state);
    const drivesMatch = result.match(/drives: ([^|]+)/);
    if (drivesMatch) {
      const driveList = drivesMatch[1].trim().split(', ');
      expect(driveList.length).toBeLessThanOrEqual(3);
    }
  });

  it('formats trust section only for deviating domains', () => {
    // personal default is 0.5; raise to 0.6 (deviation 0.1 > 0.05)
    const state = makeState({
      trust: { ...DEFAULT_FULL_STATE().trust, personal: 0.60 },
    });
    const result = compressForContext(state);
    expect(result).toContain('trust');
    expect(result).toContain('pe:0.60');
  });

  it('does NOT include trust section when all trust values are at default', () => {
    const state = makeState();
    const result = compressForContext(state);
    expect(result).not.toContain('trust');
  });
});

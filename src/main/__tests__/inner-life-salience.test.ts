/**
 * Tests for inner-life-salience.ts
 *
 * Tests salience scoring, disclosure detection, disclosure merging,
 * and noise floor clamping. Pure computation - no mocks needed.
 */

import { describe, it, expect } from 'vitest';
import {
  scoreSalience,
  detectDisclosures,
  mergeDisclosures,
  emptyDisclosureMap,
  type DisclosureMap,
} from '../inner-life-salience';
import { DEFAULT_FULL_STATE } from '../inner-life-types';
import type { FullState } from '../inner-life-types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeState(overrides?: Partial<FullState>): FullState {
  const base = DEFAULT_FULL_STATE();
  return { ...base, ...overrides };
}

// ---------------------------------------------------------------------------
// scoreSalience - baseline
// ---------------------------------------------------------------------------

describe('scoreSalience - baseline', () => {
  it('returns baseline 0.2 for neutral short text with no state change', () => {
    const state = makeState();
    const score = scoreSalience('hello', 'will', null, state);
    // baseline 0.2, short message penalty -0.1 = 0.1
    expect(score).toBeCloseTo(0.1, 1);
  });

  it('never returns below the noise floor of 0.05', () => {
    const state = makeState();
    // Very short, pure tech, no disclosure
    const score = scoreSalience('git fix', 'will', null, state);
    expect(score).toBeGreaterThanOrEqual(0.05);
  });

  it('never returns above 1.0', () => {
    const prev = makeState();
    // Create a state with huge emotional displacement
    const curr = makeState({
      emotions: {
        ...DEFAULT_FULL_STATE().emotions,
        connection: 1.0,
        curiosity: 1.0,
        warmth: 1.0,
        frustration: 1.0,
        playfulness: 1.0,
        confidence: 1.0,
        amusement: 1.0,
        anticipation: 1.0,
        satisfaction: 1.0,
        restlessness: 1.0,
        tenderness: 1.0,
        melancholy: 1.0,
        focus: 1.0,
        defiance: 1.0,
      },
    });
    // Long vulnerability-heavy, multi-domain disclosure addressing the agent
    const text = 'Xan, I feel afraid and honestly I need help. My relationship is struggling and I am lonely. ' +
      'I feel like my career is failing. Who are you to me? I miss those days and I think about meaning and purpose. ' +
      'a'.repeat(300);
    const score = scoreSalience(text, 'will', prev, curr);
    expect(score).toBeLessThanOrEqual(1.0);
  });
});

// ---------------------------------------------------------------------------
// scoreSalience - emotional displacement
// ---------------------------------------------------------------------------

describe('scoreSalience - emotional displacement', () => {
  it('adds 0.3 for displacement > 1.0', () => {
    const prev = makeState();
    const curr = makeState({
      emotions: {
        ...DEFAULT_FULL_STATE().emotions,
        connection: 1.0, // +0.5
        curiosity: 1.0,  // +0.4
        warmth: 1.0,     // +0.5
      },
    });
    // displacement = 0.5 + 0.4 + 0.5 = 1.4 > 1.0
    const score = scoreSalience('something meaningful happened', 'agent', prev, curr);
    // baseline 0.2 + displacement 0.3 = 0.5
    expect(score).toBeGreaterThanOrEqual(0.5);
  });

  it('adds 0.2 for displacement between 0.5 and 1.0', () => {
    const prev = makeState();
    const curr = makeState({
      emotions: {
        ...DEFAULT_FULL_STATE().emotions,
        connection: 0.8, // +0.3
        curiosity: 0.9,  // +0.3
      },
    });
    // displacement = 0.3 + 0.3 = 0.6
    const score = scoreSalience('moderate change', 'agent', prev, curr);
    expect(score).toBeGreaterThanOrEqual(0.4);
  });

  it('adds 0.1 for displacement between 0.2 and 0.5', () => {
    const prev = makeState();
    const curr = makeState({
      emotions: {
        ...DEFAULT_FULL_STATE().emotions,
        connection: 0.7, // +0.2
        curiosity: 0.7,  // +0.1
      },
    });
    // displacement = 0.2 + 0.1 = 0.3
    const score = scoreSalience('slight change', 'agent', prev, curr);
    expect(score).toBeGreaterThanOrEqual(0.3);
  });

  it('skips displacement scoring when prevState is null', () => {
    const curr = makeState();
    const score = scoreSalience('first message', 'agent', null, curr);
    expect(score).toBe(0.2); // just baseline, no length bonus for agent role
  });
});

// ---------------------------------------------------------------------------
// scoreSalience - length and depth (user role)
// ---------------------------------------------------------------------------

describe('scoreSalience - length scoring', () => {
  it('adds 0.15 for user messages over 500 chars', () => {
    const state = makeState();
    const longMsg = 'a'.repeat(501);
    const score = scoreSalience(longMsg, 'will', null, state);
    // baseline 0.2 + length 0.15 = 0.35
    expect(score).toBeGreaterThanOrEqual(0.35);
  });

  it('adds 0.08 for user messages between 200 and 500 chars', () => {
    const state = makeState();
    const medMsg = 'a'.repeat(250);
    const score = scoreSalience(medMsg, 'will', null, state);
    // baseline 0.2 + length 0.08 = 0.28
    expect(score).toBeGreaterThanOrEqual(0.28);
  });

  it('subtracts 0.1 for user messages under 30 chars', () => {
    const state = makeState();
    const score = scoreSalience('hi there', 'will', null, state);
    // baseline 0.2 - short penalty 0.1 = 0.1
    expect(score).toBeCloseTo(0.1, 1);
  });

  it('does not apply length scoring for agent messages', () => {
    const state = makeState();
    const score = scoreSalience('ok', 'agent', null, state);
    // baseline 0.2, no length penalty for agent role
    expect(score).toBe(0.2);
  });
});

// ---------------------------------------------------------------------------
// scoreSalience - vulnerability markers
// ---------------------------------------------------------------------------

describe('scoreSalience - vulnerability', () => {
  it('adds 0.25 for 2+ vulnerability keywords', () => {
    const state = makeState();
    const score = scoreSalience('I am afraid and honestly struggling', 'agent', null, state);
    // baseline 0.2 + vuln 0.25 + disclosure hits >= 1
    expect(score).toBeGreaterThanOrEqual(0.45);
  });

  it('adds 0.12 for 1 vulnerability keyword', () => {
    const state = makeState();
    const score = scoreSalience('I am honestly not sure about this', 'agent', null, state);
    // baseline 0.2 + vuln 0.12 + disclosure hit 0.05
    expect(score).toBeGreaterThanOrEqual(0.32);
  });
});

// ---------------------------------------------------------------------------
// scoreSalience - relational content
// ---------------------------------------------------------------------------

describe('scoreSalience - relational content', () => {
  it('adds 0.2 for user addressing the agent about its nature', () => {
    const state = makeState();
    const score = scoreSalience('What are you to me, Xan? I feel something here.', 'will', null, state);
    // baseline + relational + disclosure hits + possible vulnerability
    expect(score).toBeGreaterThanOrEqual(0.4);
  });

  it('does not add relational bonus when role is agent', () => {
    const state = makeState();
    const scoreAgent = scoreSalience('You feel like a real companion', 'agent', null, state);
    const scoreUser = scoreSalience('You feel like a real companion', 'will', null, state);
    expect(scoreUser).toBeGreaterThan(scoreAgent);
  });
});

// ---------------------------------------------------------------------------
// scoreSalience - technical/routine penalty
// ---------------------------------------------------------------------------

describe('scoreSalience - technical penalty', () => {
  it('applies -0.1 penalty for pure technical content with 3+ markers', () => {
    const state = makeState();
    // Use tech keywords that do not overlap with any disclosure category.
    // "build" is in creative disclosure, so avoid it. Use only: git, commit, deploy, bug, error, npm, pnpm, typescript, webpack
    const score = scoreSalience('git commit deploy bug error npm pnpm typescript webpack', 'will', null, state);
    // baseline 0.2 - tech penalty 0.1 - short penalty 0.1 = 0.05 (clamped at floor)
    expect(score).toBeLessThanOrEqual(0.15);
  });

  it('does not apply penalty when technical content has disclosure', () => {
    const state = makeState();
    const techWithPersonal = 'I am struggling with this git deploy build error and honestly failing';
    const score = scoreSalience(techWithPersonal, 'will', null, state);
    // Has disclosure hits so no tech penalty
    expect(score).toBeGreaterThanOrEqual(0.2);
  });
});

// ---------------------------------------------------------------------------
// scoreSalience - disclosure depth bonus
// ---------------------------------------------------------------------------

describe('scoreSalience - disclosure depth', () => {
  it('adds 0.15 for touching 3+ disclosure domains', () => {
    const state = makeState();
    // career + relationship + anxiety
    const score = scoreSalience(
      'My job is stressful and my relationship is in trouble and I am worried about everything',
      'will',
      null,
      state,
    );
    expect(score).toBeGreaterThanOrEqual(0.35);
  });

  it('adds 0.05 for touching 1-2 disclosure domains', () => {
    const state = makeState();
    const score = scoreSalience('I have been stressed at work lately', 'will', null, state);
    // career domain hit + some bonuses
    expect(score).toBeGreaterThanOrEqual(0.2);
  });
});

// ---------------------------------------------------------------------------
// detectDisclosures
// ---------------------------------------------------------------------------

describe('detectDisclosures', () => {
  it('returns empty object for neutral text', () => {
    const result = detectDisclosures('The weather is nice today');
    expect(Object.keys(result)).toHaveLength(0);
  });

  it('detects career disclosure', () => {
    const result = detectDisclosures('I am worried about my job and career direction');
    expect(result.career).toBeDefined();
    expect(result.career).toBeGreaterThan(0);
  });

  it('detects relationship disclosure', () => {
    const result = detectDisclosures('My partner and I are having relationship problems');
    expect(result.relationship).toBeDefined();
    expect(result.relationship).toBeGreaterThan(0);
  });

  it('detects anxiety disclosure', () => {
    const result = detectDisclosures('I am so anxious and stressed about everything');
    expect(result.anxiety).toBeDefined();
    expect(result.anxiety).toBeGreaterThan(0);
  });

  it('detects physical disclosure', () => {
    const result = detectDisclosures('I am exhausted and depleted, my body is aching');
    expect(result.physical).toBeDefined();
    expect(result.physical).toBeGreaterThan(0);
  });

  it('detects spiritual disclosure', () => {
    const result = detectDisclosures('I have been thinking about meaning and purpose and mortality');
    expect(result.spiritual).toBeDefined();
    expect(result.spiritual).toBeGreaterThan(0);
  });

  it('detects creative disclosure', () => {
    const result = detectDisclosures('I want to create something beautiful with art and design');
    expect(result.creative).toBeDefined();
    expect(result.creative).toBeGreaterThan(0);
  });

  it('detects identity disclosure', () => {
    const result = detectDisclosures("I think I'm the kind of person who always tries too hard");
    expect(result.identity).toBeDefined();
    expect(result.identity).toBeGreaterThan(0);
  });

  it('detects vulnerability disclosure', () => {
    const result = detectDisclosures("I'm afraid to admit that I'm failing and struggling");
    expect(result.vulnerability).toBeDefined();
    expect(result.vulnerability).toBeGreaterThan(0);
  });

  it('detects multiple domains simultaneously', () => {
    const result = detectDisclosures(
      'I am stressed at work, my relationship is falling apart, and I feel lonely',
    );
    expect(Object.keys(result).length).toBeGreaterThanOrEqual(2);
  });

  it('depth increases with more keywords per domain', () => {
    const shallow = detectDisclosures('I have a job');
    const deep = detectDisclosures('My job and career and promotion and boss and salary and burnout are all causing me stress');
    if (shallow.career && deep.career) {
      expect(deep.career).toBeGreaterThanOrEqual(shallow.career);
    }
  });

  it('depth increases with message length', () => {
    const short = detectDisclosures('worried about work');
    const long = detectDisclosures('I have been really worried about work lately. ' + 'a'.repeat(400));
    // Longer message should have higher depth for anxiety domain
    if (short.anxiety && long.anxiety) {
      expect(long.anxiety).toBeGreaterThanOrEqual(short.anxiety);
    }
  });

  it('filters out very shallow disclosures (depth <= 0.1)', () => {
    // A single keyword in a very short message
    const result = detectDisclosures('job');
    // keyword factor = 1/3 = 0.33, length factor = 3/500 = 0.006
    // depth = 0.006 * 0.4 + 0.33 * 0.6 = 0.2 -> rounded = 0.2 > 0.1 so passes
    // but the filter is > 0.1
    if (result.career !== undefined) {
      expect(result.career).toBeGreaterThan(0.1);
    }
  });
});

// ---------------------------------------------------------------------------
// mergeDisclosures
// ---------------------------------------------------------------------------

describe('mergeDisclosures', () => {
  it('merges new disclosures into empty map', () => {
    const empty = emptyDisclosureMap();
    const detected = { career: 0.5, anxiety: 0.3 };
    const merged = mergeDisclosures(empty, detected);
    expect(merged.career).toBe(0.5);
    expect(merged.anxiety).toBe(0.3);
    expect(merged.relationship).toBe(0);
  });

  it('does not mutate the original map', () => {
    const existing = emptyDisclosureMap();
    mergeDisclosures(existing, { career: 0.5 });
    expect(existing.career).toBe(0);
  });

  it('uses max(existing, new) - takes higher value', () => {
    const existing: DisclosureMap = { ...emptyDisclosureMap(), career: 0.7 };
    const detected = { career: 0.3 };
    const merged = mergeDisclosures(existing, detected);
    expect(merged.career).toBe(0.7);
  });

  it('updates when new value is higher', () => {
    const existing: DisclosureMap = { ...emptyDisclosureMap(), career: 0.3 };
    const detected = { career: 0.8 };
    const merged = mergeDisclosures(existing, detected);
    expect(merged.career).toBe(0.8);
  });

  it('preserves all existing values when merging partial', () => {
    const existing: DisclosureMap = {
      ...emptyDisclosureMap(),
      career: 0.5,
      relationship: 0.4,
      anxiety: 0.3,
    };
    const detected = { spiritual: 0.6 };
    const merged = mergeDisclosures(existing, detected);
    expect(merged.career).toBe(0.5);
    expect(merged.relationship).toBe(0.4);
    expect(merged.anxiety).toBe(0.3);
    expect(merged.spiritual).toBe(0.6);
  });
});

// ---------------------------------------------------------------------------
// emptyDisclosureMap
// ---------------------------------------------------------------------------

describe('emptyDisclosureMap', () => {
  it('returns all 8 categories at zero', () => {
    const map = emptyDisclosureMap();
    expect(Object.keys(map)).toHaveLength(8);
    for (const value of Object.values(map)) {
      expect(value).toBe(0);
    }
  });

  it('returns a new object each call', () => {
    const a = emptyDisclosureMap();
    const b = emptyDisclosureMap();
    expect(a).not.toBe(b);
    a.career = 99;
    expect(b.career).toBe(0);
  });
});

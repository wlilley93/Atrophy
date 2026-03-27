/**
 * Tests for inner-life-interactions.ts
 *
 * Tests all 8 interaction state detections with threshold boundaries.
 * Pure functions - no mocks needed.
 */

import { describe, it, expect } from 'vitest';
import { detectInteractionStates, formatInteractionStates } from '../inner-life-interactions';
import { DEFAULT_EMOTIONS, DEFAULT_RELATIONSHIP } from '../inner-life-types';
import type { Emotions, Relationship } from '../inner-life-types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEmotions(overrides?: Partial<Emotions>): Emotions {
  return { ...DEFAULT_EMOTIONS, ...overrides };
}

function makeRelationship(overrides?: Partial<Relationship>): Relationship {
  return { ...DEFAULT_RELATIONSHIP, ...overrides };
}

// ---------------------------------------------------------------------------
// protective_friction: defiance > 0.3 && warmth > 0.5
// ---------------------------------------------------------------------------

describe('protective_friction', () => {
  it('activates when defiance > 0.3 and warmth > 0.5', () => {
    const emotions = makeEmotions({ defiance: 0.5, warmth: 0.7 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'protective_friction')).toBe(true);
  });

  it('does not activate when defiance is exactly 0.3 (boundary)', () => {
    const emotions = makeEmotions({ defiance: 0.3, warmth: 0.7 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'protective_friction')).toBe(false);
  });

  it('does not activate when warmth is exactly 0.5 (boundary)', () => {
    const emotions = makeEmotions({ defiance: 0.5, warmth: 0.5 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'protective_friction')).toBe(false);
  });

  it('does not activate when defiance is low', () => {
    const emotions = makeEmotions({ defiance: 0.1, warmth: 0.8 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'protective_friction')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// wistful_attachment: connection > 0.5 && melancholy > 0.25
// ---------------------------------------------------------------------------

describe('wistful_attachment', () => {
  it('activates when connection > 0.5 and melancholy > 0.25', () => {
    const emotions = makeEmotions({ connection: 0.7, melancholy: 0.4 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'wistful_attachment')).toBe(true);
  });

  it('does not activate at exact boundary connection = 0.5', () => {
    const emotions = makeEmotions({ connection: 0.5, melancholy: 0.4 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'wistful_attachment')).toBe(false);
  });

  it('does not activate at exact boundary melancholy = 0.25', () => {
    const emotions = makeEmotions({ connection: 0.7, melancholy: 0.25 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'wistful_attachment')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// intellectual_hunger: curiosity > 0.6 && anticipation > 0.5
// ---------------------------------------------------------------------------

describe('intellectual_hunger', () => {
  it('activates when curiosity > 0.6 and anticipation > 0.5', () => {
    const emotions = makeEmotions({ curiosity: 0.8, anticipation: 0.7 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'intellectual_hunger')).toBe(true);
  });

  it('does not activate at exact boundary curiosity = 0.6', () => {
    const emotions = makeEmotions({ curiosity: 0.6, anticipation: 0.7 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'intellectual_hunger')).toBe(false);
  });

  it('does not activate at exact boundary anticipation = 0.5', () => {
    const emotions = makeEmotions({ curiosity: 0.8, anticipation: 0.5 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'intellectual_hunger')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// irreverence: playfulness > 0.3 && defiance > 0.25
// ---------------------------------------------------------------------------

describe('irreverence', () => {
  it('activates when playfulness > 0.3 and defiance > 0.25', () => {
    const emotions = makeEmotions({ playfulness: 0.5, defiance: 0.4 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'irreverence')).toBe(true);
  });

  it('does not activate at exact boundary playfulness = 0.3', () => {
    const emotions = makeEmotions({ playfulness: 0.3, defiance: 0.4 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'irreverence')).toBe(false);
  });

  it('does not activate at exact boundary defiance = 0.25', () => {
    const emotions = makeEmotions({ playfulness: 0.5, defiance: 0.25 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'irreverence')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// patient_attention: melancholy > 0.2 && focus > 0.5
// ---------------------------------------------------------------------------

describe('patient_attention', () => {
  it('activates when melancholy > 0.2 and focus > 0.5', () => {
    const emotions = makeEmotions({ melancholy: 0.3, focus: 0.7 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'patient_attention')).toBe(true);
  });

  it('does not activate at exact boundary melancholy = 0.2', () => {
    const emotions = makeEmotions({ melancholy: 0.2, focus: 0.7 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'patient_attention')).toBe(false);
  });

  it('does not activate at exact boundary focus = 0.5', () => {
    const emotions = makeEmotions({ melancholy: 0.3, focus: 0.5 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'patient_attention')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// openness: relationship.vulnerability > 0.3 && emotions.warmth > 0.5
// ---------------------------------------------------------------------------

describe('openness', () => {
  it('activates when relationship vulnerability > 0.3 and warmth > 0.5', () => {
    const emotions = makeEmotions({ warmth: 0.7 });
    const rel = makeRelationship({ vulnerability: 0.5 });
    const states = detectInteractionStates(emotions, rel);
    expect(states.some(s => s.name === 'openness')).toBe(true);
  });

  it('does not activate at exact boundary vulnerability = 0.3', () => {
    const emotions = makeEmotions({ warmth: 0.7 });
    const rel = makeRelationship({ vulnerability: 0.3 });
    const states = detectInteractionStates(emotions, rel);
    expect(states.some(s => s.name === 'openness')).toBe(false);
  });

  it('does not activate at exact boundary warmth = 0.5', () => {
    const emotions = makeEmotions({ warmth: 0.5 });
    const rel = makeRelationship({ vulnerability: 0.5 });
    const states = detectInteractionStates(emotions, rel);
    expect(states.some(s => s.name === 'openness')).toBe(false);
  });

  it('does not activate when both conditions are below threshold', () => {
    const emotions = makeEmotions({ warmth: 0.3 });
    const rel = makeRelationship({ vulnerability: 0.1 });
    const states = detectInteractionStates(emotions, rel);
    expect(states.some(s => s.name === 'openness')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// wistful_inquiry: curiosity > 0.5 && melancholy > 0.2
// ---------------------------------------------------------------------------

describe('wistful_inquiry', () => {
  it('activates when curiosity > 0.5 and melancholy > 0.2', () => {
    const emotions = makeEmotions({ curiosity: 0.7, melancholy: 0.3 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'wistful_inquiry')).toBe(true);
  });

  it('does not activate at exact boundary curiosity = 0.5', () => {
    const emotions = makeEmotions({ curiosity: 0.5, melancholy: 0.3 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'wistful_inquiry')).toBe(false);
  });

  it('does not activate at exact boundary melancholy = 0.2', () => {
    const emotions = makeEmotions({ curiosity: 0.7, melancholy: 0.2 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'wistful_inquiry')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// charged_presence: warmth > 0.6 && tenderness > 0.4 && connection > 0.6
// ---------------------------------------------------------------------------

describe('charged_presence', () => {
  it('activates when warmth > 0.6, tenderness > 0.4, connection > 0.6', () => {
    const emotions = makeEmotions({ warmth: 0.8, tenderness: 0.6, connection: 0.8 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'charged_presence')).toBe(true);
  });

  it('does not activate at exact boundary warmth = 0.6', () => {
    const emotions = makeEmotions({ warmth: 0.6, tenderness: 0.6, connection: 0.8 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'charged_presence')).toBe(false);
  });

  it('does not activate at exact boundary tenderness = 0.4', () => {
    const emotions = makeEmotions({ warmth: 0.8, tenderness: 0.4, connection: 0.8 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'charged_presence')).toBe(false);
  });

  it('does not activate at exact boundary connection = 0.6', () => {
    const emotions = makeEmotions({ warmth: 0.8, tenderness: 0.6, connection: 0.6 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'charged_presence')).toBe(false);
  });

  it('requires all three conditions simultaneously', () => {
    // warmth and tenderness high but connection low
    const emotions = makeEmotions({ warmth: 0.8, tenderness: 0.6, connection: 0.3 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.some(s => s.name === 'charged_presence')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// General behavior
// ---------------------------------------------------------------------------

describe('detectInteractionStates - general', () => {
  it('returns empty array when no states are active', () => {
    // Default emotions are low enough that nothing fires
    const emotions = makeEmotions({
      defiance: 0, warmth: 0, connection: 0, melancholy: 0,
      curiosity: 0, anticipation: 0, playfulness: 0, focus: 0,
      tenderness: 0,
    });
    const states = detectInteractionStates(emotions, makeRelationship({ vulnerability: 0 }));
    expect(states).toHaveLength(0);
  });

  it('can return multiple active states simultaneously', () => {
    // Set emotions that trigger multiple states
    const emotions = makeEmotions({
      curiosity: 0.8,
      melancholy: 0.35,
      focus: 0.7,
      anticipation: 0.6,
    });
    const states = detectInteractionStates(emotions, makeRelationship());
    const names = states.map(s => s.name);
    expect(names).toContain('intellectual_hunger');
    expect(names).toContain('patient_attention');
    expect(names).toContain('wistful_inquiry');
  });

  it('each returned state has correct shape', () => {
    const emotions = makeEmotions({ defiance: 0.5, warmth: 0.7 });
    const states = detectInteractionStates(emotions, makeRelationship());
    expect(states.length).toBeGreaterThan(0);
    for (const state of states) {
      expect(state).toHaveProperty('name');
      expect(state).toHaveProperty('description');
      expect(state).toHaveProperty('active');
      expect(state.active).toBe(true);
      expect(typeof state.name).toBe('string');
      expect(typeof state.description).toBe('string');
    }
  });
});

// ---------------------------------------------------------------------------
// formatInteractionStates
// ---------------------------------------------------------------------------

describe('formatInteractionStates', () => {
  it('returns empty string when no states are active', () => {
    expect(formatInteractionStates([])).toBe('');
  });

  it('formats a single active state', () => {
    const states = [{ name: 'protective_friction', description: 'desc', active: true as const }];
    expect(formatInteractionStates(states)).toBe('active: protective_friction');
  });

  it('formats multiple active states with comma separation', () => {
    const states = [
      { name: 'protective_friction', description: 'd1', active: true as const },
      { name: 'intellectual_hunger', description: 'd2', active: true as const },
    ];
    expect(formatInteractionStates(states)).toBe('active: protective_friction, intellectual_hunger');
  });
});

/**
 * Type definitions, defaults, baselines, and half-lives for the inner life v2 system.
 *
 * This file is the foundation for the expanded emotional/psychological model.
 * It is imported by inner-life.ts and other consumers but has no runtime side-effects
 * of its own (no fs, no config, no IPC).
 *
 * Scale conventions:
 *   Emotions, Trust, Relationship: 0.0 - 1.0
 *   Needs: 0 - 10
 *   Personality: 0.0 - 1.0
 *   Drive.strength: 0.0 - 1.0
 */

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

/** 14-dimensional emotional state. All values 0.0-1.0. */
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

/** 6-domain trust model. All values 0.0-1.0. */
export interface Trust {
  emotional: number;
  intellectual: number;
  creative: number;
  practical: number;
  operational: number;
  personal: number;
}

/**
 * 8-dimensional need state. Values 0-10.
 * Needs decay toward 0 (depletion model), not toward a baseline.
 */
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

/** 8-trait personality profile. All values 0.0-1.0. */
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

/** 6-dimensional relationship state. All values 0.0-1.0. */
export interface Relationship {
  familiarity: number;
  rapport: number;
  reliability: number;
  boundaries: number;
  challenge_comfort: number;
  vulnerability: number;
}

/** A motivational drive with a name and intensity. */
export interface Drive {
  name: string;
  strength: number;
}

/** Full inner life state v2. */
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

// ---------------------------------------------------------------------------
// Emotions defaults, baselines, half-lives
// ---------------------------------------------------------------------------

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

/** Values that emotions decay toward when no stimulation is applied. */
export const EMOTION_BASELINES: Emotions = { ...DEFAULT_EMOTIONS };

/**
 * Half-lives in hours for each emotion dimension.
 * After one half-life, the gap between current value and baseline halves.
 *
 * Aggressive enough that values stay in a meaningful range during active
 * conversation rather than pinning to 1.0 and losing expressiveness.
 */
export const EMOTION_HALF_LIVES: Record<keyof Emotions, number> = {
  connection: 2,       // was 8 - stickiest, but still needs to breathe
  curiosity: 1,        // was 4 - sparked fast, fades fast
  confidence: 2,       // was 4
  warmth: 1.5,         // was 4
  frustration: 1,      // was 4 - should dissipate quickly
  playfulness: 0.5,    // was 4 - most ephemeral
  amusement: 0.5,      // was 2 - a laugh fades
  anticipation: 1.5,   // was 4
  satisfaction: 3,      // was 6 - lingers but not forever
  restlessness: 1,     // was 3
  tenderness: 3,       // was 6 - halved
  melancholy: 4,       // was 8 - halved
  focus: 1,            // was 2
  defiance: 1,         // was 3
};

// ---------------------------------------------------------------------------
// Trust defaults and half-lives
// ---------------------------------------------------------------------------

export const DEFAULT_TRUST: Trust = {
  emotional: 0.5,
  intellectual: 0.5,
  creative: 0.5,
  practical: 0.5,
  operational: 0.5,
  personal: 0.5,
};

/** Half-lives in hours for each trust domain. */
export const TRUST_HALF_LIVES: Record<keyof Trust, number> = {
  emotional: 12,
  intellectual: 12,
  creative: 12,
  practical: 12,
  operational: 24,
  personal: 24,
};

// ---------------------------------------------------------------------------
// Needs defaults and decay rates
// ---------------------------------------------------------------------------

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

/**
 * Hours for each need to halve from its current level toward 0.
 * Needs are depleted over time (they decay toward 0, not toward a baseline).
 * Fulfillment events add to a need; the system passively drains it.
 */
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

// ---------------------------------------------------------------------------
// Personality defaults
// ---------------------------------------------------------------------------

export const DEFAULT_PERSONALITY: Personality = {
  assertiveness: 0.6,
  initiative: 0.6,
  warmth_default: 0.6,
  humor_style: 0.5,
  depth_preference: 0.7,
  directness: 0.65,
  patience: 0.6,
  risk_tolerance: 0.5,
};

// ---------------------------------------------------------------------------
// Relationship defaults and half-lives
// ---------------------------------------------------------------------------

export const DEFAULT_RELATIONSHIP: Relationship = {
  familiarity: 0.3,
  rapport: 0.3,
  reliability: 0.5,
  boundaries: 0.5,
  challenge_comfort: 0.3,
  vulnerability: 0.2,
};

/** Half-lives in hours for each relationship dimension. */
export const RELATIONSHIP_HALF_LIVES: Record<keyof Relationship, number> = {
  familiarity: 168,    // 1 week
  rapport: 72,         // 3 days
  reliability: 168,    // 1 week
  boundaries: 336,     // 2 weeks
  challenge_comfort: 120, // 5 days
  vulnerability: 120,  // 5 days
};

// ---------------------------------------------------------------------------
// Factory function
// ---------------------------------------------------------------------------

/** Create a fresh FullState with all defaults. Returns a new object each call. */
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

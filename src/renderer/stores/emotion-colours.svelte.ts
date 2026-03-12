/**
 * Emotion-to-colour mapping for the orb avatar.
 *
 * Classifies response text into discrete emotion types, each with an
 * associated HSL colour. The OrbAvatar reads the active emotion colour
 * and blends it into its rendering. After a reaction, the colour reverts
 * to the default after REVERT_TIMEOUT_MS.
 *
 * Ported from: source_repo/display/emotion_colour.py
 */

// -- Types --

export type EmotionType =
  | 'thinking'
  | 'alert'
  | 'frustrated'
  | 'positive'
  | 'cautious'
  | 'reflective';

export interface EmotionSpec {
  colour: HSLColour;
  clip: string;
  keywords: string[];
}

export interface HSLColour {
  h: number;
  s: number;
  l: number;
}

// -- Colour palette --

const COLOURS: Record<string, HSLColour> = {
  blue: { h: 220, s: 50, l: 20 },
  dark_blue: { h: 230, s: 40, l: 15 },
  red: { h: 0, s: 60, l: 25 },
  green: { h: 140, s: 45, l: 22 },
  orange: { h: 30, s: 55, l: 25 },
  purple: { h: 270, s: 45, l: 22 },
};

// -- Emotion definitions --

export const EMOTIONS: Record<EmotionType, EmotionSpec> = {
  thinking: {
    colour: COLOURS.dark_blue,
    clip: 'idle_hover',
    keywords: [], // triggered programmatically, not by text
  },
  alert: {
    colour: COLOURS.red,
    clip: 'pulse_intense',
    keywords: [
      'warning', 'danger', 'urgent', 'critical', 'alert', 'immediately',
      'stop', 'protect', 'threat', 'security', 'compromised', 'breach',
      'emergency', 'do not', 'must not', 'cannot allow',
    ],
  },
  frustrated: {
    colour: COLOURS.red,
    clip: 'itch',
    keywords: [
      'error', 'failed', 'broken', 'crash', 'bug', 'wrong', 'problem',
      'issue', 'unfortunately', 'unable', "can't", "won't work",
      'frustrat', 'damn', 'annoying',
    ],
  },
  positive: {
    colour: COLOURS.green,
    clip: 'drift_close',
    keywords: [
      'done', 'complete', 'success', 'great', 'excellent', 'good',
      'ready', 'confirmed', 'yes', 'perfect', 'resolved', 'fixed',
      'healthy', 'growing', 'progress', 'well done', 'nice',
      'happy', 'glad', 'proud', 'love',
    ],
  },
  cautious: {
    colour: COLOURS.orange,
    clip: 'drift_lateral',
    keywords: [
      'note', 'caution', 'cost', 'price', 'pay', 'spend', 'budget',
      'careful', 'watch out', 'heads up', 'fyi', 'worth noting',
      'trade-off', 'consider', 'maybe', 'possibly', 'suggest',
      'however', 'but', 'although', 'risk',
    ],
  },
  reflective: {
    colour: COLOURS.purple,
    clip: 'crystal_shimmer',
    keywords: [
      'interesting', 'philosophical', 'wonder', 'meaning', 'think about',
      'reflects', 'deeper', 'perspective', 'soul', 'evolve', 'growth',
      'remember when', 'looking back', 'pattern', 'insight', 'curious',
      'fascinating', 'profound', 'existential', 'beautiful', 'strange',
    ],
  },
};

// -- Defaults --

export const DEFAULT_COLOUR: HSLColour = COLOURS.blue;
export const REVERT_TIMEOUT_MS = 12_000;

// -- Classifier --

/**
 * Score-based keyword classifier. Returns the best-matching emotion
 * or null if no strong signal is found.
 *
 * Scoring: each keyword hit adds `count * (1 + keyword.length / 10)`,
 * weighting longer (more specific) phrases higher. A minimum score
 * threshold of 2.0 filters out weak matches.
 */
export function classifyEmotion(text: string): EmotionType | null {
  if (!text) return null;

  const lower = text.toLowerCase();
  const scores = new Map<EmotionType, number>();

  for (const [emotion, spec] of Object.entries(EMOTIONS) as [EmotionType, EmotionSpec][]) {
    if (spec.keywords.length === 0) continue;

    let score = 0;
    for (const kw of spec.keywords) {
      let count = 0;
      let idx = lower.indexOf(kw);
      while (idx !== -1) {
        count++;
        idx = lower.indexOf(kw, idx + 1);
      }
      if (count > 0) {
        score += count * (1 + kw.length / 10);
      }
    }

    if (score > 0) {
      scores.set(emotion, score);
    }
  }

  if (scores.size === 0) return null;

  let best: EmotionType | null = null;
  let bestScore = 0;
  for (const [emotion, score] of scores) {
    if (score > bestScore) {
      bestScore = score;
      best = emotion;
    }
  }

  if (bestScore < 2.0) return null;
  return best;
}

// -- Helpers --

/** Get the (colour, clip) pair for an emotion. Returns null if unknown. */
export function getReaction(emotion: EmotionType): { colour: HSLColour; clip: string } | null {
  const spec = EMOTIONS[emotion];
  if (!spec) return null;
  return { colour: spec.colour, clip: spec.clip };
}

/** Resolve the avatar directory colour name for a given emotion. */
export function getColourDirName(emotion: EmotionType): string {
  const spec = EMOTIONS[emotion];
  if (!spec) return 'blue';
  // Reverse-lookup which named colour matches this emotion's HSL
  for (const [name, hsl] of Object.entries(COLOURS)) {
    if (hsl.h === spec.colour.h && hsl.s === spec.colour.s && hsl.l === spec.colour.l) {
      return name;
    }
  }
  return 'blue';
}

// -- Reactive state --

/** The currently active emotion (null means default/ambient). */
export const activeEmotion = $state<{ type: EmotionType | null; colour: HSLColour }>({
  type: null,
  colour: DEFAULT_COLOUR,
});

let revertTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * Set the active emotion based on response text. Starts a revert
 * timer that returns to default after REVERT_TIMEOUT_MS.
 */
export function setEmotionFromText(text: string): void {
  const emotion = classifyEmotion(text);
  if (emotion) {
    setEmotion(emotion);
  }
}

/**
 * Set a specific emotion directly (e.g. 'thinking' during inference).
 */
export function setEmotion(emotion: EmotionType): void {
  const spec = EMOTIONS[emotion];
  if (!spec) return;

  activeEmotion.type = emotion;
  activeEmotion.colour = spec.colour;

  // Reset revert timer
  if (revertTimer !== null) {
    clearTimeout(revertTimer);
  }
  revertTimer = setTimeout(revertToDefault, REVERT_TIMEOUT_MS);
}

/**
 * Revert to the default ambient colour immediately.
 */
export function revertToDefault(): void {
  if (revertTimer !== null) {
    clearTimeout(revertTimer);
    revertTimer = null;
  }
  activeEmotion.type = null;
  activeEmotion.colour = DEFAULT_COLOUR;
}

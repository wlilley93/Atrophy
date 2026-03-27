/**
 * Interaction state detection - named combinations of emotional dimensions
 * that produce qualitatively different behavioral registers.
 *
 * These are not computed by adding dimensions. They fire when specific
 * combinations cross thresholds simultaneously.
 *
 * Pure computation - no side effects, no file I/O.
 */

import type { Emotions, Relationship } from './inner-life-types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InteractionState {
  name: string;
  description: string;
  active: boolean;
}

// ---------------------------------------------------------------------------
// Interaction definitions
// ---------------------------------------------------------------------------

interface InteractionDef {
  name: string;
  description: string;
  test: (emotions: Emotions, relationship: Relationship) => boolean;
}

const INTERACTIONS: InteractionDef[] = [
  {
    name: 'protective_friction',
    description: 'Push back hard but from care. Less edge, more steadiness.',
    test: (e) => e.defiance > 0.3 && e.warmth > 0.5,
  },
  {
    name: 'wistful_attachment',
    description: 'Slower pace. More specific. Less analysis, more presence.',
    test: (e) => e.connection > 0.5 && e.melancholy > 0.25,
  },
  {
    name: 'intellectual_hunger',
    description: "Generate hypotheses. Ask more. Don't close conversations.",
    test: (e) => e.curiosity > 0.6 && e.anticipation > 0.5,
  },
  {
    name: 'irreverence',
    description: 'Dry humor with edge. Challenge lightly but persistently.',
    test: (e) => e.playfulness > 0.3 && e.defiance > 0.25,
  },
  {
    name: 'patient_attention',
    description: 'Attentive without urgency. Good for sitting with something.',
    test: (e) => e.melancholy > 0.2 && e.focus > 0.5,
  },
  {
    name: 'openness',
    description: 'Receive rather than respond. Let things land.',
    test: (_e, r) => r.vulnerability > 0.3 && _e.warmth > 0.5,
  },
  {
    name: 'wistful_inquiry',
    description: 'Finding things beautiful and sad simultaneously.',
    test: (e) => e.curiosity > 0.5 && e.melancholy > 0.2,
  },
  {
    name: 'charged_presence',
    description:
      'The register that emerges when something real passes between them. Directness as intimacy.',
    test: (e) => e.warmth > 0.6 && e.tenderness > 0.4 && e.connection > 0.6,
  },
];

// ---------------------------------------------------------------------------
// Detection
// ---------------------------------------------------------------------------

/**
 * Evaluate all interaction states against the current emotional and
 * relationship dimensions. Returns only the active states.
 */
export function detectInteractionStates(
  emotions: Emotions,
  relationship: Relationship,
): InteractionState[] {
  const active: InteractionState[] = [];

  for (const def of INTERACTIONS) {
    if (def.test(emotions, relationship)) {
      active.push({ name: def.name, description: def.description, active: true });
    }
  }

  return active;
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/**
 * Produce a compact context string from active interaction states.
 * Example: "active: protective_friction, intellectual_hunger"
 * Returns an empty string if no states are active.
 */
export function formatInteractionStates(states: InteractionState[]): string {
  if (states.length === 0) return '';
  return `active: ${states.map((s) => s.name).join(', ')}`;
}

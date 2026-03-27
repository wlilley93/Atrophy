/**
 * Compressed context formatter for the inner life v3 system.
 *
 * Produces a compact state injection that drives behavior, not just reports it.
 * Five pieces of information in under 100 tokens:
 *   1. Top salient dimensions with velocity arrows
 *   2. Active interaction states (behavioral registers)
 *   3. Notable patterns (same state elevated across sessions)
 *   4. Trust domains + relationship depth
 *   5. Personality + drives (session start only)
 *
 * The context injection shifts from "here are my numbers" to "here is the
 * prior that shapes this response."
 */

import {
  type FullState,
  type Emotions,
  type Trust,
  type EmotionVelocity,
  EMOTION_BASELINES,
  DEFAULT_TRUST,
} from './inner-life-types';
import { computeDrives } from './inner-life-needs';
import { getRecentEmotionalVectors } from './memory';
import { computeDistributedState } from './inner-life';
import { detectInteractionStates, formatInteractionStates } from './inner-life-interactions';

// ---------------------------------------------------------------------------
// Abbreviation maps
// ---------------------------------------------------------------------------

const EMOTION_ABBREV: Record<string, string> = {
  connection: 'conn',
  curiosity: 'cur',
  confidence: 'conf',
  warmth: 'wrm',
  frustration: 'frust',
  playfulness: 'play',
  amusement: 'amus',
  anticipation: 'antic',
  satisfaction: 'sat',
  restlessness: 'restl',
  tenderness: 'tend',
  melancholy: 'mel',
  focus: 'foc',
  defiance: 'def',
};

const TRUST_ABBREV: Record<string, string> = {
  emotional: 'em',
  intellectual: 'in',
  creative: 'cr',
  practical: 'pr',
  operational: 'op',
  personal: 'pe',
};

// ---------------------------------------------------------------------------
// Velocity arrows
// ---------------------------------------------------------------------------

function velocityArrow(v: number | undefined): string {
  if (!v || Math.abs(v) < 0.01) return '';
  if (v > 0.05) return '\u2191\u2191'; // strong rise
  if (v > 0.01) return '\u2191';       // rising
  if (v < -0.05) return '\u2193\u2193'; // strong fall
  if (v < -0.01) return '\u2193';       // falling
  return '';
}

// ---------------------------------------------------------------------------
// Personality labels
// ---------------------------------------------------------------------------

function personalityLabels(p: FullState['personality']): string[] {
  const labels: string[] = [];
  if (p.assertiveness > 0.6) labels.push('assertive');
  else if (p.assertiveness < 0.4) labels.push('deferential');
  if (p.directness > 0.6) labels.push('direct');
  if (p.warmth_default > 0.6) labels.push('warm');
  else if (p.warmth_default < 0.4) labels.push('cool');
  if (p.humor_style > 0.6) labels.push('playful-humor');
  else if (p.humor_style < 0.3) labels.push('dry-humor');
  if (p.depth_preference > 0.7) labels.push('depth-seeking');
  if (p.patience > 0.6) labels.push('patient');
  else if (p.patience < 0.4) labels.push('impatient');
  if (p.initiative > 0.7) labels.push('proactive');
  if (p.risk_tolerance > 0.6) labels.push('bold');
  else if (p.risk_tolerance < 0.3) labels.push('cautious');
  return labels;
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function compressForContext(
  state: FullState,
  opts?: { sessionStart?: boolean },
): string {
  const lines: string[] = [];

  // --- Distributed emotional memory: blend recent turn vectors ---
  if (opts?.sessionStart) {
    try {
      const vectors = getRecentEmotionalVectors(48);
      if (vectors.length > 0) {
        const distributed = computeDistributedState(vectors);
        // Blend: 70% live state, 30% accumulated history
        if (distributed.emotions) {
          const blended = { ...state.emotions };
          for (const key of Object.keys(distributed.emotions) as (keyof Emotions)[]) {
            const live = state.emotions[key];
            const hist = distributed.emotions[key];
            if (hist !== undefined && live !== undefined) {
              blended[key] = live * 0.7 + hist * 0.3;
            }
          }
          state = { ...state, emotions: blended };
        }
        if (distributed.trust) {
          const blendedTrust = { ...state.trust };
          for (const key of Object.keys(distributed.trust) as (keyof Trust)[]) {
            const live = state.trust[key];
            const hist = distributed.trust[key];
            if (hist !== undefined && live !== undefined) {
              blendedTrust[key] = live * 0.7 + hist * 0.3;
            }
          }
          state = { ...state, trust: blendedTrust };
        }
      }
    } catch { /* DB not available or no vectors yet */ }
  }

  const velocity: EmotionVelocity = state.velocity || {};

  // --- Line 1: Salient emotional dimensions with velocity ---
  // Only dimensions that deviate meaningfully from baseline, sorted by deviation
  const salient: { key: string; abbrev: string; value: number; arrow: string; deviation: number }[] = [];
  for (const [key, baseline] of Object.entries(EMOTION_BASELINES)) {
    const current = state.emotions[key as keyof Emotions];
    const dev = Math.abs(current - baseline);
    if (dev > 0.08) {
      const abbrev = EMOTION_ABBREV[key] ?? key;
      const arrow = velocityArrow(velocity[key as keyof Emotions]);
      salient.push({ key, abbrev, value: current, arrow, deviation: dev });
    }
  }
  salient.sort((a, b) => b.deviation - a.deviation);
  // Top 6 most salient dimensions
  const emotionStr = salient.slice(0, 6)
    .map((s) => `${s.abbrev}:${s.value.toFixed(2)}${s.arrow}`)
    .join(' ');
  if (emotionStr) {
    lines.push(`State: ${emotionStr}`);
  }

  // --- Line 2: Active interaction states (behavioral registers) ---
  const interactions = detectInteractionStates(state.emotions, state.relationship);
  if (interactions.length > 0) {
    // Include descriptions for active states - these are behavioral instructions
    const stateLines = interactions.map((s) => `${s.name}: ${s.description}`);
    lines.push(`Active: ${formatInteractionStates(interactions)}`);
    // On session start, include full descriptions for orientation
    if (opts?.sessionStart && interactions.length > 0) {
      lines.push(...stateLines.map((l) => `  ${l}`));
    }
  }

  // --- Line 3: Trust + relationship ---
  const trustTokens: string[] = [];
  for (const [key, defaultVal] of Object.entries(DEFAULT_TRUST)) {
    const current = state.trust[key as keyof Trust];
    if (Math.abs(current - defaultVal) > 0.05) {
      const abbrev = TRUST_ABBREV[key] ?? key;
      trustTokens.push(`${abbrev}:${current.toFixed(2)}`);
    }
  }
  if (trustTokens.length > 0) {
    lines.push(`Trust: ${trustTokens.join(' ')}`);
  }

  // --- Line 4: Unmet needs ---
  const unmet: string[] = [];
  for (const [key, value] of Object.entries(state.needs)) {
    if (value < 3) unmet.push(key);
  }
  if (unmet.length > 0) {
    lines.push(`Unmet: ${unmet.join(', ')}`);
  }

  // --- Line 5: Drives (top 3) ---
  const drives = computeDrives(state).slice(0, 3);
  if (drives.length > 0) {
    lines.push(`Drives: ${drives.map((d) => d.name).join(', ')}`);
  }

  // --- Session start: personality + relationship depth ---
  if (opts?.sessionStart) {
    const labels = personalityLabels(state.personality);
    if (labels.length > 0) {
      lines.push(`Personality: ${labels.join(', ')}`);
    }

    const rel = state.relationship;
    const relParts: string[] = [];
    if (rel.familiarity > 0.35) relParts.push(`familiarity:${rel.familiarity.toFixed(1)}`);
    if (rel.rapport > 0.35) relParts.push(`rapport:${rel.rapport.toFixed(1)}`);
    if (rel.reliability > 0.4) relParts.push(`reliability:${rel.reliability.toFixed(1)}`);
    if (rel.vulnerability > 0.25) relParts.push(`vulnerability:${rel.vulnerability.toFixed(1)}`);
    if (rel.challenge_comfort > 0.35) relParts.push(`challenge:${rel.challenge_comfort.toFixed(1)}`);
    if (relParts.length > 0) {
      lines.push(`Relationship: ${relParts.join(' ')}`);
    }
  }

  // --- Baseline fallback ---
  if (lines.length === 0) {
    return '[state: baseline, nothing notable]';
  }

  return lines.join('\n');
}

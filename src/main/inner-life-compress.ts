/**
 * Compressed context formatter for the inner life v2 system.
 *
 * Produces a compact state line suitable for injection into a system prompt.
 * Uses a delta-based approach: only deviations from baselines are reported,
 * keeping typical output to ~50-80 tokens.
 */

import { type FullState, EMOTION_BASELINES, DEFAULT_TRUST } from './inner-life-types';
import { computeDrives } from './inner-life-needs';

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

const NEEDS_ABBREV: Record<string, string> = {
  stimulation: 'stim',
  expression: 'expr',
  purpose: 'purp',
  autonomy: 'auto',
  recognition: 'recog',
  novelty: 'nov',
  social: 'soc',
  rest: 'rest_n',
};

// ---------------------------------------------------------------------------
// Personality label logic
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
  if (p.depth_preference > 0.7) labels.push('deep');
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
  const parts: string[] = [];

  // --- Emotions: only dimensions that deviate > 0.1 from their baseline ---
  const emotionTokens: string[] = [];
  for (const [key, baseline] of Object.entries(EMOTION_BASELINES)) {
    const current = state.emotions[key as keyof typeof state.emotions];
    if (Math.abs(current - baseline) > 0.1) {
      const abbrev = EMOTION_ABBREV[key] ?? key;
      emotionTokens.push(`${abbrev}:${current.toFixed(2)}`);
    }
  }
  if (emotionTokens.length > 0) {
    parts.push(emotionTokens.join(' '));
  }

  // --- Trust: only domains that deviate > 0.05 from their default ---
  const trustTokens: string[] = [];
  for (const [key, defaultVal] of Object.entries(DEFAULT_TRUST)) {
    const current = state.trust[key as keyof typeof state.trust];
    if (Math.abs(current - defaultVal) > 0.05) {
      const abbrev = TRUST_ABBREV[key] ?? key;
      trustTokens.push(`${abbrev}:${current.toFixed(2)}`);
    }
  }
  if (trustTokens.length > 0) {
    parts.push(`trust ${trustTokens.join(' ')}`);
  }

  // --- Needs: only needs below 3 (unmet) ---
  const needsTokens: string[] = [];
  for (const [key, value] of Object.entries(state.needs)) {
    if (value < 3) {
      const abbrev = NEEDS_ABBREV[key] ?? key;
      needsTokens.push(`${abbrev}:${Math.round(value)}`);
    }
  }
  if (needsTokens.length > 0) {
    parts.push(`needs ${needsTokens.join(' ')}`);
  }

  // --- Drives: top 3 by strength ---
  const drives = computeDrives(state).slice(0, 3);
  if (drives.length > 0) {
    parts.push(`drives: ${drives.map((d) => d.name).join(', ')}`);
  }

  // --- Session start extras ---
  if (opts?.sessionStart) {
    const labels = personalityLabels(state.personality);
    if (labels.length > 0) {
      parts.push(`personality: ${labels.join(', ')}`);
    }

    const relTokens: string[] = [];
    const rel = state.relationship;
    if (rel.familiarity > 0.3) relTokens.push(`fam:${rel.familiarity.toFixed(1)}`);
    if (rel.rapport > 0.3) relTokens.push(`rap:${rel.rapport.toFixed(1)}`);
    if (rel.reliability > 0.3) relTokens.push(`rel:${rel.reliability.toFixed(1)}`);
    if (rel.boundaries > 0.3) relTokens.push(`bnd:${rel.boundaries.toFixed(1)}`);
    if (rel.challenge_comfort > 0.3) relTokens.push(`chg:${rel.challenge_comfort.toFixed(1)}`);
    if (rel.vulnerability > 0.3) relTokens.push(`vul:${rel.vulnerability.toFixed(1)}`);

    if (relTokens.length > 0) {
      parts.push(`relationship ${relTokens.join(' ')}`);
    }
  }

  // --- Baseline fallback ---
  if (parts.length === 0) {
    return '[state: baseline, nothing notable]';
  }

  return `[state] ${parts.join(' | ')}`;
}

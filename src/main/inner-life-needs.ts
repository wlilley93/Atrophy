/**
 * Needs system for the inner life v2 model.
 *
 * Provides:
 *   satisfyNeed  - increase a need's value (clamp to [0, 10]), persist
 *   depleteNeed  - decrease a need's value (clamp to [0, 10]), persist
 *   computeDrives - derive active motivational drives from unmet needs,
 *                   personality traits, emotions, and trust
 *
 * Scale: needs are 0-10; "low" means below 3-4. Drive strength is 0-1.
 */

import { type FullState, type Needs, type Drive } from './inner-life-types';
import { saveState } from './inner-life';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function clampNeeds(v: number): number {
  return Math.max(0, Math.min(10, v));
}

// ---------------------------------------------------------------------------
// satisfyNeed
// ---------------------------------------------------------------------------

/**
 * Increase `need` by `amount`, clamp to [0, 10], save state, return updated state.
 */
export function satisfyNeed(
  state: FullState,
  need: keyof Needs,
  amount: number,
): FullState {
  const needs = { ...state.needs };
  needs[need] = clampNeeds(needs[need] + amount);
  const updated = { ...state, needs };
  saveState(updated);
  return updated;
}

// ---------------------------------------------------------------------------
// depleteNeed
// ---------------------------------------------------------------------------

/**
 * Decrease `need` by `amount`, clamp to [0, 10], save state, return updated state.
 */
export function depleteNeed(
  state: FullState,
  need: keyof Needs,
  amount: number,
): FullState {
  const needs = { ...state.needs };
  needs[need] = clampNeeds(needs[need] - amount);
  const updated = { ...state, needs };
  saveState(updated);
  return updated;
}

// ---------------------------------------------------------------------------
// computeDrives
// ---------------------------------------------------------------------------

/**
 * Compute active motivational drives from unmet needs + personality + emotions + trust.
 *
 * Drive strength formula: combines unmet-need severity (1 - value/10) with the
 * relevant personality/emotion/trust amplifier. Only drives with strength > 0.3
 * are included. Result is sorted by strength descending.
 *
 * "Low" threshold: need value below 4 (on the 0-10 scale).
 */
export function computeDrives(state: FullState): Drive[] {
  const { needs, personality, emotions, trust } = state;
  const drives: Drive[] = [];

  // Rule 1: Low stimulation + high curiosity -> "seeking-new-topics"
  if (needs.stimulation <= 3) {
    const strength = (1 - needs.stimulation / 10) * emotions.curiosity;
    if (strength > 0.3) {
      drives.push({ name: 'seeking-new-topics', strength });
    }
  }

  // Rule 2: Low purpose + high initiative -> "offering-to-help"
  if (needs.purpose <= 3) {
    const strength = (1 - needs.purpose / 10) * personality.initiative;
    if (strength > 0.3) {
      drives.push({ name: 'offering-to-help', strength });
    }
  }

  // Rule 3: Low novelty + high restlessness -> "changing-the-subject"
  if (needs.novelty <= 3) {
    const strength = (1 - needs.novelty / 10) * emotions.restlessness;
    if (strength > 0.3) {
      drives.push({ name: 'changing-the-subject', strength });
    }
  }

  // Rule 4: Low recognition + low assertiveness -> "quietly-withdrawn"
  // Both conditions compound: unmet recognition AND low assertiveness push toward withdrawal.
  // Strength: severity of unmet recognition * (1 - assertiveness) - the less assertive,
  // the stronger the withdrawal pull.
  if (needs.recognition <= 3) {
    const strength = (1 - needs.recognition / 10) * (1 - personality.assertiveness);
    if (strength > 0.3) {
      drives.push({ name: 'quietly-withdrawn', strength });
    }
  }

  // Rule 5: Low social + high warmth_default -> "reaching-out-unprompted"
  if (needs.social <= 3) {
    const strength = (1 - needs.social / 10) * personality.warmth_default;
    if (strength > 0.3) {
      drives.push({ name: 'reaching-out-unprompted', strength });
    }
  }

  // Rule 6: Low rest -> "conserving-energy"
  // No amplifier needed - rest depletion alone drives the response.
  if (needs.rest <= 3) {
    const strength = (1 - needs.rest / 10);
    if (strength > 0.3) {
      drives.push({ name: 'conserving-energy', strength });
    }
  }

  // Rule 7: Low expression + high creative trust -> "wanting-to-create"
  if (needs.expression <= 3) {
    const strength = (1 - needs.expression / 10) * trust.creative;
    if (strength > 0.3) {
      drives.push({ name: 'wanting-to-create', strength });
    }
  }

  // Rule 8: Low autonomy + high operational trust -> "acting-independently"
  if (needs.autonomy <= 3) {
    const strength = (1 - needs.autonomy / 10) * trust.operational;
    if (strength > 0.3) {
      drives.push({ name: 'acting-independently', strength });
    }
  }

  // Sort by strength descending
  drives.sort((a, b) => b.strength - a.strength);

  return drives;
}

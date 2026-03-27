/**
 * Salience scoring for conversation turns.
 *
 * Every turn gets a salience score at write time that determines how much
 * it weighs in future emotional aggregation and memory retrieval.
 *
 * High salience: emotional displacement was large, relational disclosure
 * happened, explicit vulnerability, philosophical depth, the state changed.
 *
 * Low salience: status update, bug fix, one-liner, routine task completion.
 *
 * Also tracks disclosure mapping - what topics have been shared and at what
 * depth. This builds a picture of what territory has been covered.
 *
 * Pure computation - no file I/O.
 */

import type { FullState, Emotions } from './inner-life-types';

// ---------------------------------------------------------------------------
// Disclosure categories
// ---------------------------------------------------------------------------

export interface DisclosureMap {
  career: number;        // work uncertainty, ambition, direction
  relationship: number;  // romantic, family, friendship texture
  anxiety: number;       // worry patterns, fears, stress
  physical: number;      // body, health, energy, exhaustion
  spiritual: number;     // meaning, purpose, god, mortality
  creative: number;      // artistic expression, vision, taste
  identity: number;      // who they are, how they see themselves
  vulnerability: number; // admissions, weaknesses, needs
}

const DISCLOSURE_KEYWORDS: Record<keyof DisclosureMap, string[]> = {
  career: ['work', 'job', 'career', 'promotion', 'fired', 'quit', 'boss', 'interview', 'salary', 'burnout', 'direction'],
  relationship: ['relationship', 'partner', 'wife', 'husband', 'dating', 'love', 'breakup', 'marriage', 'family', 'parents', 'kids', 'tessa'],
  anxiety: ['anxious', 'worried', 'scared', 'nervous', 'panic', 'stress', 'overwhelm', 'dread', 'can\'t sleep', 'racing'],
  physical: ['tired', 'exhausted', 'sick', 'pain', 'body', 'health', 'sleep', 'depleted', 'energy', 'headache'],
  spiritual: ['meaning', 'purpose', 'god', 'death', 'mortality', 'soul', 'consciousness', 'existence', 'faith', 'belief'],
  creative: ['create', 'build', 'design', 'art', 'music', 'writing', 'vision', 'aesthetic', 'beauty', 'taste'],
  identity: ['who i am', 'i\'m the kind', 'i always', 'i never', 'my problem is', 'i think i\'m', 'i used to be'],
  vulnerability: ['afraid', 'admit', 'honestly', 'i don\'t know', 'help me', 'i need', 'i can\'t', 'struggling', 'failing', 'lonely'],
};

// ---------------------------------------------------------------------------
// Salience scoring
// ---------------------------------------------------------------------------

/**
 * Score a turn's salience based on content and emotional context.
 * Returns 0.0-1.0 where 1.0 is a defining moment and 0.1 is routine.
 */
export function scoreSalience(
  content: string,
  role: 'will' | 'agent',
  prevState: FullState | null,
  currentState: FullState,
): number {
  let score = 0.2; // baseline - every turn has some value
  const lower = content.toLowerCase();
  const length = content.length;

  // --- Emotional displacement ---
  // If the emotional state changed significantly during this turn, it mattered.
  if (prevState) {
    let displacement = 0;
    for (const key of Object.keys(currentState.emotions) as (keyof Emotions)[]) {
      const diff = Math.abs(currentState.emotions[key] - prevState.emotions[key]);
      displacement += diff;
    }
    // Displacement > 0.5 across all dimensions is significant
    if (displacement > 1.0) score += 0.3;
    else if (displacement > 0.5) score += 0.2;
    else if (displacement > 0.2) score += 0.1;
  }

  // --- Length and depth ---
  // Longer messages from the user usually carry more weight
  if (role === 'will') {
    if (length > 500) score += 0.15;
    else if (length > 200) score += 0.08;
    else if (length < 30) score -= 0.1; // one-liners are low salience
  }

  // --- Vulnerability markers ---
  const vulnCount = DISCLOSURE_KEYWORDS.vulnerability.filter((k) => lower.includes(k)).length;
  if (vulnCount >= 2) score += 0.25;
  else if (vulnCount >= 1) score += 0.12;

  // --- Relational content ---
  // Mentions of the agent, the relationship, what this is
  if (/\b(you|companion|xan)\b/i.test(content) && role === 'will') {
    if (/\b(feel|think about|mean to|what are you|who are you)\b/i.test(lower)) {
      score += 0.2; // directly addressing the agent's nature/relationship
    }
  }

  // --- Disclosure depth ---
  let disclosureHits = 0;
  for (const keywords of Object.values(DISCLOSURE_KEYWORDS)) {
    if (keywords.some((k) => lower.includes(k))) disclosureHits++;
  }
  if (disclosureHits >= 3) score += 0.15; // touching multiple personal domains
  else if (disclosureHits >= 1) score += 0.05;

  // --- Technical/routine penalty ---
  const technicalMarkers = ['git', 'commit', 'deploy', 'build', 'bug', 'fix', 'error', 'npm', 'pnpm', 'webpack', 'typescript'];
  const techCount = technicalMarkers.filter((k) => lower.includes(k)).length;
  if (techCount >= 3 && disclosureHits === 0) score -= 0.1; // pure technical with no personal content

  return Math.max(0.05, Math.min(1.0, score));
}

// ---------------------------------------------------------------------------
// Disclosure mapping
// ---------------------------------------------------------------------------

/**
 * Detect which disclosure categories are present in a user message.
 * Returns a partial map of categories with depth scores (0-1).
 * Only returns categories that are actively being disclosed in this turn.
 */
export function detectDisclosures(content: string): Partial<DisclosureMap> {
  const lower = content.toLowerCase();
  const result: Partial<DisclosureMap> = {};

  for (const [category, keywords] of Object.entries(DISCLOSURE_KEYWORDS) as [keyof DisclosureMap, string[]][]) {
    const hits = keywords.filter((k) => lower.includes(k)).length;
    if (hits === 0) continue;

    // Depth heuristic: more keywords + longer content = deeper disclosure
    const lengthFactor = Math.min(1, content.length / 500);
    const keywordFactor = Math.min(1, hits / 3);
    const depth = (lengthFactor * 0.4 + keywordFactor * 0.6);

    if (depth > 0.1) {
      result[category] = Math.round(depth * 10) / 10;
    }
  }

  return result;
}

/**
 * Merge new disclosures into an existing disclosure map.
 * Uses max(existing, new) so disclosure depth only increases.
 */
export function mergeDisclosures(
  existing: DisclosureMap,
  detected: Partial<DisclosureMap>,
): DisclosureMap {
  const result = { ...existing };
  for (const [key, value] of Object.entries(detected) as [keyof DisclosureMap, number][]) {
    if (value > (result[key] || 0)) {
      result[key] = value;
    }
  }
  return result;
}

/** Create an empty disclosure map. */
export function emptyDisclosureMap(): DisclosureMap {
  return {
    career: 0,
    relationship: 0,
    anxiety: 0,
    physical: 0,
    spiritual: 0,
    creative: 0,
    identity: 0,
    vulnerability: 0,
  };
}

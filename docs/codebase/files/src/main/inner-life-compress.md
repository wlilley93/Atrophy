# src/main/inner-life-compress.ts - Compressed Context Formatter

**Line count:** ~150 lines  
**Dependencies:** `./inner-life-types`, `./inner-life-needs`  
**Purpose:** Produce compact state lines for system prompt injection (~50-80 tokens)

## Overview

This module implements a delta-based context formatter for the inner life v2 system. Instead of dumping all state values, it only reports deviations from baselines, keeping typical output to 50-80 tokens.

## Abbreviation Maps

### EMOTION_ABBREV

```typescript
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
```

### TRUST_ABBREV

```typescript
const TRUST_ABBREV: Record<string, string> = {
  emotional: 'em',
  intellectual: 'in',
  creative: 'cr',
  practical: 'pr',
  operational: 'op',
  personal: 'pe',
};
```

### NEEDS_ABBREV

```typescript
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
```

## Personality Labels

```typescript
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
```

**Thresholds:**
- High: > 0.6 (or > 0.7 for some traits)
- Low: < 0.4 (or < 0.3 for some traits)

## compressForContext

```typescript
export function compressForContext(
  state: FullState,
  opts?: { sessionStart?: boolean },
): string {
  const parts: string[] = [];

  // --- Emotions: only dimensions that deviate > 0.1 from baseline ---
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

  // --- Trust: only domains that deviate > 0.05 from default ---
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
    // Personality labels
    const labels = personalityLabels(state.personality);
    if (labels.length > 0) {
      parts.push(`personality: ${labels.join(', ')}`);
    }

    // Relationship dimensions (only if > 0.3)
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
```

## Compression Strategy

| Category | Threshold | Format |
|----------|-----------|--------|
| Emotions | Deviation > 0.1 from baseline | `conn:0.75 cur:0.80` |
| Trust | Deviation > 0.05 from default | `trust em:0.65 cr:0.70` |
| Needs | Value < 3 (unmet) | `needs stim:2 nov:1` |
| Drives | Top 3 by strength | `drives: seeking-new-topics, offering-to-help` |
| Personality | sessionStart only | `personality: assertive, direct, warm` |
| Relationship | sessionStart only, > 0.3 | `relationship fam:0.5 rap:0.4` |

## Example Output

### Typical active conversation

```
[state] conn:0.72 cur:0.85 frust:0.05 | trust cr:0.65 | drives: seeking-new-topics, offering-to-help
```

**Token count:** ~20 tokens

### Session start (full context)

```
[state] conn:0.72 cur:0.85 | trust cr:0.65 op:0.70 | needs stim:2 nov:1 | drives: seeking-new-topics | personality: assertive, direct, warm | relationship fam:0.5 rap:0.6 rel:0.7
```

**Token count:** ~50 tokens

### Baseline (nothing notable)

```
[state: baseline, nothing notable]
```

**Token count:** 6 tokens

## Usage in Inference

```typescript
// In inference.ts
import { compressForContext } from './inner-life-compress';

function buildAgencyContext(userMessage: string): string {
  const parts: string[] = [timeOfDayContext().context];
  
  // Compressed state injection (~50-80 tokens vs ~150-200)
  const emotionalState = loadState();
  parts.push(compressForContext(emotionalState, { sessionStart: !getAgencyState().sessionStartInjected }));
  
  // ... other context
  return parts.join('\n\n');
}
```

## Exported API

| Function | Purpose |
|----------|---------|
| `compressForContext(state, opts)` | Produce compact state line for prompt injection |

## See Also

- [`inner-life.ts`](inner-life.md) - Inner life engine
- [`inner-life-types.ts`](inner-life-types.md) - Type definitions and baselines
- [`inner-life-needs.ts`](inner-life-needs.md) - Drive computation

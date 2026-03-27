# src/main/sentinel.ts - SENTINEL Coherence Monitor

**Dependencies:** `./memory`, `./inference`, `./logger`  
**Purpose:** Mid-session coherence monitoring with automatic re-anchoring

## Overview

SENTINEL checks every 5 minutes for signs of conversational degradation:
- Repetition (same phrases/structures across recent turns)
- Drift (excessive agreeableness, losing voice)
- Energy flatness (all responses similar length)
- Vocabulary staleness (language narrowing)

When degradation is detected, it fires a silent re-anchoring turn to bring the agent back to its core identity.

## N-gram Helpers

### ngrams

```typescript
function ngrams(text: string, n: number): Set<string> {
  const words = text.toLowerCase().match(/[a-z]+/g) || [];
  if (words.length < n) return new Set();
  const result = new Set<string>();
  for (let i = 0; i <= words.length - n; i++) {
    result.add(words.slice(i, i + n).join(' '));
  }
  return result;
}
```

**Purpose:** Extract n-grams (word sequences) from text

**Example:** `"hello world test"` with n=2 → `{"hello world", "world test"}`

### ngramOverlap

```typescript
function ngramOverlap(textA: string, textB: string): number {
  const gramsA = new Set([...ngrams(textA, 2), ...ngrams(textA, 3)]);
  const gramsB = new Set([...ngrams(textB, 2), ...ngrams(textB, 3)]);
  if (gramsA.size === 0 || gramsB.size === 0) return 0;

  let intersection = 0;
  for (const g of gramsA) {
    if (gramsB.has(g)) intersection++;
  }
  const union = new Set([...gramsA, ...gramsB]).size;
  return intersection / union;
}
```

**Purpose:** Calculate Jaccard similarity between two texts using 2-grams and 3-grams

**Returns:** 0.0 (no overlap) to 1.0 (identical)

## Agreement Starters

```typescript
const AGREEMENT_STARTERS = [
  'yes', 'yeah', "that's", 'right', 'exactly', 'i agree',
  'absolutely', 'of course', 'totally', "you're right",
  'that makes sense', 'good point', 'fair', 'true',
];
```

**Purpose:** Detect excessive agreeableness (drift indicator)

## checkCoherence

```typescript
export interface CoherenceResult {
  degraded: boolean;
  signals: string[];
  score: number;
}

export function checkCoherence(recentTurns: string[]): CoherenceResult {
  const signals: string[] = [];
  const scores: number[] = [];

  if (recentTurns.length < 3) {
    return { degraded: false, signals: [], score: 0 };
  }

  const turns = recentTurns.slice(-5);

  // Check 1a: Repetition (n-gram overlap between consecutive turns)
  const overlaps: number[] = [];
  for (let i = 1; i < turns.length; i++) {
    overlaps.push(ngramOverlap(turns[i - 1], turns[i]));
  }

  const highOverlapCount = overlaps.filter((o) => o > 0.40).length;
  if (highOverlapCount > 0) {
    const worst = Math.max(...overlaps);
    signals.push(
      `Repetition detected: ${highOverlapCount} consecutive turn pair(s) ` +
      `share >40% phrasing (worst: ${Math.round(worst * 100)}%)`,
    );
    scores.push(Math.min(1.0, worst * 1.5));
  }

  // Check 1b: Alternating repetition (A-B-A-B oscillation at stride 2)
  if (turns.length >= 4) {
    const strideOverlaps: number[] = [];
    for (let i = 2; i < turns.length; i++) {
      strideOverlaps.push(ngramOverlap(turns[i - 2], turns[i]));
    }
    const highStrideCount = strideOverlaps.filter((o) => o > 0.50).length;
    if (highStrideCount >= 2) {
      const worst = Math.max(...strideOverlaps);
      signals.push(
        `Alternating repetition: ${highStrideCount} stride-2 pair(s) ` +
        `share >50% phrasing (worst: ${Math.round(worst * 100)}%). ` +
        'You are oscillating between the same two responses.',
      );
      scores.push(Math.min(1.0, worst * 1.4));
    }
  }

  // Check 2: Length flatness
  const lengths = turns.map((t) => t.length);
  if (lengths.length >= 3) {
    const avgLen = lengths.reduce((a, b) => a + b, 0) / lengths.length;
    if (avgLen > 0) {
      const maxDev = Math.max(...lengths.map((l) => Math.abs(l - avgLen) / avgLen));
      if (maxDev < 0.20) {
        signals.push(
          `Energy flatness: last ${turns.length} responses all within ` +
          `20% of the same length (~${Math.round(avgLen)} chars). ` +
          'Vary your depth - short when short serves, long when it matters.',
        );
        scores.push(0.3);
      }
    }
  }

  // Check 3: Agreement drift
  let agreementCount = 0;
  const agreementExamples: string[] = [];
  for (const turn of turns) {
    const firstWords = turn.trim().toLowerCase().slice(0, 60);
    for (const starter of AGREEMENT_STARTERS) {
      if (firstWords.startsWith(starter)) {
        agreementCount++;
        agreementExamples.push(starter);
        break;
      }
    }
  }

  const agreementRatio = turns.length > 0 ? agreementCount / turns.length : 0;
  if (agreementRatio > 0.60) {
    signals.push(
      `Agreement drift: ${agreementCount} of your last ${turns.length} ` +
      `responses opened with agreement words ` +
      `(${agreementExamples.map((e) => `'${e}'`).join(', ')}). ` +
      'Find something to push on or complicate.',
    );
    scores.push(Math.min(1.0, agreementRatio));
  }

  // Check 4: Vocabulary staleness
  if (turns.length >= 4) {
    const mid = Math.floor(turns.length / 2);
    const firstHalf = turns.slice(0, mid).join(' ');
    const secondHalf = turns.slice(mid).join(' ');

    const wordsFirst = new Set((firstHalf.toLowerCase().match(/[a-z]+/g) || []));
    const wordsSecond = new Set((secondHalf.toLowerCase().match(/[a-z]+/g) || []));

    if (wordsFirst.size > 0 && wordsSecond.size > 0) {
      let newWords = 0;
      for (const w of wordsSecond) {
        if (!wordsFirst.has(w)) newWords++;
      }
      const newRatio = newWords / wordsSecond.size;

      if (newRatio < 0.25) {
        signals.push(
          `Vocabulary staleness: later turns introduce only ` +
          `${Math.round(newRatio * 100)}% new words. Your language is narrowing. ` +
          'Reach for different registers, metaphors, or specifics.',
        );
        scores.push(0.4);
      }
    }
  }

  const score = scores.length > 0
    ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 1000) / 1000
    : 0;

  return {
    degraded: score > 0.5,
    signals,
    score,
  };
}
```

**Coherence checks:**

| Check | Threshold | Signal |
|-------|-----------|--------|
| 1a: Consecutive repetition | >40% n-gram overlap | Repetition detected |
| 1b: Alternating repetition | >50% stride-2 overlap | Oscillating responses |
| 2: Length flatness | <20% deviation | Energy flatness |
| 3: Agreement drift | >60% agreement starters | Excessive agreeableness |
| 4: Vocabulary staleness | <25% new words | Language narrowing |

**Scoring:**
- Each check adds to scores array if triggered
- Final score = average of triggered scores
- `degraded = true` if score > 0.5

## formatReanchorPrompt

```typescript
function formatReanchorPrompt(signals: string[]): string {
  const signalBlock = signals.map((s) => `  - ${s}`).join('\n');
  return (
    '[COHERENCE CHECK - you are drifting. The following signals were detected:\n' +
    signalBlock + '\n' +
    // ... re-anchoring instructions
  );
}
```

**Purpose:** Format re-anchoring prompt with detected signals

## runCoherenceCheck

```typescript
export async function runCoherenceCheck(
  sessionId: string,
  systemPrompt: string,
): Promise<void> {
  const recentTurns = memory.getRecentCompanionTurns(5);
  const result = checkCoherence(recentTurns);

  if (!result.degraded) {
    log.debug(`coherence check: OK (score: ${result.score})`);
    return;
  }

  log.warn(`coherence check: DEGRADED (score: ${result.score})`);
  log.warn(`signals: ${result.signals.join('; ')}`);

  // Fire re-anchoring turn
  const reanchorPrompt = formatReanchorPrompt(result.signals);
  const emitter = streamInference(reanchorPrompt, systemPrompt, sessionId);

  // Collect response but don't display - it's for internal re-anchoring
  let response = '';
  await new Promise<void>((resolve) => {
    emitter.on('event', (evt: InferenceEvent) => {
      if (evt.type === 'StreamDone') {
        response = evt.fullText;
        resolve();
      } else if (evt.type === 'StreamError') {
        resolve();
      }
    });
  });

  log.info(`re-anchoring complete: ${response.length} chars`);
}
```

**Purpose:** Run coherence check and re-anchor if degraded

**Flow:**
1. Get last 5 agent turns
2. Run coherence check
3. If degraded, fire re-anchoring prompt
4. Collect response (not displayed to user)
5. Log result

## Usage in app.ts

```typescript
// In app.ts - sentinel timer (every 5 minutes)
sentinelTimer = setInterval(() => {
  if (currentSession && systemPrompt && currentSession.cliSessionId) {
    runCoherenceCheck(currentSession.cliSessionId, systemPrompt)
      .catch((e) => log.error(`sentinel error: ${e}`));
  }
}, 5 * 60 * 1000);
```

**Schedule:** Every 5 minutes during active session

## Exported API

| Function | Purpose |
|----------|---------|
| `checkCoherence(recentTurns)` | Check coherence of recent turns |
| `runCoherenceCheck(sessionId, systemPrompt)` | Run check and re-anchor if needed |
| `CoherenceResult` | Result interface with degraded, signals, score |

## See Also

- `src/main/app.ts` - Sentinel timer integration
- `src/main/inference.ts` - streamInference for re-anchoring
- `src/main/memory.ts` - getRecentCompanionTurns

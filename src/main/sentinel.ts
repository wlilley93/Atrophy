/**
 * SENTINEL - mid-session coherence monitor.
 * Port of core/sentinel.py.
 *
 * Checks every 5 minutes for signs of conversational degradation:
 * - Repetition (same phrases/structures across recent turns)
 * - Drift (excessive agreeableness, losing voice)
 * - Energy flatness (all responses similar length)
 * - Vocabulary staleness (language narrowing)
 *
 * When degradation is detected, fires a silent re-anchoring turn.
 */

import * as memory from './memory';
import { streamInference, InferenceEvent } from './inference';
import { createLogger } from './logger';

const log = createLogger('sentinel');

// ---------------------------------------------------------------------------
// N-gram helpers
// ---------------------------------------------------------------------------

function ngrams(text: string, n: number): Set<string> {
  const words = text.toLowerCase().match(/[a-z]+/g) || [];
  if (words.length < n) return new Set();
  const result = new Set<string>();
  for (let i = 0; i <= words.length - n; i++) {
    result.add(words.slice(i, i + n).join(' '));
  }
  return result;
}

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

// ---------------------------------------------------------------------------
// Agreement starters
// ---------------------------------------------------------------------------

const AGREEMENT_STARTERS = [
  'yes', 'yeah', "that's", 'right', 'exactly', 'i agree',
  'absolutely', 'of course', 'totally', "you're right",
  'that makes sense', 'good point', 'fair', 'true',
];

// ---------------------------------------------------------------------------
// Core coherence check
// ---------------------------------------------------------------------------

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
  // Consecutive overlap can be low while stride-2 overlap is high.
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

// ---------------------------------------------------------------------------
// Re-anchoring prompt
// ---------------------------------------------------------------------------

function formatReanchorPrompt(signals: string[]): string {
  const signalBlock = signals.map((s) => `  - ${s}`).join('\n');
  return (
    '[COHERENCE CHECK - you are drifting. The following signals were detected:\n' +
    signalBlock + '\n' +
    'Re-anchor: reconnect with what actually matters in this conversation. ' +
    "Be specific. Push back if you need to. Don't just agree. " +
    "Change your rhythm - if you've been long, go short. If you've been " +
    'agreeable, find a real question. If your language has gone flat, reach ' +
    'for something precise.\n' +
    'Work this into your next response naturally. Do not announce the ' +
    'course-correction. Do not produce spoken output for this turn. ' +
    'Just recalibrate silently.]'
  );
}

// ---------------------------------------------------------------------------
// Full coherence check cycle
// ---------------------------------------------------------------------------

export function runCoherenceCheck(
  cliSessionId: string,
  system: string,
): Promise<string | null> {
  return new Promise((resolve) => {
    const recent = memory.getRecentCompanionTurns(5).reverse(); // DESC -> chronological

    if (recent.length < 3) {
      log.debug('skipped - fewer than 3 turns');
      resolve(null);
      return;
    }

    const t0 = Date.now();
    const result = checkCoherence(recent);
    const checkMs = Date.now() - t0;

    const action = result.degraded ? 'reanchor' : 'none';
    memory.logCoherenceCheck(
      result.score,
      result.degraded,
      JSON.stringify(result.signals),
      action,
    );

    const signalStr = result.signals.length > 0 ? result.signals.join('; ') : 'clean';
    log.info(
      `score=${result.score.toFixed(2)} ` +
      `degraded=${result.degraded} | ${signalStr} | ${checkMs}ms`,
    );

    if (!result.degraded) {
      resolve(null);
      return;
    }

    // Fire re-anchoring turn - silent, no UI output
    const reanchorPrompt = formatReanchorPrompt(result.signals);
    log.info('firing re-anchor turn...');

    let newSessionId: string | null = null;
    const toolsUsed: string[] = [];

    const emitter = streamInference(reanchorPrompt, system, cliSessionId);

    emitter.on('event', (event: InferenceEvent) => {
      switch (event.type) {
        case 'ToolUse':
          toolsUsed.push(event.name);
          break;
        case 'StreamDone':
          if (event.sessionId && event.sessionId !== cliSessionId) {
            newSessionId = event.sessionId;
          }
          {
            const toolsStr = toolsUsed.length > 0 ? ` | tools: ${toolsUsed.join(', ')}` : '';
            log.info(`reanchor complete${toolsStr}`);
          }
          emitter.removeAllListeners();
          resolve(newSessionId);
          break;
        case 'StreamError':
          log.error(`reanchor error: ${event.message.slice(0, 120)}`);
          emitter.removeAllListeners();
          resolve(null);
          break;
      }
    });
  });
}

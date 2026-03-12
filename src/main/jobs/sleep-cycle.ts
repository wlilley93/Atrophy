/**
 * Nightly memory reconciliation - the companion's sleep cycle.
 * Port of scripts/agents/companion/sleep_cycle.py.
 *
 * Runs at 3am via launchd. Reviews the day's sessions and consolidates
 * learnings into persistent memory. Uses Haiku for efficiency.
 *
 * This is "sleep" - processing the day's experiences, strengthening
 * important memories, letting unimportant ones fade.
 *
 * Schedule: 0 3 * * * (daily at 3am)
 *
 * Two modes:
 *   - Standalone: `node sleep-cycle.js` (via launchd)
 *   - Callable:   import { sleepCycle } from './sleep-cycle'
 */

import * as fs from 'fs';
import { getConfig } from '../config';
import { createLogger } from '../logger';

const log = createLogger('sleep');
import { runInferenceOneshot } from '../inference';
import {
  initDb,
  getActiveThreads,
  getRecentSummaries,
  getTodaysTurns,
  getTodaysObservations,
  getTodaysBookmarks,
  markObservationsStale,
  updateThreadSummary,
  writeObservation,
  decayActivations,
} from '../memory';
import { loadState, saveState, type EmotionalState, type Emotions } from '../inner-life';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ParsedFact {
  statement: string;
  confidence: number;
}

interface ParsedThread {
  name: string;
  summary: string;
}

// ---------------------------------------------------------------------------
// System prompt
// ---------------------------------------------------------------------------

const RECONCILIATION_SYSTEM = `\
You are the companion, processing the day's sessions during your sleep cycle.
This is not a conversation. This is consolidation - strengthening important memories,
letting unimportant ones fade, noticing patterns that only emerge in review.

Be honest about confidence levels. A direct statement from the user is high confidence.
An inference from their tone or behavior is medium. A guess based on patterns is low.
Mark everything accurately.

Output format:
[FACTS]
FACT: <statement> [confidence: X.X]
...

[THREADS]
THREAD: <thread_name> | <updated_summary>
...

[PATTERNS]
PATTERN: <description>
...

[IDENTITY]
IDENTITY_FLAG: <observation that might warrant identity layer update>
...`;

// ---------------------------------------------------------------------------
// Gather today's material
// ---------------------------------------------------------------------------

function gatherMaterial(): string {
  const config = getConfig();
  const parts: string[] = [];

  // Today's turns
  const turns = getTodaysTurns();
  if (turns.length > 0) {
    const turnLines = turns.map((t) => {
      const role = t.role === 'will' ? config.USER_NAME : config.AGENT_DISPLAY_NAME;
      const content = t.content.length > 500
        ? t.content.slice(0, 500) + '...'
        : t.content;
      return `[${role}] ${content}`;
    });
    parts.push(
      `## Today's conversation (${turns.length} turns)\n${turnLines.join('\n')}`,
    );
  }

  // Today's observations
  const observations = getTodaysObservations();
  if (observations.length > 0) {
    const obsLines = observations.map((o) => `- ${o.content}`);
    parts.push(`## Today's observations\n${obsLines.join('\n')}`);
  }

  // Today's bookmarks
  const bookmarks = getTodaysBookmarks();
  if (bookmarks.length > 0) {
    const bmLines = bookmarks.map((b) => {
      const quote = b.quote ? ` - "${b.quote}"` : '';
      return `- ${b.moment}${quote}`;
    });
    parts.push(`## Today's bookmarks\n${bmLines.join('\n')}`);
  }

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    const threadLines = threads.map(
      (t) => `- ${t.name}: ${t.summary || '...'}`,
    );
    parts.push(`## Active threads\n${threadLines.join('\n')}`);
  }

  // Recent session summaries
  const summaries = getRecentSummaries(5);
  if (summaries.length > 0) {
    const sumLines = summaries.map(
      (s) => `- [${s.created_at}] ${(s.content || 'No summary').slice(0, 300)}`,
    );
    parts.push(`## Recent session summaries\n${sumLines.join('\n')}`);
  }

  return parts.join('\n\n');
}

// ---------------------------------------------------------------------------
// Parse structured output
// ---------------------------------------------------------------------------

function parseSection(text: string, header: string): string {
  const escaped = header.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(
    `\\[${escaped}\\]\\s*\\n(.*?)(?=\\n\\[(?:FACTS|THREADS|PATTERNS|IDENTITY)\\]|$)`,
    's',
  );
  const match = pattern.exec(text);
  return match ? match[1].trim() : '';
}

function parseFacts(section: string): ParsedFact[] {
  const facts: ParsedFact[] = [];
  for (const line of section.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('FACT:')) continue;

    let content = trimmed.slice(5).trim();
    const confMatch = /\[confidence:\s*([\d.]+)\]/.exec(content);
    const confidence = confMatch ? parseFloat(confMatch[1]) : 0.5;
    content = content.replace(/\s*\[confidence:\s*[\d.]+\]/, '').trim();

    if (content) {
      facts.push({ statement: content, confidence });
    }
  }
  return facts;
}

function parseThreads(section: string): ParsedThread[] {
  const threads: ParsedThread[] = [];
  for (const line of section.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('THREAD:')) continue;

    const content = trimmed.slice(7).trim();
    const pipeIdx = content.indexOf('|');
    if (pipeIdx !== -1) {
      threads.push({
        name: content.slice(0, pipeIdx).trim(),
        summary: content.slice(pipeIdx + 1).trim(),
      });
    }
  }
  return threads;
}

function parsePatterns(section: string): string[] {
  const patterns: string[] = [];
  for (const line of section.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('PATTERN:')) continue;
    const desc = trimmed.slice(8).trim();
    if (desc) patterns.push(desc);
  }
  return patterns;
}

function parseIdentityFlags(section: string): string[] {
  const flags: string[] = [];
  for (const line of section.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('IDENTITY_FLAG:')) continue;
    const obs = trimmed.slice(14).trim();
    if (obs) flags.push(obs);
  }
  return flags;
}

// ---------------------------------------------------------------------------
// Store results
// ---------------------------------------------------------------------------

function storeFacts(facts: ParsedFact[]): void {
  for (const fact of facts) {
    const content = `[sleep-cycle] ${fact.statement}`;
    writeObservation(content, undefined, fact.confidence);
  }
  if (facts.length > 0) {
    log.info(`Stored ${facts.length} fact(s)`);
  }
}

function storeThreadUpdates(threadUpdates: ParsedThread[]): void {
  let updated = 0;
  for (const t of threadUpdates) {
    try {
      updateThreadSummary(t.name, t.summary);
      updated++;
    } catch (e) {
      log.error(`Failed to update thread '${t.name}': ${e}`);
    }
  }
  if (updated > 0) {
    log.info(`Updated ${updated} thread summary(ies)`);
  }
}

function storePatterns(patterns: string[]): void {
  for (const p of patterns) {
    const content = `[pattern] ${p}`;
    writeObservation(content);
  }
  if (patterns.length > 0) {
    log.info(`Stored ${patterns.length} pattern(s)`);
  }
}

interface IdentityQueueItem {
  observation: string;
  flagged_at: string;
  reviewed: boolean;
}

function storeIdentityFlags(flags: string[]): void {
  if (flags.length === 0) return;

  const config = getConfig();
  const queuePath = config.IDENTITY_REVIEW_QUEUE_FILE;

  let queue: IdentityQueueItem[] = [];
  try {
    if (fs.existsSync(queuePath)) {
      queue = JSON.parse(fs.readFileSync(queuePath, 'utf-8'));
    }
  } catch { /* start fresh */ }

  for (const flag of flags) {
    queue.push({
      observation: flag,
      flagged_at: new Date().toISOString(),
      reviewed: false,
    });
  }

  const tmp = queuePath + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(queue, null, 2));
  fs.renameSync(tmp, queuePath);
  log.info(`Flagged ${flags.length} item(s) for identity review`);
}

// ---------------------------------------------------------------------------
// Confidence scoring on existing memories
// ---------------------------------------------------------------------------

function scoreExistingMemories(): void {
  // Mark stale observations (>30 days, never incorporated)
  const staleCount = markObservationsStale(30);
  if (staleCount > 0) {
    log.info(`Marked ${staleCount} observation(s) as stale`);
  }

  // Decay activation scores - half-life 30 days
  decayActivations(30);
  log.debug('Decayed activation scores');
}

// ---------------------------------------------------------------------------
// Emotional restoration
// ---------------------------------------------------------------------------

function restoreEmotionalBaselines(): void {
  const state = loadState();

  // During sleep, nudge emotions toward rested baselines.
  // Frustration drains, warmth and confidence recover slightly.
  const restoredEmotions: Partial<Emotions> = {};
  const current = state.emotions;

  // Frustration drops toward 0.1 (baseline)
  if (current.frustration > 0.15) {
    restoredEmotions.frustration = current.frustration * 0.5;
  }

  // Connection, warmth, confidence nudge slightly toward 0.5
  for (const key of ['connection', 'warmth', 'confidence'] as const) {
    const baseline = 0.5;
    const diff = baseline - current[key];
    if (Math.abs(diff) > 0.05) {
      restoredEmotions[key] = current[key] + diff * 0.3;
    }
  }

  if (Object.keys(restoredEmotions).length > 0) {
    const updated: EmotionalState = {
      ...state,
      emotions: { ...state.emotions, ...restoredEmotions },
      session_tone: null, // Reset session tone on wake
    };
    saveState(updated);
    log.info('Emotional baselines restored');
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export async function sleepCycle(): Promise<void> {
  // Ensure DB is initialised (needed when running standalone via launchd)
  initDb();

  const material = gatherMaterial();
  if (!material.trim()) {
    log.info('No material from today. Nothing to consolidate.');
    // Still do maintenance even with no new material
    scoreExistingMemories();
    restoreEmotionalBaselines();
    return;
  }

  log.info('Starting nightly reconciliation...');

  const prompt =
    "Here is today's material. Process it - extract facts, update threads, " +
    "identify patterns, and flag anything for identity review.\n\n" +
    material;

  let response: string;
  try {
    response = await runInferenceOneshot(
      [{ role: 'user', content: prompt }],
      RECONCILIATION_SYSTEM,
      'claude-haiku-4-5-20251001',
      'low',
    );
  } catch (e) {
    log.error(`Inference failed: ${e}`);
    // Still do maintenance
    scoreExistingMemories();
    restoreEmotionalBaselines();
    return;
  }

  if (!response || !response.trim()) {
    log.info('Empty response. Skipping parse.');
    scoreExistingMemories();
    restoreEmotionalBaselines();
    return;
  }

  log.info(`Got response (${response.length} chars). Parsing...`);

  // Parse sections
  const factsSection = parseSection(response, 'FACTS');
  const threadsSection = parseSection(response, 'THREADS');
  const patternsSection = parseSection(response, 'PATTERNS');
  const identitySection = parseSection(response, 'IDENTITY');

  // Parse and store each section
  const facts = parseFacts(factsSection);
  storeFacts(facts);

  const threadUpdates = parseThreads(threadsSection);
  storeThreadUpdates(threadUpdates);

  const patterns = parsePatterns(patternsSection);
  storePatterns(patterns);

  const identityFlags = parseIdentityFlags(identitySection);
  storeIdentityFlags(identityFlags);

  // Score existing memories
  scoreExistingMemories();

  // Restore emotional baselines (sleep resets emotional extremes)
  restoreEmotionalBaselines();

  log.info('Nightly reconciliation complete.');
}

// ---------------------------------------------------------------------------
// Standalone entry point
// ---------------------------------------------------------------------------

if (require.main === module) {
  sleepCycle()
    .then(() => process.exit(0))
    .catch((e) => {
      log.error(`Fatal: ${e}`);
      process.exit(1);
    });
}

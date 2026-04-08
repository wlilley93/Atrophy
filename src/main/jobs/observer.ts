/**
 * Pre-compaction observer - periodic fact extraction from recent conversation.
 * Port of scripts/agents/companion/observer.py.
 *
 * Runs every 15 minutes via launchd. Scans recent turns for durable facts
 * worth preserving between compaction events. Complements the memory flush
 * by catching things that matter before they scroll out of context.
 *
 * Most runs are no-ops (no new turns). When there is material, uses Haiku
 * with low effort for fast, cheap extraction.
 *
 * Silent monitoring - no user-facing output.
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';
import { getConfig } from '../config';
import { getAgentDir } from '../agent-manager';
import { runInferenceOneshot } from '../inference';
import { writeObservation, extractAndStoreEntities } from '../memory';
import { createLogger } from '../logger';

const log = createLogger('observer');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TurnRow {
  id: number;
  role: string;
  content: string;
  timestamp: string;
}

interface ObserverState {
  last_turn_id: number;
}

interface ParsedObservation {
  statement: string;
  confidence: number;
}

// ---------------------------------------------------------------------------
// State tracking
// ---------------------------------------------------------------------------

function stateFilePath(agentName: string): string {
  return path.join(getAgentDir(agentName), 'state', '.observer_state.json');
}

function loadState(agentName: string): ObserverState {
  const filePath = stateFilePath(agentName);
  try {
    if (fs.existsSync(filePath)) {
      return JSON.parse(fs.readFileSync(filePath, 'utf-8')) as ObserverState;
    }
  } catch {
    // Corrupted state file - start fresh
  }
  return { last_turn_id: 0 };
}

function saveState(agentName: string, state: ObserverState): void {
  const filePath = stateFilePath(agentName);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(state, null, 2));
}

// ---------------------------------------------------------------------------
// System prompt
// ---------------------------------------------------------------------------

const OBSERVER_SYSTEM = `\
You are extracting durable facts from a conversation transcript.
Not everything is worth preserving - only extract things that would be
useful to remember in a future session.

Output format (one per line):
OBSERVATION: <fact> [confidence: X.X]

If there is nothing worth extracting, respond with: NOTHING_NEW`;

// ---------------------------------------------------------------------------
// Get recent turns
// ---------------------------------------------------------------------------

function getRecentTurns(agentName: string, sinceId: number): TurnRow[] {
  const config = getConfig();
  config.reloadForAgent(agentName);
  const dbPath = config.DB_PATH;
  if (!fs.existsSync(dbPath)) return [];

  const db = new Database(dbPath, { readonly: true });

  try {
    const cutoff = new Date(Date.now() - 15 * 60 * 1000)
      .toISOString()
      .replace('T', ' ')
      .slice(0, 19);

    return db
      .prepare(
        'SELECT id, role, content, timestamp FROM turns ' +
        'WHERE id > ? AND timestamp > ? ' +
        'ORDER BY timestamp',
      )
      .all(sinceId, cutoff) as TurnRow[];
  } finally {
    db.close();
  }
}

// ---------------------------------------------------------------------------
// Parse observations from inference response
// ---------------------------------------------------------------------------

function parseObservations(response: string): ParsedObservation[] {
  const observations: ParsedObservation[] = [];
  const confRe = /\[confidence:\s*([\d.]+)\]/;

  for (const line of response.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('OBSERVATION:')) continue;

    let content = trimmed.slice('OBSERVATION:'.length).trim();

    // Extract confidence
    const confMatch = confRe.exec(content);
    const confidence = confMatch ? parseFloat(confMatch[1]) : 0.5;

    // Remove confidence tag from content
    const statement = content.replace(/\s*\[confidence:\s*[\d.]+\]/, '').trim();
    if (statement) {
      observations.push({ statement, confidence });
    }
  }

  return observations;
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runObserver(agentName: string): Promise<void> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  const state = loadState(agentName);
  const lastId = state.last_turn_id;

  // Get recent turns since last run
  const turns = getRecentTurns(agentName, lastId);

  if (turns.length === 0) {
    // Fast path - nothing new
    return;
  }

  log.info(`${turns.length} new turn(s) since ID ${lastId}`);

  // Build transcript
  const transcriptLines = turns.map((t) => {
    const role = t.role === 'will' ? config.USER_NAME : config.AGENT_DISPLAY_NAME;
    const content = t.content.length > 500 ? t.content.slice(0, 500) + '...' : t.content;
    return `[${role}] ${content}`;
  });

  const transcript = transcriptLines.join('\n');

  const prompt =
    'Extract any durable facts from this recent conversation excerpt.\n\n' +
    transcript;

  let response: string;
  try {
    response = await runInferenceOneshot(
      [{ role: 'user', content: prompt }],
      OBSERVER_SYSTEM,
      'claude-haiku-4-5-20251001',
      'low',
    );
  } catch (e) {
    log.error(`Inference failed: ${e}`);
    return;
  }

  if (!response || !response.trim()) {
    log.info('Empty response.');
    return;
  }

  // Update state to highest turn ID we processed
  const maxId = Math.max(...turns.map((t) => t.id));
  state.last_turn_id = maxId;
  saveState(agentName, state);

  // Check for nothing new
  if (response.trim().includes('NOTHING_NEW')) {
    log.info('Nothing worth extracting.');
    return;
  }

  // Parse and store observations
  const observations = parseObservations(response);
  if (observations.length === 0) {
    log.info('No observations parsed.');
    return;
  }

  for (const obs of observations) {
    const content = `[observer] ${obs.statement}`;
    writeObservation(content, undefined, obs.confidence);
  }

  log.info(`Stored ${observations.length} observation(s)`);

  // Entity extraction from the transcript (silent - enriches the entity graph)
  try {
    for (const t of turns) {
      if (t.content.length > 50) {
        extractAndStoreEntities(t.content);
      }
    }
  } catch {
    // Entity extraction is best-effort, never block
  }
}

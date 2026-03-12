/**
 * Heartbeat background job - periodic check-in evaluation.
 * Port of scripts/agents/companion/heartbeat.py.
 *
 * Runs via launchd every 30 minutes. Gathers context about active threads,
 * time since last interaction, and recent session activity. Asks the companion
 * to evaluate whether to reach out unprompted using the HEARTBEAT.md checklist.
 *
 * If the companion decides to reach out, fires a macOS notification and queues
 * the message for next app launch.
 */

import * as fs from 'fs';
import * as path from 'path';
import { EventEmitter } from 'events';
import { getConfig } from '../config';
import {
  getDb,
  getActiveThreads,
  getRecentSummaries,
  getRecentObservations,
  getLastInteractionTime,
  getLastCliSessionId,
  logHeartbeat,
} from '../memory';
import {
  streamInference,
  InferenceEvent,
  TextDeltaEvent,
  ToolUseEvent,
  StreamDoneEvent,
  StreamErrorEvent,
} from '../inference';
import { loadSystemPrompt } from '../context';
import { isAway, isMacIdle } from '../status';
import { sendNotification } from '../notify';
import { queueMessage } from '../queue';
import { sendMessage as sendTelegram } from '../telegram';
import { registerJob, activeHoursGate } from './index';
import { createLogger } from '../logger';

const log = createLogger('heartbeat');

// ---------------------------------------------------------------------------
// Heartbeat prompt
// ---------------------------------------------------------------------------

const HEARTBEAT_PROMPT =
  '[HEARTBEAT CHECK - internal evaluation, not a conversation]\n\n' +
  'You are deciding whether to reach out to the user unprompted. ' +
  'You have access to your full conversation history and memory tools.\n\n' +
  'First, review your state - use recall, daily_digest, or your memory tools ' +
  'if you need to refresh context. You may also update your HEARTBEAT.md ' +
  'checklist via write_note if your monitoring criteria should evolve.\n\n' +
  'Then evaluate using the checklist below. Respond with exactly ONE prefix:\n\n' +
  '[REACH_OUT] followed by the message you\'d send him. Be specific. ' +
  'Reference the actual thing. Don\'t say \'just checking in.\'\n\n' +
  '[HEARTBEAT_OK] followed by a brief reason why now isn\'t the right time.\n\n' +
  '[SUPPRESS] followed by a brief reason if you actively shouldn\'t reach out ' +
  '(e.g. he\'s away, it\'s too soon, he needs space).\n\n' +
  'Keep it short. 1-3 sentences for the message, one line for OK/SUPPRESS.';

// ---------------------------------------------------------------------------
// Checklist loader
// ---------------------------------------------------------------------------

function loadChecklist(): string {
  const config = getConfig();
  const heartbeatPath = path.join(config.OBSIDIAN_AGENT_DIR, 'skills', 'HEARTBEAT.md');
  try {
    if (fs.existsSync(heartbeatPath)) {
      return fs.readFileSync(heartbeatPath, 'utf-8');
    }
  } catch { /* missing file */ }

  // Fallback: check agent prompts dir
  const fallbackPath = path.join(config.AGENT_DIR, 'prompts', 'HEARTBEAT.md');
  try {
    if (fs.existsSync(fallbackPath)) {
      return fs.readFileSync(fallbackPath, 'utf-8');
    }
  } catch { /* missing file */ }

  return '';
}

// ---------------------------------------------------------------------------
// Context gathering
// ---------------------------------------------------------------------------

function gatherContext(): string {
  const parts: string[] = [];

  // Time since last interaction
  const lastTime = getLastInteractionTime();
  if (lastTime) {
    parts.push(`## Last interaction\n${lastTime}`);
  } else {
    parts.push('## Last interaction\nNo previous interactions found.');
  }

  // Recent turn count (last session)
  const db = getDb();
  const row = db
    .prepare(
      'SELECT COUNT(*) as cnt FROM turns t ' +
      'JOIN sessions s ON t.session_id = s.id ' +
      'WHERE s.id = (SELECT MAX(id) FROM sessions)',
    )
    .get() as { cnt: number } | undefined;
  if (row) {
    parts.push(`## Recent session turn count\n${row.cnt} turns`);
  }

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    const lines = threads.slice(0, 5).map(
      (t) => `- ${t.name}: ${t.summary || '...'}`,
    );
    parts.push(`## Active threads\n${lines.join('\n')}`);
  }

  // Recent session summaries
  const summaries = getRecentSummaries(3);
  if (summaries.length > 0) {
    const lines = summaries.map(
      (s) => `- ${s.created_at || '?'}: ${(s.content || 'No summary').slice(0, 200)}`,
    );
    parts.push(`## Recent sessions\n${lines.join('\n')}`);
  }

  // Recent observations
  const observations = getRecentObservations(5);
  if (observations.length > 0) {
    const lines = observations.map((o) => `- ${o.content}`);
    parts.push(`## Recent observations\n${lines.join('\n')}`);
  }

  return parts.join('\n\n');
}

// ---------------------------------------------------------------------------
// Inference wrapper
// ---------------------------------------------------------------------------

function runHeartbeatInference(
  prompt: string,
  cliSessionId: string | null,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const system = loadSystemPrompt();
    let fullText = '';
    const toolsUsed: string[] = [];

    const emitter: EventEmitter = streamInference(prompt, system, cliSessionId);

    emitter.on('event', (event: InferenceEvent) => {
      switch (event.type) {
        case 'TextDelta':
          // Collected via StreamDone
          break;
        case 'ToolUse':
          toolsUsed.push((event as ToolUseEvent).name);
          log.debug(`tool -> ${(event as ToolUseEvent).name}`);
          break;
        case 'StreamDone':
          fullText = (event as StreamDoneEvent).fullText;
          if (toolsUsed.length > 0) {
            log.debug(`used tools: ${toolsUsed.join(', ')}`);
          }
          resolve(fullText);
          break;
        case 'StreamError':
          reject(new Error((event as StreamErrorEvent).message));
          break;
        default:
          break;
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Parse response and act
// ---------------------------------------------------------------------------

async function handleResponse(response: string): Promise<string> {
  const config = getConfig();
  const stripped = response.trim();

  if (stripped.startsWith('[REACH_OUT]')) {
    const message = stripped.slice('[REACH_OUT]'.length).trim();
    logHeartbeat('REACH_OUT', '', message);

    // Route: Telegram only if Mac is idle (user is away from computer)
    // Local notification + queue always
    if (isMacIdle()) {
      try {
        await sendTelegram(message);
        log.info('Sent via Telegram (Mac idle)');
      } catch (e) {
        log.error(`Telegram send failed: ${e}`);
      }
    } else {
      log.info('Mac active - local only, skipping Telegram');
    }

    sendNotification(config.AGENT_DISPLAY_NAME, message.slice(0, 200));
    queueMessage(message, 'heartbeat');

    return `REACH_OUT: ${message.slice(0, 80)}`;
  }

  if (stripped.startsWith('[HEARTBEAT_OK]')) {
    const reason = stripped.slice('[HEARTBEAT_OK]'.length).trim();
    logHeartbeat('HEARTBEAT_OK', reason);
    return `OK: ${reason.slice(0, 80)}`;
  }

  if (stripped.startsWith('[SUPPRESS]')) {
    const reason = stripped.slice('[SUPPRESS]'.length).trim();
    logHeartbeat('SUPPRESS', reason);
    return `Suppressed: ${reason.slice(0, 80)}`;
  }

  // Unexpected format - log but don't act
  logHeartbeat('UNKNOWN', stripped.slice(0, 500));
  return `Unknown format: ${stripped.slice(0, 80)}`;
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runHeartbeat(agentName: string): Promise<string> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  // Gate: user status
  if (isAway()) {
    logHeartbeat('SUPPRESS', 'User is away');
    return 'Skipped: user is away';
  }

  // Gate: heartbeat checklist must exist
  const checklist = loadChecklist();
  if (!checklist) {
    return 'Skipped: no HEARTBEAT.md found';
  }

  const context = gatherContext();
  const cliSessionId = getLastCliSessionId();

  const prompt =
    `${HEARTBEAT_PROMPT}\n\n---\n\n${checklist}\n\n---\n\n## Current Context\n\n${context}`;

  const mode = cliSessionId ? 'resume' : 'cold';
  log.info(`Running evaluation (${mode})...`);

  let response: string;
  try {
    response = await runHeartbeatInference(prompt, cliSessionId);
  } catch (e) {
    const errMsg = e instanceof Error ? e.message : String(e);
    logHeartbeat('ERROR', errMsg);
    throw new Error(`Inference failed: ${errMsg}`);
  }

  if (!response || !response.trim()) {
    logHeartbeat('ERROR', 'Empty response');
    return 'Error: empty response';
  }

  log.debug(`Response: ${response.slice(0, 120)}...`);
  return handleResponse(response);
}

// ---------------------------------------------------------------------------
// Job registration
// ---------------------------------------------------------------------------

registerJob({
  name: 'heartbeat',
  description: 'Periodic check-in - decides whether to reach out unprompted',
  gates: [activeHoursGate],
  run: async () => {
    const config = getConfig();
    return runHeartbeat(config.AGENT_NAME);
  },
});

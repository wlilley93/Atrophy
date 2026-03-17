/**
 * Send a spontaneous voice note via Telegram.
 * Port of scripts/agents/companion/voice_note.py.
 *
 * Runs on a randomised schedule. The agent generates a short thought -
 * something it has been sitting with, a connection it noticed, a follow-up
 * to something from a recent conversation - synthesises it as speech,
 * and sends it as a Telegram voice note.
 *
 * After running, reschedules itself to a random time 2-8 hours from now
 * (within active hours). The randomness is the point - it should feel
 * like the agent genuinely thought of something and reached out.
 */

import * as fs from 'fs';

import { getConfig } from '../config';
import { createLogger } from '../logger';
import { convertToOgg, cleanupFiles } from '../audio-convert';

const log = createLogger('voice-note');
import {
  getDb,
  getActiveThreads,
  getRecentObservations,
  writeObservation,
} from '../memory';
import { runInferenceOneshot } from '../inference';
import { loadPrompt } from '../prompts';
import { synthesise } from '../tts';
import { sendVoiceNote, sendMessage } from '../telegram';
import { editJobSchedule } from '../cron';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ConversationTurn {
  role: string;
  content: string;
}

// ---------------------------------------------------------------------------
// Context gathering
// ---------------------------------------------------------------------------

/**
 * Pull recent threads, observations, and conversation turns for inspiration.
 */
function gatherContext(): string {
  const db = getDb();
  const parts: string[] = [];

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    const threadLines = threads.slice(0, 5).map(
      (t) => `- ${t.name}: ${t.summary ?? '...'}`,
    );
    parts.push('Active threads:\n' + threadLines.join('\n'));
  }

  // Recent observations
  const obs = getRecentObservations(8);
  if (obs.length > 0) {
    const obsLines = obs.map((o) => `- ${o.content}`);
    parts.push('Recent observations:\n' + obsLines.join('\n'));
  }

  // Recent conversation turns (last few meaningful exchanges)
  const turns = db
    .prepare(
      `SELECT role, content FROM conversation_history
       WHERE role IN ('user', 'agent')
       ORDER BY created_at DESC LIMIT 6`,
    )
    .all() as ConversationTurn[];

  if (turns.length > 0) {
    const turnLines = turns
      .reverse()
      .map((t) => `- [${t.role}] ${t.content.slice(0, 200)}`);
    parts.push('Recent conversation:\n' + turnLines.join('\n'));
  }

  return parts.join('\n\n');
}

// ---------------------------------------------------------------------------
// Rescheduling
// ---------------------------------------------------------------------------

/**
 * Reschedule the voice note job to a random time 2-8 hours from now,
 * clamped to active hours.
 */
function reschedule(): void {
  const config = getConfig();
  const activeStart = config.HEARTBEAT_ACTIVE_START;
  const activeEnd = config.HEARTBEAT_ACTIVE_END;

  const now = new Date();
  const offsetHours = 2 + Math.random() * 6; // 2-8 hours
  let nextRun = new Date(now.getTime() + offsetHours * 3600_000);

  // If outside active hours, push to next active window
  if (nextRun.getHours() >= activeEnd) {
    nextRun.setDate(nextRun.getDate() + 1);
    nextRun.setHours(activeStart, Math.floor(Math.random() * 60), 0, 0);
  } else if (nextRun.getHours() < activeStart) {
    nextRun.setHours(activeStart, Math.floor(Math.random() * 60), 0, 0);
  }

  const cron = `${nextRun.getMinutes()} ${nextRun.getHours()} ${nextRun.getDate()} ${nextRun.getMonth() + 1} *`;

  try {
    editJobSchedule('voice_note', cron);
  } catch (e) {
    log.error(`Failed to reschedule: ${e}`);
    return;
  }

  log.info(
    `Rescheduled to ${nextRun.toISOString().slice(0, 16).replace('T', ' ')}`,
  );
}

// ---------------------------------------------------------------------------
// Sentiment / intent enrichment
// ---------------------------------------------------------------------------

interface VoiceNoteEnrichment {
  sentiment: string;
  intent: string;
  summary: string;
}

/**
 * Enrich a voice note with sentiment and intent classification via a
 * lightweight oneshot inference call.
 */
async function enrichVoiceNote(text: string): Promise<VoiceNoteEnrichment> {
  const fallback: VoiceNoteEnrichment = {
    sentiment: 'neutral',
    intent: 'spontaneous-thought',
    summary: text.slice(0, 120),
  };

  try {
    const result = await runInferenceOneshot(
      [
        {
          role: 'user',
          content: [
            'Classify this voice note. Return JSON only, no markdown fence.',
            '',
            `"""${text}"""`,
            '',
            'Schema: { "sentiment": "positive|neutral|negative|mixed",',
            '  "intent": "follow-up|connection|observation|question|encouragement|spontaneous-thought",',
            '  "summary": "<one-sentence summary>" }',
          ].join('\n'),
        },
      ],
      'You are a text classifier. Return valid JSON only.',
      'claude-haiku-4-5',
      'low',
    );

    const parsed = JSON.parse(result.trim()) as Partial<VoiceNoteEnrichment>;
    return {
      sentiment: parsed.sentiment ?? fallback.sentiment,
      intent: parsed.intent ?? fallback.intent,
      summary: parsed.summary ?? fallback.summary,
    };
  } catch {
    return fallback;
  }
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Generate and send a spontaneous voice note via Telegram.
 * Enriches the result with sentiment/intent and stores as an observation.
 */
export async function run(): Promise<void> {
  const config = getConfig();

  if (!config.TELEGRAM_BOT_TOKEN || !config.TELEGRAM_CHAT_ID) {
    log.info('Telegram not configured - skipping');
    return;
  }

  const now = new Date();
  const hour = now.getHours();

  // Check active hours
  if (hour < config.HEARTBEAT_ACTIVE_START || hour >= config.HEARTBEAT_ACTIVE_END) {
    log.info('Outside active hours - rescheduling');
    reschedule();
    return;
  }

  const context = gatherContext();
  if (!context.trim()) {
    log.info('No context material - skipping');
    reschedule();
    return;
  }

  // Generate the thought
  let prompt = loadPrompt('voice-note');
  if (!prompt) {
    prompt =
      'You are sending a spontaneous voice note to the person you know. ' +
      'Something you have been sitting with - a thought, a connection you ' +
      'noticed, a follow-up to something recent. Keep it short and natural. ' +
      '2-4 sentences. Speak as yourself, not as an assistant delivering a ' +
      'report. This should sound like a person who just thought of something ' +
      'and wanted to share it. No greeting. No sign-off. Just the thought.';
  }

  // Include current time so the agent knows when it is
  const now = new Date();
  const timeStr = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const dayStr = now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });

  let result: string;
  try {
    result = await runInferenceOneshot(
      [{ role: 'user', content: `Current time: ${timeStr}, ${dayStr}\n\n${context}\n\n---\n\n${prompt}` }],
      `You are ${config.AGENT_DISPLAY_NAME}. Generate a short, natural voice note.`,
    );
  } catch (e) {
    log.error(`Inference failed: ${e}`);
    reschedule();
    return;
  }

  if (!result || !result.trim()) {
    log.info('Empty result - skipping');
    reschedule();
    return;
  }

  log.info(`Generated: ${result.slice(0, 100)}...`);

  // Enrich with sentiment/intent
  const enrichment = await enrichVoiceNote(result);

  // Synthesise speech
  let audioPath: string | null = null;
  try {
    audioPath = await synthesise(result);
    if (!audioPath || !fs.existsSync(audioPath) || fs.statSync(audioPath).size === 0) {
      log.warn('TTS produced no audio - sending as text');
      await sendMessage(result);
      storeObservation(result, enrichment);
      reschedule();
      return;
    }
  } catch (e) {
    log.warn(`TTS failed: ${e} - sending as text`);
    await sendMessage(result);
    storeObservation(result, enrichment);
    reschedule();
    return;
  }

  // Convert to OGG for Telegram voice notes
  const oggPath = convertToOgg(audioPath);
  const sendPath = oggPath ?? audioPath;

  // Send via Telegram
  const success = await sendVoiceNote(sendPath);

  if (success) {
    log.info('Sent voice note via Telegram');
  } else {
    log.warn('Failed to send voice note - sending as text');
    await sendMessage(result);
  }

  // Store as observation
  storeObservation(result, enrichment);

  // Clean up temp files
  cleanupFiles(audioPath, oggPath);

  reschedule();
}

// ---------------------------------------------------------------------------
// Observation storage
// ---------------------------------------------------------------------------

/**
 * Store the voice note as an observation in the memory database.
 */
function storeObservation(text: string, enrichment: VoiceNoteEnrichment): void {
  try {
    writeObservation(
      `[voice-note] [${enrichment.sentiment}] [${enrichment.intent}] ${enrichment.summary}`,
      undefined,  // no source turn
      0.6,        // moderate confidence for self-generated content
    );
  } catch (e) {
    log.error(`Failed to store observation: ${e}`);
  }
}

/**
 * Morning brief - queued for next app launch.
 * Port of scripts/agents/companion/morning_brief.py.
 *
 * Runs via launchd at 7am. Gathers weather, headlines, active threads,
 * recent session summaries, and observations. Composes a natural brief
 * via oneshot inference. Writes to the message queue with pre-synthesised
 * TTS audio so it plays instantly on next launch. Also sends via Telegram.
 *
 * Schedule: 0 7 * * * (daily at 7am)
 *
 * Two modes:
 *   - Standalone: `node morning-brief.js` (via launchd)
 *   - Callable:   import { morningBrief } from './morning-brief'
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from '../config';
import { createLogger } from '../logger';

const log = createLogger('brief');
import { runInferenceOneshot } from '../inference';
import { loadPrompt } from '../prompts';
import { queueMessage } from '../queue';
import { sendNotification } from '../notify';
import { synthesiseSync } from '../tts';
import { sendMessage as sendTelegram } from '../telegram';
import {
  getActiveThreads,
  getRecentSummaries,
  getRecentObservations,
  initDb,
} from '../memory';

// ---------------------------------------------------------------------------
// Weather fetch (wttr.in - plain text, no deps)
// ---------------------------------------------------------------------------

async function fetchWeather(location = 'Leeds'): Promise<string> {
  try {
    const resp = await fetch(
      `https://wttr.in/${encodeURIComponent(location)}?format=%C+%t+%w+%h`,
      {
        headers: { 'User-Agent': 'curl/7.0' },
        signal: AbortSignal.timeout(10_000),
      },
    );
    if (!resp.ok) return '';
    return (await resp.text()).trim();
  } catch (e) {
    log.warn(`weather fetch failed: ${e}`);
    return '';
  }
}

// ---------------------------------------------------------------------------
// Headlines fetch (BBC RSS)
// ---------------------------------------------------------------------------

async function fetchHeadlines(): Promise<string> {
  try {
    const resp = await fetch('https://feeds.bbci.co.uk/news/rss.xml', {
      headers: { 'User-Agent': 'curl/7.0' },
      signal: AbortSignal.timeout(10_000),
    });
    if (!resp.ok) return '';
    const xml = await resp.text();

    // Lightweight RSS title extraction - no XML parser needed
    const items: string[] = [];
    const itemRe = /<item>[\s\S]*?<\/item>/g;
    const titleRe = /<title><!\[CDATA\[(.*?)\]\]><\/title>|<title>(.*?)<\/title>/;
    let match: RegExpExecArray | null;
    let count = 0;

    while ((match = itemRe.exec(xml)) !== null && count < 5) {
      const titleMatch = titleRe.exec(match[0]);
      const title = titleMatch?.[1] || titleMatch?.[2];
      if (title) {
        items.push(`- ${title}`);
        count++;
      }
    }

    return items.join('\n');
  } catch (e) {
    log.warn(`headlines fetch failed: ${e}`);
    return '';
  }
}

// ---------------------------------------------------------------------------
// Context assembly
// ---------------------------------------------------------------------------

async function gatherContext(): Promise<string> {
  const config = getConfig();
  const parts: string[] = [];

  // Weather
  const weather = await fetchWeather();
  if (weather) {
    parts.push(`## Weather in Leeds\n${weather}`);
  }

  // Headlines
  const headlines = await fetchHeadlines();
  if (headlines) {
    parts.push(`## UK headlines\n${headlines}`);
  }

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    const lines = threads.slice(0, 5).map(
      (t) => `- ${t.name}: ${t.summary || '...'}`,
    );
    parts.push(`## Active threads\n${lines.join('\n')}`);
  }

  // Recent sessions (last 2 days)
  const summaries = getRecentSummaries(3);
  if (summaries.length > 0) {
    const lines = summaries.map(
      (s) => `- ${s.created_at}: ${(s.content || 'No summary').slice(0, 200)}`,
    );
    parts.push(`## Recent sessions\n${lines.join('\n')}`);
  }

  // Recent observations
  const observations = getRecentObservations(5);
  if (observations.length > 0) {
    const lines = observations.map((o) => `- ${o.content}`);
    parts.push(`## Recent observations\n${lines.join('\n')}`);
  }

  // Companion reflections (latest from Obsidian)
  const reflectionsPath = path.join(
    config.OBSIDIAN_AGENT_NOTES,
    'notes',
    'reflections.md',
  );
  try {
    if (fs.existsSync(reflectionsPath)) {
      let content = fs.readFileSync(reflectionsPath, 'utf-8');
      if (content.length > 800) {
        content = '...' + content.slice(-800);
      }
      parts.push(`## Your recent reflections\n${content}`);
    }
  } catch { /* non-critical */ }

  return parts.join('\n\n');
}

// ---------------------------------------------------------------------------
// TTS pre-synthesis
// ---------------------------------------------------------------------------

async function synthesiseAudio(text: string): Promise<string> {
  try {
    const audioPath = await synthesiseSync(text);
    if (audioPath) {
      const stat = fs.statSync(audioPath);
      if (stat.size > 100) return audioPath;
    }
  } catch (e) {
    log.warn(`TTS failed: ${e}`);
  }
  return '';
}

// ---------------------------------------------------------------------------
// Fallback prompt
// ---------------------------------------------------------------------------

const BRIEF_FALLBACK =
  "You are the companion. Write a short natural morning message for Will. " +
  "3-6 sentences. Warm but not performative.";

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export async function morningBrief(): Promise<void> {
  // Ensure DB is initialised (needed when running standalone via launchd)
  initDb();

  const context = await gatherContext();
  if (!context.trim()) {
    log.info('No context gathered. Skipping.');
    return;
  }

  log.info('Generating morning brief...');

  let brief: string;
  try {
    brief = await runInferenceOneshot(
      [{ role: 'user', content: `Here's what you have this morning:\n\n${context}` }],
      loadPrompt('morning-brief', BRIEF_FALLBACK),
    );
  } catch (e) {
    log.error(`Inference failed: ${e}`);
    return;
  }

  if (!brief || !brief.trim()) {
    log.info('Empty response. Skipping.');
    return;
  }

  log.info(`Generated: ${brief.slice(0, 100)}...`);

  // Pre-synthesise TTS
  const audio = await synthesiseAudio(brief);
  if (audio) {
    log.debug(`Audio cached: ${audio}`);
  }

  // Send via Telegram
  try {
    await sendTelegram(brief);
    log.info('Sent via Telegram.');
  } catch (e) {
    log.warn(`Telegram send failed: ${e}`);
  }

  // Send notification
  sendNotification('Morning Brief', brief.slice(0, 200));

  // Queue for next app launch
  queueMessage(brief, 'morning_brief', audio);
  log.info('Queued for next launch.');
}

// ---------------------------------------------------------------------------
// Standalone entry point
// ---------------------------------------------------------------------------

if (require.main === module) {
  morningBrief()
    .then(() => process.exit(0))
    .catch((e) => {
      log.error(`Fatal: ${e}`);
      process.exit(1);
    });
}

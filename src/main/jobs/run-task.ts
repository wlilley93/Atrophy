/**
 * Generic task runner - executes a prompt-based task and delivers the result.
 * Port of scripts/agents/companion/run_task.py.
 *
 * The companion agent can schedule this via manage_schedule to create
 * arbitrary recurring tasks without writing code.
 *
 * Usage (standalone):
 *   node run-task.js <task_name>
 *
 * Task definitions live in Obsidian at:
 *   Agent Workspace/<agent>/tasks/<task_name>.md
 *
 * Each task file is YAML frontmatter + prompt body:
 *
 *   ---
 *   deliver: message_queue     # message_queue | telegram | notification | obsidian
 *   voice: true                # pre-synthesise TTS audio
 *   sources:                   # optional data sources to fetch before running
 *     - weather
 *     - headlines
 *     - threads
 *     - summaries
 *     - observations
 *   ---
 *
 *   You are the companion. Fetch and summarise the latest UK news headlines.
 *   Keep it to 3-5 bullet points. Be conversational.
 *
 * The prompt is sent to oneshot inference with gathered source data.
 * The response is delivered via the specified channel.
 *
 * Dual-use: callable as a function from the main process, or runnable
 * as a standalone launchd script via the CLI entry point at the bottom.
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from '../config';
import { createLogger } from '../logger';

const log = createLogger('task');
import { runInferenceOneshot } from '../inference';
import { queueMessage } from '../queue';
import { sendNotification } from '../notify';
import { sendMessage as telegramSend, sendVoiceNote } from '../channels/telegram';
import { synthesiseSync } from '../tts';
import {
  getActiveThreads,
  getRecentSummaries,
  getRecentObservations,
} from '../memory';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TaskMeta {
  deliver?: string;
  voice?: boolean;
  sources?: string[];
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Task loading
// ---------------------------------------------------------------------------

function tasksDir(): string {
  const config = getConfig();
  return path.join(config.OBSIDIAN_AGENT_DIR, 'tasks');
}

function loadTask(name: string): { meta: TaskMeta; prompt: string } {
  const taskPath = path.join(tasksDir(), `${name}.md`);
  if (!fs.existsSync(taskPath)) {
    throw new Error(`Task not found: ${taskPath}`);
  }

  const content = fs.readFileSync(taskPath, 'utf-8');
  let meta: TaskMeta = {};
  let prompt = content;

  if (content.startsWith('---')) {
    const parts = content.split('---', 3);
    if (parts.length >= 3) {
      const frontmatter = parts[1].trim();
      prompt = parts[2].trim();

      // Simple YAML parsing (no dependency)
      for (const line of frontmatter.split('\n')) {
        const stripped = line.trim();
        if (!stripped.includes(':')) continue;

        const colonIdx = stripped.indexOf(':');
        const key = stripped.slice(0, colonIdx).trim();
        const val = stripped.slice(colonIdx + 1).trim();

        // Skip list heads (will be parsed separately)
        if (!val || val.startsWith('-') || val.startsWith('[')) continue;

        if (val.toLowerCase() === 'true' || val.toLowerCase() === 'yes') {
          meta[key] = true;
        } else if (val.toLowerCase() === 'false' || val.toLowerCase() === 'no') {
          meta[key] = false;
        } else {
          meta[key] = val;
        }
      }

      // Parse sources list
      if (!meta.sources) {
        const sources: string[] = [];
        let inSources = false;
        for (const line of frontmatter.split('\n')) {
          const stripped = line.trim();
          if (stripped.startsWith('sources:')) {
            inSources = true;
            continue;
          }
          if (inSources && stripped.startsWith('- ')) {
            sources.push(stripped.slice(2).trim());
          } else if (inSources && !stripped.startsWith('-')) {
            inSources = false;
          }
        }
        if (sources.length > 0) {
          meta.sources = sources;
        }
      }
    }
  }

  return { meta, prompt };
}

// ---------------------------------------------------------------------------
// Source gathering
// ---------------------------------------------------------------------------

async function gatherSources(sources: string[]): Promise<string> {
  const parts: string[] = [];

  if (sources.includes('weather')) {
    try {
      const resp = await fetch('https://wttr.in/Leeds?format=%C+%t+%w+%h', {
        headers: { 'User-Agent': 'curl/7.0' },
        signal: AbortSignal.timeout(10_000),
      });
      if (resp.ok) {
        const weather = (await resp.text()).trim();
        if (weather) {
          parts.push(`## Weather\n${weather}`);
        }
      }
    } catch { /* non-fatal */ }
  }

  if (sources.includes('headlines')) {
    try {
      const resp = await fetch('https://feeds.bbci.co.uk/news/rss.xml', {
        headers: { 'User-Agent': 'curl/7.0' },
        signal: AbortSignal.timeout(10_000),
      });
      const xml = await resp.text();
      // Simple XML title extraction - no dependency
      const titles: string[] = [];
      const itemRe = /<item>[\s\S]*?<\/item>/g;
      const titleRe = /<title><!\[CDATA\[(.*?)\]\]><\/title>|<title>(.*?)<\/title>/;
      let match: RegExpExecArray | null;
      while ((match = itemRe.exec(xml)) !== null && titles.length < 8) {
        const titleMatch = titleRe.exec(match[0]);
        if (titleMatch) {
          titles.push(`- ${titleMatch[1] || titleMatch[2]}`);
        }
      }
      if (titles.length > 0) {
        parts.push(`## Headlines\n${titles.join('\n')}`);
      }
    } catch { /* non-fatal */ }
  }

  if (sources.includes('threads')) {
    try {
      const threads = getActiveThreads();
      if (threads.length > 0) {
        const lines = threads.slice(0, 5).map(
          (t) => `- ${t.name}: ${t.summary || '...'}`,
        );
        parts.push(`## Active threads\n${lines.join('\n')}`);
      }
    } catch { /* non-fatal */ }
  }

  if (sources.includes('summaries')) {
    try {
      const summaries = getRecentSummaries(3);
      if (summaries.length > 0) {
        const lines = summaries.map(
          (s) => `- ${(s.content || '').slice(0, 200)}`,
        );
        parts.push(`## Recent sessions\n${lines.join('\n')}`);
      }
    } catch { /* non-fatal */ }
  }

  if (sources.includes('observations')) {
    try {
      const obs = getRecentObservations(5);
      if (obs.length > 0) {
        const lines = obs.map((o) => `- ${o.content}`);
        parts.push(`## Observations\n${lines.join('\n')}`);
      }
    } catch { /* non-fatal */ }
  }

  return parts.join('\n\n');
}

// ---------------------------------------------------------------------------
// Delivery
// ---------------------------------------------------------------------------

async function deliver(
  text: string,
  meta: TaskMeta,
  taskName: string,
): Promise<void> {
  const config = getConfig();
  const deliverMethod = (meta.deliver as string) || 'message_queue';

  // Pre-synthesise TTS if requested
  let audioPath = '';
  if (meta.voice) {
    try {
      const result = await synthesiseSync(text);
      if (result) {
        audioPath = result;
      }
    } catch (e) {
      log.warn(`TTS failed: ${e}`);
    }
  }

  if (deliverMethod === 'message_queue') {
    await queueMessage(text, taskName, audioPath);
    log.info('Queued for next interaction.');
  } else if (deliverMethod === 'telegram' || deliverMethod === 'telegram_voice') {
    try {
      if (deliverMethod === 'telegram_voice' && audioPath) {
        const sent = await sendVoiceNote(audioPath);
        if (!sent) {
          await telegramSend(text);
        }
      } else {
        await telegramSend(text);
      }
      log.info('Sent via Telegram.');
    } catch (e) {
      log.error(`Telegram failed: ${e}`);
    }
    // Also queue for app
    await queueMessage(text, taskName, audioPath);
  } else if (deliverMethod === 'notification') {
    // Truncate for notification (macOS has limits)
    const body = text.length > 200 ? text.slice(0, 200) + '...' : text;
    sendNotification(config.AGENT_DISPLAY_NAME, body, taskName);
    // Also queue full text
    await queueMessage(text, taskName, audioPath);
  } else if (deliverMethod === 'obsidian') {
    const notePath = path.join(config.OBSIDIAN_AGENT_DIR, 'notes', 'tasks', `${taskName}.md`);
    fs.mkdirSync(path.dirname(notePath), { recursive: true });

    const now = new Date();
    const timestamp = `${now.toISOString().split('T')[0]} ${now.toTimeString().slice(0, 5)}`;
    const entry = `\n---\n**${timestamp}**\n\n${text}\n`;

    fs.appendFileSync(notePath, entry);
    log.debug(`Written to Obsidian: ${notePath}`);
  } else {
    log.warn(`Unknown delivery method: ${deliverMethod}`);
    await queueMessage(text, taskName, audioPath);
  }
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runTask(taskName: string): Promise<void> {
  const config = getConfig();
  const { meta, prompt } = loadTask(taskName);

  log.info(`Running: ${taskName}`);
  log.debug(`Deliver via: ${meta.deliver || 'message_queue'}`);

  // Gather sources if specified
  const sources = meta.sources || [];
  let context = '';
  if (sources.length > 0) {
    log.debug(`Fetching sources: ${sources.join(', ')}`);
    context = await gatherSources(sources);
  }

  // Build inference input
  let userMsg = prompt;
  if (context) {
    userMsg = `Here's the data you requested:\n\n${context}\n\n---\n\n${prompt}`;
  }

  let result: string;
  try {
    result = await runInferenceOneshot(
      [{ role: 'user', content: userMsg }],
      `You are ${config.AGENT_DISPLAY_NAME}. Complete this task naturally, as yourself.`,
    );
  } catch (e) {
    log.error(`Inference failed: ${e}`);
    return;
  }

  if (!result || !result.trim()) {
    log.info('Empty response. Skipping delivery.');
    return;
  }

  log.debug(`Result: ${result.slice(0, 100)}...`);
  await deliver(result, meta, taskName);
}

// ---------------------------------------------------------------------------
// CLI entry point - for launchd
// ---------------------------------------------------------------------------

if (require.main === module) {
  const taskName = process.argv[2];
  if (!taskName) {
    log.error(`Usage: node run-task.js <task_name>`);
    log.error(`Tasks dir: ${tasksDir()}`);
    process.exit(1);
  }
  runTask(taskName).catch((e) => {
    log.error(`Fatal: ${e}`);
    process.exit(1);
  });
}

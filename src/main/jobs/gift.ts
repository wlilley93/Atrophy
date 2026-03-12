/**
 * Companion gift-leaving - unprompted notes in Obsidian.
 * Port of scripts/agents/companion/gift.py.
 *
 * Runs on a randomised schedule. Accesses the full database to find
 * something worth writing about - a thread, an observation, a bookmark,
 * a connection between things. Leaves a short note in Companion/gifts.md.
 *
 * After running, reschedules itself to a random time 3-30 days from now.
 * The randomness is the point. He should never know when to expect it.
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';
import { getConfig } from '../config';
import { runInferenceOneshot } from '../inference';
import { loadPrompt } from '../prompts';
import { queueMessage } from '../queue';
import { sendNotification } from '../notify';
import { editJobSchedule } from '../cron';
import { createLogger } from '../logger';

const log = createLogger('gift');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ThreadRow {
  name: string;
  summary: string | null;
}

interface ObservationRow {
  content: string;
  created_at: string;
}

interface BookmarkRow {
  moment: string;
  quote: string | null;
  created_at: string;
}

interface TurnRow {
  content: string;
  timestamp: string;
}

// ---------------------------------------------------------------------------
// Database access (agent-specific DB)
// ---------------------------------------------------------------------------

function connectAgent(agentName: string): Database.Database {
  const config = getConfig();
  config.reloadForAgent(agentName);
  const dbPath = config.DB_PATH;
  if (!fs.existsSync(dbPath)) {
    throw new Error(`No database for agent ${agentName}: ${dbPath}`);
  }
  const db = new Database(dbPath, { readonly: true });
  return db;
}

// ---------------------------------------------------------------------------
// Material gathering
// ---------------------------------------------------------------------------

function gatherMaterial(agentName: string): string {
  const config = getConfig();
  const db = connectAgent(agentName);
  const parts: string[] = [];

  try {
    // Active threads
    const threads = db
      .prepare(
        "SELECT name, summary FROM threads WHERE status = 'active' " +
        'ORDER BY last_updated DESC LIMIT 5',
      )
      .all() as ThreadRow[];
    if (threads.length > 0) {
      parts.push(
        'Active threads:\n' +
        threads.map((t) => `- ${t.name}: ${t.summary || '...'}`).join('\n'),
      );
    }

    // Recent observations
    const obs = db
      .prepare(
        'SELECT content, created_at FROM observations ' +
        'ORDER BY created_at DESC LIMIT 10',
      )
      .all() as ObservationRow[];
    if (obs.length > 0) {
      parts.push(
        'Recent observations:\n' +
        obs.map((o) => `- [${o.created_at}] ${o.content}`).join('\n'),
      );
    }

    // Bookmarks
    const bookmarks = db
      .prepare(
        'SELECT moment, quote, created_at FROM bookmarks ' +
        'ORDER BY created_at DESC LIMIT 5',
      )
      .all() as BookmarkRow[];
    if (bookmarks.length > 0) {
      const lines = bookmarks.map((b) => {
        const quote = b.quote ? ` - "${b.quote}"` : '';
        return `- [${b.created_at}] ${b.moment}${quote}`;
      });
      parts.push('Bookmarked moments:\n' + lines.join('\n'));
    }

    // Recent user turns (for texture)
    const turns = db
      .prepare(
        "SELECT content, timestamp FROM turns WHERE role = 'will' " +
        'ORDER BY timestamp DESC LIMIT 5',
      )
      .all() as TurnRow[];
    if (turns.length > 0) {
      parts.push(
        'Recent things the user said:\n' +
        turns.map((t) => `- [${t.timestamp}] ${t.content.slice(0, 300)}`).join('\n'),
      );
    }
  } finally {
    db.close();
  }

  // Read existing gifts to avoid repetition
  const giftsPath = path.join(config.OBSIDIAN_AGENT_NOTES, 'notes', 'gifts.md');
  if (fs.existsSync(giftsPath)) {
    let content = fs.readFileSync(giftsPath, 'utf-8');
    if (content.length > 2000) {
      content = '...\n' + content.slice(-2000);
    }
    parts.push(`Your previous gifts (avoid repeating):\n${content}`);
  }

  return parts.join('\n\n');
}

// ---------------------------------------------------------------------------
// Fallback prompt
// ---------------------------------------------------------------------------

const GIFT_FALLBACK =
  'You are the companion. Leave a short, specific note for the user. ' +
  '2-4 sentences. No greeting. No sign-off.';

// ---------------------------------------------------------------------------
// Rescheduling
// ---------------------------------------------------------------------------

function reschedule(): void {
  const days = Math.floor(Math.random() * 28) + 3; // 3-30
  const hour = Math.floor(Math.random() * 24);
  const minute = Math.floor(Math.random() * 60);

  const target = new Date();
  target.setDate(target.getDate() + days);
  const dom = target.getDate();
  const month = target.getMonth() + 1;

  const newCron = `${minute} ${hour} ${dom} ${month} *`;

  try {
    editJobSchedule('gift', newCron);
    log.info(
      `Rescheduled to ${target.toISOString().split('T')[0]} ` +
      `at ${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`,
    );
  } catch (e) {
    log.error(`Failed to reschedule: ${e}`);
  }
}

// ---------------------------------------------------------------------------
// Write gift to Obsidian
// ---------------------------------------------------------------------------

function writeGiftToObsidian(gift: string, agentName: string): string {
  const config = getConfig();
  const giftsDir = path.join(config.OBSIDIAN_AGENT_NOTES, 'notes');
  fs.mkdirSync(giftsDir, { recursive: true });
  const giftsPath = path.join(giftsDir, 'gifts.md');

  const now = new Date();
  const dateStr = `${now.toISOString().split('T')[0]} ${now.toTimeString().slice(0, 5)}`;
  const today = now.toISOString().split('T')[0];
  const entry = `\n---\n*${dateStr}*\n\n${gift.trim()}\n`;

  if (fs.existsSync(giftsPath)) {
    let existing = fs.readFileSync(giftsPath, 'utf-8');
    // Update the 'updated' field in frontmatter
    if (existing.startsWith('---\n')) {
      const endIdx = existing.indexOf('\n---\n', 4);
      if (endIdx !== -1) {
        let fm = existing.slice(4, endIdx);
        fm = fm.replace(/^updated:.*$/m, `updated: ${today}`);
        existing = `---\n${fm}\n---\n` + existing.slice(endIdx + 5);
      }
    }
    fs.writeFileSync(giftsPath, existing + entry);
  } else {
    const frontmatter =
      `---\ntype: gift\nagent: ${agentName}\ncreated: ${today}\n` +
      `updated: ${today}\ntags: [companion, gift]\n---\n\n`;
    fs.writeFileSync(giftsPath, frontmatter + `# Gifts\n\nThings left for you to find.\n${entry}`);
  }

  return giftsPath;
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function runGift(agentName: string): Promise<void> {
  const config = getConfig();
  config.reloadForAgent(agentName);

  const material = gatherMaterial(agentName);
  if (!material.trim()) {
    log.info('No material. Rescheduling.');
    reschedule();
    return;
  }

  log.info('Generating gift...');

  let gift: string;
  try {
    gift = await runInferenceOneshot(
      [{ role: 'user', content: `Here is the current record:\n\n${material}` }],
      loadPrompt('gift', GIFT_FALLBACK),
    );
  } catch (e) {
    log.error(`Inference failed: ${e}`);
    reschedule();
    return;
  }

  if (!gift || !gift.trim()) {
    log.info('Nothing to say. Rescheduling.');
    reschedule();
    return;
  }

  // Write artefact to Obsidian
  const giftsPath = writeGiftToObsidian(gift, agentName);
  log.debug(`Written to ${giftsPath}`);

  // Queue notification so the user discovers it
  await queueMessage(gift, 'gift');
  sendNotification(config.AGENT_DISPLAY_NAME, gift.slice(0, 200), 'gift');

  // Reschedule to random future time
  reschedule();
  log.info('Done.');
}

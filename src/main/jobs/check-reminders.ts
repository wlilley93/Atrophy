/**
 * Check and fire due reminders.
 * Port of scripts/agents/companion/check_reminders.py.
 *
 * Runs every minute via launchd. Reads reminders from the agent's
 * reminder store, fires notifications + queues messages for any
 * that are due, then removes them.
 *
 * Reminders are stored in agents/<name>/data/.reminders.json:
 * [
 *   {
 *     "id": "uuid",
 *     "time": "2024-03-10T14:30:00",
 *     "message": "Take out the bins",
 *     "source": "will",
 *     "created_at": "2024-03-10T12:00:00"
 *   }
 * ]
 *
 * Dual-use: callable as a function from the main process, or runnable
 * as a standalone launchd script via the CLI entry point at the bottom.
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from '../config';
import { createLogger } from '../logger';

const log = createLogger('reminder');
import { sendNotification } from '../notify';
import { queueMessage } from '../queue';
import { sendMessage as telegramSend } from '../telegram';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Reminder {
  id: string;
  time: string;
  message: string;
  source: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Reminder storage
// ---------------------------------------------------------------------------

function remindersPath(): string {
  const config = getConfig();
  return path.join(config.DATA_DIR, '.reminders.json');
}

function loadReminders(): Reminder[] {
  const p = remindersPath();
  if (!fs.existsSync(p)) return [];
  try {
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch {
    return [];
  }
}

function saveReminders(reminders: Reminder[]): void {
  const p = remindersPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  // Write to temp file then rename for atomicity (prevents data loss
  // if another process writes between our read and write)
  const tmp = p + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(reminders, null, 2) + '\n');
  fs.renameSync(tmp, p);
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export async function checkReminders(): Promise<void> {
  const config = getConfig();
  const reminders = loadReminders();
  if (reminders.length === 0) return;

  const now = new Date();
  const due: Reminder[] = [];
  const remaining: Reminder[] = [];

  for (const r of reminders) {
    let remindTime: Date;
    try {
      remindTime = new Date(r.time);
      if (isNaN(remindTime.getTime())) {
        remaining.push(r);
        continue;
      }
    } catch {
      remaining.push(r);
      continue;
    }

    if (remindTime <= now) {
      due.push(r);
    } else {
      remaining.push(r);
    }
  }

  if (due.length === 0) return;

  // Fire due reminders
  for (const r of due) {
    const msg = r.message || 'Reminder';
    log.info(`Firing: ${msg}`);

    // macOS notification with sound
    sendNotification(`Reminder - ${config.AGENT_DISPLAY_NAME}`, msg);

    // Queue for next app interaction
    queueMessage(`Reminder: ${msg}`, 'reminder');

    // Send via Telegram if configured
    try {
      if (config.TELEGRAM_BOT_TOKEN && config.TELEGRAM_CHAT_ID) {
        await telegramSend(`Reminder: ${msg}`);
      }
    } catch { /* non-fatal */ }
  }

  // Re-read to merge any reminders added while we were firing notifications,
  // then remove only the ones we actually fired (by time+message identity)
  const firedSet = new Set(due.map(r => `${r.time}|${r.message}`));
  const fresh = loadReminders();
  const merged = fresh.filter(r => !firedSet.has(`${r.time}|${r.message}`));
  saveReminders(merged);
  log.info(`Fired ${due.length}, ${merged.length} remaining.`);
}

// ---------------------------------------------------------------------------
// CLI entry point - for launchd
// ---------------------------------------------------------------------------

if (require.main === module) {
  checkReminders().catch((e) => {
    log.error(`Fatal: ${e}`);
    process.exit(1);
  });
}

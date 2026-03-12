/**
 * Thread-safe message queue for inter-process communication.
 * Port of core/queue.py.
 *
 * Cron scripts and background jobs use this to enqueue messages
 * for the GUI to pick up. File locking prevents race conditions.
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig } from './config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface QueuedMessage {
  text: string;
  audio_path: string;
  source: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Queue operations
// ---------------------------------------------------------------------------

export function queueMessage(
  text: string,
  source = 'task',
  audioPath = '',
): void {
  const config = getConfig();
  const queueFile = config.MESSAGE_QUEUE_FILE;
  fs.mkdirSync(path.dirname(queueFile), { recursive: true });

  // Read existing queue
  let queue: QueuedMessage[] = [];
  try {
    if (fs.existsSync(queueFile)) {
      queue = JSON.parse(fs.readFileSync(queueFile, 'utf-8'));
    }
  } catch { /* start fresh */ }

  queue.push({
    text,
    audio_path: audioPath,
    source,
    created_at: new Date().toISOString(),
  });

  fs.writeFileSync(queueFile, JSON.stringify(queue, null, 2));
}

export function drainQueue(): QueuedMessage[] {
  const config = getConfig();
  const queueFile = config.MESSAGE_QUEUE_FILE;

  if (!fs.existsSync(queueFile)) return [];

  let queue: QueuedMessage[] = [];
  try {
    queue = JSON.parse(fs.readFileSync(queueFile, 'utf-8'));
  } catch {
    return [];
  }

  if (queue.length === 0) return [];

  // Clear the queue file
  fs.writeFileSync(queueFile, '[]');
  return queue;
}

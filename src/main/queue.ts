/**
 * Thread-safe message queue for inter-process communication.
 * Port of core/queue.py.
 *
 * Cron scripts and background jobs use this to enqueue messages
 * for the GUI to pick up. File locking prevents race conditions.
 */

import * as fs from 'fs';
import * as path from 'path';
import { getConfig, USER_DATA } from './config';

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
// File locking (async - non-blocking)
// ---------------------------------------------------------------------------

const LOCK_RETRY_INTERVAL_MS = 50;
const LOCK_TIMEOUT_MS = 5000;
const LOCK_STALE_MS = 30000; // consider lock stale after 30s

/**
 * Wait for the given number of milliseconds without blocking the event loop.
 */
function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Acquire an exclusive lock file asynchronously. Uses O_CREAT | O_EXCL (wx flag)
 * for atomic creation - only one process can create the file. Retries with
 * setTimeout-based delay up to the timeout, never blocking the event loop.
 *
 * Returns the lock file path on success so the caller can release it.
 */
async function acquireLock(queueFile: string): Promise<string> {
  const lockPath = queueFile + '.lock';
  const deadline = Date.now() + LOCK_TIMEOUT_MS;

  while (Date.now() < deadline) {
    try {
      // Atomic create - fails if file already exists
      const fd = fs.openSync(lockPath, 'wx');
      // Write our PID so stale detection can identify the owner
      fs.writeSync(fd, String(process.pid));
      fs.closeSync(fd);
      return lockPath;
    } catch (err: unknown) {
      const code = (err as NodeJS.ErrnoException).code;
      if (code === 'EEXIST') {
        // Lock file exists - check if stale
        try {
          const stat = fs.statSync(lockPath);
          if (Date.now() - stat.mtimeMs > LOCK_STALE_MS) {
            // Stale lock - remove and retry immediately
            fs.unlinkSync(lockPath);
            continue;
          }
        } catch {
          // Lock file vanished between check and stat - retry
          continue;
        }
        // Wait without blocking the event loop, then retry
        await delay(LOCK_RETRY_INTERVAL_MS);
      } else {
        // Unexpected error (permissions, disk full, etc.) - throw
        throw err;
      }
    }
  }

  throw new Error(`Failed to acquire lock on ${lockPath} within ${LOCK_TIMEOUT_MS}ms`);
}

/**
 * Release the lock by removing the lock file.
 */
function releaseLock(lockPath: string): void {
  try {
    fs.unlinkSync(lockPath);
  } catch {
    // Already removed - not our problem
  }
}

/**
 * Execute an async function while holding an exclusive file lock on the queue file.
 * The lock is always released, even if the function throws.
 */
async function withLock<T>(queueFile: string, fn: () => T | Promise<T>): Promise<T> {
  const lockPath = await acquireLock(queueFile);
  try {
    return await fn();
  } finally {
    releaseLock(lockPath);
  }
}

// ---------------------------------------------------------------------------
// Queue operations
// ---------------------------------------------------------------------------

export async function queueMessage(
  text: string,
  source = 'task',
  audioPath = '',
): Promise<void> {
  const config = getConfig();
  const queueFile = config.MESSAGE_QUEUE_FILE;
  fs.mkdirSync(path.dirname(queueFile), { recursive: true });

  await withLock(queueFile, () => {
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
  });
}

export async function drainQueue(): Promise<QueuedMessage[]> {
  const config = getConfig();
  const queueFile = config.MESSAGE_QUEUE_FILE;

  if (!fs.existsSync(queueFile)) return [];

  return withLock(queueFile, () => {
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
  });
}

// ---------------------------------------------------------------------------
// Per-agent queue draining (for multi-agent message delivery)
// ---------------------------------------------------------------------------

/**
 * Drain message queue for a specific agent.
 * Used during boot and agent switching to deliver pending messages.
 */
export async function drainAgentQueue(agentName: string): Promise<QueuedMessage[]> {
  const queueFile = path.join(
    USER_DATA,
    'agents',
    agentName,
    'data',
    '.message_queue.json',
  );

  if (!fs.existsSync(queueFile)) return [];

  return withLock(queueFile, () => {
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
  });
}

/**
 * Drain all agents' queues. Returns a map of agent name to messages.
 */
export async function drainAllAgentQueues(): Promise<Record<string, QueuedMessage[]>> {
  const agentsDir = path.join(USER_DATA, 'agents');
  const result: Record<string, QueuedMessage[]> = {};

  if (!fs.existsSync(agentsDir)) return result;

  const agents = fs.readdirSync(agentsDir);
  for (const agent of agents) {
    const messages = await drainAgentQueue(agent);
    if (messages.length > 0) {
      result[agent] = messages;
    }
  }

  return result;
}

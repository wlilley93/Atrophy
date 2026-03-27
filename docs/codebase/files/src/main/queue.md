# src/main/queue.ts - Thread-Safe Message Queue

**Dependencies:** `fs`, `path`, `./config`  
**Purpose:** Thread-safe message queue for inter-process communication with cron scripts and background jobs

## Overview

Cron scripts and background jobs use this queue to enqueue messages for the GUI to pick up. File locking prevents race conditions between multiple writers (cron jobs, Telegram daemon, etc.).

## Types

```typescript
export interface QueuedMessage {
  text: string;
  audio_path: string;
  source: string;
  created_at: string;
}
```

**Fields:**
- `text`: Message content
- `audio_path`: Path to optional audio file
- `source`: Message source (e.g., 'task', 'heartbeat', 'telegram')
- `created_at`: ISO 8601 timestamp

## File Locking (Async, Non-Blocking)

```typescript
const LOCK_RETRY_INTERVAL_MS = 50;
const LOCK_TIMEOUT_MS = 5000;
const LOCK_STALE_MS = 30000; // Consider lock stale after 30s
```

### delay

```typescript
function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
```

**Purpose:** Wait without blocking the event loop

### acquireLock

```typescript
async function acquireLock(queueFile: string): Promise<string> {
  const lockPath = queueFile + '.lock';
  const deadline = Date.now() + LOCK_TIMEOUT_MS;

  while (Date.now() < deadline) {
    try {
      // Atomic create - fails if file already exists (O_CREAT | O_EXCL)
      const fd = fs.openSync(lockPath, 'wx');
      // Write our PID for stale detection
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
          // Lock file vanished - retry
          continue;
        }
        // Wait without blocking event loop, then retry
        await delay(LOCK_RETRY_INTERVAL_MS);
      } else {
        // Unexpected error - throw
        throw err;
      }
    }
  }

  throw new Error(`Failed to acquire lock on ${lockPath} within ${LOCK_TIMEOUT_MS}ms`);
}
```

**Lock mechanism:**
1. Use `wx` flag (O_CREAT | O_EXCL) for atomic creation
2. Write PID to lock file for stale detection
3. If lock exists, check modification time
4. If stale (>30s), remove and retry
5. If not stale, wait 50ms and retry
6. Timeout after 5 seconds

**Why async:** Node.js event loop must not block during lock acquisition

### releaseLock

```typescript
function releaseLock(lockPath: string): void {
  try {
    fs.unlinkSync(lockPath);
  } catch {
    // Already removed - not our problem
  }
}
```

**Purpose:** Release lock by removing lock file

### withLock

```typescript
async function withLock<T>(queueFile: string, fn: () => T | Promise<T>): Promise<T> {
  const lockPath = await acquireLock(queueFile);
  try {
    return await fn();
  } finally {
    releaseLock(lockPath);
  }
}
```

**Purpose:** Execute async function while holding exclusive file lock

**Guarantee:** Lock always released, even if function throws

## Queue Operations

### queueMessage

```typescript
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
```

**Purpose:** Add message to queue with file locking

**Default source:** `'task'`

### drainQueue

```typescript
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
```

**Purpose:** Read and clear queue atomically

**Returns:** All queued messages, or empty array

## Per-Agent Queue Operations

### drainAgentQueue

```typescript
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

    fs.writeFileSync(queueFile, '[]');
    return queue;
  });
}
```

**Purpose:** Drain message queue for specific agent

**Use case:** Agent switching - deliver pending messages to new agent

### drainAllAgentQueues

```typescript
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
```

**Purpose:** Drain all agents' queues

**Returns:** Map of agent name to messages

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read/Write | `~/.atrophy/agents/<name>/data/.message_queue.json` | Per-agent queue |
| Read/Write | `~/.atrophy/agents/<name>/data/.message_queue.json.lock` | Lock file |
| Read/Write | `~/.atrophy/agents/<name>/data/.message_queue.json` | Global queue (legacy) |

## Exported API

| Function | Purpose |
|----------|---------|
| `queueMessage(text, source, audioPath)` | Add message to queue |
| `drainQueue()` | Read and clear global queue |
| `drainAgentQueue(agentName)` | Drain specific agent's queue |
| `drainAllAgentQueues()` | Drain all agents' queues |
| `QueuedMessage` | Message interface |

## See Also

- `src/main/channels/cron.ts` - Cron jobs use queueMessage
- `src/main/channels/telegram/daemon.ts` - Telegram uses queueMessage
- `src/main/ipc/agents.ts` - queue:drainAgent, queue:drainAll IPC handlers
- `src/main/app.ts` - Queue polling timer

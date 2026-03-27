# src/main/channels/switchboard.ts - Central Message Switchboard

**Dependencies:** `uuid`, `../config`, `../logger`  
**Purpose:** Central message routing - all messages flow through here as Envelopes with source/destination addresses

## Overview

The switchboard is the central routing engine for inter-agent communication. Every message is wrapped in an `Envelope` with source/destination addresses. Handlers register for address patterns, and the switchboard routes envelopes to matching handlers. It supports wildcards for broadcast, maintains a message log, and provides a service directory for discovery.

## Types

### Envelope

```typescript
export interface Envelope {
  id: string;            // unique message ID (uuid)
  from: string;          // source address (e.g. "telegram:xan", "desktop:companion")
  to: string;            // destination address (e.g. "agent:xan", "agent:*")
  text: string;          // message content
  type: 'user' | 'agent' | 'system';
  priority: 'normal' | 'high' | 'system';
  replyTo?: string;      // where to send response
  timestamp: number;     // Date.now()
  metadata?: Record<string, unknown>;
}
```

**Address format:** `<channel>:<agent>` e.g., `telegram:xan`, `desktop:companion`, `agent:*`

### MessageHandler

```typescript
export type MessageHandler = (envelope: Envelope) => Promise<void>;
```

### ServiceEntry

```typescript
export interface ServiceEntry {
  address: string;       // e.g. "telegram:xan", "agent:companion"
  type: 'channel' | 'agent' | 'system' | 'webhook' | 'mcp';
  description: string;   // human-readable description
  capabilities?: string[]; // what this service can do
  registeredAt: number;  // timestamp
}
```

**Purpose:** Metadata about registered handlers for service discovery.

## Switchboard Class

### Properties

```typescript
class Switchboard {
  private handlers: Map<string, MessageHandler> = new Map();
  private directory: Map<string, ServiceEntry> = new Map();
  private messageLog: Envelope[] = [];
  private queuePollTimer: ReturnType<typeof setInterval> | null = null;
}
```

**Constants:**
- `MAX_LOG_SIZE = 200` - Max messages to retain
- `QUEUE_POLL_INTERVAL = 2000` - MCP queue poll interval (ms)

### register

```typescript
register(address: string, handler: MessageHandler, meta?: Partial<ServiceEntry>): void {
  if (this.handlers.has(address)) {
    log.warn(`Overwriting existing handler for ${address}`);
  }
  this.handlers.set(address, handler);

  // Infer service type from address prefix
  const inferType = (): ServiceEntry['type'] => {
    if (address.startsWith('agent:')) return 'agent';
    if (address.startsWith('telegram:') || address.startsWith('desktop:')) return 'channel';
    if (address.startsWith('webhook:')) return 'webhook';
    if (address.startsWith('mcp:')) return 'mcp';
    return 'system';
  };

  this.directory.set(address, {
    address,
    type: meta?.type || inferType(),
    description: meta?.description || address,
    capabilities: meta?.capabilities,
    registeredAt: Date.now(),
  });

  log.info(`Registered handler: ${address} (${this.directory.get(address)!.type})`);
}
```

**Purpose:** Register handler for address with service metadata.

**Address patterns:**
- Exact: `agent:xan`
- Wildcard: `agent:*` (matches all agents)

**Type inference:**
- `agent:*` → `'agent'`
- `telegram:*`, `desktop:*` → `'channel'`
- `webhook:*` → `'webhook'`
- `mcp:*` → `'mcp'`
- Default → `'system'`

### unregister

```typescript
unregister(address: string): void {
  if (this.handlers.delete(address)) {
    log.info(`Unregistered handler: ${address}`);
  }
}
```

### route

```typescript
async route(envelope: Envelope): Promise<void> {
  // Log the message
  this.messageLog.push(envelope);
  if (this.messageLog.length > MAX_LOG_SIZE) {
    this.messageLog = this.messageLog.slice(-MAX_LOG_SIZE);
  }

  log.debug(
    `Route: ${envelope.from} -> ${envelope.to} [${envelope.type}/${envelope.priority}] "${envelope.text.slice(0, 80)}"`,
  );

  const target = envelope.to;

  // Broadcast - deliver to all matching handlers
  if (target.endsWith(':*')) {
    const prefix = target.slice(0, -1); // "agent:*" -> "agent:"
    const delivered: string[] = [];

    for (const [address, handler] of this.handlers) {
      if (address.startsWith(prefix) && address !== envelope.from) {
        try {
          await handler(envelope);
          delivered.push(address);
        } catch (err) {
          log.error(`Handler error for ${address}: ${err}`);
        }
      }
    }

    if (delivered.length === 0) {
      log.warn(`No handlers matched broadcast ${target}`);
    } else {
      log.debug(`Broadcast ${target} delivered to: ${delivered.join(', ')}`);
    }
    return;
  }

  // Exact match
  const handler = this.handlers.get(target);
  if (handler) {
    try {
      await handler(envelope);
    } catch (err) {
      log.error(`Handler error for ${target}: ${err}`);
    }
    return;
  }

  log.warn(`No handler for address: ${target}`);
}
```

**Routing logic:**

1. **Log message:** Add to message log (max 200 entries)
2. **Broadcast (`:*`):** Deliver to ALL handlers matching prefix (excluding sender)
3. **Exact match:** Deliver to specific handler
4. **No match:** Log warning

**Example broadcast:**
```
from: telegram:xan
to: agent:*
→ Delivers to: agent:xan, agent:kai, agent:nova (but NOT telegram:xan)
```

### record

```typescript
record(envelope: Envelope): void {
  this.messageLog.push(envelope);
  if (this.messageLog.length > MAX_LOG_SIZE) {
    this.messageLog = this.messageLog.slice(-MAX_LOG_SIZE);
  }
  log.debug(
    `Record: ${envelope.from} -> ${envelope.to} [${envelope.type}] "${envelope.text.slice(0, 80)}"`,
  );
}
```

**Purpose:** Log message without delivery. Used when caller handles delivery directly (e.g., desktop GUI inference).

### createEnvelope

```typescript
createEnvelope(
  from: string,
  to: string,
  text: string,
  opts?: Partial<Envelope>,
): Envelope {
  return {
    id: uuidv4(),
    from,
    to,
    text,
    type: opts?.type || 'user',
    priority: opts?.priority || 'normal',
    replyTo: opts?.replyTo || from,
    timestamp: Date.now(),
    metadata: opts?.metadata,
  };
}
```

**Purpose:** Helper to create envelope with defaults.

### getRecentMessages

```typescript
getRecentMessages(count?: number): Envelope[] {
  return this.messageLog.slice(-(count || 50));
}
```

**Returns:** Recent messages for debugging (default 50)

### hasHandler / getRegisteredAddresses

```typescript
hasHandler(address: string): boolean {
  return this.handlers.has(address);
}

getRegisteredAddresses(): string[] {
  return Array.from(this.handlers.keys());
}
```

## Service Directory

### getDirectory

```typescript
getDirectory(): ServiceEntry[] {
  return Array.from(this.directory.values());
}
```

**Purpose:** Get full service directory for agent discovery.

### getDirectoryByType

```typescript
getDirectoryByType(type: ServiceEntry['type']): ServiceEntry[] {
  return this.getDirectory().filter(e => e.type === type);
}
```

**Purpose:** Filter directory by type (channel, agent, system, webhook, mcp).

### getService

```typescript
getService(address: string): ServiceEntry | undefined {
  return this.directory.get(address);
}
```

**Purpose:** Get single service entry by address.

## MCP Queue Polling

### startQueuePolling

```typescript
startQueuePolling(): void {
  if (this.queuePollTimer) return;

  const fs = require('fs');
  const path = require('path');
  const queuePath = path.join(USER_DATA, '.switchboard_queue.json');

  this.queuePollTimer = setInterval(async () => {
    try {
      if (!fs.existsSync(queuePath)) return;

      // Atomic read-and-clear: rename to temp path
      const tmpPath = queuePath + `.poll-${process.pid}-${Date.now()}`;
      try {
        fs.renameSync(queuePath, tmpPath);
      } catch { return; }
      
      // Restore empty queue immediately
      fs.writeFileSync(queuePath, '[]');

      const raw = fs.readFileSync(tmpPath, 'utf8');
      try { fs.unlinkSync(tmpPath); } catch { /* cleanup */ }

      const envelopes: Envelope[] = JSON.parse(raw);
      if (envelopes.length === 0) return;

      // Process each envelope
      for (const env of envelopes) {
        log.info(`Queue: ${env.from} -> ${env.to} "${env.text?.slice(0, 60)}"`);
        try {
          await this.route(env);
        } catch (err) {
          log.error(`Queue envelope error: ${err}`);
        }
      }
    } catch { /* ignore */ }
  }, QUEUE_POLL_INTERVAL);
}
```

**Purpose:** Poll MCP queue file for envelopes from Python MCP servers.

**Atomic read pattern (FIXED 2026-03-26):**
1. Rename queue file to temp path (prevents TOCTOU race)
2. Restore empty queue immediately (MCP servers can keep writing)
3. Read and process temp file
4. Clean up temp file

**Bug fix:** Previous implementation had a TOCTOU race where the Python MCP server could append envelopes between `readFileSync` and `writeFileSync('[]')`, silently dropping messages. The atomic rename pattern eliminates this race.

## Singleton

```typescript
export const switchboard = new Switchboard();
```

**Usage:** `import { switchboard } from './switchboard'`

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/.switchboard_queue.json` | Queue polling |
| Write | `~/.atrophy/.switchboard_queue.json` | Queue polling (restore empty) |
| Read/Write | `~/.atrophy/.switchboard_queue.json.poll-*` | Queue polling (temp) |

## Exported API

| Function/Class | Purpose |
|----------------|---------|
| `Switchboard` | Main switchboard class |
| `switchboard` | Singleton instance |
| `Envelope` | Message envelope type |
| `ServiceEntry` | Service directory entry type |
| `MessageHandler` | Handler function type |

## See Also

- `src/main/ipc/agents.ts` - Registers desktop handlers
- `src/main/ipc/inference.ts` - Records messages through switchboard
- `src/main/mcp-registry.ts` - Registers MCP servers with switchboard
- `mcp/memory_server.py` - Writes envelopes to queue file

# src/main/channels/agent-router.ts - Per-Agent Message Router

**Dependencies:** `./switchboard`, `../logger`  
**Purpose:** Per-agent message filtering, queue depth limits, and outbound permission checks

## Overview

The agent router sits between the switchboard and an agent's inference engine. Each agent has one router instance that handles:
- Inbound message filtering (accept/reject lists)
- Queue depth limits (prevent overload)
- Outbound permission checks (system access, agent addressing)

**Difference from agent-manager.ts:** Agent-manager handles agent *lifecycle* (discovery, switching, state). Agent-router handles *message routing* for a specific agent.

## Types

### AgentRouterConfig

```typescript
export interface AgentRouterConfig {
  acceptFrom: string[];       // addresses to accept ("*" = all)
  rejectFrom: string[];       // addresses to block (checked before accept)
  maxQueueDepth: number;      // pending messages before rejecting
  systemAccess: boolean;      // can send system commands
  canAddressAgents: boolean;  // can message other agents
}
```

### AgentMessageCallback

```typescript
export type AgentMessageCallback = (envelope: Envelope) => Promise<string | void>;
```

**Purpose:** Callback invoked when a message passes filtering. Returns response text or void for fire-and-forget.

## Default Configs

### DEFAULT_CONFIG

```typescript
const DEFAULT_CONFIG: AgentRouterConfig = {
  acceptFrom: ['*'],
  rejectFrom: [],
  maxQueueDepth: 10,
  systemAccess: false,
  canAddressAgents: true,
};
```

### defaultConfigForAgent

```typescript
export function defaultConfigForAgent(agentName: string): AgentRouterConfig {
  if (agentName === 'xan') {
    return {
      acceptFrom: ['*'],
      rejectFrom: [],
      maxQueueDepth: 20,
      systemAccess: true,
      canAddressAgents: true,
    };
  }
  return { ...DEFAULT_CONFIG };
}
```

**Xan privileges:**
- Higher queue depth (20 vs 10)
- System access enabled

## AgentRouter Class

### Constructor

```typescript
export class AgentRouter {
  private address: string;
  private queueDepth = 0;

  constructor(
    private agentName: string,
    private config: AgentRouterConfig,
    private onMessage: AgentMessageCallback,
  ) {
    this.address = `agent:${agentName}`;

    // Register with switchboard
    switchboard.register(this.address, this.handleInbound.bind(this));

    log.info(
      `[${agentName}] Router created - accept: [${config.acceptFrom.join(', ')}], ` +
      `system: ${config.systemAccess}, agents: ${config.canAddressAgents}`,
    );
  }
}
```

**Registration:** Registers `agent:<name>` address with switchboard

### handleInbound

```typescript
private async handleInbound(envelope: Envelope): Promise<void> {
  // Check reject list first (takes priority over accept)
  if (this.isRejected(envelope.from)) {
    log.debug(`[${this.agentName}] Rejected message from ${envelope.from}`);
    return;
  }

  // Check accept list
  if (!this.isAccepted(envelope.from)) {
    log.debug(`[${this.agentName}] Not accepted from ${envelope.from}`);
    return;
  }

  // Check queue depth
  if (this.queueDepth >= this.config.maxQueueDepth) {
    log.warn(`[${this.agentName}] Queue full, dropping message from ${envelope.from}`);
    return;
  }

  // System messages are injected as context - don't run inference
  if (envelope.type === 'system') {
    log.debug(`[${this.agentName}] System message from ${envelope.from}`);
    try {
      await this.onMessage(envelope);
    } catch (err) {
      log.error(`[${this.agentName}] System message handler error: ${err}`);
    }
    return;
  }

  // User or agent message - run inference
  this.queueDepth++;
  try {
    const response = await this.onMessage(envelope);

    // Route response back via switchboard using envelope.replyTo
    if (response && envelope.replyTo) {
      const responseEnvelope = switchboard.createEnvelope(
        this.address,
        envelope.replyTo,
        response,
        {
          type: 'agent',
          priority: 'normal',
          metadata: {
            inReplyTo: envelope.id,
            agentName: this.agentName,
          },
        },
      );
      await switchboard.route(responseEnvelope);
    }
  } catch (err) {
    log.error(`[${this.agentName}] Message handler error: ${err}`);
  } finally {
    this.queueDepth--;
  }
}
```

**Filtering order:**
1. Reject list (highest priority)
2. Accept list
3. Queue depth check

**Message types:**
- `system`: Injected as context, no inference, fire-and-forget
- `user`/`agent`: Run inference, route response back

### isRejected

```typescript
private isRejected(from: string): boolean {
  return this.config.rejectFrom.some(
    (pattern) => from === pattern || from.startsWith(pattern + ':'),
  );
}
```

**Pattern matching:** Exact match or prefix match (e.g., `agent:spam` matches `agent:spam:*`)

### isAccepted

```typescript
private isAccepted(from: string): boolean {
  if (this.config.acceptFrom.includes('*')) return true;
  return this.config.acceptFrom.some(
    (pattern) => from === pattern || from.startsWith(pattern + ':'),
  );
}
```

**Wildcard:** `*` accepts from all addresses

## Usage Example

```typescript
import { AgentRouter, defaultConfigForAgent } from './channels/agent-router';

// Create router for Xan
const xanRouter = new AgentRouter(
  'xan',
  defaultConfigForAgent('xan'),
  async (envelope) => {
    // Run inference
    const response = await runInference(envelope.text);
    return response;
  },
);

// Create router for Montgomery with custom config
const montgomeryRouter = new AgentRouter(
  'montgomery',
  {
    acceptFrom: ['telegram:montgomery', 'agent:xan'],
    rejectFrom: ['agent:spam'],
    maxQueueDepth: 5,
    systemAccess: false,
    canAddressAgents: false,
  },
  async (envelope) => {
    // Run inference
  },
);
```

## Integration with Switchboard

```
┌─────────────────────────────────────────────────────────────────┐
│                    Message Flow                                  │
│                                                                   │
│  Switchboard ──▶ AgentRouter.handleInbound()                     │
│                      │                                           │
│                      ▼                                           │
│              ┌───────────────┐                                   │
│              │ isRejected()? │──Yes──▶ Drop                     │
│              └───────────────┘                                   │
│                      │ No                                        │
│                      ▼                                           │
│              ┌───────────────┐                                   │
│              │ isAccepted()? │──No──▶ Drop                      │
│              └───────────────┘                                   │
│                      │ Yes                                       │
│                      ▼                                           │
│              ┌───────────────┐                                   │
│              │ Queue full?   │──Yes──▶ Drop                     │
│              └───────────────┘                                   │
│                      │ No                                        │
│                      ▼                                           │
│              ┌───────────────┐                                   │
│              │ System type?  │──Yes──▶ Inject context            │
│              └───────────────┘                                   │
│                      │ No                                        │
│                      ▼                                           │
│              ┌───────────────┐                                   │
│              │ onMessage()   │──▶ Inference                      │
│              └───────────────┘                                   │
│                      │                                           │
│                      ▼                                           │
│              Route response via switchboard                      │
└─────────────────────────────────────────────────────────────────┘
```

## File I/O

None - router is purely in-memory.

## Exported API

| Function/Class | Purpose |
|----------------|---------|
| `AgentRouter` | Per-agent message router class |
| `AgentRouterConfig` | Router configuration interface |
| `AgentMessageCallback` | Message handler callback type |
| `defaultConfigForAgent(agentName)` | Get default config for known agent |

## See Also

- [`switchboard.md`](switchboard.md) - Central message switchboard
- [`daemon.ts`](telegram/daemon.md) - Telegram daemon uses agent router
- [`inference.ts`](../inference.md) - Inference engine called by router

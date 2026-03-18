# Switchboard Architecture

## Design

A central message switchboard through which ALL communication flows - inbound from external channels, outbound to users, and inter-agent.

### Core Concepts

**Switchboard** - single entry point for all messages. Routes based on destination address. Logs everything. Doesn't know or care about channel specifics.

**Agent Router** - each agent has one. Sits between the switchboard and the agent's inference engine. Decides how to handle inbound messages: accept, reject, queue, transform. Also handles outbound - agent responses go back through the switchboard to the correct destination.

**Addresses** - every entity has an address:
- `telegram:xan` - Xan's Telegram bot
- `desktop:companion` - Companion's desktop GUI
- `agent:xan` - Xan's inference engine
- `agent:companion` - Companion's inference engine
- `system` - system-level broadcasts
- `webhook:myapp` - external webhook
- `cron:heartbeat:xan` - Xan's heartbeat job

**Envelope** - every message is wrapped:
```typescript
interface Envelope {
  from: string;        // source address
  to: string;          // destination address
  text: string;        // message content
  type: 'user' | 'agent' | 'system';  // message class
  priority: 'normal' | 'high' | 'system';
  replyTo?: string;    // address to send response back to
  metadata?: Record<string, unknown>;
}
```

### Message Flows

**User sends Telegram message to Xan:**
```
from: "telegram:xan"
to: "agent:xan"
replyTo: "telegram:xan"
type: "user"
```
Switchboard delivers to Xan's Agent Router. Router accepts, forwards to inference. Response envelope:
```
from: "agent:xan"
to: "telegram:xan"  (copied from replyTo)
type: "agent"
```

**Xan asks Companion a question:**
```
from: "agent:xan"
to: "agent:companion"
replyTo: "agent:xan"
type: "agent"
priority: "normal"
```
Switchboard delivers to Companion's Agent Router. Router accepts, runs full inference. Response goes back to Xan's router, which injects it as context into Xan's next turn.

**System broadcast (e.g. "Will is away"):**
```
from: "system"
to: "agent:*"  (broadcast)
type: "system"
priority: "system"
```
Switchboard delivers to ALL agent routers. Each router handles it as context injection (lightweight, no inference).

**Xan sends a system command (e.g. "mute Companion for 1 hour"):**
```
from: "agent:xan"
to: "system"
type: "system"
priority: "high"
text: "mute agent:companion duration:60m"
```
Switchboard handles system commands directly. Xan has elevated system access.

### Agent Router Per-Agent

Each agent's router is configured independently:

```typescript
interface AgentRouterConfig {
  accept_from: string[];     // addresses this agent accepts messages from
  reject_from: string[];     // addresses to block
  max_queue_depth: number;   // how many pending messages before rejecting
  system_access: boolean;    // can this agent send system commands?
  can_address_agents: boolean; // can this agent message other agents?
}
```

**Xan's router:**
- accept_from: ["*"] (accepts everything)
- system_access: true (can send system commands)
- can_address_agents: true

**Companion's router:**
- accept_from: ["telegram:companion", "desktop:companion", "agent:xan", "system", "cron:*"]
- system_access: false
- can_address_agents: true (can ask questions, but not send commands)

### Xan's System Role

Xan's agent router has elevated privileges:
- Can send `type: "system"` messages that the switchboard executes
- Can broadcast to all agents
- Can mute/unmute other agents
- Can query switchboard state (who's active, message counts, etc.)
- These capabilities are exposed as MCP tools on Xan's memory server

### Lightweight vs Full Inference

**Full inference** (agent-to-agent conversation):
- `type: "agent"` messages to `agent:*` addresses
- Delivered as input to the target agent's Claude session
- Target agent processes with full personality and responds
- Used for "ask Companion what she thinks about X"

**System level** (no inference):
- `type: "system"` messages
- Handled by the switchboard or injected as context
- Used for "Will is away", "mute for 1 hour", status updates
- Xan can send both

### Implementation in Electron App

The switchboard lives in `src/main/switchboard.ts`:
- Singleton, created on app startup
- All existing message paths rewired through it
- telegram-daemon.ts creates envelopes, sends to switchboard
- app.ts (desktop input) creates envelopes, sends to switchboard
- inference responses create envelopes back through switchboard

Each agent router lives in `src/main/agent-router.ts`:
- One instance per agent
- Config loaded from agent.json (new `router` section)
- Registered with switchboard on agent discovery

### What Changes in Existing Code

1. `telegram-daemon.ts` - wrap messages in Envelope, send to switchboard instead of calling streamInference directly. Receive responses from switchboard instead of inline.
2. `app.ts` - desktop input goes through switchboard
3. `inference.ts` - responses go back through switchboard
4. `router.ts` - deleted (replaced by switchboard + agent routers)
5. MCP memory server - add switchboard tools for Xan (send_message_to_agent, broadcast, query_status)

### What Agents Know

Agents don't know about the switchboard directly. They interact through:
1. **MCP tools** - `send_message(to, text)`, `broadcast(text)`, `query_status()`
2. **Context injection** - system messages appear as context, not as user messages
3. **Response routing** - handled automatically by their agent router

This means agents can learn to use inter-agent communication through their MCP tools, and could theoretically build new integrations (e.g. Xan could create a cron job that sends a daily summary to all agents via the switchboard).

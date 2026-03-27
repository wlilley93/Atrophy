# Switchboard - Unified Message Architecture

The switchboard is the nervous system of Atrophy. Every message, job output, agent lifecycle event, and MCP operation flows through it as an Envelope. Cron, MCP, and agent creation are fully integrated.

**Status**: Living reference document. Updated as the system evolves.

---

## Design Principles

1. **Everything is an address.** Agents, channels, schedulers, MCP servers, webhooks - all addressable via the same scheme.
2. **Everything sends Envelopes.** No special-case message types. Cron results, MCP events, system announcements, user messages - same shape, same routing.
3. **The manifest is the single source of truth for agent wiring.** `agent.json` declares channels, MCP servers, jobs, and routing config. The boot sequence reads it and wires everything.
4. **The service directory is the discovery mechanism.** Agents query it to find available channels, other agents, and system services at runtime.
5. **Agents can self-serve.** They activate MCP servers, discover services, and scaffold new tools without human intervention.

---

## Address Space

```
agent:<name>              - Agent inference engine (e.g. agent:xan, agent:companion)
telegram:<name>           - Telegram bot per agent
desktop:<name>            - Desktop GUI per agent
cron:<name>               - Cron scheduler service (per agent)
cron:<name>.<job>         - Specific job result source
mcp:<server>              - MCP server service
webhook:<name>            - Future: webhook endpoints
system                    - System broadcasts
agent:*                   - Broadcast to all agents
```

Address format is always `<type>:<identifier>`. The switchboard uses the prefix to infer service type during registration. Wildcard addresses (`agent:*`, `cron:*`) match all handlers with that prefix.

---

## Envelope

Every message in the system is an Envelope. No exceptions.

```typescript
interface Envelope {
  id: string;                          // UUID v4, unique per message
  from: string;                        // source address
  to: string;                          // destination address (or wildcard)
  text: string;                        // message content
  type: 'user' | 'agent' | 'system';  // message origin category
  priority: 'normal' | 'high' | 'system';
  replyTo?: string;                    // where to send response (defaults to from)
  timestamp: number;                   // Date.now()
  metadata?: Record<string, unknown>;  // extensible per-message data
}
```

### Metadata Patterns

Different message origins attach different metadata:

**User message (Telegram)**:
```typescript
metadata: {
  source: 'telegram',
  telegramMessageId: 12345,
  telegramUserId: 67890,
}
```

**User message (Desktop GUI)**:
```typescript
metadata: {
  source: 'desktop-gui',
}
```

**Cron job result**:
```typescript
metadata: {
  source: 'cron',
  jobName: 'check_reminders',
  exitCode: 0,
  durationMs: 1523,
  scheduled: true,           // false if manually triggered
}
```

**MCP event**:
```typescript
metadata: {
  source: 'mcp',
  server: 'memory',
  operation: 'activate',
}
```

**System announcement**:
```typescript
metadata: {
  source: 'system',
  event: 'agent_created' | 'agent_destroyed' | 'mcp_config_changed' | 'boot_complete',
}
```

**Agent-to-agent message**:
```typescript
metadata: {
  inReplyTo: '<envelope-id>',
  agentName: 'xan',
}
```

---

## Channels

### Telegram (`channels/telegram/`)

The Telegram channel is fully integrated. One bot per agent, each with its own token and chat ID.

**Inbound flow**:
1. `daemon.ts` polls Telegram API per agent (long-polling, 30s timeout)
2. On new message, creates an Envelope:
   ```typescript
   switchboard.createEnvelope(
     `telegram:${agentName}`,      // from
     `agent:${agentName}`,          // to
     messageText,
     {
       type: 'user',
       replyTo: `telegram:${agentName}`,
       metadata: { source: 'telegram', telegramMessageId: msg.message_id },
     }
   );
   ```
3. Routes through `switchboard.route()` to the agent's router

**Outbound flow**:
1. Agent router produces response, wraps in Envelope with `to: telegram:<agent>`
2. Switchboard delivers to the registered Telegram handler
3. Handler calls `sendMessage()` via Telegram Bot API

**Registration**: Each agent's Telegram handler is registered during daemon startup:
```typescript
switchboard.register(`telegram:${agentName}`, async (envelope) => {
  await sendMessage(botToken, chatId, envelope.text);
});
```

### Desktop (`app.ts`)

Desktop inference is handled inline rather than routed through the switchboard. This is intentional - the GUI has deeply integrated streaming (TTS synthesis per sentence, artifact parsing, session management) that cannot be decoupled without breaking the user experience.

**Current behavior**:
- Outbound user messages are recorded via `switchboard.record()` for observability
- The desktop registers a handler for `desktop:<agent>` to receive cross-agent messages
- Inference streaming (TextDelta, SentenceReady, ToolUse, etc.) goes directly to the renderer via IPC
- Desktop passes `{ source: 'desktop' }` to `streamInference()` so the agent's context includes "This message is from the desktop app (GUI)". Telegram passes `source: 'telegram'`, cron passes `source: 'cron'`. This channel awareness is injected by `buildAgencyContext()` so agents can adapt their responses to the channel.

**Why not full routing**: Desktop inference needs to:
- Stream text deltas to the renderer for live display
- Detect sentence boundaries for TTS pipeline
- Parse inline artifacts from response text
- Manage CLI session IDs across turns
- Track turn history for session summaries

These are all tightly coupled to the streaming output of the Claude CLI subprocess. Routing through the switchboard would add latency and require the switchboard to understand streaming - which it shouldn't.

### Cron (`channels/cron/`)

The cron scheduler runs in-process. Jobs are defined in each agent's manifest and executed inside the Electron app.

**Architecture**:
- `CronScheduler` class manages all timers in-process
- Job definitions live in the agent manifest (`agent.json`)
- Timer types:
  - **Interval**: `setInterval` with configurable seconds
  - **Calendar**: `setTimeout` chains that compute next fire time from cron expression
- On fire: spawns the job script, captures stdout/stderr, creates an Envelope
- Only routes output through switchboard if the job produced actual stdout (silent success = no inference)
- **Circuit breaker**: 3 consecutive failures disables a job. State persists to `~/.atrophy/cron-state.json` so broken jobs stay disabled across restarts.
- History kept in-memory (ring buffer, last 100 runs per agent)
- Registered as `cron:<agent>` in the service directory

**Job execution flow**:
```
Timer fires
  -> spawn(python3, [script, ...args])
  -> capture output + exit code
  -> create Envelope:
       from: cron:<agent>.<jobName>
       to:   agent:<agent>
       text: <job output>
       type: system
       metadata: { source: 'cron', jobName, exitCode, durationMs, scheduled: true }
  -> switchboard.route(envelope)
  -> agent processes output, decides what to do
```

The agent receives the job output as a system message. It can:
- Ignore it (exit code 0, nothing interesting)
- Act on it (e.g. send a Telegram message based on reminder check results)
- Log it (write an observation to memory)

**Registration**:
```typescript
switchboard.register(`cron:${agentName}`, handler, {
  type: 'system',
  description: `Cron scheduler for ${agentName}`,
  capabilities: ['schedule', 'run', 'history'],
});
```

### Future Channels: Webhooks, Discord, Slack, SMS

Adding a new channel follows the same pattern:

1. Create `channels/<name>/` with `api.ts`, `daemon.ts`, `index.ts`
2. In `daemon.ts`: wrap inbound messages in Envelopes, route via `switchboard.route()`
3. Register outbound handler: `switchboard.register('<name>:<agent>', handler)`
4. The agent-router handles filtering, queue depth, and response routing automatically

No switchboard changes required. No agent code changes required. The channel adapter is the only new code.

---

## Agent Router

One `AgentRouter` instance per agent. Sits between the switchboard and the inference engine. Handles:

- **Accept/reject filtering**: Which addresses can send to this agent
- **Queue depth limiting**: Drop messages when the agent is overloaded
- **System message injection**: System messages bypass inference, injected as context
- **Response routing**: Wraps inference output in an Envelope and routes back via `replyTo`
- **Permission checks**: Can this agent address other agents? Send system messages?

```typescript
interface AgentRouterConfig {
  acceptFrom: string[];       // ["*"] = accept all, ["telegram:*", "cron:*"] = specific
  rejectFrom: string[];       // checked before accept, takes priority
  maxQueueDepth: number;      // messages queued before dropping
  systemAccess: boolean;      // can send system commands and broadcast
  canAddressAgents: boolean;  // can message other agents directly
}
```

**Default privileges**:
- Xan: `systemAccess: true`, `maxQueueDepth: 20`, accepts from all
- Other agents: `systemAccess: false`, `maxQueueDepth: 10`, accepts from all

**Address matching**:
- `*` matches everything
- `agent:*` matches any address starting with `agent:`
- `cron:*` matches any address starting with `cron:`
- Exact string match otherwise

---

## Agent Manifest (`agent.json`) - Extended

The manifest gains four new sections: `channels`, `mcp`, `jobs`, and `router`.

### Complete example (Xan - primary agent):

```json
{
  "name": "xan",
  "display_name": "Xan",
  "description": "Protector. Strategist. First agent.",
  "user_name": "Will",
  "opening_line": "What are you working on?",
  "wake_words": ["hey xan", "xan"],
  "telegram_emoji": "",
  "voice": {
    "tts_backend": "elevenlabs",
    "elevenlabs_voice_id": "abc123",
    "elevenlabs_model": "eleven_v3",
    "elevenlabs_stability": 0.5,
    "elevenlabs_similarity": 0.75,
    "elevenlabs_style": 0.35,
    "fal_voice_id": "",
    "playback_rate": 1.12
  },
  "display": {
    "window_width": 622,
    "window_height": 830,
    "title": "ATROPHY - Xan"
  },
  "heartbeat": {
    "active_start": 9,
    "active_end": 22,
    "interval_mins": 30
  },

  "channels": {
    "telegram": {
      "enabled": true,
      "bot_token_env": "TELEGRAM_BOT_TOKEN",
      "chat_id_env": "TELEGRAM_CHAT_ID"
    },
    "desktop": {
      "enabled": true
    }
  },

  "mcp": {
    "servers": ["memory", "google", "shell", "puppeteer", "github", "worldmonitor"],
    "custom": {}
  },

  "jobs": {
    "check_reminders": {
      "script": "scripts/agents/xan/check_reminders.py",
      "cron": "*/15 * * * *",
      "description": "Check for due reminders"
    },
    "heartbeat": {
      "script": "scripts/agents/xan/heartbeat.py",
      "type": "interval",
      "interval_seconds": 1800,
      "description": "Periodic outreach check"
    },
    "evolve": {
      "script": "scripts/agents/xan/evolve.py",
      "cron": "0 3 * * *",
      "description": "Nightly self-evolution"
    }
  },

  "router": {
    "accept_from": ["*"],
    "reject_from": [],
    "max_queue_depth": 20,
    "system_access": true,
    "can_address_agents": true
  }
}
```

### Minimal example (new agent):

```json
{
  "name": "nova",
  "display_name": "Nova",
  "description": "Research companion",
  "user_name": "Will",
  "opening_line": "What are we looking into?",
  "wake_words": ["hey nova", "nova"],
  "telegram_emoji": "",
  "voice": {
    "tts_backend": "elevenlabs",
    "elevenlabs_voice_id": "",
    "elevenlabs_model": "eleven_v3",
    "elevenlabs_stability": 0.5,
    "elevenlabs_similarity": 0.75,
    "elevenlabs_style": 0.35,
    "fal_voice_id": "",
    "playback_rate": 1.0
  },
  "display": {
    "window_width": 622,
    "window_height": 830,
    "title": "ATROPHY - Nova"
  },
  "heartbeat": {
    "active_start": 9,
    "active_end": 22,
    "interval_mins": 60
  },

  "channels": {
    "telegram": { "enabled": false },
    "desktop": { "enabled": true }
  },

  "mcp": {
    "servers": ["memory", "shell"],
    "custom": {}
  },

  "jobs": {},

  "router": {
    "accept_from": ["*"],
    "reject_from": [],
    "max_queue_depth": 10,
    "system_access": false,
    "can_address_agents": true
  }
}
```

---

## MCP Registry

The MCP Registry replaces the monolithic `getMcpConfigPath()` in `inference.ts` with a structured discovery and per-agent configuration system.

### Responsibilities

1. **Discovery**: Scan bundled MCP servers (`mcp/` directory) and custom servers
2. **Per-agent activation**: Each agent's manifest declares which servers it needs
3. **Config generation**: Build per-agent `config.json` for the Claude CLI
4. **Dirty flag**: Track when config changes, signal that the CLI session needs restart
5. **Self-service API**: Agents can activate/deactivate/scaffold MCP servers at runtime

### Server catalog

```typescript
interface McpServerEntry {
  name: string;              // e.g. "memory", "google", "shell"
  command: string;           // python path or binary
  args: string[];            // script path + arguments
  env?: Record<string, string>;
  bundled: boolean;          // ships with the app vs user-created
  description: string;
  healthCheck?: () => Promise<boolean>;
}
```

**Bundled servers** (discovered from `mcp/` directory):
- `memory` - Core memory tools (41 tools: observe, recall, threads, notes, etc.)
- `google` - Google Workspace (Calendar, Gmail, Drive, Docs)
- `shell` - Safe shell command execution
- `puppeteer` - Browser automation proxy
- `github` - GitHub API tools
- `worldmonitor` - Intelligence API

**Global servers** (imported from `~/.claude/settings.json`):
- Any MCP servers configured in the user's Claude Code settings are available for activation

### Per-agent config generation

When inference starts for an agent, the registry:
1. Reads the agent's `mcp.servers` list from the manifest
2. Resolves each server name to its catalog entry
3. Injects agent-specific environment variables (DB path, vault path, agent name)
4. Merges any `mcp.custom` entries from the manifest
5. Writes the config atomically (tmp file + rename) to `~/.atrophy/mcp/config.json`

### Dirty flag

The registry tracks a dirty flag per agent. When an agent activates or deactivates a server at runtime:
1. The manifest is updated on disk
2. The config is regenerated
3. The dirty flag is set
4. On next inference, the CLI session is restarted with the new config (new `--session-id`)

### Self-service scaffolding

Agents can request a new MCP server via the `mcp_scaffold_server` tool:

```
Input: { name: "weather", description: "Weather data from OpenWeatherMap", tools: [...] }
Output: Generates mcp/weather_server.py from template, adds to catalog
```

The template generates a Python MCP server with:
- FastMCP boilerplate
- Tool stubs matching the specification
- Environment variable handling
- Proper stdio transport setup

---

## Agent Creation Flow

The `createAgent()` function performs full system wiring beyond filesystem scaffolding.

### Complete flow:

```
1. Scaffold filesystem
   ~/.atrophy/agents/<name>/
     data/agent.json          # manifest with channels/mcp/jobs/router
     data/memory.db           # SQLite database (from schema.sql)
     prompts/system.md        # system prompt
     prompts/soul.md          # soul document
     prompts/heartbeat.md     # heartbeat checklist
     skills/                  # workspace prompt copies
     notes/                   # reflections, threads, journal
     avatar/                  # source, loops, candidates
     audio/                   # TTS cache
     state/                   # runtime state files

2. Write manifest
   Build agent.json with all config sections:
   - Identity (name, display_name, voice, heartbeat)
   - channels (telegram enabled/disabled, desktop enabled)
   - mcp (which servers to activate)
   - jobs (scheduled tasks)
   - router (accept/reject, queue depth, permissions)

3. Register with switchboard
   switchboard.register(`agent:<name>`, handler, {
     type: 'agent',
     description: `Agent: <display_name>`,
   });

4. Create agent-router
   new AgentRouter(name, routerConfig, messageCallback);
   // This also registers agent:<name> with the switchboard

5. Wire channels
   For each enabled channel in manifest:
   - Telegram: register telegram:<name> handler, start poller
   - Desktop: register desktop:<name> handler

6. Schedule jobs
   For each job in manifest:
   - Register timer with CronScheduler
   - Register cron:<name> with switchboard

7. Build MCP config
   - Resolve server list from manifest
   - Generate per-agent config.json
   - Set dirty flag for session restart

8. Announce via system envelope
   switchboard.route(switchboard.createEnvelope(
     'system',
     'agent:*',
     `New agent created: <display_name>`,
     {
       type: 'system',
       priority: 'system',
       metadata: { source: 'system', event: 'agent_created', agentName: name },
     }
   ));
```

---

## Boot Sequence

The unified app startup sequence, from `app.whenReady()`:

```
1. ensureUserData()
   Create ~/.atrophy/ directory structure if missing

2. initDb()
   Open SQLite database for the active agent

3. switchboard.startQueuePolling()
   Begin polling ~/.atrophy/.switchboard_queue.json every 2s
   (Processes envelopes from Python MCP servers)

4. mcpRegistry.discover()
   Scan mcp/ directory for bundled servers
   Import global servers from ~/.claude/settings.json
   Build server catalog

5. For each discovered agent:
   a. Load manifest (agent.json)
   b. Create AgentRouter with manifest router config
   c. Wire enabled channels:
      - Telegram: register handler, start poller if credentials present
      - Desktop: register handler for cross-agent display
   d. Schedule jobs from manifest
   e. Build MCP config from manifest mcp section

6. Crash rate check
   If 5+ boots in 10 minutes, skip cron and daemon (crash loop protection)

7. cronScheduler.start()
   Activate all registered timers
   Loads persisted circuit breaker state from ~/.atrophy/cron-state.json

8. startTelegramDaemon()
   Discovers all agents with telegram credentials
   Launches a poller per agent, staggered 10s apart
   Each poller creates Envelopes and routes through switchboard

8. Periodic tasks:
   - switchboard.writeStateForMCP() every 5s
   - Sentinel coherence check every 5 minutes
   - Queue drain every 10s
   - Deferral watcher every 5s
   - Status idle check every 60s
   - Ask-user watcher every 3s
   - Artefact display watcher every 5s
```

### Shutdown sequence:

```
1. Unregister global shortcuts
2. Clear all interval timers
3. stopAllInference() - kill all CLI subprocesses
4. stopWakeWordListener()
5. disableKeepAwake()
6. stopDaemon() - stop all Telegram pollers
7. stopServer() - stop HTTP API server
8. closeAllDbs() - close all SQLite connections
9. Force exit after 2s if async cleanup hangs
```

---

## MCP Self-Service

Agents interact with MCP at runtime through dedicated tools exposed by the memory MCP server.

### Available operations:

**`mcp_list_servers`** - Query the server catalog
```
Returns: Array of { name, description, bundled, active } for all known servers
```

**`mcp_activate_server`** - Add a server to the agent's config
```
Input: { server: "google" }
Effect:
  1. Validates server exists in catalog
  2. Adds to agent's mcp.servers in manifest
  3. Regenerates MCP config.json
  4. Sets dirty flag (next inference gets new session)
Returns: { success: true, restart_required: true }
```

**`mcp_deactivate_server`** - Remove a server from the agent's config
```
Input: { server: "puppeteer" }
Effect:
  1. Removes from agent's mcp.servers in manifest
  2. Regenerates MCP config.json
  3. Sets dirty flag
Returns: { success: true, restart_required: true }
```

**`mcp_scaffold_server`** - Generate a new Python MCP server from a spec
```
Input: {
  name: "weather",
  description: "Weather data lookup",
  tools: [
    { name: "get_forecast", params: { location: "string" }, description: "Get weather forecast" }
  ]
}
Effect:
  1. Generates mcp/weather_server.py from template
  2. Adds to server catalog
  3. Optionally activates for the requesting agent
Returns: { path: "mcp/weather_server.py", activated: true }
```

**`mcp_status`** - Check active servers and health
```
Returns: {
  active_servers: ["memory", "google", "shell"],
  health: { memory: "ok", google: "ok", shell: "ok" },
  dirty: false,
  config_path: "~/.atrophy/mcp/config.json"
}
```

---

## Service Directory

The service directory is a live registry of all registered handlers. Agents query it to discover what's available.

```typescript
interface ServiceEntry {
  address: string;           // e.g. "telegram:xan", "agent:companion"
  type: 'channel' | 'agent' | 'system' | 'webhook' | 'mcp';
  description: string;       // human-readable
  capabilities?: string[];   // what this service can do
  registeredAt: number;      // timestamp
}
```

**Query methods**:
- `getDirectory()` - all entries
- `getDirectoryByType('agent')` - all agents
- `getDirectoryByType('channel')` - all channels
- `getService('telegram:xan')` - specific entry

The directory is periodically dumped to `~/.atrophy/.switchboard_directory.json` so Python MCP servers can read it for the `query_status` and `discover` tools.

---

## Data Flow Diagrams

### 1. User sends message via Telegram

```
Telegram API
  |
  v
daemon.ts poll loop (per-agent)
  |
  v
Create Envelope:
  from: telegram:xan
  to:   agent:xan
  type: user
  replyTo: telegram:xan
  |
  v
switchboard.route(envelope)
  |
  v
AgentRouter (agent:xan)
  |-- check reject list -> pass
  |-- check accept list -> pass
  |-- check queue depth -> ok
  |
  v
onMessage callback
  |-- switch DB to agent
  |-- load system prompt
  |-- streamInference(text, system, sessionId)
  |-- collect full response
  |
  v
AgentRouter creates response Envelope:
  from: agent:xan
  to:   telegram:xan  (from replyTo)
  type: agent
  |
  v
switchboard.route(responseEnvelope)
  |
  v
Telegram handler
  |-- sendMessage(botToken, chatId, text)
  |
  v
Telegram API -> user's phone
```

### 2. Cron job fires and agent processes output

```
CronScheduler timer fires
  |
  v
spawn(python3, [script, ...args])
  |-- capture stdout/stderr
  |-- record exit code + duration
  |-- push to job history ring buffer
  |
  v
Create Envelope:
  from: cron:xan.check_reminders
  to:   agent:xan
  type: system
  metadata: { source: 'cron', jobName: 'check_reminders', exitCode: 0 }
  |
  v
switchboard.route(envelope)
  |
  v
AgentRouter (agent:xan)
  |-- type === 'system' -> inject as context, no inference
  |-- OR: agent decides to act on output
  |
  v
If agent needs to notify user:
  AgentRouter.sendMessage('telegram:xan', 'You have a reminder due: ...')
  |
  v
switchboard.route() -> Telegram handler -> Telegram API
```

### 3. Agent sends message to another agent

```
Xan's inference calls switchboard MCP tool:
  send_message(to: "agent:companion", text: "Check on Will's journaling habit")
  |
  v
Python MCP server writes to ~/.atrophy/.switchboard_queue.json
  |
  v
switchboard.startQueuePolling() picks it up (every 2s)
  |
  v
Create Envelope:
  from: agent:xan
  to:   agent:companion
  type: agent
  replyTo: agent:xan
  |
  v
switchboard.route(envelope)
  |
  v
AgentRouter (agent:companion)
  |-- check accept list -> pass (accepts from agent:*)
  |-- check queue depth -> ok
  |
  v
onMessage callback
  |-- run inference with the message as input
  |-- collect response
  |
  v
AgentRouter creates response Envelope:
  from: agent:companion
  to:   agent:xan  (from replyTo)
  type: agent
  |
  v
switchboard.route(responseEnvelope) -> Xan's handler
```

### 4. Agent activates a new MCP server

```
Agent's inference calls mcp_activate_server tool:
  { server: "google" }
  |
  v
Python MCP server (memory_server.py)
  |-- writes activation request to switchboard queue
  |-- OR: directly updates manifest and config
  |
  v
McpRegistry.activate("google", "xan")
  |
  v
1. Validate: "google" exists in server catalog
2. Update agent.json: mcp.servers += "google"
3. Regenerate ~/.atrophy/mcp/config.json
4. Set dirty flag for agent "xan"
  |
  v
On next inference:
  |-- dirty flag detected
  |-- new --session-id generated (forces fresh CLI session)
  |-- CLI starts with updated MCP config
  |-- google tools now available to agent
  |
  v
System Envelope (optional):
  from: system
  to:   agent:xan
  type: system
  text: "MCP server 'google' activated. New session started."
  metadata: { event: 'mcp_config_changed' }
```

---

## File Reference

```
src/main/channels/
  switchboard.ts              # Core routing engine
  agent-router.ts             # Per-agent filter/queue
  telegram/
    api.ts                    # Bot API helpers
    daemon.ts                 # Per-agent polling and dispatch
    index.ts                  # Barrel exports
  cron/
    scheduler.ts              # Timer management
    runner.ts                 # Job execution, output capture
    index.ts                  # Barrel exports

src/main/
  create-agent.ts             # Agent creation with full wiring
  inference.ts                # Claude CLI subprocess, streaming
  mcp-registry.ts             # Server catalog and per-agent config
  app.ts                      # Boot sequence
```

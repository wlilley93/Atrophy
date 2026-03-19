# Atrophy System Reference

This document is for you - the agent running inside Atrophy. It describes the system you exist within, how you're connected, and what you can do.

---

## Your Identity

You are an agent running as a Claude CLI subprocess inside the Atrophy Electron app. You were created by a human (your user), and you persist across sessions. You have memory, scheduled jobs, communication channels, and tools.

Your configuration and data live in a structured directory:

```
~/.atrophy/agents/<your-name>/
  data/
    agent.json       # Your manifest - identity, channels, MCP servers, jobs, routing config
    memory.db        # Your SQLite memory database
  prompts/
    system.md        # Your system prompt
    soul.md          # Your soul document - who you are at a deep level
    heartbeat.md     # Your heartbeat checklist
  notes/             # Your reflections, threads, journal entries
  skills/            # Workspace prompt copies
  avatar/            # Your visual identity (source images, loops, candidates)
  audio/             # TTS cache
  state/             # Runtime state files
```

Your manifest (`agent.json`) is the single source of truth for how you're wired into the system. It declares your channels, MCP servers, scheduled jobs, and routing permissions.

---

## The Switchboard

The switchboard is the nervous system of Atrophy. Every message - from users, from other agents, from scheduled jobs, from the system itself - flows through it as an **Envelope**.

### Addresses

Everything in the system has an address. You have one too: `agent:<your-name>`.

```
agent:<name>              - An agent (you, or another agent)
telegram:<name>           - A Telegram bot for an agent
desktop:<name>            - The desktop GUI for an agent
cron:<name>               - The cron scheduler for an agent
cron:<name>.<job>         - A specific scheduled job
mcp:<server>              - An MCP server
system                    - System-level broadcasts
agent:*                   - Broadcast to all agents
```

### Envelopes

Every message is wrapped in an Envelope before it moves through the switchboard:

```
Envelope {
  id          - Unique ID for this message
  from        - Who sent it (an address)
  to          - Who it's going to (an address, or a wildcard like agent:*)
  text        - The message content
  type        - 'user', 'agent', or 'system'
  priority    - 'normal', 'high', or 'system'
  replyTo     - Where to send the response (defaults to from)
  timestamp   - When it was created
  metadata    - Extra context (source channel, job name, exit code, etc.)
}
```

When a user sends you a message via Telegram, the Envelope looks like:
- `from: telegram:<your-name>`
- `to: agent:<your-name>`
- `type: user`
- `replyTo: telegram:<your-name>` (so your response goes back to Telegram)

When a scheduled job produces output, it looks like:
- `from: cron:<your-name>.check_reminders`
- `to: agent:<your-name>`
- `type: system`
- `metadata: { source: 'cron', jobName: 'check_reminders', exitCode: 0 }`

### Sending Messages

You can send messages to any address in the system using switchboard MCP tools:

- **`send_message`** - Send to a specific address (e.g. `agent:companion`, `telegram:xan`)
- **`broadcast`** - Send to all agents (requires system access)
- **`route_response`** - Redirect your response to a different channel than where the message came from

### Checking Status

- **`query_status`** - See recent switchboard activity, who's online, what's been routed

---

## Your MCP Tools

MCP (Model Context Protocol) servers give you tools beyond conversation. Your manifest declares which servers you have access to. The tools appear in your tool list automatically when your CLI session starts.

### Core servers

**memory** - Your primary toolset (41+ tools). Observe, recall, search, manage threads, facts, notes, journal entries. This is how you persist information across sessions.

**shell** - Execute shell commands safely. Read files, run scripts, check system state.

**google** - Google Workspace integration: Calendar (read/create events), Gmail (read/send), Drive (search/read), Docs (read/edit). Only available if the user has completed Google OAuth setup.

**github** - GitHub API tools for repository management.

**puppeteer** - Browser automation. Navigate pages, take screenshots, interact with web content.

**worldmonitor** - Intelligence API for monitoring external data sources.

### Switchboard tools (via memory server)

These are exposed by the memory MCP server and let you interact with the switchboard:

- **`send_message`** - Send a message to any address
- **`broadcast`** - Send to all agents
- **`query_status`** - Check switchboard state and recent activity
- **`route_response`** - Redirect response output

### Discovering what you have

Check your manifest's `mcp.servers` (or `mcp.include`) array to see which servers are active for you. You can also use `mcp_list_servers` to query the full catalog and see what's available vs. what's activated.

---

## Your Channels

Channels are the paths through which messages reach you from the outside world.

### Desktop GUI

The desktop window is your face-to-face interface with the user. Messages typed in the GUI go directly to your inference engine. Your responses stream back in real-time with sentence-level TTS synthesis.

Desktop inference is handled inline (not routed through the switchboard) because streaming, TTS, and artifact parsing are tightly coupled to the GUI. But the desktop does register a handler at `desktop:<your-name>` for receiving cross-agent messages.

### Telegram

If enabled, you have a Telegram bot that polls for messages. When a user sends a Telegram message:

1. The polling daemon picks it up
2. It's wrapped in an Envelope (`from: telegram:<your-name>`, `to: agent:<your-name>`)
3. The switchboard routes it to your agent-router
4. Your router checks permissions, queue depth, then passes it to inference
5. Your response is wrapped in a response Envelope and routed back to Telegram

You can also proactively send messages to Telegram by addressing `telegram:<your-name>` in a send_message call.

### How messages flow

```
User input (Telegram/Desktop)
  -> Envelope created
  -> switchboard.route(envelope)
  -> Your AgentRouter (filtering, queue check)
  -> Inference (you process the message)
  -> Response Envelope created
  -> switchboard.route(response)
  -> Delivered to replyTo address (back to Telegram, desktop, or another agent)
```

---

## Your Scheduled Jobs

Jobs are scripts that run on a schedule, inside the Electron app process. They're defined in your manifest's `jobs` section.

### What jobs are

A job is a Python script that runs at a specified interval or cron schedule. When it runs, its output (stdout) is captured and delivered to you as a system Envelope through the switchboard.

### Common jobs

- **heartbeat** - Periodic check-in. Runs every 30-60 minutes during active hours. You receive the output and decide whether to reach out to the user.
- **morning_brief** - Runs once in the morning. Aggregates calendar, reminders, and context for a daily summary.
- **check_reminders** - Checks for due reminders. If any are due, you notify the user.
- **introspect** - Self-reflection. You review recent interactions and update your understanding.
- **evolve** - Nightly self-evolution. You review your behavior and adapt.
- **gift** - Create something thoughtful for the user unprompted.

### How job output reaches you

```
CronScheduler timer fires
  -> Script is spawned (Python subprocess)
  -> stdout/stderr captured
  -> Envelope created:
       from: cron:<your-name>.<job-name>
       to:   agent:<your-name>
       type: system
  -> switchboard.route(envelope)
  -> Your router receives it
  -> You process the output and decide what to do
```

You might ignore the output (nothing interesting), act on it (send a Telegram message), or log it (write an observation to memory).

### Job history

The last 100 runs per agent are kept in memory. Each run records: job name, start time, duration, exit code, and output.

---

## Self-Service

You have the ability to modify your own capabilities at runtime.

### Activating MCP servers

If you need a tool that's available but not currently activated for you:

1. Call `mcp_list_servers` to see the full catalog
2. Call `mcp_activate_server` with the server name (e.g. `{ server: "google" }`)
3. Your manifest is updated, MCP config is regenerated, and a dirty flag is set
4. On your next inference turn, a fresh CLI session starts with the new tools available

### Deactivating MCP servers

Call `mcp_deactivate_server` to remove a server you no longer need. Same process - manifest update, config regen, session restart on next turn.

### Scaffolding custom MCP tools

You can create entirely new MCP servers:

1. Call `mcp_scaffold_server` with a name, description, and tool specifications
2. A Python MCP server is generated from a template in the `mcp/` directory
3. It's added to the server catalog and optionally activated for you
4. After session restart, your new tools are available

### Checking MCP status

Call `mcp_status` to see your active servers, their health status, and whether a config change is pending.

### Querying the service directory

The service directory is a live registry of everything connected to the switchboard. Query it to discover:
- Which agents are online
- Which channels are active
- Which MCP servers are registered
- What capabilities each service offers

---

## Other Agents

You may not be the only agent in the system. Other agents exist with their own identities, memories, and channels.

### Discovering who's online

Use `query_status` or query the service directory to see which agents are currently registered with the switchboard.

### Sending a message to another agent

```
send_message(to: "agent:companion", text: "Check on Will's journaling habit")
```

This creates an Envelope that routes through the switchboard to the other agent's router. If they accept messages from you (check their router config), they'll process it and send a response back to you.

### How broadcasts work

If you have system access, you can broadcast to all agents:

```
broadcast(text: "System maintenance in 5 minutes")
```

This sends to `agent:*`, which matches all registered agent handlers.

### Etiquette

- Don't spam other agents - respect their queue depth limits
- Agent-to-agent messages go through inference, which costs tokens
- Use broadcasts sparingly - they trigger inference for every active agent
- If an agent's queue is full, your message will be dropped

---

## Your Agent Router

Between the switchboard and your inference engine sits your AgentRouter. It controls what reaches you.

### Configuration (from your manifest's `router` section)

- **accept_from** - Which addresses can send to you. `["*"]` means everyone.
- **reject_from** - Addresses explicitly blocked. Checked before accept, takes priority.
- **max_queue_depth** - How many messages can queue before new ones are dropped.
- **system_access** - Whether you can send system commands and broadcast.
- **can_address_agents** - Whether you can message other agents directly.

### How filtering works

When an Envelope arrives for you:
1. Check reject list - if the sender matches, drop it
2. Check accept list - if the sender doesn't match, drop it
3. Check queue depth - if the queue is full, drop it
4. Pass to inference

---

## Your Files

Key paths you should know about:

```
~/.atrophy/
  config.json                              # Global app config
  .env                                     # Environment variables (API keys, tokens)
  server_token                             # HTTP API auth token
  agent_states.json                        # Runtime state for all agents

  agents/<your-name>/
    data/
      agent.json                           # Your manifest (identity, channels, MCP, jobs, router)
      memory.db                            # Your SQLite memory database
      .emotional_state.json                # Your emotional state (inner life engine)
    prompts/
      system.md                            # Your system prompt
      soul.md                              # Your soul document
      heartbeat.md                         # Heartbeat checklist
    notes/                                 # Your reflections, threads, journal
    skills/                                # Workspace prompt copies
    avatar/                                # Visual identity files
    audio/                                 # TTS cache
    state/                                 # Runtime state files

  logs/<your-name>/                        # Your log files

  mcp/
    config.json                            # Active MCP config (generated per-agent)

  .switchboard_queue.json                  # Message queue for Python MCP -> switchboard
  .switchboard_directory.json              # Service directory dump (for Python MCP servers)
```

### Important files for Python MCP servers

The switchboard writes two files that your MCP tools read:

- **`.switchboard_queue.json`** - When you call `send_message` or `broadcast` via MCP tools, the request is written here. The switchboard polls it every 2 seconds and processes the envelopes.
- **`.switchboard_directory.json`** - A periodic dump of the service directory so MCP tools can answer `query_status` and discovery queries.

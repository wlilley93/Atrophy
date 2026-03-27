# src/main/channels/telegram/daemon.ts - Telegram Polling Daemon

**Dependencies:** `fs`, `os`, `path`, `child_process`, `electron`, `../../config`, `../../status`, `./api`, `./formatter`, `../../agent-manager`, `../../inference`, `../../context`, `../../jobs/generate-avatar`, `../../memory`, `../../logger`, `../switchboard`, `../agent-router`, `../../session`  
**Purpose:** Parallel per-agent Telegram pollers with session management

## Overview

This module implements the Telegram daemon that polls for incoming messages from multiple agents, each with their own bot (token + chat ID). Messages flow through the central switchboard for routing to agent-specific inference.

**Architecture:**
```
Telegram poll → Envelope → switchboard → agent router → inference
Response → Envelope → switchboard → telegram handler → Telegram API
```

**Modes:**
- Continuous loop (KeepAlive daemon)
- Managed from Electron main process

## Per-Agent Session Management

```typescript
const _agentSessions: Map<string, Session> = new Map();
const _agentLastActivity: Map<string, number> = new Map();

const SESSION_IDLE_THRESHOLD_MS = 30 * 60 * 1000; // 30 minutes

function getAgentSession(agentName: string): Session {
  let session = _agentSessions.get(agentName);
  const now = Date.now();

  if (session) {
    const lastActivity = _agentLastActivity.get(agentName) || 0;
    const gap = now - lastActivity;

    if (gap > SESSION_IDLE_THRESHOLD_MS && session.turnHistory.length > 0) {
      // Session idle - rotate it
      const oldSession = session;
      const oldCliId = oldSession.cliSessionId;
      const system = loadSystemPrompt();
      oldSession.end(system).catch((err) => {
        log.error(`[${agentName}] failed to end idle session: ${err}`);
      });

      // Start fresh session, carry over CLI session ID
      session = new Session();
      session.start();
      if (oldCliId) {
        session.cliSessionId = oldCliId;
      }
      _agentSessions.set(agentName, session);
      log.info(`[${agentName}] rotated idle session (gap: ${Math.round(gap / 60000)}m)`);
    }
  }

  if (!session) {
    session = new Session();
    session.start();
    _agentSessions.set(agentName, session);
  }

  _agentLastActivity.set(agentName, now);
  return session;
}
```

**Features:**
- Per-agent session persistence
- Idle rotation after 30 minutes (generates summary)
- CLI session ID carries over across rotations

**Important:** Caller must call `config.reloadForAgent()` and `memory.initDb()` before `getAgentSession()` to ensure correct agent DB.

## Agent Routers

```typescript
const _agentRouters: Map<string, AgentRouter> = new Map();
```

**Purpose:** One router per agent for message filtering and queue depth limits.

## Main Window Accessor

```typescript
let _getMainWindow: (() => BrowserWindow | null) | null = null;

export function setMainWindowAccessor(fn: () => BrowserWindow | null): void {
  _getMainWindow = fn;
}
```

**Purpose:** Set during boot for UI notifications.

## State Persistence

### Daemon State

```typescript
interface AgentPollerState {
  last_update_id: number;
  last_dispatched_id: number;
}

interface DaemonState {
  agents: Record<string, AgentPollerState>;
}

const STATE_FILE = path.join(USER_DATA, '.telegram_daemon_state.json');

function loadState(): DaemonState {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const raw = JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));
      // Migrate from old format
      if (raw.agents && typeof raw.agents === 'object') {
        return { agents: raw.agents };
      }
      return { agents: {} };
    }
  } catch { /* default */ }
  return { agents: {} };
}

function saveState(state: DaemonState): void {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2) + '\n');
}
```

**Purpose:** Persist update IDs across restarts to avoid re-processing old messages.

## Instance Locking

### acquireLock

```typescript
const LOCK_FILE = path.join(USER_DATA, '.telegram_daemon.lock');
let _lockFd: number | null = null;

export function acquireLock(): boolean {
  fs.mkdirSync(path.dirname(LOCK_FILE), { recursive: true });

  // macOS O_EXLOCK for exclusive lock
  const O_EXLOCK = 0x20;
  const O_NONBLOCK = 0x4000;

  try {
    _lockFd = fs.openSync(
      LOCK_FILE,
      fs.constants.O_WRONLY | fs.constants.O_CREAT | O_EXLOCK | O_NONBLOCK,
      0o644,
    );
  } catch (err: unknown) {
    // EAGAIN/EWOULDBLOCK means another process holds lock
    const code = (err as NodeJS.ErrnoException).code;
    if (code === 'EAGAIN' || code === 'EWOULDBLOCK') {
      return false;
    }
    // Fallback: check PID file
    const pidFile = LOCK_FILE + '.pid';
    try {
      const existingPid = parseInt(fs.readFileSync(pidFile, 'utf-8'), 10);
      if (existingPid && process.pid !== existingPid) {
        try {
          process.kill(existingPid, 0);
          return false;  // Process still running
        } catch {
          // Process dead, remove stale lock
          fs.unlinkSync(pidFile);
        }
      }
    } catch { /* no PID file */ }

    // Take the lock
    fs.writeFileSync(pidFile, String(process.pid));
    return true;
  }

  return true;
}
```

**Purpose:** Prevent multiple daemon instances from running simultaneously.

**Mechanism:**
1. macOS: `O_EXLOCK` for exclusive file lock
2. Fallback: PID file check

### releaseLock

```typescript
export function releaseLock(): void {
  if (_lockFd !== null) {
    try {
      fs.closeSync(_lockFd);
    } catch { /* ignore */ }
    _lockFd = null;
  }

  // Clean up PID file
  const pidFile = LOCK_FILE + '.pid';
  try {
    fs.unlinkSync(pidFile);
  } catch { /* ignore */ }
}
```

## Agent Discovery

### discoverTelegramAgents

```typescript
async function discoverTelegramAgents(): Promise<TelegramAgent[]> {
  const agents: TelegramAgent[] = [];
  const seen = new Set<string>();

  for (const base of [USER_DATA, BUNDLE_ROOT]) {
    const agentsDir = path.join(base, 'agents');
    if (!fs.existsSync(agentsDir)) continue;

    for (const name of fs.readdirSync(agentsDir)) {
      if (seen.has(name)) continue;
      seen.add(name);

      const manifestPath = path.join(agentsDir, name, 'data', 'agent.json');
      if (!fs.existsSync(manifestPath)) continue;

      try {
        const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
        const channels = (manifest.channels as Record<string, Record<string, string>>) || {};
        const tg = channels.telegram || {};

        // Resolve credentials from env
        let botToken = '';
        let chatId = '';
        if (tg.bot_token_env) {
          botToken = process.env[tg.bot_token_env] || '';
        }
        if (tg.chat_id_env) {
          chatId = process.env[tg.chat_id_env] || '';
        }

        if (botToken && chatId) {
          agents.push({
            name,
            display_name: (manifest.display_name as string) || name,
            emoji: (manifest.telegram_emoji as string) || '',
            botToken,
            chatId,
          });
        }
      } catch { /* skip */ }
    }
  }

  return agents;
}
```

**Purpose:** Find all agents with Telegram credentials configured.

**Credential resolution:**
1. Check `channels.telegram.bot_token_env` → env var
2. Check `channels.telegram.chat_id_env` → env var

## Message Polling

### pollAgent

```typescript
async function pollAgent(agent: TelegramAgent): Promise<void> {
  const state = loadState();
  const agentState = state.agents[agent.name] || { last_update_id: 0, last_dispatched_id: 0 };

  const allowedUpdates = ['message', 'my_chat_member'];
  const payload: Record<string, unknown> = {
    offset: agentState.last_update_id + 1,
    timeout: 30,
    allowed_updates: allowedUpdates,
  };

  const result = await post('getUpdates', payload, 40_000, agent.botToken) as Array<Record<string, unknown>> | null;
  if (!result || result.length === 0) return;

  for (const update of result) {
    const updateId = update.update_id as number;

    // Check for membership change
    const memberChange = update.my_chat_member as Record<string, unknown> | undefined;
    if (memberChange) {
      await handleMembershipChange(agent, memberChange);
      agentState.last_update_id = updateId;
      saveState(state);
      continue;
    }

    // Process message
    const message = update.message as Record<string, unknown> | undefined;
    if (!message) continue;

    const from = message.from as Record<string, unknown> | undefined;
    const text = message.text as string | undefined;
    const chatId = message.chat?.id as number | undefined;

    // Verify chat ID matches configured
    if (String(chatId) !== agent.chatId) continue;

    // Dispatch to agent router
    if (text && from) {
      await dispatchToAgent(agent, text, String(chatId), agent.botToken);
    }

    agentState.last_update_id = updateId;
    saveState(state);
  }
}
```

**Purpose:** Poll for updates for a single agent.

**Update types:**
- `message` - Regular messages
- `my_chat_member` - Bot membership changes (added/removed from groups)

## Message Dispatch

### dispatchToAgent

```typescript
async function dispatchToAgent(
  agent: TelegramAgent,
  text: string,
  chatId: string,
  botToken: string,
): Promise<void> {
  const config = getConfig();

  // Reload config for this agent
  config.reloadForAgent(agent.name);
  initDb();
  resetMcpConfig();

  // Get or create session
  const session = getAgentSession(agent.name);

  // Get or create router
  let router = _agentRouters.get(agent.name);
  if (!router) {
    const routerConfig = defaultConfigForAgent(agent.name);
    router = new AgentRouter(agent.name, routerConfig, async (envelope) => {
      // Record user turn
      session.addTurn('will', envelope.text);

      // Run inference
      const systemPrompt = loadSystemPrompt();
      const emitter = streamInference(envelope.text, systemPrompt, session.cliSessionId);

      let fullText = '';
      let messageId: number | null = null;
      const streamState: StreamState = {
        thinkingText: '',
        activeTool: null,
        pendingTools: new Map(),
        completedTools: [],
        responseText: '',
        isCompacting: false,
        startTime: Date.now(),
      };

      for await (const evt of emitter) {
        switch (evt.type) {
          case 'ThinkingDelta':
            streamState.thinkingText = evt.text;
            break;

          case 'ToolUse':
            streamState.activeTool = {
              name: evt.name,
              id: evt.toolId,
              input: '',
              result: '',
            };
            break;

          case 'ToolInputDelta':
            if (streamState.activeTool) {
              streamState.activeTool.input += evt.delta;
            }
            break;

          case 'ToolResult':
            if (streamState.activeTool) {
              streamState.activeTool.result = evt.output;
              streamState.completedTools.push(streamState.activeTool);
              streamState.activeTool = null;
            }
            break;

          case 'Compacting':
            streamState.isCompacting = true;
            break;

          case 'TextDelta':
            streamState.responseText += evt.text;
            break;

          case 'StreamDone':
            fullText = evt.fullText;
            if (evt.sessionId) {
              session.cliSessionId = evt.sessionId;
            }
            break;
        }

        // Update Telegram message periodically
        if (messageId) {
          const statusText = buildStatusDisplay(streamState);
          await editMessage(messageId, statusText, chatId, botToken);
        }
      }

      // Record agent turn
      session.addTurn('agent', fullText);

      return fullText;
    });

    _agentRouters.set(agent.name, router);
  }

  // Create envelope and route through switchboard
  const envelope = switchboard.createEnvelope(
    `telegram:${agent.name}`,
    `agent:${agent.name}`,
    text,
    {
      type: 'user',
      priority: 'normal',
      replyTo: `telegram:${agent.name}`,
    },
  );

  await switchboard.route(envelope);
}
```

**Purpose:** Dispatch message to agent's inference engine.

**Flow:**
1. Reload config for agent
2. Get/create session
3. Get/create router
4. Create envelope
5. Route through switchboard
6. Stream inference with Telegram status updates

## Membership Change Handling

### handleMembershipChange

```typescript
async function handleMembershipChange(
  agent: TelegramAgent,
  memberChange: Record<string, unknown>,
): Promise<void> {
  const chat = memberChange.chat as Record<string, unknown> | undefined;
  const newMember = memberChange.new_chat_member as Record<string, unknown> | undefined;
  const oldMember = memberChange.old_chat_member as Record<string, unknown> | undefined;

  if (!chat || !newMember || !oldMember) return;

  const chatType = chat.type as string;
  const newStatus = newMember.status as string;
  const oldStatus = oldMember.status as string;

  // Only handle group/supergroup changes
  if (chatType !== 'group' && chatType !== 'supergroup') return;

  const chatId = String(chat.id);
  const chatTitle = (chat.title as string) || 'the group';

  // Added to group
  if ((newStatus === 'member' || newStatus === 'administrator') &&
      oldStatus !== 'member' && oldStatus !== 'administrator') {
    // Save DM chat ID if not already set
    const manifest = loadAgentManifest(agent.name);
    const channels = (manifest.channels as Record<string, Record<string, string>>) || {};
    const tg = channels.telegram || {};

    if (!tg.chat_id_env) {
      // First group - save current chat as DM fallback
      saveAgentConfig(agent.name, {
        channels: {
          telegram: {
            bot_token_env: tg.bot_token_env,
            chat_id_env: `TELEGRAM_CHAT_ID_${agent.name.toUpperCase()}`,
          },
        },
      });
      // Set env var for current session
      process.env[`TELEGRAM_CHAT_ID_${agent.name.toUpperCase()}`] = agent.chatId;
    }

    // Update active chat ID to group
    saveAgentConfig(agent.name, {
      TELEGRAM_CHAT_ID: chatId,
    });

    // Send greeting
    const greeting = `${agent.emoji} *${agent.display_name}* is now active in this group.`;
    await sendMessage(greeting, chatId, false, agent.botToken);

    log.info(`[${agent.name}] Added to group: ${chatTitle}`);
  }

  // Removed from group
  if (newStatus === 'left' || newStatus === 'kicked') {
    // Revert to DM chat ID
    const manifest = loadAgentManifest(agent.name);
    const channels = (manifest.channels as Record<string, Record<string, string>>) || {};
    const tg = channels.telegram || {};

    let dmChatId = '';
    if (tg.chat_id_env) {
      dmChatId = process.env[tg.chat_id_env] || '';
    }

    if (dmChatId) {
      saveAgentConfig(agent.name, { TELEGRAM_CHAT_ID: dmChatId });

      // Send revert notification to DM
      const notification = `I've been removed from ${chatTitle}. Back to this chat.`;
      await sendMessage(notification, dmChatId, true, agent.botToken);

      log.info(`[${agent.name}] Removed from group: ${chatTitle}, reverted to DM`);
    } else {
      log.warn(`[${agent.name}] Removed from group but no DM chat ID configured`);
    }
  }
}
```

**Purpose:** Handle bot being added to/removed from Telegram groups.

**Transitions:**
- **Added:** Save DM as fallback, update to group chat, send greeting
- **Removed:** Revert to DM chat, send notification

## Main Loop

### startDaemon

```typescript
export async function startDaemon(): Promise<void> {
  if (!acquireLock()) {
    log.info('Telegram daemon already running (lock held)');
    return;
  }

  try {
    const agents = await discoverTelegramAgents();
    log.info(`Starting Telegram daemon for ${agents.length} agent(s)`);

    // Set main window accessor for UI notifications
    setMainWindowAccessor(() => _getMainWindow?.());

    // Start pollers with staggered starts (10s apart)
    for (let i = 0; i < agents.length; i++) {
      const agent = agents[i];
      setTimeout(() => {
        runAgentPoller(agent);
      }, i * 10_000);
    }
  } catch (err) {
    log.error(`Telegram daemon failed: ${err}`);
    releaseLock();
  }
}
```

**Purpose:** Start daemon with exclusive lock.

### runAgentPoller

```typescript
async function runAgentPoller(agent: TelegramAgent): Promise<void> {
  log.info(`[${agent.name}] Starting poller`);

  while (true) {
    try {
      // Random jitter (8-15s) for organic feel
      const jitter = 8000 + Math.random() * 7000;
      await new Promise((r) => setTimeout(r, jitter));

      await pollAgent(agent);
    } catch (err) {
      log.error(`[${agent.name}] Poller error: ${err}`);
      await new Promise((r) => setTimeout(r, 5000));
    }
  }
}
```

**Purpose:** Continuous polling loop with random jitter.

### stopDaemon

```typescript
export function stopDaemon(): void {
  log.info('Stopping Telegram daemon');
  releaseLock();
}
```

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/.telegram_daemon_state.json` | Update ID tracking |
| `~/.atrophy/.telegram_daemon.lock` | Instance lock |
| `~/.atrophy/.telegram_daemon.lock.pid` | PID file (fallback) |
| `~/.atrophy/agents/<name>/data/agent.json` | Agent config |

## Exported API

| Function | Purpose |
|----------|---------|
| `setMainWindowAccessor(fn)` | Set main window getter |
| `acquireLock()` | Acquire exclusive daemon lock |
| `releaseLock()` | Release daemon lock |
| `startDaemon()` | Start polling daemon |
| `stopDaemon()` | Stop daemon |
| `getAgentSession(agentName)` | Get/create agent session |

## See Also

- [`api.ts`](api.md) - Telegram Bot API client
- [`formatter.ts`](formatter.md) - Streaming status display
- `src/main/ipc/telegram.ts` - Telegram IPC handlers
- `src/main/channels/switchboard.ts` - Message routing

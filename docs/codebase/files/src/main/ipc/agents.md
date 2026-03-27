# src/main/ipc/agents.ts - Agent Management IPC Handlers

**Dependencies:** `electron`, `path`, `fs`, `../config`, `../agent-manager`, `../prompts`, `../memory`, `../jobs/generate-mirror-avatar`, `../avatar-downloader`, `../queue`, `../session`, `../logger`, `../ipc-handlers`  
**Purpose:** IPC handlers for agent management, deferral, message queues, mirror setup, ask-user responses, and org management

## Overview

This module provides the renderer with controls for:
- Listing and cycling agents
- Getting/setting agent state (muted/enabled)
- Switching agents (with session suspension/resumption)
- Mirror avatar setup (photo upload, generation, voice ID)
- Agent deferral (handoff between agents)
- Message queue draining
- Ask-user response handling (MCP ask_user tool → GUI dialog)
- **NEW:** Agent/org CRUD operations

## Recent Changes (2026-03-26)

### Session Suspension on Deferral

Updated `deferral:complete` to suspend (not end) the current agent's session:

```typescript
// Suspend (not end) current agent's session so it can be resumed later
if (ctx.currentSession) {
  if (ctx.currentSession.cliSessionId) {
    suspendAgentSession(ctx.currentAgentName!, ctx.currentSession.cliSessionId, ctx.currentSession.turnHistory);
  }
  // Close the session in the DB so ended_at is set
  if (ctx.currentSession.sessionId != null) {
    endSessionInDb(ctx.currentSession.sessionId, null, ctx.currentSession.mood);
  }
  ctx.currentSession = null;  // Null out before switchAgent
}

// Use the canonical switchAgent
const result = await ctx.switchAgent(data.target);

// Resume a previously suspended session for the target agent
const resumed = resumeAgentSession(data.target);
```

**Benefits:**
- Preserves conversation context across deferrals
- Allows resuming suspended sessions later
- Cleaner session lifecycle

### New Handlers

| Handler | Purpose |
|---------|---------|
| `agent:create` | Create new agent with org context |
| `agent:delete` | Delete agent |
| `org:list` | List organizations |
| `org:create` | Create organization |
| `org:dissolve` | Dissolve organization |
| `org:addAgent` | Add agent to organization |
| `org:removeAgent` | Remove agent from organization |
| `job:update` | Update job schedule/config |

## IPC Handlers

### Agent Discovery

#### agent:list

```typescript
ipcMain.handle('agent:list', () => {
  return discoverUiAgents().map(a => a.name);
});
```

**Returns:** Array of agent directory names (e.g., `['xan', 'kai', 'nova']`)

#### agent:listFull

```typescript
ipcMain.handle('agent:listFull', () => {
  return discoverUiAgents();
});
```

**Returns:** Full agent info objects with name, display_name, description, role

#### agent:cycle

```typescript
ipcMain.handle('agent:cycle', (_event, direction: number) => {
  const next = cycleAgent(direction, getConfig().AGENT_NAME);
  return next;
});
```

**Parameters:**
- `direction`: +1 for next agent, -1 for previous

**Returns:** Next agent info object

**Use case:** Rolodex-style agent switching via chevron clicks in AgentName.svelte

### Agent State

#### agent:getState

```typescript
ipcMain.handle('agent:getState', (_event, name: string) => {
  return getAgentState(name);
});
```

**Returns:** `{ muted?: boolean; enabled?: boolean }`

#### agent:setState

```typescript
ipcMain.handle('agent:setState', (_event, name: string, opts: { muted?: boolean; enabled?: boolean }) => {
  setAgentState(name, opts);
});
```

**Purpose:** Mute/unmute or enable/disable an agent. State persisted to `~/.atrophy/agent_states.json`.

### Agent Switching

#### agent:switch

```typescript
ipcMain.handle('agent:switch', async (_event, name: string) => {
  return ctx.switchAgent(name);
});
```

**Delegates to:** `ctx.switchAgent()` from `app.ts`

**Returns:** `{ agentName, agentDisplayName, customSetup }`

### Mirror Avatar Setup

#### mirror:uploadPhoto

```typescript
ipcMain.handle('mirror:uploadPhoto', async (_event, photoData: ArrayBuffer, filename: string) => {
  const c = getConfig();
  const ext = path.extname(filename).toLowerCase() || '.jpg';
  if (!['.png', '.jpg', '.jpeg', '.webp'].includes(ext)) {
    throw new Error('Unsupported image format. Use PNG, JPG, or WebP.');
  }
  const saved = saveUserPhoto(c.AGENT_NAME, Buffer.from(photoData), ext);
  return saved;
});
```

**Purpose:** Save user-uploaded photo for mirror avatar generation.

**Validation:** Only PNG, JPG, JPEG, WebP allowed.

**Returns:** Saved file path

#### mirror:generateAvatar

```typescript
ipcMain.handle('mirror:generateAvatar', async () => {
  const c = getConfig();
  const clips = await generateMirrorAvatar(c.AGENT_NAME, (progress: MirrorAvatarProgress) => {
    if (ctx.mainWindow) {
      ctx.mainWindow.webContents.send('mirror:avatarProgress', progress);
    }
  });
  return clips;
});
```

**Purpose:** Generate mirror avatar video loops from uploaded photo.

**Progress events:** Sends `mirror:avatarProgress` to renderer with generation progress.

**Returns:** Array of generated clip paths

#### mirror:saveVoiceId

```typescript
ipcMain.handle('mirror:saveVoiceId', async (_event, voiceId: string) => {
  const c = getConfig();
  saveAgentConfig(c.AGENT_NAME, { ELEVENLABS_VOICE_ID: voiceId });
  c.ELEVENLABS_VOICE_ID = voiceId;
});
```

**Purpose:** Save ElevenLabs voice ID to agent config.

#### mirror:checkSetup

```typescript
ipcMain.handle('mirror:checkSetup', () => {
  const c = getConfig();
  return {
    hasPhoto: hasMirrorSourcePhoto(c.AGENT_NAME),
    hasLoops: isMirrorSetupComplete(c.AGENT_NAME),
  };
});
```

**Returns:** `{ hasPhoto: boolean; hasLoops: boolean }`

**Use case:** Check mirror setup completion status in Settings panel.

#### mirror:openExternal

```typescript
ipcMain.handle('mirror:openExternal', (_event, url: string) => {
  // Only allow specific trusted URLs
  const allowed = [
    'https://elevenlabs.io',
    'https://www.elevenlabs.io',
  ];
  if (allowed.some((prefix) => url.startsWith(prefix))) {
    shell.openExternal(url);
  }
});
```

**Security:** URL allowlist prevents opening arbitrary URLs from renderer.

#### mirror:downloadAssets

```typescript
ipcMain.handle('mirror:downloadAssets', async () => {
  const c = getConfig();
  await ensureAvatarAssets(c.AGENT_NAME, ctx.mainWindow);
});
```

**Purpose:** Download placeholder avatar assets for agent.

### Agent Deferral

#### deferral:complete

```typescript
ipcMain.handle('deferral:complete', async (_event, data: { target: string; context: string; user_question: string }) => {
  if (!/^[a-zA-Z0-9_-]+$/.test(data.target)) throw new Error('Invalid agent name');
  try {
    // 1. End and suspend current agent's session
    if (ctx.currentSession) {
      if (ctx.currentSession.cliSessionId) {
        suspendAgentSession(ctx.currentAgentName!, ctx.currentSession.cliSessionId, ctx.currentSession.turnHistory);
      }
      if (ctx.currentSession.sessionId != null) {
        try {
          endSessionInDb(ctx.currentSession.sessionId, null, ctx.currentSession.mood);
        } catch { /* non-fatal */ }
      }
      ctx.currentSession = null;
    }

    // 2. Stop current inference and audio
    stopInference();
    clearAudioQueue();

    // 3. Switch to target agent
    const config = getConfig();
    config.reloadForAgent(data.target);
    initDb();
    resetMcpConfig();
    ctx.currentAgentName = data.target;
    setLastActiveAgent(data.target);

    // 4. Resume or create new session for target agent
    const resumed = resumeAgentSession(data.target);
    ctx.currentSession = new Session();
    ctx.currentSession.start();
    if (resumed) {
      ctx.currentSession.setCliSessionId(resumed.cliSessionId);
      ctx.currentSession.turnHistory = resumed.turnHistory as typeof ctx.currentSession.turnHistory;
    } else {
      ctx.currentSession.inheritCliSessionId();
    }
    ctx.systemPrompt = null;  // Force reload for new agent

    return {
      agentName: config.AGENT_NAME,
      agentDisplayName: config.AGENT_DISPLAY_NAME,
    };
  } catch (err) {
    log.error(`deferral:complete failed: ${err}`);
    throw err;
  }
});
```

**Purpose:** Complete an agent deferral - suspend current agent, switch to target, resume target's session.

**Deferral flow:**
1. **Suspend current session:** Save CLI session with turn history for later resumption
2. **End DB session:** Set `ended_at` in database
3. **Stop inference:** Kill any running Claude CLI subprocess
4. **Clear audio queue:** Stop pending TTS playback
5. **Switch config:** Reload config for target agent
6. **Reinitialize DB:** Open target agent's database
7. **Reset MCP config:** Regenerate MCP config for new agent
8. **Resume target session:** Restore CLI session if available, or create new one
9. **Clear system prompt:** Force reload for new agent

**Returns:** New agent info

### Message Queues

#### queue:drainAgent

```typescript
ipcMain.handle('queue:drainAgent', (_event, agentName: string) => {
  // Validate agent name to prevent path traversal
  if (!/^[a-zA-Z0-9_-]+$/.test(agentName)) return [];
  return drainAgentQueue(agentName);
});
```

**Security:** Agent name validation prevents path traversal attacks.

**Returns:** Array of pending messages for specific agent

#### queue:drainAll

```typescript
ipcMain.handle('queue:drainAll', () => {
  return drainAllAgentQueues();
});
```

**Returns:** Array of all pending messages across all agents

### Ask-User Response (MCP ask_user → GUI)

#### ask:respond

```typescript
ipcMain.handle('ask:respond', (_event, requestId: string, response: string | boolean | null) => {
  // Verify requestId matches active ask dialog
  if (!ctx.pendingAskId || ctx.pendingAskId !== requestId) {
    log.warn(`ask:respond ignored: requestId mismatch (expected ${ctx.pendingAskId}, got ${requestId})`);
    return;
  }

  // If destination was set (secure_input), route value before writing response
  let destinationFailed = false;
  if (ctx.pendingAskDestination && typeof response === 'string' && response) {
    const dest = ctx.pendingAskDestination;
    if (dest.startsWith('secret:')) {
      const key = dest.slice('secret:'.length);
      if (!saveEnvVar(key, response)) {
        log.warn(`ask:respond - secret key rejected by whitelist: ${key}`);
        destinationFailed = true;
      }
    } else if (dest.startsWith('config:')) {
      const key = dest.slice('config:'.length);
      const SAFE_CONFIG_KEYS = new Set([
        'USER_NAME', 'MUTE_BY_DEFAULT', 'EYE_MODE_DEFAULT',
        'INPUT_MODE', 'VOICE_CALL_MODE', 'WAKE_WORD_ENABLED', 'ADAPTIVE_EFFORT',
        'NOTIFICATIONS_ENABLED', 'WINDOW_WIDTH', 'WINDOW_HEIGHT',
      ]);
      if (!SAFE_CONFIG_KEYS.has(key)) {
        log.warn(`ask:respond - config key rejected by allowlist: ${key}`);
        destinationFailed = true;
      } else {
        saveUserConfig({ [key]: response });
      }
    }
  }

  writeAskResponse(requestId, response, destinationFailed);
  ctx.pendingAskId = null;
  ctx.pendingAskDestination = null;
});
```

**Purpose:** Handle user response to MCP ask_user tool requests.

**Security features:**
1. **Request ID validation:** Prevents stale/fabricated responses
2. **Secret key whitelist:** Only allowed env vars can be saved
3. **Config key allowlist:** Only safe config keys can be modified

**Destination routing:**
- `secret:<key>` → `saveEnvVar(key, value)` → `~/.atrophy/.env`
- `config:<key>` → `saveUserConfig({ [key]: value })` → `~/.atrophy/config.json`

**Response flow:**
1. Verify request ID matches pending ask
2. If destination set and response is string:
   - Route to secret store or config based on prefix
   - Validate against allowlist
3. Write response file for MCP server to read
4. Clear pending state

## Security Considerations

### Input Validation

**Agent name validation:**
```typescript
if (!/^[a-zA-Z0-9_-]+$/.test(agentName)) return [];
```

Prevents path traversal and injection attacks.

### URL Allowlisting

```typescript
const allowed = [
  'https://elevenlabs.io',
  'https://www.elevenlabs.io',
];
if (allowed.some((prefix) => url.startsWith(prefix))) {
  shell.openExternal(url);
}
```

Prevents opening arbitrary URLs from renderer.

### Secret Key Whitelist

```typescript
const ALLOWED_ENV_KEYS = new Set([
  'ELEVENLABS_API_KEY',
  'FAL_KEY',
  'TELEGRAM_BOT_TOKEN',
  'TELEGRAM_CHAT_ID',
  'OPENAI_API_KEY',
  'ANTHROPIC_API_KEY',
]);
```

Only these keys can be saved via ask:respond.

### Config Key Allowlist

```typescript
const SAFE_CONFIG_KEYS = new Set([
  'USER_NAME', 'MUTE_BY_DEFAULT', 'EYE_MODE_DEFAULT',
  'INPUT_MODE', 'VOICE_CALL_MODE', 'WAKE_WORD_ENABLED', 'ADAPTIVE_EFFORT',
  'NOTIFICATIONS_ENABLED', 'WINDOW_WIDTH', 'WINDOW_HEIGHT',
]);
```

Prevents changing security-sensitive settings (binary paths, etc.).

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/agents/<name>/avatar/source/` | mirror:uploadPhoto |
| Write | `~/.atrophy/agents/<name>/avatar/source/face.<ext>` | mirror:uploadPhoto |
| Read/Write | `~/.atrophy/agents/<name>/avatar/loops/` | mirror:generateAvatar |
| Read/Write | `~/.atrophy/agents/<name>/data/agent.json` | mirror:saveVoiceId |
| Read/Write | `~/.atrophy/agent_states.json` | agent:getState/setState |
| Read/Write | `~/.atrophy/agents/<name>/data/.message_queue.json` | queue:drain* |
| Read/Write | `~/.atrophy/agents/<name>/data/.ask_response.json` | ask:respond |
| Write | `~/.atrophy/.env` | ask:respond (secret:) |
| Write | `~/.atrophy/config.json` | ask:respond (config:) |
| Write | `~/.atrophy/agents/<name>/data/memory.db` | ask:respond (observation) |

## Exported API

| Function | Purpose |
|----------|---------|
| `registerAgentHandlers(ctx)` | Register all agent IPC handlers |

## See Also

- `src/main/agent-manager.ts` - Agent discovery and state management
- `src/main/jobs/generate-mirror-avatar.ts` - Mirror avatar generation
- `src/main/queue.ts` - Message queue management
- `src/main/ipc-handlers.ts` - IPC context interface

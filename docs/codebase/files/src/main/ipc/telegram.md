# src/main/ipc/telegram.ts - Telegram IPC Handlers

**Line count:** ~70 lines  
**Dependencies:** `electron`, `../config`, `../agent-manager`, `../channels/telegram`, `../ipc-handlers`  
**Purpose:** IPC handlers for Telegram daemon and bot management

## Overview

This module provides the renderer with controls for:
- Starting/stopping Telegram daemon
- Checking daemon status
- Discovering chat ID from bot token
- Saving agent bot token
- Setting bot profile photo
- Getting agent Telegram config

## IPC Handlers

### Daemon Control

#### telegram:startDaemon

```typescript
ipcMain.handle('telegram:startDaemon', () => {
  return startDaemon();
});
```

**Purpose:** Start Telegram polling daemon.

**Returns:** `true` if started successfully

#### telegram:stopDaemon

```typescript
ipcMain.handle('telegram:stopDaemon', () => {
  stopDaemon();
});
```

**Purpose:** Stop Telegram polling daemon.

#### telegram:isRunning

```typescript
ipcMain.handle('telegram:isRunning', () => {
  return isDaemonRunning();
});
```

**Returns:** Whether daemon is currently running

### Chat ID Discovery

#### telegram:discoverChatId

```typescript
ipcMain.handle('telegram:discoverChatId', async (_event, botToken: string, agentName?: string) => {
  if (agentName && !AGENT_NAME_RE.test(agentName)) throw new Error('Invalid agent name');
  const result = await discoverChatId(botToken);
  if (result) {
    const c = getConfig();
    const targetAgent = agentName || c.AGENT_NAME;
    saveAgentConfig(targetAgent, { TELEGRAM_CHAT_ID: result.chatId });
    if (targetAgent === c.AGENT_NAME) {
      (c as unknown as Record<string, unknown>).TELEGRAM_CHAT_ID = result.chatId;
    }
  }
  return result;
});
```

**Purpose:** Auto-discover chat ID by sending a test message and polling for it.

**Flow:**
1. Validate agent name
2. Call `discoverChatId(botToken)` which:
   - Sends "Setup test message" to the bot's chat
   - Polls for incoming messages for 60 seconds
   - Extracts chat ID from first message received
3. Save discovered chat ID to agent config
4. Update running config if target is current agent

**Returns:** `{ chatId: string }` or `null` on failure

### Bot Token Management

#### telegram:saveAgentBotToken

```typescript
ipcMain.handle('telegram:saveAgentBotToken', async (_event, agentName: string, botToken: string) => {
  if (!AGENT_NAME_RE.test(agentName)) throw new Error('Invalid agent name');
  saveAgentConfig(agentName, { TELEGRAM_BOT_TOKEN: botToken });
  const c = getConfig();
  if (agentName === c.AGENT_NAME) {
    (c as unknown as Record<string, unknown>).TELEGRAM_BOT_TOKEN = botToken;
  }
});
```

**Purpose:** Save bot token to agent config.

**Security:** Agent name validation prevents injection.

### Bot Profile Photo

#### telegram:setBotPhoto

```typescript
ipcMain.handle('telegram:setBotPhoto', async (_event, agentName: string, botToken: string) => {
  if (!AGENT_NAME_RE.test(agentName)) throw new Error('Invalid agent name');
  const { getReferenceImages } = await import('../jobs/generate-avatar');
  const { setBotProfilePhoto } = await import('../channels/telegram');
  const refs = getReferenceImages(agentName);
  if (refs.length === 0) return false;
  return setBotProfilePhoto(refs[0], botToken);
});
```

**Purpose:** Set bot's profile photo from agent's reference image.

**Flow:**
1. Validate agent name
2. Get reference images for agent
3. Call `setBotProfilePhoto()` with first reference image

**Returns:** `true` on success, `false` if no reference images or API failure

### Agent Config

#### telegram:getAgentConfig

```typescript
ipcMain.handle('telegram:getAgentConfig', async (_event, agentName: string) => {
  if (!AGENT_NAME_RE.test(agentName)) throw new Error('Invalid agent name');
  const manifest = findManifest(agentName) || {};
  const channels = (manifest.channels as Record<string, Record<string, string>> | undefined) || {};
  const tg = channels.telegram || {};
  const botTokenEnv = tg.bot_token_env;
  const chatIdEnv = tg.chat_id_env;
  return {
    botToken: botTokenEnv && process.env[botTokenEnv] ? '***' : '',
    chatId: chatIdEnv ? process.env[chatIdEnv] || '' : '',
  };
});
```

**Purpose:** Read agent's Telegram config from manifest.

**Why direct manifest read:** Avoids mutating the shared config singleton which could race with the Telegram daemon.

**Returns:** `{ botToken: string; chatId: string }` with masked token

## Security Considerations

### Agent Name Validation

```typescript
const AGENT_NAME_RE = /^[a-zA-Z0-9_-]+$/;
```

Prevents path traversal and injection attacks.

### Secret Masking

```typescript
botToken: botTokenEnv && process.env[botTokenEnv] ? '***' : ''
```

Bot tokens are masked before sending to renderer.

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/agents/<name>/data/agent.json` | telegram:saveAgentBotToken, telegram:getAgentConfig |
| Read | `~/.atrophy/agents/<name>/avatar/source/` | telegram:setBotPhoto |
| Write | `~/.atrophy/agents/<name>/data/agent.json` | telegram:discoverChatId, telegram:saveAgentBotToken |

## Exported API

| Function | Purpose |
|----------|---------|
| `registerTelegramHandlers(ctx)` | Register all Telegram IPC handlers |

## See Also

- `src/main/channels/telegram/` - Telegram daemon and API
- `src/main/agent-manager.ts` - Agent discovery and manifest loading
- `src/main/jobs/generate-avatar.ts` - Reference image management
- `src/main/config.ts` - Configuration management

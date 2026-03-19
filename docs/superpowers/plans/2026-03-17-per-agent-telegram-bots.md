# Per-Agent Telegram Bots Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Topics-based single-bot architecture with per-agent Telegram bots, where each agent has its own bot, chat, and profile picture - like separate friends in WhatsApp.

**Architecture:** Per-agent `telegram_bot_token` and `telegram_chat_id` in agent.json, with global credentials as fallback for Xan. Daemon rewired to run parallel pollers (one per agent) with random jitter. `channels/telegram/api.ts` functions accept optional `botToken` param. `threadId` removed throughout. Settings UI gets per-agent telegram config in agent list. Setup wizard asks for bot token on new agent creation.

**Tech Stack:** TypeScript, Electron, Telegram Bot API, Svelte 5 (runes mode)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/main/config.ts` | Modify | Add per-agent telegram resolution, remove `TELEGRAM_GROUP_ID` |
| `src/main/channels/telegram/api.ts` | Modify | Add `botToken` param to `post()` and public functions, remove `threadId`, add `setBotProfilePhoto()` |
| `src/main/channels/telegram/daemon.ts` | Rewrite | Parallel per-agent pollers, remove Topics mode |
| `src/main/app.ts` | Modify | New IPC handlers for per-agent telegram config, remove group ID |
| `src/preload/index.ts` | Modify | Expose new IPC channels |
| `src/renderer/components/Settings.svelte` | Modify | Per-agent telegram config in agent list |
| `src/main/inference.ts` | Modify | Pass per-agent telegram credentials to MCP env |

---

### Task 1: Config - per-agent telegram resolution

**Files:**
- Modify: `src/main/config.ts`

- [ ] **Step 1: Read config.ts to understand current structure**

Read the full file to understand the _resolveAgent method, AGENT_KEY_NESTING, AGENT_KEY_ROOT, and how telegram fields are currently resolved.

- [ ] **Step 2: Add per-agent telegram fields to _resolveAgent**

In `_resolveAgent()`, after the line that reads `TELEGRAM_EMOJI` (~line 667), add:

```typescript
    // Per-agent telegram credentials (fall back to global)
    this.TELEGRAM_BOT_TOKEN =
      (_agentManifest.telegram_bot_token as string) ||
      process.env.TELEGRAM_BOT_TOKEN ||
      cfg('TELEGRAM_BOT_TOKEN', '');
    this.TELEGRAM_CHAT_ID =
      (_agentManifest.telegram_chat_id as string) ||
      process.env.TELEGRAM_CHAT_ID ||
      cfg('TELEGRAM_CHAT_ID', '');
```

- [ ] **Step 3: Remove the old global-only telegram resolution**

Find and remove the existing telegram resolution block (~lines 752-757):
```typescript
    // Telegram - system-level credentials, shared by all agents.
    // One bot, one group. Topics mode - each agent gets its own topic thread.
    this.TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || cfg('TELEGRAM_BOT_TOKEN', '');
    this.TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID || cfg('TELEGRAM_CHAT_ID', '');
    this.TELEGRAM_GROUP_ID = process.env.TELEGRAM_GROUP_ID || cfg('TELEGRAM_GROUP_ID', '');
```

- [ ] **Step 4: Remove TELEGRAM_GROUP_ID from the class**

Remove `TELEGRAM_GROUP_ID` from:
- The class property declaration
- The defaults in the constructor
- The `ALLOWED_ENV_KEYS` set (but keep the other telegram keys)

- [ ] **Step 5: Add telegram keys to AGENT_KEY_ROOT mapping**

In the `AGENT_KEY_ROOT` map (around line 848), add:
```typescript
  TELEGRAM_BOT_TOKEN: 'telegram_bot_token',
  TELEGRAM_CHAT_ID: 'telegram_chat_id',
```

This ensures `saveAgentConfig` writes them as snake_case root keys in agent.json.

- [ ] **Step 6: Run type check**

Run: `npx tsc --noEmit`
Expected: Errors for TELEGRAM_GROUP_ID references in other files (expected, fixed in later tasks)

- [ ] **Step 7: Commit**

```bash
git add src/main/config.ts
git commit -m "feat: per-agent telegram credentials with global fallback"
```

---

### Task 2: telegram api - add botToken param, remove threadId

**Files:**
- Modify: `src/main/channels/telegram/api.ts`

- [ ] **Step 1: Read channels/telegram/api.ts fully**

- [ ] **Step 2: Update post() to accept botToken**

Change the internal `post` function and `apiUrl`:

```typescript
function apiUrl(method: string, botToken?: string): string {
  const token = botToken || getConfig().TELEGRAM_BOT_TOKEN;
  return `https://api.telegram.org/bot${token}/${method}`;
}

export async function post(method: string, payload: Record<string, unknown>, timeoutMs = 15_000, botToken?: string): Promise<unknown | null> {
  const token = botToken || getConfig().TELEGRAM_BOT_TOKEN;
  if (!token) {
    log.warn('TELEGRAM_BOT_TOKEN not configured');
    return null;
  }

  const pollTimeout = (payload.timeout as number) || 0;
  const fetchTimeout = pollTimeout > 0 ? (pollTimeout + 10) * 1000 : 15_000;

  try {
    const resp = await fetch(apiUrl(method, botToken), {
      // ... rest unchanged
```

- [ ] **Step 3: Remove threadId from sendMessage**

Remove the `threadId` parameter and the `if (threadId) payload.message_thread_id = threadId;` line.

- [ ] **Step 4: Remove threadId from sendMessageGetId**

Same - remove threadId param and message_thread_id payload.

- [ ] **Step 5: Remove threadId from sendButtons**

Same pattern.

- [ ] **Step 6: Remove threadId from sendVoiceNote, sendPhoto, sendVideo, sendDocument, sendArtefact**

Remove threadId param from all file-sending functions. Remove `message_thread_id` from `sendFileUpload`.

- [ ] **Step 7: Add botToken param to sendMessage, sendMessageGetId, editMessage, sendButtons**

Add optional `botToken?: string` as the last parameter to each. Pass through to `post()`.

- [ ] **Step 8: Add setBotProfilePhoto function**

```typescript
/**
 * Set the bot's profile photo. Requires the photo as a local file path.
 */
export async function setBotProfilePhoto(photoPath: string, botToken?: string): Promise<boolean> {
  const token = botToken || getConfig().TELEGRAM_BOT_TOKEN;
  if (!token) return false;

  try {
    const boundary = `----FormBoundary${Date.now()}${Math.random().toString(36).slice(2)}`;
    const body = buildMultipartBody({}, { name: 'photo', path: photoPath, contentType: 'image/png' }, boundary);

    const resp = await fetch(apiUrl('setMyProfilePhoto', token), {
      method: 'POST',
      headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}` },
      body,
      signal: AbortSignal.timeout(30_000),
    });

    const result = await resp.json() as { ok: boolean };
    if (result.ok) {
      log.info('Bot profile photo updated');
      return true;
    }
    log.warn(`setMyProfilePhoto failed: ${JSON.stringify(result)}`);
    return false;
  } catch (e) {
    log.warn(`setMyProfilePhoto error: ${e}`);
    return false;
  }
}
```

- [ ] **Step 9: Update discoverChatId to use provided token consistently**

The function already takes `botToken` as a param and builds URLs manually. No change needed, but verify it does not use `apiUrl()`.

- [ ] **Step 10: Update the export line**

Add `setBotProfilePhoto` to exports. Remove references to `_post` alias if no longer needed by daemon (daemon will use `post` directly with botToken).

- [ ] **Step 11: Run type check**

Run: `npx tsc --noEmit`
Expected: Errors in channels/telegram/daemon.ts and other files that still pass threadId (expected, fixed in later tasks)

- [ ] **Step 12: Commit**

```bash
git add src/main/channels/telegram/api.ts
git commit -m "feat: per-agent bot token support, remove threadId from telegram API"
```

---

### Task 3: Rewrite telegram daemon - parallel per-agent pollers

**Files:**
- Modify: `src/main/channels/telegram/daemon.ts`

This is the largest task. The daemon is completely rewritten from single-poller/Topics to parallel per-agent pollers.

- [ ] **Step 1: Read the current channels/telegram/daemon.ts fully**

- [ ] **Step 2: Replace state types and persistence**

Replace `DaemonState` and related code:

```typescript
interface AgentPollerState {
  last_update_id: number;
}

interface DaemonState {
  agents: Record<string, AgentPollerState>; // agent_name -> state
}
```

Update `loadState` / `saveState` to use the new shape. Migrate old format: if `topic_map` exists in loaded state, ignore it.

- [ ] **Step 3: Remove Topics mode code**

Remove entirely:
- `createForumTopic()`
- `ensureTopics()`
- All `topic_map` / `message_thread_id` / `threadId` references

- [ ] **Step 4: Update discoverEnabledAgents to include telegram credentials**

```typescript
function discoverTelegramAgents(): { name: string; display_name: string; emoji: string; botToken: string; chatId: string }[] {
  const agents: { name: string; display_name: string; emoji: string; botToken: string; chatId: string }[] = [];
  const config = getConfig();

  for (const agent of discoverAgents()) {
    const state = getAgentState(agent.name);
    if (!state.enabled) continue;

    // Temporarily load this agent's config to get their telegram credentials
    config.reloadForAgent(agent.name);
    const botToken = config.TELEGRAM_BOT_TOKEN;
    const chatId = config.TELEGRAM_CHAT_ID;

    if (!botToken || !chatId) continue; // Skip agents without telegram config

    const manifest = getAgentManifest(agent.name);
    agents.push({
      name: agent.name,
      display_name: agent.display_name || agent.name.charAt(0).toUpperCase() + agent.name.slice(1),
      emoji: (manifest.telegram_emoji as string) || '',
      botToken,
      chatId,
    });
  }

  // Restore original agent
  config.reloadForAgent(config.AGENT_NAME);
  return agents;
}
```

- [ ] **Step 5: Rewrite dispatchToAgent to accept botToken**

Update the signature and pass botToken to all telegram calls:

```typescript
async function dispatchToAgent(
  agentName: string,
  text: string,
  chatId: string,
  botToken: string,
): Promise<string | null>
```

Replace all `sendMessageGetId(...)` and `editMessage(...)` calls to include `botToken` as the last argument. Remove all threadId params.

- [ ] **Step 6: Write the per-agent poller function**

```typescript
async function pollAgent(
  agent: { name: string; display_name: string; emoji: string; botToken: string; chatId: string },
): Promise<void> {
  const agentState = _state.agents[agent.name] || { last_update_id: 0 };

  let raw: unknown;
  try {
    raw = await post('getUpdates', {
      offset: agentState.last_update_id + 1,
      timeout: 30,
      allowed_updates: ['message'],
    }, 45_000, agent.botToken);
  } catch (e) {
    if (!_running) return;
    throw e;
  }

  const result = Array.isArray(raw) ? raw as {
    update_id: number;
    message?: {
      text?: string;
      caption?: string;
      from?: { id: number };
      chat?: { id: number };
      photo?: { file_id: string; width: number; height: number }[];
      voice?: { file_id: string; duration: number };
      document?: { file_id: string; file_name?: string };
      video?: { file_id: string; duration: number };
    };
  }[] : null;

  if (!result) return;

  for (const update of result) {
    agentState.last_update_id = Math.max(agentState.last_update_id, update.update_id);

    const msg = update.message;
    if (!msg) continue;

    const hasText = !!(msg.text?.trim());
    const hasMedia = !!(msg.photo || msg.voice || msg.document || msg.video);
    if (!hasText && !hasMedia) continue;

    // Only accept messages from the configured chat
    const msgChatId = String(msg.chat?.id || '');
    if (msgChatId !== agent.chatId) continue;

    const text = (msg.text || '').trim();

    // Handle /status
    if (text.toLowerCase() === '/status') {
      await handleStatusCommand(msgChatId, agent.botToken);
      continue;
    }

    // Build prompt (same media handling as before but without threadId)
    const promptParts: string[] = [];
    const mediaDir = path.join(USER_DATA, 'agents', agent.name, 'media');

    // ... same media download logic as current but using downloadTelegramFile with agent.botToken ...

    const messageText = text || (msg.caption || '').trim();
    if (messageText) promptParts.push(messageText);

    const fullPrompt = promptParts.join('\n\n');
    if (!fullPrompt) continue;

    log.info(`[${agent.name}] Message: ${fullPrompt.slice(0, 80)}`);

    const response = await dispatchToAgent(agent.name, fullPrompt, msgChatId, agent.botToken);
    if (response) {
      log.info(`[${agent.name}] Responded (${response.length} chars)`);
    } else {
      log.warn(`[${agent.name}] No response`);
    }
  }

  _state.agents[agent.name] = agentState;
  saveState(_state);
}
```

- [ ] **Step 7: Write per-agent poller loop with jitter**

```typescript
async function runAgentPoller(
  agent: { name: string; display_name: string; emoji: string; botToken: string; chatId: string },
): Promise<void> {
  log.info(`[${agent.name}] Poller started (bot: ...${agent.botToken.slice(-6)})`);

  while (_running) {
    try {
      await pollAgent(agent);
    } catch (e) {
      if (!_running) return;
      log.error(`[${agent.name}] Poll error: ${e}`);
    }
    if (_running) {
      // Random jitter: 8-15 seconds between polls for organic feel
      const jitter = 8000 + Math.random() * 7000;
      await new Promise((resolve) => {
        const t = setTimeout(resolve, jitter);
        _pollerTimers.push(t as unknown as ReturnType<typeof setTimeout>);
      });
    }
  }

  log.info(`[${agent.name}] Poller stopped`);
}
```

- [ ] **Step 8: Rewrite startDaemon to launch parallel pollers**

```typescript
let _pollerTimers: ReturnType<typeof setTimeout>[] = [];

export function startDaemon(): boolean {
  if (_running) return true;

  if (!acquireLock()) {
    log.warn('Another instance is running - exiting');
    return false;
  }

  _running = true;
  _state = loadState();
  _pollerTimers = [];

  const agents = discoverTelegramAgents();

  if (agents.length === 0) {
    log.warn('No agents with telegram credentials found');
    releaseLock();
    _running = false;
    return false;
  }

  log.info(`Starting ${agents.length} poller(s): ${agents.map((a) => a.name).join(', ')}`);

  // Set bot profile photos on startup
  for (const agent of agents) {
    setAgentBotPhoto(agent.name, agent.botToken).catch(() => {});
  }

  // Launch all pollers in parallel
  for (const agent of agents) {
    runAgentPoller(agent);
  }

  return true;
}
```

- [ ] **Step 9: Update stopDaemon**

```typescript
export function stopDaemon(): void {
  _running = false;
  for (const t of _pollerTimers) clearTimeout(t);
  _pollerTimers = [];
  releaseLock();
  log.info('Stopped');
}
```

- [ ] **Step 10: Add setBotProfilePhoto helper**

```typescript
import { setBotProfilePhoto } from './channels/telegram';
import { getReferenceImages } from './jobs/generate-avatar';

async function setAgentBotPhoto(agentName: string, botToken: string): Promise<void> {
  const refs = getReferenceImages(agentName);
  if (refs.length === 0) return;
  try {
    await setBotProfilePhoto(refs[0], botToken);
    log.info(`[${agentName}] Bot profile photo set`);
  } catch (e) {
    log.debug(`[${agentName}] Profile photo failed: ${e}`);
  }
}
```

- [ ] **Step 11: Update handleStatusCommand to accept botToken**

```typescript
async function handleStatusCommand(chatId: string, botToken: string): Promise<void> {
  const agents = discoverTelegramAgents();
  const lines = ['*Active agents:*\n'];
  for (const a of agents) {
    const prefix = a.emoji ? `${a.emoji} ` : '';
    lines.push(`${prefix}*${a.display_name}*`);
  }
  await sendMessage(lines.join('\n'), chatId, false, botToken);
}
```

- [ ] **Step 12: Update downloadTelegramFile calls for per-agent botToken**

The `downloadTelegramFile` function in `channels/telegram/api.ts` uses `config.TELEGRAM_BOT_TOKEN` internally. Since we call `config.reloadForAgent()` before dispatch, this should resolve correctly. But the `pollAgent` function calls it BEFORE dispatch. Need to either:
- Pass botToken to downloadTelegramFile (add param)
- Or temporarily reload config in pollAgent before media download

Simplest: add optional `botToken` param to `downloadTelegramFile` in `channels/telegram/api.ts`.

- [ ] **Step 13: Remove launchd plist generation for Topics mode**

Keep the launchd install/uninstall functions but update `buildDaemonPlist` if needed. The plist args don't reference Topics.

- [ ] **Step 14: Run type check**

Run: `npx tsc --noEmit`
Expected: Clean (or minor issues in other files)

- [ ] **Step 15: Commit**

```bash
git add src/main/channels/telegram/daemon.ts
git commit -m "feat: parallel per-agent telegram pollers, remove Topics mode"
```

---

### Task 4: IPC handlers and preload

**Files:**
- Modify: `src/main/app.ts`
- Modify: `src/preload/index.ts`

- [ ] **Step 1: Add TELEGRAM_BOT_TOKEN to agentKeys in app.ts**

In the `agentKeys` set (~line 584), add `'TELEGRAM_BOT_TOKEN'` alongside the existing `'TELEGRAM_CHAT_ID'`.

- [ ] **Step 2: Update discoverChatId handler for per-agent use**

Update the `telegram:discoverChatId` handler to save to agent.json instead of env:

```typescript
  ipcMain.handle('telegram:discoverChatId', async (_event, botToken: string, agentName?: string) => {
    const result = await discoverChatId(botToken);
    if (result) {
      const c = getConfig();
      const targetAgent = agentName || c.AGENT_NAME;
      saveAgentConfig(targetAgent, { TELEGRAM_CHAT_ID: result.chatId });
      // Update running config if this is the current agent
      if (targetAgent === c.AGENT_NAME) {
        (c as unknown as Record<string, unknown>).TELEGRAM_CHAT_ID = result.chatId;
      }
    }
    return result;
  });
```

- [ ] **Step 3: Add IPC handler for saving per-agent telegram bot token**

```typescript
  ipcMain.handle('telegram:saveAgentBotToken', async (_event, agentName: string, botToken: string) => {
    saveAgentConfig(agentName, { TELEGRAM_BOT_TOKEN: botToken });
    const c = getConfig();
    if (agentName === c.AGENT_NAME) {
      (c as unknown as Record<string, unknown>).TELEGRAM_BOT_TOKEN = botToken;
    }
  });
```

- [ ] **Step 4: Add IPC handler for setting bot profile photo**

```typescript
  ipcMain.handle('telegram:setBotPhoto', async (_event, agentName: string, botToken: string) => {
    const { getReferenceImages } = await import('./jobs/generate-avatar');
    const { setBotProfilePhoto } = await import('./telegram');
    const refs = getReferenceImages(agentName);
    if (refs.length === 0) return false;
    return setBotProfilePhoto(refs[0], botToken);
  });
```

- [ ] **Step 5: Remove TELEGRAM_GROUP_ID references from app.ts**

Search for `TELEGRAM_GROUP_ID` and remove any reference.

- [ ] **Step 6: Update preload to expose new IPC channels**

In `src/preload/index.ts`, update the type interface and implementations:

```typescript
  // Update existing
  discoverTelegramChatId: (botToken: string, agentName?: string) =>
    ipcRenderer.invoke('telegram:discoverChatId', botToken, agentName),

  // Add new
  saveTelegramBotToken: (agentName: string, botToken: string) =>
    ipcRenderer.invoke('telegram:saveAgentBotToken', agentName, botToken),
  setTelegramBotPhoto: (agentName: string, botToken: string) =>
    ipcRenderer.invoke('telegram:setBotPhoto', agentName, botToken),
```

- [ ] **Step 7: Run type check**

Run: `npx tsc --noEmit`
Expected: Clean or close to clean

- [ ] **Step 8: Commit**

```bash
git add src/main/app.ts src/preload/index.ts
git commit -m "feat: IPC handlers for per-agent telegram config"
```

---

### Task 5: Settings UI - per-agent telegram config

**Files:**
- Modify: `src/renderer/components/Settings.svelte`

- [ ] **Step 1: Read the Settings.svelte agent list section**

Find the agent list rendering (where mute/enable toggles are). This is where per-agent telegram config goes.

- [ ] **Step 2: Add per-agent telegram state**

Add reactive state for per-agent telegram editing:

```typescript
  let agentTelegramEditing = $state<string | null>(null); // agent name being edited
  let agentBotToken = $state('');
  let agentChatId = $state('');
  let agentTelegramDiscovering = $state(false);
  let agentTelegramStatus = $state('');
```

- [ ] **Step 3: Add per-agent telegram UI in agent list**

In each agent row (after the mute/enable controls), add an expandable telegram config section:

```svelte
{#if agentTelegramEditing === agent.name}
  <div class="agent-telegram-config">
    <label class="field">
      <span class="field-label">Bot Token</span>
      <div class="input-eye-wrap">
        <input type="password" bind:value={agentBotToken} class="field-input has-eye" placeholder="Paste from @BotFather" />
      </div>
    </label>
    <label class="field">
      <span class="field-label">Chat ID</span>
      <input type="text" bind:value={agentChatId} class="field-input" placeholder="Auto-detected" readonly />
    </label>
    {#if agentBotToken && !agentChatId}
      <div class="field row">
        <button
          class="daemon-btn"
          disabled={agentTelegramDiscovering}
          onclick={async () => {
            agentTelegramDiscovering = true;
            agentTelegramStatus = 'Send any message to the bot...';
            await api?.saveTelegramBotToken(agent.name, agentBotToken);
            const result = await api?.discoverTelegramChatId(agentBotToken, agent.name);
            agentTelegramDiscovering = false;
            if (result) {
              agentChatId = result.chatId;
              agentTelegramStatus = 'Connected';
              await api?.setTelegramBotPhoto(agent.name, agentBotToken);
            } else {
              agentTelegramStatus = 'Timed out';
            }
          }}
        >
          {agentTelegramDiscovering ? 'Listening...' : 'Auto-detect Chat ID'}
        </button>
        <span class="field-info">{agentTelegramStatus}</span>
      </div>
    {/if}
    {#if agentBotToken && agentChatId}
      <span class="field-info connected">Connected</span>
    {/if}
    <button class="daemon-btn" onclick={async () => {
      if (agentBotToken) await api?.saveTelegramBotToken(agent.name, agentBotToken);
      agentTelegramEditing = null;
    }}>Done</button>
  </div>
{:else}
  <button class="agent-telegram-btn" onclick={() => {
    agentTelegramEditing = agent.name;
    // Load existing values from agent config
    agentBotToken = '';
    agentChatId = '';
    agentTelegramStatus = '';
  }}>
    Telegram {agent.hasTelegram ? '(connected)' : '(not configured)'}
  </button>
{/if}
```

- [ ] **Step 4: Load per-agent telegram status in agent list**

When loading agents, check if each has telegram configured. Add a `hasTelegram` flag to the agent list data by reading the agent manifest.

- [ ] **Step 5: Run type check and visual verify**

Run: `npx tsc --noEmit`
Run the app in dev mode to visually verify the settings UI.

- [ ] **Step 6: Commit**

```bash
git add src/renderer/components/Settings.svelte
git commit -m "feat: per-agent telegram config in settings UI"
```

---

### Task 6: MCP server - per-agent telegram env vars

**Files:**
- Modify: `src/main/inference.ts`

- [ ] **Step 1: Verify MCP config passes per-agent telegram credentials**

In `getMcpConfigPath()`, the memory server env already includes:
```typescript
TELEGRAM_BOT_TOKEN: config.TELEGRAM_BOT_TOKEN || '',
TELEGRAM_CHAT_ID: config.TELEGRAM_CHAT_ID || '',
```

Since `config.TELEGRAM_BOT_TOKEN` now resolves per-agent after `reloadForAgent()`, this should work automatically. Verify by reading the function.

- [ ] **Step 2: Remove TELEGRAM_GROUP_ID from MCP env if present**

Check if `TELEGRAM_GROUP_ID` is passed to any MCP server env. If so, remove it.

- [ ] **Step 3: Run type check**

Run: `npx tsc --noEmit`
Expected: Clean

- [ ] **Step 4: Commit**

```bash
git add src/main/inference.ts
git commit -m "chore: remove TELEGRAM_GROUP_ID from MCP env"
```

---

### Task 7: Fix remaining threadId references

**Files:**
- Modify: various files that still pass threadId to telegram functions

- [ ] **Step 1: Search for all threadId references**

Run: `grep -rn "threadId\|thread_id\|message_thread_id" src/main/ --include="*.ts" | grep -v node_modules | grep -v __tests__`

Fix each reference by removing the threadId parameter.

- [ ] **Step 2: Fix heartbeat.ts**

Remove any threadId usage in delivery helpers.

- [ ] **Step 3: Fix voice-note.ts**

Remove threadId from sendVoiceNote/sendMessage calls if present.

- [ ] **Step 4: Fix any remaining files**

Check run-task.ts, morning-brief.ts, gift.ts, etc.

- [ ] **Step 5: Run type check**

Run: `npx tsc --noEmit`
Expected: Clean

- [ ] **Step 6: Run all tests**

Run: `npx vitest run`
Expected: All pass (update mocks if needed)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: remove threadId from all telegram calls"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run full test suite**

Run: `npx vitest run`
Expected: All tests pass

- [ ] **Step 2: Run type check**

Run: `npx tsc --noEmit`
Expected: Clean

- [ ] **Step 3: Build the app**

Run: `npx electron-vite build`
Expected: Main and preload build succeed

- [ ] **Step 4: Search for any remaining TELEGRAM_GROUP_ID references**

Run: `grep -rn "TELEGRAM_GROUP_ID\|group_id\|topic_map\|createForumTopic\|ensureTopics\|message_thread_id" src/ --include="*.ts"`
Expected: No matches

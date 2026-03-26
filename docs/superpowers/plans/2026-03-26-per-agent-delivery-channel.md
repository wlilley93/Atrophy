# Per-Agent Delivery Channel Mode - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route cron job output to desktop, telegram, or both based on a per-agent `notify_via` setting.

**Architecture:** Add `NOTIFY_VIA` config field (auto/telegram/both), implement routing logic in the telegram daemon's cron handler, add a desktop delivery path that sends cron responses through the renderer, and expose a dropdown per agent in Settings.

**Tech Stack:** TypeScript, Svelte 5 (runes), Electron IPC

**Spec:** `docs/specs/decisions/2026-03-26-per-agent-delivery-channel-mode.md`

---

### Task 1: Add `NOTIFY_VIA` to config

**Files:**
- Modify: `src/main/config.ts:519-524` (field declaration)
- Modify: `src/main/config.ts:619-622` (constructor defaults)
- Modify: `src/main/config.ts:700-705` (agent manifest loading)
- Modify: `src/main/config.ts:886-891` (AGENT_KEY_ROOT mapping)

- [ ] **Step 1: Add the field declaration**

In `src/main/config.ts`, after the `TELEGRAM_DM_CHAT_ID: string;` declaration (line 523), add:

```typescript
  NOTIFY_VIA: string; // 'auto' | 'telegram' | 'both'
```

- [ ] **Step 2: Add the constructor default**

After `this.TELEGRAM_DM_CHAT_ID = '';` (line 622), add:

```typescript
    this.NOTIFY_VIA = 'auto';
```

- [ ] **Step 3: Populate from agent manifest**

After the `TELEGRAM_DM_CHAT_ID` assignment (line 704-705), add:

```typescript
    this.NOTIFY_VIA =
      (_agentManifest.notify_via as string) || 'auto';
```

- [ ] **Step 4: Add to AGENT_KEY_ROOT**

After the `TELEGRAM_DM_CHAT_ID` entry (line 890), add:

```typescript
  NOTIFY_VIA: 'notify_via',
```

- [ ] **Step 5: Verify build**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit 2>&1 | grep NOTIFY_VIA | head -5`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/main/config.ts
git commit -m "feat(config): add NOTIFY_VIA field for per-agent delivery channel mode"
```

---

### Task 2: Add routing logic to cron dispatch in telegram daemon

**Files:**
- Modify: `src/main/channels/telegram/daemon.ts:1295-1366` (cron dispatch logic in registerAgentSwitchboard callback)

This is the core change. The cron dispatch section (lines 1307-1366) currently always sends to Telegram. We need to check `notify_via` + user status to decide where to send.

- [ ] **Step 1: Add status import**

At the top of `daemon.ts`, add `getStatus` to the existing imports or add a new import:

```typescript
import { getStatus } from '../../status';
```

Check if it's already imported. If not, add it after the existing imports.

- [ ] **Step 2: Add `getAgentManifest` import check**

Verify `getAgentManifest` is already imported from `../../agent-manager`. It should be (used at line 1361).

- [ ] **Step 3: Replace the cron response section**

Find the cron response section (lines 1357-1371):

```typescript
    // For cron dispatches with meaningful responses, send to Telegram.
    // dispatchToAgent only sends via edit for Telegram-origin messages
    // (where msgId exists). For cron, we need to explicitly send.
    if (isCron && response) {
      const manifest = getAgentManifest(agent.name);
      const emoji = (manifest.telegram_emoji as string) || '';
      const display = (manifest.display_name as string) || agent.name;
      const header = emoji ? `${emoji} *${display}*\n\n` : '';
      await sendMessage(`${header}${response}`, chatId, false, botToken);
      log.info(`[${agent.name}] Cron response sent to Telegram (${response.length} chars)`);
    } else if (response) {
      log.info(`[${agent.name}] Responded via switchboard (${response.length} chars)`);
    } else if (!isCron) {
      log.error(`[${agent.name}] No response after retry - message dropped`);
    }
```

Replace with:

```typescript
    // Route cron responses based on per-agent notify_via setting.
    // Non-cron responses (Telegram user messages) always reply on Telegram.
    if (isCron && response) {
      const config = getConfig();
      config.reloadForAgent(agent.name);
      const notifyVia = config.NOTIFY_VIA || 'auto';
      const userStatus = getStatus();
      const isActive = userStatus.status === 'active';

      const sendToTelegram = notifyVia === 'telegram'
        || notifyVia === 'both'
        || (notifyVia === 'auto' && !isActive);
      const sendToDesktop = notifyVia === 'both'
        || (notifyVia === 'auto' && isActive);

      const manifest = getAgentManifest(agent.name);
      const emoji = (manifest.telegram_emoji as string) || '';
      const display = (manifest.display_name as string) || agent.name;

      if (sendToTelegram) {
        const header = emoji ? `${emoji} *${display}*\n\n` : '';
        await sendMessage(`${header}${response}`, chatId, false, botToken);
        log.info(`[${agent.name}] Cron response sent to Telegram (${response.length} chars)`);
      }

      if (sendToDesktop) {
        const win = _getMainWindow?.();
        if (win) {
          win.webContents.send('cron:desktopDelivery', {
            agent: agent.name,
            displayName: display,
            emoji,
            text: response,
          });
          log.info(`[${agent.name}] Cron response sent to desktop (${response.length} chars)`);
        } else if (notifyVia === 'both') {
          // Desktop not available but mode is 'both' - fall back to Telegram
          if (!sendToTelegram) {
            const header = emoji ? `${emoji} *${display}*\n\n` : '';
            await sendMessage(`${header}${response}`, chatId, false, botToken);
            log.info(`[${agent.name}] Desktop unavailable - fell back to Telegram`);
          }
        }
      }
    } else if (response) {
      log.info(`[${agent.name}] Responded via switchboard (${response.length} chars)`);
    } else if (!isCron) {
      log.error(`[${agent.name}] No response after retry - message dropped`);
    }
```

- [ ] **Step 4: Add `_getMainWindow` reference**

The daemon needs access to the main window to send IPC events to the renderer. Find where the daemon stores references (near the top of the file). Add a module-level variable and a setter:

Check if a `_getMainWindow` or similar accessor already exists. If not, add near the top of the file (after the existing module-level variables):

```typescript
let _getMainWindow: (() => Electron.BrowserWindow | null) | null = null;

export function setMainWindowAccessor(fn: () => Electron.BrowserWindow | null): void {
  _getMainWindow = fn;
}
```

Then in `src/main/app.ts`, after calling `startDaemon()`, add:

```typescript
import { setMainWindowAccessor } from './channels/telegram';
// ... in the boot function, after startDaemon():
setMainWindowAccessor(() => mainWindow);
```

Check if `setMainWindowAccessor` is already exported from `./channels/telegram/index.ts` barrel. If not, add it.

- [ ] **Step 5: Add `cron:desktopDelivery` to preload allowlist**

In `src/preload/index.ts`, find the `ALLOWED_CHANNELS` set and add:

```typescript
'cron:desktopDelivery',
```

- [ ] **Step 6: Verify build**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit 2>&1 | grep -i "notify\|cron:desktop\|getMainWindow" | head -10`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add src/main/channels/telegram/daemon.ts src/main/channels/telegram/index.ts src/main/app.ts src/preload/index.ts
git commit -m "feat(telegram): route cron output based on per-agent notify_via setting"
```

---

### Task 3: Handle desktop delivery in Window.svelte

**Files:**
- Modify: `src/renderer/components/Window.svelte` (add listener for `cron:desktopDelivery`)

When a `cron:desktopDelivery` event arrives, we need to show the cron response in the transcript and optionally trigger TTS.

- [ ] **Step 1: Add listener for cron desktop delivery**

In Window.svelte, in the `onMount` block where other IPC listeners are registered (near line 840-855), add:

```typescript
      // Desktop delivery of cron job output (when notify_via is 'auto'+active or 'both')
      ipcCleanups.push(api.on('cron:desktopDelivery', (data: {
        agent: string;
        displayName: string;
        emoji: string;
        text: string;
      }) => {
        // Add a divider so the user knows this is from a scheduled job
        addDivider(`${data.emoji} ${data.displayName} - scheduled update`);
        // Add the response as an agent message
        const msg = addMessage('agent', data.text);
        msg.complete = true;
        msg.revealed = msg.content.length;
      }));
```

- [ ] **Step 2: Ensure imports**

Verify that `addDivider` and `addMessage` are imported from the transcript store. They should be (already used in Window.svelte).

- [ ] **Step 3: Verify build**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit 2>&1 | grep "Window.svelte" | head -5`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/renderer/components/Window.svelte
git commit -m "feat(ui): show cron desktop delivery in transcript with divider"
```

---

### Task 4: Add delivery mode dropdown to SettingsTab

**Files:**
- Modify: `src/renderer/components/settings/SettingsTab.svelte` (agent list section)

- [ ] **Step 1: Add state for tracking per-agent notify_via**

In the SettingsTab script section, near the top where other local state is defined, add:

```typescript
  let agentNotifyVia = $state<Record<string, string>>({});
```

- [ ] **Step 2: Load notify_via values on mount**

In the SettingsTab, there should be an initialization block or the parent loads config. The agent list comes from props. We need to load each agent's notify_via. Add a function:

```typescript
  async function loadAgentNotifyVia() {
    if (!api) return;
    const map: Record<string, string> = {};
    for (const agent of agentList) {
      try {
        const cfg = await api.getAgentConfig(agent.name);
        map[agent.name] = cfg?.notifyVia || 'auto';
      } catch {
        map[agent.name] = 'auto';
      }
    }
    agentNotifyVia = map;
  }
```

Call this in the component's initialization (e.g., in an `$effect` that watches `agentList`):

```typescript
  $effect(() => {
    if (agentList.length > 0) loadAgentNotifyVia();
  });
```

- [ ] **Step 3: Add save function for notify_via**

```typescript
  async function updateNotifyVia(agentName: string, value: string) {
    agentNotifyVia[agentName] = value;
    await api?.updateAgentConfig(agentName, { NOTIFY_VIA: value });
  }
```

- [ ] **Step 4: Add dropdown to agent row template**

In the template, find the agent row section (around line 186 `<div class="agent-actions">`). Add the dropdown before the existing buttons:

```svelte
            <select
              class="notify-via-select"
              value={agentNotifyVia[agent.name] || 'auto'}
              onchange={(e) => updateNotifyVia(agent.name, e.currentTarget.value)}
            >
              <option value="auto">Auto</option>
              <option value="telegram">Telegram</option>
              <option value="both">Both</option>
            </select>
```

- [ ] **Step 5: Add CSS for the dropdown**

In the `<style>` section, add:

```css
  .notify-via-select {
    height: 24px;
    padding: 0 6px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 4px;
    color: rgba(255, 255, 255, 0.6);
    font-size: 11px;
    outline: none;
    -webkit-appearance: none;
    appearance: none;
    cursor: pointer;
  }

  .notify-via-select:focus {
    border-color: rgba(255, 255, 255, 0.25);
  }

  .notify-via-select option {
    background: rgb(30, 30, 35);
    color: rgba(255, 255, 255, 0.85);
  }
```

- [ ] **Step 6: Verify `getAgentConfig` and `updateAgentConfig` exist in preload**

Check that these API methods exist. If `getAgentConfig` doesn't exist, use the existing `getTelegramAgentConfig` pattern or add a new IPC handler. If `updateAgentConfig` doesn't exist, use the existing `saveAgentConfig` via `api.updateConfig` with the agent name.

Check: `grep -n "getAgentConfig\|updateAgentConfig" src/preload/index.ts`

If these don't exist, the simplest approach is to use the existing `saveAgentSetting` or similar. Alternatively, add:

In preload interface:
```typescript
  updateAgentConfig: (agentName: string, updates: Record<string, unknown>) => Promise<void>;
```

In preload implementation:
```typescript
  updateAgentConfig: (agentName, updates) => ipcRenderer.invoke('agent:updateConfig', agentName, updates),
```

In `src/main/ipc/agents.ts`, add handler:
```typescript
  ipcMain.handle('agent:updateConfig', (_event, agentName: string, updates: Record<string, unknown>) => {
    saveAgentConfig(agentName, updates);
  });
```

- [ ] **Step 7: Verify build**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit 2>&1 | grep "SettingsTab" | head -5`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
git add src/renderer/components/settings/SettingsTab.svelte src/preload/index.ts src/main/ipc/agents.ts
git commit -m "feat(settings): add per-agent delivery mode dropdown (auto/telegram/both)"
```

---

### Task 5: Verify full build and test

**Files:** None (verification only)

- [ ] **Step 1: Full build check**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit`
Expected: Clean build (no new errors)

- [ ] **Step 2: Manual test plan**

Test steps when the app is running:
1. Open Settings - verify each agent has a delivery dropdown showing "Auto"
2. Change Montgomery to "Both" - verify it saves (check agent.json for `notify_via: "both"`)
3. Mark yourself as active, trigger a cron job - verify output appears in the desktop transcript
4. Mark yourself as away, trigger a cron job - verify output goes to Telegram only
5. Set an agent to "Both", trigger a cron job - verify output appears in both desktop and Telegram
6. Set an agent to "Telegram", trigger a cron job - verify output only goes to Telegram regardless of status

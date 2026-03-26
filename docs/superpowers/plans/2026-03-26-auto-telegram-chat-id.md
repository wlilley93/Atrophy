# Auto Telegram Chat ID Management - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically update an agent's active Telegram chat ID when its bot is added to or removed from a group.

**Architecture:** Add `my_chat_member` to `getUpdates` polling. When membership changes, persist the new active chat ID to the agent manifest and mutate it in-memory. A new `telegram_dm_chat_id` field preserves the original 1:1 fallback.

**Tech Stack:** TypeScript, Telegram Bot API (`my_chat_member` update type)

**Spec:** `docs/specs/decisions/2026-03-26-auto-telegram-chat-id-management.md`

---

### Task 1: Add `TELEGRAM_DM_CHAT_ID` to config

**Files:**
- Modify: `src/main/config.ts:519-522` (field declaration)
- Modify: `src/main/config.ts:619-620` (constructor defaults)
- Modify: `src/main/config.ts:696-701` (agent manifest loading)
- Modify: `src/main/config.ts:877-886` (AGENT_KEY_ROOT mapping)

- [ ] **Step 1: Add the field declaration**

In `src/main/config.ts`, after the `TELEGRAM_CHAT_ID` declaration (line 522), add:

```typescript
  TELEGRAM_DM_CHAT_ID: string;
```

- [ ] **Step 2: Add the constructor default**

In the constructor defaults block, after `this.TELEGRAM_CHAT_ID = '';` (line 620), add:

```typescript
    this.TELEGRAM_DM_CHAT_ID = '';
```

- [ ] **Step 3: Populate from agent manifest**

In `reloadForAgent()`, after the `TELEGRAM_CHAT_ID` assignment (line 700-701), add:

```typescript
    this.TELEGRAM_DM_CHAT_ID =
      (_agentManifest.telegram_dm_chat_id as string) || '';
```

- [ ] **Step 4: Add to AGENT_KEY_ROOT**

In the `AGENT_KEY_ROOT` mapping, after the `TELEGRAM_CHAT_ID` entry (line 885), add:

```typescript
  TELEGRAM_DM_CHAT_ID: 'telegram_dm_chat_id',
```

- [ ] **Step 5: Verify build**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors related to `TELEGRAM_DM_CHAT_ID`

- [ ] **Step 6: Commit**

```bash
git add src/main/config.ts
git commit -m "feat(config): add TELEGRAM_DM_CHAT_ID field for group chat fallback"
```

---

### Task 2: Handle `my_chat_member` updates in polling

**Files:**
- Modify: `src/main/channels/telegram/daemon.ts:920-942` (pollAgent getUpdates call and type)
- Modify: `src/main/channels/telegram/daemon.ts:946-950` (update processing loop)

- [ ] **Step 1: Add `my_chat_member` to allowed_updates**

In `pollAgent()`, change line 923 from:

```typescript
      allowed_updates: ['message'],
```

to:

```typescript
      allowed_updates: ['message', 'my_chat_member'],
```

- [ ] **Step 2: Expand the update type**

Replace the type cast on lines 930-942:

```typescript
  const result = Array.isArray(raw) ? raw as {
    update_id: number;
    message?: {
      text?: string;
      caption?: string;
      from?: { id: number; is_bot?: boolean };
      chat?: { id: number };
      photo?: { file_id: string; file_unique_id: string; width: number; height: number; file_size?: number }[];
      voice?: { file_id: string; duration: number; mime_type?: string; file_size?: number };
      document?: { file_id: string; file_name?: string; mime_type?: string; file_size?: number };
      video?: { file_id: string; duration: number; width: number; height: number; mime_type?: string; file_size?: number };
    };
  }[] : null;
```

with:

```typescript
  const result = Array.isArray(raw) ? raw as {
    update_id: number;
    message?: {
      text?: string;
      caption?: string;
      from?: { id: number; is_bot?: boolean };
      chat?: { id: number; type?: string };
      photo?: { file_id: string; file_unique_id: string; width: number; height: number; file_size?: number }[];
      voice?: { file_id: string; duration: number; mime_type?: string; file_size?: number };
      document?: { file_id: string; file_name?: string; mime_type?: string; file_size?: number };
      video?: { file_id: string; duration: number; width: number; height: number; mime_type?: string; file_size?: number };
    };
    my_chat_member?: {
      chat: { id: number; type: string; title?: string };
      new_chat_member: { status: string };
      old_chat_member: { status: string };
    };
  }[] : null;
```

Note: also added `type?: string` to `message.chat` - it was missing.

- [ ] **Step 3: Handle membership updates before the message loop**

In the `for (const update of result)` loop, after advancing `last_update_id` (line 947) and before the `const msg = update.message;` line (line 949), add:

```typescript
    // Handle bot membership changes (added/removed from groups)
    if (update.my_chat_member) {
      await handleMembershipChange(agent, update.my_chat_member);
      continue;
    }
```

- [ ] **Step 4: Verify build**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit 2>&1 | head -20`
Expected: Error about `handleMembershipChange` not existing (expected - we'll add it in Task 3)

- [ ] **Step 5: Commit**

```bash
git add src/main/channels/telegram/daemon.ts
git commit -m "feat(telegram): poll for my_chat_member updates alongside messages"
```

---

### Task 3: Implement `handleMembershipChange()`

**Files:**
- Modify: `src/main/channels/telegram/daemon.ts` (new function + import)

- [ ] **Step 1: Add `saveAgentConfig` to imports**

At the top of `daemon.ts`, in the import from `../../config` (line 21), add `saveAgentConfig`:

```typescript
import { getConfig, USER_DATA, BUNDLE_ROOT, saveAgentConfig } from '../../config';
```

- [ ] **Step 2: Add the `handleMembershipChange` function**

Add this function above `pollAgent()` (before line 912), after the dedup helpers section:

```typescript
// ---------------------------------------------------------------------------
// Group membership tracking
// ---------------------------------------------------------------------------

/**
 * Handle my_chat_member updates - bot added/removed from groups.
 *
 * When added to a group: save DM as fallback, switch active chat to group.
 * When removed: revert to DM fallback.
 */
async function handleMembershipChange(
  agent: TelegramAgent,
  member: {
    chat: { id: number; type: string; title?: string };
    new_chat_member: { status: string };
    old_chat_member: { status: string };
  },
): Promise<void> {
  const chatType = member.chat.type;
  const newStatus = member.new_chat_member.status;
  const groupChatId = String(member.chat.id);
  const groupTitle = member.chat.title || 'group';

  const isGroup = chatType === 'group' || chatType === 'supergroup';
  const isAdded = newStatus === 'member' || newStatus === 'administrator';
  const isRemoved = newStatus === 'left' || newStatus === 'kicked';

  if (isGroup && isAdded) {
    // Save the current chat ID as DM fallback (only if not already saved)
    const config = getConfig();
    config.reloadForAgent(agent.name);
    const existingDm = config.TELEGRAM_DM_CHAT_ID;

    if (!existingDm) {
      saveAgentConfig(agent.name, { TELEGRAM_DM_CHAT_ID: agent.chatId });
    }

    // Switch active chat to the group
    saveAgentConfig(agent.name, { TELEGRAM_CHAT_ID: groupChatId });
    agent.chatId = groupChatId;

    log.info(`[${agent.name}] Joined ${groupTitle} (${groupChatId}) - switched active chat`);

    // Send greeting to the group
    const prefix = agent.emoji ? `${agent.emoji} ` : '';
    await sendMessage(
      `${prefix}*${agent.display_name}* is now active in this group.`,
      groupChatId,
      false,
      agent.botToken,
    );

  } else if (isRemoved) {
    // Revert to DM fallback
    const config = getConfig();
    config.reloadForAgent(agent.name);
    const dmChatId = config.TELEGRAM_DM_CHAT_ID;

    if (dmChatId) {
      saveAgentConfig(agent.name, { TELEGRAM_CHAT_ID: dmChatId });
      agent.chatId = dmChatId;

      log.info(`[${agent.name}] Removed from ${groupTitle} - reverted to DM (${dmChatId})`);

      // Notify in the DM
      const prefix = agent.emoji ? `${agent.emoji} ` : '';
      await sendMessage(
        `${prefix}*${agent.display_name}* removed from _${groupTitle}_. Back to this chat.`,
        dmChatId,
        false,
        agent.botToken,
      );
    } else {
      log.warn(`[${agent.name}] Removed from ${groupTitle} but no DM fallback configured`);
    }
  }
}
```

- [ ] **Step 3: Verify build**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/main/channels/telegram/daemon.ts
git commit -m "feat(telegram): auto-switch chat ID on group add/remove"
```

---

### Task 4: Backfill DM chat ID for existing agents

**Files:**
- Modify: `src/main/channels/telegram/daemon.ts` (inside `discoverTelegramAgents()`)

Existing agents already have a `telegram_chat_id` but no `telegram_dm_chat_id`. We need to backfill the DM ID during discovery so the fallback works if they're later added to a group.

- [ ] **Step 1: Add backfill logic to `discoverTelegramAgents()`**

In `discoverTelegramAgents()`, after reading `botToken` and `chatId` (lines 389-390), and after the `if (!botToken || !chatId) continue;` guard (line 392), add:

```typescript
      // Backfill DM chat ID for agents that predate the group feature.
      // If telegram_dm_chat_id is empty, the current chat_id is the DM.
      const dmChatId = config.TELEGRAM_DM_CHAT_ID;
      if (!dmChatId && chatId) {
        saveAgentConfig(agent.name, { TELEGRAM_DM_CHAT_ID: chatId });
      }
```

- [ ] **Step 2: Verify build**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/main/channels/telegram/daemon.ts
git commit -m "feat(telegram): backfill dm_chat_id for existing agents on discovery"
```

---

### Task 5: Manual test and final commit

**Files:** None (verification only)

- [ ] **Step 1: Verify the full build compiles**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit`
Expected: Clean build, no errors

- [ ] **Step 2: Verify agent.json is unchanged on disk**

Run: `cat ~/.atrophy/agents/companion/data/agent.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('chat_id:', d.get('telegram_chat_id','MISSING')); print('dm_id:', d.get('telegram_dm_chat_id','MISSING'))"`
Expected: `chat_id` has current value, `dm_id` is `MISSING` (backfill happens at daemon start, not before)

- [ ] **Step 3: Document the test plan**

Manual test steps (to run when the app is launched):
1. Start the app - verify daemon logs show agents discovered
2. Check `~/.atrophy/agents/companion/data/agent.json` - `telegram_dm_chat_id` should now be backfilled
3. Add companion bot to a test group - verify greeting appears in the group
4. Send a message in the group - verify the agent responds
5. Remove the bot from the group - verify DM notification appears
6. Send a DM to the bot - verify it responds in the DM again

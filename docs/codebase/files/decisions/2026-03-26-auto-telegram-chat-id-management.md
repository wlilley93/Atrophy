# Auto Telegram Chat ID Management

**Date:** 2026-03-26  
**Status:** Implemented

## Overview

Agents can now automatically detect when they are added to or removed from Telegram groups, updating their active chat ID without manual configuration. All tier 1 agents can operate in group contexts with zero manual config.

## Architecture

### Manifest-Centric Design

The agent manifest (`agent.json`) is the single source of truth:
- `telegram_chat_id` - **Active** chat (group or DM)
- `telegram_dm_chat_id` - Preserved 1:1 DM fallback

Everything that reads the manifest (cron jobs, server, switchboard, MCP config) automatically routes to the correct chat with zero changes.

### Detection Mechanism

Telegram sends `my_chat_member` updates when the bot's membership status changes. The daemon polls for these updates alongside regular messages.

**Update shape:**
```typescript
{
  update_id: number;
  my_chat_member: {
    chat: { id: number; type: string; title?: string };
    from: { id: number; first_name?: string };
    old_chat_member: { status: string };
    new_chat_member: { status: string };
  };
}
```

**Status transitions:**
- **Added:** `new_chat_member.status` is `"member"` or `"administrator"` AND `chat.type` is `"group"` or `"supergroup"`
- **Removed:** `new_chat_member.status` is `"left"` or `"kicked"`

## State Transitions

### Added to Group

1. If `telegram_dm_chat_id` not set, save current `telegram_chat_id` as `telegram_dm_chat_id`
2. Update `telegram_chat_id` to group's chat ID via `saveAgentConfig()`
3. Mutate `agent.chatId` in-memory for immediate use
4. Send greeting: `"{emoji} {display_name} is now active in this group."`
5. Log transition

### Removed from Group

1. Read `telegram_dm_chat_id` from manifest
2. Update `telegram_chat_id` back to DM value
3. Mutate `agent.chatId` in-memory
4. Send DM: `"I've been removed from {group title}. Back to this chat."`
5. Log transition

### Second Group Override

If already in a group and added to another:
- New group becomes primary
- First group is NOT tracked
- On removal from second group, revert to DM
- User must re-add bot to desired group

## Implementation

### Files Changed

#### `src/main/channels/telegram/daemon.ts`

```typescript
// Add 'my_chat_member' to allowed_updates
const allowedUpdates = ['message', 'my_chat_member'];

// Handle membership changes
function handleMembershipChange(agent: AgentConfig, update: Update): void {
  const memberChange = update.my_chat_member!;
  const newStatus = memberChange.new_chat_member.status;
  const chatType = memberChange.chat.type;
  
  if (chatType === 'group' || chatType === 'supergroup') {
    if (newStatus === 'member' || newStatus === 'administrator') {
      // Added to group
      if (!agent.telegramDmChatId) {
        agent.telegramDmChatId = agent.chatId;
      }
      agent.chatId = memberChange.chat.id;
      saveAgentConfig(agent.name, { 
        TELEGRAM_CHAT_ID: String(agent.chatId),
        TELEGRAM_DM_CHAT_ID: String(agent.telegramDmChatId),
      });
      sendGreeting(agent);
    } else if (newStatus === 'left' || newStatus === 'kicked') {
      // Removed from group
      if (agent.telegramDmChatId) {
        agent.chatId = agent.telegramDmChatId;
        saveAgentConfig(agent.name, { TELEGRAM_CHAT_ID: String(agent.chatId) });
        sendRevertNotification(agent, memberChange.chat.title);
      }
    }
  }
}
```

#### `src/main/config.ts`

```typescript
// Config class additions
TELEGRAM_DM_CHAT_ID: string;  // Preserved 1:1 DM fallback

// In reloadForAgent()
this.TELEGRAM_DM_CHAT_ID = (_agentManifest.telegram_dm_chat_id as string) || '';

// In saveAgentConfig() key mapping
const AGENT_KEY_ROOT: Record<string, string> = {
  // ...
  'TELEGRAM_DM_CHAT_ID': 'telegram_dm_chat_id',
};
```

#### `scripts/agents/shared/credentials.py`

New shared module for credential loading:

```python
def load_telegram_credentials(agent_name: str = "") -> tuple[str, str]:
    """Load Telegram bot token and chat ID from environment.
    
    Tries agent-specific env vars first, then manifest env var references,
    then falls back to generic TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.
    """
    # Try agent-specific env vars (TELEGRAM_BOT_TOKEN_MONTGOMERY)
    # Try manifest env var references (channels.telegram.bot_token_env)
    # Fallback to generic vars
```

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Bot added to group before DM setup | `telegram_dm_chat_id` empty, group becomes primary. If removed, no DM to revert to - agent goes offline until re-added to group or user sends DM |
| Daemon restart while in group | `telegram_chat_id` already group ID, polling continues in group |
| Bot kicked vs left | Both treated identically - revert to DM |
| Bot made admin vs member | Both treated as "added" - no distinction |

## IPC Handlers

New handlers for UI management:

```typescript
// agent:create - Create new agent with org context
ipcMain.handle('agent:create', async (_event, opts) => {
  return createAgent(opts);
});

// agent:delete - Delete agent
ipcMain.handle('agent:delete', async (_event, name) => {
  return deleteAgent(name);
});

// org:list, org:create, org:dissolve - Organization CRUD
// org:addAgent, org:removeAgent - Agent-org membership
```

## See Also

- [`src/main/channels/telegram/daemon.ts`](files/src/main/channels/telegram/daemon.md) - Telegram daemon implementation
- [`src/main/config.ts`](files/src/main/config.md) - Configuration system
- [`scripts/agents/shared/credentials.py`](files/scripts/agents/shared/credentials.md) - Credential loading

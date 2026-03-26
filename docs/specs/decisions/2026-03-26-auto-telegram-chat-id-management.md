# Auto Telegram Chat ID Management

**Date:** 2026-03-26
**Status:** Approved

## Problem

When a bot is added to a Telegram group, its `telegram_chat_id` must be manually reconfigured. There is no automatic detection of group membership changes. All tier 1 agents should be capable of operating in a group context with zero manual config.

## Requirements

1. When a bot is added to a group, automatically update its active chat ID to that group
2. When removed from a group, revert to the original 1:1 DM chat ID
3. If added to a second group while already in one, the second group becomes primary
4. If removed from the second group, revert to 1:1 DM (not back to first group)
5. Send a greeting in the group when joining
6. Send a DM notification when reverting to 1:1

## Approach: Manifest-centric

The agent manifest (`agent.json`) is the single source of truth. `telegram_chat_id` always reflects the **active** chat (group or DM). A new field `telegram_dm_chat_id` preserves the original 1:1 fallback.

This means everything that reads the manifest - cron jobs, server, switchboard, MCP config - automatically routes to the correct chat with zero changes.

## Detection

Add `my_chat_member` to `allowed_updates` in `pollAgent()`'s `getUpdates` call. Telegram sends this update type when the bot's membership status changes in any chat.

The `my_chat_member` update shape:

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

Relevant status transitions:
- **Added:** `new_chat_member.status` is `"member"` or `"administrator"` AND `chat.type` is `"group"` or `"supergroup"`
- **Removed:** `new_chat_member.status` is `"left"` or `"kicked"`

## State Transitions

### Added to group

1. If `telegram_dm_chat_id` is not already set in the manifest, save the current `telegram_chat_id` as `telegram_dm_chat_id` (preserves the original DM across multiple group switches)
2. Update `telegram_chat_id` in the manifest to the group's chat ID via `saveAgentConfig()`
3. Mutate `agent.chatId` in-memory so the poller immediately uses the new ID
4. Send greeting to the group: `"{emoji} {display_name} is now active in this group."`
5. Log the transition

### Removed from group

1. Read `telegram_dm_chat_id` from the manifest
2. Update `telegram_chat_id` back to the DM value via `saveAgentConfig()`
3. Mutate `agent.chatId` in-memory
4. Send a message to the DM: `"I've been removed from {group title}. Back to this chat."`
5. Log the transition

### Second group override

If already in a group and added to another, the new group becomes primary. The first group is not tracked. On removal from the second group, revert to DM. The user must re-add the bot to whichever group they want.

## Files Changed

### `src/main/channels/telegram/daemon.ts`

- Add `'my_chat_member'` to the `allowed_updates` array in `pollAgent()`
- Expand the update type in `pollAgent()` to include the `my_chat_member` shape
- Add `handleMembershipChange(agent, update)` function:
  - Determines if added or removed
  - Calls `saveAgentConfig()` to persist chat ID changes
  - Mutates `agent.chatId` in-memory
  - Sends greeting or revert notification
- Call `handleMembershipChange()` in the poll loop before the message loop
- Reload config after chat ID change so subsequent dispatches use the new ID

### `src/main/config.ts`

- Add `TELEGRAM_DM_CHAT_ID: string` field to `Config` class
- Initialize to `''` in constructor defaults
- Populate from `_agentManifest.telegram_dm_chat_id` in `reloadForAgent()`
- Add `'telegram_dm_chat_id'` to `AGENT_KEY_ROOT` mapping so `saveAgentConfig()` writes it correctly

### No changes needed

- `api.ts` - all send functions already accept explicit `chatId` parameter
- `discoverTelegramAgents()` - reads `telegram_chat_id` from config, works whether it's a group or DM
- Switchboard routing - uses whatever `chatId` the agent has
- Cron job notifications - read from manifest, automatically route to group
- Setup wizard `discoverChatId()` - still captures the 1:1 DM as before
- Agent manifests - no structural changes, just two fields that get written at runtime

## Edge Cases

- **Bot added to group before DM setup:** `telegram_dm_chat_id` would be empty. The group becomes primary. If removed, there's no DM to revert to - log a warning, keep `telegram_chat_id` unchanged (the now-inactive group ID), and skip the DM notification. The agent effectively goes offline on Telegram until the user either re-adds it to a group or sends a DM (which would be captured by `discoverChatId()` in settings).
- **Daemon restart while in group:** `telegram_chat_id` in manifest is already the group ID. `discoverTelegramAgents()` picks it up. Polling continues in the group. `telegram_dm_chat_id` is preserved in the manifest for future revert.
- **Bot kicked vs left:** Both treated identically - revert to DM.
- **Bot made admin vs member:** Both treated as "added" - no distinction needed.

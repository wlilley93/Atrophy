# Per-Agent Telegram Bots

## Goal

Replace the single-bot Topics architecture with per-agent Telegram bots. Each agent gets its own BotFather-created bot with its own profile picture (set from the agent's reference image), creating the experience of multiple friends messaging independently in separate chats - like WhatsApp.

## Architecture

### Data Model

`agent.json` gets two new optional fields:

```json
{
  "telegram_bot_token": "123:ABC...",
  "telegram_chat_id": "987654321"
}
```

If absent, the agent falls back to the global `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` from env vars or `~/.atrophy/config.json`. Xan uses the global credentials. Agents without any telegram config (no per-agent and no global) are skipped by the daemon.

### Config Resolution

`config.ts` already has three-tier resolution (env -> config.json -> agent.json -> defaults). Per-agent telegram fields are added to the agent.json tier. `reloadForAgent(name)` picks up the per-agent values when switching context. Resolution order for `TELEGRAM_BOT_TOKEN`:

1. `agents/<name>/data/agent.json` -> `telegram_bot_token` (per-agent)
2. `process.env.TELEGRAM_BOT_TOKEN` (global env)
3. `~/.atrophy/config.json` -> `TELEGRAM_BOT_TOKEN` (global config)
4. Empty string (not configured)

Same for `TELEGRAM_CHAT_ID`.

### Daemon - Parallel Independent Pollers

The current single-poller/Topics daemon is replaced with parallel independent pollers - one per agent that has telegram credentials.

**Startup:**
1. Discover all enabled agents
2. For each agent with `telegram_bot_token` + `telegram_chat_id`: spawn an async poller
3. Each poller has its own `getUpdates` offset, stored in per-agent state
4. Poll intervals have random jitter (8-15 seconds) so responses feel organic

**Per-agent poller loop:**
1. Call `getUpdates` with the agent's bot token (30s long poll)
2. Filter messages from the configured `telegram_chat_id` only
3. Dispatch directly to the agent (no routing - the bot IS the agent)
4. Stream response back via `editMessage` (same streaming as current)
5. Wait random jitter before next poll

**State persistence:**
```json
// ~/.atrophy/.telegram_daemon_state.json
{
  "agents": {
    "xan": { "last_update_id": 123456 },
    "companion": { "last_update_id": 789012 }
  }
}
```

No more `topic_map`. Each agent's offset is independent.

**Instance locking:** Keep the single lock file. Only one daemon process runs, but it manages multiple pollers internally.

### Bot Profile Pictures

On daemon startup, for each agent with telegram credentials and reference images:
1. Read first image from `avatar/Reference/`
2. Call Telegram's `setMyProfilePhoto` API (multipart upload)
3. Log success/failure, don't block startup

Also triggered when credentials are saved in settings.

### telegram.ts Changes

All API functions already accept `chatId`. Add an optional `botToken` parameter to:
- `post()` (internal helper) - use provided token instead of `config.TELEGRAM_BOT_TOKEN`
- `sendMessage()`, `sendMessageGetId()`, `editMessage()`, `sendPhoto()`, `sendVoiceNote()`, `sendButtons()`, `pollCallback()`

Pattern:
```typescript
async function post(method: string, payload: Record<string, unknown>, timeoutMs?: number, botToken?: string): Promise<unknown | null> {
  const token = botToken || getConfig().TELEGRAM_BOT_TOKEN;
  // ...
}
```

The daemon passes the agent's bot token explicitly. Heartbeat/voice-note jobs use `config.TELEGRAM_BOT_TOKEN` which resolves per-agent after `reloadForAgent()`.

### MCP Server

Already receives `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as env vars in the MCP config. After `reloadForAgent()`, these resolve to per-agent values. The MCP server's `send_telegram` and `ask_user` tools work unchanged.

### Settings UI

**Global section** stays as-is (for Xan / fallback).

**Agent list** - each agent row in the agents section gets expandable telegram config:
- Bot Token (password input with eye toggle)
- Chat ID (text input, auto-detect button)
- Auto-detect: "Send any message to this bot" -> polls for first message -> captures chat ID
- Status pill: "Connected" / "Not configured"

When saving per-agent telegram config:
- Write `telegram_bot_token` and `telegram_chat_id` to `agents/<name>/data/agent.json`
- If daemon is running, restart the relevant poller
- Trigger profile photo update

### Setup Wizard

After AI-driven agent creation (step 2 of the existing wizard flow):

1. "Want to connect [agent name] to Telegram?"
2. If yes:
   a. "Create a bot via @BotFather and paste the token"
   b. Paste token -> save to agent.json
   c. "Now send any message to the bot"
   d. Auto-detect chat ID (same `discoverChatId` flow)
   e. Set bot profile photo from reference image
3. If skip: agent works locally only, configurable later in settings

### What Gets Removed

- `TELEGRAM_GROUP_ID` config field (no more group)
- `createForumTopic()`, `ensureTopics()` in telegram-daemon.ts
- `topic_map` in daemon state
- `message_thread_id` parameter from all telegram.ts functions (threadId)
- Topics mode documentation references

### What Stays

- Global `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (Xan uses these)
- `sendMessage`, `sendPhoto`, `sendVoiceNote`, etc. signatures (minus threadId)
- Instance locking (one daemon process)
- Streaming dispatch with rich display
- All heartbeat/voice-note/selfie delivery logic
- MCP server telegram tools

### File Impact

| File | Change |
|------|--------|
| `src/main/config.ts` | Add per-agent `telegram_bot_token` / `telegram_chat_id` resolution. Remove `TELEGRAM_GROUP_ID`. |
| `src/main/telegram.ts` | Add `botToken` param to `post()` and all public functions. Remove `threadId` param. Add `setBotProfilePhoto()`. |
| `src/main/telegram-daemon.ts` | Rewrite: parallel per-agent pollers, remove Topics mode, per-agent state. |
| `src/main/jobs/heartbeat.ts` | Remove `threadId` usage (already sends to default chat). |
| `src/main/jobs/voice-note.ts` | No change (uses config which resolves per-agent). |
| `src/renderer/components/Settings.svelte` | Add per-agent telegram config in agent list. |
| `src/renderer/components/SetupWizard.svelte` | Add telegram bot setup step for new agents. |
| `src/main/ipc-handlers.ts` | Add handlers for per-agent telegram config save, profile photo update. |
| `src/preload/index.ts` | Expose new IPC channels. |

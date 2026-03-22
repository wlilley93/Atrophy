# Channels

External communication channels beyond the direct conversation interface. The channel system enables the companion to communicate with the user through Telegram, serving as an always-available messaging layer that works independently of the GUI window. This is the primary mechanism for autonomous outreach - heartbeat messages, morning briefs, voice notes, and scheduled task delivery all flow through the Telegram channel.

## Architecture

All channel and routing code lives under `src/main/channels/`:

```
src/main/channels/
  switchboard.ts        # Core routing engine (channel-agnostic)
  agent-router.ts       # Per-agent filter/queue between switchboard and inference
  telegram/             # Telegram channel adapter
    api.ts              # Bot API helpers (send, edit, download, bot commands)
    daemon.ts           # Per-agent polling, dispatch, streaming display
    formatter.ts        # Message formatting, streaming status, tool result display
    index.ts            # Barrel re-exports
```

There are 3 layers:
1. **Switchboard** (channel-agnostic routing) - routes Envelopes between addresses
2. **Channel adapters** (e.g. `telegram/`) - bridge external platforms to/from the switchboard
3. **Agent router** - per-agent filtering between switchboard and inference

To add a new channel: create `channels/<name>/` with api + daemon + index, register with switchboard.

Each agent has its own dedicated Telegram bot - its own token, its own chat, and its own profile photo set from the agent's reference images. The daemon runs parallel per-agent pollers with randomised jitter so activity feels organic rather than mechanical. Per-agent dispatch locks allow agents to dispatch inference in parallel while a narrow config lock protects the shared Config singleton during the brief setup-and-spawn window.

This replaces the previous Topics mode architecture where all agents shared a single bot and a single group with forum threads. The per-agent bot model eliminates group management entirely - no shared group, no topic IDs, no routing logic.

```
Telegram Bot API (one bot per agent)
  |
src/main/channels/telegram/daemon.ts  (parallel per-agent pollers, staggered 10s apart)
  |
discoverTelegramAgents()               (agents with bot token + chat ID configured)
  |
withAgentDispatchLock(name)            (per-agent lock - agents dispatch in parallel)
  |
withConfigLock()                       (narrow lock - config reload + subprocess spawn only)
  |
src/main/channels/telegram/api.ts      (send via agent's own bot token)
```

---

## src/main/channels/telegram/api.ts - Bot API Client

This module implements the Telegram Bot API integration using pure HTTP via `fetch()` (Node built-in undici). There are no third-party Telegram libraries - all API calls are handwritten HTTP requests. This keeps the dependency footprint minimal and gives full control over timeout, error handling, and multipart form construction.

The module provides three layers of functionality: low-level API helpers, message sending/receiving primitives, and high-level convenience methods for common interaction patterns.

All sending and receiving functions accept an optional `botToken` parameter. When provided it overrides the token from config, which allows parallel per-agent pollers to call telegram functions without switching global config state.

### Internal API Helper

The `apiUrl` function constructs Telegram API URLs from the given bot token (or the current config's token as a fallback) and a method name.

```typescript
function apiUrl(method: string, botToken?: string): string
```

The `post` function is the generic POST helper used by all Bot API calls. It handles the complete request lifecycle - checking that the bot token is configured, sending the JSON payload, parsing the response, and returning the result. All calls use a 15-second timeout via `AbortSignal.timeout(15_000)` to prevent the app from hanging on network issues. Errors are logged but never thrown, so callers always get a clean return value (the result object on success, or `null` on failure).

```typescript
async function post(method: string, payload: Record<string, unknown>, botToken?: string): Promise<unknown | null>
```

### Sending

The module provides three sending methods, each handling a different message type. All three support optional emoji-prefixed agent identification and an optional `botToken` override for per-agent bot dispatch.

The `sendMessage` function sends a plain Markdown-formatted text message. When `prefix=true` (the default), it prepends the agent's emoji and display name (e.g. "moon *Xan*") so the recipient knows which agent is speaking.

```typescript
export async function sendMessage(
  text: string,
  chatId?: string,     // defaults to config TELEGRAM_CHAT_ID
  prefix?: boolean,    // defaults to true
  botToken?: string,   // overrides config token for per-agent bots
): Promise<boolean>
```

The `sendMessageGetId` function is identical to `sendMessage` but returns the `message_id` of the sent message rather than a boolean. This is used by the daemon for streaming responses - the ID is needed so the daemon can edit the message in-place as inference output arrives.

```typescript
export async function sendMessageGetId(text: string, chatId?: string, botToken?: string): Promise<number | null>
```

The `editMessage` function edits an existing message's text in-place via the `editMessageText` Bot API method. Input is truncated to 4096 characters (Telegram's per-message limit) before sending. Returns `true` on success or `false` on failure. This is used by the daemon to stream inference output into the initial "Thinking..." placeholder message.

```typescript
export async function editMessage(messageId: number, text: string, chatId?: string, botToken?: string): Promise<boolean>
```

The `sendPhoto` function sends an image file as a Telegram photo message. It reads the file into a `Buffer`, detects the content type from the file extension, and uploads via multipart form data. Supports `.jpg`/`.jpeg`, `.png`, `.gif`, and `.webp`. The optional `prefix` flag prepends the agent's emoji and display name (defaults to `true`).

```typescript
export async function sendPhoto(filePath: string, caption?: string, chatId?: string, prefix?: boolean, botToken?: string): Promise<boolean>
```

This function is used by the `heartbeat` job to deliver selfie images. Multipart form data is built manually (same approach as `sendVoiceNote`) with a 30-second upload timeout.

The `sendButtons` function sends a message with an inline keyboard - rows of tappable buttons that appear below the message. This is used for confirmation prompts (Yes/No) and permission requests. It returns the `message_id` for tracking which message the user responds to.

```typescript
export async function sendButtons(
  text: string,
  buttons: { text: string; callback_data: string }[][],
  chatId?: string,
  prefix?: boolean,
  botToken?: string,
): Promise<number | null>
```

Each inner array represents a row of buttons. The following example creates a single row with two buttons side by side.

```typescript
[[{ text: 'Yes', callback_data: 'yes' }, { text: 'No', callback_data: 'no' }]]
```

The `sendVoiceNote` function sends an audio file as a Telegram voice note. It reads the file into a `Buffer` and determines the correct API method based on the file extension. This distinction matters because Telegram treats voice messages (`.ogg`) differently from audio files in the UI - voice messages get a waveform player, while audio files get a standard media player.

```typescript
export async function sendVoiceNote(
  audioPath: string,
  caption?: string,
  chatId?: string,
  prefix?: boolean,
  botToken?: string,
): Promise<boolean>
```

The function handles the API method selection as follows:

- `.ogg` / `.oga` files: uses `sendVoice` API with field name `voice` and content type `audio/ogg`
- All other files: uses `sendAudio` API with field name `audio` and content type `audio/mpeg`

Multipart form data is built manually using `Buffer.concat()` with a generated boundary string, since the built-in `fetch` does not support `FormData` with file uploads in Node.js. The upload timeout is extended to 30 seconds to accommodate larger audio files. This function is used by the `voice-note.ts` job and the `telegram_voice` delivery method in `run-task.ts`.

### Receiving

The receiving functions use Telegram's long-polling approach rather than webhooks. Long-polling is simpler to set up (no public URL or SSL certificate required) and works behind NATs and firewalls.

The `flushOldUpdates` function consumes all pending updates from the Telegram API without processing them. This is called before any polling operation to ensure the poller only sees fresh messages, preventing stale responses from previous sessions.

```typescript
async function flushOldUpdates(botToken?: string): Promise<void>
```

The `pollCallback` function long-polls for an inline keyboard callback. It polls in 30-second windows until a `callback_query` from the target user (matched by `from.id`) is received. When a callback arrives, it automatically answers the callback query via `answerCallbackQuery` (which removes the loading spinner in the Telegram client). Returns the `callback_data` string or `null` on timeout.

```typescript
export async function pollCallback(
  timeoutSecs?: number,  // default 120
  chatId?: string,
  botToken?: string,
): Promise<string | null>
```

If the API returns null (network error), the function waits 2 seconds before retrying. This prevents tight retry loops during transient network outages.

The `pollReply` function long-polls for a text message reply. It uses the same polling pattern as `pollCallback` but filters for `message` updates instead of `callback_query` updates. Returns the message text or `null` on timeout. Both polling functions match messages by `from.id` to ensure they only accept responses from the correct user.

```typescript
export async function pollReply(
  timeoutSecs?: number,  // default 120
  chatId?: string,
  botToken?: string,
): Promise<string | null>
```

### High-Level Convenience Methods

These methods combine sending and receiving into complete interaction patterns. They handle the full lifecycle of an interactive exchange - flushing stale updates, sending the prompt, and polling for the response.

The `askConfirm` function sends a confirmation prompt with Yes/No buttons and waits for the user to tap one. It flushes old updates first, sends the buttons, and polls for a callback. Returns `true` (yes), `false` (no), or `null` (timeout). This is the standard pattern for permission and confirmation requests from background jobs.

```typescript
export async function askConfirm(
  text: string,
  timeoutSecs?: number,  // default 120
  botToken?: string,
): Promise<boolean | null>
```

The `askQuestion` function sends a question and waits for a free-text reply. It flushes old updates first, sends the message, and polls for a reply. Returns the reply text or `null` on timeout.

```typescript
export async function askQuestion(
  text: string,
  timeoutSecs?: number,  // default 120
  botToken?: string,
): Promise<string | null>
```

### Bot Command Registration

Bot command registration makes agent names appear in Telegram's autocomplete menu. When the user types `/` in the chat, they see a list of all agents with their descriptions, making it easy to address a specific agent.

The `registerBotCommands` function scans all discovered agents via `discoverAgents()` and builds a command list. Each agent gets a `/<agent_name>` command with its description from the manifest (truncated to Telegram's 256-character limit). Two utility commands are appended: `/status` (show active agents) and `/mute` (toggle agent muting). The full list is sent to the Telegram API via `setMyCommands`. An optional `botToken` targets a specific agent's bot.

```typescript
export async function registerBotCommands(botToken?: string): Promise<boolean>
```

The `clearBotCommands` function removes all bot commands via `deleteMyCommands` API. This is used during cleanup or when the agent roster changes significantly.

```typescript
export async function clearBotCommands(botToken?: string): Promise<boolean>
```

### Bot Profile Photo

The `setBotProfilePhoto` function sets the bot's profile photo via the `setMyPhoto` Bot API method. It reads the image file, uploads it as multipart form data, and returns a boolean indicating success. This is called on daemon startup for each agent to set the bot's avatar from the agent's reference image.

```typescript
export async function setBotProfilePhoto(imagePath: string, botToken?: string): Promise<boolean>
```

### Update ID Tracking

Each per-agent poller in the daemon maintains its own `lastUpdateId` in per-agent state. This prevents re-processing old messages after a restart or reconnection. Each poller independently tracks its own offset into the update stream for its bot.

When calling `getUpdates`, the offset is set to `lastUpdateId + 1`, telling the Telegram API to only return updates newer than the last processed one. This is a standard Telegram pattern that ensures exactly-once processing of messages.

### Configuration

Each agent's Telegram configuration comes from its `agent.json` manifest. Each agent has its own bot token and chat ID. Xan (the primary agent) falls back to the global `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` env vars if per-agent fields are not set.

```json
{
  "telegram_bot_token": "7123456789:AAH...",
  "telegram_chat_id": "-1001234567890",
  "telegram_emoji": "\ud83c\udf19"
}
```

The `telegram_bot_token` is the Bot API token from @BotFather for this agent's dedicated bot. The `telegram_chat_id` is the 1:1 chat ID between the user and that bot (auto-detected by the Settings UI after the token is saved). The `telegram_emoji` appears before the agent's name in outgoing messages for visual identification.

### Usage

The Telegram channel is used by multiple components throughout the system. Understanding which components use it helps explain why the channel needs to be robust and handle concurrent access gracefully.

- **Telegram daemon**: Polls each agent's own bot for incoming messages and dispatches to inference - the main incoming message handler
- **`ask_user` MCP tool**: Sends questions during conversation and blocks for a reply - used when the agent needs user input mid-task
- **`send_telegram` MCP tool**: Proactive outreach (rate limited to 5/day) - used for unprompted messages
- **`heartbeat` job**: Evaluates whether to reach out and sends messages, voice notes (`[VOICE_NOTE]`), selfie images (`[SELFIE]` via `sendPhoto()`), and interactive button questions (`[ASK]`) - periodic check-in
- **`gift` job**: Delivers unprompted notes - monthly creative outreach
- **`voice-note` job**: Sends spontaneous voice notes (OGG Opus via `sendVoiceNote()`) - audio-based outreach
- **`run-task` job**: `telegram_voice` delivery method sends task output as voice notes - scheduled task delivery
- **`sendPhoto`**: Used by heartbeat selfie delivery to send image files via the agent's own bot

### Error Handling and Resilience

The `post` function implements several layers of defensive handling beyond the basic timeout.

**Flood control (429 RetryAfter)**: When Telegram returns a 429 rate-limit response, `post` reads the `parameters.retry_after` field from the response body. If the required wait is 30 seconds or less, it sleeps for that duration and retries the request automatically. If the ban exceeds 30 seconds, the message is dropped (logged as a warning) rather than blocking the caller for a long time.

**Exponential backoff on network errors**: If a request fails due to a network error (fetch throws) rather than an API error, `post` retries up to 3 times with delays of 1s, 2s, and 3s between attempts. This handles transient connectivity blips without requiring the caller to implement retry logic.

**Markdown fallback**: Two wrapper functions handle Markdown parse failures gracefully.

```typescript
async function postWithMarkdownFallback(method: string, payload: Record<string, unknown>, botToken?: string): Promise<unknown | null>
async function editWithMarkdownFallback(messageId: number, text: string, chatId: string, botToken: string): Promise<boolean>
```

Both functions first attempt the request with `parse_mode: 'Markdown'`. If Telegram returns a 400 error indicating a Markdown parsing failure, they automatically retry with `parse_mode` omitted, sending the content as plain text. This prevents messages from being silently dropped when the agent's response contains Markdown syntax that Telegram rejects (unmatched backticks, nested formatting, etc.).

**"message is not modified" suppression**: The `editMessage` function treats Telegram's 400 "message is not modified" error as a success instead of a failure. This error occurs frequently during streaming edits when the content hasn't changed between throttle windows - treating it as a failure would log noise and return `false` to the caller despite nothing actually going wrong.

### Implementation Notes

The implementation makes several deliberate technical choices that affect reliability and simplicity. These notes capture the reasoning behind the design decisions.

- Uses `fetch()` (Node built-in undici) - no `requests`, `urllib`, or `telegram` library dependency. This avoids version conflicts and keeps the module self-contained.
- Long-polling with `getUpdates` (no webhooks). Simpler infrastructure requirements - no public URL, SSL certificate, or reverse proxy needed.
- All sending/receiving functions accept an optional `botToken` param so the daemon's parallel pollers can call them without mutating global config state.
- Each agent poller tracks its own `lastUpdateId` independently in per-agent state, preventing cross-agent update offset collisions.
- `flushOldUpdates()` consumes pending updates before any polling operation, preventing stale responses from interfering with fresh interactions.
- All API calls have a 15-second timeout (`AbortSignal.timeout(15_000)`). Long enough for normal API calls, short enough to detect network issues quickly.
- Errors are logged but don't throw - functions return `null`/`false` on failure. This fail-soft approach prevents a Telegram API error from crashing the entire application.
- Multipart form data is built manually with `Buffer` for voice note and photo uploads (30-second timeout). The extended timeout accommodates audio files that can be several hundred kilobytes.

---

## Legacy Router (Deleted)

> **Note:** `src/main/router.ts` has been deleted. The legacy two-tier routing system (pattern matching + LLM classification) is no longer needed. With per-agent bots, each agent has its own dedicated bot and chat, so routing is unnecessary - incoming messages are already scoped to the correct agent by which bot received them. Routing between channels and agents is now handled by the switchboard and agent-router in `src/main/channels/`.

---

## src/main/channels/telegram/formatter.ts - Message Formatting

Extracted from daemon.ts to keep formatting logic separate from polling/dispatch. Handles all Telegram-specific message rendering.

**Exports:**
- `ToolCallState`, `StreamState` - interfaces tracking streaming display state
- `formatToolName(name)` - strips MCP prefixes (e.g. `mcp__memory__save_observation` -> `save_observation`)
- `truncate(text, max)` - text truncation with ellipsis
- `escapeMarkdown(text)` - Telegram MarkdownV2 escaping
- `formatElapsed(ms)` - human-readable duration (e.g. "2m 15s")
- `formatToolResult(result)` - concise tool result summaries for streaming display
- `formatToolInput(args)` - tool input argument display
- `buildStatusDisplay(state)` - full streaming status line (tool count, elapsed, thinking indicator)

Used by daemon.ts during streaming dispatch to build the status footer shown below each agent response.

---

## src/main/channels/telegram/daemon.ts - Polling Daemon

The polling daemon is responsible for receiving Telegram messages from each agent's dedicated bot and dispatching responses. It runs parallel per-agent pollers with randomised jitter. Each agent has its own dispatch lock so agents dispatch in parallel; a narrow config lock serialises only the Config singleton mutation during setup. Pollers launch staggered 10 seconds apart to avoid thundering herd on startup.

### How It Works

On startup, `discoverTelegramAgents()` finds all agents that have both `telegram_bot_token` and `telegram_chat_id` configured. For each discovered agent a `runAgentPoller()` loop starts independently. Each loop:

1. **Wait with jitter** - sleeps 8-15 seconds (randomised) between polls for organic feel
2. **Poll** - calls `getUpdates` on the agent's own bot token, `allowed_updates: ['message']`
3. **Intercept utility commands** - `/status` handled directly without dispatch
4. **Dispatch** - for each incoming message, calls `withAgentDispatchLock()` to acquire the per-agent lock, then invokes `dispatchToAgent()`
5. **Respond** - streams the agent's response back into the same chat via `editMessage()`
6. **Persist** - saves per-agent `lastUpdateId` to state after each poll

### Agent Discovery

```typescript
async function discoverTelegramAgents(): Promise<TelegramAgentConfig[]>
```

Scans all agents via `discoverAgents()`, loads each manifest, and returns those with `telegram_bot_token` and `telegram_chat_id` set (either in the manifest directly or via global config fallback for Xan). Disabled and muted agents are excluded.

```typescript
interface TelegramAgentConfig {
  name: string;
  botToken: string;
  chatId: string;
}
```

### Agent Dispatch

The `dispatchToAgent` function handles temporarily switching the application's context to the target agent, running inference, and returning the response. This context switch is necessary because config, database, and prompt system are all agent-scoped.

```typescript
async function dispatchToAgent(agentName: string, text: string, chatId: string, botToken: string): Promise<string | null>
```

The dispatch sequence is:

1. Saves the current agent name for later restoration
2. Sends an initial "Thinking..." placeholder message via `sendMessageGetId()` (only for user-initiated Telegram messages; system-originated dispatches like cron are silent)
3. Acquires the **config lock** (`withConfigLock`), then:
   a. Calls `config.reloadForAgent(agentName)` and `memory.initDb()` to switch context
   b. Loads the system prompt via `loadSystemPrompt()`
   c. Gets the CLI session ID from memory for session continuity
   d. Spawns `streamInference()` - the config lock is released once the subprocess is spawned
4. Streams inference. As events arrive, the placeholder is periodically edited (throttled to once every 1.5 seconds) with a progressively richer display:
   - **Thinking blockquotes** - `ThinkingDeltaEvent` content rendered as `> _thinking preview..._`
   - **Tool input display** - `ToolUseEvent` appends formatted tool argument summaries
   - **Tool result stats** - `ToolResultEvent` formatted per tool type (match counts, line counts, etc.)
   - **Compacting** - surfaced inline when the CLI context window is compacted mid-stream
5. On completion: final `editMessage()` with the complete response, prefixed with the agent's emoji and display name
6. On no response: **deletes the orphaned "Thinking..." message** via `deleteMessage()` instead of leaving it visible
7. On dispatch timeout (5 min): calls `stopInference()` to kill the zombie CLI process, clears the flush timer
8. Restores the original agent config via `withConfigLock` -> `config.reloadForAgent(originalAgent)` and `memory.initDb()`
9. Returns the response text or `null`

### Dispatch Locks

Two-tier locking system allows parallel dispatch while protecting the shared Config singleton:

```typescript
// Per-agent - agents dispatch in parallel, but each agent serialises its own dispatches
function withAgentDispatchLock<T>(agentName: string, fn: () => Promise<T>): Promise<T>

// Config - narrow lock around config.reloadForAgent() + subprocess spawn only
function withConfigLock<T>(fn: () => Promise<T>): Promise<T>
```

**Per-agent dispatch lock**: Each agent has its own promise-chaining queue. Companion and Montgomery can dispatch simultaneously. But if two messages arrive for the same agent, they're serialised.

**Config lock**: The Config singleton is mutated by `config.reloadForAgent()`. This narrow lock is held only while reloading config and spawning the subprocess - released before streaming begins. The `finally` block that restores the original agent config is also wrapped in the config lock.

This replaced the previous global `withDispatchLock` which serialised ALL agents, causing worst-case queuing of N * inference-time when N agents had pending messages.

### Race Condition Prevention

- **Per-agent dispatch lock** - `withAgentDispatchLock()` serialises per agent while allowing cross-agent parallelism.
- **Config lock** - `withConfigLock()` serialises the Config singleton mutation during the brief setup window.
- **Active dispatch guard** - `_activeDispatches` set drops inbound messages for an agent that's already dispatching, preventing queue buildup.
- **Instance lock** - `O_EXLOCK` on macOS (with pid-check fallback on other platforms) prevents two daemon instances from running simultaneously.
- **Per-bot polling** - each poller owns its own update offset for its bot, eliminating contention on `getUpdates`.
- **Isolated memory** - each agent has its own SQLite database, so there are no cross-agent write conflicts at the DB layer.
- **Staggered startup** - pollers launch 10 seconds apart to avoid thundering herd on daemon start.

### Message Deduplication

The daemon uses a hash-based deduplication cache to prevent the same message from being dispatched twice. This guards against edge cases where a network hiccup causes the same update to appear in consecutive polls before the offset is advanced.

Each incoming message is hashed (message text + message ID). Before dispatch, the hash is checked against an in-memory cache with a 5-second expiry window. If the hash is already present and was seen within the last 5 seconds, the message is silently dropped. If it is new (or older than 5 seconds), the hash is recorded and dispatch proceeds.

The cache holds at most 200 entries. When the limit is reached, the oldest entry is evicted to keep memory bounded.

### Instance Locking

The instance lock prevents duplicate daemon processes, which would cause messages to be processed multiple times and responses to be sent in duplicate.

```typescript
export function acquireLock(): boolean
```

The lock function opens `~/.atrophy/.telegram_daemon.lock` with `O_WRONLY | O_CREAT | O_EXLOCK | O_NONBLOCK`. The flags work as follows:

- `O_EXLOCK` (0x20): macOS advisory exclusive lock acquired atomically on open
- `O_NONBLOCK` (0x4000): fail immediately if lock is held (instead of blocking)

On success, writes the current PID to the lock file so operators can identify which process holds the lock. On `EAGAIN`/`EWOULDBLOCK`, another instance holds the lock and the function returns false.

If `O_EXLOCK` is not supported (Linux), the function falls back to `acquireLockFallback()`, which uses a simpler strategy:

1. Read the PID from the lock file
2. Check if that process is alive via `process.kill(pid, 0)`
3. If dead (or file corrupt), reclaim by writing own PID
4. Open the file with `O_RDONLY` to keep a reference

This fallback is not race-free (two processes could both find the lock stale simultaneously), but it is acceptable for a single-user daemon where the race window is extremely narrow.

The `releaseLock` function closes the lock file descriptor and unlinks the lock file. It is safe to call even if no lock is held, since both operations are wrapped in try/catch blocks.

```typescript
export function releaseLock(): void
```

### Utility Commands

The daemon intercepts utility commands before dispatch. The `/status` command can be sent to any agent's bot.

| Command | Action |
|---------|--------|
| `/status` | Lists all enabled agents with emoji, display name, and bot presence indicator. Sends the list as a formatted Markdown message. |

### State Persistence

The daemon tracks per-agent polling state in `~/.atrophy/.telegram_daemon_state.json`.

```json
{
  "agents": {
    "xan": { "last_update_id": 123456789 },
    "companion": { "last_update_id": 987654321 }
  }
}
```

Each agent's `last_update_id` is saved after every successful poll cycle. On daemon start, each poller loads its agent's saved offset so no messages are re-processed after a restart or reboot. If the state file is missing or an agent entry is absent, the poller begins from update ID 0.

Bot profile photos are set on daemon startup: `setBotProfilePhoto()` is called for each discovered agent using the agent's reference image from `avatar/source/face.png` (if it exists).

### Daemon Control

Three functions control the daemon's lifecycle. They are called from the Electron main process via IPC handlers or from the command-line entry point.

```typescript
export function startDaemon(): boolean
export function stopDaemon(): void
export function isDaemonRunning(): boolean
```

The `startDaemon` function performs a complete startup sequence:

1. Checks if already running (returns true immediately if so)
2. Acquires the instance lock (returns false if another instance is running)
3. Calls `discoverTelegramAgents()` to find all configured agents
4. Loads per-agent state (last_update_id) from state file
5. Sets bot profile photos from agent reference images
6. Starts a `runAgentPoller()` loop for each discovered agent (all run in parallel)

The `stopDaemon` function performs the reverse:

1. Sets a running flag to false (all poller loops check this flag)
2. Aborts any in-flight long-polls via per-poller AbortControllers
3. Releases the instance lock

### Operating Modes

The daemon can run in three modes depending on how it is started. All three modes use the same polling and dispatch logic - they differ only in lifecycle management.

- **Managed** - started from within the Electron main process via `startDaemon()`. This is the standard mode when the app is running. The daemon stops when the app quits.
- **Continuous** - as a launchd agent with `KeepAlive: true`, launched via `--telegram-daemon` flag. This mode keeps the daemon running even when the GUI is closed, ensuring Telegram messages are always processed.
- **Single poll** - one-shot execution for testing or cron-triggered runs. Useful for debugging dispatch behavior without starting the full daemon loop.

### launchd Management

The daemon can be installed as a macOS launchd agent for continuous operation. The launchd plist is generated programmatically with the correct paths and environment variables.

```typescript
export function installLaunchd(electronBin: string): void
export function uninstallLaunchd(): void
export function isLaunchdInstalled(): boolean
```

The launchd plist is configured with the following properties:

- Label: `com.atrophy.telegram-daemon`
- Path: `~/Library/LaunchAgents/com.atrophy.telegram-daemon.plist`
- `KeepAlive: true` and `RunAtLoad: true` - the daemon starts at login and restarts if it crashes
- Stdout: `~/.atrophy/logs/telegram_daemon.log`
- Stderr: `~/.atrophy/logs/telegram_daemon.err`
- Environment: `PATH` is inherited from the current process, ensuring Node.js and Python are findable

The `installLaunchd` function unloads the existing plist if present, writes the new one, and loads it via `launchctl`. The plist XML is hand-built with proper escaping via `escapeXml()` to handle special characters in file paths.

### Error Recovery

The daemon is designed to be resilient against transient failures. No single error - whether from the Telegram API, agent inference, or database access - should stop the daemon from processing future messages.

- API poll errors are caught and logged but do not stop the daemon. The next interval tick retries the poll.
- Individual message dispatch failures are caught per-agent and do not block other agents from processing the same message.
- If the Telegram API returns null (network error), the poll is skipped and retried on the next interval.
- The daemon continues running even if all agents fail to respond, logging the failures for debugging.

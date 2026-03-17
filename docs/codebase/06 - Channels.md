# Channels

External communication channels beyond the direct conversation interface. The channel system enables the companion to communicate with the user through Telegram, serving as an always-available messaging layer that works independently of the GUI window. This is the primary mechanism for autonomous outreach - heartbeat messages, morning briefs, voice notes, and scheduled task delivery all flow through the Telegram channel.

## Architecture

Each agent has its own dedicated Telegram bot - its own token, its own chat, and its own profile photo set from the agent's reference images. The daemon runs parallel per-agent pollers with randomised jitter so activity feels organic rather than mechanical. A dispatch mutex serialises inference so the Config singleton and Claude CLI are never contested between pollers.

This replaces the previous Topics mode architecture where all agents shared a single bot and a single group with forum threads. The per-agent bot model eliminates group management entirely - no shared group, no topic IDs, no routing logic.

```
Telegram Bot API (one bot per agent)
  |
src/main/telegram-daemon.ts  (parallel per-agent pollers)
  |
discoverTelegramAgents()       (agents with bot token + chat ID configured)
  |
withDispatchLock()             (mutex - one agent dispatches at a time)
  |
src/main/telegram.ts           (send via agent's own bot token)
```

---

## src/main/telegram.ts - Bot API Client

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

## src/main/router.ts - Message Router (Legacy)

> **Note:** The router is no longer used by the Telegram daemon. With per-agent bots, each agent has its own dedicated bot and chat, so routing is unnecessary - incoming messages are already scoped to the correct agent by which bot received them. The router module remains in the codebase for potential use by other subsystems but is not part of the active Telegram message flow.

The router is a two-tier routing system that was originally used to decide which agent(s) should handle an incoming Telegram message. The first tier uses pattern matching (free, instant), and the second tier uses a lightweight LLM call (costs one Haiku inference). This tiered approach means most messages are routed without any LLM cost, while ambiguous messages still get intelligent routing.

### Types

The router defines two key types. `AgentInfo` represents a routable agent with its metadata, and `RoutingDecision` captures the routing outcome including which agents were selected, how they were selected, and the cleaned message text.

```typescript
interface AgentInfo {
  name: string;
  display_name: string;
  description: string;
  wake_words: string[];
  emoji: string;
}

export interface RoutingDecision {
  agents: string[];              // agent slugs to handle the message
  tier: 'explicit' | 'agent' | 'single' | 'none';
  text: string;                  // cleaned message text
}
```

The `tier` field records how the routing decision was made: `explicit` means pattern matching, `agent` means the LLM routing agent decided, `single` means there was only one available agent (no routing needed), and `none` means no agents were available.

### Agent Registry

The `loadAgentRegistry()` function builds the routing registry fresh on every call. This ensures the registry always reflects the current agent state, including recently muted or disabled agents. The building process is:

1. Calling `discoverAgents()` to get all agents from both `USER_DATA` and `BUNDLE_ROOT`
2. Filtering out disabled and muted agents (via `getAgentState()`). Muted agents are excluded from routing so they do not receive messages.
3. Loading each agent's manifest from `USER_DATA` then `BUNDLE_ROOT` (same two-tier resolution as the rest of the system)
4. Extracting `display_name`, `description`, `wake_words`, and `telegram_emoji` for routing metadata

### Tier 1: Explicit Routing (Free)

The `checkExplicit(text, agents)` function performs pattern matching with no LLM call. It checks five patterns in order, returning the first match. This tier handles the majority of messages in practice, since users quickly learn to prefix their messages with an agent name.

| Pattern | Example | Behaviour |
|---------|---------|-----------|
| `/agent_name` | `/companion what's up` | Route to named agent, strip prefix |
| `@agent_name` | `@companion thoughts?` | Route to mentioned agent(s) |
| `agent_name:` | `companion: hey` | Route to named agent, strip prefix |
| Wake word | `hey darling` | Route to agent with matching wake word |
| Multiple names | `companion and monty, debate this` | Route to all named agents |

The matching logic for each pattern works as follows:

- `/command` prefix: extracts the first word after `/`, matches against `agent.name` or `agent.display_name.toLowerCase()`. This follows the Telegram bot command convention.
- `@mention`: uses regex `/@(\w+)/g` to find all mentions, matches each against agent names. Multiple mentions route to multiple agents.
- `name:` prefix: checks if message starts with `<name>:` or `<display_name>:` (case-insensitive). This is a natural addressing pattern.
- Wake words: checks if message starts with any wake word (case-insensitive). Wake words are configured per-agent in the manifest.
- Multi-agent: if two or more agent names/display names appear anywhere in the message, routes to all of them. This enables "debate" or "discuss" patterns.

Returns the matched agent name(s) as an array, or `null` if no explicit match was found (falling through to Tier 2).

### Tier 2: Routing Agent (Haiku)

When no explicit match is found, a lightweight LLM call classifies the message. This tier handles ambiguous messages where the user did not explicitly name an agent. The routing agent is a separate inference call that costs minimal tokens.

```typescript
async function routeViaAgent(text: string, agents: AgentInfo[]): Promise<string[]>
```

The routing call uses `runInferenceOneshot()` with the following parameters:

- Model: `claude-haiku-4-5-20251001` (cheapest and fastest model)
- Effort: `low` (minimal processing)
- System prompt: instructs the routing agent to return ONLY a JSON array of agent slugs, with no explanation or commentary

The system prompt includes a list of valid agent slugs with their descriptions, an instruction to route to ONE agent unless multiple perspectives are genuinely needed, and the rule to pick the personality that best fits for casual/general messages.

The response is parsed with `result.match(/\[.*?\]/s)` to extract the JSON array from the response. Valid slugs are filtered against the known agent list, and any invalid slugs are dropped. If parsing fails entirely or no valid slugs are found, the function falls back to routing to the first agent in the registry.

### Main Router

The `routeMessage` function is the main entry point for all routing decisions. It orchestrates the two tiers and handles edge cases where routing is not needed.

```typescript
export async function routeMessage(text: string): Promise<RoutingDecision>
```

The decision flow proceeds through these steps:

1. Load agent registry (filters disabled/muted agents)
2. If no agents available: return `tier: 'none'` (the daemon will log this and skip the message)
3. If exactly one agent: return `tier: 'single'` (skip routing entirely - no need to decide)
4. Try explicit routing. If matched, clean the text (strip `/prefix` or `name:` prefix) and return `tier: 'explicit'`
5. Fall through to routing agent. Return `tier: 'agent'`

Text cleaning for explicit routes strips the addressing prefix so the agent sees the actual question rather than the routing syntax:

- If starts with `/`, take everything after the first space
- If contains `:` within the first 30 characters, take everything after the colon

The 30-character limit on colon detection prevents false matches on messages that contain colons in their body text (like URLs or time references).

### Routing Queue (File-Based IPC)

The router includes a file-based queue at `~/.atrophy/.telegram_routes.json` for daemon coordination. This queue serves as a persistent record of routing decisions and enables multi-process coordination when the daemon and GUI need to share routing state.

```typescript
interface RouteEntry {
  message_id: number;
  text: string;
  agents: string[];
  tier: string;
  timestamp: number;
}

export function enqueueRoute(messageId: number, text: string, decision: RoutingDecision): void
export function dequeueRoute(agentName: string): RouteEntry | null
```

The `enqueueRoute` function appends a route entry and keeps only the last 50 entries, preventing unbounded growth. The `dequeueRoute` function finds the first entry containing the given agent name, removes the agent from the entry's agent list (since that agent has now handled the message), and deletes the entry entirely if no agents remain. This consumption pattern supports multi-agent routing where each agent independently dequeues its portion of the work.

---

## src/main/telegram-daemon.ts - Polling Daemon

The polling daemon is responsible for receiving Telegram messages from each agent's dedicated bot and dispatching responses. It runs parallel per-agent pollers with randomised jitter, and a dispatch mutex ensures inference (which mutates the Config singleton and Claude CLI session) runs for only one agent at a time. The daemon runs as either a managed timer within the Electron main process or as a standalone launchd agent.

### How It Works

On startup, `discoverTelegramAgents()` finds all agents that have both `telegram_bot_token` and `telegram_chat_id` configured. For each discovered agent a `runAgentPoller()` loop starts independently. Each loop:

1. **Wait with jitter** - sleeps 8-15 seconds (randomised) between polls for organic feel
2. **Poll** - calls `getUpdates` on the agent's own bot token, `allowed_updates: ['message']`
3. **Intercept utility commands** - `/status` handled directly without dispatch
4. **Dispatch** - for each incoming message, calls `withDispatchLock()` to acquire the mutex, then invokes `dispatchToAgent()`
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
2. Calls `config.reloadForAgent(agentName)` and `memory.initDb()` to switch context to the target agent
3. Loads the system prompt via `loadSystemPrompt()` using the target agent's prompts
4. Gets the last CLI session ID from memory for session continuity
5. Prepends `[Telegram message from the user]` to the message text
6. Sends an initial "Thinking..." placeholder message via `sendMessageGetId()` using the agent's `botToken`
7. Streams inference via `streamInference()`. As events arrive, the placeholder is periodically edited (throttled to once every 1.5 seconds) with a progressively richer display:
   - **Elapsed time counter** - a live status line "12s | 3 tools" is appended below the streamed text while inference is running. Elapsed time counts up from the moment inference starts.
   - **Thinking blockquotes** - `ThinkingDeltaEvent` content is rendered as `> _thinking preview..._` (truncated to 400 chars). Extended thinking is surfaced inline rather than hidden.
   - **Tool input display** - `ToolUseEvent` appends a formatted line showing a human-readable summary of tool arguments via `formatToolInput()`. For example, `recall` shows the query string rather than raw JSON.
   - **Tool result stats** - `ToolResultEvent` content is formatted per tool type via `formatToolResult()`: search tools show "5 matches", file reads show "42 lines", writes show "wrote 3 lines", edits show "applied", general results show "3 results".
   - Compacting status is surfaced inline when the CLI context window is compacted mid-stream.
8. Performs a final `editMessage()` with the complete response, prefixed with the agent's emoji and display name, and a stats footer line `_18s | 3 tools | ~42.5 tokens_` showing elapsed time, tool call count, and approximate token usage.
9. Restores the original agent config via `config.reloadForAgent(originalAgent)` and `memory.initDb()`
10. Returns the response text or `null`

### Dispatch Mutex

```typescript
async function withDispatchLock<T>(fn: () => Promise<T>): Promise<T>
```

A simple promise-chaining mutex. All calls to `dispatchToAgent` are wrapped in `withDispatchLock()`, which serialises inference across all parallel pollers. This prevents:

- Two agents from concurrently mutating the Config singleton
- Two Claude CLI processes from competing for the same session context
- Interleaved writes to overlapping database tables

Pollers themselves continue running in parallel - only the dispatch (inference) step is serialised.

### Race Condition Prevention

- **Dispatch mutex** - `withDispatchLock()` ensures only one agent dispatches at a time, while pollers themselves stay parallel.
- **Instance lock** - `O_EXLOCK` on macOS (with pid-check fallback on other platforms) prevents two daemon instances from running simultaneously. Only one process can hold the lock.
- **Per-bot polling** - each poller owns its own update offset for its bot, eliminating contention on `getUpdates`.
- **Isolated memory** - each agent has its own SQLite database, so there are no cross-agent write conflicts at the DB layer.

The only concurrent Telegram activity outside the daemon is cron jobs (heartbeat, morning brief) sending messages independently. This is safe because they're independent fire-and-forget POSTs.

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

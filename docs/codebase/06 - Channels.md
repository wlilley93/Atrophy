# Channels

External communication channels beyond the direct conversation interface. The channel system enables the companion to communicate with the user through Telegram, serving as an always-available messaging layer that works independently of the GUI window. This is the primary mechanism for autonomous outreach - heartbeat messages, morning briefs, voice notes, and scheduled task delivery all flow through the Telegram channel.

## Architecture

Telegram uses Topics mode - a single group with Topics (Forum mode) enabled, where each agent gets its own topic thread. The bot is shared across all agents, and routing is handled structurally by Telegram itself rather than by application-level logic. Messages sent to a topic are dispatched directly to the corresponding agent, and each agent's responses go back to its own topic.

This replaces the previous flat-chat architecture where all agents shared a single conversation and a router (pattern matching + LLM classification) decided which agent should respond. Topics mode eliminates the need for routing entirely - the topic ID tells the daemon exactly which agent the message is for.

```
Telegram Bot API (Topics-enabled group)
  |
src/main/telegram-daemon.ts  (single poller)
  |
Topic ID -> agent mapping      (no router needed)
  |
Sequential dispatch             (one agent at a time)
  |
src/main/telegram.ts            (send to agent's topic)
```

---

## src/main/telegram.ts - Bot API Client

This module implements the Telegram Bot API integration using pure HTTP via `fetch()` (Node built-in undici). There are no third-party Telegram libraries - all API calls are handwritten HTTP requests. This keeps the dependency footprint minimal and gives full control over timeout, error handling, and multipart form construction.

The module provides three layers of functionality: low-level API helpers, message sending/receiving primitives, and high-level convenience methods for common interaction patterns.

### Internal API Helper

The `apiUrl` function constructs Telegram API URLs from the configured bot token and a method name. It reads the token from the current config, meaning it automatically uses the correct token after an agent switch.

```typescript
function apiUrl(method: string): string
```

The `post` function is the generic POST helper used by all Bot API calls. It handles the complete request lifecycle - checking that the bot token is configured, sending the JSON payload, parsing the response, and returning the result. All calls use a 15-second timeout via `AbortSignal.timeout(15_000)` to prevent the app from hanging on network issues. Errors are logged but never thrown, so callers always get a clean return value (the result object on success, or `null` on failure).

```typescript
async function post(method: string, payload: Record<string, unknown>): Promise<unknown | null>
```

### Sending

The module provides three sending methods, each handling a different message type. All three support optional emoji-prefixed agent identification.

The `sendMessage` function sends a plain Markdown-formatted text message. Messages are sent to the agent's topic thread within the group by default. When `prefix=true` (the default), it prepends the agent's emoji and display name (e.g. "moon *Xan*") so the recipient knows which agent is speaking, though this is less critical in Topics mode since each topic is already scoped to one agent.

```typescript
export async function sendMessage(
  text: string,
  chatId?: string,    // defaults to config.TELEGRAM_GROUP_ID
  prefix?: boolean,   // defaults to true
  topicId?: number,   // defaults to agent's TELEGRAM_TOPIC_ID
): Promise<boolean>
```

The `sendButtons` function sends a message with an inline keyboard - rows of tappable buttons that appear below the message. This is used for confirmation prompts (Yes/No) and permission requests. It returns the `message_id` for tracking which message the user responds to.

```typescript
export async function sendButtons(
  text: string,
  buttons: { text: string; callback_data: string }[][],
  chatId?: string,
  prefix?: boolean,
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
async function flushOldUpdates(): Promise<void>
```

The `pollCallback` function long-polls for an inline keyboard callback. It polls in 30-second windows until a `callback_query` from the target user (matched by `from.id`) is received. When a callback arrives, it automatically answers the callback query via `answerCallbackQuery` (which removes the loading spinner in the Telegram client). Returns the `callback_data` string or `null` on timeout.

```typescript
export async function pollCallback(
  timeoutSecs?: number,  // default 120
  chatId?: string,
): Promise<string | null>
```

If the API returns null (network error), the function waits 2 seconds before retrying. This prevents tight retry loops during transient network outages.

The `pollReply` function long-polls for a text message reply. It uses the same polling pattern as `pollCallback` but filters for `message` updates instead of `callback_query` updates. Returns the message text or `null` on timeout. Both polling functions match messages by `from.id` to ensure they only accept responses from the correct user.

```typescript
export async function pollReply(
  timeoutSecs?: number,  // default 120
  chatId?: string,
): Promise<string | null>
```

### High-Level Convenience Methods

These methods combine sending and receiving into complete interaction patterns. They handle the full lifecycle of an interactive exchange - flushing stale updates, sending the prompt, and polling for the response.

The `askConfirm` function sends a confirmation prompt with Yes/No buttons and waits for the user to tap one. It flushes old updates first, sends the buttons, and polls for a callback. Returns `true` (yes), `false` (no), or `null` (timeout). This is the standard pattern for permission and confirmation requests from background jobs.

```typescript
export async function askConfirm(
  text: string,
  timeoutSecs?: number,  // default 120
): Promise<boolean | null>
```

The `askQuestion` function sends a question and waits for a free-text reply. It flushes old updates first, sends the message, and polls for a reply. Returns the reply text or `null` on timeout.

```typescript
export async function askQuestion(
  text: string,
  timeoutSecs?: number,  // default 120
): Promise<string | null>
```

### Bot Command Registration

Bot command registration makes agent names appear in Telegram's autocomplete menu. When the user types `/` in the chat, they see a list of all agents with their descriptions, making it easy to address a specific agent.

The `registerBotCommands` function scans all discovered agents via `discoverAgents()` and builds a command list. Each agent gets a `/<agent_name>` command with its description from the manifest (truncated to Telegram's 256-character limit). Two utility commands are appended: `/status` (show active agents) and `/mute` (toggle agent muting). The full list is sent to the Telegram API via `setMyCommands`.

```typescript
export async function registerBotCommands(): Promise<boolean>
```

The `clearBotCommands` function removes all bot commands via `deleteMyCommands` API. This is used during cleanup or when the agent roster changes significantly.

```typescript
export async function clearBotCommands(): Promise<boolean>
```

### Update ID Tracking

The module maintains a module-level `_lastUpdateId` variable that tracks the highest processed update ID. This prevents re-processing old messages after a restart or reconnection. The variable is shared between the telegram module and the daemon via `setLastUpdateId()`, ensuring both components agree on which updates have been processed.

When calling `getUpdates`, the offset is set to `_lastUpdateId + 1`, telling the Telegram API to only return updates newer than the last processed one. This is a standard Telegram pattern that ensures exactly-once processing of messages.

### Configuration

Each agent's Telegram configuration comes from its `agent.json` manifest. All agents share a single bot and group, but each has its own topic thread ID.

```json
{
  "telegram": {
    "bot_token_env": "TELEGRAM_BOT_TOKEN",
    "group_id_env": "TELEGRAM_GROUP_ID",
    "topic_id": 42
  },
  "telegram_emoji": "\ud83c\udf19"
}
```

The `topic_id` identifies the agent's topic thread within the Topics-enabled group. The `telegram_emoji` appears before the agent's name in outgoing messages - less critical in Topics mode since each topic is already scoped to one agent, but still used for visual consistency.

### Usage

The Telegram channel is used by multiple components throughout the system. Understanding which components use it helps explain why the channel needs to be robust and handle concurrent access gracefully.

- **Telegram daemon**: Receives messages in agent topics and dispatches directly - the main incoming message handler
- **`ask_user` MCP tool**: Sends questions during conversation and blocks for a reply - used when the agent needs user input mid-task
- **`send_telegram` MCP tool**: Proactive outreach (rate limited to 5/day) - used for unprompted messages
- **`heartbeat` job**: Evaluates whether to reach out and sends messages - periodic check-in
- **`gift` job**: Delivers unprompted notes - monthly creative outreach
- **`voice-note` job**: Sends spontaneous voice notes (OGG Opus via `sendVoiceNote()`) - audio-based outreach
- **`run-task` job**: `telegram_voice` delivery method sends task output as voice notes - scheduled task delivery

### Implementation Notes

The implementation makes several deliberate technical choices that affect reliability and simplicity. These notes capture the reasoning behind the design decisions.

- Uses `fetch()` (Node built-in undici) - no `requests`, `urllib`, or `telegram` library dependency. This avoids version conflicts and keeps the module self-contained.
- Long-polling with `getUpdates` (no webhooks). Simpler infrastructure requirements - no public URL, SSL certificate, or reverse proxy needed.
- Tracks `_lastUpdateId` globally to avoid re-processing old updates. Shared between the telegram module and daemon via setter function.
- `flushOldUpdates()` consumes pending updates before any polling operation, preventing stale responses from interfering with fresh interactions.
- All API calls have a 15-second timeout (`AbortSignal.timeout(15_000)`). Long enough for normal API calls, short enough to detect network issues quickly.
- Errors are logged but don't throw - functions return `null`/`false` on failure. This fail-soft approach prevents a Telegram API error from crashing the entire application.
- Multipart form data is built manually with `Buffer` for voice note uploads (30-second timeout). The extended timeout accommodates audio files that can be several hundred kilobytes.

---

## src/main/router.ts - Message Router (Legacy)

> **Note:** The router is no longer used by the Telegram daemon. With Topics mode, each agent has its own topic thread, so routing is handled structurally by Telegram rather than by application logic. The router module remains in the codebase for potential use by other subsystems but is not part of the active Telegram message flow.

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

The polling daemon is the single-process component responsible for receiving Telegram messages from the Topics-enabled group, mapping them to agents by topic ID, and dispatching responses. It runs as either a managed timer within the Electron main process or as a standalone launchd agent. The key architectural decision is sequential dispatch - agents process messages one at a time, never concurrently.

### How It Works

The daemon's poll cycle runs on every interval tick. With Topics mode, routing is structural - the topic ID on each incoming message directly identifies the target agent, eliminating the need for the router module. Each step builds on the previous one, and failures at any step are caught and logged without stopping the daemon.

1. **Poll** - Long-polls `getUpdates` with 30-second timeout, `allowed_updates: ['message']`
2. **Filter** - Only accepts messages from the configured `TELEGRAM_GROUP_ID`
3. **Intercept utility commands** - `/status` handled directly without dispatch
4. **Map topic to agent** - Looks up the agent whose topic matches the message's `message_thread_id` via `topic_map`
5. **Dispatch** - Invokes the target agent via `dispatchToAgent()`
6. **Respond** - Sends the agent's response to the same topic thread
7. **Persist** - Saves `_lastUpdateId` to state file after each poll cycle

### Agent Dispatch

The `dispatchToAgent` function handles the complex process of temporarily switching the application's context to a different agent, running inference, and switching back. This is necessary because the config, database, and prompt system are all agent-scoped - you cannot run inference for agent B while agent A's config is loaded.

```typescript
async function dispatchToAgent(agentName: string, text: string): Promise<string | null>
```

The dispatch sequence is:

1. Saves the current agent name for later restoration
2. Calls `config.reloadForAgent(agentName)` and `memory.initDb()` to switch context to the target agent
3. Loads the system prompt via `loadSystemPrompt()` using the target agent's prompts
4. Gets the last CLI session ID from memory for session continuity (so the agent resumes its existing conversation context)
5. Prepends `[Telegram message from the user]` to the message text so the agent knows the message came from Telegram
6. Runs `streamInference()` and collects the full response (tool calls are logged but the streaming events are not forwarded to the renderer)
7. Restores the original agent config via `config.reloadForAgent(originalAgent)` and `memory.initDb()`
8. Returns the response text or `null`

The `sendAgentResponse` function loads the agent's manifest to get `telegram_emoji` and `display_name`, prepends them to the response, and sends via `sendMessage()` with `prefix=false` into the agent's topic thread.

```typescript
function sendAgentResponse(agentName: string, text: string, chatId: string, threadId: number): void
```

### Race Condition Prevention

Sequential dispatch is the core safety mechanism. Even though Topics mode means each message targets a single agent, messages from different topics can arrive in the same poll batch. Without sequential dispatch, two agents could simultaneously write to the same database, compete for the Claude CLI session, or produce interleaved responses.

- **No concurrent agents** - agent A completes all tool calls and inference before agent B starts. This is enforced by `await` on each dispatch.
- **Instance lock** - `O_EXLOCK` on macOS (with pid-check fallback on other platforms) prevents two daemon instances from running simultaneously. Only one process can hold the lock.
- **Single poller** - one process owns the update offset, preventing contention on `getUpdates` that could cause duplicate message processing.
- **Isolated memory** - each agent has its own SQLite database, so there are no cross-agent write conflicts. The config switch changes which database is active.

The only concurrent Telegram activity is cron jobs (heartbeat, morning brief) sending messages independently. This is safe because they're independent fire-and-forget POSTs that don't read from or write to the shared update offset.

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

The daemon intercepts utility commands before dispatch. The `/status` command can be sent in any topic or in the general thread.

| Command | Action |
|---------|--------|
| `/status` | Lists all enabled agents with emoji, display name, and slash command. Sends the list as a formatted Markdown message. |

### State Persistence

The daemon tracks its position in the Telegram update stream and the topic-to-agent mapping using a state file at `~/.atrophy/.telegram_daemon_state.json`.

```json
{
  "last_update_id": 123456789,
  "topic_map": {
    "42": "xan",
    "43": "companion"
  }
}
```

The `topic_map` maps Telegram thread IDs (as strings) to agent names. This mapping is built on first run when topics are created, and persists across restarts so the daemon does not need to recreate topics.

The state is loaded on daemon start and saved after each poll cycle. This ensures the daemon does not re-process old messages after a restart or system reboot. If the state file is missing or corrupt, the daemon starts from update ID 0 with an empty topic map, which triggers topic creation for all enabled agents.

### Daemon Control

Three functions control the daemon's lifecycle. They are called from the Electron main process via IPC handlers or from the command-line entry point.

```typescript
export function startDaemon(intervalMs?: number): boolean  // default 10000
export function stopDaemon(): void
export function isDaemonRunning(): boolean
```

The `startDaemon` function performs a complete startup sequence:

1. Checks if already running (returns true immediately if so)
2. Acquires the instance lock (returns false if another instance is running)
3. Loads state (last_update_id and topic_map) from state file
4. Sets the module-level `_lastUpdateId` and syncs to the telegram module via `setLastUpdateId()`
5. Calls `ensureTopics()` to create missing topic threads for enabled agents
6. Enters a sequential poll loop (each poll waits for completion before scheduling the next)

The `stopDaemon` function performs the reverse:

1. Sets running flag to false
2. Aborts any in-flight long-poll via AbortController
3. Clears the poll timer
4. Releases the instance lock

### Operating Modes

The daemon can run in three modes depending on how it is started. All three modes use the same polling and dispatch logic - they differ only in lifecycle management.

- **Managed** - started from within the Electron main process via `startDaemon()`, polls on a configurable interval (default 10 seconds). This is the standard mode when the app is running. The daemon stops when the app quits.
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

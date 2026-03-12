# Channels

External communication channels beyond the direct conversation interface.

## Architecture

All agents share a single Telegram bot. A central daemon polls for messages, routes them to the right agent(s), and dispatches responses sequentially. This eliminates race conditions - no two agents ever run concurrently.

```
Telegram Bot API
  |
src/main/telegram-daemon.ts  (single poller)
  |
src/main/router.ts           (explicit match -> routing agent)
  |
Sequential dispatch           (agent A responds fully, then agent B)
  |
src/main/telegram.ts          (send with emoji prefix)
```

---

## src/main/telegram.ts - Bot API Client

Telegram Bot API integration. Pure HTTP via `fetch()` (Node built-in undici) - no third-party Telegram libraries.

### Internal API Helper

```typescript
function apiUrl(method: string): string
```

Constructs `https://api.telegram.org/bot<TOKEN>/<method>` from the current config's `TELEGRAM_BOT_TOKEN`.

```typescript
async function post(method: string, payload: Record<string, unknown>): Promise<unknown | null>
```

Generic POST helper for all Bot API calls. Checks that `TELEGRAM_BOT_TOKEN` is configured, sends JSON payload, parses the response, and returns `result` on success or `null` on failure. All calls have a 15-second timeout (`AbortSignal.timeout(15_000)`). Errors are logged but never thrown - the function always returns cleanly.

### Sending

```typescript
export async function sendMessage(
  text: string,
  chatId?: string,    // defaults to config.TELEGRAM_CHAT_ID
  prefix?: boolean,   // defaults to true
): Promise<boolean>
```

Send a plain Markdown message. When `prefix=true` (default), prepends the agent's emoji and display name (e.g. "moon *Xan*") so the recipient knows which agent is speaking. Uses `parse_mode: 'Markdown'`. Returns `true` on success.

```typescript
export async function sendButtons(
  text: string,
  buttons: { text: string; callback_data: string }[][],
  chatId?: string,
  prefix?: boolean,
): Promise<number | null>
```

Send a message with an inline keyboard. Each inner array is a row of buttons. Returns the `message_id` for tracking replies. Uses `reply_markup: { inline_keyboard: buttons }`.

Button format example:
```typescript
[[{ text: 'Yes', callback_data: 'yes' }, { text: 'No', callback_data: 'no' }]]
```

```typescript
export async function sendVoiceNote(
  audioPath: string,
  caption?: string,
  chatId?: string,
  prefix?: boolean,
): Promise<boolean>
```

Send an audio file as a Telegram voice note. Reads the file into a `Buffer`, determines the API method based on file extension:
- `.ogg` / `.oga` files: uses `sendVoice` API with field name `voice` and content type `audio/ogg`
- All other files: uses `sendAudio` API with field name `audio` and content type `audio/mpeg`

Builds multipart form data manually using `Buffer.concat()` with a generated boundary string. Has a 30-second timeout. Used by the `voice-note.ts` job and the `telegram_voice` delivery method in `run-task.ts`.

### Receiving

```typescript
async function flushOldUpdates(): Promise<void>
```

Consumes all pending updates from the Telegram API without processing them. Used before polling operations to avoid stale responses.

```typescript
export async function pollCallback(
  timeoutSecs?: number,  // default 120
  chatId?: string,
): Promise<string | null>
```

Long-poll for an inline keyboard callback. Polls in 30-second windows until a `callback_query` from the target user (matched by `from.id`) is received. Automatically answers the callback query via `answerCallbackQuery` (removes the loading spinner in Telegram). Returns `callback_data` or `null` on timeout.

If the API returns null (network error), waits 2 seconds before retrying.

```typescript
export async function pollReply(
  timeoutSecs?: number,  // default 120
  chatId?: string,
): Promise<string | null>
```

Long-poll for a text message reply. Same polling pattern as `pollCallback` but uses `allowed_updates: ['message']`. Returns message text or `null` on timeout. Matches messages by `from.id`.

### High-Level Convenience Methods

```typescript
export async function askConfirm(
  text: string,
  timeoutSecs?: number,  // default 120
): Promise<boolean | null>
```

Send a confirmation prompt with Yes/No buttons. Flushes old updates first, sends buttons, polls for callback. Returns `true` (yes), `false` (no), or `null` (timeout).

```typescript
export async function askQuestion(
  text: string,
  timeoutSecs?: number,  // default 120
): Promise<string | null>
```

Send a question and wait for a text reply. Flushes old updates first, sends message, polls for reply.

### Bot Command Registration

```typescript
export async function registerBotCommands(): Promise<boolean>
```

Scans all discovered agents via `discoverAgents()` and builds a command list:
- One `/agent_name` command per agent (description from manifest, truncated to 256 chars)
- `/status` - "Show which agents are active"
- `/mute` - "Mute/unmute the current agent"

Calls `setMyCommands` API. Commands appear in Telegram's autocomplete menu.

```typescript
export async function clearBotCommands(): Promise<boolean>
```

Removes all bot commands via `deleteMyCommands` API.

### Update ID Tracking

The module maintains a module-level `_lastUpdateId` variable that tracks the highest processed update ID. This prevents re-processing old messages. The variable is shared between the telegram module and the daemon via `setLastUpdateId()`.

### Configuration

Per-agent from `agent.json`:

```json
{
  "telegram": {
    "bot_token_env": "TELEGRAM_BOT_TOKEN",
    "chat_id_env": "TELEGRAM_CHAT_ID"
  },
  "telegram_emoji": "\ud83c\udf19"
}
```

The env var names themselves are configurable, allowing multiple agents to use different Telegram bots. The `telegram_emoji` appears before the agent's name in all outgoing messages.

### Usage

The Telegram channel is used by:

- **Telegram daemon**: Receives and dispatches routed messages
- **`ask_will` MCP tool**: Sends questions during conversation and blocks for a reply
- **`send_telegram` MCP tool**: Proactive outreach (rate limited to 5/day)
- **`heartbeat` job**: Evaluates whether to reach out and sends messages
- **`gift` job**: Delivers unprompted notes
- **`voice-note` job**: Sends spontaneous voice notes (OGG Opus via `sendVoiceNote()`)
- **`run-task` job**: `telegram_voice` delivery method sends task output as voice notes

### Implementation Notes

- Uses `fetch()` (Node built-in undici) - no `requests`, `urllib`, or `telegram` library dependency
- Long-polling with `getUpdates` (no webhooks)
- Tracks `_lastUpdateId` globally to avoid re-processing old updates
- `flushOldUpdates()` consumes pending updates before any polling operation
- All API calls have a 15-second timeout (`AbortSignal.timeout(15_000)`)
- Errors are logged but don't throw - functions return `null`/`false` on failure
- Multipart form data is built manually with `Buffer` for voice note uploads (30-second timeout)

---

## src/main/router.ts - Message Router

Two-tier routing system that decides which agent(s) should handle an incoming Telegram message.

### Types

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

### Agent Registry

`loadAgentRegistry()` builds the routing registry by:
1. Calling `discoverAgents()` to get all agents
2. Filtering out disabled and muted agents (via `getAgentState()`)
3. Loading each agent's manifest from `USER_DATA` then `BUNDLE_ROOT`
4. Extracting `display_name`, `description`, `wake_words`, and `telegram_emoji`

### Tier 1: Explicit Routing (Free)

`checkExplicit(text, agents)` performs pattern matching with no LLM call:

| Pattern | Example | Behaviour |
|---------|---------|-----------|
| `/agent_name` | `/companion what's up` | Route to named agent, strip prefix |
| `@agent_name` | `@companion thoughts?` | Route to mentioned agent(s) |
| `agent_name:` | `companion: hey` | Route to named agent, strip prefix |
| Wake word | `hey darling` | Route to agent with matching wake word |
| Multiple names | `companion and monty, debate this` | Route to all named agents |

Matching details:
- `/command` prefix: extracts the first word after `/`, matches against `agent.name` or `agent.display_name.toLowerCase()`
- `@mention`: uses regex `/@(\w+)/g` to find all mentions, matches each against agent names
- `name:` prefix: checks if message starts with `<name>:` or `<display_name>:` (case-insensitive)
- Wake words: checks if message starts with any wake word (case-insensitive)
- Multi-agent: if two or more agent names/display names appear anywhere in the message, routes to all of them

Returns the matched agent name(s) as an array, or `null` if no explicit match.

### Tier 2: Routing Agent (Haiku)

```typescript
async function routeViaAgent(text: string, agents: AgentInfo[]): Promise<string[]>
```

When no explicit match is found, a lightweight LLM call classifies the message. Uses `runInferenceOneshot()` with:
- Model: `claude-haiku-4-5-20251001`
- Effort: `low`
- System prompt: instructs the routing agent to return ONLY a JSON array of agent slugs

The system prompt includes:
- A list of valid agent slugs
- Instructions to route to ONE agent unless multiple perspectives are genuinely needed
- The rule to pick the personality that best fits for casual/general messages

The response is parsed with `result.match(/\[.*?\]/s)` to extract the JSON array. Valid slugs are filtered. Falls back to the first agent on failure.

### Main Router

```typescript
export async function routeMessage(text: string): Promise<RoutingDecision>
```

Decision flow:
1. Load agent registry (filters disabled/muted agents)
2. If no agents available: return `tier: 'none'`
3. If exactly one agent: return `tier: 'single'` (skip routing entirely)
4. Try explicit routing. If matched, clean the text (strip `/prefix` or `name:` prefix) and return `tier: 'explicit'`
5. Fall through to routing agent. Return `tier: 'agent'`

Text cleaning for explicit routes:
- If starts with `/`, take everything after the first space
- If contains `:` within the first 30 characters, take everything after the colon

### Routing Queue (File-Based IPC)

The router includes a file-based queue at `~/.atrophy/.telegram_routes.json` for daemon coordination:

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

`enqueueRoute()` appends a route entry and keeps only the last 50 entries. `dequeueRoute()` finds the first entry containing the agent name, removes the agent from the entry's agent list, and deletes the entry entirely if no agents remain.

---

## src/main/telegram-daemon.ts - Polling Daemon

Single-process daemon that polls for Telegram messages, routes them, and dispatches to agents sequentially.

### How It Works

1. **Poll** - Long-polls `getUpdates` with 30-second timeout, `allowed_updates: ['message']`
2. **Filter** - Only accepts messages from the configured `TELEGRAM_CHAT_ID` (matches both `from.id` and `chat.id`)
3. **Intercept utility commands** - `/status`, `/mute` handled directly
4. **Route** - Passes message through `routeMessage()`
5. **Dispatch** - Invokes each target agent one at a time via `dispatchToAgent()`
6. **Respond** - Sends each agent's response to Telegram with emoji prefix
7. **Persist** - Saves `_lastUpdateId` to state file after each poll

### Agent Dispatch

```typescript
async function dispatchToAgent(agentName: string, text: string): Promise<string | null>
```

The dispatch function:
1. Saves the current agent name
2. Calls `config.reloadForAgent(agentName)` and `memory.initDb()` to switch context
3. Loads the system prompt via `loadSystemPrompt()`
4. Gets the last CLI session ID from memory for session continuity
5. Prepends `[Telegram message from Will]` to the message text
6. Runs `streamInference()` and collects the full response
7. Restores the original agent config
8. Returns the response text or `null`

```typescript
function sendAgentResponse(agentName: string, text: string): void
```

Loads the agent's manifest to get `telegram_emoji` and `display_name`, prepends them to the response, and sends via `sendMessage()` with `prefix=false` (to avoid double-prefixing).

### Race Condition Prevention

Sequential dispatch is the core safety mechanism:

- **No concurrent agents** - agent A completes all tool calls before agent B starts
- **Instance lock** - `O_EXLOCK` on macOS (with pid-check fallback on other platforms) prevents two daemon instances from running simultaneously
- **Single poller** - one process owns the update offset, no contention on `getUpdates`
- **Isolated memory** - each agent has its own SQLite database (no cross-agent writes)

The only concurrent Telegram activity is cron jobs (heartbeat, morning brief) sending messages independently. This is safe because they're independent fire-and-forget POSTs to different conversations.

### Instance Locking

```typescript
export function acquireLock(): boolean
```

Opens `~/.atrophy/.telegram_daemon.lock` with `O_WRONLY | O_CREAT | O_EXLOCK | O_NONBLOCK`:
- `O_EXLOCK` (0x20): macOS advisory exclusive lock on open
- `O_NONBLOCK` (0x4000): fail immediately if lock is held

On success, writes the current PID to the lock file. On `EAGAIN`/`EWOULDBLOCK`, another instance holds the lock - returns false.

If `O_EXLOCK` is not supported (Linux), falls back to `acquireLockFallback()`:
1. Read the PID from the lock file
2. Check if that process is alive via `process.kill(pid, 0)`
3. If dead (or file corrupt), reclaim by writing own PID
4. Open the file with `O_RDONLY` to keep a reference

```typescript
export function releaseLock(): void
```

Closes the lock file descriptor and unlinks the lock file. Safe to call even if no lock is held.

### Utility Commands

| Command | Action |
|---------|--------|
| `/status` | Lists all agents with emoji, display name, slash command, and state (active/muted/disabled) |
| `/mute` | Toggles mute on the default agent |
| `/mute agent_name` | Toggles mute on a specific agent (matches by name or display_name, case-insensitive) |

### State Persistence

The daemon tracks `last_update_id` in `~/.atrophy/.telegram_daemon_state.json`:

```json
{"last_update_id": 123456789}
```

Loaded on daemon start, saved after each poll cycle. This prevents re-processing old messages after a daemon restart or system reboot.

### Daemon Control

```typescript
export function startDaemon(intervalMs?: number): boolean  // default 10000
export function stopDaemon(): void
export function isDaemonRunning(): boolean
```

`startDaemon()`:
1. Checks if already running
2. Acquires the instance lock (returns false if another instance is running)
3. Loads the last update ID from state file
4. Sets the module-level `_lastUpdateId` and syncs to the telegram module
5. Runs an initial poll
6. Sets up recurring `setInterval` polls

`stopDaemon()`:
1. Clears the poll timer
2. Sets running flag to false
3. Releases the instance lock

### Operating Modes

The daemon can run in three modes:

- **Managed** - started from within the Electron main process via `startDaemon()`, polls on a configurable interval (default 10 seconds)
- **Continuous** - as a launchd agent with `KeepAlive: true`, launched via `--telegram-daemon` flag
- **Single poll** - one-shot execution for testing or cron-triggered runs

### launchd Management

```typescript
export function installLaunchd(electronBin: string): void
export function uninstallLaunchd(): void
export function isLaunchdInstalled(): boolean
```

The launchd plist is:
- Label: `com.atrophiedmind.telegram-daemon`
- Path: `~/Library/LaunchAgents/com.atrophiedmind.telegram-daemon.plist`
- `KeepAlive: true` and `RunAtLoad: true`
- Stdout: `~/.atrophy/logs/telegram_daemon.log`
- Stderr: `~/.atrophy/logs/telegram_daemon.err`
- Environment: `PATH` is inherited from the current process

`installLaunchd()` unloads the existing plist if present, writes the new one, and loads it via `launchctl`. The plist XML is hand-built with proper escaping via `escapeXml()`.

### Error Recovery

- API poll errors are caught and logged but do not stop the daemon
- Individual message dispatch failures are caught per-agent and do not block other agents
- If the Telegram API returns null (network error), the poll is skipped and retried on the next interval
- The daemon continues running even if all agents fail to respond

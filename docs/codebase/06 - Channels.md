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

## src/main/telegram.ts - Bot API Client

Telegram Bot API integration. Pure HTTP via `fetch()` (Node built-in undici) - no third-party Telegram libraries.

### Sending

```typescript
export async function sendMessage(
  text: string,
  chatId?: string,
  prefix?: boolean,
): Promise<boolean>
```

Send a plain Markdown message. When `prefix=true` (default), prepends the agent's emoji and display name so the recipient knows which agent is speaking. Returns `true` on success.

```typescript
export async function sendButtons(
  text: string,
  buttons: { text: string; callback_data: string }[][],
  chatId?: string,
  prefix?: boolean,
): Promise<number | null>
```

Send a message with an inline keyboard. Each inner list is a row of buttons. Returns `message_id` for tracking replies.

Button format:
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

Send an audio file as a Telegram voice note via multipart file upload (`sendVoice` API for OGG/OGA files, `sendAudio` for others). Optional caption is displayed below the voice note. Returns `true` on success. Used by the `voice-note.ts` job and the `telegram_voice` delivery method in `run-task.ts`.

### Receiving

```typescript
export async function pollCallback(
  timeoutSecs?: number,
  chatId?: string,
): Promise<string | null>
```

Long-poll for an inline keyboard callback. Polls in 30-second windows until a callback from the target user is received. Automatically answers the callback query (removes the loading spinner). Returns `callback_data` or `null` on timeout.

```typescript
export async function pollReply(
  timeoutSecs?: number,
  chatId?: string,
): Promise<string | null>
```

Long-poll for a text message reply. Same polling pattern. Returns message text or `null` on timeout.

### High-Level

```typescript
export async function askConfirm(text: string, timeoutSecs?: number): Promise<boolean | null>
```

Send a confirmation prompt with Yes/No buttons. Returns `true`, `false`, or `null` (timeout). Flushes old updates before sending to avoid stale responses.

```typescript
export async function askQuestion(text: string, timeoutSecs?: number): Promise<string | null>
```

Send a question and wait for a text reply.

### Bot Command Registration

Bot command registration is built into `telegram.ts` rather than being a separate script.

```typescript
export async function registerBotCommands(): Promise<boolean>
```

Scans all discovered agents via `discoverAgents()` and registers one `/agent_name` command per agent (description from manifest), plus `/status` and `/mute` utility commands. Uses the Telegram `setMyCommands` API. Commands are automatically re-registered when a new agent is created.

```typescript
export async function clearBotCommands(): Promise<boolean>
```

Removes all bot commands from the Telegram API via `deleteMyCommands`.

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

## src/main/router.ts - Message Router

Two-tier routing system that decides which agent(s) should handle an incoming Telegram message.

### Tier 1: Explicit Routing (Free)

Pattern matching - no LLM call:

| Pattern | Example | Behaviour |
|---------|---------|-----------|
| `/agent_name` | `/companion what's up` | Route to named agent, strip prefix |
| `@agent_name` | `@companion thoughts?` | Route to mentioned agent(s) |
| `agent_name:` | `companion: hey` | Route to named agent, strip prefix |
| Wake word | `hey darling` | Route to agent with matching wake word |
| Multiple names | `companion and monty, debate this` | Route to all named agents |

### Tier 2: Routing Agent (Haiku)

When no explicit match is found, a lightweight LLM call classifies the message:

```typescript
async function routeViaAgent(text: string, agents: AgentInfo[]): Promise<string[]>
```

Uses `runInferenceOneshot()` with `claude-haiku-4-5-20251001` at low effort. The routing agent sees all available agents with their descriptions and returns a JSON array of agent slugs. Falls back to the first agent (default companion) on failure.

### API

```typescript
export async function routeMessage(text: string): Promise<RoutingDecision>
```

Returns a `RoutingDecision` with:
- `agents` - list of agent slugs to handle the message
- `tier` - `"explicit"`, `"agent"`, `"single"`, or `"none"`
- `text` - cleaned message text (prefix stripped for explicit routes)

### Short-circuit

If only one agent is enabled, routing is skipped entirely (`tier="single"`).

### Routing Queue

The router includes a file-based IPC mechanism for daemon coordination via `~/.atrophy/.telegram_routes.json`:

```typescript
export function enqueueRoute(messageId: number, text: string, decision: RoutingDecision): void
export function dequeueRoute(agentName: string): RouteEntry | null
```

The queue keeps the last 50 entries and allows daemons to consume routed messages asynchronously.

## src/main/telegram-daemon.ts - Polling Daemon

Single-process daemon that polls for Telegram messages, routes them, and dispatches to agents sequentially.

### How It Works

1. **Poll** - Long-polls `getUpdates` with 30-second timeout
2. **Filter** - Only accepts messages from the configured `TELEGRAM_CHAT_ID`
3. **Intercept utility commands** - `/status`, `/mute` handled directly
4. **Route** - Passes message through `routeMessage()`
5. **Dispatch** - Invokes each target agent one at a time via `streamInference()`
6. **Respond** - Sends each agent's response to Telegram with emoji prefix

### Race Condition Prevention

Sequential dispatch is the core safety mechanism:

- **No concurrent agents** - agent A completes all tool calls before agent B starts
- **Instance lock** - `O_EXLOCK` on macOS (with pid-check fallback on other platforms) prevents two daemon instances from running simultaneously
- **Single poller** - one process owns the update offset, no contention on `getUpdates`
- **Isolated memory** - each agent has its own SQLite database (no cross-agent writes)

The only concurrent Telegram activity is cron jobs (heartbeat, morning brief) sending messages independently. This is safe because they're independent fire-and-forget POSTs to different conversations.

### Instance Locking

The daemon uses `O_EXLOCK | O_NONBLOCK` on macOS for file-level exclusive locking at `~/.atrophy/.telegram_daemon.lock`. This is equivalent to Python's `fcntl.flock` with `LOCK_EX | LOCK_NB`. On platforms that do not support `O_EXLOCK`, it falls back to a pid-check strategy: read the pid from the lock file, check if that process is alive, and reclaim if stale.

```typescript
export function acquireLock(): boolean
export function releaseLock(): void
```

### Utility Commands

| Command | Action |
|---------|--------|
| `/status` | Lists all agents with their current state (active/muted/disabled) |
| `/mute` | Toggles mute on the default agent |
| `/mute agent_name` | Toggles mute on a specific agent |

### State Persistence

The daemon tracks `last_update_id` in `~/.atrophy/.telegram_daemon_state.json` across restarts. This prevents re-processing old messages after a daemon restart or system reboot.

### Daemon Control

```typescript
export function startDaemon(intervalMs?: number): boolean
export function stopDaemon(): void
export function isDaemonRunning(): boolean
```

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

The launchd plist uses `KeepAlive: true` and `RunAtLoad: true`. Logs go to `~/.atrophy/logs/telegram_daemon.log`. The plist is labelled `com.atrophiedmind.telegram-daemon` and installed to `~/Library/LaunchAgents/`.

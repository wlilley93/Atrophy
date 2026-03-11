# Channels

External communication channels beyond the direct conversation interface.

## Architecture

All agents share a single Telegram bot. A central daemon polls for messages, routes them to the right agent(s), and dispatches responses sequentially. This eliminates race conditions -- no two agents ever run concurrently.

```
Telegram Bot API
  ↓
channels/telegram_daemon.py  (single poller)
  ↓
channels/router.py           (explicit match → routing agent)
  ↓
Sequential dispatch           (agent A responds fully, then agent B)
  ↓
channels/telegram.py          (send with emoji prefix)
```

## channels/telegram.py -- Bot API Client

Telegram Bot API integration. Pure HTTP via `urllib` -- no third-party Telegram libraries.

### Sending

```python
def send_message(text: str, chat_id: str = "", prefix: bool = True) -> bool
```

Send a plain Markdown message. When `prefix=True` (default), prepends the agent's emoji and display name so the recipient knows which agent is speaking. Returns `True` on success.

```python
def send_buttons(text: str, buttons: list[list[dict]], chat_id: str = "", prefix: bool = True) -> int | None
```

Send a message with an inline keyboard. Each inner list is a row of buttons. Returns `message_id` for tracking replies.

Button format:
```python
[[{"text": "Yes", "callback_data": "yes"}, {"text": "No", "callback_data": "no"}]]
```

### Receiving

```python
def poll_callback(timeout_secs: int = 120, chat_id: str = "") -> str | None
```

Long-poll for an inline keyboard callback. Polls in 30-second windows until a callback from the target user is received. Automatically answers the callback query (removes the loading spinner). Returns `callback_data` or `None` on timeout.

```python
def poll_reply(timeout_secs: int = 120, chat_id: str = "") -> str | None
```

Long-poll for a text message reply. Same polling pattern. Returns message text or `None` on timeout.

### High-Level

```python
def ask_confirm(text: str, timeout_secs: int = 120) -> bool | None
```

Send a confirmation prompt with Yes/No buttons. Returns `True`, `False`, or `None` (timeout). Flushes old updates before sending to avoid stale responses.

```python
def ask_question(text: str, timeout_secs: int = 120) -> str | None
```

Send a question and wait for a text reply.

### Configuration

Per-agent from `agent.json`:

```json
{
  "telegram": {
    "bot_token_env": "TELEGRAM_BOT_TOKEN",
    "chat_id_env": "TELEGRAM_CHAT_ID"
  },
  "telegram_emoji": "🌙"
}
```

The env var names themselves are configurable, allowing multiple agents to use different Telegram bots. The `telegram_emoji` appears before the agent's name in all outgoing messages.

### Usage

The Telegram channel is used by:

- **Telegram daemon**: Receives and dispatches routed messages
- **`ask_will` MCP tool**: Sends questions during conversation and blocks for a reply
- **`send_telegram` MCP tool**: Proactive outreach (rate limited to 5/day)
- **`heartbeat` daemon**: Evaluates whether to reach out and sends messages
- **`gift` daemon**: Delivers unprompted notes

### Implementation Notes

- Uses `urllib.request` directly -- no `requests` or `telegram` library dependency
- Long-polling with `getUpdates` (no webhooks)
- Tracks `_last_update_id` globally to avoid re-processing old updates
- `_flush_old_updates()` consumes pending updates before any polling operation
- All API calls have a 15-second timeout
- Errors are logged but don't raise -- functions return `None`/`False` on failure

## channels/router.py -- Message Router

Two-tier routing system that decides which agent(s) should handle an incoming Telegram message.

### Tier 1: Explicit Routing (Free)

Pattern matching -- no LLM call:

| Pattern | Example | Behaviour |
|---------|---------|-----------|
| `/agent_name` | `/companion what's up` | Route to named agent, strip prefix |
| `@agent_name` | `@companion thoughts?` | Route to mentioned agent(s) |
| `agent_name:` | `companion: hey` | Route to named agent, strip prefix |
| Wake word | `hey darling` | Route to agent with matching wake word |
| Multiple names | `companion and monty, debate this` | Route to all named agents |

### Tier 2: Routing Agent (Haiku)

When no explicit match is found, a lightweight LLM call classifies the message:

```python
def _route_via_agent(text: str, agents: list[dict]) -> list[str]
```

Uses `run_inference_oneshot()` with `claude-haiku-4-5-20251001` at low effort. The routing agent sees all available agents with their descriptions and returns a JSON array of agent slugs. Falls back to the first agent (default companion) on failure.

### API

```python
def route_message(text: str) -> RoutingDecision
```

Returns a `RoutingDecision` with:
- `agents` -- list of agent slugs to handle the message
- `tier` -- `"explicit"`, `"agent"`, `"single"`, or `"none"`
- `text` -- cleaned message text (prefix stripped for explicit routes)

### Short-circuit

If only one agent is enabled, routing is skipped entirely (`tier="single"`).

## channels/telegram_daemon.py -- Polling Daemon

Single-process daemon that polls for Telegram messages, routes them, and dispatches to agents sequentially.

### How It Works

1. **Poll** -- Long-polls `getUpdates` with 30-second timeout
2. **Filter** -- Only accepts messages from the configured `TELEGRAM_CHAT_ID`
3. **Intercept utility commands** -- `/status`, `/mute` handled directly
4. **Route** -- Passes message through `router.route_message()`
5. **Dispatch** -- Invokes each target agent one at a time via `stream_inference()`
6. **Respond** -- Sends each agent's response to Telegram with emoji prefix

### Race Condition Prevention

Sequential dispatch is the core safety mechanism:

- **No concurrent agents** -- agent A completes all tool calls before agent B starts
- **Instance lock** -- `fcntl.flock` prevents two daemon instances from running simultaneously
- **Single poller** -- one process owns the update offset, no contention on `getUpdates`
- **Isolated memory** -- each agent has its own SQLite database (no cross-agent writes)

The only concurrent Telegram activity is cron jobs (heartbeat, morning brief) sending messages independently. This is safe because they're independent fire-and-forget POSTs to different conversations.

### Utility Commands

| Command | Action |
|---------|--------|
| `/status` | Lists all agents with their current state (active/muted/disabled) |
| `/mute` | Toggles mute on the default agent |
| `/mute agent_name` | Toggles mute on a specific agent |

### State Persistence

The daemon tracks `last_update_id` in `~/.atrophy/.telegram_daemon_state.json` across restarts. This prevents re-processing old messages after a daemon restart or system reboot.

### Management

```bash
python channels/telegram_daemon.py --install    # Install as launchd agent (continuous)
python channels/telegram_daemon.py --uninstall  # Stop and remove from launchd
python channels/telegram_daemon.py --loop       # Run in foreground (continuous)
python channels/telegram_daemon.py              # Single poll (testing/cron)
```

The launchd plist uses `KeepAlive: true` and `RunAtLoad: true`. Logs go to `~/.atrophy/logs/telegram_daemon.log`.

## scripts/register_telegram_commands.py -- Bot Command Registration

Registers `/agent_name` commands with the Telegram Bot API so users get autocomplete in the Telegram command menu.

```bash
python scripts/register_telegram_commands.py           # Register all agent commands
python scripts/register_telegram_commands.py --clear   # Remove all commands
```

Scans all enabled agents via `discover_agents()` and registers:
- One `/agent_name` command per agent (description from manifest)
- `/status` -- show active agents
- `/mute` -- toggle mute

Commands are automatically re-registered when a new agent is created via `scripts/create_agent.py`.

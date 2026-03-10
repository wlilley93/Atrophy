# Channels

External communication channels beyond the direct conversation interface.

## channels/telegram.py

Telegram Bot API integration. Pure HTTP via `urllib` -- no third-party Telegram libraries.

### Sending

```python
def send_message(text: str, chat_id: str = "") -> bool
```

Send a plain Markdown message. Returns `True` on success.

```python
def send_buttons(text: str, buttons: list[list[dict]], chat_id: str = "") -> int | None
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
  }
}
```

The env var names themselves are configurable, allowing multiple agents to use different Telegram bots.

### Usage

The Telegram channel is used by:

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

# scripts/agents/shared/credentials.py - Shared Credential Loading

**Line count:** ~50 lines  
**Dependencies:** `os`, `json`, `pathlib`  
**Purpose:** Load Telegram credentials from environment with agent-specific fallbacks

## Overview

This module provides a shared function for loading Telegram bot tokens and chat IDs across all agent scripts. It implements a three-tier fallback:
1. Agent-specific environment variables (e.g., `TELEGRAM_BOT_TOKEN_MONTGOMERY`)
2. Manifest env var references (`channels.telegram.bot_token_env`)
3. Generic environment variables (`TELEGRAM_BOT_TOKEN`)

## load_telegram_credentials

```python
def load_telegram_credentials(agent_name: str = "") -> tuple[str, str]:
    """Load Telegram bot token and chat ID from environment.

    Tries agent-specific env vars first (e.g. TELEGRAM_BOT_TOKEN_MONTGOMERY),
    then falls back to reading the agent manifest's env var references,
    then falls back to generic TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.

    Returns (bot_token, chat_id). Raises RuntimeError if not found.
    """
    if not agent_name:
        agent_name = os.environ.get("AGENT", "")

    # Try agent-specific env vars (uppercase agent name)
    suffix = agent_name.upper().replace("-", "_")
    token = os.environ.get(f"TELEGRAM_BOT_TOKEN_{suffix}", "")
    chat_id = os.environ.get(f"TELEGRAM_CHAT_ID_{suffix}", "")

    # Try reading env var names from agent manifest
    if not token or not chat_id:
        home = os.environ.get("HOME", str(Path.home()))
        manifest_path = os.path.join(home, ".atrophy", "agents", agent_name, "data", "agent.json")
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            channels = manifest.get("channels", {}).get("telegram", {})
            token_env = channels.get("bot_token_env", "")
            chat_id_env = channels.get("chat_id_env", "")
            if token_env and not token:
                token = os.environ.get(token_env, "")
            if chat_id_env and not chat_id:
                chat_id = os.environ.get(chat_id_env, "")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    # Final fallback to generic env vars
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not chat_id:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        raise RuntimeError(
            f"Missing Telegram credentials for agent '{agent_name}'. "
            f"Set TELEGRAM_BOT_TOKEN_{suffix} and TELEGRAM_CHAT_ID_{suffix} in ~/.atrophy/.env"
        )

    return token, chat_id
```

## Fallback Order

```
┌─────────────────────────────────────────────────────────────┐
│              Credential Resolution Flow                      │
│                                                               │
│  1. Agent-specific env vars                                   │
│     TELEGRAM_BOT_TOKEN_{AGENT}                               │
│     TELEGRAM_CHAT_ID_{AGENT}                                 │
│                                                               │
│         │ (if not found)                                      │
│         ▼                                                     │
│  2. Manifest env var references                               │
│     channels.telegram.bot_token_env                          │
│     channels.telegram.chat_id_env                            │
│                                                               │
│         │ (if not found)                                      │
│         ▼                                                     │
│  3. Generic env vars                                          │
│     TELEGRAM_BOT_TOKEN                                       │
│     TELEGRAM_CHAT_ID                                         │
│                                                               │
│         │ (if not found)                                      │
│         ▼                                                     │
│  4. RuntimeError                                              │
└─────────────────────────────────────────────────────────────┘
```

## Usage Example

```python
from credentials import load_telegram_credentials

# Get credentials for current agent (from AGENT env var)
bot_token, chat_id = load_telegram_credentials()

# Or specify agent explicitly
bot_token, chat_id = load_telegram_credentials("montgomery")

# Use with Telegram API
await send_message(bot_token, chat_id, "Hello!")
```

## Environment Variable Setup

In `~/.atrophy/.env`:

```bash
# Generic fallback
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890

# Agent-specific (optional, overrides generic)
TELEGRAM_BOT_TOKEN_XAN=7123456789:AAHxan123456
TELEGRAM_CHAT_ID_XAN=-1009876543210

TELEGRAM_BOT_TOKEN_MONTGOMERY=7987654321:AAHmont123456
TELEGRAM_CHAT_ID_MONTGOMERY=-1001122334455
```

## Agent Manifest Setup

In `~/.atrophy/agents/<name>/data/agent.json`:

```json
{
  "channels": {
    "telegram": {
      "bot_token_env": "MY_CUSTOM_TOKEN_ENV",
      "chat_id_env": "MY_CUSTOM_CHAT_ID_ENV"
    }
  }
}
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Agent name not provided | Uses `AGENT` env var, defaults to `""` |
| Agent-specific env not set | Falls back to manifest references |
| Manifest not found | Falls back to generic env vars |
| No credentials found | Raises `RuntimeError` with helpful message |

## Files Using This Module

- `scripts/agents/*/heartbeat.py` - Heartbeat job
- `scripts/agents/*/morning_brief.py` - Morning brief job
- `scripts/agents/*/voice_note.py` - Voice note job
- `scripts/agents/*/gift.py` - Gift job
- `scripts/agents/*/run_task.py` - Task runner

## See Also

- [`src/main/channels/telegram/api.ts`](files/src/main/channels/telegram/api.md) - Telegram Bot API client
- [`src/main/channels/telegram/daemon.ts`](files/src/main/channels/telegram/daemon.md) - Telegram polling daemon
- [`src/main/config.ts`](files/src/main/config.md) - Configuration system with Telegram support

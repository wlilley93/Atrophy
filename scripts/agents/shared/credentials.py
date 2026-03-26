"""Shared credential loading for agent scripts.

Loads Telegram bot tokens and chat IDs from environment variables.
The cron runner sets the AGENT env var and injects per-agent env vars
from ~/.atrophy/.env, so credentials are available at runtime.
"""

import os
import json
from pathlib import Path


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

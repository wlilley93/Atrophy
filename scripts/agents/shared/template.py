#!/usr/bin/env python3
"""
TEMPLATE: Agent script template.

Copy this file to scripts/agents/<agent_name>/<script_name>.py
and fill in the TODO sections.

This template provides:
- Correct path resolution (portable, no hardcoded paths)
- Shared utility imports (credentials, telegram, claude_cli)
- Proper logging setup
- Error handling with graceful degradation

After creating the script, register it as a job in the agent's manifest:
  agent.json -> jobs -> { "your_job": { "cron": "...", "script": "scripts/agents/<name>/<script>.py" } }
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup - NEVER use hardcoded absolute paths
# ---------------------------------------------------------------------------

# Project root (scripts/agents/<agent>/<script>.py -> 4 parents up)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # shared/ access

# Agent name from environment (set by cron runner)
AGENT_NAME = os.environ.get("AGENT", "unknown")

# Standard paths
_HOME = Path.home()
_ATROPHY_DIR = _HOME / ".atrophy"
_AGENT_DIR = _ATROPHY_DIR / "agents" / AGENT_NAME
_DATA_DIR = _AGENT_DIR / "data"
_AGENT_JSON = _DATA_DIR / "agent.json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(Path(__file__).stem)

# ---------------------------------------------------------------------------
# Shared utilities - use these instead of writing your own
# ---------------------------------------------------------------------------

# Telegram credentials (from env vars, NOT from agent.json directly)
from shared.credentials import load_telegram_credentials

# Telegram message sending
from shared.telegram_utils import send_telegram

# Claude CLI wrapper (for LLM calls)
from shared.claude_cli import call_claude

# ---------------------------------------------------------------------------
# Script logic - TODO: replace with your implementation
# ---------------------------------------------------------------------------


def main():
    log.info(f"Starting {Path(__file__).stem} for agent {AGENT_NAME}")

    # Example: load credentials and send a message
    # token, chat_id = load_telegram_credentials(AGENT_NAME)
    # send_telegram(token, chat_id, "Hello from script template")

    # Example: call Claude for analysis
    # result = call_claude(
    #     system="You are an analyst.",
    #     prompt="Summarise the current situation.",
    #     model="sonnet",
    # )

    # Print output for the cron runner to capture
    # (only printed output with route_output_to="self" triggers agent inference)
    print("Script completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"Script failed: {e}", exc_info=True)
        sys.exit(1)

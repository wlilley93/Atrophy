#!/usr/bin/env python3
"""Telegram polling daemon — single process, sequential agent dispatch.

Polls the shared Telegram bot for incoming messages. Routes each message
via the router (explicit match → routing agent), then dispatches to target
agent(s) one at a time. Sequential dispatch eliminates race conditions —
no two agents ever run concurrently.

Designed to run as a launchd interval job (e.g. every 10 seconds) or as
a long-running daemon with its own poll loop.

Usage:
    python -m channels.telegram_daemon          # poll once
    python -m channels.telegram_daemon --loop   # continuous polling
"""
import fcntl
import json
import logging
import os
import sys
import time
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, USER_DATA,
    AGENT_NAME, BUNDLE_ROOT,
)
from channels.telegram import send_message, _post, _last_update_id
from channels.router import route_message, RoutingDecision

log = logging.getLogger("telegram_daemon")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

# State file — tracks last processed update_id across runs
_STATE_FILE = USER_DATA / ".telegram_daemon_state.json"

# Lock file — prevents concurrent daemon instances
_LOCK_FILE = USER_DATA / ".telegram_daemon.lock"


# ── State persistence ──

def _load_last_update_id() -> int:
    if _STATE_FILE.exists():
        try:
            state = json.loads(_STATE_FILE.read_text())
            return state.get("last_update_id", 0)
        except (json.JSONDecodeError, OSError):
            pass
    return 0


def _save_last_update_id(update_id: int):
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps({"last_update_id": update_id}) + "\n")


# ── Agent dispatch ──

def _dispatch_to_agent(agent_name: str, text: str, chat_id: str) -> str | None:
    """Invoke an agent to respond to a message. Returns response text or None.

    Uses run_inference_oneshot for simplicity — the agent gets the message,
    its full system prompt, and MCP tools. Runs synchronously.
    """
    # Temporarily switch AGENT env so config loads the right agent
    original_agent = os.environ.get("AGENT", "")
    os.environ["AGENT"] = agent_name

    try:
        # Reload config for this agent
        from importlib import reload
        import config as config_mod
        reload(config_mod)

        from core.context import load_system_prompt
        from core.inference import stream_inference, TextDelta, ToolUse, StreamDone, StreamError
        from core.memory import get_last_cli_session_id

        system = load_system_prompt()
        cli_session_id = get_last_cli_session_id()

        prompt = f"[Telegram message from Will]\n\n{text}"
        full_text = ""
        tools_used = []

        for event in stream_inference(prompt, system, cli_session_id):
            if isinstance(event, TextDelta):
                pass
            elif isinstance(event, ToolUse):
                tools_used.append(event.name)
                log.info("  [%s] tool → %s", agent_name, event.name)
            elif isinstance(event, StreamDone):
                full_text = event.full_text
            elif isinstance(event, StreamError):
                log.error("  [%s] inference error: %s", agent_name, event.message)
                return None

        if tools_used:
            log.info("  [%s] used tools: %s", agent_name, ", ".join(tools_used))

        return full_text.strip() if full_text else None

    except Exception as e:
        log.error("  [%s] dispatch failed: %s", agent_name, e)
        return None
    finally:
        # Restore original agent
        if original_agent:
            os.environ["AGENT"] = original_agent
        else:
            os.environ.pop("AGENT", None)
        from importlib import reload
        import config as config_mod
        reload(config_mod)


def _send_agent_response(agent_name: str, text: str):
    """Send an agent's response to Telegram with emoji prefix."""
    # Load agent manifest to get emoji
    for base in [USER_DATA / "agents" / agent_name, BUNDLE_ROOT / "agents" / agent_name]:
        mpath = base / "data" / "agent.json"
        if mpath.exists():
            try:
                manifest = json.loads(mpath.read_text())
                emoji = manifest.get("telegram_emoji", "")
                display = manifest.get("display_name", agent_name.title())
                if emoji:
                    text = f"{emoji} *{display}*\n\n{text}"
                break
            except (json.JSONDecodeError, OSError):
                pass

    send_message(text, prefix=False)  # prefix=False since we added our own


# ── Utility commands ──

def _handle_status_command():
    """Respond to /status with a list of active agents."""
    from core.agent_manager import discover_agents, get_agent_state

    lines = ["*Active agents:*\n"]
    for agent in discover_agents():
        name = agent["name"]
        state = get_agent_state(name)
        enabled = state.get("enabled", True)
        muted = state.get("muted", False)

        # Load emoji from manifest
        emoji = ""
        for base in [USER_DATA / "agents" / name, BUNDLE_ROOT / "agents" / name]:
            mpath = base / "data" / "agent.json"
            if mpath.exists():
                try:
                    manifest = json.loads(mpath.read_text())
                    emoji = manifest.get("telegram_emoji", "")
                except (json.JSONDecodeError, OSError):
                    pass
                break

        status = "active"
        if not enabled:
            status = "disabled"
        elif muted:
            status = "muted"

        prefix = emoji + " " if emoji else ""
        lines.append(f"{prefix}*{agent['display_name']}* (`/{name}`) — {status}")

    send_message("\n".join(lines), prefix=False)


def _handle_mute_command(text: str):
    """Handle /mute or /mute agent_name."""
    from core.agent_manager import discover_agents, get_agent_state, set_agent_state

    parts = text.strip().split()
    agents = discover_agents()

    if len(parts) < 2:
        # Toggle mute on the first (default) agent
        if agents:
            target = agents[0]["name"]
        else:
            send_message("No agents available.", prefix=False)
            return
    else:
        target = parts[1].lower().lstrip("/")

    # Find the agent
    found = None
    for a in agents:
        if a["name"] == target or a["display_name"].lower() == target:
            found = a
            break

    if not found:
        send_message(f"Unknown agent: `{target}`", prefix=False)
        return

    state = get_agent_state(found["name"])
    new_muted = not state.get("muted", False)
    set_agent_state(found["name"], muted=new_muted)

    verb = "muted" if new_muted else "unmuted"
    send_message(f"*{found['display_name']}* {verb}.", prefix=False)


# ── Polling ──

def _poll_once(last_update_id: int) -> int:
    """Poll for new messages, route and dispatch. Returns new last_update_id."""
    if not TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not configured")
        return last_update_id

    result = _post("getUpdates", {
        "offset": last_update_id + 1,
        "timeout": 30,
        "allowed_updates": ["message"],
    })

    if result is None:
        return last_update_id

    for update in result:
        update_id = update["update_id"]
        last_update_id = max(last_update_id, update_id)

        msg = update.get("message")
        if not msg or not msg.get("text"):
            continue

        # Only accept messages from the configured chat
        sender_id = str(msg.get("from", {}).get("id", ""))
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if TELEGRAM_CHAT_ID and sender_id != TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
            log.debug("Ignoring message from %s (expected %s)", sender_id, TELEGRAM_CHAT_ID)
            continue

        text = msg["text"].strip()
        if not text:
            continue

        log.info("Received: %s", text[:80])

        # Handle utility commands before routing
        if text.lower() == "/status":
            _handle_status_command()
            continue
        if text.lower().startswith("/mute"):
            _handle_mute_command(text)
            continue

        # Route the message
        decision = route_message(text)
        log.info("Routed: %s", decision)

        if not decision.agents:
            log.warning("No agents available to handle message")
            continue

        # Dispatch to each agent sequentially — no race conditions
        for agent_name in decision.agents:
            log.info("Dispatching to %s...", agent_name)
            response = _dispatch_to_agent(agent_name, decision.text, chat_id)
            if response:
                _send_agent_response(agent_name, response)
                log.info("  [%s] responded (%d chars)", agent_name, len(response))
            else:
                log.warning("  [%s] no response", agent_name)

    return last_update_id


# ── Instance locking ──

_lock_fd = None

def _acquire_lock() -> bool:
    """Acquire exclusive daemon lock. Returns False if another instance is running."""
    global _lock_fd
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _lock_fd = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        return True
    except BlockingIOError:
        _lock_fd.close()
        _lock_fd = None
        return False


def _release_lock():
    global _lock_fd
    if _lock_fd:
        fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        _lock_fd.close()
        _lock_fd = None


# ── launchd install/uninstall ──

_PLIST_LABEL = "com.atrophiedmind.telegram-daemon"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_PLIST_LABEL}.plist"


def _install_launchd():
    """Install the daemon as a launchd agent (continuous polling)."""
    import plistlib
    import subprocess

    project_root = Path(__file__).resolve().parent.parent
    python_bin = sys.executable
    script = str(project_root / "channels" / "telegram_daemon.py")
    log_dir = USER_DATA / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    plist = {
        "Label": _PLIST_LABEL,
        "ProgramArguments": [python_bin, script, "--loop"],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_dir / "telegram_daemon.log"),
        "StandardErrorPath": str(log_dir / "telegram_daemon.err"),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        },
    }

    # Unload first if already installed
    if _PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(_PLIST_PATH)],
                       capture_output=True)

    _PLIST_PATH.write_bytes(plistlib.dumps(plist))
    subprocess.run(["launchctl", "load", str(_PLIST_PATH)], check=True)
    print(f"Installed: {_PLIST_PATH}")
    print("Telegram daemon is now running.")


def _uninstall_launchd():
    """Uninstall the daemon from launchd."""
    import subprocess

    if _PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(_PLIST_PATH)],
                       capture_output=True)
        _PLIST_PATH.unlink()
        print(f"Uninstalled: {_PLIST_PATH}")
    else:
        print("Not installed.")


# ── Entry point ──

def main():
    if "--install" in sys.argv:
        _install_launchd()
        return
    if "--uninstall" in sys.argv:
        _uninstall_launchd()
        return

    if not _acquire_lock():
        log.info("Another daemon instance is running. Exiting.")
        return

    try:
        last_id = _load_last_update_id()
        loop_mode = "--loop" in sys.argv

        if loop_mode:
            log.info("Starting continuous polling (last_update_id=%d)...", last_id)
            while True:
                last_id = _poll_once(last_id)
                _save_last_update_id(last_id)
        else:
            # Single poll — for launchd interval jobs
            last_id = _poll_once(last_id)
            _save_last_update_id(last_id)
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        _release_lock()


if __name__ == "__main__":
    main()

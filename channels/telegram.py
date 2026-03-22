"""Python Telegram Bot API helpers for agent scripts.

Sends text messages and voice notes via the Telegram Bot API.
Uses config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID which
are resolved per-agent from the manifest at import time.
"""
import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path

log = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"


def _get_credentials() -> tuple[str, str]:
    """Resolve Telegram bot token and chat ID from config."""
    try:
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        return TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    except ImportError:
        # Fallback to env vars
        return (
            os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            os.environ.get("TELEGRAM_CHAT_ID", ""),
        )


def send_message(text: str, parse_mode: str | None = "Markdown") -> bool:
    """Send a text message via Telegram Bot API.

    Returns True on success, False on failure. Never raises.
    """
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        log.warning("Telegram not configured - skipping send_message")
        return False

    url = _API.format(token=token, method="sendMessage")
    body: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        body["parse_mode"] = parse_mode
    payload = json.dumps(body).encode()

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log.error("send_message failed: %s", e)
        return False


def send_voice_note(audio_path: str, caption: str | None = None) -> bool:
    """Send an audio file as a Telegram voice note.

    Expects OGG Opus for proper voice note display, but any audio format
    will be accepted by Telegram (just displayed as an audio file instead).

    Returns True on success, False on failure. Never raises.
    """
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        log.warning("Telegram not configured - skipping send_voice_note")
        return False

    path = Path(audio_path)
    if not path.exists() or path.stat().st_size == 0:
        log.error("Voice note file missing or empty: %s", audio_path)
        return False

    # Build multipart/form-data manually (no requests dependency)
    boundary = "----AtrophyVoiceNote"
    body = bytearray()

    # chat_id field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'.encode()
    body += f"{chat_id}\r\n".encode()

    # caption field (optional)
    if caption:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="caption"\r\n\r\n'.encode()
        body += f"{caption}\r\n".encode()

    # voice file field
    body += f"--{boundary}\r\n".encode()
    body += (
        f'Content-Disposition: form-data; name="voice"; '
        f'filename="{path.name}"\r\n'
    ).encode()
    body += f"Content-Type: audio/ogg\r\n\r\n".encode()
    body += path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()

    url = _API.format(token=token, method="sendVoice")
    req = urllib.request.Request(
        url, data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log.error("send_voice_note failed: %s", e)
        return False


def send_audio(audio_path: str, caption: str | None = None) -> bool:
    """Send an audio file as a Telegram audio message (not voice note).

    Use this for MP3/WAV files that shouldn't display as voice notes.
    """
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        log.warning("Telegram not configured - skipping send_audio")
        return False

    path = Path(audio_path)
    if not path.exists() or path.stat().st_size == 0:
        log.error("Audio file missing or empty: %s", audio_path)
        return False

    boundary = "----AtrophyAudio"
    body = bytearray()

    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'.encode()
    body += f"{chat_id}\r\n".encode()

    if caption:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="caption"\r\n\r\n'.encode()
        body += f"{caption}\r\n".encode()

    body += f"--{boundary}\r\n".encode()
    body += (
        f'Content-Disposition: form-data; name="audio"; '
        f'filename="{path.name}"\r\n'
    ).encode()
    body += f"Content-Type: audio/mpeg\r\n\r\n".encode()
    body += path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()

    url = _API.format(token=token, method="sendAudio")
    req = urllib.request.Request(
        url, data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log.error("send_audio failed: %s", e)
        return False


# Stubs for MCP memory_server.py interactive tools
# These require a polling-based implementation that doesn't exist yet
def ask_confirm(question: str) -> bool:
    """Placeholder - interactive confirmation not yet supported from scripts."""
    log.warning("ask_confirm not implemented for script context: %s", question)
    return False


def ask_question(question: str) -> str:
    """Placeholder - interactive questioning not yet supported from scripts."""
    log.warning("ask_question not implemented for script context: %s", question)
    return ""

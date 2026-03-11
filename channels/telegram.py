"""Telegram channel - send and receive via Bot API.

Uses inline keyboards for confirmations/permissions and polls for
text replies to questions. No webhooks - pure HTTP polling with
urllib so there are no extra dependencies.
"""
import json
import logging
import time
import urllib.request
import urllib.error
from pathlib import Path

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, AGENT_DISPLAY_NAME, TELEGRAM_EMOJI

log = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}"

# Track last processed update to avoid re-reading old ones
_last_update_id = 0


def _api_url(method: str) -> str:
    return f"{_API_BASE.format(token=TELEGRAM_BOT_TOKEN)}/{method}"


def _post(method: str, payload: dict) -> dict | None:
    """POST to Telegram Bot API. Returns parsed result or None."""
    if not TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not configured")
        return None

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        _api_url(method),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                return result.get("result")
            log.error("Telegram API error: %s", result)
            return None
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        log.error("Telegram HTTP %d: %s", e.code, body)
        return None
    except Exception as e:
        log.error("Telegram error: %s", e)
        return None


# ── Sending ──


def send_message(text: str, chat_id: str = "", prefix: bool = True) -> bool:
    """Send a plain Telegram message. Returns True on success.

    When prefix=True (default), prepends the agent's emoji and name
    so the recipient knows which agent is speaking.
    """
    target = chat_id or TELEGRAM_CHAT_ID
    if not target:
        log.error("TELEGRAM_CHAT_ID not configured")
        return False

    if prefix and TELEGRAM_EMOJI:
        text = f"{TELEGRAM_EMOJI} *{AGENT_DISPLAY_NAME}*\n\n{text}"

    result = _post("sendMessage", {
        "chat_id": target,
        "text": text,
        "parse_mode": "Markdown",
    })
    if result:
        log.info("Sent Telegram message (%d chars)", len(text))
        return True
    return False


def send_buttons(text: str, buttons: list[list[dict]], chat_id: str = "",
                  prefix: bool = True) -> int | None:
    """Send a message with an inline keyboard. Returns message_id or None.

    buttons format: [[{"text": "Yes", "callback_data": "yes"}, ...], ...]
    Each inner list is a row of buttons.
    """
    target = chat_id or TELEGRAM_CHAT_ID
    if not target:
        log.error("TELEGRAM_CHAT_ID not configured")
        return None

    if prefix and TELEGRAM_EMOJI:
        text = f"{TELEGRAM_EMOJI} *{AGENT_DISPLAY_NAME}*\n\n{text}"

    result = _post("sendMessage", {
        "chat_id": target,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": buttons},
    })
    if result:
        log.info("Sent Telegram buttons (%d chars)", len(text))
        return result.get("message_id")
    return None


def send_voice_note(audio_path: str, caption: str = "", chat_id: str = "",
                    prefix: bool = True) -> bool:
    """Send a voice note (OGG/OPUS) via Telegram. Returns True on success.

    Telegram requires voice notes in OGG Opus format. If the file is not OGG,
    it will be sent as a document instead.
    """
    target = chat_id or TELEGRAM_CHAT_ID
    if not target:
        log.error("TELEGRAM_CHAT_ID not configured")
        return False

    if prefix and TELEGRAM_EMOJI and caption:
        caption = f"{TELEGRAM_EMOJI} *{AGENT_DISPLAY_NAME}*\n\n{caption}"

    import mimetypes
    mime = mimetypes.guess_type(audio_path)[0] or ""

    try:
        # Build multipart form data
        import uuid
        boundary = uuid.uuid4().hex
        body = b""

        # chat_id field
        body += f"--{boundary}\r\n".encode()
        body += b"Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n"
        body += f"{target}\r\n".encode()

        # caption field (if any)
        if caption:
            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"caption\"\r\n\r\n"
            body += f"{caption}\r\n".encode()
            body += f"--{boundary}\r\n".encode()
            body += b"Content-Disposition: form-data; name=\"parse_mode\"\r\n\r\n"
            body += b"Markdown\r\n"

        # Voice/audio file
        with open(audio_path, "rb") as f:
            file_data = f.read()

        filename = Path(audio_path).name
        # Use sendVoice for OGG, sendAudio for others
        if "ogg" in mime or audio_path.endswith(".ogg") or audio_path.endswith(".oga"):
            method = "sendVoice"
            field_name = "voice"
        else:
            method = "sendAudio"
            field_name = "audio"

        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
        body += f"Content-Type: {mime or 'audio/ogg'}\r\n\r\n".encode()
        body += file_data
        body += f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            _api_url(method),
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                log.info("Sent voice note via Telegram (%d bytes)", len(file_data))
                return True
            log.error("Telegram voice note error: %s", result)
            return False
    except Exception as e:
        log.error("Telegram voice note error: %s", e)
        return False


# ── Receiving ──


def _flush_old_updates():
    """Consume any pending updates so we only see new ones."""
    global _last_update_id
    result = _post("getUpdates", {"offset": _last_update_id + 1, "timeout": 0})
    if result:
        for update in result:
            _last_update_id = max(_last_update_id, update["update_id"])


def poll_callback(timeout_secs: int = 120, chat_id: str = "") -> str | None:
    """Poll for an inline keyboard callback. Returns callback_data or None.

    Answers the callback query automatically (removes loading spinner).
    """
    global _last_update_id
    target = chat_id or TELEGRAM_CHAT_ID
    deadline = time.time() + timeout_secs

    while time.time() < deadline:
        remaining = max(1, int(deadline - time.time()))
        poll_time = min(remaining, 30)  # Telegram long-poll max 30s

        result = _post("getUpdates", {
            "offset": _last_update_id + 1,
            "timeout": poll_time,
            "allowed_updates": ["callback_query", "message"],
        })
        if result is None:
            time.sleep(2)
            continue

        for update in result:
            _last_update_id = max(_last_update_id, update["update_id"])

            cb = update.get("callback_query")
            if cb and str(cb.get("from", {}).get("id")) == target:
                # Answer the callback (removes spinner)
                _post("answerCallbackQuery", {
                    "callback_query_id": cb["id"],
                })
                return cb.get("data")

    return None  # timed out


def poll_reply(timeout_secs: int = 120, chat_id: str = "") -> str | None:
    """Poll for a text message reply. Returns message text or None."""
    global _last_update_id
    target = chat_id or TELEGRAM_CHAT_ID
    deadline = time.time() + timeout_secs

    while time.time() < deadline:
        remaining = max(1, int(deadline - time.time()))
        poll_time = min(remaining, 30)

        result = _post("getUpdates", {
            "offset": _last_update_id + 1,
            "timeout": poll_time,
            "allowed_updates": ["message"],
        })
        if result is None:
            time.sleep(2)
            continue

        for update in result:
            _last_update_id = max(_last_update_id, update["update_id"])

            msg = update.get("message")
            if msg and str(msg.get("from", {}).get("id")) == target and msg.get("text"):
                return msg["text"]

    return None  # timed out


# ── High-level: ask and wait ──


def ask_confirm(text: str, timeout_secs: int = 120) -> bool | None:
    """Send a confirmation prompt with Yes/No buttons. Returns True/False/None (timeout)."""
    _flush_old_updates()

    buttons = [[
        {"text": "Yes", "callback_data": "yes"},
        {"text": "No", "callback_data": "no"},
    ]]
    msg_id = send_buttons(text, buttons)
    if not msg_id:
        return None

    response = poll_callback(timeout_secs)
    if response == "yes":
        return True
    elif response == "no":
        return False
    return None


def ask_question(text: str, timeout_secs: int = 120) -> str | None:
    """Send a question and wait for a text reply. Returns reply or None (timeout)."""
    _flush_old_updates()

    if not send_message(text):
        return None

    return poll_reply(timeout_secs)

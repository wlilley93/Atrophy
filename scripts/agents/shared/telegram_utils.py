"""Shared Telegram utilities for agent scripts.

Provides send_telegram() and send_voice_note() for all agent scripts.
Loads credentials via the shared credentials module.
"""

import json
import os
import urllib.request
import urllib.parse
from pathlib import Path


def send_telegram(token: str, chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
    """Send a text message via Telegram Bot API.

    Splits messages >4096 chars at paragraph boundaries.
    Returns True if all parts sent successfully.
    """
    MAX_LEN = 4096
    chunks = _split_message(text, MAX_LEN)
    ok = True
    for chunk in chunks:
        try:
            payload = json.dumps({
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
            }).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print(f"[telegram] Send failed: {e}")
            ok = False
    return ok


def send_voice_note(token: str, chat_id: str, audio_path: str, caption: str = "") -> bool:
    """Send a voice note via Telegram Bot API."""
    try:
        import mimetypes
        boundary = "----AtrophyBoundary"
        body = []

        body.append(f"--{boundary}\r\n")
        body.append(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n')

        if caption:
            body.append(f"--{boundary}\r\n")
            body.append(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n')

        mime_type = mimetypes.guess_type(audio_path)[0] or "audio/ogg"
        filename = os.path.basename(audio_path)
        body.append(f"--{boundary}\r\n")
        body.append(f'Content-Disposition: form-data; name="voice"; filename="{filename}"\r\n')
        body.append(f"Content-Type: {mime_type}\r\n\r\n")

        text_part = "".join(body).encode()
        with open(audio_path, "rb") as f:
            file_data = f.read()
        end_part = f"\r\n--{boundary}--\r\n".encode()

        data = text_part + file_data + end_part
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendVoice",
            data=data,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception as e:
        print(f"[telegram] Voice send failed: {e}")
        return False


def _split_message(text: str, max_len: int) -> list[str]:
    """Split a message at paragraph boundaries to fit within max_len."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > max_len:
            if current:
                chunks.append(current.strip())
            current = paragraph
        else:
            current = current + "\n\n" + paragraph if current else paragraph

    if current.strip():
        chunks.append(current.strip())

    # Final safety: hard-split any chunk still over max_len
    result = []
    for chunk in chunks:
        while len(chunk) > max_len:
            result.append(chunk[:max_len])
            chunk = chunk[max_len:]
        if chunk:
            result.append(chunk)

    return result

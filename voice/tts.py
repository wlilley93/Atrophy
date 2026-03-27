"""TTS synthesis via ElevenLabs REST API.

Used by cron jobs that run outside a Claude session.
Reads credentials and settings from config.py.
"""
import hashlib
import time
import urllib.request
import urllib.error
import json
from pathlib import Path


def synthesise_sync(text: str) -> Path:
    """Synthesise text, save to tts_output/, return the Path."""
    import sys
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    from config import (
        ELEVENLABS_API_KEY,
        ELEVENLABS_VOICE_ID,
        ELEVENLABS_MODEL,
        ELEVENLABS_STABILITY,
        ELEVENLABS_SIMILARITY,
        ELEVENLABS_STYLE,
    )

    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set")
    if not ELEVENLABS_VOICE_ID:
        raise RuntimeError("ELEVENLABS_VOICE_ID not set")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    payload = json.dumps({
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": ELEVENLABS_STABILITY,
            "similarity_boost": ELEVENLABS_SIMILARITY,
            "style": ELEVENLABS_STYLE,
            "use_speaker_boost": True,
        },
    }).encode()

    auth_header = "xi-api-key"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            auth_header: ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"ElevenLabs {e.code}: {body}")

    out_dir = Path.home() / ".atrophy" / "tts_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]
    out_path = out_dir / f"tts_{ts}_{text_hash}.mp3"
    out_path.write_bytes(audio)
    return out_path

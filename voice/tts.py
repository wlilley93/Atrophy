"""Text-to-speech — async, three-tier fallback.

Chain: ElevenLabs streaming → ElevenLabs batch → Fal → macOS say.

ElevenLabs streaming is primary for lowest latency (audio bytes arrive
while still being generated). Batch and Fal are fallbacks.

Interface:
    await synthesise(text) -> Path          (generate audio file)
    synthesise_sync(text) -> Path           (blocking, for use in threads)
    await synthesise_stream(text) -> Path   (streaming, faster first byte)
    await play(path)                        (play through speakers)
    await speak(text)                       (synthesise + play)
"""
import asyncio
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

from config import (
    TTS_BACKEND, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID,
    ELEVENLABS_MODEL, ELEVENLABS_STABILITY, ELEVENLABS_SIMILARITY,
    ELEVENLABS_STYLE, FAL_TTS_ENDPOINT, FAL_VOICE_ID,
    TTS_PLAYBACK_RATE,
)

_TAG_RE = re.compile(r"\[[\w\s]+\]")
_CODE_BLOCK_RE = re.compile(r'```[\s\S]*?```')
_INLINE_CODE_RE = re.compile(r'`[^`]+`')

_PROSODY_RE = re.compile(r'\[([^\]]+)\]')

_PROSODY_MAP = {
    # tag -> (stability_delta, similarity_delta, style_delta)
    'whispers': (0.2, 0.0, -0.2),
    'barely audible': (0.2, 0.0, -0.2),
    'quietly': (0.15, 0.0, -0.15),
    'hushed': (0.2, 0.0, -0.2),
    'softer': (0.1, 0.0, -0.1),
    'lower': (0.1, 0.0, -0.1),
    'warmly': (0.0, 0.1, 0.2),
    'tenderly': (0.05, 0.1, 0.2),
    'gently': (0.05, 0.1, 0.15),
    'firm': (-0.1, 0.0, 0.3),
    'frustrated': (-0.1, 0.0, 0.3),
    'excited': (-0.15, 0.0, 0.1),
    'quickly': (-0.15, 0.0, 0.0),
    'faster now': (-0.15, 0.0, 0.0),
    'wry': (0.0, 0.0, 0.15),
    'dry': (0.1, 0.0, -0.1),
    'sardonic': (0.0, 0.0, 0.2),
    'raw': (-0.1, 0.0, 0.25),
    'vulnerable': (0.0, 0.1, 0.15),
    'heavy': (0.1, 0.0, 0.1),
    'slowly': (0.15, 0.0, 0.0),
    'uncertain': (0.0, 0.0, 0.1),
    'hesitant': (0.05, 0.0, 0.05),
    'nervous': (-0.1, 0.0, 0.15),
    'reluctant': (0.05, 0.0, 0.1),
    'tired': (0.15, 0.0, -0.1),
    'sorrowful': (0.1, 0.1, 0.15),
    'grieving': (0.1, 0.1, 0.2),
    'resigned': (0.15, 0.0, -0.1),
    'haunted': (0.05, 0.05, 0.15),
    'melancholic': (0.1, 0.1, 0.1),
    'nostalgic': (0.05, 0.1, 0.15),
    'voice breaking': (-0.15, 0.0, 0.3),
    'laughs softly': (0.0, 0.0, 0.2),
    'laughs bitterly': (-0.05, 0.0, 0.25),
    'smirks': (0.0, 0.0, 0.15),
    'emphasis': (0.0, 0.0, 0.0),
}

# Breath/pause replacements
_BREATH_TAGS = {
    'breath': '...',
    'inhales slowly': '... ...',
    'exhales': '...',
    'sighs': '...',
    'sighs quietly': '...',
    'clears throat': '...',
    'pause': '. . .',
    'long pause': '. . . . .',
    'trailing off': '...',
    'gulps': '...',
}


def _process_prosody(text: str) -> tuple[str, dict]:
    """Strip audio tags, extract voice setting deltas."""
    stability_d = 0.0
    similarity_d = 0.0
    style_d = 0.0

    def _replace(match):
        nonlocal stability_d, similarity_d, style_d
        tag = match.group(1).lower().strip()

        # Breath/pause → text replacement
        if tag in _BREATH_TAGS:
            return _BREATH_TAGS[tag]

        # Prosody → voice settings
        if tag in _PROSODY_MAP:
            sd, sim_d, sty_d = _PROSODY_MAP[tag]
            stability_d += sd
            similarity_d += sim_d
            style_d += sty_d
            return ''

        # Unknown tag → strip
        return ''

    cleaned = _PROSODY_RE.sub(_replace, text).strip()
    # Clean up multiple spaces
    cleaned = re.sub(r'  +', ' ', cleaned)
    # Strip text that is only punctuation/whitespace (ElevenLabs rejects these)
    if cleaned and not re.sub(r'[\s.\-,;:!?\u2026]+', '', cleaned):
        cleaned = ''

    overrides = {}
    if stability_d != 0:
        overrides['stability'] = stability_d
    if similarity_d != 0:
        overrides['similarity_boost'] = similarity_d
    if style_d != 0:
        overrides['style'] = style_d

    return cleaned, overrides


# ── Main interfaces ──

async def synthesise(text: str) -> Path:
    """Generate speech audio file. Returns path to audio."""
    # Strip code blocks before processing
    text = _CODE_BLOCK_RE.sub('', text)
    text = _INLINE_CODE_RE.sub('', text)
    # Strip tags and check for empty text
    cleaned, _ = _process_prosody(text)
    # Skip if empty or too short — ElevenLabs hallucinates on tiny fragments
    if not cleaned or len(cleaned.strip()) < 8:
        tmp = tempfile.NamedTemporaryFile(suffix=".aiff", delete=False)
        tmp.close()
        return Path(tmp.name)

    # Primary: Fal
    if FAL_VOICE_ID:
        try:
            return await _synthesise_fal(text)
        except Exception as e:
            print(f"[TTS] Fal failed ({e}), trying ElevenLabs...")

    # Fallback: ElevenLabs streaming
    if ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID:
        try:
            return await _synthesise_elevenlabs_stream(text)
        except Exception as e:
            print(f"[TTS] ElevenLabs failed ({e}), falling back to macOS")

    return await _synthesise_macos(text)


def synthesise_sync(text: str) -> Path:
    """Blocking synthesise — for use in QThread workers."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(synthesise(text))
    finally:
        loop.close()


async def play(audio_path: Path) -> None:
    """Play audio file through system speakers."""
    proc = await asyncio.create_subprocess_exec(
        "afplay", "-r", str(TTS_PLAYBACK_RATE), str(audio_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


def play_sync(audio_path: Path) -> None:
    """Blocking play — for use in threads."""
    subprocess.run(
        ["afplay", "-r", str(TTS_PLAYBACK_RATE), str(audio_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def speak(text: str) -> Path:
    """Convenience: synthesise + play. Returns audio path."""
    path = await synthesise(text)
    await play(path)
    return path


# ── ElevenLabs streaming (primary — lowest latency) ──

async def _synthesise_elevenlabs_stream(text: str) -> Path:
    """ElevenLabs streaming endpoint. Audio bytes arrive while generating."""
    text, prosody_overrides = _process_prosody(text)

    if not text or not text.strip():
        raise ValueError("Empty text after prosody stripping")

    # Clamp overrides to ±0.15 — enough to be expressive without losing coherence
    stab_d = max(-0.15, min(0.15, prosody_overrides.get('stability', 0)))
    sim_d = max(-0.15, min(0.15, prosody_overrides.get('similarity_boost', 0)))
    sty_d = max(-0.15, min(0.15, prosody_overrides.get('style', 0)))
    stab = max(0.0, min(1.0, ELEVENLABS_STABILITY + stab_d))
    sim = max(0.0, min(1.0, ELEVENLABS_SIMILARITY + sim_d))
    sty = max(0.0, min(1.0, ELEVENLABS_STYLE + sty_d))

    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech"
        f"/{ELEVENLABS_VOICE_ID}/stream"
        f"?output_format=mp3_44100_128"
    )
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": stab,
            "similarity_boost": sim,
            "style": sty,
        },
    }

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)

    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST", url, json=payload, headers=headers, timeout=30.0
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"ElevenLabs {response.status_code}: {body.decode(errors='replace')[:300]}"
                )
            async for chunk in response.aiter_bytes(chunk_size=4096):
                tmp.write(chunk)

    tmp.close()
    return Path(tmp.name)


# ── Fal ElevenLabs v3 (fallback) ──

async def _synthesise_fal(text: str) -> Path:
    import fal_client

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: fal_client.subscribe(
            FAL_TTS_ENDPOINT,
            arguments={
                "text": text,
                "voice": FAL_VOICE_ID,
                "stability": ELEVENLABS_STABILITY,
            },
        ),
    )

    audio_url = result["audio"]["url"]

    async with httpx.AsyncClient() as client:
        response = await client.get(audio_url, timeout=30.0)
        response.raise_for_status()

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.write(response.content)
    tmp.close()
    return Path(tmp.name)


# ── macOS say (last resort) ──

async def _synthesise_macos(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".aiff", delete=False)
    tmp.close()
    audio_path = Path(tmp.name)

    clean = _TAG_RE.sub("", text).strip()

    proc = await asyncio.create_subprocess_exec(
        "say", "-v", "Samantha", "-r", "175", "-o", str(audio_path), clean,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return audio_path

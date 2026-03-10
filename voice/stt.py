"""Speech-to-text via whisper.cpp with Metal acceleration."""
import subprocess
import tempfile
import wave
import numpy as np
from pathlib import Path

from config import WHISPER_BIN, WHISPER_MODEL, WHISPER_PATH, SAMPLE_RATE, CHANNELS

# Tiny model for fast wake-word detection (same as WHISPER_MODEL if already tiny)
_WHISPER_MODEL_TINY = WHISPER_PATH / "models" / "ggml-tiny.en.bin"


def transcribe(audio_data: np.ndarray) -> str:
    """Transcribe numpy float32 audio array to text.

    Args:
        audio_data: float32 numpy array, mono, 16kHz

    Returns:
        Transcribed text string, empty if nothing detected.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = Path(f.name)
        with wave.open(f.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit PCM
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio_data * 32767).astype(np.int16).tobytes())

    try:
        result = subprocess.run(
            [
                str(WHISPER_BIN),
                "-m", str(WHISPER_MODEL),
                "-f", str(tmp_path),
                "--no-timestamps",
                "-t", "4",
                "--language", "en",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return ""

        # whisper.cpp outputs metadata lines starting with [ — skip those
        lines = []
        for line in result.stdout.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("["):
                lines.append(stripped)

        return " ".join(lines)

    finally:
        tmp_path.unlink(missing_ok=True)


def transcribe_fast(audio_data: np.ndarray) -> str:
    """Fast transcription optimised for short (2-second) clips.

    Uses whisper.cpp tiny model with minimal settings for speed.
    Designed for wake word detection — completes in <200ms on Metal
    for a 2-second clip.

    Args:
        audio_data: float32 numpy array, mono, 16kHz

    Returns:
        Transcribed text string, empty if nothing detected.
    """
    model = _WHISPER_MODEL_TINY if _WHISPER_MODEL_TINY.exists() else WHISPER_MODEL

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = Path(f.name)
        with wave.open(f.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit PCM
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio_data * 32767).astype(np.int16).tobytes())

    try:
        result = subprocess.run(
            [
                str(WHISPER_BIN),
                "-m", str(model),
                "-f", str(tmp_path),
                "--no-timestamps",
                "-t", "2",          # fewer threads — lighter footprint
                "--language", "en",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return ""

        lines = []
        for line in result.stdout.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("["):
                lines.append(stripped)

        return " ".join(lines)

    finally:
        tmp_path.unlink(missing_ok=True)

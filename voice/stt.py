"""Speech-to-text via whisper.cpp with Metal acceleration."""
import subprocess
import tempfile
import wave
import numpy as np
from pathlib import Path

from config import WHISPER_BIN, WHISPER_MODEL, SAMPLE_RATE, CHANNELS


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

"""Wake word detection - ambient listening with local keyword detection.

Uses a lightweight approach: continuously record short audio chunks,
run whisper.cpp transcription on each chunk, check for wake word.
All processing is local - audio never leaves the machine.
"""
import logging
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

from config import (
    SAMPLE_RATE, CHANNELS, WAKE_WORDS, WAKE_CHUNK_SECONDS,
    WHISPER_BIN, WHISPER_MODEL,
)
from voice.stt import transcribe_fast

log = logging.getLogger(__name__)


class WakeWordListener:
    """Ambient wake word detector using whisper.cpp keyword spotting.

    Records 2-second audio chunks, transcribes each with whisper tiny,
    and fires a callback when a wake word is detected.
    """

    def __init__(
        self,
        wake_words: list[str] | None = None,
        callback: callable = None,
    ):
        self._wake_words = [w.strip().lower() for w in (wake_words or WAKE_WORDS)]
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._running = False
        self._paused = False
        self._lock = threading.Lock()

    @property
    def is_listening(self) -> bool:
        return self._running and not self._paused

    def start(self):
        """Begin ambient listening in a background daemon thread."""
        if self._running:
            return

        # Pre-flight: check dependencies
        if not Path(WHISPER_BIN).exists():
            log.warning("Wake word: whisper binary not found at %s", WHISPER_BIN)
            return
        if not Path(WHISPER_MODEL).exists():
            log.warning("Wake word: whisper model not found at %s", WHISPER_MODEL)
            return

        try:
            import sounddevice  # noqa: F401
        except ImportError:
            log.warning("Wake word: sounddevice not available")
            return

        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        log.info("Wake word listener started (words: %s)", self._wake_words)

    def stop(self):
        """Stop listening entirely."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("Wake word listener stopped")

    def pause(self):
        """Pause listening (during TTS playback or active conversation)."""
        self._paused = True

    def resume(self):
        """Resume listening after a pause."""
        self._paused = False

    def _listen_loop(self):
        """Main loop: record chunks, transcribe, check for wake words."""
        import sounddevice as sd

        chunk_samples = int(SAMPLE_RATE * WAKE_CHUNK_SECONDS)

        while self._running:
            # Skip recording while paused - check frequently to stay responsive
            if self._paused:
                import time
                time.sleep(0.2)
                continue

            try:
                # Record a short chunk
                audio = sd.rec(
                    chunk_samples,
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="float32",
                    blocking=True,
                )

                if not self._running or self._paused:
                    continue

                audio = audio.flatten()

                # Skip near-silent chunks (RMS below threshold)
                rms = np.sqrt(np.mean(audio ** 2))
                if rms < 0.005:
                    continue

                # Transcribe the chunk
                text = transcribe_fast(audio)
                if not text:
                    continue

                text_lower = text.lower().strip()
                log.debug("Wake word chunk: '%s'", text_lower)

                # Check for wake word match
                if self._matches(text_lower):
                    log.info("Wake word detected: '%s'", text_lower)
                    self._paused = True  # auto-pause until explicitly resumed
                    if self._callback:
                        try:
                            self._callback()
                        except Exception:
                            log.exception("Wake word callback error")

            except Exception:
                if self._running:
                    log.exception("Wake word listen loop error")
                    import time
                    time.sleep(1.0)  # back off on errors

    def _matches(self, text: str) -> bool:
        """Check if transcribed text contains any wake word (fuzzy)."""
        for word in self._wake_words:
            if word in text:
                return True
        return False

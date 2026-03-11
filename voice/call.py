"""Voice call - hands-free continuous conversation loop.

Captures audio from the mic, detects speech via energy + silence,
transcribes with whisper, runs inference, speaks the response via
ElevenLabs TTS. Repeats until stopped.

The ambient video keeps playing - this only touches audio I/O.
"""
import numpy as np
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from config import SAMPLE_RATE, CHANNELS

# ── Audio capture parameters ──
ENERGY_THRESHOLD = 0.015       # RMS energy to detect speech
SILENCE_DURATION = 1.5         # Seconds of silence to end an utterance
MIN_SPEECH_DURATION = 0.5      # Minimum seconds of speech to process
CHUNK_SAMPLES = 1600           # 100ms chunks at 16kHz
MAX_UTTERANCE_SEC = 30         # Safety cap on utterance length


class VoiceCall(QThread):
    """Runs a hands-free voice conversation in a background thread.

    Signals:
        status_changed(str)   - "listening", "thinking", "speaking", "idle"
        user_said(str)        - transcribed user speech
        agent_said(str)       - agent response text
        error(str)            - error message
        call_ended()          - call terminated
    """
    status_changed = pyqtSignal(str)
    user_said = pyqtSignal(str)
    agent_said = pyqtSignal(str)
    error = pyqtSignal(str)
    call_ended = pyqtSignal()

    def __init__(self, system_prompt: str, cli_session_id: str | None,
                 session=None, synth_fn=None):
        super().__init__()
        self._system = system_prompt
        self._cli_session_id = cli_session_id
        self._session = session
        self._synth_fn = synth_fn   # synthesise_sync(text) -> Path
        self._running = False
        self._muted = False          # Mic muted (listen but don't process)

    @property
    def cli_session_id(self):
        return self._cli_session_id

    def stop(self):
        self._running = False

    def set_muted(self, muted: bool):
        self._muted = muted

    def run(self):
        self._running = True
        try:
            import sounddevice as sd
        except ImportError:
            self.error.emit("sounddevice not installed - voice call unavailable")
            self.call_ended.emit()
            return

        self.status_changed.emit("listening")

        while self._running:
            try:
                audio = self._capture_utterance(sd)
                if audio is None or not self._running:
                    break

                if len(audio) / SAMPLE_RATE < MIN_SPEECH_DURATION:
                    continue

                # Transcribe
                self.status_changed.emit("thinking")
                from voice.stt import transcribe
                text = transcribe(audio)
                if not text or len(text.strip()) < 2:
                    self.status_changed.emit("listening")
                    continue

                self.user_said.emit(text.strip())

                # Record turn
                if self._session:
                    self._session.add_turn("will", text.strip())

                # Inference
                response = self._run_inference(text.strip())
                if not response or not self._running:
                    self.status_changed.emit("listening")
                    continue

                self.agent_said.emit(response)

                # Record turn
                if self._session:
                    self._session.add_turn("agent", response)

                # Speak
                self.status_changed.emit("speaking")
                self._speak(response)

                self.status_changed.emit("listening")

            except Exception as e:
                self.error.emit(str(e))
                if self._running:
                    self.status_changed.emit("listening")

        self.status_changed.emit("idle")
        self.call_ended.emit()

    def _capture_utterance(self, sd) -> np.ndarray | None:
        """Record until speech ends (silence detection)."""
        chunks = []
        silent_chunks = 0
        speech_started = False
        silence_chunks_needed = int(SILENCE_DURATION * SAMPLE_RATE / CHUNK_SAMPLES)
        max_chunks = int(MAX_UTTERANCE_SEC * SAMPLE_RATE / CHUNK_SAMPLES)

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                dtype='float32', blocksize=CHUNK_SAMPLES) as stream:
                for _ in range(max_chunks):
                    if not self._running:
                        return None

                    data, _ = stream.read(CHUNK_SAMPLES)
                    chunk = data.flatten()

                    if self._muted:
                        silent_chunks += 1
                        continue

                    rms = np.sqrt(np.mean(chunk ** 2))

                    if rms > ENERGY_THRESHOLD:
                        speech_started = True
                        silent_chunks = 0
                        chunks.append(chunk)
                    elif speech_started:
                        silent_chunks += 1
                        chunks.append(chunk)  # Keep trailing audio
                        if silent_chunks >= silence_chunks_needed:
                            break
                    # else: still waiting for speech to start

        except Exception as e:
            self.error.emit(f"Mic error: {e}")
            return None

        if not chunks:
            return None

        return np.concatenate(chunks)

    def _run_inference(self, text: str) -> str | None:
        """Run inference through the Claude CLI."""
        from core.inference import run_inference_turn
        try:
            response, session_id = run_inference_turn(
                text, self._system, self._cli_session_id,
            )
            if session_id:
                self._cli_session_id = session_id
                if self._session:
                    self._session.set_cli_session_id(session_id)
            return response
        except Exception as e:
            self.error.emit(f"Inference error: {e}")
            return None

    def _speak(self, text: str):
        """Synthesise and play TTS."""
        if not self._synth_fn:
            return
        try:
            audio_path = self._synth_fn(text)
            if audio_path and Path(audio_path).exists():
                from voice.tts import play_sync
                play_sync(audio_path)
        except Exception as e:
            self.error.emit(f"TTS error: {e}")

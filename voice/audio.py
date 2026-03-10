"""Audio capture (push-to-talk with Ctrl) and playback.

Push-to-talk: hold left Ctrl to record, release to stop.
Uses pynput for key detection, sounddevice for mic capture.
"""
import asyncio
import threading
import numpy as np
import sounddevice as sd
from pynput import keyboard

from config import SAMPLE_RATE, CHANNELS, MAX_RECORD_SEC


class PushToTalk:
    """Hold Ctrl to record audio from the microphone."""

    def __init__(self):
        self._recording = False
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._done_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listener: keyboard.Listener | None = None

    def _on_press(self, key):
        if key == keyboard.Key.ctrl_l and not self._recording:
            self._recording = True
            self._frames.clear()
            self._start_stream()

    def _on_release(self, key):
        if key == keyboard.Key.ctrl_l and self._recording:
            self._recording = False
            self._stop_stream()
            if self._done_event and self._loop:
                self._loop.call_soon_threadsafe(self._done_event.set)

    def _audio_callback(self, indata, frames, time_info, status):
        if self._recording:
            self._frames.append(indata.copy())

    def _start_stream(self):
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=self._audio_callback,
        )
        self._stream.start()

    def _stop_stream(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def record(self) -> np.ndarray | None:
        """Wait for Ctrl press+release, return recorded audio.

        Returns float32 numpy array (mono, 16kHz) or None if empty.
        """
        self._loop = asyncio.get_event_loop()
        self._done_event = asyncio.Event()

        # Start keyboard listener in background thread
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

        try:
            # Wait for recording to complete (Ctrl released) with timeout
            await asyncio.wait_for(
                self._done_event.wait(),
                timeout=MAX_RECORD_SEC,
            )
        except asyncio.TimeoutError:
            self._recording = False
            self._stop_stream()
        finally:
            self._listener.stop()
            self._listener = None

        if not self._frames:
            return None

        audio = np.concatenate(self._frames, axis=0).flatten()
        if len(audio) < SAMPLE_RATE * 0.3:  # less than 300ms — skip
            return None

        return audio

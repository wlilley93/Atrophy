# Voice Pipeline

The voice system spans four modules: audio capture, speech-to-text, text-to-speech, and wake word detection.

## voice/audio.py -- Push-to-Talk

`PushToTalk` class handles microphone capture via push-to-talk.

- **Key detection**: `pynput` keyboard listener, triggers on left Ctrl press/release
- **Audio capture**: `sounddevice.InputStream` at 16kHz mono, float32
- **Minimum duration**: Clips under 300ms are discarded (accidental taps)
- **Maximum duration**: Configurable via `MAX_RECORD_SEC` (default 120s)

```python
class PushToTalk:
    async def record(self) -> np.ndarray | None
```

The `record()` method is async. It starts a keyboard listener in a background thread, waits for Ctrl press+release, then returns the concatenated audio frames. The keyboard listener is created and destroyed per recording cycle.

## voice/stt.py -- Speech-to-Text

Whisper.cpp with Metal acceleration (Apple Silicon GPU).

**Two modes**:

| Function | Model | Threads | Timeout | Use case |
|----------|-------|---------|---------|----------|
| `transcribe()` | ggml-tiny.en | 4 | 30s | Full conversation turns |
| `transcribe_fast()` | ggml-tiny.en | 2 | 5s | 2-second wake word clips (<200ms) |

**Process**:

1. Convert float32 numpy array to 16-bit PCM WAV in a temp file
2. Call `whisper-cli` subprocess with `--no-timestamps --language en`
3. Parse stdout, skipping metadata lines (those starting with `[`)
4. Delete temp file

The whisper binary path is configured via `WHISPER_BIN` (default: `vendor/whisper.cpp/build/bin/whisper-cli`).

## voice/tts.py -- Text-to-Speech

Three-tier fallback chain with prosody tag support.

### Tier Priority

1. **ElevenLabs v3 streaming** -- Lowest latency. Audio bytes arrive while still being generated via `httpx` async streaming.
2. **Fal** -- ElevenLabs v3 via Fal proxy. Higher latency but alternate endpoint.
3. **macOS `say`** -- Last resort. Samantha voice at 175 WPM.

### Prosody Tags

The agent can embed prosody tags in its output text. These are stripped before sending to TTS but modify voice parameters:

```
[whispers]   -> stability +0.20, style -0.20
[warmly]     -> similarity +0.10, style +0.20
[firmly]     -> stability -0.10, style +0.30
[raw]        -> stability -0.10, style +0.25
[tired]      -> stability +0.15, style -0.10
[laughs softly] -> style +0.20
```

Over 30 tags are supported, covering emotional registers (warm, tender, vulnerable, frustrated), delivery styles (whispers, quietly, firmly, quickly), and paralinguistic cues (breath, sighs, voice breaking, laughs).

Breath/pause tags are replaced with ellipses rather than stripped, creating natural pauses in the audio.

Deltas are clamped to +/-0.15 to prevent extreme voice distortion.

### Per-Agent Voice Config

Voice parameters come from `agent.json`:

```json
{
  "voice": {
    "tts_backend": "elevenlabs",
    "elevenlabs_voice_id": "...",
    "elevenlabs_model": "eleven_v3",
    "elevenlabs_stability": 0.5,
    "elevenlabs_similarity": 0.75,
    "elevenlabs_style": 0.35,
    "playback_rate": 1.12
  }
}
```

### Code Block Handling

Code blocks (both fenced and inline) are stripped before TTS -- the agent shouldn't try to speak code.

### Interface

```python
async def synthesise(text: str) -> Path         # generate audio file
def synthesise_sync(text: str) -> Path          # blocking (for QThread workers)
async def play(audio_path: Path) -> None        # afplay with configurable rate
def play_sync(audio_path: Path) -> None         # blocking play
async def speak(text: str) -> Path              # synthesise + play
```

Playback uses macOS `afplay` with a configurable rate multiplier (default 1.12x).

## voice/wake_word.py -- Wake Word Detection

Background ambient listener using whisper.cpp keyword spotting.

```python
class WakeWordListener:
    def start()    # begin ambient listening (daemon thread)
    def stop()     # stop entirely
    def pause()    # pause during conversation/TTS
    def resume()   # resume after pause
```

**Process loop**:

1. Record a 2-second audio chunk via `sounddevice.rec()` (blocking)
2. Check RMS amplitude -- skip near-silent chunks (< 0.005)
3. Transcribe with `transcribe_fast()` (whisper tiny, <200ms)
4. Check transcription against wake words (substring match)
5. On match: auto-pause, fire callback

Wake words are configurable per-agent (default: `["hey <name>", "<name>"]`). All processing is local -- audio never leaves the machine.

Enabled via `WAKE_WORD_ENABLED=true` environment variable.

## Streaming TTS Pipeline

In both CLI and GUI modes, TTS runs as a parallel pipeline:

```
Inference stream -> SentenceReady events -> TTS queue -> Audio playback queue
                                              |
                                   (synthesise in parallel)
```

1. Inference yields `SentenceReady` events as sentences complete
2. Each sentence is pushed to a TTS queue
3. A TTS worker synthesises sentences in order
4. Audio plays sequentially via `afplay`

In the GUI, `StreamingPipelineWorker` (a QThread) runs inference in one thread and TTS in another. Sentences are displayed immediately as text, then played back as audio catches up.

This means sentence 2 is being synthesised while sentence 1 is playing, and sentence 3 is being streamed while sentence 2 is being synthesised.

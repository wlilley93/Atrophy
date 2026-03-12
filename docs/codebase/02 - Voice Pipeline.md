# Voice Pipeline

The voice system spans five modules across the main and renderer processes: audio capture (renderer + main bridge), speech-to-text, text-to-speech, wake word detection, and voice call mode.

## Temp File Management

Both `tts.ts` and `stt.ts` generate temp files using Node.js built-in `crypto.randomBytes()` and `os.tmpdir()`:

```typescript
function secureTmp(ext: string): string {
  const name = crypto.randomBytes(12).toString('hex') + ext;
  return path.join(os.tmpdir(), 'atrophy-tts-' + name);
}
```

Each module uses its own prefix (`atrophy-tts-`, `atrophy-stt-`) to keep temp files identifiable. Files are deleted after use.

**Why `crypto.randomBytes()` instead of predictable names:** The random filename pattern prevents TOCTOU (time-of-check-time-of-use) race conditions. Python's `NamedTemporaryFile` with `delete=False` follows a create-close-reopen pattern that leaves a window between file creation and the process reopening it for writing. During that window, an attacker could replace the file with a symlink pointing to a sensitive location (a symlink attack), causing the process to overwrite an arbitrary file. By generating an unguessable 12-byte hex filename via `crypto.randomBytes(12)`, the path is effectively unguessable - an attacker cannot predict the filename to create a race condition. The `atrophy-tts-` / `atrophy-stt-` prefixes are for human identification only and do not weaken the randomness of the path.

## src/main/audio.ts - Audio Bridge (Push-to-Talk)

Bridges renderer audio capture with the main process. In the Python version, `pynput` detected Ctrl key presses and `sounddevice` captured audio - both in the same process. In Electron, these responsibilities are split across processes.

- **Key detection**: Renderer listens for Ctrl keydown/keyup on the `window` object, sends IPC signals to main
- **Audio capture**: Renderer uses `navigator.mediaDevices.getUserMedia()` at 16kHz mono with all processing disabled (echoCancellation, noiseSuppression, autoGainControl all `false` - otherwise Chromium switches macOS to "voice processing" audio mode which downsamples all system audio)
- **PCM transport**: Renderer sends Float32Array chunks over `audio:chunk` IPC channel via `ipcRenderer.send()`
- **Minimum duration**: Clips under 300ms are discarded (accidental taps)
- **Maximum duration**: Configurable via `MAX_RECORD_SEC`

### IPC Channels

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `audio:start` | renderer -> main (invoke) | Begin recording, reset chunk buffer |
| `audio:stop` | renderer -> main (invoke) | Stop recording, concatenate chunks, run whisper, return transcription |
| `audio:chunk` | renderer -> main (send) | Stream PCM Float32Array chunks during recording |

### Renderer Side (InputBar.svelte)

Audio capture uses `ScriptProcessorNode` (wider browser support than AudioWorklet for simple capture):

```typescript
const processor = audioContext.createScriptProcessor(4096, 1, 1);
processor.onaudioprocess = (e) => {
  if (!isRecording) return;
  const input = e.inputBuffer.getChannelData(0);
  const buffer = new Float32Array(input);
  api.sendAudioChunk(buffer.buffer);
};
```

Push-to-talk binds to Ctrl key globally:

```typescript
function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key === 'Control' && !isRecording && session.inferenceState === 'idle') {
    startRecording();
  }
}
function onGlobalKeyup(e: KeyboardEvent) {
  if (e.key === 'Control' && isRecording) {
    stopRecording();
  }
}
```

The mic button in the input bar also supports hold-to-record via `onmousedown` / `onmouseup`.

### Main Side (audio.ts)

```typescript
export function registerAudioHandlers(getWindow: () => BrowserWindow | null): void
export function isRecording(): boolean
```

Accumulates Float32Array chunks in a module-level array. On `audio:stop`, concatenates all chunks into a single Float32Array, skips if too short, then calls `transcribe()` from `stt.ts`.

## src/main/stt.ts - Speech-to-Text

Whisper.cpp with Metal acceleration (Apple Silicon GPU).

**Two modes**:

| Function | Model | Threads | Timeout | Use case |
|----------|-------|---------|---------|----------|
| `transcribe()` | ggml-tiny.en | 4 | 30s | Full conversation turns |
| `transcribeFast()` | ggml-tiny.en (prefers ggml-tiny.en.bin if available) | 2 | 5s | 2-second wake word clips (<200ms) |

**Process**:

1. Convert Float32Array to 16-bit PCM WAV via `writeWav()` (writes RIFF header + int16 sample data)
2. Call `whisper-cli` subprocess with `--no-timestamps --language en`
3. Parse stdout, skipping metadata lines (those starting with `[`)
4. Delete temp file

```typescript
export function transcribe(audioData: Float32Array): Promise<string>
export function transcribeFast(audioData: Float32Array): Promise<string>
```

WAV conversion is done inline - float32 samples in [-1, 1] are scaled to int16:

```typescript
const int16 = new Int16Array(audioData.length);
for (let i = 0; i < audioData.length; i++) {
  const s = Math.max(-1, Math.min(1, audioData[i]));
  int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
}
```

The whisper binary path is configured via `WHISPER_BIN` (default: `vendor/whisper.cpp/build/bin/whisper-cli`). The model path is configured via `WHISPER_MODEL`.

## src/main/tts.ts - Text-to-Speech

Three-tier fallback chain with prosody tag support.

### Tier Priority

1. **ElevenLabs streaming** - Lowest latency. Audio bytes fetched via `fetch()` with the streaming endpoint, written to a temp MP3 file.
2. **Fal** - ElevenLabs v3 via Fal proxy. Submit-and-poll REST API with up to 30 retries at 1-second intervals.
3. **macOS `say`** - Last resort. Samantha voice at 175 WPM, outputs to AIFF.

### Prosody Tags

The agent can embed prosody tags in its output text. These are stripped before sending to TTS but modify voice parameters:

```
[whispers]   -> stability +0.20, style -0.20
[warmly]     -> similarity +0.10, style +0.20
[firm]       -> stability -0.10, style +0.30
[raw]        -> stability -0.10, style +0.25
[tired]      -> stability +0.15, style -0.10
[laughs softly] -> style +0.20
```

Over 30 tags are supported, covering emotional registers (warm, tender, vulnerable, frustrated), delivery styles (whispers, quietly, firm, quickly), and paralinguistic cues (breath, sighs, voice breaking, laughs).

Breath/pause tags are replaced with ellipses rather than stripped, creating natural pauses in the audio:

```typescript
const BREATH_TAGS: Record<string, string> = {
  'breath': '...',
  'sighs': '...',
  'pause': '. . .',
  'long pause': '. . . . .',
  'trailing off': '...',
};
```

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

Code blocks (both fenced and inline) are stripped before TTS - the agent shouldn't try to speak code:

```typescript
text = text.replace(CODE_BLOCK_RE, '');
text = text.replace(INLINE_CODE_RE, '');
```

Text that is too short after prosody processing (< 8 characters) is silently skipped.

### Interface

```typescript
export async function synthesise(text: string): Promise<string | null>
export async function synthesiseSync(text: string): Promise<string | null>
export function playAudio(audioPath: string, rate?: number): Promise<void>
export function enqueueAudio(audioPath: string, index: number): void
export function clearAudioQueue(): void
export function setPlaybackCallbacks(callbacks: {
  onStarted?: (index: number) => void;
  onDone?: (index: number) => void;
  onQueueEmpty?: () => void;
}): void
export function stripProsodyTags(text: string): string
```

Playback uses macOS `afplay` with a configurable rate multiplier (default 1.12x). Temp files are deleted after playback completes.

**Note:** There is no combined `speak()` function that synthesises and plays in one call. Synthesis (`synthesise()`) and playback (`playAudio()` / `enqueueAudio()`) are deliberately separate operations. This separation enables the streaming TTS pipeline where sentences are synthesised in parallel while earlier sentences are still playing. In `index.ts`, the inference handler calls `synthesise()` on each `SentenceReady` event and feeds the resulting audio path into `enqueueAudio()` - the queue handles sequential playback independently. For blocking contexts (like the setup wizard), `synthesiseSync()` is available but still returns only a file path - the caller is responsible for playback.

### Audio Playback Queue

TTS audio files are played sequentially through a queue in the main process. The queue supports callbacks for playback lifecycle events:

- `onStarted(index)` - fired when a sentence begins playing
- `onDone(index)` - fired when a sentence finishes playing
- `onQueueEmpty()` - fired when all queued audio has played

These callbacks are forwarded to the renderer via IPC (`tts:started`, `tts:done`, `tts:queueEmpty`) so the UI can show a warm vignette effect during audio playback.

## src/main/wake-word.ts - Wake Word Detection

Background ambient listener using whisper.cpp keyword spotting. This system is **independent of the mic/PTT button** - it runs in its own loop and does not require the user to press any button.

```typescript
export function startWakeWordListener(
  onDetected: () => void,
  getWindow: () => BrowserWindow | null,
): void
export function stopWakeWordListener(getWindow: () => BrowserWindow | null): void
export function pauseWakeWord(): void
export function resumeWakeWord(): void
export function isWakeWordListening(): boolean
export function registerWakeWordHandlers(): void
```

**Architecture** (differs from Python):

In Python, `sounddevice.rec()` captured audio directly in the background thread. In Electron, the renderer captures audio via Web Audio API and sends chunks to main via IPC. The main process tells the renderer to start/stop ambient capture:

- Main sends `wakeword:start` (with chunk duration) to renderer
- Renderer captures audio and sends Float32Array chunks via `wakeword:chunk`
- Main receives chunks, checks RMS energy, runs fast whisper transcription

**Process loop**:

1. Receive audio chunk from renderer via `wakeword:chunk` IPC
2. Check RMS amplitude - skip near-silent chunks (< 0.005)
3. Transcribe with `transcribeFast()` (whisper tiny, <200ms)
4. Check transcription against wake words (case-insensitive substring match)
5. On match: auto-pause, fire callback

Wake words are configurable per-agent (default: `["hey <name>", "<name>"]`). All processing is local - audio never leaves the machine.

Pre-flight checks verify the whisper binary and model exist before starting.

**Enabling wake words:**
- In the GUI, click the microphone-with-waves button in the top-right (shortcut: **Cmd+Shift+W**). The button turns green when active.
- Via environment variable: `WAKE_WORD_ENABLED=true`
- Via the settings panel: Input section > Wake Word Detection toggle

## src/main/call.ts - Voice Call Mode

Hands-free continuous conversation loop. Captures audio from the mic (via renderer IPC chunks), detects speech via energy-based VAD, transcribes with whisper, runs inference, speaks the response via TTS. Repeats until stopped.

### Call State Machine

```
idle -> listening -> thinking -> speaking -> listening -> ...
```

```typescript
export type CallStatus = 'idle' | 'listening' | 'thinking' | 'speaking';

export function startCall(
  systemPrompt: string,
  cliSessionId: string | null,
  getWindow: () => BrowserWindow | null,
): void
export function stopCall(): void
export function isInCall(): boolean
export function isMuted(): boolean
export function setMuted(muted: boolean): void
export function getCallStatus(): CallStatus
export function registerCallHandlers(getWindow: () => BrowserWindow | null): void
```

### VAD (Voice Activity Detection)

Energy-based detection using RMS amplitude:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `ENERGY_THRESHOLD` | 0.015 | RMS energy to count as speech |
| `SILENCE_DURATION` | 1.5s | Seconds of silence to end an utterance |
| `MIN_SPEECH_DURATION` | 0.5s | Minimum seconds of speech to process |
| `CHUNK_SAMPLES` | 1600 | 100ms chunks at 16kHz |
| `MAX_UTTERANCE_SEC` | 30 | Safety cap on utterance length |

Chunks arriving via the `call:chunk` IPC channel are classified as speech or silence based on their RMS energy. When speech starts, chunks accumulate. When silence exceeds `SILENCE_DURATION`, the utterance is finalised and sent for transcription.

### Conversation Loop

1. **Capture** - Wait for a complete utterance via VAD
2. **Transcribe** - Run whisper on the concatenated audio
3. **Infer** - Stream inference via Claude CLI, forwarding text deltas to the renderer for live display
4. **Speak** - Synthesise the full response via TTS and play inline (not queued)
5. **Resume** - Return to listening state

### Event System

The call module emits events via Node.js `EventEmitter`:

| Event | Payload | Purpose |
|-------|---------|---------|
| `status` | `CallStatus` | Status changed |
| `userSaid` | `string` | User utterance transcribed |
| `agentSaid` | `string` | Agent response complete |
| `error` | `string` | Error during any phase |
| `ended` | - | Call terminated |

Status changes are also forwarded to the renderer via `call:statusChanged` IPC.

### IPC Channels

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `call:start` | renderer -> main (invoke) | Start a voice call |
| `call:stop` | renderer -> main (invoke) | Stop the current call |
| `call:status` | renderer -> main (invoke) | Get current call state |
| `call:setMuted` | renderer -> main (invoke) | Mute/unmute during call |
| `call:chunk` | renderer -> main (send) | Stream PCM chunks during call |
| `call:statusChanged` | main -> renderer (send) | Status change notification |

## Streaming TTS Pipeline

TTS runs as a parallel pipeline between the main and renderer processes:

```
Inference stream -> SentenceReady events -> TTS synthesise -> Audio playback queue
                                              |
                                   (synthesise in parallel)
```

1. Inference yields `SentenceReady` events as sentences complete
2. Each sentence is synthesised via `synthesise()` in `tts.ts`
3. The resulting audio file path is pushed to the playback queue via `enqueueAudio()`
4. Audio plays sequentially via `afplay`

Sentences are displayed immediately as text in the renderer (via `TextDelta` events), then played back as audio catches up. This means sentence 2 is being synthesised while sentence 1 is playing, and sentence 3 is being streamed while sentence 2 is being synthesised.

### Playback Events

The renderer tracks playback state through IPC events:

- `tts:started` - a sentence begins playing (activates warm vignette overlay)
- `tts:done` - a sentence finishes playing
- `tts:queueEmpty` - all audio played (deactivates vignette)

During voice call mode, TTS is played inline (not through the queue) to keep the conversation loop synchronous.

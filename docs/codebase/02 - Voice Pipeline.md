# Voice Pipeline

The voice system spans six modules across the main and renderer processes: audio capture (renderer + main bridge), speech-to-text, text-to-speech, wake word detection, voice call mode, and the streaming TTS pipeline that ties inference to playback. All voice-related code lives in `src/main/` and communicates with the renderer through well-defined IPC channels. The pipeline is designed around a split-process architecture where audio capture always happens in the renderer (via Web Audio API) and all processing - transcription, synthesis, playback - happens in the main process. This split exists because Electron's renderer has access to browser media APIs while the main process has access to the filesystem, native binaries, and subprocess spawning.

The modules build on each other in a clear dependency chain. The audio bridge (`audio.ts`) and STT module (`stt.ts`) handle the input side, converting mic audio into text. The TTS module (`tts.ts`) handles the output side, converting text into audio playback. The wake word detector (`wake-word.ts`) uses STT for ambient keyword spotting. The call module (`call.ts`) ties all of these together into a continuous conversation loop. The streaming TTS pipeline (orchestrated in `index.ts`) connects inference output to TTS synthesis and sequential playback during normal chat.

---

## Table of Contents

- [Temp File Management](#temp-file-management)
- [src/main/audio.ts - Audio Bridge (Push-to-Talk)](#srcmainaudiots---audio-bridge-push-to-talk)
- [src/main/stt.ts - Speech-to-Text](#srcmainstts---speech-to-text)
- [src/main/tts.ts - Text-to-Speech](#srcmainttsts---text-to-speech)
- [src/main/wake-word.ts - Wake Word Detection](#srcmainwake-wordts---wake-word-detection)
- [src/main/call.ts - Voice Call Mode](#srcmaincallts---voice-call-mode)
- [Streaming TTS Pipeline](#streaming-tts-pipeline)
- [Configuration Reference](#configuration-reference)
- [IPC Channel Summary](#ipc-channel-summary)
- [Preload API Surface](#preload-api-surface)

---

## Temp File Management

Both the TTS and STT modules need to write audio data to disk before passing it to external processes (`afplay` for playback, `whisper-cli` for transcription). Neither tool accepts audio via stdin - they require file paths. To manage these intermediate files safely, both modules use a shared pattern that generates cryptographically random filenames in the system temp directory, preventing collisions and symlink attacks.

The following helper function is duplicated in both `tts.ts` and `stt.ts` (each with its own prefix) rather than shared in a utility module. This keeps each voice module self-contained with zero cross-dependencies, which simplifies testing and avoids circular imports in the voice subsystem.

```typescript
function secureTmp(ext: string): string {
  const name = crypto.randomBytes(12).toString('hex') + ext;
  return path.join(os.tmpdir(), 'atrophy-tts-' + name);
}
```

Each module uses its own prefix (`atrophy-tts-`, `atrophy-stt-`) to keep temp files identifiable during debugging or manual cleanup. Files are deleted after use - TTS files are removed after `afplay` finishes playback, and STT files are removed after the whisper process exits. Both cleanup paths use `try { fs.unlinkSync(path); } catch {}` to silently handle cases where the file was already removed.

**Why `crypto.randomBytes()` instead of predictable names:** The random filename pattern prevents TOCTOU (time-of-check-time-of-use) race conditions. Python's `NamedTemporaryFile` with `delete=False` follows a create-close-reopen pattern that leaves a window between file creation and the process reopening it for writing. During that window, an attacker could replace the file with a symlink pointing to a sensitive location (a symlink attack), causing the process to overwrite an arbitrary file. By generating an unguessable 12-byte hex filename via `crypto.randomBytes(12)`, the path is effectively unguessable - an attacker cannot predict the filename to create a race condition. The `atrophy-tts-` / `atrophy-stt-` prefixes are for human identification only and do not weaken the randomness of the path.

Here are examples of the generated temp file paths to illustrate the naming convention:

- TTS: `/tmp/atrophy-tts-a3f7b2c9e1d04f6a8b2c.mp3`
- STT: `/tmp/atrophy-stt-7e9c1a3b5d8f2e4a6c0b.wav`

With temp files handled, the next section covers the audio bridge that captures mic input and feeds it to the STT module for transcription.

---

## src/main/audio.ts - Audio Bridge (Push-to-Talk)

This module bridges renderer audio capture with the main process for push-to-talk voice input. In the Python version, `pynput` detected Ctrl key presses and `sounddevice` captured audio - both in the same process. In Electron, these responsibilities are split across processes because the renderer has access to browser media APIs (`getUserMedia`) while the main process has access to the filesystem and whisper binary. The audio bridge manages this split by accumulating PCM chunks sent from the renderer over IPC and handing the complete recording to the STT module when the user releases the push-to-talk key.

### Architecture

The push-to-talk system involves coordination between the renderer and main processes. The following list describes how each responsibility is distributed across the process boundary:

- **Key detection**: The renderer listens for Ctrl keydown/keyup on the `window` object and sends IPC signals to main. This runs in the renderer because keyboard events are DOM events.
- **Audio capture**: The renderer uses `navigator.mediaDevices.getUserMedia()` at 16kHz mono with all processing disabled (echoCancellation, noiseSuppression, autoGainControl all `false` - otherwise Chromium switches macOS to "voice processing" audio mode which downsamples all system audio). This must run in the renderer because `getUserMedia` is a browser API.
- **PCM transport**: The renderer sends Float32Array chunks over the `audio:chunk` IPC channel via `ipcRenderer.send()`. The chunks are sent as raw ArrayBuffers for zero-copy transfer.
- **Minimum duration**: Clips under 300ms are discarded to filter out accidental key taps that produce no meaningful speech.
- **Maximum duration**: Configurable via `MAX_RECORD_SEC` (default: 120 seconds). Exceeding this limit logs a warning but does not truncate the audio.

### Module State

The audio bridge maintains minimal state - just enough to track whether a recording is in progress and accumulate the incoming PCM chunks. The state is reset at the start of each new recording when `audio:start` fires.

```typescript
let _chunks: Float32Array[];   // Accumulated PCM chunks from renderer
let _recording: boolean;        // Whether recording is active
let _startTime: number;         // Timestamp (ms) when recording started
```

### Exported Functions

The module exports two functions. The primary function `registerAudioHandlers()` sets up all three IPC handlers that make push-to-talk work. It must be called once during app startup before any recording can occur. The `isRecording()` function is a simple state query used by other modules (such as the wake word detector) to avoid interfering with an active recording.

```typescript
/**
 * Register IPC handlers for audio:start, audio:stop, and audio:chunk.
 * Must be called once at startup.
 * @param getWindow - Getter for the main BrowserWindow (unused in current implementation
 *                    but passed for consistency with other handler registrations)
 */
export function registerAudioHandlers(
  getWindow: () => BrowserWindow | null,
): void

/**
 * Returns whether a recording is currently in progress.
 */
export function isRecording(): boolean
```

### IPC Channels

The following table lists the three IPC channels that the audio bridge registers. Together they form the complete push-to-talk protocol between renderer and main:

| Channel | Direction | Type | Purpose |
|---------|-----------|------|---------|
| `audio:start` | renderer -> main | `invoke` (returns void) | Begin recording. Resets chunk buffer and sets `_recording = true`. |
| `audio:stop` | renderer -> main | `invoke` (returns string) | Stop recording. Concatenates all chunks, checks minimum duration (300ms), runs whisper transcription, returns transcribed text. Returns empty string on failure. |
| `audio:chunk` | renderer -> main | `send` (fire-and-forget) | Stream PCM Float32Array chunks during recording. Payload is raw `ArrayBuffer`. Chunks arriving when `_recording` is false are silently dropped. |

### Internal Flow: audio:stop Handler

When the user releases the push-to-talk key, the renderer invokes `audio:stop`. This triggers the most important code path in the module - the handler that assembles captured audio, validates it, and runs transcription. The following steps describe the complete flow from stop signal to returned text:

1. Set `_recording = false`, compute elapsed time
2. If no chunks accumulated, return empty string
3. Concatenate all `Float32Array` chunks into a single contiguous array. This concatenation step is necessary because the renderer sends audio in small buffers (4096 samples each), but whisper expects a single continuous WAV file:
   ```typescript
   const totalLength = _chunks.reduce((acc, c) => acc + c.length, 0);
   const audio = new Float32Array(totalLength);
   let offset = 0;
   for (const chunk of _chunks) {
     audio.set(chunk, offset);
     offset += chunk.length;
   }
   ```
4. Clear the chunks buffer
5. Check minimum duration: `audio.length < config.SAMPLE_RATE * 0.3` (300ms at 16kHz = 4800 samples)
6. Log if max recording time exceeded (does not truncate - just warns)
7. Call `transcribe(audio)` from `stt.ts`
8. Return transcribed text, or empty string on error

### Renderer Side (InputBar.svelte)

The renderer side of push-to-talk lives in `InputBar.svelte`. Audio capture uses `ScriptProcessorNode` for wider browser support than AudioWorklet for this simple capture use case. The processor callback fires roughly every 256ms (4096 samples at 16kHz) and forwards each buffer to the main process over IPC:

```typescript
const processor = audioContext.createScriptProcessor(4096, 1, 1);
processor.onaudioprocess = (e) => {
  if (!isRecording) return;
  const input = e.inputBuffer.getChannelData(0);
  const buffer = new Float32Array(input);
  api.sendAudioChunk(buffer.buffer);
};
```

Push-to-talk binds to the Ctrl key globally on the window, allowing the user to hold Ctrl anywhere in the app to record. The keydown handler checks that no recording is already in progress and that inference is idle before starting:

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

The mic button in the input bar also supports hold-to-record via `onmousedown` / `onmouseup`, providing an alternative to the keyboard shortcut.

### Audio Format

The following table documents the audio format used throughout the push-to-talk pipeline, from renderer capture through to the WAV file written by the STT module:

| Property | Value |
|----------|-------|
| Sample rate | 16000 Hz (config.SAMPLE_RATE) |
| Channels | 1 (mono, config.CHANNELS) |
| Bit depth | 32-bit float (Float32Array, range [-1.0, 1.0]) |
| Buffer size | 4096 samples per ScriptProcessorNode callback |
| Transport | Raw ArrayBuffer over IPC |

The audio bridge captures and transports PCM data, but does not perform any transcription itself. That responsibility belongs to the STT module, which receives the concatenated audio and runs whisper.

---

## src/main/stt.ts - Speech-to-Text

This module handles speech-to-text transcription by spawning the whisper.cpp binary as a subprocess with Metal acceleration on Apple Silicon. It provides two transcription modes with different latency and accuracy tradeoffs - a full-quality mode for conversation turns and a fast mode for wake word detection. The module is stateless; each call to `transcribe()` or `transcribeFast()` writes a fresh WAV file, spawns a new whisper process, parses the output, and cleans up. This stateless design means multiple transcriptions can run concurrently without interference, though in practice the app rarely needs more than one at a time.

### Exported Functions

The module exports two public functions that differ in their speed/accuracy tradeoff. The `transcribe()` function is used by the audio bridge (`audio.ts`) after push-to-talk recordings and by the call module (`call.ts`) for full conversation turns. The `transcribeFast()` function is used exclusively by the wake word detector (`wake-word.ts`) where low latency matters more than perfect accuracy.

```typescript
/**
 * Full transcription for conversation turns.
 * Spawns whisper-cli with 4 threads and a 30-second timeout.
 * @param audioData - PCM audio as Float32Array (16kHz mono, range [-1, 1])
 * @returns Transcribed text. Returns empty string on error or timeout (graceful degradation).
 */
export function transcribe(audioData: Float32Array): Promise<string>

/**
 * Fast transcription for wake word detection.
 * Uses the tiny.en model if available, 2 threads, 5-second timeout.
 * @param audioData - PCM audio as Float32Array (typically 2-second clips)
 * @returns Transcribed text. Returns empty string on error or timeout.
 */
export function transcribeFast(audioData: Float32Array): Promise<string>
```

### Two Transcription Modes

The two modes exist because wake word detection runs continuously in the background and must process many short audio clips with minimal CPU usage, while conversation transcription runs occasionally and benefits from higher accuracy. The following table compares their parameters:

| Property | `transcribe()` | `transcribeFast()` |
|----------|----------------|---------------------|
| Use case | Full conversation turns | Wake word clips (~2 seconds) |
| Model | `config.WHISPER_MODEL` (ggml-tiny.en.bin) | Prefers `ggml-tiny.en.bin` in same directory; falls back to `config.WHISPER_MODEL` |
| Threads | 4 (`-t 4`) | 2 (`-t 2`) |
| Timeout | 30,000 ms | 5,000 ms |
| Error handling | Returns empty string (graceful) | Returns empty string (graceful) |
| Typical latency | < 1 second for short clips | < 200ms for 2-second clips |

### Whisper.cpp Subprocess Details

Both modes spawn the same whisper-cli binary with nearly identical arguments. The command-line invocation follows this pattern:

```
whisper-cli -m <model_path> -f <wav_path> --no-timestamps -t <threads> --language en
```

The following table breaks down each argument and why it is used:

| Flag | Value | Purpose |
|------|-------|---------|
| `-m` | Path to GGML model file | Model selection |
| `-f` | Path to temp WAV file | Input audio |
| `--no-timestamps` | (flag) | Suppress `[00:00.000 --> 00:02.000]` timestamp prefixes |
| `-t` | `4` or `2` | Thread count (fewer = lighter CPU footprint) |
| `--language` | `en` | Force English (skip language detection) |

The binary path defaults to `vendor/whisper.cpp/build/bin/whisper-cli` relative to the whisper path. The model defaults to `vendor/whisper.cpp/models/ggml-tiny.en.bin`. Both are resolved via `config.WHISPER_BIN` and `config.WHISPER_MODEL`.

### WAV File Writing (Internal)

Before spawning whisper, the module must convert the Float32Array PCM data from the renderer into a WAV file on disk. The `writeWav()` function handles this conversion, producing a standard RIFF WAV file that whisper.cpp can read. This is necessary because whisper-cli does not accept raw PCM via stdin - it requires a WAV file path as its `-f` argument.

```typescript
function writeWav(
  audioData: Float32Array,
  sampleRate: number,
  channels: number,
): string
```

**Conversion process:**

The first step converts the floating-point samples into 16-bit signed integers, which is the format expected by the WAV container. The conversion uses asymmetric scaling to correctly map the full [-1.0, 1.0] float range to the [-32768, 32767] integer range:

1. Convert float32 samples (range [-1.0, 1.0]) to int16:
   ```typescript
   const int16 = new Int16Array(audioData.length);
   for (let i = 0; i < audioData.length; i++) {
     const s = Math.max(-1, Math.min(1, audioData[i]));
     int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
   }
   ```
   - Negative values scaled to [-32768, 0]
   - Positive values scaled to [0, 32767]
   - Values clamped to [-1, 1] before conversion

2. The function then writes a standard 44-byte RIFF WAV header followed by the int16 sample data. The header fields are populated as follows:

   | Offset | Size | Field | Value |
   |--------|------|-------|-------|
   | 0 | 4 | ChunkID | `RIFF` |
   | 4 | 4 | ChunkSize | `36 + dataBytes` |
   | 8 | 4 | Format | `WAVE` |
   | 12 | 4 | Subchunk1ID | `fmt ` |
   | 16 | 4 | Subchunk1Size | `16` (PCM) |
   | 20 | 2 | AudioFormat | `1` (PCM) |
   | 22 | 2 | NumChannels | `1` (mono) |
   | 24 | 4 | SampleRate | `16000` |
   | 28 | 4 | ByteRate | `32000` (16000 * 1 * 2) |
   | 32 | 2 | BlockAlign | `2` (1 * 16/8) |
   | 34 | 2 | BitsPerSample | `16` |
   | 36 | 4 | Subchunk2ID | `data` |
   | 40 | 4 | Subchunk2Size | `int16.length * 2` |

3. Concatenate header + int16 data, write to temp file

The resulting WAV file has the following properties:

| Property | Value |
|----------|-------|
| Format | PCM (uncompressed) |
| Sample rate | 16000 Hz |
| Channels | 1 (mono) |
| Bit depth | 16-bit signed integer |
| Byte order | Little-endian |
| File extension | `.wav` |

### Output Parsing

Whisper.cpp writes its output to stdout in a format that includes metadata lines alongside the actual transcription. The parser needs to separate the transcription text from the metadata. It works by splitting stdout on newlines, trimming whitespace, filtering out empty lines and any lines starting with `[` (which are timestamp markers and model information), and joining the remaining lines with spaces.

Example raw whisper output:
```
[00:00:00.000 --> 00:00:02.000]   Hello, how are you today?
```
After parsing: `Hello, how are you today?`

### Error Handling

Both `transcribe()` and `transcribeFast()` are designed for graceful degradation. Voice input is a convenience feature, and a transcription failure should never crash the app or block the UI. The following list describes how each error condition is handled:

- **Non-zero exit code**: Returns empty string (does not reject the promise)
- **Process error (e.g. binary not found)**: Returns empty string
- **Timeout**: Kills the process, cleans up the temp file, rejects with a descriptive error
- **Temp file cleanup**: Always runs in `close` and `error` handlers via `try { fs.unlinkSync(wavPath); } catch {}`

### Timeout Implementation

Each transcription mode has a safety timeout that kills the whisper process if it hangs. This prevents a stuck process from blocking the voice pipeline indefinitely. The `transcribe()` function uses a 30-second timeout, while `transcribeFast()` uses a 5-second timeout. The following code shows the timeout pattern used by the full transcription mode:

```typescript
const timeout = setTimeout(() => {
  try { proc.kill(); } catch { /* noop */ }
  cleanup();
  reject(new Error('Whisper transcription timed out (30s)'));
}, 30000);
```

The timeout is cleared when the process exits normally. The kill signal is `SIGTERM` (default for `process.kill()`).

With STT handling the input side (mic audio to text), the next module handles the output side - converting the agent's text responses into spoken audio.

---

## src/main/tts.ts - Text-to-Speech

This module handles the complete text-to-speech pipeline: taking raw text (potentially containing prosody tags), synthesising it into an audio file via a three-tier fallback chain, and playing the result through the speakers. It also manages a sequential playback queue that enables the streaming TTS pipeline where sentences are synthesised concurrently but played back in order. The three-tier fallback chain (ElevenLabs, Fal, macOS say) ensures that voice output is always available, degrading gracefully from high-quality cloud synthesis to the built-in macOS voice when cloud services are unavailable or misconfigured.

### Exported Functions

The module exports seven public functions that serve three distinct roles: synthesis (converting text to audio files), playback (playing audio files through the speakers), and queue management (coordinating sequential playback during streaming inference). The separation between synthesis and playback is a deliberate design choice - it enables the streaming pipeline where multiple sentences can be synthesised in parallel while earlier sentences are still playing.

```typescript
/**
 * Primary TTS entry point. Synthesises text to an audio file using the
 * three-tier fallback chain: ElevenLabs -> Fal -> macOS say.
 *
 * Strips code blocks (fenced and inline) before processing.
 * Returns null if text is too short (< 8 chars after prosody stripping)
 * or if all backends fail.
 *
 * @param text - Raw text, may contain prosody tags like [whispers]
 * @returns Path to temp audio file (MP3 or AIFF), or null
 */
export async function synthesise(text: string): Promise<string | null>

/**
 * Blocking wrapper around synthesise(). Functionally identical in Node.js
 * (the event loop is always running). Exists for API parity with Python's
 * synthesise_sync() which ran the async function in a new event loop.
 * Used in contexts where the caller awaits inline (e.g. setup wizard).
 *
 * @param text - Raw text, may contain prosody tags
 * @returns Path to temp audio file, or null
 */
export async function synthesiseSync(text: string): Promise<string | null>

/**
 * Play an audio file via macOS afplay.
 * Deletes the temp file after playback completes (success or failure).
 *
 * @param audioPath - Path to audio file (MP3, AIFF, etc.)
 * @param rate - Playback rate multiplier. Defaults to config.TTS_PLAYBACK_RATE (1.12)
 * @returns Resolves when playback finishes
 */
export function playAudio(audioPath: string, rate?: number): Promise<void>

/**
 * Add an audio file to the sequential playback queue.
 * If nothing is currently playing, starts playback immediately.
 *
 * @param audioPath - Path to audio file
 * @param index - Sentence index (passed to callbacks for UI synchronisation)
 */
export function enqueueAudio(audioPath: string, index: number): void

/**
 * Clear all pending items from the playback queue.
 * Does not stop the currently playing item.
 */
export function clearAudioQueue(): void

/**
 * Register callbacks for playback lifecycle events.
 * Called once at startup by the inference handler.
 *
 * @param callbacks.onStarted - Fired when a sentence begins playing (receives sentence index)
 * @param callbacks.onDone - Fired when a sentence finishes playing (receives sentence index)
 * @param callbacks.onQueueEmpty - Fired when all queued audio has played
 */
export function setPlaybackCallbacks(callbacks: {
  onStarted?: (index: number) => void;
  onDone?: (index: number) => void;
  onQueueEmpty?: () => void;
}): void

/**
 * Strip prosody tags from text for display purposes.
 * Removes all [tag] markers and collapses double spaces.
 *
 * @param text - Text containing prosody tags
 * @returns Clean text suitable for transcript display
 */
export function stripProsodyTags(text: string): string
```

### Synthesis Flow (synthesise)

The `synthesise()` function is the primary entry point for all TTS in the app. It preprocesses the input text (stripping code and checking length), then tries each backend in order until one succeeds. The full flow proceeds as follows:

1. **Strip code blocks**: Remove fenced (` ``` `) and inline (`` ` ``) code blocks via regex
2. **Check text length**: Run `processProsody()` to get cleaned text. If result is empty or under 8 characters, return null
3. **Try ElevenLabs**: If `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` are configured, call `synthesiseElevenLabsStream()`. On failure, log and continue.
4. **Try Fal**: If `FAL_VOICE_ID` is configured, call `synthesiseFal()`. On failure, log and continue.
5. **Try macOS say**: Call `synthesiseMacOS()`. On failure, log and return null.
6. **All failed**: Log "No voice available - skipping audio", return null.

### Tier 1: ElevenLabs Streaming

**Function:** `synthesiseElevenLabsStream(text: string): Promise<string>`

The primary TTS backend with the lowest latency. ElevenLabs is a cloud-based neural voice synthesis service that produces high-quality, natural-sounding speech. This function uses the streaming endpoint to get audio bytes in a single HTTP response rather than a polling workflow, which minimises time-to-first-byte.

The function sends a POST request to the ElevenLabs streaming API endpoint:

```
POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?output_format=mp3_44100_128
```

The request requires two headers for authentication and content type:

- `xi-api-key`: The ElevenLabs API key
- `Content-Type`: `application/json`

The request body contains the cleaned text (after prosody processing), the model identifier, and voice settings that have been adjusted by any prosody tag deltas:

```json
{
  "text": "<cleaned text after prosody processing>",
  "model_id": "eleven_v3",
  "voice_settings": {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.35
  }
}
```

Voice settings are the base values from config, adjusted by prosody tag deltas and clamped to [0, 1]. Each individual delta is also clamped to [-0.15, +0.15] before being added to the base. This double-clamping prevents extreme prosody combinations from pushing voice settings into unnatural territory:

```typescript
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const stabD = clamp(overrides.stability || 0, -0.15, 0.15);
// stabD applied to base: clamp(config.ELEVENLABS_STABILITY + stabD, 0, 1)
```

**Output format:** MP3, 44.1kHz, 128kbps (specified by `output_format=mp3_44100_128` query parameter).

**Process:**
1. Run prosody processing on input text
2. If cleaned text is empty, throw (triggers fallback)
3. Clamp prosody deltas to +/-0.15 range
4. Compute final voice settings: base + clamped delta, clamped to [0, 1]
5. POST to ElevenLabs streaming endpoint
6. If response is not OK, throw with status and first 300 chars of body
7. Read full response as ArrayBuffer, convert to Buffer
8. Write to temp MP3 file via `fs.writeFileSync()`
9. Return temp file path

**Error handling:** Non-OK HTTP responses throw with the status code and a truncated error body (max 300 chars). This triggers the Fal fallback.

### Tier 2: Fal (fal.ai Hosted ElevenLabs v3)

**Function:** `synthesiseFal(text: string): Promise<string>`

The second-tier fallback uses fal.ai as a proxy to ElevenLabs. This is useful when the user's ElevenLabs API key has exhausted its quota or is rate-limited, but fal.ai access is still available through a separate billing account. Unlike the direct ElevenLabs integration, Fal uses a submit-and-poll pattern where the synthesis request is queued and the result is retrieved asynchronously.

The submit request is sent to the Fal queue endpoint:

```
POST https://queue.fal.run/{config.FAL_TTS_ENDPOINT}
```

Default endpoint: `fal-ai/elevenlabs/tts/eleven-v3`

**Authentication:** `Authorization: Key {FAL_KEY}` header. FAL_KEY comes from the `FAL_KEY` environment variable.

The request body is simpler than the ElevenLabs direct call because Fal exposes fewer voice tuning parameters:

```json
{
  "text": "<cleaned text>",
  "voice": "<FAL_VOICE_ID>",
  "stability": 0.5
}
```

Note: Fal uses only the `stability` parameter from config, not similarity_boost or style. Prosody tag overrides are processed (to clean the text) but the delta values are not applied to the Fal request.

**Response handling - two paths:**

The Fal API can return results synchronously or asynchronously depending on queue depth. The function handles both cases:

1. **Synchronous result**: If the response includes `audio.url`, use it directly (small queue, fast turnaround)
2. **Async polling**: If the response includes `request_id`, poll for results:
   - Poll URL: `https://queue.fal.run/{endpoint}/requests/{request_id}`
   - Poll interval: 1000ms
   - Max attempts: 30 (total timeout: ~30 seconds)
   - Success: response contains `audio.url`
   - Failure: response has `status === 'FAILED'`
   - Timeout: throws after 30 attempts with no result

**Audio download:** Once the audio URL is obtained, the audio file is downloaded with a 30-second AbortSignal timeout to prevent hanging on slow CDN responses:
```typescript
const audioResponse = await fetch(audioUrl, { signal: AbortSignal.timeout(30_000) });
```

**Output format:** MP3 (downloaded from Fal's CDN), written to temp file.

### Tier 3: macOS say (Last Resort)

**Function:** `synthesiseMacOS(text: string): Promise<string>`

The final fallback uses the built-in macOS `say` command, which is always available on any Mac without requiring API keys or network access. The voice quality is noticeably lower than ElevenLabs, but it ensures the agent can always speak even when offline or when cloud services are misconfigured. This fallback is especially important during the setup wizard, where ElevenLabs credentials may not yet be configured.

The function spawns the `say` command as a subprocess:
```
say -v Samantha -r 175 -o <output_path> <cleaned_text>
```

The following table explains each flag:

| Flag | Value | Purpose |
|------|-------|---------|
| `-v` | `Samantha` | Voice selection (high-quality female voice) |
| `-r` | `175` | Speech rate in words per minute |
| `-o` | Temp file path | Output to file instead of speakers |

**Text cleaning:** All prosody tags are stripped via simple regex `text.replace(/\[[\w\s]+\]/g, '')` (not the full prosody processor - just removes square-bracket tags). The macOS say command does not support any form of prosody control, so the tags are removed entirely.

**Output format:** AIFF (Apple's native audio format), uncompressed. File extension is `.aiff`.

**Error handling:** Non-zero exit code rejects the promise. Process spawn errors also reject. Both cases trigger the "No voice available" fallback in the main `synthesise()` function.

### Prosody System

The prosody system allows the agent to embed emotional and stylistic cues in its text output that modify how the text is spoken. The agent can write tags like `[whispers]`, `[warmly]`, or `[sighs]` in its response, and the TTS module interprets these tags to adjust ElevenLabs voice parameters or insert natural pauses. This system gives the agent expressive vocal range beyond flat text reading, making conversations feel more natural. The prosody tags are transparent to the user - they are stripped from the transcript display via `stripProsodyTags()` and only affect the audio output.

The prosody system controls two things:

1. **Voice parameter deltas** - Modify ElevenLabs stability, similarity_boost, and style settings to change vocal characteristics like breathiness, warmth, or intensity
2. **Text replacements** - Breath/pause tags become ellipses for natural pauses in the synthesised audio

#### Regex Patterns

Three regex patterns are used throughout the TTS module to identify and process different types of content in the agent's output text:

```typescript
const PROSODY_RE = /\[([^\]]+)\]/g;       // Matches [any tag]
const CODE_BLOCK_RE = /```[\s\S]*?```/g;  // Fenced code blocks
const INLINE_CODE_RE = /`[^`]+`/g;        // Inline code spans
```

#### processProsody() - Internal Function

The `processProsody()` function is the core of the prosody system. It scans text for all `[tag]` markers, applies the appropriate voice parameter deltas or text replacements, and returns both the cleaned text and the accumulated voice setting overrides. This function is called by every synthesis tier (ElevenLabs, Fal, macOS say) to clean the text, though only ElevenLabs uses the voice setting overrides.

```typescript
function processProsody(text: string): ProsodyResult
```

The function returns a `ProsodyResult` containing the cleaned text with all tags removed, plus any non-zero voice parameter deltas that should be applied to the ElevenLabs request:

```typescript
interface ProsodyResult {
  text: string;                    // Cleaned text with tags removed
  overrides: {
    stability?: number;            // Cumulative delta for stability
    similarity_boost?: number;     // Cumulative delta for similarity
    style?: number;                // Cumulative delta for style
  };
}
```

**Processing logic:**

1. Scan text for all `[tag]` matches
2. For each tag (case-insensitive, trimmed):
   - If it matches a breath tag: replace with the corresponding ellipsis text
   - If it matches a prosody tag: accumulate the three deltas, replace tag with empty string
   - If unknown: strip the tag (replace with empty string)
3. Collapse double spaces to single spaces, trim
4. Check if remaining text is only punctuation/whitespace (`/[\s.\-,;:!?\u2026]+/g`). If so, set text to empty string.
5. Return cleaned text and non-zero overrides

**Multiple tags are cumulative.** If the text contains both `[whispers]` (stability +0.2) and `[slowly]` (stability +0.15), the total stability delta is +0.35 (though it will be clamped to +0.15 before application).

#### Prosody Tag Reference - Voice Parameter Deltas

Each tag applies deltas to `[stability, similarity_boost, style]`. The tags are grouped by emotional register to make it easier to find the right tag for a given mood. The three voice parameters map loosely to vocal characteristics: stability controls consistency (higher = more monotone, lower = more dynamic), similarity_boost controls how closely the output matches the original voice sample, and style controls emotional expressiveness.

**Quiet/soft register:**
| Tag | Stability | Similarity | Style |
|-----|-----------|------------|-------|
| `whispers` | +0.20 | 0.00 | -0.20 |
| `barely audible` | +0.20 | 0.00 | -0.20 |
| `quietly` | +0.15 | 0.00 | -0.15 |
| `hushed` | +0.20 | 0.00 | -0.20 |
| `softer` | +0.10 | 0.00 | -0.10 |
| `lower` | +0.10 | 0.00 | -0.10 |

**Warm/tender register:**
| Tag | Stability | Similarity | Style |
|-----|-----------|------------|-------|
| `warmly` | 0.00 | +0.10 | +0.20 |
| `tenderly` | +0.05 | +0.10 | +0.20 |
| `gently` | +0.05 | +0.10 | +0.15 |

**Intense/forceful register:**
| Tag | Stability | Similarity | Style |
|-----|-----------|------------|-------|
| `firm` | -0.10 | 0.00 | +0.30 |
| `frustrated` | -0.10 | 0.00 | +0.30 |
| `excited` | -0.15 | 0.00 | +0.10 |

**Pace modifiers:**
| Tag | Stability | Similarity | Style |
|-----|-----------|------------|-------|
| `quickly` | -0.15 | 0.00 | 0.00 |
| `faster now` | -0.15 | 0.00 | 0.00 |
| `slowly` | +0.15 | 0.00 | 0.00 |

**Ironic/dry register:**
| Tag | Stability | Similarity | Style |
|-----|-----------|------------|-------|
| `wry` | 0.00 | 0.00 | +0.15 |
| `dry` | +0.10 | 0.00 | -0.10 |
| `sardonic` | 0.00 | 0.00 | +0.20 |

**Vulnerable/emotional register:**
| Tag | Stability | Similarity | Style |
|-----|-----------|------------|-------|
| `raw` | -0.10 | 0.00 | +0.25 |
| `vulnerable` | 0.00 | +0.10 | +0.15 |
| `heavy` | +0.10 | 0.00 | +0.10 |
| `uncertain` | 0.00 | 0.00 | +0.10 |
| `hesitant` | +0.05 | 0.00 | +0.05 |
| `nervous` | -0.10 | 0.00 | +0.15 |
| `reluctant` | +0.05 | 0.00 | +0.10 |

**Grief/fatigue register:**
| Tag | Stability | Similarity | Style |
|-----|-----------|------------|-------|
| `tired` | +0.15 | 0.00 | -0.10 |
| `sorrowful` | +0.10 | +0.10 | +0.15 |
| `grieving` | +0.10 | +0.10 | +0.20 |
| `resigned` | +0.15 | 0.00 | -0.10 |
| `haunted` | +0.05 | +0.05 | +0.15 |
| `melancholic` | +0.10 | +0.10 | +0.10 |
| `nostalgic` | +0.05 | +0.10 | +0.15 |

**Paralinguistic cues:**
| Tag | Stability | Similarity | Style |
|-----|-----------|------------|-------|
| `voice breaking` | -0.15 | 0.00 | +0.30 |
| `laughs softly` | 0.00 | 0.00 | +0.20 |
| `laughs bitterly` | -0.05 | 0.00 | +0.25 |
| `smirks` | 0.00 | 0.00 | +0.15 |
| `emphasis` | 0.00 | 0.00 | 0.00 |

#### Breath/Pause Tag Reference

Unlike voice parameter tags that modify how the text is spoken, breath and pause tags insert literal text into the output that causes the TTS engine to produce natural pauses. The ellipsis characters cause ElevenLabs to generate brief silences, simulating breathing and hesitation. The following table lists all breath/pause tags and their text replacements:

| Tag | Replacement |
|-----|-------------|
| `breath` | `...` |
| `inhales slowly` | `... ...` |
| `exhales` | `...` |
| `sighs` | `...` |
| `sighs quietly` | `...` |
| `clears throat` | `...` |
| `pause` | `. . .` |
| `long pause` | `. . . . .` |
| `trailing off` | `...` |
| `gulps` | `...` |

### Code Block Handling

The agent frequently includes code snippets in its responses, but these should never be spoken aloud - they would sound like nonsense when read by a TTS engine. Both fenced code blocks (triple backtick) and inline code spans (single backtick) are stripped before any synthesis occurs. The stripping happens at the very start of the `synthesise()` function, before prosody processing or length checks:

```typescript
const CODE_BLOCK_RE = /```[\s\S]*?```/g;  // Fenced: ```code```
const INLINE_CODE_RE = /`[^`]+`/g;         // Inline: `code`
```

Text that is too short after prosody processing (< 8 characters) is silently skipped (returns null). This threshold prevents the TTS engine from being invoked for fragments like "OK" or "Hmm" that would sound unnatural as isolated audio clips.

### Playback via afplay

All audio playback in the voice pipeline goes through macOS's built-in `afplay` command, which supports both MP3 (from ElevenLabs/Fal) and AIFF (from macOS say) formats. The `playAudio()` function spawns `afplay` as a subprocess and resolves the returned promise when playback completes:

```
afplay -r <rate> <audioPath>
```

The following table describes the playback parameter:

| Flag | Value | Purpose |
|------|-------|---------|
| `-r` | `config.TTS_PLAYBACK_RATE` (default: 1.12) | Playback speed multiplier. Values > 1.0 speed up. |

The default rate of 1.12x is slightly faster than normal speech, which keeps the agent's responses from feeling sluggish during conversation. This value is configurable per-agent through the settings panel.

**Temp file cleanup:** The audio file is deleted via `fs.unlinkSync()` in both the `close` and `error` handlers of the `afplay` subprocess. Errors during unlink are silently swallowed because the file may have already been removed by a previous cleanup attempt.

### Audio Playback Queue

TTS audio files are played sequentially through a queue in the main process. This queue is the mechanism that enables the streaming pipeline where sentences are synthesised concurrently but played in order. Without it, sentences would play out of order because shorter sentences synthesise faster than longer ones. The queue ensures that sentence 1 always finishes playing before sentence 2 starts, regardless of when each synthesis completed.

The queue maintains the following internal state to track pending items, the current playback status, and registered lifecycle callbacks:

```typescript
interface QueueItem {
  audioPath: string;   // Path to temp audio file
  index: number;       // Sentence index for UI synchronisation
}

let _queue: QueueItem[];                              // Pending items
let _playing: boolean;                                // Whether processQueue is running
let _onStarted: ((index: number) => void) | null;     // Callback: sentence started playing
let _onDone: ((index: number) => void) | null;         // Callback: sentence finished playing
let _onQueueEmpty: (() => void) | null;                // Callback: queue drained
```

**Queue processing loop (`processQueue`):**

The `processQueue()` function is the async loop that drains the queue one item at a time. It starts automatically when the first item is enqueued and runs until the queue is empty:

1. Set `_playing = true`
2. While items remain in `_queue`:
   a. Shift the next item
   b. Fire `_onStarted(item.index)`
   c. Call `playAudio(item.audioPath)` (awaits completion)
   d. Fire `_onDone(item.index)`
3. Set `_playing = false`
4. Fire `_onQueueEmpty()`

**Key behaviors:**
- `enqueueAudio()` starts `processQueue()` if not already running
- `clearAudioQueue()` empties the queue but does not stop the currently playing item
- Playback errors are caught and logged but do not stop the queue

### Playback Events (forwarded to renderer via IPC)

The playback queue fires lifecycle callbacks that are forwarded to the renderer over IPC. These events allow the UI to synchronise visual effects with audio playback - for example, showing a warm vignette overlay while the agent is speaking:

| Callback | IPC Channel | Purpose |
|----------|-------------|---------|
| `onStarted(index)` | `tts:started` | Sentence begins playing - activates warm vignette overlay |
| `onDone(index)` | `tts:done` | Sentence finishes playing |
| `onQueueEmpty()` | `tts:queueEmpty` | All audio played - deactivates vignette |

### Per-Agent Voice Config

Each agent can have its own voice configuration, allowing different agents to sound distinct. Voice parameters come from the agent manifest (`agent.json`) and are resolved via the three-tier config system (env vars, user config, agent config, defaults). The following table lists all TTS-related config keys:

| Config Key | Default | Description |
|------------|---------|-------------|
| `ELEVENLABS_API_KEY` | `''` | Global API key (from user config or env) |
| `ELEVENLABS_VOICE_ID` | `''` | Per-agent voice ID |
| `ELEVENLABS_MODEL` | `'eleven_v3'` | ElevenLabs model identifier |
| `ELEVENLABS_STABILITY` | `0.5` | Base voice stability [0, 1] |
| `ELEVENLABS_SIMILARITY` | `0.75` | Base similarity boost [0, 1] |
| `ELEVENLABS_STYLE` | `0.35` | Base style exaggeration [0, 1] |
| `TTS_PLAYBACK_RATE` | `1.12` | afplay rate multiplier |
| `FAL_TTS_ENDPOINT` | `'fal-ai/elevenlabs/tts/eleven-v3'` | Fal.ai endpoint path |
| `FAL_VOICE_ID` | `''` | Fal voice identifier |

**Design note:** There is no combined `speak()` function that synthesises and plays in one call. Synthesis (`synthesise()`) and playback (`playAudio()` / `enqueueAudio()`) are deliberately separate operations. This separation enables the streaming TTS pipeline where sentences are synthesised in parallel while earlier sentences are still playing. In `index.ts`, the inference handler calls `synthesise()` on each `SentenceReady` event and feeds the resulting audio path into `enqueueAudio()` - the queue handles sequential playback independently. For blocking contexts (like the setup wizard), `synthesiseSync()` is available but still returns only a file path - the caller is responsible for playback.

The TTS module handles one-shot synthesis and queued playback for normal chat. The next two modules cover background listening (wake word detection) and continuous conversation (voice call mode), both of which build on the audio and STT foundations described above.

### ElevenLabs Credit Exhaustion

The TTS module tracks ElevenLabs API failures to handle credit exhaustion gracefully. When `synthesise()` catches an error containing HTTP status 401, 402, or 429 from ElevenLabs, it calls `markElevenLabsExhausted()` which starts a 30-minute cooldown. During cooldown, `isElevenLabsExhausted()` returns true and the ElevenLabs tier is skipped entirely - synthesis falls through to Fal then macOS `say`.

```typescript
export const COOLDOWN_MS = 30 * 60 * 1000; // 30 minutes
export function markElevenLabsExhausted(): void;
export function isElevenLabsExhausted(): boolean;
export function resetElevenLabsStatus(): void;
```

The cooldown auto-resets after 30 minutes. `resetElevenLabsStatus()` allows manual recovery. This is used by heartbeat voice note delivery to decide whether to attempt voice synthesis or fall back to text.

### src/main/audio-convert.ts - Shared Audio Conversion

Shared utilities for audio format conversion, extracted from the voice-note job for reuse by both `voice-note.ts` and `heartbeat.ts`.

```typescript
export function convertToOgg(inputPath: string): string | null;
export function cleanupFiles(...paths: (string | null | undefined)[]): void;
```

`convertToOgg` shells out to `ffmpeg` (via `execFileSync` for safety - no shell injection) to convert any audio file to OGG Opus at 64kbps. This is the format required for Telegram voice notes (the `sendVoice` API). Returns the output path on success, null on failure (ffmpeg not found, timeout, empty output). 30-second timeout.

`cleanupFiles` removes temp audio files, accepting nulls safely. Used after voice note delivery to clean up both the MP3 source and OGG output.

---

## src/main/wake-word.ts - Wake Word Detection

The wake word module provides background ambient listening using whisper.cpp keyword spotting. When enabled, it continuously captures short audio clips from the microphone, runs fast whisper transcription on each clip, and checks the transcription for configured trigger phrases like "hey Xan" or just "Xan". This system is **independent of the mic/PTT button** - it runs in its own loop and does not require the user to press any button. The wake word detector allows the user to activate the agent hands-free, similar to "Hey Siri" or "OK Google", but using local processing rather than cloud services. All audio stays on the machine and is never transmitted to any server for wake word detection.

### Exported Functions

The module exports six functions that manage the lifecycle of the wake word listener. The listener has three states: stopped (not running), running (actively processing audio), and paused (running but ignoring audio, typically after a detection). The pause/resume mechanism exists to prevent repeated triggering - when a wake word is detected, the listener auto-pauses and must be explicitly resumed after the resulting interaction completes.

```typescript
/**
 * Start the wake word listener. Sends 'wakeword:start' to the renderer
 * to begin ambient audio capture. Pre-flight checks verify the whisper
 * binary and model exist. No-op if WAKE_WORD_ENABLED is false.
 *
 * @param onDetected - Callback fired when a wake word is detected.
 *                     The listener auto-pauses after detection.
 * @param getWindow - Getter for the main BrowserWindow (used to send IPC)
 */
export function startWakeWordListener(
  onDetected: () => void,
  getWindow: () => BrowserWindow | null,
): void

/**
 * Stop the wake word listener. Sends 'wakeword:stop' to the renderer
 * to halt ambient audio capture.
 *
 * @param getWindow - Getter for the main BrowserWindow
 */
export function stopWakeWordListener(
  getWindow: () => BrowserWindow | null,
): void

/**
 * Pause wake word detection without stopping the listener.
 * Audio chunks arriving while paused are silently dropped.
 */
export function pauseWakeWord(): void

/**
 * Resume wake word detection after a pause.
 */
export function resumeWakeWord(): void

/**
 * Returns true if the listener is running and not paused.
 */
export function isWakeWordListening(): boolean

/**
 * Register IPC handlers for wake word audio chunks.
 * Must be called once at startup.
 */
export function registerWakeWordHandlers(): void
```

### Module State

The wake word module maintains minimal state - just enough to track whether the listener is active, whether it has been paused (typically after a detection), and the callback to fire when a wake word is matched. The state is intentionally simple because all the complexity lives in the per-chunk processing logic in the IPC handler.

```typescript
let _running: boolean;                       // Listener active
let _paused: boolean;                        // Temporarily suppressed (auto-set on detection)
let _onDetected: (() => void) | null;        // Detection callback
```

### Architecture (Differs from Python)

The Electron wake word architecture differs significantly from the Python version due to the process boundary. In Python, `sounddevice.rec()` captured audio directly in the background thread, and whisper ran in the same process. In Electron, audio capture must happen in the renderer (which has access to `getUserMedia`), while whisper must run in the main process (which can spawn subprocesses). The wake word module bridges this gap by coordinating audio capture in the renderer and transcription in the main process through IPC messages:

1. Main sends `wakeword:start` (with `config.WAKE_CHUNK_SECONDS` duration) to renderer
2. Renderer captures audio and sends Float32Array chunks via `wakeword:chunk`
3. Main receives chunks, checks RMS energy, runs fast whisper transcription

### Detection Loop (per chunk)

Each audio chunk from the renderer goes through a pipeline of checks before being sent to whisper for transcription. The RMS energy check acts as a cheap gate that prevents whisper from being invoked on silence, saving significant CPU. The full per-chunk processing flow is:

1. Receive audio chunk from renderer via `wakeword:chunk` IPC
2. If `_running` is false or `_paused` is true, drop the chunk
3. Convert `ArrayBuffer` to `Float32Array`
4. Compute RMS amplitude using the following function, which calculates the root-mean-square of the audio samples as a measure of loudness:
   ```typescript
   function rms(audio: Float32Array): number {
     let sum = 0;
     for (let i = 0; i < audio.length; i++) {
       sum += audio[i] * audio[i];
     }
     return Math.sqrt(sum / audio.length);
   }
   ```
5. Skip if RMS < 0.005 (near-silence threshold)
6. Transcribe with `transcribeFast()` (whisper tiny, 2 threads, 5s timeout)
7. Convert transcription to lowercase, trim
8. Check against all configured wake words (case-insensitive substring match via `textLower.includes(word)`)
9. On match:
   - Log the detected text
   - Set `_paused = true` (auto-pause to prevent repeated triggers)
   - Fire `_onDetected()` callback

### IPC Channels

The wake word system uses three IPC channels - two from main to renderer to control the ambient capture, and one from renderer to main to send audio data. The following table documents all three:

| Channel | Direction | Type | Purpose |
|---------|-----------|------|---------|
| `wakeword:start` | main -> renderer | `send` | Start ambient audio capture. Payload: `chunkSeconds` (number) |
| `wakeword:stop` | main -> renderer | `send` | Stop ambient audio capture |
| `wakeword:chunk` | renderer -> main | `send` | Audio chunk for analysis. Payload: `ArrayBuffer` |

### Pre-flight Checks

`startWakeWordListener()` performs three checks before starting to ensure all required dependencies are available. If any check fails, the function returns silently without starting the listener and logs the specific reason:

1. `config.WAKE_WORD_ENABLED` must be true (default: false)
2. `config.WHISPER_BIN` must exist on disk (`fs.existsSync()`)
3. `config.WHISPER_MODEL` must exist on disk (`fs.existsSync()`)

If any check fails, the function returns without starting (logs the reason).

### RMS Silence Threshold

The silence threshold determines the minimum audio energy level required before a chunk is sent to whisper for transcription. This table documents the threshold value:

| Threshold | Value | Purpose |
|-----------|-------|---------|
| Near-silence (wake word) | 0.005 | Skip chunks that are essentially ambient noise |

This threshold is hardcoded (not configurable). It is deliberately low to avoid missing soft speech - the whisper model handles the actual recognition. Setting it too high would cause the detector to miss quietly spoken wake words, while the current low value only filters out near-total silence.

### Wake Word Configuration

The following config keys control wake word behavior. The feature is disabled by default and must be explicitly enabled through the GUI, environment variable, or settings panel:

| Config Key | Default | Description |
|------------|---------|-------------|
| `WAKE_WORD_ENABLED` | `false` | Master enable/disable |
| `WAKE_CHUNK_SECONDS` | `2` | Duration of each ambient capture chunk sent to main |
| `WAKE_WORDS` | `['hey <name>', '<name>']` | List of trigger phrases (from agent manifest) |

**Enabling wake words:** There are three ways to turn on wake word detection, listed in order of convenience:

- In the GUI, click the microphone-with-waves button in the top-right (shortcut: **Cmd+Shift+W**). The button turns green when active.
- Via environment variable: `WAKE_WORD_ENABLED=true`
- Via the settings panel: Input section > Wake Word Detection toggle

While the wake word detector listens for a single trigger phrase to begin an interaction, the voice call module (covered next) provides a fully hands-free continuous conversation mode where the user speaks naturally without any trigger words.

---

## src/main/call.ts - Voice Call Mode

The call module implements a hands-free continuous conversation loop that captures audio from the mic (via renderer IPC chunks), detects speech boundaries via energy-based voice activity detection (VAD), transcribes with whisper, runs inference through the Claude CLI, and speaks the response via TTS. This loop repeats until the user explicitly stops the call or closes the window. Unlike push-to-talk where the user holds a key to record, voice call mode listens continuously and uses VAD to determine when the user starts and stops speaking. This makes it suitable for longer, more natural conversations where holding a key would be cumbersome.

The call module ties together all the other voice modules - it uses `stt.ts` for transcription, `tts.ts` for synthesis and playback, and `inference.ts` for generating responses. It manages its own audio chunk accumulation and VAD rather than using the audio bridge, because the call's continuous listening pattern is fundamentally different from push-to-talk's discrete recording sessions.

### Call State Machine

The call progresses through four states in a fixed cycle. Each state transition is broadcast to both the internal event system and the renderer via IPC, allowing the UI to display the current phase (e.g., showing a pulsing indicator while thinking, or a speaker icon while speaking):

```
idle -> listening -> thinking -> speaking -> listening -> ...
```

The `CallStatus` type captures these four states:

```typescript
export type CallStatus = 'idle' | 'listening' | 'thinking' | 'speaking';
```

### Exported Functions

The module exports a rich API for controlling and observing voice calls. The core functions (`startCall`, `stopCall`) manage the call lifecycle, while helper functions provide state queries and mute control. The event system (`onCallEvent`, `offCallEvent`) allows other parts of the app to react to call activity without tight coupling. The `registerCallHandlers()` function exposes all of this to the renderer via IPC.

```typescript
/**
 * Start a hands-free voice call. The renderer must be sending audio chunks
 * via the 'call:chunk' IPC channel. The call loops until stopCall() is
 * invoked or the window closes.
 *
 * @param systemPrompt - The system prompt for inference
 * @param cliSessionId - Existing CLI session ID (or null to start fresh)
 * @param getWindow - Getter for the main BrowserWindow
 */
export function startCall(
  systemPrompt: string,
  cliSessionId: string | null,
  getWindow: () => BrowserWindow | null,
): void

/**
 * Stop the current voice call. Unblocks any pending utterance capture
 * by resolving the capture promise with null.
 */
export function stopCall(): void

/** Whether a call is currently active. */
export function isInCall(): boolean

/** Whether the mic is muted (still in call but not processing audio). */
export function isMuted(): boolean

/**
 * Mute/unmute the mic during a call.
 * When muted, incoming chunks increment the silent counter but are not accumulated.
 */
export function setMuted(muted: boolean): void

/** Current call status. */
export function getCallStatus(): CallStatus

/** The CLI session ID (may update during the call as inference returns new IDs). */
export function getCallCliSessionId(): string | null

/**
 * Subscribe to call events.
 * @param event - One of: 'status', 'userSaid', 'agentSaid', 'error', 'ended'
 * @param listener - Event handler
 */
export function onCallEvent(
  event: 'status' | 'userSaid' | 'agentSaid' | 'error' | 'ended',
  listener: (...args: unknown[]) => void,
): void

/**
 * Remove a call event listener.
 */
export function offCallEvent(
  event: 'status' | 'userSaid' | 'agentSaid' | 'error' | 'ended',
  listener: (...args: unknown[]) => void,
): void

/**
 * Register IPC handlers for call:start, call:stop, call:status,
 * call:setMuted, and call:chunk. Must be called once at startup.
 *
 * @param getWindow - Getter for the main BrowserWindow
 */
export function registerCallHandlers(
  getWindow: () => BrowserWindow | null,
): void
```

### Module State

The call module maintains more state than any other voice module because it must track the call lifecycle, the VAD state, the inference session, and the window reference simultaneously. The state is divided into two groups: call-level state (active flag, mute, status, session ID) and VAD state (chunks, speech detection, utterance resolution). All state is reset by the `_cleanup()` function when a call ends.

```typescript
const _emitter: EventEmitter;                          // Node.js EventEmitter for call events
let _active: boolean;                                   // Call in progress
let _muted: boolean;                                    // Mic muted
let _status: CallStatus;                                // Current state machine position
let _cliSessionId: string | null;                       // Claude CLI session ID (may update)
let _systemPrompt: string | null;                       // System prompt for inference
let _getWindow: (() => BrowserWindow | null) | null;    // Window getter

// VAD state
let _chunks: Float32Array[];                            // Accumulated speech audio
let _speechStarted: boolean;                            // Whether speech has been detected
let _silentChunks: number;                              // Count of consecutive silent chunks
let _utteranceReady: boolean;                           // Guard against double resolution
let _utteranceResolve: ((audio: Float32Array | null) => void) | null;  // Promise resolver
```

### VAD (Voice Activity Detection)

The call module uses energy-based voice activity detection to determine when the user is speaking and when they have finished. This is simpler and lower-latency than a neural VAD model, at the cost of being less accurate in noisy environments. The VAD works by computing the RMS energy of each incoming audio chunk and comparing it against a threshold. When energy exceeds the threshold, speech has started; when energy drops below the threshold for long enough, the utterance is complete. The following constants control this behavior:

| Constant | Value | Purpose |
|----------|-------|---------|
| `ENERGY_THRESHOLD` | `0.015` | RMS energy level to classify a chunk as speech |
| `SILENCE_DURATION` | `1.5` | Seconds of continuous silence to end an utterance |
| `MIN_SPEECH_DURATION` | `0.5` | Minimum seconds of speech to process (shorter is discarded) |
| `CHUNK_SAMPLES` | `1600` | Samples per chunk (100ms at 16kHz) |
| `MAX_UTTERANCE_SEC` | `30` | Safety cap on utterance length |

These constants are used to compute two derived values at runtime that determine the chunk-level thresholds for silence detection and maximum utterance length:

- `silenceChunksNeeded = ceil((1.5 * 16000) / 1600) = 15` chunks
- `maxChunks = ceil((30 * 16000) / 1600) = 300` chunks

### VAD Chunk Processing (_ingestChunk)

The `_ingestChunk()` function is called for every audio chunk received from the renderer during a call. It implements the core VAD logic, deciding whether each chunk contains speech or silence and accumulating speech audio for later transcription. The function follows this decision tree for each incoming chunk:

1. If no pending utterance resolver or utterance already finalised, drop
2. If muted, increment silent chunk counter and return
3. Compute RMS energy of the chunk
4. If RMS > `ENERGY_THRESHOLD` (0.015):
   - Mark `_speechStarted = true`
   - Reset `_silentChunks` counter
   - Accumulate the chunk
5. Else if speech already started:
   - Increment `_silentChunks`
   - Still accumulate the chunk (trailing audio for natural cutoff)
   - If `_silentChunks >= silenceChunksNeeded` (15 chunks = 1.5s), finalise utterance
6. Else (no speech yet): discard chunk (ambient noise)
7. If total chunks >= `maxChunks` (300 = 30s), force-finalise

### Utterance Capture (_captureUtterance)

The `_captureUtterance()` function returns a `Promise<Float32Array | null>` that resolves when a complete utterance has been captured. It sets up the VAD state and creates a promise that will be resolved by `_ingestChunk()` when it detects end-of-speech. The promise resolves in one of three ways:

- The VAD detects end-of-utterance (silence after speech)
- The safety timeout fires (`MAX_UTTERANCE_SEC * 1000 + 500` ms)
- `stopCall()` is called (resolves with null)

The safety timeout has a 500ms buffer beyond the max utterance time to allow the VAD to naturally finalise before forcing it.

### Utterance Finalisation (_finaliseUtterance)

The `_finaliseUtterance()` function is called when the VAD determines that an utterance is complete (either due to silence, timeout, or max length). It concatenates all accumulated chunks into a single audio buffer and resolves the capture promise. The function takes care to prevent double-resolution by nulling out the resolver reference and setting a guard flag:

1. Capture the resolver function and null out the module-level reference
2. Set `_utteranceReady = true` (guard flag)
3. If no chunks accumulated, resolve with null
4. Concatenate all chunks into a single `Float32Array`
5. Clear the chunks array
6. Resolve with the concatenated audio

### Conversation Loop (_runLoop)

The `_runLoop()` function is the main async loop that runs for the duration of a call. It orchestrates the full listen-think-speak cycle, calling into the STT, inference, and TTS modules in sequence. Each iteration of the loop represents one complete conversational turn:

1. **Capture**: Call `_captureUtterance()` - blocks until speech is detected and silence follows
2. **Duration check**: If audio is shorter than `MIN_SPEECH_DURATION` (0.5s), skip and re-listen
3. **Transcribe**: Set status to `thinking`, run `transcribe(audio)` from stt.ts
4. **Validate**: If transcription is empty or under 2 characters, skip and re-listen
5. **Emit**: Fire `userSaid` event with trimmed text
6. **Infer**: Call `_runInference(text)` - streams Claude CLI response, forwarding all events to the renderer
7. **Emit**: Fire `agentSaid` event with full response
8. **Speak**: Set status to `speaking`, synthesise and play audio inline (not queued)
9. **Resume**: Set status to `listening`, loop back to step 1

**Error handling:** Errors in any phase are emitted via the `error` event. If the call is still active, status returns to `listening` and the loop continues. This resilience means a single transcription failure or TTS error does not terminate the call.

### Inference During Call (_runInference)

The `_runInference()` function calls `streamInference()` from the inference module and collects the full response. All streaming events are forwarded to the renderer for live display, so the user can read the response in the transcript as it streams even before TTS playback begins. The following table maps each inference event to its forwarded IPC channel:

| Inference Event | Forwarded IPC Channel | Notes |
|-----------------|----------------------|-------|
| `TextDelta` | `inference:textDelta` | Real-time text streaming |
| `SentenceReady` | `inference:sentenceReady` | Audio path is empty string (TTS is handled separately) |
| `ToolUse` | `inference:toolUse` | Tool name |
| `Compacting` | `inference:compacting` | Context window compaction |
| `StreamDone` | `inference:done` | Updates `_cliSessionId` if a new session ID is returned |
| `StreamError` | `inference:error` | Emits error event, resolves with null |

**Important:** During voice calls, TTS is played inline via `synthesise()` + `playAudio()` (not through the playback queue). This keeps the conversation loop synchronous - the agent waits for the full response to be spoken before listening again. This differs from normal chat where sentences are queued and played overlapping with continued synthesis.

### Event System

The call module uses a Node.js `EventEmitter` to broadcast internal events to any interested listeners. This decouples the call logic from the UI layer - the renderer subscribes to these events via IPC forwarding, and other main-process modules can subscribe directly. The following table lists all events:

| Event | Payload | When |
|-------|---------|------|
| `status` | `CallStatus` | Every state transition |
| `userSaid` | `string` | After successful transcription |
| `agentSaid` | `string` | After inference completes with a response |
| `error` | `string` | Any error during capture, transcription, inference, or TTS |
| `ended` | (none) | Call terminated (cleanup complete) |

Status changes are also forwarded to the renderer via `call:statusChanged` IPC.

### IPC Channels

The call module registers five IPC handlers and sends one outbound notification. The following table documents the complete IPC surface:

| Channel | Direction | Type | Purpose |
|---------|-----------|------|---------|
| `call:start` | renderer -> main | `invoke` | Start a voice call. Args: `(systemPrompt: string, cliSessionId: string | null)` |
| `call:stop` | renderer -> main | `invoke` | Stop the current call |
| `call:status` | renderer -> main | `invoke` | Get current state: `{ active, status, muted }` |
| `call:setMuted` | renderer -> main | `invoke` | Mute/unmute. Arg: `(muted: boolean)` |
| `call:chunk` | renderer -> main | `send` | Stream PCM chunks during call. Payload: `ArrayBuffer` |
| `call:statusChanged` | main -> renderer | `send` | Status change notification. Payload: `CallStatus` |

### Cleanup (_cleanup)

The `_cleanup()` function is called when the conversation loop exits, whether normally (user stopped the call) or due to an unrecoverable error. It resets all module state to its initial values and broadcasts the termination:

1. Set `_active = false`
2. Clear all VAD state (`_chunks`, `_speechStarted`, `_silentChunks`, `_utteranceResolve`)
3. Set status to `idle` (triggers IPC notification)
4. Emit `ended` event

The individual voice modules described above handle their respective domains independently. The streaming TTS pipeline, described next, is the orchestration layer that ties inference output to TTS synthesis and sequential playback during normal (non-call) conversation.

---

## Streaming TTS Pipeline

During normal chat (not voice call mode), TTS runs as a parallel pipeline between the main and renderer processes. This pipeline is orchestrated in `index.ts` rather than in any single voice module, and it is responsible for making the agent "speak" each sentence as it is generated by the inference engine. The key insight is that synthesis and playback are decoupled - sentence 2 can be synthesising while sentence 1 is still playing, and sentence 3 can be streaming from the Claude CLI while sentence 2 is synthesising.

The data flow through the pipeline looks like this:

```
Inference stream -> SentenceReady events -> TTS synthesise -> Audio playback queue
                                              |
                                   (synthesise in parallel)
```

The pipeline operates in four stages:

1. Inference yields `SentenceReady` events as sentences complete (detected by regex-based sentence boundary detection in the inference module)
2. Each sentence is synthesised via `synthesise()` in `tts.ts`, which returns a path to a temp audio file
3. The resulting audio file path is pushed to the playback queue via `enqueueAudio()`
4. Audio plays sequentially via `afplay`, with each item played in the order it was enqueued

Sentences are displayed immediately as text in the renderer (via `TextDelta` events), then played back as audio catches up. This means sentence 2 is being synthesised while sentence 1 is playing, and sentence 3 is being streamed while sentence 2 is being synthesised. The result is a natural conversational flow where the user sees text appear in real-time and hears the agent speak with minimal delay.

### Playback Events

The renderer tracks playback state through IPC events forwarded from the TTS playback queue. These events drive visual feedback in the UI so the user knows when the agent is actively speaking:

- `tts:started` - a sentence begins playing (activates warm vignette overlay around the edges of the window)
- `tts:done` - a sentence finishes playing (used for internal bookkeeping)
- `tts:queueEmpty` - all audio played (deactivates vignette, signals the end of the speaking phase)

During voice call mode, TTS is played inline (not through the queue) to keep the conversation loop synchronous. This means the playback events above are not fired during calls - the call module manages its own speaking state via the `call:statusChanged` IPC channel instead.

---

## Configuration Reference

All voice-related config values are documented here in one place for easy reference. These values are resolved through the three-tier config system (env vars, user config at `~/.atrophy/config.json`, agent config at `agents/<name>/data/agent.json`, then defaults). The "Source" column indicates where the default typically comes from.

### Audio Capture

These settings control the raw audio format used throughout the voice pipeline. They are shared by the audio bridge, STT, and wake word modules:

| Key | Default | Source | Description |
|-----|---------|--------|-------------|
| `SAMPLE_RATE` | `16000` | Hardcoded default | Audio sample rate in Hz |
| `CHANNELS` | `1` | Hardcoded default | Number of audio channels (mono) |
| `MAX_RECORD_SEC` | `120` | Hardcoded default | Maximum push-to-talk recording duration in seconds |

### TTS (ElevenLabs)

These settings configure the primary TTS backend. The API key is global (shared across all agents), while voice ID and voice tuning parameters are per-agent:

| Key | Default | Source | Description |
|-----|---------|--------|-------------|
| `ELEVENLABS_API_KEY` | `''` | User config / env | API key (global, not per-agent) |
| `ELEVENLABS_VOICE_ID` | `''` | Agent config | Voice ID for synthesis |
| `ELEVENLABS_MODEL` | `'eleven_v3'` | Agent config | Model identifier |
| `ELEVENLABS_STABILITY` | `0.5` | Agent config | Voice stability [0, 1] |
| `ELEVENLABS_SIMILARITY` | `0.75` | Agent config | Similarity boost [0, 1] |
| `ELEVENLABS_STYLE` | `0.35` | Agent config | Style exaggeration [0, 1] |
| `TTS_PLAYBACK_RATE` | `1.12` | Agent config | afplay speed multiplier |

### TTS (Fal)

These settings configure the Fal fallback TTS backend. Fal authentication uses an environment variable rather than the config system:

| Key | Default | Source | Description |
|-----|---------|--------|-------------|
| `FAL_TTS_ENDPOINT` | `'fal-ai/elevenlabs/tts/eleven-v3'` | Hardcoded default | Fal API endpoint path |
| `FAL_VOICE_ID` | `''` | Agent config | Voice identifier for Fal |

Authentication via `FAL_KEY` environment variable (not in config system - read directly from `process.env`).

### Wake Word

These settings control the wake word detection feature. The feature is disabled by default to avoid unnecessary CPU usage from continuous whisper transcription:

| Key | Default | Source | Description |
|-----|---------|--------|-------------|
| `WAKE_WORD_ENABLED` | `false` | User config | Master toggle |
| `WAKE_CHUNK_SECONDS` | `2` | Hardcoded default | Duration of ambient capture chunks |
| `WAKE_WORDS` | `['hey <name>', '<name>']` | Agent manifest | Trigger phrases |

### Whisper

These settings point to the whisper.cpp binary and model. They are derived from `WHISPER_PATH` in the config system rather than set directly:

| Key | Default | Source | Description |
|-----|---------|--------|-------------|
| `WHISPER_BIN` | `'<WHISPER_PATH>/build/bin/whisper-cli'` | Derived from WHISPER_PATH | Path to whisper-cli binary |
| `WHISPER_MODEL` | `'<WHISPER_PATH>/models/ggml-tiny.en.bin'` | Derived from WHISPER_PATH | Path to GGML model file |

---

## IPC Channel Summary

This section provides a complete reference of all IPC channels used by the voice pipeline, grouped by subsystem. Each channel is documented with its direction (renderer to main or main to renderer), its type (invoke for request/response, send for fire-and-forget), and its payload format.

### Audio Capture (Push-to-Talk)

These channels implement the push-to-talk recording protocol between the renderer's audio capture and the main process's transcription pipeline:

| Channel | Direction | Type | Payload |
|---------|-----------|------|---------|
| `audio:start` | renderer -> main | invoke | (none) -> void |
| `audio:stop` | renderer -> main | invoke | (none) -> string (transcription) |
| `audio:chunk` | renderer -> main | send | ArrayBuffer (Float32Array of PCM samples) |

### TTS Playback

These channels notify the renderer about playback state changes so the UI can show visual effects (like the warm vignette overlay) synchronized with audio:

| Channel | Direction | Type | Payload |
|---------|-----------|------|---------|
| `tts:started` | main -> renderer | send | number (sentence index) |
| `tts:done` | main -> renderer | send | number (sentence index) |
| `tts:queueEmpty` | main -> renderer | send | (none) |

### Wake Word

These channels manage the ambient audio capture loop for wake word detection. The main process controls when the renderer starts and stops capturing:

| Channel | Direction | Type | Payload |
|---------|-----------|------|---------|
| `wakeword:start` | main -> renderer | send | number (chunk seconds) |
| `wakeword:stop` | main -> renderer | send | (none) |
| `wakeword:chunk` | renderer -> main | send | ArrayBuffer (Float32Array of PCM samples) |

### Voice Call

These channels implement the full voice call protocol, including call lifecycle control, mute toggle, audio streaming, and status notifications:

| Channel | Direction | Type | Payload |
|---------|-----------|------|---------|
| `call:start` | renderer -> main | invoke | (systemPrompt: string, cliSessionId: string) -> void |
| `call:stop` | renderer -> main | invoke | (none) -> void |
| `call:status` | renderer -> main | invoke | (none) -> { active, status, muted } |
| `call:setMuted` | renderer -> main | invoke | (muted: boolean) -> void |
| `call:chunk` | renderer -> main | send | ArrayBuffer (Float32Array of PCM samples) |
| `call:statusChanged` | main -> renderer | send | CallStatus string |

---

## Preload API Surface

The renderer accesses voice features through the `window.atrophy` API exposed via `contextBridge` in `preload/index.ts`. This API surface is the only way the renderer can interact with the voice pipeline - it cannot call `ipcRenderer` directly. Each method below wraps one or more of the IPC channels documented above. All listener functions return an unsubscribe function (`() => void`) for cleanup, implemented via the `createListener` helper in `preload/index.ts` which wraps `ipcRenderer.on()` and returns a function that calls `ipcRenderer.removeListener()`.

### Audio Capture

These methods are used by `InputBar.svelte` to implement push-to-talk recording. The `sendAudioChunk` method is called from the `ScriptProcessorNode` callback during active recording:

```typescript
startRecording: () => Promise<void>              // Triggers audio:start
stopRecording: () => Promise<string>             // Triggers audio:stop, returns transcription
sendAudioChunk: (buffer: ArrayBuffer) => void    // Sends audio:chunk (fire-and-forget)
```

### TTS Events

These listener methods are used by the `Window.svelte` component to synchronise the vignette overlay effect with audio playback. The `onTtsStarted` callback activates the overlay and `onTtsQueueEmpty` deactivates it:

```typescript
onTtsStarted: (cb: (index: number) => void) => () => void      // Listens to tts:started
onTtsDone: (cb: (index: number) => void) => () => void          // Listens to tts:done
onTtsQueueEmpty: (cb: () => void) => () => void                  // Listens to tts:queueEmpty
```

### Wake Word

These methods are used by the renderer to manage the ambient audio capture loop for wake word detection. The `onWakeWordStart` callback tells the renderer to begin capturing and sending audio chunks at the specified interval:

```typescript
onWakeWordStart: (cb: (chunkSeconds: number) => void) => () => void  // Listens to wakeword:start
onWakeWordStop: (cb: () => void) => () => void                        // Listens to wakeword:stop
sendWakeWordChunk: (buffer: ArrayBuffer) => void                      // Sends wakeword:chunk
```

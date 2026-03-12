# Voice Pipeline

The voice system spans six modules across the main and renderer processes: audio capture (renderer + main bridge), speech-to-text, text-to-speech, wake word detection, voice call mode, and the streaming TTS pipeline that ties inference to playback. All voice-related code lives in `src/main/` and communicates with the renderer through well-defined IPC channels.

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

Both `tts.ts` and `stt.ts` generate temp files using Node.js built-in `crypto.randomBytes()` and `os.tmpdir()`:

```typescript
function secureTmp(ext: string): string {
  const name = crypto.randomBytes(12).toString('hex') + ext;
  return path.join(os.tmpdir(), 'atrophy-tts-' + name);
}
```

Each module uses its own prefix (`atrophy-tts-`, `atrophy-stt-`) to keep temp files identifiable. Files are deleted after use - TTS files after `afplay` finishes, STT files after whisper exits.

**Why `crypto.randomBytes()` instead of predictable names:** The random filename pattern prevents TOCTOU (time-of-check-time-of-use) race conditions. Python's `NamedTemporaryFile` with `delete=False` follows a create-close-reopen pattern that leaves a window between file creation and the process reopening it for writing. During that window, an attacker could replace the file with a symlink pointing to a sensitive location (a symlink attack), causing the process to overwrite an arbitrary file. By generating an unguessable 12-byte hex filename via `crypto.randomBytes(12)`, the path is effectively unguessable - an attacker cannot predict the filename to create a race condition. The `atrophy-tts-` / `atrophy-stt-` prefixes are for human identification only and do not weaken the randomness of the path.

**Temp file naming examples:**
- TTS: `/tmp/atrophy-tts-a3f7b2c9e1d04f6a8b2c.mp3`
- STT: `/tmp/atrophy-stt-7e9c1a3b5d8f2e4a6c0b.wav`

---

## src/main/audio.ts - Audio Bridge (Push-to-Talk)

Bridges renderer audio capture with the main process. In the Python version, `pynput` detected Ctrl key presses and `sounddevice` captured audio - both in the same process. In Electron, these responsibilities are split across processes.

### Architecture

- **Key detection**: Renderer listens for Ctrl keydown/keyup on the `window` object, sends IPC signals to main
- **Audio capture**: Renderer uses `navigator.mediaDevices.getUserMedia()` at 16kHz mono with all processing disabled (echoCancellation, noiseSuppression, autoGainControl all `false` - otherwise Chromium switches macOS to "voice processing" audio mode which downsamples all system audio)
- **PCM transport**: Renderer sends Float32Array chunks over `audio:chunk` IPC channel via `ipcRenderer.send()`
- **Minimum duration**: Clips under 300ms are discarded (accidental taps)
- **Maximum duration**: Configurable via `MAX_RECORD_SEC` (default: 120 seconds)

### Module State

```typescript
let _chunks: Float32Array[];   // Accumulated PCM chunks from renderer
let _recording: boolean;        // Whether recording is active
let _startTime: number;         // Timestamp (ms) when recording started
```

### Exported Functions

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

| Channel | Direction | Type | Purpose |
|---------|-----------|------|---------|
| `audio:start` | renderer -> main | `invoke` (returns void) | Begin recording. Resets chunk buffer and sets `_recording = true`. |
| `audio:stop` | renderer -> main | `invoke` (returns string) | Stop recording. Concatenates all chunks, checks minimum duration (300ms), runs whisper transcription, returns transcribed text. Returns empty string on failure. |
| `audio:chunk` | renderer -> main | `send` (fire-and-forget) | Stream PCM Float32Array chunks during recording. Payload is raw `ArrayBuffer`. Chunks arriving when `_recording` is false are silently dropped. |

### Internal Flow: audio:stop Handler

1. Set `_recording = false`, compute elapsed time
2. If no chunks accumulated, return empty string
3. Concatenate all `Float32Array` chunks into a single contiguous array:
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

### Audio Format

| Property | Value |
|----------|-------|
| Sample rate | 16000 Hz (config.SAMPLE_RATE) |
| Channels | 1 (mono, config.CHANNELS) |
| Bit depth | 32-bit float (Float32Array, range [-1.0, 1.0]) |
| Buffer size | 4096 samples per ScriptProcessorNode callback |
| Transport | Raw ArrayBuffer over IPC |

---

## src/main/stt.ts - Speech-to-Text

Whisper.cpp with Metal acceleration (Apple Silicon GPU). Two transcription modes for different latency/accuracy tradeoffs.

### Exported Functions

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

| Property | `transcribe()` | `transcribeFast()` |
|----------|----------------|---------------------|
| Use case | Full conversation turns | Wake word clips (~2 seconds) |
| Model | `config.WHISPER_MODEL` (ggml-tiny.en.bin) | Prefers `ggml-tiny.en.bin` in same directory; falls back to `config.WHISPER_MODEL` |
| Threads | 4 (`-t 4`) | 2 (`-t 2`) |
| Timeout | 30,000 ms | 5,000 ms |
| Error handling | Returns empty string (graceful) | Returns empty string (graceful) |
| Typical latency | < 1 second for short clips | < 200ms for 2-second clips |

### Whisper.cpp Subprocess Details

Both modes spawn the same binary with nearly identical arguments:

```
whisper-cli -m <model_path> -f <wav_path> --no-timestamps -t <threads> --language en
```

Full argument breakdown:

| Flag | Value | Purpose |
|------|-------|---------|
| `-m` | Path to GGML model file | Model selection |
| `-f` | Path to temp WAV file | Input audio |
| `--no-timestamps` | (flag) | Suppress `[00:00.000 --> 00:02.000]` timestamp prefixes |
| `-t` | `4` or `2` | Thread count (fewer = lighter CPU footprint) |
| `--language` | `en` | Force English (skip language detection) |

The binary path defaults to `vendor/whisper.cpp/build/bin/whisper-cli` relative to the whisper path. The model defaults to `vendor/whisper.cpp/models/ggml-tiny.en.bin`. Both are resolved via `config.WHISPER_BIN` and `config.WHISPER_MODEL`.

### WAV File Writing (Internal)

```typescript
function writeWav(
  audioData: Float32Array,
  sampleRate: number,
  channels: number,
): string
```

Converts Float32Array PCM to a standard WAV file that whisper.cpp can read. Returns the path to the temp WAV file.

**Conversion process:**

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

2. Write 44-byte RIFF WAV header:

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

**WAV output format:**

| Property | Value |
|----------|-------|
| Format | PCM (uncompressed) |
| Sample rate | 16000 Hz |
| Channels | 1 (mono) |
| Bit depth | 16-bit signed integer |
| Byte order | Little-endian |
| File extension | `.wav` |

### Output Parsing

Whisper.cpp stdout contains metadata lines (prefixed with `[`) and transcription lines. The parser:

1. Splits stdout on newlines
2. Trims each line
3. Filters out empty lines and lines starting with `[` (timestamps, model info)
4. Joins remaining lines with spaces

Example raw whisper output:
```
[00:00:00.000 --> 00:00:02.000]   Hello, how are you today?
```
After parsing: `Hello, how are you today?`

### Error Handling

Both `transcribe()` and `transcribeFast()` are designed for graceful degradation:

- **Non-zero exit code**: Returns empty string (does not reject)
- **Process error (e.g. binary not found)**: Returns empty string
- **Timeout**: Kills the process, cleans up temp file, rejects with descriptive error
- **Temp file cleanup**: Always runs in `close` and `error` handlers via `try { fs.unlinkSync(wavPath); } catch {}`

### Timeout Implementation

```typescript
const timeout = setTimeout(() => {
  try { proc.kill(); } catch { /* noop */ }
  cleanup();
  reject(new Error('Whisper transcription timed out (30s)'));
}, 30000);
```

The timeout is cleared when the process exits normally. The kill signal is `SIGTERM` (default for `process.kill()`).

---

## src/main/tts.ts - Text-to-Speech

Three-tier fallback chain with prosody tag support. The module handles synthesis (text to audio file), playback (audio file to speakers), and a sequential playback queue for streaming TTS.

### Exported Functions

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

1. **Strip code blocks**: Remove fenced (` ``` `) and inline (`` ` ``) code blocks via regex
2. **Check text length**: Run `processProsody()` to get cleaned text. If result is empty or under 8 characters, return null
3. **Try ElevenLabs**: If `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` are configured, call `synthesiseElevenLabsStream()`. On failure, log and continue.
4. **Try Fal**: If `FAL_VOICE_ID` is configured, call `synthesiseFal()`. On failure, log and continue.
5. **Try macOS say**: Call `synthesiseMacOS()`. On failure, log and return null.
6. **All failed**: Log "No voice available - skipping audio", return null.

### Tier 1: ElevenLabs Streaming

**Function:** `synthesiseElevenLabsStream(text: string): Promise<string>`

The primary TTS backend with the lowest latency. Uses the ElevenLabs streaming endpoint to get audio bytes in a single HTTP response.

**API endpoint:**
```
POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream?output_format=mp3_44100_128
```

**Request headers:**
- `xi-api-key`: The ElevenLabs API key
- `Content-Type`: `application/json`

**Request body:**
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

Voice settings are the base values from config, adjusted by prosody tag deltas and clamped to [0, 1]. Each individual delta is also clamped to [-0.15, +0.15] before being added to the base.

**Clamping logic:**
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

Fallback using fal.ai as a proxy to ElevenLabs. Uses a submit-and-poll pattern.

**Submit endpoint:**
```
POST https://queue.fal.run/{config.FAL_TTS_ENDPOINT}
```

Default endpoint: `fal-ai/elevenlabs/tts/eleven-v3`

**Authentication:** `Authorization: Key {FAL_KEY}` header. FAL_KEY comes from the `FAL_KEY` environment variable.

**Request body:**
```json
{
  "text": "<cleaned text>",
  "voice": "<FAL_VOICE_ID>",
  "stability": 0.5
}
```

Note: Fal uses only the `stability` parameter from config, not similarity_boost or style. Prosody tag overrides are processed (to clean the text) but the delta values are not applied to the Fal request.

**Response handling - two paths:**

1. **Synchronous result**: If the response includes `audio.url`, use it directly (small queue, fast turnaround)
2. **Async polling**: If the response includes `request_id`, poll for results:
   - Poll URL: `https://queue.fal.run/{endpoint}/requests/{request_id}`
   - Poll interval: 1000ms
   - Max attempts: 30 (total timeout: ~30 seconds)
   - Success: response contains `audio.url`
   - Failure: response has `status === 'FAILED'`
   - Timeout: throws after 30 attempts with no result

**Audio download:** Once the audio URL is obtained, download with a 30-second AbortSignal timeout:
```typescript
const audioResponse = await fetch(audioUrl, { signal: AbortSignal.timeout(30_000) });
```

**Output format:** MP3 (downloaded from Fal's CDN), written to temp file.

### Tier 3: macOS say (Last Resort)

**Function:** `synthesiseMacOS(text: string): Promise<string>`

Uses the built-in macOS `say` command as a last resort when no cloud TTS is available.

**Subprocess invocation:**
```
say -v Samantha -r 175 -o <output_path> <cleaned_text>
```

| Flag | Value | Purpose |
|------|-------|---------|
| `-v` | `Samantha` | Voice selection (high-quality female voice) |
| `-r` | `175` | Speech rate in words per minute |
| `-o` | Temp file path | Output to file instead of speakers |

**Text cleaning:** All prosody tags are stripped via simple regex `text.replace(/\[[\w\s]+\]/g, '')` (not the full prosody processor - just removes square-bracket tags).

**Output format:** AIFF (Apple's native audio format), uncompressed. File extension is `.aiff`.

**Error handling:** Non-zero exit code rejects the promise. Process spawn errors also reject.

### Prosody System

The agent can embed prosody tags in its output text like `[whispers]`, `[warmly]`, `[sighs]`. These control two things:

1. **Voice parameter deltas** - Modify ElevenLabs stability, similarity_boost, and style settings
2. **Text replacements** - Breath/pause tags become ellipses for natural pauses

#### Regex Patterns

```typescript
const PROSODY_RE = /\[([^\]]+)\]/g;       // Matches [any tag]
const CODE_BLOCK_RE = /```[\s\S]*?```/g;  // Fenced code blocks
const INLINE_CODE_RE = /`[^`]+`/g;        // Inline code spans
```

#### processProsody() - Internal Function

```typescript
function processProsody(text: string): ProsodyResult
```

**Returns:**
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

Each tag applies deltas to `[stability, similarity_boost, style]`:

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

These tags are replaced with ellipsis text rather than stripped, creating natural pauses in the synthesised audio:

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

Code blocks (both fenced and inline) are stripped before TTS - the agent should not try to speak code:

```typescript
const CODE_BLOCK_RE = /```[\s\S]*?```/g;  // Fenced: ```code```
const INLINE_CODE_RE = /`[^`]+`/g;         // Inline: `code`
```

Text that is too short after prosody processing (< 8 characters) is silently skipped (returns null).

### Playback via afplay

```
afplay -r <rate> <audioPath>
```

| Flag | Value | Purpose |
|------|-------|---------|
| `-r` | `config.TTS_PLAYBACK_RATE` (default: 1.12) | Playback speed multiplier. Values > 1.0 speed up. |

**Temp file cleanup:** The audio file is deleted via `fs.unlinkSync()` in both the `close` and `error` handlers. Errors during unlink are silently swallowed.

### Audio Playback Queue

TTS audio files are played sequentially through a queue in the main process. This enables the streaming pipeline where sentences are synthesised concurrently but played in order.

**Internal state:**

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

These callbacks are forwarded to the renderer via IPC so the UI can show effects during audio playback:

| Callback | IPC Channel | Purpose |
|----------|-------------|---------|
| `onStarted(index)` | `tts:started` | Sentence begins playing - activates warm vignette overlay |
| `onDone(index)` | `tts:done` | Sentence finishes playing |
| `onQueueEmpty()` | `tts:queueEmpty` | All audio played - deactivates vignette |

### Per-Agent Voice Config

Voice parameters come from the agent manifest (`agent.json`) and are resolved via the three-tier config system:

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

---

## src/main/wake-word.ts - Wake Word Detection

Background ambient listener using whisper.cpp keyword spotting. This system is **independent of the mic/PTT button** - it runs in its own loop and does not require the user to press any button.

### Exported Functions

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

```typescript
let _running: boolean;                       // Listener active
let _paused: boolean;                        // Temporarily suppressed (auto-set on detection)
let _onDetected: (() => void) | null;        // Detection callback
```

### Architecture (Differs from Python)

In Python, `sounddevice.rec()` captured audio directly in the background thread. In Electron, the renderer captures audio via Web Audio API and sends chunks to main via IPC. The main process tells the renderer to start/stop ambient capture:

1. Main sends `wakeword:start` (with `config.WAKE_CHUNK_SECONDS` duration) to renderer
2. Renderer captures audio and sends Float32Array chunks via `wakeword:chunk`
3. Main receives chunks, checks RMS energy, runs fast whisper transcription

### Detection Loop (per chunk)

1. Receive audio chunk from renderer via `wakeword:chunk` IPC
2. If `_running` is false or `_paused` is true, drop the chunk
3. Convert `ArrayBuffer` to `Float32Array`
4. Compute RMS amplitude:
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

| Channel | Direction | Type | Purpose |
|---------|-----------|------|---------|
| `wakeword:start` | main -> renderer | `send` | Start ambient audio capture. Payload: `chunkSeconds` (number) |
| `wakeword:stop` | main -> renderer | `send` | Stop ambient audio capture |
| `wakeword:chunk` | renderer -> main | `send` | Audio chunk for analysis. Payload: `ArrayBuffer` |

### Pre-flight Checks

`startWakeWordListener()` performs three checks before starting:

1. `config.WAKE_WORD_ENABLED` must be true (default: false)
2. `config.WHISPER_BIN` must exist on disk (`fs.existsSync()`)
3. `config.WHISPER_MODEL` must exist on disk (`fs.existsSync()`)

If any check fails, the function returns without starting (logs the reason).

### RMS Silence Threshold

| Threshold | Value | Purpose |
|-----------|-------|---------|
| Near-silence (wake word) | 0.005 | Skip chunks that are essentially ambient noise |

This threshold is hardcoded (not configurable). It is deliberately low to avoid missing soft speech - the whisper model handles the actual recognition.

### Wake Word Configuration

| Config Key | Default | Description |
|------------|---------|-------------|
| `WAKE_WORD_ENABLED` | `false` | Master enable/disable |
| `WAKE_CHUNK_SECONDS` | `2` | Duration of each ambient capture chunk sent to main |
| `WAKE_WORDS` | `['hey <name>', '<name>']` | List of trigger phrases (from agent manifest) |

**Enabling wake words:**
- In the GUI, click the microphone-with-waves button in the top-right (shortcut: **Cmd+Shift+W**). The button turns green when active.
- Via environment variable: `WAKE_WORD_ENABLED=true`
- Via the settings panel: Input section > Wake Word Detection toggle

---

## src/main/call.ts - Voice Call Mode

Hands-free continuous conversation loop. Captures audio from the mic (via renderer IPC chunks), detects speech via energy-based VAD, transcribes with whisper, runs inference, speaks the response via TTS. Repeats until stopped.

### Call State Machine

```
idle -> listening -> thinking -> speaking -> listening -> ...
```

```typescript
export type CallStatus = 'idle' | 'listening' | 'thinking' | 'speaking';
```

### Exported Functions

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

Energy-based detection using RMS amplitude. Constants are hardcoded at the module level:

| Constant | Value | Purpose |
|----------|-------|---------|
| `ENERGY_THRESHOLD` | `0.015` | RMS energy level to classify a chunk as speech |
| `SILENCE_DURATION` | `1.5` | Seconds of continuous silence to end an utterance |
| `MIN_SPEECH_DURATION` | `0.5` | Minimum seconds of speech to process (shorter is discarded) |
| `CHUNK_SAMPLES` | `1600` | Samples per chunk (100ms at 16kHz) |
| `MAX_UTTERANCE_SEC` | `30` | Safety cap on utterance length |

**Derived values (computed at runtime):**
- `silenceChunksNeeded = ceil((1.5 * 16000) / 1600) = 15` chunks
- `maxChunks = ceil((30 * 16000) / 1600) = 300` chunks

### VAD Chunk Processing (_ingestChunk)

For each incoming audio chunk:

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

Returns a `Promise<Float32Array | null>`. The promise resolves when:
- The VAD detects end-of-utterance (silence after speech)
- The safety timeout fires (`MAX_UTTERANCE_SEC * 1000 + 500` ms)
- `stopCall()` is called (resolves with null)

The safety timeout has a 500ms buffer beyond the max utterance time to allow the VAD to naturally finalise before forcing it.

### Utterance Finalisation (_finaliseUtterance)

1. Capture the resolver function and null out the module-level reference
2. Set `_utteranceReady = true` (guard flag)
3. If no chunks accumulated, resolve with null
4. Concatenate all chunks into a single `Float32Array`
5. Clear the chunks array
6. Resolve with the concatenated audio

### Conversation Loop (_runLoop)

The main async loop that runs for the duration of a call:

1. **Capture**: Call `_captureUtterance()` - blocks until speech is detected and silence follows
2. **Duration check**: If audio is shorter than `MIN_SPEECH_DURATION` (0.5s), skip and re-listen
3. **Transcribe**: Set status to `thinking`, run `transcribe(audio)` from stt.ts
4. **Validate**: If transcription is empty or under 2 characters, skip and re-listen
5. **Emit**: Fire `userSaid` event with trimmed text
6. **Infer**: Call `_runInference(text)` - streams Claude CLI response, forwarding all events to the renderer
7. **Emit**: Fire `agentSaid` event with full response
8. **Speak**: Set status to `speaking`, synthesise and play audio inline (not queued)
9. **Resume**: Set status to `listening`, loop back to step 1

**Error handling:** Errors in any phase are emitted via the `error` event. If the call is still active, status returns to `listening` and the loop continues.

### Inference During Call (_runInference)

Calls `streamInference()` from the inference module and collects the full response. All streaming events are forwarded to the renderer for live display:

| Inference Event | Forwarded IPC Channel | Notes |
|-----------------|----------------------|-------|
| `TextDelta` | `inference:textDelta` | Real-time text streaming |
| `SentenceReady` | `inference:sentenceReady` | Audio path is empty string (TTS is handled separately) |
| `ToolUse` | `inference:toolUse` | Tool name |
| `Compacting` | `inference:compacting` | Context window compaction |
| `StreamDone` | `inference:done` | Updates `_cliSessionId` if a new session ID is returned |
| `StreamError` | `inference:error` | Emits error event, resolves with null |

**Important:** During voice calls, TTS is played inline via `synthesise()` + `playAudio()` (not through the playback queue). This keeps the conversation loop synchronous - the agent waits for the full response to be spoken before listening again.

### Event System

The call module uses a Node.js `EventEmitter` for internal events:

| Event | Payload | When |
|-------|---------|------|
| `status` | `CallStatus` | Every state transition |
| `userSaid` | `string` | After successful transcription |
| `agentSaid` | `string` | After inference completes with a response |
| `error` | `string` | Any error during capture, transcription, inference, or TTS |
| `ended` | (none) | Call terminated (cleanup complete) |

Status changes are also forwarded to the renderer via `call:statusChanged` IPC.

### IPC Channels

| Channel | Direction | Type | Purpose |
|---------|-----------|------|---------|
| `call:start` | renderer -> main | `invoke` | Start a voice call. Args: `(systemPrompt: string, cliSessionId: string | null)` |
| `call:stop` | renderer -> main | `invoke` | Stop the current call |
| `call:status` | renderer -> main | `invoke` | Get current state: `{ active, status, muted }` |
| `call:setMuted` | renderer -> main | `invoke` | Mute/unmute. Arg: `(muted: boolean)` |
| `call:chunk` | renderer -> main | `send` | Stream PCM chunks during call. Payload: `ArrayBuffer` |
| `call:statusChanged` | main -> renderer | `send` | Status change notification. Payload: `CallStatus` |

### Cleanup (_cleanup)

Called when the loop exits (normally or via error):

1. Set `_active = false`
2. Clear all VAD state (`_chunks`, `_speechStarted`, `_silentChunks`, `_utteranceResolve`)
3. Set status to `idle` (triggers IPC notification)
4. Emit `ended` event

---

## Streaming TTS Pipeline

TTS runs as a parallel pipeline between the main and renderer processes during normal (non-call) conversation:

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

---

## Configuration Reference

All voice-related config values, their defaults, and where they come from:

### Audio Capture

| Key | Default | Source | Description |
|-----|---------|--------|-------------|
| `SAMPLE_RATE` | `16000` | Hardcoded default | Audio sample rate in Hz |
| `CHANNELS` | `1` | Hardcoded default | Number of audio channels (mono) |
| `MAX_RECORD_SEC` | `120` | Hardcoded default | Maximum push-to-talk recording duration in seconds |

### TTS (ElevenLabs)

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

| Key | Default | Source | Description |
|-----|---------|--------|-------------|
| `FAL_TTS_ENDPOINT` | `'fal-ai/elevenlabs/tts/eleven-v3'` | Hardcoded default | Fal API endpoint path |
| `FAL_VOICE_ID` | `''` | Agent config | Voice identifier for Fal |

Authentication via `FAL_KEY` environment variable (not in config system - read directly from `process.env`).

### Wake Word

| Key | Default | Source | Description |
|-----|---------|--------|-------------|
| `WAKE_WORD_ENABLED` | `false` | User config | Master toggle |
| `WAKE_CHUNK_SECONDS` | `2` | Hardcoded default | Duration of ambient capture chunks |
| `WAKE_WORDS` | `['hey <name>', '<name>']` | Agent manifest | Trigger phrases |

### Whisper

| Key | Default | Source | Description |
|-----|---------|--------|-------------|
| `WHISPER_BIN` | `'<WHISPER_PATH>/build/bin/whisper-cli'` | Derived from WHISPER_PATH | Path to whisper-cli binary |
| `WHISPER_MODEL` | `'<WHISPER_PATH>/models/ggml-tiny.en.bin'` | Derived from WHISPER_PATH | Path to GGML model file |

---

## IPC Channel Summary

Complete list of IPC channels used by the voice pipeline:

### Audio Capture (Push-to-Talk)

| Channel | Direction | Type | Payload |
|---------|-----------|------|---------|
| `audio:start` | renderer -> main | invoke | (none) -> void |
| `audio:stop` | renderer -> main | invoke | (none) -> string (transcription) |
| `audio:chunk` | renderer -> main | send | ArrayBuffer (Float32Array of PCM samples) |

### TTS Playback

| Channel | Direction | Type | Payload |
|---------|-----------|------|---------|
| `tts:started` | main -> renderer | send | number (sentence index) |
| `tts:done` | main -> renderer | send | number (sentence index) |
| `tts:queueEmpty` | main -> renderer | send | (none) |

### Wake Word

| Channel | Direction | Type | Payload |
|---------|-----------|------|---------|
| `wakeword:start` | main -> renderer | send | number (chunk seconds) |
| `wakeword:stop` | main -> renderer | send | (none) |
| `wakeword:chunk` | renderer -> main | send | ArrayBuffer (Float32Array of PCM samples) |

### Voice Call

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

The renderer accesses voice features through the `window.atrophy` API exposed via contextBridge. Relevant methods:

### Audio Capture

```typescript
startRecording: () => Promise<void>              // Triggers audio:start
stopRecording: () => Promise<string>             // Triggers audio:stop, returns transcription
sendAudioChunk: (buffer: ArrayBuffer) => void    // Sends audio:chunk (fire-and-forget)
```

### TTS Events

```typescript
onTtsStarted: (cb: (index: number) => void) => () => void      // Listens to tts:started
onTtsDone: (cb: (index: number) => void) => () => void          // Listens to tts:done
onTtsQueueEmpty: (cb: () => void) => () => void                  // Listens to tts:queueEmpty
```

### Wake Word

```typescript
onWakeWordStart: (cb: (chunkSeconds: number) => void) => () => void  // Listens to wakeword:start
onWakeWordStop: (cb: () => void) => () => void                        // Listens to wakeword:stop
sendWakeWordChunk: (buffer: ArrayBuffer) => void                      // Sends wakeword:chunk
```

All listener functions return an unsubscribe function (`() => void`) for cleanup. The `createListener` helper in `preload/index.ts` wraps `ipcRenderer.on()` and returns a function that calls `ipcRenderer.removeListener()`.

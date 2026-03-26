# src/main/audio.ts - Audio Bridge (Push-to-Talk)

**Line count:** ~100 lines  
**Dependencies:** Electron (`ipcMain`, `BrowserWindow`), `./stt`, `./config`, `./logger`  
**Purpose:** Bridges renderer audio capture with main process for push-to-talk voice input

## Overview

In Electron, audio capture happens in the renderer via Web Audio API (browser media APIs), while all processing (transcription, synthesis, playback) happens in the main process (filesystem, native binaries, subprocess spawning). This module manages the split by accumulating PCM chunks sent from the renderer over IPC and handing the complete recording to the STT module when the user releases the push-to-talk key.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Renderer Process                          │
│  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐  │
│  │ Key detection│────▶│ getUserMedia │────▶│ ScriptProcessor │  │
│  │ (Ctrl key)  │     │ (16kHz mono) │     │ (4096 samples)  │  │
│  └─────────────┘     └──────────────┘     └────────┬────────┘  │
│                                                    │            │
│                                          audio:chunk (IPC)      │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Main Process                              │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────────┐  │
│  │ audio:start  │◀────│ audio:chunk  │◀────│  Float32Array   │  │
│  │ audio:stop   │     │ (accumulate) │     │  chunks         │  │
│  └──────┬───────┘     └──────────────┘     └─────────────────┘  │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────┐                                               │
│  │ transcribe() │                                               │
│  │ (whisper.cpp)│                                               │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
```

## Module State

```typescript
let _chunks: Float32Array[] = [];
let _totalSamples = 0;
let _recording = false;
let _startTime = 0;

// Cap at ~5 minutes of 16kHz mono audio (~19MB) to prevent OOM
const MAX_SAMPLES = 16000 * 60 * 5;
```

| Variable | Purpose |
|----------|---------|
| `_chunks` | Array of Float32Array PCM chunks from renderer |
| `_totalSamples` | Running total of samples (for cap check) |
| `_recording` | Whether recording is active |
| `_startTime` | Timestamp when recording started (for duration logging) |
| `MAX_SAMPLES` | Safety cap to prevent OOM (5 minutes at 16kHz = ~19MB) |

## IPC Registration

```typescript
export function registerAudioHandlers(getWindow: () => BrowserWindow | null): void {
  ipcMain.handle('audio:start', () => {
    _chunks = [];
    _totalSamples = 0;
    _recording = true;
    _startTime = Date.now();
    log.info('recording started');
  });

  ipcMain.handle('audio:stop', async () => {
    _recording = false;
    const elapsed = (Date.now() - _startTime) / 1000;
    log.info(`recording stopped (${elapsed.toFixed(1)}s)`);

    if (_chunks.length === 0) {
      return '';
    }

    // Concatenate all chunks
    const totalLength = _chunks.reduce((acc, c) => acc + c.length, 0);
    const audio = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of _chunks) {
      audio.set(chunk, offset);
      offset += chunk.length;
    }
    _chunks = [];

    const config = getConfig();

    // Skip if too short (< 300ms)
    if (audio.length < config.SAMPLE_RATE * 0.3) {
      log.debug('too short, skipping');
      return '';
    }

    // Skip if too long
    if (elapsed > config.MAX_RECORD_SEC) {
      log.warn('exceeded max recording time');
    }

    // Transcribe
    try {
      const text = await transcribe(audio);
      log.debug(`transcribed: "${text.slice(0, 80)}"`);
      return text;
    } catch (e) {
      log.error(`transcription failed: ${e}`);
      return '';
    }
  });

  // Receive PCM chunks from renderer
  ipcMain.on('audio:chunk', (_event, buffer: ArrayBuffer) => {
    if (!_recording) return;
    const chunk = new Float32Array(buffer);
    if (_totalSamples + chunk.length > MAX_SAMPLES) {
      log.warn('audio chunk limit reached, ignoring further chunks');
      return;
    }
    _totalSamples += chunk.length;
    _chunks.push(chunk);
  });
}
```

### audio:start Handler

**Purpose:** Initialize recording state when user presses push-to-talk key.

**Actions:**
1. Clear chunks array
2. Reset sample counter
3. Set `_recording = true`
4. Record start timestamp

### audio:stop Handler

**Purpose:** Stop recording, concatenate chunks, run transcription.

**Flow:**
1. Set `_recording = false`
2. Calculate elapsed time
3. If no chunks, return empty string
4. Concatenate all Float32Array chunks into single contiguous array
5. Clear chunks buffer
6. Check minimum duration (300ms at 16kHz = 4800 samples)
7. Log warning if max recording time exceeded (does not truncate)
8. Call `transcribe(audio)` from stt.ts
9. Return transcribed text, or empty string on error

**Why concatenation is necessary:** The renderer sends audio in small buffers (4096 samples each, ~256ms at 16kHz), but whisper expects a single continuous WAV file.

### audio:chunk Handler

**Purpose:** Accumulate PCM chunks from renderer during recording.

**Flow:**
1. If not recording, silently drop chunk
2. Convert ArrayBuffer to Float32Array (zero-copy)
3. Check if adding this chunk would exceed MAX_SAMPLES
4. If over limit, log warning and ignore further chunks
5. Add to chunks array

**Why the cap:** Prevents OOM if the key gets stuck or user holds it indefinitely. 5 minutes of 16kHz mono audio is ~19MB.

## Chunk Concatenation

```typescript
const totalLength = _chunks.reduce((acc, c) => acc + c.length, 0);
const audio = new Float32Array(totalLength);
let offset = 0;
for (const chunk of _chunks) {
  audio.set(chunk, offset);
  offset += chunk.length;
}
```

**How it works:**
1. Calculate total length by summing all chunk lengths
2. Allocate single Float32Array of exact size
3. Copy each chunk into the correct offset position
4. Result is a contiguous Float32Array ready for WAV conversion

## Minimum Duration Check

```typescript
if (audio.length < config.SAMPLE_RATE * 0.3) {
  log.debug('too short, skipping');
  return '';
}
```

**Purpose:** Filter out accidental key taps that produce no meaningful speech. 300ms at 16kHz = 4800 samples.

## Renderer Side (InputBar.svelte)

The renderer side captures audio using `ScriptProcessorNode`:

```typescript
const processor = audioContext.createScriptProcessor(4096, 1, 1);
processor.onaudioprocess = (e) => {
  if (!isRecording) return;
  const input = e.inputBuffer.getChannelData(0);
  const buffer = new Float32Array(input);
  api.sendAudioChunk(buffer.buffer);
};
```

**Audio format:**
- Sample rate: 16000 Hz
- Channels: 1 (mono)
- Bit depth: 32-bit float (Float32Array, range [-1.0, 1.0])
- Buffer size: 4096 samples per callback (~256ms)
- Transport: Raw ArrayBuffer over IPC

## Push-to-Talk Binding

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

**Checks before starting:**
1. Not already recording
2. Inference is idle (don't interrupt agent speech)

## Audio Format Summary

| Property | Value |
|----------|-------|
| Sample rate | 16000 Hz |
| Channels | 1 (mono) |
| Bit depth | 32-bit float |
| Range | [-1.0, 1.0] |
| Buffer size | 4096 samples |
| Transport | Raw ArrayBuffer over IPC |

## Error Handling

- **No chunks:** Return empty string
- **Too short (< 300ms):** Return empty string
- **Transcription error:** Log error, return empty string
- **Max samples exceeded:** Log warning, ignore further chunks

All errors are handled gracefully - voice input is a convenience feature and should never crash the app.

## Exported API

| Function | Purpose |
|----------|---------|
| `registerAudioHandlers(getWindow)` | Register IPC handlers for audio:start, audio:stop, audio:chunk |
| `isRecording()` | Returns whether recording is currently in progress |

## See Also

- `src/main/stt.ts` - Called by audio:stop for transcription
- `src/renderer/components/InputBar.svelte` - Renderer-side audio capture
- `src/main/wake-word.ts` - Similar audio capture for wake word detection

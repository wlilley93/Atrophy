# src/main/wake-word.ts - Wake Word Detection

**Line count:** ~120 lines  
**Dependencies:** Electron (`ipcMain`, `BrowserWindow`), `./stt`, `./config`, `./logger`  
**Purpose:** Ambient wake word detection using local whisper.cpp transcription

## Overview

This module implements wake word detection for hands-free activation. When enabled, it continuously transcribes ambient audio and checks for configured wake words (e.g., "hey xan", "xan"). All processing is local - audio never leaves the machine.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Renderer Process                          │
│  ┌─────────────────┐     ┌─────────────────────────────────┐   │
│  │ wakeword:start  │────▶│ Continuous audio capture        │   │
│  │ wakeword:stop   │     │ (chunks every WAKE_CHUNK_SEC)   │   │
│  └─────────────────┘     └───────────────┬─────────────────┘   │
│                                          │                      │
│                                wakeword:chunk (IPC)             │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Main Process                              │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────────┐  │
│  │ wakeword:    │     │ RMS check    │     │ transcribeFast()│  │
│  │ chunk        │────▶│ (skip quiet) │────▶│ (whisper.cpp)   │  │
│  └──────────────┘     └──────────────┘     └────────┬────────┘  │
│                                                    │            │
│                                                    ▼            │
│  ┌──────────────────────────────────────────────────────┐     │
│  │ Check for wake word match in transcription           │     │
│  │ If matched: pause detection, call onDetected()       │     │
│  └──────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

## Module State

```typescript
let _running = false;
let _paused = false;
let _onDetected: (() => void) | null = null;
let _transcribing = false;
```

| Variable | Purpose |
|----------|---------|
| `_running` | Whether wake word detection is active |
| `_paused` | Temporarily paused (e.g., during TTS playback) |
| `_onDetected` | Callback when wake word is detected |
| `_transcribing` | Prevents concurrent transcriptions |

## RMS Calculation

```typescript
function rms(audio: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < audio.length; i++) {
    sum += audio[i] * audio[i];
  }
  return Math.sqrt(sum / audio.length);
}
```

**Purpose:** Calculate root mean square (RMS) energy of audio chunk. Used to skip near-silent chunks and avoid unnecessary transcription.

**Threshold:** Chunks with RMS < 0.005 are skipped.

## Public API

### startWakeWordListener

```typescript
export function startWakeWordListener(
  onDetected: () => void,
  getWindow: () => BrowserWindow | null,
): void {
  const config = getConfig();

  // Pre-flight checks
  if (!config.WAKE_WORD_ENABLED) return;
  if (!fs.existsSync(config.WHISPER_BIN)) {
    log.warn(`whisper binary not found at ${config.WHISPER_BIN}`);
    return;
  }
  if (!fs.existsSync(config.WHISPER_MODEL)) {
    log.warn(`whisper model not found at ${config.WHISPER_MODEL}`);
    return;
  }

  _running = true;
  _paused = false;
  _onDetected = onDetected;

  // Tell renderer to start ambient audio capture
  const win = getWindow();
  if (win) {
    win.webContents.send('wakeword:start', config.WAKE_CHUNK_SECONDS);
  }

  log.info(`listener started (words: ${config.WAKE_WORDS.join(', ')})`);
}
```

**Pre-flight checks:**
1. `WAKE_WORD_ENABLED` must be true in config
2. whisper.cpp binary must exist at configured path
3. whisper model must exist at configured path

**Renderer signal:** Sends `wakeword:start` with chunk duration in seconds. Renderer responds with `wakeword:chunk` IPC messages.

### stopWakeWordListener

```typescript
export function stopWakeWordListener(getWindow: () => BrowserWindow | null): void {
  _running = false;
  _onDetected = null;

  const win = getWindow();
  if (win) {
    win.webContents.send('wakeword:stop');
  }

  log.info('listener stopped');
}
```

**Purpose:** Stop wake word detection and tell renderer to stop capturing ambient audio.

### pauseWakeWord / resumeWakeWord

```typescript
export function pauseWakeWord(): void {
  _paused = true;
}

export function resumeWakeWord(): void {
  _paused = false;
}
```

**Purpose:** Temporarily pause detection during TTS playback to avoid the agent detecting its own speech.

### isWakeWordListening

```typescript
export function isWakeWordListening(): boolean {
  return _running && !_paused;
}
```

**Purpose:** Check if wake word detection is actively listening.

## IPC Handler

```typescript
ipcMain.on('wakeword:chunk', async (_event, buffer: ArrayBuffer) => {
  if (!_running || _paused || _transcribing) return;

  const audio = new Float32Array(buffer);

  // Skip near-silent chunks
  if (rms(audio) < 0.005) return;

  _transcribing = true;
  try {
    const text = await transcribeFast(audio);
    if (!text) return;

    const textLower = text.toLowerCase().trim();
    const config = getConfig();
    const wakeWords = config.WAKE_WORDS.map((w) => w.toLowerCase());

    // Check for wake word match
    const matched = wakeWords.some((w) => textLower.includes(w));
    if (matched) {
      log.info(`detected: "${textLower}"`);
      _paused = true;  // Auto-pause until explicitly resumed
      _onDetected?.();
    }
  } catch (e) {
    log.error(`transcription error: ${e}`);
  } finally {
    _transcribing = false;
  }
});
```

### Processing Flow

1. **Guard checks:** Skip if not running, paused, or already transcribing
2. **RMS check:** Skip near-silent chunks (RMS < 0.005)
3. **Transcribe:** Call `transcribeFast()` for quick transcription
4. **Normalize:** Convert to lowercase and trim
5. **Match:** Check if any wake word is contained in transcription
6. **On match:** Log, auto-pause, call detection callback

### Auto-Pause on Detection

```typescript
if (matched) {
  _paused = true;  // Auto-pause until explicitly resumed
  _onDetected?.();
}
```

**Why:** After detecting the wake word, pause detection to prevent continuous triggering. The caller must explicitly resume (typically after the agent finishes speaking).

### Concurrency Prevention

```typescript
if (_transcribing) return;
// ...
_transcribing = true;
try {
  // ... transcribe ...
} finally {
  _transcribing = false;
}
```

**Why:** Prevents multiple transcriptions running concurrently, which could cause:
- CPU overload from multiple whisper.cpp processes
- Race conditions in detection logic
- Audio backlog buildup

## Wake Word Configuration

Wake words are configured per-agent in `agent.json`:

```json
{
  "wake_words": ["hey xan", "xan"]
}
```

**Matching:** Case-insensitive substring match. "hey xan" matches "Hey Xan, are you there?".

## Renderer Integration

The renderer captures ambient audio when `wakeword:start` is received:

```typescript
ipcRenderer.on('wakeword:start', (_event, chunkSeconds) => {
  // Start continuous audio capture
  // Send chunks every chunkSeconds via wakeword:chunk
});

ipcRenderer.on('wakeword:stop', () => {
  // Stop audio capture
});
```

## Error Handling

- **Transcription error:** Log error, continue listening (graceful degradation)
- **Empty transcription:** Skip silently
- **No match:** Continue listening

Wake word detection is designed to be resilient - transient errors should not disable the feature.

## Performance Considerations

1. **RMS pre-filter:** Skips silent chunks, reducing whisper.cpp invocations
2. **transcribeFast:** Uses tiny model, 2 threads, 5-second timeout
3. **Concurrency limit:** Only one transcription at a time
4. **Auto-pause:** Prevents rapid re-triggering

## Exported API Summary

| Function | Purpose |
|----------|---------|
| `startWakeWordListener(onDetected, getWindow)` | Start ambient wake word detection |
| `stopWakeWordListener(getWindow)` | Stop wake word detection |
| `pauseWakeWord()` | Temporarily pause (e.g., during TTS) |
| `resumeWakeWord()` | Resume after pause |
| `isWakeWordListening()` | Check if actively listening |
| `registerWakeWordHandlers()` | Register IPC handler for wakeword:chunk |

## See Also

- `src/main/stt.ts` - `transcribeFast()` for wake word transcription
- `src/main/tts.ts` - Pauses wake word during TTS playback
- `src/main/app.ts` - Integrates wake word with main process lifecycle

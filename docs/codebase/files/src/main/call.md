# src/main/call.ts - Voice Call Mode

**Line count:** ~350 lines  
**Dependencies:** Node.js built-ins, Electron, `./stt`, `./tts`, `./inference`, `./config`, `./logger`  
**Purpose:** Hands-free continuous conversation loop with VAD-based utterance detection

## Overview

This module implements a hands-free voice call mode where the agent continuously listens, transcribes, infers, and speaks in a loop. It uses energy-based Voice Activity Detection (VAD) to detect when the user starts and stops speaking, then orchestrates the full conversation pipeline.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Voice Call Loop                               │
│                                                                   │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────────┐   │
│  │ 1. Listen   │────▶│ 2. Transcribe│────▶│ 3. Infer        │   │
│  │ (VAD)       │     │ (whisper)   │     │ (Claude Code)   │   │
│  └─────────────┘     └─────────────┘     └────────┬────────┘   │
│                                                   │             │
│  ┌─────────────┐     ┌─────────────┐             │             │
│  │ 5. Listen   │◀────│ 4. Speak    │◀────────────┘             │
│  │ (resume)    │     │ (TTS)       │                           │
│  └─────────────┘     └─────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

## Audio Capture Parameters

```typescript
const ENERGY_THRESHOLD = 0.015;       // RMS energy to count as speech
const SILENCE_DURATION = 1.5;         // Seconds of silence to end utterance
const MIN_SPEECH_DURATION = 0.5;      // Minimum seconds of speech to process
const CHUNK_SAMPLES = 1600;           // 100ms chunks at 16kHz
const MAX_UTTERANCE_SEC = 30;         // Safety cap on utterance length
```

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `ENERGY_THRESHOLD` | 0.015 | RMS threshold for speech detection |
| `SILENCE_DURATION` | 1.5s | Silence required to end utterance |
| `MIN_SPEECH_DURATION` | 0.5s | Minimum speech to process (filter noise) |
| `CHUNK_SAMPLES` | 1600 | 100ms chunks at 16kHz sample rate |
| `MAX_UTTERANCE_SEC` | 30s | Safety cap to prevent runaway |

## Module State

```typescript
export type CallStatus = 'idle' | 'listening' | 'thinking' | 'speaking';

let _active = false;
let _muted = false;
let _status: CallStatus = 'idle';
let _cliSessionId: string | null = null;
let _systemPrompt: string | null = null;

// Audio chunk accumulation for VAD
let _chunks: Float32Array[] = [];
let _speechStarted = false;
let _silentChunks = 0;
let _utteranceReady = false;
let _utteranceResolve: ((audio: Float32Array | null) => void) | null = null;
```

| Variable | Purpose |
|----------|---------|
| `_active` | Whether call is in progress |
| `_muted` | Mic muted (listening but not processing) |
| `_status` | Current state for UI display |
| `_cliSessionId` | Claude CLI session for continuity |
| `_systemPrompt` | System prompt for inference |
| `_chunks` | Accumulated audio for current utterance |
| `_speechStarted` | Whether speech has been detected |
| `_silentChunks` | Count of consecutive silent chunks |
| `_utteranceResolve` | Promise resolver for captured utterance |

## Public API

### startCall

```typescript
export function startCall(
  systemPrompt: string,
  cliSessionId: string | null,
  getWindow: () => BrowserWindow | null,
): void {
  if (_active) return;

  _active = true;
  _muted = false;
  _systemPrompt = systemPrompt;
  _cliSessionId = cliSessionId;
  _getWindow = getWindow;

  _setStatus('listening');
  _runLoop().catch((err) => {
    log.error(`loop error: ${err}`);
    _emitter.emit('error', String(err));
    _cleanup();
  });
}
```

**Purpose:** Start hands-free voice call loop.

**Parameters:**
- `systemPrompt`: System prompt for inference
- `cliSessionId`: CLI session ID for continuity (or null for new session)
- `getWindow`: Getter for main BrowserWindow (for IPC)

### stopCall

```typescript
export function stopCall(): void {
  _active = false;
  // Unblock any pending utterance capture
  if (_utteranceResolve) {
    _utteranceResolve(null);
    _utteranceResolve = null;
  }
}
```

**Purpose:** Stop the voice call loop and unblock any pending operations.

### Call Status Methods

```typescript
export function isInCall(): boolean { return _active; }
export function isMuted(): boolean { return _muted; }
export function setMuted(muted: boolean): void { _muted = muted; }
export function getCallStatus(): CallStatus { return _status; }
export function getCallCliSessionId(): string | null { return _cliSessionId; }
```

### Event Subscription

```typescript
export function onCallEvent(
  event: 'status' | 'userSaid' | 'agentSaid' | 'error' | 'ended',
  listener: (...args: unknown[]) => void,
): void {
  _emitter.on(event, listener);
}

export function offCallEvent(
  event: 'status' | 'userSaid' | 'agentSaid' | 'error' | 'ended',
  listener: (...args: unknown[]) => void,
): void {
  _emitter.off(event, listener);
}
```

**Events:**
- `status`: Call status changed (idle/listening/thinking/speaking)
- `userSaid`: User speech transcribed (payload: text)
- `agentSaid`: Agent response generated (payload: text)
- `error`: Error occurred (payload: error message)
- `ended`: Call ended

## Main Conversation Loop

```typescript
async function _runLoop(): Promise<void> {
  while (_active) {
    try {
      // 1. Capture an utterance via VAD
      const audio = await _captureUtterance();
      if (audio === null || !_active) break;

      const config = getConfig();
      const durationSec = audio.length / config.SAMPLE_RATE;

      if (durationSec < MIN_SPEECH_DURATION) {
        continue;  // Too short, skip
      }

      // 2. Transcribe
      _setStatus('thinking');
      const text = await transcribe(audio);

      if (!text || text.trim().length < 2) {
        _setStatus('listening');
        continue;
      }

      const trimmed = text.trim();
      _emitter.emit('userSaid', trimmed);

      // 3. Run inference
      const response = await _runInference(trimmed);

      if (!response || !_active) {
        _setStatus('listening');
        continue;
      }

      _emitter.emit('agentSaid', response);

      // 4. Speak the response
      _setStatus('speaking');
      await _speak(response);

      // 5. Resume listening
      _setStatus('listening');

    } catch (err) {
      _emitter.emit('error', String(err));
      if (_active) {
        _setStatus('listening');
      }
    }
  }

  _cleanup();
}
```

**Loop phases:**
1. **Capture:** Wait for complete utterance via VAD
2. **Transcribe:** Convert speech to text via whisper.cpp
3. **Infer:** Run Claude Code inference
4. **Speak:** Synthesize and play response via TTS
5. **Resume:** Return to listening state

**Error handling:** Errors are emitted as events, loop continues if still active.

## Utterance Capture (Energy-Based VAD)

### _captureUtterance

```typescript
function _captureUtterance(): Promise<Float32Array | null> {
  _chunks = [];
  _speechStarted = false;
  _silentChunks = 0;
  _utteranceReady = false;

  return new Promise<Float32Array | null>((resolve) => {
    _utteranceResolve = resolve;

    // Safety timeout
    const timeoutMs = MAX_UTTERANCE_SEC * 1000 + 500;
    const timer = setTimeout(() => {
      _finaliseUtterance();
    }, timeoutMs);

    const originalResolve = _utteranceResolve;
    _utteranceResolve = (audio) => {
      clearTimeout(timer);
      originalResolve(audio);
    };
  });
}
```

**Purpose:** Wait for a complete utterance and return concatenated audio.

**Safety timeout:** Caps utterance at 30.5 seconds to prevent runaway.

### _ingestChunk

```typescript
function _ingestChunk(chunk: Float32Array): void {
  if (!_utteranceResolve || _utteranceReady) return;

  if (_muted) {
    _silentChunks++;
    return;
  }

  // Compute RMS energy
  let sum = 0;
  for (let i = 0; i < chunk.length; i++) {
    sum += chunk[i] * chunk[i];
  }
  const rms = Math.sqrt(sum / chunk.length);

  const config = getConfig();
  const silenceChunksNeeded = Math.ceil(
    (SILENCE_DURATION * config.SAMPLE_RATE) / CHUNK_SAMPLES,
  );
  const maxChunks = Math.ceil(
    (MAX_UTTERANCE_SEC * config.SAMPLE_RATE) / CHUNK_SAMPLES,
  );

  if (rms > ENERGY_THRESHOLD) {
    // Speech detected
    _speechStarted = true;
    _silentChunks = 0;
    _chunks.push(chunk);
  } else if (_speechStarted) {
    // Post-speech silence
    _silentChunks++;
    _chunks.push(chunk);  // Keep trailing audio
    if (_silentChunks >= silenceChunksNeeded) {
      _finaliseUtterance();
      return;
    }
  }
  // else: waiting for speech to start - discard ambient noise

  // Safety cap
  if (_chunks.length >= maxChunks) {
    _finaliseUtterance();
  }
}
```

**VAD Logic:**

| State | RMS > threshold | Action |
|-------|-----------------|--------|
| Waiting for speech | No | Discard chunk (ambient noise) |
| Waiting for speech | Yes | Start recording, set `_speechStarted = true` |
| Recording | Yes | Continue recording, reset silence counter |
| Recording | No | Increment silence counter, keep chunk |
| Recording | No + silence reached | Finalize utterance |

**Why keep trailing audio:** Natural speech often has quiet sounds at the end (trailing off, soft consonants). Keeping trailing audio ensures complete utterances.

### _finaliseUtterance

```typescript
function _finaliseUtterance(): void {
  if (!_utteranceResolve) return;

  const resolve = _utteranceResolve;
  _utteranceResolve = null;
  _utteranceReady = true;

  if (_chunks.length === 0) {
    resolve(null);
    return;
  }

  const totalLength = _chunks.reduce((acc, c) => acc + c.length, 0);
  const audio = new Float32Array(totalLength);
  let offset = 0;
  for (const c of _chunks) {
    audio.set(c, offset);
    offset += c.length;
  }
  _chunks = [];

  resolve(audio);
}
```

**Purpose:** Concatenate captured chunks and resolve the utterance promise.

## Inference Integration

```typescript
function _runInference(text: string): Promise<string | null> {
  return new Promise<string | null>((resolve) => {
    if (!_systemPrompt) {
      resolve(null);
      return;
    }

    const emitter = streamInference(text, _systemPrompt, _cliSessionId);
    let fullText = '';

    emitter.on('event', (evt: InferenceEvent) => {
      switch (evt.type) {
        case 'TextDelta':
          _getWindow?.()?.webContents.send('inference:textDelta', evt.text);
          break;
        case 'SentenceReady':
          _getWindow?.()?.webContents.send('inference:sentenceReady', evt.sentence, '');
          break;
        case 'ToolUse':
          _getWindow?.()?.webContents.send('inference:toolUse', evt.name);
          break;
        case 'Compacting':
          _getWindow?.()?.webContents.send('inference:compacting');
          break;
        case 'StreamDone':
          fullText = evt.fullText;
          if (evt.sessionId) {
            _cliSessionId = evt.sessionId;
            _setCliSessionIdExternal?.(evt.sessionId);
          }
          _getWindow?.()?.webContents.send('inference:done', fullText);
          resolve(fullText || null);
          break;
        case 'StreamError':
          _emitter.emit('error', `Inference error: ${evt.message}`);
          _getWindow?.()?.webContents.send('inference:error', evt.message);
          resolve(null);
          break;
      }
    });
  });
}
```

**Features:**
- Forwards inference events to renderer for live display
- Updates CLI session ID when rotated by inference
- Resolves with full response text

## TTS Playback

```typescript
async function _speak(text: string): Promise<void> {
  try {
    const audioPath = await synthesise(text);
    if (audioPath && _active) {
      await playAudio(audioPath);
    }
  } catch (err) {
    _emitter.emit('error', `TTS error: ${err}`);
  }
}
```

**Purpose:** Synthesize and play agent response. Uses inline playback (not queued) for voice call mode.

## IPC Registration

```typescript
export function registerCallHandlers(
  getWindow: () => BrowserWindow | null,
  getSystemPrompt?: () => string | null,
  getCliSessionId?: () => string | null,
  setCliSessionId?: (id: string) => void,
): void {
  _setCliSessionIdExternal = setCliSessionId || null;

  // Receive PCM chunks from renderer during a call
  ipcMain.on('call:chunk', (_event, buffer: ArrayBuffer) => {
    if (!_active) return;
    _ingestChunk(new Float32Array(buffer));
  });

  ipcMain.handle('call:start', (_event, systemPrompt, cliSessionId) => {
    const prompt = systemPrompt || getSystemPrompt?.() || null;
    const sessionId = cliSessionId || getCliSessionId?.() || null;
    if (!prompt) {
      log.warn('cannot start call - no system prompt');
      return;
    }
    startCall(prompt, sessionId, getWindow);
  });

  ipcMain.handle('call:stop', () => { stopCall(); });
  ipcMain.handle('call:status', () => {
    return { active: _active, status: _status, muted: _muted };
  });
  ipcMain.handle('call:setMuted', (_event, muted: boolean) => {
    setMuted(muted);
  });
}
```

**IPC Channels:**
- `call:chunk` (send): Audio chunks from renderer
- `call:start` (invoke): Start voice call
- `call:stop` (invoke): Stop voice call
- `call:status` (invoke): Get call status
- `call:setMuted` (invoke): Mute/unmute mic

## Status Transitions

```
idle ──startCall──▶ listening ──speech detected──▶ thinking
                       ▲                            │
                       │                            │
                       │                    transcription done
                       │                            │
                       │                            ▼
                       │                       listening ──valid text──▶ thinking
                       │                            │
                       │                            ▼
                       │                       (skip - too short)
                       │
                       │                            ▼
                       │                       inference done ──▶ speaking
                       │                                            │
                       │                                            │
                       └────────────────────────────────────────────┘
                                                        TTS done
```

## Cleanup

```typescript
function _cleanup(): void {
  _active = false;
  _chunks = [];
  _speechStarted = false;
  _silentChunks = 0;
  _utteranceResolve = null;
  _setStatus('idle');
  _emitter.emit('ended');
}
```

**Purpose:** Reset all state and emit ended event.

## Exported API Summary

| Function | Purpose |
|----------|---------|
| `startCall(systemPrompt, cliSessionId, getWindow)` | Start hands-free voice call |
| `stopCall()` | Stop voice call |
| `isInCall()` | Check if call is active |
| `isMuted()` | Check mic mute state |
| `setMuted(muted)` | Mute/unmute mic |
| `getCallStatus()` | Get current status |
| `getCallCliSessionId()` | Get CLI session ID |
| `onCallEvent(event, listener)` | Subscribe to events |
| `offCallEvent(event, listener)` | Unsubscribe from events |
| `registerCallHandlers(...)` | Register IPC handlers |

## See Also

- `src/main/tts.ts` - TTS synthesis and playback
- `src/main/stt.ts` - Speech transcription
- `src/main/inference.ts` - Claude Code inference streaming
- `src/main/voice-call.ts` - ElevenLabs Conversational AI integration

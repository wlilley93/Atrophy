/**
 * Voice call - hands-free continuous conversation loop.
 * Port of voice/call.py.
 *
 * Captures audio from the mic (via renderer IPC chunks), detects speech
 * via energy-based VAD, transcribes with whisper, runs inference, speaks
 * the response via TTS. Repeats until stopped.
 *
 * The renderer keeps sending PCM chunks while a call is active. This module
 * runs the listen-transcribe-infer-speak loop entirely in the main process.
 */

import { EventEmitter } from 'events';
import { BrowserWindow, ipcMain } from 'electron';
import { transcribe } from './stt';
import { synthesise, playAudio } from './tts';
import { streamInference, InferenceEvent } from './inference';
import { getConfig } from './config';
import { createLogger } from './logger';

const log = createLogger('call');

// ---------------------------------------------------------------------------
// Audio capture parameters
// ---------------------------------------------------------------------------

const ENERGY_THRESHOLD = 0.015;       // RMS energy to count as speech
const SILENCE_DURATION = 1.5;         // Seconds of silence to end an utterance
const MIN_SPEECH_DURATION = 0.5;      // Minimum seconds of speech to process
const CHUNK_SAMPLES = 1600;           // 100ms chunks at 16kHz
const MAX_UTTERANCE_SEC = 30;         // Safety cap on utterance length

// ---------------------------------------------------------------------------
// Call state
// ---------------------------------------------------------------------------

export type CallStatus = 'idle' | 'listening' | 'thinking' | 'speaking';

const _emitter = new EventEmitter();

let _active = false;
let _muted = false;
let _status: CallStatus = 'idle';
let _cliSessionId: string | null = null;
let _systemPrompt: string | null = null;
let _getWindow: (() => BrowserWindow | null) | null = null;

// External callback to propagate CLI session ID changes
let _setCliSessionIdExternal: ((id: string) => void) | null = null;

// Audio chunk accumulation for VAD
let _chunks: Float32Array[] = [];
let _speechStarted = false;
let _silentChunks = 0;
let _utteranceReady = false;
let _utteranceResolve: ((audio: Float32Array | null) => void) | null = null;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Start a hands-free voice call. The renderer must be sending audio chunks
 * via the 'call:chunk' IPC channel. The call loops until stopCall() is
 * invoked or the window closes.
 */
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

/** Stop the current voice call. */
export function stopCall(): void {
  _active = false;
  // Unblock any pending utterance capture
  if (_utteranceResolve) {
    _utteranceResolve(null);
    _utteranceResolve = null;
  }
}

/** Whether a call is currently active. */
export function isInCall(): boolean {
  return _active;
}

/** Whether the mic is muted (still listening but not processing). */
export function isMuted(): boolean {
  return _muted;
}

/** Mute/unmute the mic during a call. */
export function setMuted(muted: boolean): void {
  _muted = muted;
}

/** Current call status. */
export function getCallStatus(): CallStatus {
  return _status;
}

/** The CLI session ID (may update during the call). */
export function getCallCliSessionId(): string | null {
  return _cliSessionId;
}

/** Subscribe to call events: status, userSaid, agentSaid, error, ended. */
export function onCallEvent(
  event: 'status' | 'userSaid' | 'agentSaid' | 'error' | 'ended',
  listener: (...args: unknown[]) => void,
): void {
  _emitter.on(event, listener);
}

/** Remove a call event listener. */
export function offCallEvent(
  event: 'status' | 'userSaid' | 'agentSaid' | 'error' | 'ended',
  listener: (...args: unknown[]) => void,
): void {
  _emitter.off(event, listener);
}

// ---------------------------------------------------------------------------
// IPC registration - call this once at startup
// ---------------------------------------------------------------------------

/**
 * Register IPC handlers for the call module.
 *
 * @param getWindow - returns the main BrowserWindow
 * @param getSystemPrompt - returns the current system prompt (loaded lazily by main)
 * @param getCliSessionId - returns the current CLI session ID
 * @param setCliSessionId - updates the CLI session ID when inference rotates it
 */
export function registerCallHandlers(
  getWindow: () => BrowserWindow | null,
  getSystemPrompt?: () => string | null,
  getCliSessionId?: () => string | null,
  setCliSessionId?: (id: string) => void,
): void {
  // Store the session ID setter so the loop can propagate new IDs
  _setCliSessionIdExternal = setCliSessionId || null;

  // Receive PCM chunks from renderer during a call
  ipcMain.on('call:chunk', (_event, buffer: ArrayBuffer) => {
    if (!_active) return;
    _ingestChunk(new Float32Array(buffer));
  });

  ipcMain.handle('call:start', (_event, systemPrompt: string | null, cliSessionId: string | null) => {
    // Use provided values or fall back to main process state
    const prompt = systemPrompt || getSystemPrompt?.() || null;
    const sessionId = cliSessionId || getCliSessionId?.() || null;

    if (!prompt) {
      log.warn('cannot start call - no system prompt available');
      return;
    }

    startCall(prompt, sessionId, getWindow);
  });

  ipcMain.handle('call:stop', () => {
    stopCall();
  });

  ipcMain.handle('call:status', () => {
    return { active: _active, status: _status, muted: _muted };
  });

  ipcMain.handle('call:setMuted', (_event, muted: boolean) => {
    setMuted(muted);
  });
}

// ---------------------------------------------------------------------------
// Main conversation loop
// ---------------------------------------------------------------------------

async function _runLoop(): Promise<void> {
  while (_active) {
    try {
      // 1. Capture an utterance via VAD
      const audio = await _captureUtterance();
      if (audio === null || !_active) break;

      const config = getConfig();
      const durationSec = audio.length / config.SAMPLE_RATE;

      if (durationSec < MIN_SPEECH_DURATION) {
        continue;
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

// ---------------------------------------------------------------------------
// Utterance capture (energy-based VAD)
// ---------------------------------------------------------------------------

/**
 * Wait for a complete utterance. Returns the concatenated audio or null if
 * the call was stopped. Audio chunks arrive asynchronously via _ingestChunk().
 */
function _captureUtterance(): Promise<Float32Array | null> {
  _chunks = [];
  _speechStarted = false;
  _silentChunks = 0;
  _utteranceReady = false;

  return new Promise<Float32Array | null>((resolve) => {
    _utteranceResolve = resolve;

    // Safety timeout - cap utterance at MAX_UTTERANCE_SEC
    const config = getConfig();
    const timeoutMs = MAX_UTTERANCE_SEC * 1000 + 500; // small buffer
    const timer = setTimeout(() => {
      if (_utteranceResolve === resolve) {
        _finaliseUtterance();
      }
    }, timeoutMs);

    // Store the timer cleanup on the resolve wrapper
    const originalResolve = _utteranceResolve;
    _utteranceResolve = (audio) => {
      clearTimeout(timer);
      originalResolve(audio);
    };
  });
}

/** Process an incoming audio chunk for VAD. */
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
    _speechStarted = true;
    _silentChunks = 0;
    _chunks.push(chunk);
  } else if (_speechStarted) {
    _silentChunks++;
    _chunks.push(chunk); // Keep trailing audio for natural cutoff
    if (_silentChunks >= silenceChunksNeeded) {
      _finaliseUtterance();
      return;
    }
  }
  // else: still waiting for speech to start - discard ambient noise

  // Safety cap
  if (_chunks.length >= maxChunks) {
    _finaliseUtterance();
  }
}

/** Concatenate captured chunks and resolve the utterance promise. */
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

// ---------------------------------------------------------------------------
// Inference (streaming, wait for full response)
// ---------------------------------------------------------------------------

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
          // Forward deltas to the renderer for live display
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
            // Propagate the updated session ID back to the main process
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

// ---------------------------------------------------------------------------
// TTS playback (synthesise and play inline - not queued)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function _setStatus(status: CallStatus): void {
  _status = status;
  _emitter.emit('status', status);
  _getWindow?.()?.webContents.send('call:statusChanged', status);
}

function _cleanup(): void {
  _active = false;
  _chunks = [];
  _speechStarted = false;
  _silentChunks = 0;
  _utteranceResolve = null;
  _setStatus('idle');
  _emitter.emit('ended');
}

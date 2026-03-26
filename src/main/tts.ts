/**
 * Text-to-speech - three-tier fallback.
 * Port of voice/tts.py.
 *
 * Chain: ElevenLabs streaming -> Fal -> macOS say.
 * ElevenLabs streaming is primary for lowest latency.
 */

import { spawn, ChildProcess } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as crypto from 'crypto';
import { getConfig } from './config';
import { createLogger } from './logger';

const log = createLogger('tts');

// ---------------------------------------------------------------------------
// ElevenLabs credit exhaustion tracking
// ---------------------------------------------------------------------------

/** Cooldown period after detecting credit exhaustion (30 minutes). */
export const COOLDOWN_MS = 30 * 60 * 1000;

let _elevenLabsExhaustedAt: number | null = null;

/** Mark ElevenLabs as credit-exhausted. Starts a cooldown timer. */
export function markElevenLabsExhausted(): void {
  _elevenLabsExhaustedAt = Date.now();
  log.warn(`ElevenLabs credits exhausted - skipping for ${COOLDOWN_MS / 60_000} minutes`);
}

/** Check if ElevenLabs is in credit-exhaustion cooldown. Auto-resets after COOLDOWN_MS. */
export function isElevenLabsExhausted(): boolean {
  if (_elevenLabsExhaustedAt === null) return false;
  if (Date.now() - _elevenLabsExhaustedAt > COOLDOWN_MS) {
    _elevenLabsExhaustedAt = null;
    return false;
  }
  return true;
}

/** Reset credit exhaustion status (for testing or manual recovery). */
export function resetElevenLabsStatus(): void {
  _elevenLabsExhaustedAt = null;
}

// ---------------------------------------------------------------------------
// Temp file management
// ---------------------------------------------------------------------------

function secureTmp(ext: string): string {
  const name = crypto.randomBytes(12).toString('hex') + ext;
  return path.join(os.tmpdir(), 'atrophy-tts-' + name);
}

// ---------------------------------------------------------------------------
// Prosody system
// ---------------------------------------------------------------------------

const PROSODY_RE = /\[([^\]]+)\]/g;
const CODE_BLOCK_RE = /```[\s\S]*?```/g;
const INLINE_CODE_RE = /`[^`]+`/g;

// tag -> [stability_delta, similarity_delta, style_delta]
const PROSODY_MAP: Record<string, [number, number, number]> = {
  'whispers': [0.2, 0.0, -0.2],
  'barely audible': [0.2, 0.0, -0.2],
  'quietly': [0.15, 0.0, -0.15],
  'hushed': [0.2, 0.0, -0.2],
  'softer': [0.1, 0.0, -0.1],
  'lower': [0.1, 0.0, -0.1],
  'warmly': [0.0, 0.1, 0.2],
  'tenderly': [0.05, 0.1, 0.2],
  'gently': [0.05, 0.1, 0.15],
  'firm': [-0.1, 0.0, 0.3],
  'frustrated': [-0.1, 0.0, 0.3],
  'excited': [-0.15, 0.0, 0.1],
  'quickly': [-0.15, 0.0, 0.0],
  'faster now': [-0.15, 0.0, 0.0],
  'wry': [0.0, 0.0, 0.15],
  'dry': [0.1, 0.0, -0.1],
  'sardonic': [0.0, 0.0, 0.2],
  'raw': [-0.1, 0.0, 0.25],
  'vulnerable': [0.0, 0.1, 0.15],
  'heavy': [0.1, 0.0, 0.1],
  'slowly': [0.15, 0.0, 0.0],
  'uncertain': [0.0, 0.0, 0.1],
  'hesitant': [0.05, 0.0, 0.05],
  'nervous': [-0.1, 0.0, 0.15],
  'reluctant': [0.05, 0.0, 0.1],
  'tired': [0.15, 0.0, -0.1],
  'sorrowful': [0.1, 0.1, 0.15],
  'grieving': [0.1, 0.1, 0.2],
  'resigned': [0.15, 0.0, -0.1],
  'haunted': [0.05, 0.05, 0.15],
  'melancholic': [0.1, 0.1, 0.1],
  'nostalgic': [0.05, 0.1, 0.15],
  'voice breaking': [-0.15, 0.0, 0.3],
  'laughs softly': [0.0, 0.0, 0.2],
  'laughs bitterly': [-0.05, 0.0, 0.25],
  'smirks': [0.0, 0.0, 0.15],
  'emphasis': [0.0, 0.0, 0.0],
};

const BREATH_TAGS: Record<string, string> = {
  'breath': '...',
  'inhales slowly': '... ...',
  'exhales': '...',
  'sighs': '...',
  'sighs quietly': '...',
  'clears throat': '...',
  'pause': '. . .',
  'long pause': '. . . . .',
  'trailing off': '...',
  'gulps': '...',
};

interface ProsodyResult {
  text: string;
  overrides: {
    stability?: number;
    similarity_boost?: number;
    style?: number;
  };
}

function processProsody(text: string): ProsodyResult {
  let stabilityD = 0;
  let similarityD = 0;
  let styleD = 0;

  const cleaned = text.replace(PROSODY_RE, (_match, tag: string) => {
    const t = tag.toLowerCase().trim();

    // Breath/pause -> text replacement
    if (t in BREATH_TAGS) return BREATH_TAGS[t];

    // Prosody -> voice settings
    if (t in PROSODY_MAP) {
      const [sd, simD, styD] = PROSODY_MAP[t];
      stabilityD += sd;
      similarityD += simD;
      styleD += styD;
      return '';
    }

    // Unknown tag -> strip
    return '';
  }).replace(/  +/g, ' ').trim();

  // Strip text that is only punctuation/whitespace
  const stripped = cleaned.replace(/[\s.\-,;:!?\u2026]+/g, '');
  const finalText = stripped ? cleaned : '';

  const overrides: ProsodyResult['overrides'] = {};
  if (stabilityD !== 0) overrides.stability = stabilityD;
  if (similarityD !== 0) overrides.similarity_boost = similarityD;
  if (styleD !== 0) overrides.style = styleD;

  return { text: finalText, overrides };
}

// ---------------------------------------------------------------------------
// ElevenLabs streaming (primary)
// ---------------------------------------------------------------------------

async function synthesiseElevenLabsStream(text: string): Promise<string> {
  const config = getConfig();
  const { text: cleanedText, overrides } = processProsody(text);

  if (!cleanedText || !cleanedText.trim()) {
    throw new Error('Empty text after prosody stripping');
  }

  // Clamp overrides to +/-0.15
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
  const stabD = clamp(overrides.stability || 0, -0.15, 0.15);
  const simD = clamp(overrides.similarity_boost || 0, -0.15, 0.15);
  const styD = clamp(overrides.style || 0, -0.15, 0.15);

  const stab = clamp(config.ELEVENLABS_STABILITY + stabD, 0, 1);
  const sim = clamp(config.ELEVENLABS_SIMILARITY + simD, 0, 1);
  const sty = clamp(config.ELEVENLABS_STYLE + styD, 0, 1);

  const url =
    `https://api.elevenlabs.io/v1/text-to-speech` +
    `/${config.ELEVENLABS_VOICE_ID}/stream` +
    `?output_format=mp3_44100_128`;

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'xi-api-key': config.ELEVENLABS_API_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      text: cleanedText,
      model_id: config.ELEVENLABS_MODEL,
      voice_settings: {
        stability: stab,
        similarity_boost: sim,
        style: sty,
      },
    }),
    signal: AbortSignal.timeout(30_000),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`ElevenLabs ${response.status}: ${body.slice(0, 300)}`);
  }

  const tmpPath = secureTmp('.mp3');

  if (!response.body) {
    // Fallback: buffer the whole response if no streaming body
    const buf = Buffer.from(await response.arrayBuffer());
    fs.writeFileSync(tmpPath, buf, { mode: 0o600 });
    return tmpPath;
  }

  // Stream chunks to disk as they arrive - avoids buffering the entire
  // response in memory and reduces time-to-first-byte latency.
  const fileHandle = fs.createWriteStream(tmpPath);
  // Catch stream errors early - an unhandled 'error' event on a WriteStream
  // crashes the process, and a missing reject path hangs the TTS pipeline.
  let streamError: Error | null = null;
  fileHandle.on('error', (err) => { streamError = err; });
  try {
    const reader = response.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (streamError) throw streamError;
      fileHandle.write(Buffer.from(value));
    }
    fileHandle.end();
    await new Promise<void>((resolve, reject) => {
      fileHandle.on('finish', resolve);
      fileHandle.on('error', reject);
    });
  } catch (err) {
    fileHandle.destroy();
    try { fs.unlinkSync(tmpPath); } catch { /* cleanup best-effort */ }
    throw streamError || err;
  }

  return tmpPath;
}

// ---------------------------------------------------------------------------
// Fal TTS (fallback - fal.ai hosted ElevenLabs v3)
// ---------------------------------------------------------------------------

async function synthesiseFal(text: string): Promise<string> {
  const config = getConfig();
  const { text: cleanedText } = processProsody(text);

  if (!cleanedText || !cleanedText.trim()) {
    throw new Error('Empty text after prosody stripping');
  }

  // fal.ai REST API - submit and poll for result
  const submitUrl = `https://queue.fal.run/${config.FAL_TTS_ENDPOINT}`;

  const submitResponse = await fetch(submitUrl, {
    method: 'POST',
    headers: {
      Authorization: `Key ${process.env.FAL_KEY || ''}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      text: cleanedText,
      voice: config.FAL_VOICE_ID,
      stability: config.ELEVENLABS_STABILITY,
    }),
  });

  if (!submitResponse.ok) {
    const body = await submitResponse.text();
    throw new Error(`Fal submit ${submitResponse.status}: ${body.slice(0, 300)}`);
  }

  const submitResult = (await submitResponse.json()) as {
    request_id?: string;
    audio?: { url: string };
  };

  // If the response came back synchronously (small queue), use it directly
  let audioUrl: string | undefined;

  if (submitResult.audio?.url) {
    audioUrl = submitResult.audio.url;
  } else if (submitResult.request_id) {
    // Poll for result
    const resultUrl = `https://queue.fal.run/${config.FAL_TTS_ENDPOINT}/requests/${submitResult.request_id}`;
    const maxAttempts = 30;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      const pollResponse = await fetch(resultUrl, {
        headers: {
          Authorization: `Key ${process.env.FAL_KEY || ''}`,
        },
      });
      if (!pollResponse.ok) continue;
      const pollResult = (await pollResponse.json()) as {
        status?: string;
        audio?: { url: string };
      };
      if (pollResult.audio?.url) {
        audioUrl = pollResult.audio.url;
        break;
      }
      if (pollResult.status === 'FAILED') {
        throw new Error('Fal TTS request failed');
      }
    }
    if (!audioUrl) {
      throw new Error('Fal TTS request timed out');
    }
  } else {
    throw new Error('Fal returned unexpected response shape');
  }

  // Download the audio file
  const audioResponse = await fetch(audioUrl, { signal: AbortSignal.timeout(30_000) });
  if (!audioResponse.ok) {
    throw new Error(`Fal audio download failed: ${audioResponse.status}`);
  }

  const tmpPath = secureTmp('.mp3');
  const buffer = Buffer.from(await audioResponse.arrayBuffer());
  fs.writeFileSync(tmpPath, buffer);
  return tmpPath;
}

// ---------------------------------------------------------------------------
// macOS say (last resort)
// ---------------------------------------------------------------------------

function synthesiseMacOS(text: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const audioPath = secureTmp('.aiff');
    const clean = text.replace(/\[[\w\s]+\]/g, '').trim();

    const proc = spawn('say', ['-v', 'Samantha', '-r', '175', '-o', audioPath, clean], {
      stdio: ['ignore', 'ignore', 'ignore'],
    });

    const cleanupFile = () => { try { fs.unlinkSync(audioPath); } catch { /* already gone */ } };

    const timeout = setTimeout(() => {
      try { proc.kill(); } catch { /* already dead */ }
      cleanupFile();
      reject(new Error('macOS say timed out (30s)'));
    }, 30_000);

    proc.on('close', (code) => {
      clearTimeout(timeout);
      if (code === 0) resolve(audioPath);
      else { cleanupFile(); reject(new Error(`say exited with code ${code}`)); }
    });
    proc.on('error', (err) => {
      clearTimeout(timeout);
      cleanupFile();
      reject(err);
    });
  });
}

// ---------------------------------------------------------------------------
// Silent audio file - returned when text is empty/too short.
// Matches Python behavior: callers always get a valid file path.
// ---------------------------------------------------------------------------

// Minimal WAV: 44-byte header, zero data samples, 16kHz mono 16-bit PCM.
const SILENT_WAV_HEADER = Buffer.from([
  0x52, 0x49, 0x46, 0x46, // "RIFF"
  0x24, 0x00, 0x00, 0x00, // file size - 8 (36 bytes remaining)
  0x57, 0x41, 0x56, 0x45, // "WAVE"
  0x66, 0x6d, 0x74, 0x20, // "fmt "
  0x10, 0x00, 0x00, 0x00, // subchunk1 size (16)
  0x01, 0x00,             // PCM format
  0x01, 0x00,             // 1 channel
  0x80, 0x3e, 0x00, 0x00, // 16000 Hz sample rate
  0x00, 0x7d, 0x00, 0x00, // byte rate (32000)
  0x02, 0x00,             // block align
  0x10, 0x00,             // 16 bits per sample
  0x64, 0x61, 0x74, 0x61, // "data"
  0x00, 0x00, 0x00, 0x00, // data size (0 - silence)
]);

function writeSilentFile(): string {
  const tmpPath = secureTmp('.wav');
  fs.writeFileSync(tmpPath, SILENT_WAV_HEADER);
  return tmpPath;
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Concurrency limiter - ElevenLabs allows max 3 concurrent requests.
// We cap at 2 to leave headroom for caching/opening line synthesis.
// ---------------------------------------------------------------------------

const MAX_CONCURRENT_TTS = 2;
let _activeTtsCount = 0;
const _ttsWaiters: (() => void)[] = [];

async function acquireTtsSlot(): Promise<void> {
  if (_activeTtsCount < MAX_CONCURRENT_TTS) {
    _activeTtsCount++;
    return;
  }
  // Slot is transferred directly by releaseTtsSlot - count stays the same
  await new Promise<void>((resolve) => _ttsWaiters.push(resolve));
}

function releaseTtsSlot(): void {
  const next = _ttsWaiters.shift();
  if (next) {
    // Transfer slot directly to waiter - count unchanged
    next();
  } else {
    _activeTtsCount--;
  }
}

// ---------------------------------------------------------------------------
// Main interface
// ---------------------------------------------------------------------------

export async function synthesise(text: string): Promise<string | null> {
  // Strip code blocks
  text = text.replace(CODE_BLOCK_RE, '');
  text = text.replace(INLINE_CODE_RE, '');

  // Check for empty/too-short text - return a silent file so callers
  // always receive a valid path (matches Python behavior)
  const { text: cleaned } = processProsody(text);
  if (!cleaned || cleaned.trim().length < 8) {
    return writeSilentFile();
  }

  const config = getConfig();

  // Primary: ElevenLabs streaming (with concurrency limit)
  if (!config.ELEVENLABS_API_KEY) log.debug('ElevenLabs skipped: no API key');
  else if (!config.ELEVENLABS_VOICE_ID) log.debug('ElevenLabs skipped: no voice ID');
  else if (isElevenLabsExhausted()) log.debug('ElevenLabs skipped: credits exhausted (cooldown active)');
  if (config.ELEVENLABS_API_KEY && config.ELEVENLABS_VOICE_ID && !isElevenLabsExhausted()) {
    await acquireTtsSlot();
    try {
      return await synthesiseElevenLabsStream(text);
    } catch (e) {
      // Only mark exhausted for genuine credit/auth issues, not transient rate limits
      const errMsg = String(e);
      if (/ElevenLabs (401|402)/.test(errMsg)) {
        markElevenLabsExhausted();
      }
      log.warn(`ElevenLabs failed (${e}), trying Fal...`);
    } finally {
      releaseTtsSlot();
    }
  }

  // Fallback: Fal (fal.ai hosted ElevenLabs v3)
  if (config.FAL_VOICE_ID) {
    try {
      return await synthesiseFal(text);
    } catch (e) {
      log.warn(`Fal failed (${e}), trying macOS say...`);
    }
  }

  // Last resort: macOS say
  try {
    return await synthesiseMacOS(text);
  } catch (e) {
    log.warn(`macOS say failed (${e})`);
  }

  log.warn('No voice available - skipping audio');
  return null;
}

// ---------------------------------------------------------------------------
// Synchronous synthesise - for setup wizard and other blocking contexts
// ---------------------------------------------------------------------------

/**
 * Blocking wrapper around synthesise(). Returns a promise that resolves to the
 * audio file path, but is intended for use in contexts where the caller awaits
 * inline (e.g. setup wizard TTS playback between steps).
 *
 * This mirrors Python's synthesise_sync() which ran the async function in a
 * new event loop. In Node/Electron the event loop is always running, so this
 * is simply an alias with the same fallback chain - the caller awaits it
 * synchronously within their flow.
 */
export async function synthesiseSync(text: string): Promise<string | null> {
  return synthesise(text);
}

// ---------------------------------------------------------------------------
// Playback via afplay
// ---------------------------------------------------------------------------

let _activeAfplay: ChildProcess | null = null;

export function playAudio(audioPath: string, rate?: number, cleanupFile = true): Promise<void> {
  // Stop any currently playing audio to prevent overlap
  stopCurrentPlayback();

  return new Promise((resolve, reject) => {
    const config = getConfig();
    const playbackRate = rate || config.TTS_PLAYBACK_RATE;

    const proc = spawn('afplay', ['-r', String(playbackRate), audioPath], {
      stdio: ['ignore', 'ignore', 'ignore'],
    });
    _activeAfplay = proc;

    proc.on('close', (code) => {
      if (_activeAfplay === proc) _activeAfplay = null;
      // Clean up temp file (skip for permanent bundle files)
      if (cleanupFile) {
        try { fs.unlinkSync(audioPath); } catch { /* noop */ }
      }
      if (code !== 0 && code !== null) {
        log.warn(`afplay exited ${code} for ${path.basename(audioPath)}`);
      }
      resolve();
    });
    proc.on('error', (err) => {
      if (_activeAfplay === proc) _activeAfplay = null;
      if (cleanupFile) {
        try { fs.unlinkSync(audioPath); } catch { /* noop */ }
      }
      reject(err);
    });
  });
}

/**
 * Kill the currently playing afplay process (if any).
 * Used by clearAudioQueue to actually stop sound output.
 */
export function stopCurrentPlayback(): void {
  if (_activeAfplay) {
    try { _activeAfplay.kill(); } catch { /* already dead */ }
    _activeAfplay = null;
  }
}

// ---------------------------------------------------------------------------
// Audio playback queue (runs in main process)
// ---------------------------------------------------------------------------

interface QueueItem {
  audioPath: string;
  index: number;
}

let _queue: QueueItem[] = [];
let _playing = false;
let _nextExpectedIndex = 0;
let _waitTimer: ReturnType<typeof setTimeout> | null = null;
let _onStarted: ((index: number) => void) | null = null;
let _onDone: ((index: number) => void) | null = null;
let _onQueueEmpty: (() => void) | null = null;

export function setPlaybackCallbacks(callbacks: {
  onStarted?: (index: number) => void;
  onDone?: (index: number) => void;
  onQueueEmpty?: () => void;
}): void {
  _onStarted = callbacks.onStarted || null;
  _onDone = callbacks.onDone || null;
  _onQueueEmpty = callbacks.onQueueEmpty || null;
}

let _muted = false;

export function setMuted(muted: boolean): void {
  _muted = muted;
  if (muted) clearAudioQueue();
}

export function isMuted(): boolean {
  return _muted;
}

export function enqueueAudio(audioPath: string, index: number): void {
  if (_muted) return;
  _queue.push({ audioPath, index });
  // Keep queue sorted by sentence index so out-of-order TTS results play correctly
  _queue.sort((a, b) => a.index - b.index);
  if (!_playing) {
    processQueue();
  }
}

// Monotonic generation counter - incremented on clearAudioQueue so that
// in-flight synthesise() promises from a previous agent can be discarded.
let _ttsGeneration = 0;

/** Return the current TTS generation. Callers should capture this before
 *  starting synthesis and compare after - if it changed, discard the result. */
export function ttsGeneration(): number { return _ttsGeneration; }

/**
 * Clear all pending audio and stop the currently playing clip.
 */
export function clearAudioQueue(): void {
  _ttsGeneration++;
  // Clean up temp files from pending queue items
  for (const item of _queue) {
    try { fs.unlinkSync(item.audioPath); } catch { /* best-effort cleanup */ }
  }
  _queue = [];
  _nextExpectedIndex = 0;
  _playing = false;
  if (_waitTimer) { clearTimeout(_waitTimer); _waitTimer = null; }
  stopCurrentPlayback();
}

async function processQueue(): Promise<void> {
  if (_playing) return;
  _playing = true;

  // Capture the generation so we can detect if clearAudioQueue was called
  // (which bumps _ttsGeneration), and self-terminate this loop.
  const gen = _ttsGeneration;

  while (_queue.length > 0) {
    if (_ttsGeneration !== gen) break;

    // Wait for the next expected sentence index to avoid out-of-order playback.
    // If sentence 2 arrives before sentence 1, wait up to 3s for sentence 1.
    if (_queue[0].index > _nextExpectedIndex) {
      const arrived = await new Promise<boolean>((resolve) => {
        const check = () => {
          if (_queue.length > 0 && _queue[0].index === _nextExpectedIndex) {
            resolve(true);
          }
        };
        check();
        // Re-check when new items arrive (enqueueAudio calls processQueue which
        // won't re-enter because _playing is true, but we poll briefly)
        // Also check periodically in case enqueue happened between checks
        const interval = setInterval(() => {
          if (_ttsGeneration !== gen) {
            clearInterval(interval);
            resolve(false);
            return;
          }
          if (_queue.length > 0 && _queue[0].index === _nextExpectedIndex) {
            clearInterval(interval);
            if (_waitTimer) { clearTimeout(_waitTimer); _waitTimer = null; }
            resolve(true);
          }
        }, 50);
        _waitTimer = setTimeout(() => {
          _waitTimer = null;
          clearInterval(interval); // Prevent permanent 50ms poll leak
          resolve(false); // Give up waiting, play whatever is next
        }, 3000);
      });
      if (_ttsGeneration !== gen) break;
      if (!arrived && _queue.length === 0) break;
    }

    if (_ttsGeneration !== gen) break;

    const item = _queue.shift()!;
    _nextExpectedIndex = item.index + 1;
    _onStarted?.(item.index);

    try {
      await playAudio(item.audioPath);
    } catch (e) {
      log.error(`Playback error: ${e}`);
    }

    if (_ttsGeneration !== gen) break;

    _onDone?.(item.index);
  }

  // Only clear _playing if this loop still owns the current generation.
  // If clearAudioQueue already reset _playing and a new loop may have
  // started, we must not clobber it.
  if (_ttsGeneration === gen) {
    _playing = false;
    _onQueueEmpty?.();
  }
}

// ---------------------------------------------------------------------------
// Prosody stripping (for display - strip tags from transcript text)
// ---------------------------------------------------------------------------

export function stripProsodyTags(text: string): string {
  return text.replace(PROSODY_RE, '').replace(/  +/g, ' ').trim();
}

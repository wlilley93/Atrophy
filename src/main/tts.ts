/**
 * Text-to-speech - three-tier fallback.
 * Port of voice/tts.py.
 *
 * Chain: ElevenLabs streaming -> Fal -> macOS say.
 * ElevenLabs streaming is primary for lowest latency.
 */

import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as crypto from 'crypto';
import { getConfig } from './config';

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
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`ElevenLabs ${response.status}: ${body.slice(0, 300)}`);
  }

  const tmpPath = secureTmp('.mp3');
  const buffer = Buffer.from(await response.arrayBuffer());
  fs.writeFileSync(tmpPath, buffer);
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

    proc.on('close', (code) => {
      if (code === 0) resolve(audioPath);
      else reject(new Error(`say exited with code ${code}`));
    });
    proc.on('error', reject);
  });
}

// ---------------------------------------------------------------------------
// Main interface
// ---------------------------------------------------------------------------

export async function synthesise(text: string): Promise<string | null> {
  // Strip code blocks
  text = text.replace(CODE_BLOCK_RE, '');
  text = text.replace(INLINE_CODE_RE, '');

  // Check for empty/too-short text
  const { text: cleaned } = processProsody(text);
  if (!cleaned || cleaned.trim().length < 8) {
    return null; // Nothing to say
  }

  const config = getConfig();

  // Primary: ElevenLabs streaming
  if (config.ELEVENLABS_API_KEY && config.ELEVENLABS_VOICE_ID) {
    try {
      return await synthesiseElevenLabsStream(text);
    } catch (e) {
      console.log(`[TTS] ElevenLabs failed (${e}), trying Fal...`);
    }
  }

  // Fallback: Fal (fal.ai hosted ElevenLabs v3)
  if (config.FAL_VOICE_ID) {
    try {
      return await synthesiseFal(text);
    } catch (e) {
      console.log(`[TTS] Fal failed (${e}), trying macOS say...`);
    }
  }

  // Last resort: macOS say
  try {
    return await synthesiseMacOS(text);
  } catch (e) {
    console.log(`[TTS] macOS say failed (${e})`);
  }

  console.log('[TTS] No voice available - skipping audio');
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

export function playAudio(audioPath: string, rate?: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const config = getConfig();
    const playbackRate = rate || config.TTS_PLAYBACK_RATE;

    const proc = spawn('afplay', ['-r', String(playbackRate), audioPath], {
      stdio: ['ignore', 'ignore', 'ignore'],
    });

    proc.on('close', () => {
      // Clean up temp file
      try { fs.unlinkSync(audioPath); } catch { /* noop */ }
      resolve();
    });
    proc.on('error', (err) => {
      try { fs.unlinkSync(audioPath); } catch { /* noop */ }
      reject(err);
    });
  });
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

export function enqueueAudio(audioPath: string, index: number): void {
  _queue.push({ audioPath, index });
  if (!_playing) {
    processQueue();
  }
}

export function clearAudioQueue(): void {
  _queue = [];
}

async function processQueue(): Promise<void> {
  if (_playing) return;
  _playing = true;

  while (_queue.length > 0) {
    const item = _queue.shift()!;
    _onStarted?.(item.index);

    try {
      await playAudio(item.audioPath);
    } catch (e) {
      console.log(`[TTS] Playback error: ${e}`);
    }

    _onDone?.(item.index);
  }

  _playing = false;
  _onQueueEmpty?.();
}

// ---------------------------------------------------------------------------
// Prosody stripping (for display - strip tags from transcript text)
// ---------------------------------------------------------------------------

export function stripProsodyTags(text: string): string {
  return text.replace(PROSODY_RE, '').replace(/  +/g, ' ').trim();
}

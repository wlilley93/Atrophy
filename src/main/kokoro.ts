/**
 * Kokoro-82M TTS - local neural text-to-speech.
 *
 * Replaces Piper in the fallback chain. Kokoro-82M is an 82M parameter
 * StyleTTS2-based model with near-ElevenLabs quality. Runs via
 * onnxruntime-node (same dependency we use for embeddings), so no
 * external binary or pip install is needed.
 *
 * Model and voicepacks are downloaded automatically by
 * @huggingface/transformers on first use, cached under
 * ~/.atrophy/models/ alongside the embedding model.
 *
 * Fallback chain position: ElevenLabs -> Fal -> Kokoro -> macOS say
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as crypto from 'crypto';
import { createLogger } from './logger';
import { getConfig } from './config';

const log = createLogger('kokoro');

// ---------------------------------------------------------------------------
// Model configuration
// ---------------------------------------------------------------------------

const MODEL_ID = 'onnx-community/Kokoro-82M-v1.0-ONNX';

// ---------------------------------------------------------------------------
// Lazy-loaded singleton with failure circuit breaker
// ---------------------------------------------------------------------------

// The kokoro-js package has no types exported from the entry point, so we
// load it via dynamic import and cache the instance loosely typed.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _tts: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _loading: Promise<any> | null = null;
let _disabled = false;
let _failureCount = 0;
let _failureLoggedAt = 0;
const MAX_FAILURES = 3;
const FAILURE_LOG_INTERVAL_MS = 60 * 60 * 1000;

// ---------------------------------------------------------------------------
// Voice catalogue
// ---------------------------------------------------------------------------
//
// Kokoro voice naming: <lang><gender>_<name>
//   af = American female, am = American male
//   bf = British female,  bm = British male
//
// All 28 voices below ship with the model itself (no separate download).
// These are the highest-rated ones by the Kokoro authors:
//   af_heart, af_bella, bm_daniel, bm_fable, bm_george, am_michael
//
// Voice overall grades (from Kokoro docs):
//   af_heart A, af_bella A-, am_fenrir B+, am_michael B+, bm_fable B+,
//   bm_george B+, bf_emma B+, bm_daniel B+
//
// We pick the highest-grade voices per quadrant for defaults.

/**
 * Map an agent name to a default Kokoro voice.
 * Montgomery/defence agents get British males (Daniel/George), Companion
 * gets American females (Heart/Bella), Xan gets American male Michael.
 */
export function getDefaultKokoroVoice(agentName?: string): string {
  const name = (agentName || '').toLowerCase();

  // British male - for Montgomery and defence agents
  if (name.includes('montgomery') || name.includes('defence') || name.includes('british')) {
    return 'bm_george';
  }

  // British female
  if (name.includes('british_female') || name.includes('emma')) {
    return 'bf_emma';
  }

  // American female for Companion, Mirror, female-coded names
  if (name.includes('companion') || name.includes('mirror')
    || name.includes('luna') || name.includes('aria') || name.includes('nova')) {
    return 'af_heart';
  }

  // Default American male
  return 'am_michael';
}

// ---------------------------------------------------------------------------
// Hardware gate
// ---------------------------------------------------------------------------

/**
 * Kokoro-82M is 82 million parameters. At q8 quantization the model file
 * is ~88MB and runtime memory is ~300MB during synthesis. On machines
 * under 8GB RAM we skip Kokoro entirely and drop through to macOS say.
 */
export function isKokoroHardwareCompatible(): boolean {
  const totalGB = os.totalmem() / (1024 * 1024 * 1024);
  if (totalGB < 7.5) return false;
  if (process.arch !== 'arm64' && process.arch !== 'x64') return false;
  return true;
}

// ---------------------------------------------------------------------------
// Load the model
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function loadTTS(): Promise<any> {
  if (_tts) return _tts;
  if (_disabled) {
    const now = Date.now();
    if (now - _failureLoggedAt > FAILURE_LOG_INTERVAL_MS) {
      log.warn(`Kokoro disabled after ${_failureCount} failures - semantic TTS degraded.`);
      _failureLoggedAt = now;
    }
    throw new Error('Kokoro disabled');
  }
  if (_loading) return _loading;

  _loading = (async () => {
    try {
      const config = getConfig();
      log.info(`Loading Kokoro TTS (${MODEL_ID})...`);

      // Point transformers.js cache at our models dir so Kokoro downloads
      // land alongside the embedding model and persist between launches.
      // Env vars set before the dynamic import so kokoro-js's internal
      // @huggingface/transformers picks them up during its first load.
      // (HF_HOME is the standard location; TRANSFORMERS_CACHE is legacy.)
      process.env.HF_HOME = config.MODELS_DIR;
      process.env.TRANSFORMERS_CACHE = config.MODELS_DIR;

      const { KokoroTTS } = await import('kokoro-js');
      _tts = await KokoroTTS.from_pretrained(MODEL_ID, {
        dtype: 'q8',
        device: 'cpu',
      });

      log.info('Kokoro TTS loaded');
      _failureCount = 0;
      return _tts;
    } catch (err) {
      _loading = null;
      _failureCount++;
      if (_failureCount >= MAX_FAILURES) {
        _disabled = true;
        _failureLoggedAt = Date.now();
        log.error(`Kokoro failed to load ${_failureCount} times - disabling. Last error:`, err);
      }
      throw err;
    }
  })();

  _tts = await _loading;
  _loading = null;
  return _tts;
}

// ---------------------------------------------------------------------------
// Availability check
// ---------------------------------------------------------------------------

/** Check if Kokoro is available (hardware OK + not disabled by failures). */
export function isKokoroAvailable(): boolean {
  return isKokoroHardwareCompatible() && !_disabled;
}

// ---------------------------------------------------------------------------
// Fire-and-forget boot warm-up
// ---------------------------------------------------------------------------

/**
 * Trigger Kokoro model load during boot so the first real synthesis
 * request doesn't have to wait for the ~88MB model to download.
 * Safe to call multiple times - subsequent calls are no-ops while running
 * or after the model is cached.
 */
export async function ensureKokoroReady(): Promise<void> {
  if (!isKokoroHardwareCompatible()) {
    const totalGB = (os.totalmem() / (1024 * 1024 * 1024)).toFixed(1);
    log.info(`Kokoro skipped: hardware below minimum (${totalGB}GB RAM, ${process.arch})`);
    return;
  }
  try {
    await loadTTS();
    log.info('Kokoro ready for synthesis');
  } catch (err) {
    log.warn(`Kokoro warm-up failed (non-fatal): ${err}`);
  }
}

// ---------------------------------------------------------------------------
// Synthesis
// ---------------------------------------------------------------------------

/**
 * Synthesise text to a WAV file using Kokoro.
 * @param text - Text to speak
 * @param voiceName - Voice basename (e.g. "bm_george"). Falls back to agent default.
 * @param agentName - Current agent name (for default voice selection)
 * @returns Path to the generated WAV file in os.tmpdir()
 */
export async function synthesiseKokoro(
  text: string,
  voiceName?: string,
  agentName?: string,
): Promise<string> {
  const tts = await loadTTS();
  const voice = voiceName || getDefaultKokoroVoice(agentName);

  // Generate audio (returns a RawAudio object with .save())
  const audio = await tts.generate(text, { voice });

  // Write to a unique temp WAV file
  const tmpName = 'atrophy-kokoro-' + crypto.randomBytes(12).toString('hex') + '.wav';
  const audioPath = path.join(os.tmpdir(), tmpName);
  await audio.save(audioPath);

  if (!fs.existsSync(audioPath) || fs.statSync(audioPath).size < 100) {
    try { fs.unlinkSync(audioPath); } catch { /* cleanup */ }
    throw new Error('Kokoro produced empty audio');
  }

  return audioPath;
}

/**
 * Piper TTS - local neural text-to-speech.
 *
 * Sits between cloud backends (ElevenLabs, Fal) and macOS `say` in the
 * fallback chain. Each agent can have its own assigned Piper voice model.
 *
 * Voice models live in ~/.atrophy/models/piper/ as .onnx + .onnx.json pairs.
 * The piper binary is resolved from multiple locations or installed via pip.
 */

import { spawn, execFileSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import * as crypto from 'crypto';
import { createLogger } from './logger';
import { USER_DATA } from './config';

const log = createLogger('piper');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PIPER_MODELS_DIR = path.join(USER_DATA, 'models', 'piper');
const PIPER_BIN_DIR = path.join(USER_DATA, 'bin');

/** Default voice models to download. Each entry is [basename, HuggingFace subpath]. */
const DEFAULT_VOICES: Array<[string, string]> = [
  ['en_GB-alan-medium', 'en/en_GB/alan/medium'],
  ['en_US-amy-medium', 'en/en_US/amy/medium'],
  ['en_US-ryan-medium', 'en/en_US/ryan/medium'],
];

const HF_BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/main';

// ---------------------------------------------------------------------------
// Binary resolution
// ---------------------------------------------------------------------------

let _cachedBinaryPath: string | null = null;
let _cachedBinaryType: 'binary' | 'python' | null = null;

/**
 * Find the piper binary. Checks multiple locations in order:
 * 1. ~/.atrophy/bin/piper
 * 2. /opt/homebrew/bin/piper
 * 3. which piper (system PATH)
 * 4. python3 -m piper (pip-installed)
 */
export function findPiperBinary(): { path: string; type: 'binary' | 'python' } | null {
  if (_cachedBinaryPath) return { path: _cachedBinaryPath, type: _cachedBinaryType! };

  // 1. Local bin
  const localBin = path.join(PIPER_BIN_DIR, 'piper');
  if (fs.existsSync(localBin)) {
    _cachedBinaryPath = localBin;
    _cachedBinaryType = 'binary';
    return { path: localBin, type: 'binary' };
  }

  // 2. Homebrew
  const brewBin = '/opt/homebrew/bin/piper';
  if (fs.existsSync(brewBin)) {
    _cachedBinaryPath = brewBin;
    _cachedBinaryType = 'binary';
    return { path: brewBin, type: 'binary' };
  }

  // 3. System PATH - use execFileSync with 'which' to avoid shell injection
  try {
    const systemBin = execFileSync('/usr/bin/which', ['piper'], {
      encoding: 'utf-8',
      timeout: 5000,
    }).trim();
    if (systemBin && fs.existsSync(systemBin)) {
      _cachedBinaryPath = systemBin;
      _cachedBinaryType = 'binary';
      return { path: systemBin, type: 'binary' };
    }
  } catch { /* not found */ }

  // 4. pip-installed (python3 -m piper)
  try {
    const pythonPath = findPython();
    if (pythonPath) {
      execFileSync(pythonPath, ['-m', 'piper', '--help'], { timeout: 5000 });
      _cachedBinaryPath = pythonPath;
      _cachedBinaryType = 'python';
      return { path: pythonPath, type: 'python' };
    }
  } catch { /* not found */ }

  return null;
}

/** Reset the cached binary path (e.g. after installation). */
export function resetBinaryCache(): void {
  _cachedBinaryPath = null;
  _cachedBinaryType = null;
}

function findPython(): string | null {
  const candidates = [
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    '/usr/bin/python3',
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  // Last resort: check PATH
  try {
    const result = execFileSync('/usr/bin/which', ['python3'], {
      encoding: 'utf-8',
      timeout: 3000,
    }).trim();
    if (result) return result;
  } catch { /* not found */ }
  return null;
}

// ---------------------------------------------------------------------------
// Voice model management
// ---------------------------------------------------------------------------

/** Get the directory where Piper voice models are stored. */
export function getModelsDir(): string {
  return PIPER_MODELS_DIR;
}

/** Check if a specific voice model is downloaded (both .onnx and .onnx.json). */
export function isModelDownloaded(basename: string): boolean {
  const onnxPath = path.join(PIPER_MODELS_DIR, `${basename}.onnx`);
  const jsonPath = path.join(PIPER_MODELS_DIR, `${basename}.onnx.json`);
  return fs.existsSync(onnxPath) && fs.existsSync(jsonPath);
}

/** List all downloaded voice models (basenames without extension). */
export function listDownloadedModels(): string[] {
  if (!fs.existsSync(PIPER_MODELS_DIR)) return [];
  try {
    const files = fs.readdirSync(PIPER_MODELS_DIR);
    const onnxFiles = files.filter(f => f.endsWith('.onnx') && !f.endsWith('.onnx.json'));
    return onnxFiles
      .map(f => f.replace('.onnx', ''))
      .filter(basename => {
        // Only include if the companion .json config also exists
        return files.includes(`${basename}.onnx.json`);
      });
  } catch {
    return [];
  }
}

/** Check if Piper is available (binary found + at least one voice model). */
export function isPiperAvailable(): boolean {
  return findPiperBinary() !== null && listDownloadedModels().length > 0;
}

/**
 * Minimum hardware to run Piper comfortably. Piper uses ~200MB RAM during
 * synthesis and benefits from modern CPU vector instructions. On machines
 * below the floor we skip the install entirely so they drop straight to
 * macOS `say` rather than downloading 100MB of models that won't be used.
 *
 * Minimums:
 *   - 8GB total RAM (M1 Air with 8GB is the smallest supported Apple Silicon)
 *   - arm64 or x64 (no i386 builds exist)
 */
export function isPiperHardwareCompatible(): boolean {
  const totalGB = os.totalmem() / (1024 * 1024 * 1024);
  if (totalGB < 7.5) return false; // 8GB machines report ~7.7GB
  if (process.arch !== 'arm64' && process.arch !== 'x64') return false;
  return true;
}

// ---------------------------------------------------------------------------
// Default voice mapping
// ---------------------------------------------------------------------------

/**
 * Map an agent name to a default Piper voice model basename.
 * British-sounding agents get the British voice, female agents get Amy, etc.
 */
export function getDefaultPiperVoice(agentName?: string): string {
  const name = (agentName || '').toLowerCase();

  // British agents
  if (name.includes('montgomery') || name.includes('defence') || name.includes('british')) {
    return 'en_GB-alan-medium';
  }

  // Female-coded agents
  if (name.includes('companion') || name.includes('amy') || name.includes('mirror')
    || name.includes('luna') || name.includes('aria') || name.includes('nova')) {
    return 'en_US-amy-medium';
  }

  // Default - US male
  return 'en_US-ryan-medium';
}

// ---------------------------------------------------------------------------
// Model downloading
// ---------------------------------------------------------------------------

async function downloadFile(url: string, destPath: string): Promise<void> {
  const response = await fetch(url, { signal: AbortSignal.timeout(120_000) });
  if (!response.ok) {
    throw new Error(`Download failed: ${response.status} ${response.statusText} for ${url}`);
  }
  const buffer = Buffer.from(await response.arrayBuffer());
  fs.writeFileSync(destPath, buffer, { mode: 0o644 });
}

/**
 * Download a single voice model (both .onnx and .onnx.json files).
 * @param basename - e.g. "en_GB-alan-medium"
 * @param hfSubpath - e.g. "en/en_GB/alan/medium"
 */
async function downloadVoiceModel(basename: string, hfSubpath: string): Promise<void> {
  fs.mkdirSync(PIPER_MODELS_DIR, { recursive: true });

  const onnxUrl = `${HF_BASE}/${hfSubpath}/${basename}.onnx`;
  const jsonUrl = `${HF_BASE}/${hfSubpath}/${basename}.onnx.json`;
  const onnxDest = path.join(PIPER_MODELS_DIR, `${basename}.onnx`);
  const jsonDest = path.join(PIPER_MODELS_DIR, `${basename}.onnx.json`);

  if (!fs.existsSync(onnxDest)) {
    log.info(`Downloading Piper voice model: ${basename}.onnx`);
    await downloadFile(onnxUrl, onnxDest);
    log.info(`Downloaded: ${basename}.onnx (${(fs.statSync(onnxDest).size / 1024 / 1024).toFixed(1)} MB)`);
  }

  if (!fs.existsSync(jsonDest)) {
    log.info(`Downloading Piper voice config: ${basename}.onnx.json`);
    await downloadFile(jsonUrl, jsonDest);
    log.info(`Downloaded: ${basename}.onnx.json`);
  }
}

// ---------------------------------------------------------------------------
// pip install piper-tts
// ---------------------------------------------------------------------------

async function tryInstallPiperViaPip(): Promise<boolean> {
  const python = findPython();
  if (!python) {
    log.warn('Cannot install piper-tts: no python3 found');
    return false;
  }

  log.info('Attempting to install piper-tts via pip...');
  try {
    execFileSync(python, ['-m', 'pip', 'install', 'piper-tts'], {
      timeout: 120_000,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    resetBinaryCache();
    const found = findPiperBinary();
    if (found) {
      log.info('piper-tts installed successfully via pip');
      return true;
    }
  } catch (e) {
    log.warn(`Failed to install piper-tts via pip: ${e}`);
  }
  return false;
}

// ---------------------------------------------------------------------------
// Ensure Piper is ready (binary + default models)
// ---------------------------------------------------------------------------

let _ensureRunning = false;

/**
 * Ensure Piper TTS is ready: binary is available, default voice models
 * are downloaded. This is meant to be called fire-and-forget during boot.
 * Safe to call multiple times - subsequent calls are no-ops while running.
 */
export async function ensurePiperReady(): Promise<void> {
  if (_ensureRunning) return;
  _ensureRunning = true;

  try {
    // 0. Hardware gate - skip entirely on low-memory machines. This avoids
    // downloading 100MB of models onto a device where synthesis would be
    // slow enough to fail the 30s timeout anyway.
    if (!isPiperHardwareCompatible()) {
      const totalGB = (os.totalmem() / (1024 * 1024 * 1024)).toFixed(1);
      log.info(`Piper skipped: hardware below minimum (${totalGB}GB RAM, ${process.arch})`);
      return;
    }

    // 1. Check for piper binary
    let binary = findPiperBinary();
    if (!binary) {
      log.info('Piper binary not found - attempting pip install');
      const installed = await tryInstallPiperViaPip();
      if (!installed) {
        log.warn('Piper TTS not available - no binary found and pip install failed');
        return;
      }
      binary = findPiperBinary();
    }

    if (binary) {
      log.info(`Piper binary found: ${binary.path} (${binary.type})`);
    }

    // 2. Download default voice models
    for (const [basename, hfSubpath] of DEFAULT_VOICES) {
      if (!isModelDownloaded(basename)) {
        try {
          await downloadVoiceModel(basename, hfSubpath);
        } catch (e) {
          log.warn(`Failed to download voice model ${basename}: ${e}`);
        }
      }
    }

    const models = listDownloadedModels();
    log.info(`Piper ready: ${models.length} voice model(s) available [${models.join(', ')}]`);
  } catch (e) {
    log.warn(`Piper setup error (non-fatal): ${e}`);
  } finally {
    _ensureRunning = false;
  }
}

// ---------------------------------------------------------------------------
// Synthesis
// ---------------------------------------------------------------------------

/**
 * Synthesise text to a WAV file using Piper.
 * @param text - Text to speak
 * @param voiceModel - Model basename (e.g. "en_GB-alan-medium"). Falls back to agent default.
 * @param agentName - Current agent name (for default voice selection)
 * @returns Path to the generated WAV file
 */
export function synthesisePiper(
  text: string,
  voiceModel?: string,
  agentName?: string,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const binary = findPiperBinary();
    if (!binary) {
      reject(new Error('Piper binary not found'));
      return;
    }

    const model = voiceModel || getDefaultPiperVoice(agentName);
    const modelPath = path.join(PIPER_MODELS_DIR, `${model}.onnx`);

    if (!fs.existsSync(modelPath)) {
      reject(new Error(`Piper voice model not found: ${model}.onnx`));
      return;
    }

    // Generate a unique temp file path
    const tmpName = 'atrophy-piper-' + crypto.randomBytes(12).toString('hex') + '.wav';
    const audioPath = path.join(os.tmpdir(), tmpName);

    // Build command args based on binary type
    let cmd: string;
    let args: string[];

    if (binary.type === 'python') {
      cmd = binary.path;
      args = ['-m', 'piper', '--model', modelPath, '--output_file', audioPath];
    } else {
      cmd = binary.path;
      args = ['--model', modelPath, '--output_file', audioPath];
    }

    const proc = spawn(cmd, args, {
      stdio: ['pipe', 'ignore', 'pipe'],
    });

    let stderr = '';
    proc.stderr?.on('data', (chunk: Buffer) => {
      stderr += chunk.toString();
    });

    const timeout = setTimeout(() => {
      try { proc.kill(); } catch { /* already dead */ }
      try { fs.unlinkSync(audioPath); } catch { /* cleanup */ }
      reject(new Error('Piper synthesis timed out (30s)'));
    }, 30_000);

    proc.on('close', (code) => {
      clearTimeout(timeout);
      if (code === 0 && fs.existsSync(audioPath)) {
        const size = fs.statSync(audioPath).size;
        if (size > 44) { // more than just a WAV header
          resolve(audioPath);
        } else {
          try { fs.unlinkSync(audioPath); } catch { /* cleanup */ }
          reject(new Error('Piper produced empty audio'));
        }
      } else {
        try { fs.unlinkSync(audioPath); } catch { /* cleanup */ }
        reject(new Error(`Piper exited with code ${code}: ${stderr.slice(0, 300)}`));
      }
    });

    proc.on('error', (err) => {
      clearTimeout(timeout);
      try { fs.unlinkSync(audioPath); } catch { /* cleanup */ }
      reject(err);
    });

    // Send text via stdin
    proc.stdin.write(text);
    proc.stdin.end();
  });
}

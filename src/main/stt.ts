/**
 * Speech-to-text via whisper.cpp with Metal acceleration.
 * Port of voice/stt.py.
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
  return path.join(os.tmpdir(), 'atrophy-stt-' + name);
}

// ---------------------------------------------------------------------------
// WAV file writing
// ---------------------------------------------------------------------------

function writeWav(audioData: Float32Array, sampleRate: number, channels: number): string {
  const tmpPath = secureTmp('.wav');

  // Convert float32 [-1, 1] to int16
  const int16 = new Int16Array(audioData.length);
  for (let i = 0; i < audioData.length; i++) {
    const s = Math.max(-1, Math.min(1, audioData[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }

  const dataBytes = int16.length * 2;
  const bitsPerSample = 16;
  const blockAlign = channels * (bitsPerSample / 8);
  const byteRate = sampleRate * blockAlign;

  // WAV header (44 bytes)
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + dataBytes, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16); // chunk size
  header.writeUInt16LE(1, 20);  // PCM format
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write('data', 36);
  header.writeUInt32LE(dataBytes, 40);

  const body = Buffer.from(int16.buffer, int16.byteOffset, int16.byteLength);
  fs.writeFileSync(tmpPath, Buffer.concat([header, body]));
  return tmpPath;
}

// ---------------------------------------------------------------------------
// Transcription
// ---------------------------------------------------------------------------

export function transcribe(audioData: Float32Array): Promise<string> {
  return new Promise((resolve, reject) => {
    const config = getConfig();
    const wavPath = writeWav(audioData, config.SAMPLE_RATE, config.CHANNELS);

    const proc = spawn(config.WHISPER_BIN, [
      '-m', config.WHISPER_MODEL,
      '-f', wavPath,
      '--no-timestamps',
      '-t', '4',
      '--language', 'en',
    ], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    proc.stdout?.on('data', (chunk: Buffer) => {
      stdout += chunk.toString();
    });

    const timeout = setTimeout(() => {
      try { proc.kill(); } catch { /* noop */ }
      cleanup();
      reject(new Error('Whisper transcription timed out (30s)'));
    }, 30000);

    function cleanup() {
      try { fs.unlinkSync(wavPath); } catch { /* noop */ }
    }

    proc.on('close', (code) => {
      clearTimeout(timeout);
      cleanup();

      if (code !== 0) {
        resolve('');
        return;
      }

      // Parse output - skip metadata lines starting with [
      const lines = stdout
        .split('\n')
        .map((l) => l.trim())
        .filter((l) => l && !l.startsWith('['));

      resolve(lines.join(' '));
    });

    proc.on('error', () => {
      clearTimeout(timeout);
      cleanup();
      resolve(''); // Graceful degradation
    });
  });
}

// ---------------------------------------------------------------------------
// Fast transcription (for wake word detection)
// ---------------------------------------------------------------------------

export function transcribeFast(audioData: Float32Array): Promise<string> {
  return new Promise((resolve, reject) => {
    const config = getConfig();

    // Prefer tiny model if available
    const tinyModel = path.join(
      path.dirname(config.WHISPER_MODEL),
      'ggml-tiny.en.bin',
    );
    const model = fs.existsSync(tinyModel) ? tinyModel : config.WHISPER_MODEL;
    const wavPath = writeWav(audioData, config.SAMPLE_RATE, config.CHANNELS);

    const proc = spawn(config.WHISPER_BIN, [
      '-m', model,
      '-f', wavPath,
      '--no-timestamps',
      '-t', '2', // fewer threads for lighter footprint
      '--language', 'en',
    ], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    proc.stdout?.on('data', (chunk: Buffer) => {
      stdout += chunk.toString();
    });

    const timeout = setTimeout(() => {
      try { proc.kill(); } catch { /* noop */ }
      cleanup();
      reject(new Error('Fast transcription timed out (5s)'));
    }, 5000);

    function cleanup() {
      try { fs.unlinkSync(wavPath); } catch { /* noop */ }
    }

    proc.on('close', (code) => {
      clearTimeout(timeout);
      cleanup();

      if (code !== 0) {
        resolve('');
        return;
      }

      const lines = stdout
        .split('\n')
        .map((l) => l.trim())
        .filter((l) => l && !l.startsWith('['));

      resolve(lines.join(' '));
    });

    proc.on('error', () => {
      clearTimeout(timeout);
      cleanup();
      resolve('');
    });
  });
}

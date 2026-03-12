/**
 * Audio recording management - bridges renderer audio capture with main process.
 * Port of voice/audio.py (push-to-talk).
 *
 * In Electron, audio capture happens in the renderer via Web Audio API.
 * The renderer sends PCM chunks over IPC, main process accumulates them
 * and runs whisper when recording stops.
 *
 * Push-to-talk: renderer detects Ctrl keydown/keyup, sends IPC signals.
 */

import { ipcMain, BrowserWindow } from 'electron';
import { transcribe } from './stt';
import { getConfig } from './config';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _chunks: Float32Array[] = [];
let _recording = false;
let _startTime = 0;

// ---------------------------------------------------------------------------
// IPC registration
// ---------------------------------------------------------------------------

export function registerAudioHandlers(getWindow: () => BrowserWindow | null): void {
  ipcMain.handle('audio:start', () => {
    _chunks = [];
    _recording = true;
    _startTime = Date.now();
    console.log('[audio] recording started');
  });

  ipcMain.handle('audio:stop', async () => {
    _recording = false;
    const elapsed = (Date.now() - _startTime) / 1000;
    console.log(`[audio] recording stopped (${elapsed.toFixed(1)}s)`);

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
      console.log('[audio] too short, skipping');
      return '';
    }

    // Skip if too long
    if (elapsed > config.MAX_RECORD_SEC) {
      console.log('[audio] exceeded max recording time');
    }

    // Transcribe
    try {
      const text = await transcribe(audio);
      console.log(`[audio] transcribed: "${text.slice(0, 80)}"`);
      return text;
    } catch (e) {
      console.log(`[audio] transcription failed: ${e}`);
      return '';
    }
  });

  // Receive PCM chunks from renderer (Float32Array serialized as ArrayBuffer)
  ipcMain.on('audio:chunk', (_event, buffer: ArrayBuffer) => {
    if (!_recording) return;
    _chunks.push(new Float32Array(buffer));
  });
}

export function isRecording(): boolean {
  return _recording;
}

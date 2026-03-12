/**
 * Wake word detection - ambient listening with local whisper.cpp.
 * Port of voice/wake_word.py.
 *
 * In Electron, we can't use sounddevice directly. Instead, the renderer
 * continuously captures audio via Web Audio API when wake word mode is
 * enabled, and sends chunks to main process for transcription.
 *
 * All processing is local - audio never leaves the machine.
 */

import { ipcMain, BrowserWindow } from 'electron';
import * as fs from 'fs';
import { transcribeFast } from './stt';
import { getConfig } from './config';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _running = false;
let _paused = false;
let _onDetected: (() => void) | null = null;

// ---------------------------------------------------------------------------
// RMS calculation
// ---------------------------------------------------------------------------

function rms(audio: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < audio.length; i++) {
    sum += audio[i] * audio[i];
  }
  return Math.sqrt(sum / audio.length);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function startWakeWordListener(
  onDetected: () => void,
  getWindow: () => BrowserWindow | null,
): void {
  const config = getConfig();

  // Pre-flight checks
  if (!config.WAKE_WORD_ENABLED) return;
  if (!fs.existsSync(config.WHISPER_BIN)) {
    console.log(`[wake word] whisper binary not found at ${config.WHISPER_BIN}`);
    return;
  }
  if (!fs.existsSync(config.WHISPER_MODEL)) {
    console.log(`[wake word] whisper model not found at ${config.WHISPER_MODEL}`);
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

  console.log(`[wake word] listener started (words: ${config.WAKE_WORDS.join(', ')})`);
}

export function stopWakeWordListener(getWindow: () => BrowserWindow | null): void {
  _running = false;
  _onDetected = null;

  const win = getWindow();
  if (win) {
    win.webContents.send('wakeword:stop');
  }

  console.log('[wake word] listener stopped');
}

export function pauseWakeWord(): void {
  _paused = true;
}

export function resumeWakeWord(): void {
  _paused = false;
}

export function isWakeWordListening(): boolean {
  return _running && !_paused;
}

// ---------------------------------------------------------------------------
// IPC handler for audio chunks from renderer
// ---------------------------------------------------------------------------

export function registerWakeWordHandlers(): void {
  // Receive ambient audio chunks from renderer
  ipcMain.on('wakeword:chunk', async (_event, buffer: ArrayBuffer) => {
    if (!_running || _paused) return;

    const audio = new Float32Array(buffer);

    // Skip near-silent chunks
    if (rms(audio) < 0.005) return;

    try {
      const text = await transcribeFast(audio);
      if (!text) return;

      const textLower = text.toLowerCase().trim();
      const config = getConfig();
      const wakeWords = config.WAKE_WORDS.map((w) => w.toLowerCase());

      // Check for wake word match
      const matched = wakeWords.some((w) => textLower.includes(w));
      if (matched) {
        console.log(`[wake word] detected: "${textLower}"`);
        _paused = true; // auto-pause until explicitly resumed
        _onDetected?.();
      }
    } catch (e) {
      console.log(`[wake word] transcription error: ${e}`);
    }
  });
}

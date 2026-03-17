/**
 * Shared audio conversion utilities.
 *
 * Provides MP3-to-OGG Opus conversion via ffmpeg for Telegram voice notes,
 * and temp file cleanup helpers.
 */

import { execFileSync } from 'child_process';
import * as fs from 'fs';
import { createLogger } from './logger';

const log = createLogger('audio-convert');

/**
 * Convert an audio file to OGG Opus format for Telegram voice notes.
 * Returns the output path on success, or null if conversion fails.
 *
 * Requires ffmpeg with libopus support installed on the system.
 */
export function convertToOgg(inputPath: string): string | null {
  const outputPath = inputPath.replace(/\.[^.]+$/, '') + '.ogg';

  try {
    execFileSync(
      'ffmpeg',
      ['-y', '-i', inputPath, '-c:a', 'libopus', '-b:a', '64k', '-vn', outputPath],
      { stdio: 'pipe', timeout: 30_000 },
    );

    if (fs.existsSync(outputPath) && fs.statSync(outputPath).size > 0) {
      return outputPath;
    }
  } catch (e) {
    log.warn(`OGG conversion failed: ${e}`);
  }

  return null;
}

/**
 * Remove temp audio files. Accepts nulls safely.
 */
export function cleanupFiles(...paths: (string | null | undefined)[]): void {
  for (const p of paths) {
    if (p) {
      try {
        fs.unlinkSync(p);
      } catch { /* noop - file may already be gone */ }
    }
  }
}

/**
 * User presence status - active/away tracking.
 * Port of core/status.py.
 *
 * Status is persisted to disk so cron jobs can check it.
 * Any user input sets status to active. 10 minutes idle sets away.
 */

import * as fs from 'fs';
import { execFile } from 'child_process';
import { getConfig } from './config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UserStatus {
  status: 'active' | 'away';
  reason: string;
  since: string;
  returned_from?: string;
  away_since?: string;
}

// ---------------------------------------------------------------------------
// Away detection patterns
// ---------------------------------------------------------------------------

const AWAY_PATTERNS = new RegExp(
  '\\b(' +
  'going to bed|going to sleep|heading to bed|off to bed|' +
  'logging off|signing off|heading off|heading out|' +
  'going out|stepping out|stepping away|' +
  'gotta go|got to go|have to go|need to go|' +
  'talk later|talk tomorrow|see you later|see you tomorrow|' +
  'goodnight|good night|night night|nighty night|' +
  "i'm out|i'm off|i'm done|" +
  'catch you later|brb|be right back|' +
  'shutting down|closing up|calling it' +
  ')\\b',
  'i',
);

export const IDLE_TIMEOUT_SECS = 600; // 10 minutes

// ---------------------------------------------------------------------------
// Read / write
// ---------------------------------------------------------------------------

export function getStatus(): UserStatus {
  const config = getConfig();
  try {
    if (fs.existsSync(config.USER_STATUS_FILE)) {
      return JSON.parse(fs.readFileSync(config.USER_STATUS_FILE, 'utf-8'));
    }
  } catch { /* use default */ }
  return { status: 'active', reason: '', since: new Date().toISOString() };
}

function writeStatus(data: UserStatus): void {
  const config = getConfig();
  try {
    const tmpPath = config.USER_STATUS_FILE + '.tmp';
    fs.writeFileSync(tmpPath, JSON.stringify(data));
    fs.renameSync(tmpPath, config.USER_STATUS_FILE);
  } catch { /* silent */ }
}

export function setStatus(status: 'active' | 'away', reason = ''): void {
  writeStatus({ status, reason, since: new Date().toISOString() });
}

// ---------------------------------------------------------------------------
// Active / away transitions
// ---------------------------------------------------------------------------

export function setActive(): void {
  const current = getStatus();
  if (current.status !== 'active') {
    writeStatus({
      status: 'active',
      reason: '',
      since: new Date().toISOString(),
      returned_from: current.reason || '',
      away_since: current.since || '',
    });
  } else if (current.returned_from) {
    // Already active - clear returned_from after first read
    const cleaned = { ...current };
    delete cleaned.returned_from;
    delete cleaned.away_since;
    writeStatus(cleaned);
  }
}

export function setAway(reason = ''): void {
  setStatus('away', reason);
}

export function isAway(): boolean {
  return getStatus().status === 'away';
}

// ---------------------------------------------------------------------------
// macOS idle detection
// ---------------------------------------------------------------------------

/**
 * Check if the Mac has been idle (no keyboard/mouse) for threshold seconds.
 *
 * Uses macOS IOKit HIDIdleTime via ioreg. Returns true if idle, false if
 * active. Falls back to false (assume active) on error.
 */
export function isMacIdle(thresholdSecs: number = IDLE_TIMEOUT_SECS): Promise<boolean> {
  return new Promise((resolve) => {
    execFile('ioreg', ['-c', 'IOHIDSystem', '-d', '4'], { timeout: 5000 }, (err, stdout) => {
      if (err) { resolve(false); return; }
      for (const line of stdout.split('\n')) {
        if (line.includes('HIDIdleTime') && line.includes('=')) {
          const nsStr = line.split('=').pop()?.trim();
          if (!nsStr) continue;
          const idleNs = parseInt(nsStr, 10);
          if (isNaN(idleNs)) continue;
          const idleSecs = idleNs / 1_000_000_000;
          resolve(idleSecs >= thresholdSecs);
          return;
        }
      }
      resolve(false);
    });
  });
}

// ---------------------------------------------------------------------------
// Away intent detection
// ---------------------------------------------------------------------------

export function detectAwayIntent(text: string): string | null {
  const match = AWAY_PATTERNS.exec(text);
  return match ? match[0] : null;
}

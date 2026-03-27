/**
 * Simple leveled logger. Replaces raw console.log across the codebase
 * so log output can be filtered by severity.
 *
 * Levels: debug < info < warn < error
 * Set via LOG_LEVEL env var or config. Defaults to 'info' in production,
 * 'debug' in development.
 *
 * Maintains a ring buffer of recent log entries, forwards them to the
 * renderer via IPC for the in-app console, and writes to a persistent
 * log file at ~/.atrophy/logs/app.log so diagnostics survive crashes.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogEntry {
  timestamp: number;
  level: LogLevel;
  tag: string;
  message: string;
}

const LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

const isDev = !process.env.NODE_ENV || process.env.NODE_ENV === 'development';

let currentLevel: LogLevel = (process.env.LOG_LEVEL as LogLevel) || (isDev ? 'debug' : 'info');

// ---------------------------------------------------------------------------
// Persistent file logging
// ---------------------------------------------------------------------------

const LOG_DIR = path.join(process.env.ATROPHY_DATA || path.join(os.homedir(), '.atrophy'), 'logs');
const LOG_FILE = path.join(LOG_DIR, 'app.log');
const LOG_FILE_PREV = path.join(LOG_DIR, 'app.prev.log');
const MAX_LOG_SIZE = 2 * 1024 * 1024; // 2 MB before rotation

let _logFd: number | null = null;
let _logSize = 0;

function ensureLogFile(): void {
  if (_logFd !== null) return;
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    // Rotate if too large
    try {
      const stat = fs.statSync(LOG_FILE);
      if (stat.size > MAX_LOG_SIZE) {
        try { fs.unlinkSync(LOG_FILE_PREV); } catch { /* ok */ }
        fs.renameSync(LOG_FILE, LOG_FILE_PREV);
      } else {
        _logSize = stat.size;
      }
    } catch { /* file doesn't exist yet */ }
    _logFd = fs.openSync(LOG_FILE, 'a');
  } catch { /* best effort - don't crash the app over logging */ }
}

// Open log file immediately on module load
ensureLogFile();

// Write a boot separator so each launch is easy to find in the log
function writeBanner(): void {
  if (_logFd === null) return;
  const banner = `\n${'='.repeat(72)}\n  BOOT  ${new Date().toISOString()}  pid=${process.pid}\n${'='.repeat(72)}\n`;
  try {
    fs.writeSync(_logFd, banner);
    _logSize += Buffer.byteLength(banner);
  } catch { /* best effort */ }
}
writeBanner();

function writeToFile(level: LogLevel, tag: string, message: string): void {
  if (_logFd === null) return;
  const ts = new Date().toISOString();
  const line = `${ts} ${level.toUpperCase().padEnd(5)} [${tag}] ${message}\n`;
  try {
    fs.writeSync(_logFd, line);
    _logSize += Buffer.byteLength(line);
    // Rotate mid-session if needed
    if (_logSize > MAX_LOG_SIZE) {
      try {
        fs.closeSync(_logFd);
        _logFd = null;
        try { fs.unlinkSync(LOG_FILE_PREV); } catch { /* ok */ }
        fs.renameSync(LOG_FILE, LOG_FILE_PREV);
        _logFd = fs.openSync(LOG_FILE, 'a');
        _logSize = 0; // Reset size only after successful rotation
      } catch {
        // Rotation failed - try to re-open so logging doesn't go permanently dark
        if (_logFd === null) {
          try {
            _logFd = fs.openSync(LOG_FILE, 'a');
            // Approximate actual file size since rotation failed
            try { _logSize = fs.fstatSync(_logFd).size; } catch { /* keep current estimate */ }
          } catch { /* give up */ }
        }
      }
    }
  } catch { /* best effort */ }
}

/** Read the current log file contents (for the Console tab "load from file" feature). */
export function readLogFile(): string {
  try {
    return fs.readFileSync(LOG_FILE, 'utf-8');
  } catch {
    return '';
  }
}

/** Read the previous log file contents. */
export function readPrevLogFile(): string {
  try {
    return fs.readFileSync(LOG_FILE_PREV, 'utf-8');
  } catch {
    return '';
  }
}

/** Parse a log file string back into LogEntry objects. */
export function parseLogFile(contents: string): LogEntry[] {
  const entries: LogEntry[] = [];
  for (const line of contents.split('\n')) {
    // Format: 2026-03-27T11:20:03.286Z INFO  [tag] message
    const m = line.match(/^(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+(DEBUG|INFO|WARN|ERROR)\s+\[([^\]]*)\]\s+(.*)$/);
    if (m) {
      entries.push({
        timestamp: new Date(m[1]).getTime(),
        level: m[2].toLowerCase().trim() as LogLevel,
        tag: m[3],
        message: m[4],
      });
    }
  }
  return entries;
}

// ---------------------------------------------------------------------------
// Ring buffer for in-app console
// ---------------------------------------------------------------------------

const LOG_BUFFER_SIZE = 500;
const _logBuffer: LogEntry[] = [];
let _ipcSender: ((entry: LogEntry) => void) | null = null;

/** Register a callback to forward log entries to the renderer. */
export function setLogForwarder(sender: (entry: LogEntry) => void): void {
  _ipcSender = sender;
}

/** Get all buffered log entries (for initial load in Settings). */
export function getLogBuffer(): LogEntry[] {
  return [..._logBuffer];
}

function pushEntry(level: LogLevel, tag: string, message: string): void {
  const entry: LogEntry = { timestamp: Date.now(), level, tag, message };
  _logBuffer.push(entry);
  if (_logBuffer.length > LOG_BUFFER_SIZE) _logBuffer.shift();
  writeToFile(level, tag, message);
  if (_ipcSender) {
    try { _ipcSender(entry); } catch { /* renderer may be gone */ }
  }
}

// ---------------------------------------------------------------------------
// Core logger
// ---------------------------------------------------------------------------

export function setLogLevel(level: LogLevel): void {
  currentLevel = level;
}

function shouldLog(level: LogLevel): boolean {
  return LEVELS[level] >= LEVELS[currentLevel];
}

function fmt(tag: string, msg: string): string {
  return tag ? `[${tag}] ${msg}` : msg;
}

export function createLogger(tag: string) {
  return {
    debug(msg: string, ...args: unknown[]) {
      if (shouldLog('debug')) {
        console.debug(fmt(tag, msg), ...args);
        pushEntry('debug', tag, msg);
      }
    },
    info(msg: string, ...args: unknown[]) {
      if (shouldLog('info')) {
        console.log(fmt(tag, msg), ...args);
        pushEntry('info', tag, msg);
      }
    },
    warn(msg: string, ...args: unknown[]) {
      if (shouldLog('warn')) {
        console.warn(fmt(tag, msg), ...args);
        pushEntry('warn', tag, msg);
      }
    },
    error(msg: string, ...args: unknown[]) {
      if (shouldLog('error')) {
        console.error(fmt(tag, msg), ...args);
        pushEntry('error', tag, msg);
      }
    },
  };
}

/** Default logger with no tag */
const log = createLogger('atrophy');
export default log;

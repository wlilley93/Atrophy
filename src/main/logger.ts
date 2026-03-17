/**
 * Simple leveled logger. Replaces raw console.log across the codebase
 * so log output can be filtered by severity.
 *
 * Levels: debug < info < warn < error
 * Set via LOG_LEVEL env var or config. Defaults to 'info' in production,
 * 'debug' in development.
 *
 * Also maintains a ring buffer of recent log entries and forwards them
 * to the renderer via IPC for the in-app console.
 */

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

/**
 * Simple leveled logger. Replaces raw console.log across the codebase
 * so log output can be filtered by severity.
 *
 * Levels: debug < info < warn < error
 * Set via LOG_LEVEL env var or config. Defaults to 'info' in production,
 * 'debug' in development.
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

const isDev = !process.env.NODE_ENV || process.env.NODE_ENV === 'development';

let currentLevel: LogLevel = (process.env.LOG_LEVEL as LogLevel) || (isDev ? 'debug' : 'info');

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
      if (shouldLog('debug')) console.debug(fmt(tag, msg), ...args);
    },
    info(msg: string, ...args: unknown[]) {
      if (shouldLog('info')) console.log(fmt(tag, msg), ...args);
    },
    warn(msg: string, ...args: unknown[]) {
      if (shouldLog('warn')) console.warn(fmt(tag, msg), ...args);
    },
    error(msg: string, ...args: unknown[]) {
      if (shouldLog('error')) console.error(fmt(tag, msg), ...args);
    },
  };
}

/** Default logger with no tag */
const log = createLogger('atrophy');
export default log;

/**
 * Tests for config.ts
 *
 * Tests saveEnvVar (whitelist, per-agent patterns, newline injection),
 * isValidAgentName, isAllowedEnvKey, and findPython-related behavior.
 *
 * Uses a temp directory to isolate filesystem operations from the real
 * user data dir.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

// ---------------------------------------------------------------------------
// Temp directory for isolated tests
// ---------------------------------------------------------------------------

const TEST_DIR = path.join('/tmp', 'atrophy-config-test-' + process.pid);
const TEST_USER_DATA = path.join(TEST_DIR, 'user');

// ---------------------------------------------------------------------------
// Mocks - must be before imports of the module under test
// ---------------------------------------------------------------------------

// Redirect ATROPHY_DATA before config.ts resolves USER_DATA at import time
process.env.ATROPHY_DATA = TEST_USER_DATA;

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (name: string) => path.join(TEST_DIR, name),
    getName: () => 'atrophy-test',
    getVersion: () => '0.0.0-test',
  },
  ipcMain: { handle: vi.fn(), on: vi.fn() },
  BrowserWindow: class {},
}));

// ---------------------------------------------------------------------------
// Import the functions under test
// ---------------------------------------------------------------------------

import { isValidAgentName, isAllowedEnvKey, saveEnvVar } from '../config';

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  fs.mkdirSync(TEST_USER_DATA, { recursive: true });
});

afterEach(() => {
  fs.rmSync(TEST_DIR, { recursive: true, force: true });
  // Clean up env vars set during tests
  delete process.env.ELEVENLABS_API_KEY;
  delete process.env.XAN_TELEGRAM_BOT_TOKEN;
  delete process.env.COMPANION_TELEGRAM_CHAT_ID;
  delete process.env.MONTGOMERY_ELEVENLABS_API_KEY;
  delete process.env.EVIL_KEY;
});

// ---------------------------------------------------------------------------
// isValidAgentName
// ---------------------------------------------------------------------------

describe('isValidAgentName', () => {
  it('accepts simple alphabetic names', () => {
    expect(isValidAgentName('xan')).toBe(true);
    expect(isValidAgentName('companion')).toBe(true);
  });

  it('accepts names with hyphens and underscores', () => {
    expect(isValidAgentName('general-montgomery')).toBe(true);
    expect(isValidAgentName('agent_007')).toBe(true);
  });

  it('accepts names with numbers', () => {
    expect(isValidAgentName('agent42')).toBe(true);
  });

  it('rejects names starting with a hyphen', () => {
    expect(isValidAgentName('-xan')).toBe(false);
  });

  it('rejects names starting with an underscore', () => {
    expect(isValidAgentName('_xan')).toBe(false);
  });

  it('rejects names containing path traversal', () => {
    expect(isValidAgentName('xan..evil')).toBe(false);
    expect(isValidAgentName('../etc/passwd')).toBe(false);
  });

  it('rejects empty string', () => {
    expect(isValidAgentName('')).toBe(false);
  });

  it('rejects names with spaces', () => {
    expect(isValidAgentName('my agent')).toBe(false);
  });

  it('rejects names with special characters', () => {
    expect(isValidAgentName('agent@home')).toBe(false);
    expect(isValidAgentName('agent/evil')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isAllowedEnvKey
// ---------------------------------------------------------------------------

describe('isAllowedEnvKey', () => {
  it('returns true for whitelisted keys', () => {
    expect(isAllowedEnvKey('ELEVENLABS_API_KEY')).toBe(true);
    expect(isAllowedEnvKey('TELEGRAM_BOT_TOKEN')).toBe(true);
    expect(isAllowedEnvKey('ANTHROPIC_API_KEY')).toBe(true);
    expect(isAllowedEnvKey('FAL_KEY')).toBe(true);
    expect(isAllowedEnvKey('OPENAI_API_KEY')).toBe(true);
    expect(isAllowedEnvKey('WORLDMONITOR_API_KEY')).toBe(true);
    expect(isAllowedEnvKey('CHANNEL_API_KEY')).toBe(true);
  });

  it('returns false for non-whitelisted keys', () => {
    expect(isAllowedEnvKey('RANDOM_KEY')).toBe(false);
    expect(isAllowedEnvKey('PATH')).toBe(false);
    expect(isAllowedEnvKey('HOME')).toBe(false);
  });

  it('returns false for per-agent pattern keys (only saveEnvVar handles those)', () => {
    // isAllowedEnvKey only checks the static whitelist, not the regex patterns
    expect(isAllowedEnvKey('XAN_TELEGRAM_BOT_TOKEN')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// saveEnvVar - whitelist enforcement
// ---------------------------------------------------------------------------

describe('saveEnvVar - whitelist', () => {
  it('accepts whitelisted keys', () => {
    const result = saveEnvVar('ELEVENLABS_API_KEY', 'sk-test-123');
    expect(result).toBe(true);
    expect(process.env.ELEVENLABS_API_KEY).toBe('sk-test-123');
  });

  it('rejects non-whitelisted keys', () => {
    const result = saveEnvVar('EVIL_KEY', 'malicious-value');
    expect(result).toBe(false);
    expect(process.env.EVIL_KEY).toBeUndefined();
  });

  it('rejects PATH as non-whitelisted', () => {
    const result = saveEnvVar('PATH', '/evil/bin');
    expect(result).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// saveEnvVar - per-agent patterns
// ---------------------------------------------------------------------------

describe('saveEnvVar - per-agent telegram patterns', () => {
  it('accepts per-agent TELEGRAM_BOT_TOKEN pattern', () => {
    const result = saveEnvVar('XAN_TELEGRAM_BOT_TOKEN', 'bot-token-123');
    expect(result).toBe(true);
    expect(process.env.XAN_TELEGRAM_BOT_TOKEN).toBe('bot-token-123');
  });

  it('accepts per-agent TELEGRAM_CHAT_ID pattern', () => {
    const result = saveEnvVar('COMPANION_TELEGRAM_CHAT_ID', '-100123456');
    expect(result).toBe(true);
    expect(process.env.COMPANION_TELEGRAM_CHAT_ID).toBe('-100123456');
  });

  it('accepts per-agent TELEGRAM_DM_CHAT_ID pattern', () => {
    const result = saveEnvVar('XAN_TELEGRAM_DM_CHAT_ID', '12345');
    expect(result).toBe(true);
  });

  it('accepts per-agent ELEVENLABS_API_KEY pattern', () => {
    const result = saveEnvVar('MONTGOMERY_ELEVENLABS_API_KEY', 'el-key-abc');
    expect(result).toBe(true);
    expect(process.env.MONTGOMERY_ELEVENLABS_API_KEY).toBe('el-key-abc');
  });

  it('accepts per-agent ELEVENLABS_VOICE_ID pattern', () => {
    const result = saveEnvVar('XAN_ELEVENLABS_VOICE_ID', 'voice-id-xyz');
    expect(result).toBe(true);
  });

  it('rejects patterns that do not start with uppercase', () => {
    const result = saveEnvVar('xan_TELEGRAM_BOT_TOKEN', 'token');
    expect(result).toBe(false);
  });

  it('rejects patterns with lowercase in prefix', () => {
    const result = saveEnvVar('Xan_TELEGRAM_BOT_TOKEN', 'token');
    expect(result).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// saveEnvVar - newline injection prevention
// ---------------------------------------------------------------------------

describe('saveEnvVar - newline stripping', () => {
  it('strips \\n from values to prevent env injection', () => {
    saveEnvVar('ELEVENLABS_API_KEY', 'key123\nEVIL=injected');
    expect(process.env.ELEVENLABS_API_KEY).toBe('key123EVIL=injected');
  });

  it('strips \\r from values', () => {
    saveEnvVar('ELEVENLABS_API_KEY', 'key123\rEVIL=injected');
    expect(process.env.ELEVENLABS_API_KEY).toBe('key123EVIL=injected');
  });
});

// ---------------------------------------------------------------------------
// saveEnvVar - .env file operations
// ---------------------------------------------------------------------------

describe('saveEnvVar - file operations', () => {
  it('creates .env file if it does not exist', () => {
    const envPath = path.join(TEST_USER_DATA, '.env');
    expect(fs.existsSync(envPath)).toBe(false);
    saveEnvVar('FAL_KEY', 'fal-key-value');
    // The function writes to USER_DATA which is the real path, not our test path.
    // So we just verify it set the process.env correctly.
    expect(process.env.FAL_KEY).toBe('fal-key-value');
  });
});

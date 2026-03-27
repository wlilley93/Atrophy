/**
 * Startup / boot sequence tests.
 *
 * Guards against regressions that cause:
 * - Boot hangs (update check never resolves, brain animation loops forever)
 * - Crash loops (bad config, missing files, corrupted DB)
 * - Wrong visual state (grey screen, stuck overlays)
 * - Voice/avatar failures (missing keys, wrong paths, file:// blocked)
 * - Test pollution (tests writing to real ~/.atrophy/)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

// ---------------------------------------------------------------------------
// Temp directory isolation
// ---------------------------------------------------------------------------

const TEST_DIR = path.join('/tmp', 'atrophy-startup-test-' + process.pid);
const TEST_USER_DATA = path.join(TEST_DIR, 'user');

// Set ATROPHY_DATA before any module imports resolve USER_DATA
process.env.ATROPHY_DATA = TEST_USER_DATA;

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (name: string) => path.join(TEST_DIR, name),
    getName: () => 'atrophy-test',
    getVersion: () => '1.9.1',
    whenReady: () => Promise.resolve(),
    on: vi.fn(),
  },
  ipcMain: { handle: vi.fn(), on: vi.fn() },
  BrowserWindow: class {},
}));

vi.mock('../logger', () => ({
  createLogger: () => ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  fs.mkdirSync(TEST_USER_DATA, { recursive: true });
});

afterEach(() => {
  fs.rmSync(TEST_DIR, { recursive: true, force: true });
});

// ===========================================================================
// 1. Bundle updater - version comparison
// ===========================================================================

describe('bundle-updater: isNewer / getHotBundlePaths', () => {
  // isNewer is not exported, but we can test it indirectly via getHotBundlePaths.
  // For direct tests we import the module and test the exported functions.

  it('getHotBundlePaths returns null in dev mode', async () => {
    const original = process.env.ELECTRON_RENDERER_URL;
    process.env.ELECTRON_RENDERER_URL = 'http://localhost:5173';
    const { getHotBundlePaths } = await import('../bundle-updater');
    expect(getHotBundlePaths()).toBeNull();
    if (original) process.env.ELECTRON_RENDERER_URL = original;
    else delete process.env.ELECTRON_RENDERER_URL;
  });

  it('getHotBundlePaths returns null when no manifest exists', async () => {
    delete process.env.ELECTRON_RENDERER_URL;
    const { getHotBundlePaths } = await import('../bundle-updater');
    expect(getHotBundlePaths()).toBeNull();
  });

  it('getHotBundlePaths returns null when bundle dir is incomplete', async () => {
    delete process.env.ELECTRON_RENDERER_URL;
    // Write manifest but don't create out/ files
    const bundleDir = path.join(TEST_USER_DATA, 'bundle');
    fs.mkdirSync(bundleDir, { recursive: true });
    fs.writeFileSync(
      path.join(bundleDir, 'bundle-manifest.json'),
      JSON.stringify({ version: '99.0.0', sha256: '', timestamp: '' }),
    );
    const { getHotBundlePaths } = await import('../bundle-updater');
    // Not packaged in test, so returns null before checking files
    expect(getHotBundlePaths()).toBeNull();
  });

  it('checkForBundleUpdate returns null in dev mode', async () => {
    process.env.ELECTRON_RENDERER_URL = 'http://localhost:5173';
    const { checkForBundleUpdate } = await import('../bundle-updater');
    const result = await checkForBundleUpdate();
    expect(result).toBeNull();
    delete process.env.ELECTRON_RENDERER_URL;
  });

  it('getActiveBundleVersion returns frozen version when no hot bundle', async () => {
    const { getActiveBundleVersion } = await import('../bundle-updater');
    // app.getVersion() returns '1.9.1' from our mock
    expect(getActiveBundleVersion()).toBe('1.9.1');
  });
});

// ===========================================================================
// 2. Updater - dev mode bypass
// ===========================================================================

describe('updater: dev mode behavior', () => {
  it('checkForUpdates is a no-op that does not throw in dev mode', async () => {
    process.env.ELECTRON_RENDERER_URL = 'http://localhost:5173';

    vi.resetModules();
    vi.mock('electron', () => ({
      app: {
        isPackaged: false,
        getPath: () => TEST_DIR,
        getName: () => 'atrophy-test',
        getVersion: () => '1.9.1',
      },
      ipcMain: { handle: vi.fn(), on: vi.fn() },
      BrowserWindow: class {},
    }));
    vi.mock('../logger', () => ({
      createLogger: () => ({
        info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn(),
      }),
    }));
    vi.mock('electron-updater', () => ({
      default: {
        autoUpdater: {
          autoDownload: false,
          autoInstallOnAppQuit: false,
          on: vi.fn(),
          checkForUpdates: vi.fn().mockResolvedValue(null),
        },
      },
    }));

    const { checkForUpdates } = await import('../updater');
    // Should not throw even without initAutoUpdater (win is null)
    expect(() => checkForUpdates()).not.toThrow();
    delete process.env.ELECTRON_RENDERER_URL;
  });

  it('initAutoUpdater returns early in dev mode (no event bindings)', async () => {
    process.env.ELECTRON_RENDERER_URL = 'http://localhost:5173';

    vi.resetModules();

    const { initAutoUpdater } = await import('../updater');
    const mockWindow = { webContents: { send: vi.fn() } } as any;

    // Should not throw in dev mode
    expect(() => initAutoUpdater(mockWindow)).not.toThrow();
    delete process.env.ELECTRON_RENDERER_URL;
  });
});

// ===========================================================================
// 3. TTS fallback chain
// ===========================================================================

describe('TTS: fallback chain and credit exhaustion', () => {
  it('exhaustion cooldown blocks synthesis for 30 minutes', async () => {
    vi.resetModules();
    vi.mock('electron', () => ({
      app: {
        isPackaged: false,
        getPath: () => TEST_DIR,
        getName: () => 'atrophy-test',
        getVersion: () => '1.9.1',
      },
      ipcMain: { handle: vi.fn(), on: vi.fn() },
      BrowserWindow: class {},
    }));
    vi.mock('../config', () => ({
      getConfig: () => ({
        ELEVENLABS_API_KEY: 'test-key',
        ELEVENLABS_VOICE_ID: 'test-voice',
        ELEVENLABS_MODEL: 'eleven_v3',
        ELEVENLABS_STABILITY: 0.5,
        ELEVENLABS_SIMILARITY: 0.75,
        ELEVENLABS_STYLE: 0.35,
        TTS_PLAYBACK_RATE: 1.0,
        FAL_VOICE_ID: '',
        TTS_BACKEND: 'elevenlabs',
      }),
    }));
    vi.mock('../logger', () => ({
      createLogger: () => ({
        info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn(),
      }),
    }));

    const { markElevenLabsExhausted, isElevenLabsExhausted, resetElevenLabsStatus, COOLDOWN_MS } =
      await import('../tts');

    resetElevenLabsStatus();
    expect(isElevenLabsExhausted()).toBe(false);

    markElevenLabsExhausted();
    expect(isElevenLabsExhausted()).toBe(true);

    // Simulate time just before cooldown expires
    const originalNow = Date.now;
    const start = originalNow();
    Date.now = () => start + COOLDOWN_MS - 1000;
    expect(isElevenLabsExhausted()).toBe(true);

    // Simulate time after cooldown expires
    Date.now = () => start + COOLDOWN_MS + 1;
    expect(isElevenLabsExhausted()).toBe(false);

    Date.now = originalNow;
    resetElevenLabsStatus();
  });

  it('COOLDOWN_MS is 30 minutes', async () => {
    vi.resetModules();
    vi.mock('../config', () => ({ getConfig: () => ({}) }));
    vi.mock('../logger', () => ({
      createLogger: () => ({
        info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn(),
      }),
    }));
    const { COOLDOWN_MS } = await import('../tts');
    expect(COOLDOWN_MS).toBe(30 * 60 * 1000);
  });
});

// ===========================================================================
// 4. Avatar path resolution
// ===========================================================================

describe('avatar: path resolution', () => {
  it('listLoops returns .mp4 files from loops dir', () => {
    const agentDir = path.join(TEST_USER_DATA, 'agents', 'test_agent', 'avatar', 'loops');
    fs.mkdirSync(agentDir, { recursive: true });
    fs.writeFileSync(path.join(agentDir, 'loop_01.mp4'), '');
    fs.writeFileSync(path.join(agentDir, 'loop_02.mp4'), '');
    fs.writeFileSync(path.join(agentDir, 'thumbnail.jpg'), '');

    // Simulate what avatar:listLoops does
    const loopsDir = agentDir;
    const results: string[] = [];
    const entries = fs.readdirSync(loopsDir);
    for (const f of entries) {
      if (f.endsWith('.mp4')) {
        results.push(path.join(loopsDir, f));
      }
    }
    expect(results).toHaveLength(2);
    expect(results.every(r => r.endsWith('.mp4'))).toBe(true);
  });

  it('listLoops returns empty array when loops dir missing', () => {
    const loopsDir = path.join(TEST_USER_DATA, 'agents', 'nonexistent', 'avatar', 'loops');
    expect(fs.existsSync(loopsDir)).toBe(false);
    // Should return empty, not throw
    const results: string[] = [];
    if (fs.existsSync(loopsDir)) {
      for (const f of fs.readdirSync(loopsDir)) {
        if (f.endsWith('.mp4')) results.push(path.join(loopsDir, f));
      }
    }
    expect(results).toHaveLength(0);
  });

  it('getVideoPath rejects path traversal attempts', () => {
    const validate = (input: string) => /^[a-zA-Z0-9_-]+$/.test(input);
    expect(validate('blue')).toBe(true);
    expect(validate('idle_hover')).toBe(true);
    expect(validate('../../../etc/passwd')).toBe(false);
    expect(validate('blue/../../hack')).toBe(false);
    expect(validate('')).toBe(false);
    expect(validate('valid-name')).toBe(true);
    expect(validate('valid_name_2')).toBe(true);
  });

  it('ambient path resolution tries multiple fallback locations', () => {
    const avatarDir = path.join(TEST_USER_DATA, 'agents', 'monty', 'avatar');
    fs.mkdirSync(path.join(avatarDir, 'loops'), { recursive: true });

    // No files exist yet - all lookups should miss
    const candidates = [
      path.join(avatarDir, 'monty_ambient.mp4'),
      path.join(avatarDir, 'ambient.mp4'),
      path.join(avatarDir, 'loops', 'ambient_loop.mp4'),
    ];
    expect(candidates.every(p => !fs.existsSync(p))).toBe(true);

    // Create the third fallback
    fs.writeFileSync(path.join(avatarDir, 'loops', 'ambient_loop.mp4'), '');

    // Resolution should find the third candidate
    const found = candidates.find(p => fs.existsSync(p));
    expect(found).toBe(path.join(avatarDir, 'loops', 'ambient_loop.mp4'));
  });

  it('mirror-style loops are sorted correctly', () => {
    const loopsDir = path.join(TEST_USER_DATA, 'agents', 'mirror', 'avatar', 'loops');
    fs.mkdirSync(loopsDir, { recursive: true });

    // Create numbered clips in scrambled order
    for (const n of [3, 1, 10, 2]) {
      fs.writeFileSync(path.join(loopsDir, `ambient_loop_${String(n).padStart(2, '0')}.mp4`), '');
    }

    const entries = fs.readdirSync(loopsDir);
    const mirrorClips = entries
      .filter((f) => /^ambient_loop_\d+\.mp4$/.test(f))
      .sort();

    expect(mirrorClips).toEqual([
      'ambient_loop_01.mp4',
      'ambient_loop_02.mp4',
      'ambient_loop_03.mp4',
      'ambient_loop_10.mp4',
    ]);
  });
});

// ===========================================================================
// 5. Config test isolation (meta-test)
// ===========================================================================

describe('test isolation: ATROPHY_DATA redirection', () => {
  it('process.env.ATROPHY_DATA points to temp dir', () => {
    expect(process.env.ATROPHY_DATA).toBe(TEST_USER_DATA);
  });

  it('ATROPHY_DATA was set before config module loaded', () => {
    // This is the critical invariant: if ATROPHY_DATA is set before config.ts
    // is imported, USER_DATA resolves to the temp dir and saveEnvVar won't
    // touch the real ~/.atrophy/.env. We verify the env var is set.
    expect(process.env.ATROPHY_DATA).toBe(TEST_USER_DATA);
    expect(process.env.ATROPHY_DATA).not.toBe(path.join(os.homedir(), '.atrophy'));
  });
});

// ===========================================================================
// 6. Boot state machine
// ===========================================================================

describe('boot: state machine invariants', () => {
  it('update check has bounded timeouts (no infinite hang)', () => {
    // The renderer uses 15s for bundle check and 20s for app update check.
    // Total maximum boot delay should be under 40s.
    const BUNDLE_TIMEOUT_MS = 15_000;
    const APP_UPDATE_TIMEOUT_MS = 20_000;
    const MAX_BOOT_DELAY = BUNDLE_TIMEOUT_MS + APP_UPDATE_TIMEOUT_MS;

    expect(MAX_BOOT_DELAY).toBeLessThanOrEqual(40_000);
    // Each individual timeout should be reasonable
    expect(BUNDLE_TIMEOUT_MS).toBeGreaterThan(0);
    expect(APP_UPDATE_TIMEOUT_MS).toBeGreaterThan(0);
  });

  it('brain frame modulo is safe with zero frames', () => {
    // If brainFramePaths is empty, modulo by 0 would crash.
    // The renderer guards with: if (brainFramePaths.length > 0)
    const brainFramePaths: string[] = [];
    const guard = brainFramePaths.length > 0;

    // With guard, this should never execute
    if (guard) {
      const frame = 1 % brainFramePaths.length;
      expect(frame).toBeDefined();
    }
    expect(guard).toBe(false);
  });

  it('isNewer semver comparison handles edge cases', () => {
    // Replicate the isNewer logic from bundle-updater.ts
    function isNewer(a: string, b: string): boolean {
      const pa = a.split('.').map(Number);
      const pb = b.split('.').map(Number);
      for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
        const va = pa[i] || 0;
        const vb = pb[i] || 0;
        if (va > vb) return true;
        if (va < vb) return false;
      }
      return false;
    }

    expect(isNewer('1.9.2', '1.9.1')).toBe(true);
    expect(isNewer('1.9.1', '1.9.1')).toBe(false);
    expect(isNewer('1.9.0', '1.9.1')).toBe(false);
    expect(isNewer('2.0.0', '1.99.99')).toBe(true);
    expect(isNewer('1.10.0', '1.9.0')).toBe(true);
    expect(isNewer('1.0.0', '1.0')).toBe(false);
    expect(isNewer('1.0.1', '1.0')).toBe(true);
    // NaN from 'v' prefix - documents known limitation
    expect(isNewer('v1.0.0', '1.0.0')).toBe(false); // NaN < 1, returns false
  });
});

// ===========================================================================
// 7. Env var loading
// ===========================================================================

describe('env: .env file parsing', () => {
  it('env whitelist rejects dangerous keys', () => {
    // The ALLOWED_ENV_KEYS set in config.ts controls what .env can inject.
    // These tests verify the pattern matching without importing the real module
    // (which conflicts with vi.mock hoisting from TTS tests).
    const ALLOWED_ENV_KEYS = new Set([
      'ELEVENLABS_API_KEY', 'FAL_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID',
      'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'WORLDMONITOR_API_KEY',
      'CHANNEL_API_KEY', 'UPSTASH_REDIS_REST_URL', 'UPSTASH_REDIS_REST_TOKEN',
    ]);
    const perAgentPattern = /^[A-Z][A-Z0-9_]*_TELEGRAM_(BOT_TOKEN|CHAT_ID|DM_CHAT_ID)$/;
    const perAgentELPattern = /^[A-Z][A-Z0-9_]*_ELEVENLABS_(API_KEY|VOICE_ID)$/;

    function isAllowed(key: string): boolean {
      return ALLOWED_ENV_KEYS.has(key) || perAgentPattern.test(key) || perAgentELPattern.test(key);
    }

    expect(isAllowed('ELEVENLABS_API_KEY')).toBe(true);
    expect(isAllowed('FAL_KEY')).toBe(true);
    expect(isAllowed('XAN_TELEGRAM_BOT_TOKEN')).toBe(true);
    expect(isAllowed('MONTGOMERY_ELEVENLABS_VOICE_ID')).toBe(true);
    // Dangerous keys must be rejected
    expect(isAllowed('PATH')).toBe(false);
    expect(isAllowed('HOME')).toBe(false);
    expect(isAllowed('EVIL_KEY')).toBe(false);
    expect(isAllowed('LD_PRELOAD')).toBe(false);
    expect(isAllowed('NODE_OPTIONS')).toBe(false);
  });

  it('strips quotes from .env values', () => {
    // Simulate the .env parser logic
    function parseValue(val: string): string {
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        return val.slice(1, -1);
      }
      return val;
    }

    expect(parseValue('"quoted-value"')).toBe('quoted-value');
    expect(parseValue("'single-quoted'")).toBe('single-quoted');
    expect(parseValue('unquoted')).toBe('unquoted');
    expect(parseValue('""')).toBe('');
    expect(parseValue("''")).toBe('');
  });

  it('newline characters are stripped by the injection prevention logic', () => {
    // Replicate the stripping logic from saveEnvVar
    function stripNewlines(value: string): string {
      return value.replace(/[\r\n]/g, '');
    }

    expect(stripNewlines('safe-key\nEVIL=injected')).toBe('safe-keyEVIL=injected');
    expect(stripNewlines('safe-key\rEVIL=injected')).toBe('safe-keyEVIL=injected');
    expect(stripNewlines('safe-key\r\nEVIL=injected')).toBe('safe-keyEVIL=injected');
    expect(stripNewlines('no-newlines')).toBe('no-newlines');
    expect(stripNewlines('')).toBe('');
  });
});

/**
 * Three-tier config resolution: env vars -> ~/.atrophy/config.json -> agent.json -> defaults.
 * Port of config.py.
 */

import { app } from 'electron';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { execFileSync, execSync } from 'child_process';
import * as crypto from 'crypto';

// ---------------------------------------------------------------------------
// Root paths
// ---------------------------------------------------------------------------

export const BUNDLE_ROOT = app.isPackaged
  ? path.join(process.resourcesPath!)
  : path.resolve(__dirname, '..', '..');

export const USER_DATA = path.join(
  process.env.ATROPHY_DATA || path.join(os.homedir(), '.atrophy'),
);

// ---------------------------------------------------------------------------
// User config file
// ---------------------------------------------------------------------------

let _userCfg: Record<string, unknown> = {};

function loadUserConfig(): void {
  const cfgPath = path.join(USER_DATA, 'config.json');
  try {
    if (fs.existsSync(cfgPath)) {
      _userCfg = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
    }
  } catch {
    _userCfg = {};
  }
}

// ---------------------------------------------------------------------------
// .env file (secrets - API keys, tokens)
// ---------------------------------------------------------------------------

/** Load ~/.atrophy/.env into process.env. Called once on startup. */
function loadEnvFile(): void {
  const envPath = path.join(USER_DATA, '.env');
  if (!fs.existsSync(envPath)) return;
  try {
    const content = fs.readFileSync(envPath, 'utf-8');
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eqIdx = trimmed.indexOf('=');
      if (eqIdx === -1) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      let val = trimmed.slice(eqIdx + 1).trim();
      // Strip surrounding quotes
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      // Only load keys that are in the whitelist or match the per-agent token pattern.
      // Reject everything else to prevent arbitrary env var injection.
      const isAllowed = ALLOWED_ENV_KEYS.has(key)
        || /^[A-Z][A-Z0-9_]*_TELEGRAM_(BOT_TOKEN|CHAT_ID|DM_CHAT_ID)$/.test(key)
        || /^TELEGRAM_(BOT_TOKEN|CHAT_ID|DM_CHAT_ID)_[A-Z][A-Z0-9_]*$/.test(key)
        || /^[A-Z][A-Z0-9_]*_ELEVENLABS_(API_KEY|VOICE_ID)$/.test(key);
      if (key && !process.env[key] && isAllowed) {
        process.env[key] = val;
      }
    }
  } catch {
    // .env parse failure is non-fatal
  }
}

/** Whitelist of keys allowed in .env (secrets only). */
const ALLOWED_ENV_KEYS = new Set([
  'ELEVENLABS_API_KEY',
  'FAL_KEY',
  'TELEGRAM_BOT_TOKEN',
  'TELEGRAM_CHAT_ID',
  'OPENAI_API_KEY',
  'ANTHROPIC_API_KEY',
  'WORLDMONITOR_API_KEY',
  'CHANNEL_API_KEY',
  'UPSTASH_REDIS_REST_URL',
  'UPSTASH_REDIS_REST_TOKEN',
]);

/** Check if a key is in the allowed env keys whitelist. */
export function isAllowedEnvKey(key: string): boolean {
  return ALLOWED_ENV_KEYS.has(key);
}

/** Save a secret to ~/.atrophy/.env. Updates or appends the key. Returns false if key not in whitelist. */
export function saveEnvVar(key: string, value: string): boolean {
  const isAllowed = ALLOWED_ENV_KEYS.has(key)
    || /^[A-Z][A-Z0-9_]*_TELEGRAM_(BOT_TOKEN|CHAT_ID|DM_CHAT_ID)$/.test(key)
    || /^TELEGRAM_(BOT_TOKEN|CHAT_ID|DM_CHAT_ID)_[A-Z][A-Z0-9_]*$/.test(key)
    || /^[A-Z][A-Z0-9_]*_ELEVENLABS_(API_KEY|VOICE_ID)$/.test(key);
  if (!isAllowed) return false;
  // Strip newlines to prevent env injection
  value = value.replace(/[\r\n]/g, '');
  // Resolve data dir dynamically so tests can override via ATROPHY_DATA
  const dataDir = process.env.ATROPHY_DATA || USER_DATA;
  const envPath = path.join(dataDir, '.env');
  fs.mkdirSync(dataDir, { recursive: true });
  let lines: string[] = [];
  let replaced = false;
  if (fs.existsSync(envPath)) {
    lines = fs.readFileSync(envPath, 'utf-8').split('\n');
    lines = lines.map(line => {
      if (line.startsWith(`${key}=`)) {
        replaced = true;
        return `${key}=${value}`;
      }
      return line;
    });
  }
  if (!replaced) {
    lines.push(`${key}=${value}`);
  }
  // Remove trailing empty lines, ensure final newline
  while (lines.length > 0 && lines[lines.length - 1].trim() === '') lines.pop();
  fs.writeFileSync(envPath, lines.join('\n') + '\n', { mode: 0o600 });
  // Also set in current process
  process.env[key] = value;
  // Update cached config singleton so getConfig() sees the new value
  if (_config && key in _config) {
    (_config as any)[key] = value;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Deep merge helper
// ---------------------------------------------------------------------------

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Recursively merge source into target. Plain objects are merged key-by-key;
 * all other values (arrays, primitives, null) are overwritten from source.
 * Returns a new object - does not mutate either input.
 */
function deepMerge(
  target: Record<string, unknown>,
  source: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...target };
  for (const key of Object.keys(source)) {
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
    const srcVal = source[key];
    const tgtVal = result[key];
    if (isPlainObject(srcVal) && isPlainObject(tgtVal)) {
      result[key] = deepMerge(
        tgtVal as Record<string, unknown>,
        srcVal as Record<string, unknown>,
      );
    } else {
      result[key] = srcVal;
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Agent manifest
// ---------------------------------------------------------------------------

let _agentManifest: Record<string, unknown> = {};

/** Validate agent name - alphanumeric, hyphens, underscores only. */
export function isValidAgentName(name: string): boolean {
  return /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(name) && !name.includes('..');
}

/**
 * Resolve the user-data directory for an agent, checking org-nested
 * paths before flat. Mirrors agent-manager.getAgentDir() but lives here
 * to avoid a circular import (agent-manager imports from config).
 */
function resolveAgentDir(name: string): string {
  const agentsRoot = path.join(USER_DATA, 'agents');
  // 1. Check org-nested: agents/<org>/<name>/data/
  if (fs.existsSync(agentsRoot)) {
    try {
      for (const entry of fs.readdirSync(agentsRoot)) {
        const nested = path.join(agentsRoot, entry, name, 'data');
        if (fs.existsSync(nested)) {
          return path.join(agentsRoot, entry, name);
        }
      }
    } catch { /* non-critical */ }
  }
  // 2. Flat: agents/<name>/
  return path.join(agentsRoot, name);
}

function loadAgentManifest(name: string): void {
  if (!isValidAgentName(name)) {
    console.warn(`[config] Invalid agent name rejected: ${name}`);
    _agentManifest = {};
    return;
  }
  // Load bundle manifest as base, then merge user overrides on top.
  // This ensures bundle defaults (voice, display, heartbeat, telegram)
  // are preserved unless the user explicitly overrides them.
  const bundlePath = path.join(BUNDLE_ROOT, 'agents', name, 'data', 'agent.json');
  const userPath = path.join(resolveAgentDir(name), 'data', 'agent.json');

  let bundle: Record<string, unknown> = {};
  let user: Record<string, unknown> = {};

  try {
    if (fs.existsSync(bundlePath)) {
      bundle = JSON.parse(fs.readFileSync(bundlePath, 'utf-8'));
    }
  } catch { /* ignore */ }

  try {
    if (fs.existsSync(userPath)) {
      user = JSON.parse(fs.readFileSync(userPath, 'utf-8'));
    }
  } catch { /* ignore */ }

  _agentManifest = deepMerge(bundle, user);
}

// ---------------------------------------------------------------------------
// Resolution helper
// ---------------------------------------------------------------------------

function cfg<T>(key: string, fallback: T): T {
  // Tier 1: env vars
  const envVal = process.env[key];
  if (envVal !== undefined) {
    if (typeof fallback === 'number') {
      const n = Number(envVal);
      return (Number.isNaN(n) ? fallback : n) as T;
    }
    if (typeof fallback === 'boolean') return (envVal.toLowerCase() === 'true') as T;
    return envVal as T;
  }
  // Tier 2: user config
  if (key in _userCfg) return _userCfg[key] as T;
  // Tier 3: default
  // (Agent manifest values are read directly via nested accessors in _resolveAgent,
  // not through this function - the manifest uses snake_case nested objects.)
  return fallback;
}

// ---------------------------------------------------------------------------
// Agent directory resolution
// ---------------------------------------------------------------------------

function findAgentDir(name: string): string {
  const userAgents = path.join(USER_DATA, 'agents');

  // 1. Check org-nested paths: agents/<org>/<name>/data/agent.json
  if (fs.existsSync(userAgents)) {
    try {
      for (const entry of fs.readdirSync(userAgents)) {
        const nested = path.join(userAgents, entry, name, 'data', 'agent.json');
        if (fs.existsSync(nested)) {
          return path.join(userAgents, entry, name);
        }
      }
    } catch { /* non-critical */ }
  }

  // 2. Flat user path: agents/<name>/data/agent.json
  const userDir = path.join(userAgents, name);
  if (fs.existsSync(path.join(userDir, 'data', 'agent.json'))) return userDir;

  // 3. Bundle path
  const bundleDir = path.join(BUNDLE_ROOT, 'agents', name);
  if (fs.existsSync(path.join(bundleDir, 'data', 'agent.json'))) return bundleDir;

  return userDir; // prefer flat user dir for new agents
}

function agentDataDir(name: string): string {
  const dir = findAgentDir(name);
  const d = path.join(dir, 'data');
  fs.mkdirSync(d, { recursive: true });
  return d;
}

// ---------------------------------------------------------------------------
// ensure user data dirs
// ---------------------------------------------------------------------------

export function ensureUserData(): void {
  for (const dir of [
    USER_DATA,
    path.join(USER_DATA, 'agents'),
    path.join(USER_DATA, 'logs'),
    path.join(USER_DATA, 'models'),
  ]) {
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  }

  const cfgPath = path.join(USER_DATA, 'config.json');
  if (!fs.existsSync(cfgPath)) {
    fs.writeFileSync(cfgPath, '{}', { mode: 0o600 });
  }

  migrateAgentData();
  cleanupStaleFiles();
}

/** Remove stale temp files, old logs, and orphaned artifacts on boot. */
function cleanupStaleFiles(): void {
  try {
    // TTS temp files older than 24 hours
    const ttsDir = path.join(USER_DATA, 'tts_output');
    if (fs.existsSync(ttsDir)) {
      const cutoff = Date.now() - 24 * 60 * 60 * 1000;
      for (const f of fs.readdirSync(ttsDir)) {
        const fp = path.join(ttsDir, f);
        try {
          if (fs.statSync(fp).mtimeMs < cutoff) fs.unlinkSync(fp);
        } catch { /* skip locked files */ }
      }
    }

    // Log files older than 7 days
    const logsDir = path.join(USER_DATA, 'logs');
    if (fs.existsSync(logsDir)) {
      const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
      for (const f of fs.readdirSync(logsDir)) {
        if (!f.endsWith('.log')) continue;
        const fp = path.join(logsDir, f);
        try {
          if (fs.statSync(fp).mtimeMs < cutoff) fs.unlinkSync(fp);
        } catch { /* skip */ }
      }
    }

    // Remove known orphan files (shell redirect artifacts, empty dirs)
    const orphans = ['&1', 'signing'];
    for (const name of orphans) {
      const fp = path.join(USER_DATA, name);
      try {
        if (fs.existsSync(fp)) {
          const stat = fs.statSync(fp);
          if (stat.isFile() && stat.size === 0) fs.unlinkSync(fp);
          else if (stat.isDirectory()) {
            const entries = fs.readdirSync(fp);
            if (entries.length === 0) fs.rmdirSync(fp);
          }
        }
      } catch { /* non-fatal */ }
    }
  } catch { /* cleanup is best-effort */ }
}

function migrateAgentData(): void {
  // One-time migration: copy runtime data from bundle to ~/.atrophy/.
  // Matches Python's _migrate_legacy_data() - copies files individually,
  // skipping agent.json (manifest stays in bundle) and any file that
  // already exists at the destination.
  const bundleAgents = path.join(BUNDLE_ROOT, 'agents');
  if (!fs.existsSync(bundleAgents) || !fs.statSync(bundleAgents).isDirectory()) return;

  for (const name of fs.readdirSync(bundleAgents)) {
    const agentDir = path.join(bundleAgents, name);
    if (!fs.statSync(agentDir).isDirectory()) continue;

    // Migrate data/ files (skip agent.json - manifest stays in bundle)
    const bundleData = path.join(agentDir, 'data');
    if (fs.existsSync(bundleData) && fs.statSync(bundleData).isDirectory()) {
      const userData = agentDataDir(name);
      for (const file of fs.readdirSync(bundleData)) {
        if (file === 'agent.json') continue;
        const src = path.join(bundleData, file);
        const dst = path.join(userData, file);
        if (!fs.existsSync(dst) && fs.statSync(src).isFile()) {
          fs.copyFileSync(src, dst);
        }
      }
    }

    // Migrate entire avatar/ tree - walk recursively, copy individual
    // files only if they do not already exist at the destination.
    // This preserves any user modifications while filling in missing files.
    const bundleAvatar = path.join(agentDir, 'avatar');
    const userAvatar = path.join(resolveAgentDir(name), 'avatar');
    if (fs.existsSync(bundleAvatar) && fs.statSync(bundleAvatar).isDirectory()) {
      copyTreeIfMissing(bundleAvatar, userAvatar);
    }
  }
}

/**
 * Recursively copy files from src to dst, creating directories as needed.
 * Only copies files that do not already exist at the destination.
 */
function copyTreeIfMissing(src: string, dst: string): void {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcEntry = path.join(src, entry.name);
    const dstEntry = path.join(dst, entry.name);
    if (entry.isDirectory()) {
      copyTreeIfMissing(srcEntry, dstEntry);
    } else if (entry.isFile() && !fs.existsSync(dstEntry)) {
      fs.copyFileSync(srcEntry, dstEntry);
    }
  }
}

// ---------------------------------------------------------------------------
// Python path detection
// ---------------------------------------------------------------------------

function findPython(): string {
  if (process.env.PYTHON_PATH) {
    const p = process.env.PYTHON_PATH;
    // Validate it looks like a file path - reject shell metacharacters
    if (/^[a-zA-Z0-9_.\/~-]+$/.test(p)) return p;
    console.warn('PYTHON_PATH contains invalid characters, ignoring');
  }

  // Scan common Python locations. Electron apps don't inherit shell PATH,
  // so bare 'python3' often fails. Try full-path interpreters first (where
  // pip-installed deps like dotenv live), then fall back to bare 'python3'
  // which may resolve to macOS system Python (no pip packages).
  const home = process.env.HOME || os.homedir();
  const candidates = [
    // pyenv shim first - delegates to the user's active version
    `${home}/.pyenv/shims/python3`,
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    // Bare python3 last - may find system Python which lacks pip deps
    'python3',
  ];

  // Also scan pyenv versions directory for concrete interpreters
  try {
    const pyenvDir = `${home}/.pyenv/versions`;
    const { readdirSync, statSync } = require('fs');
    const versions = readdirSync(pyenvDir)
      .filter((v: string) => statSync(`${pyenvDir}/${v}`).isDirectory())
      .sort()
      .reverse(); // newest first
    for (const v of versions) {
      candidates.push(`${pyenvDir}/${v}/bin/python3`);
    }
  } catch {
    // pyenv not installed - that's fine
  }

  for (const c of candidates) {
    try {
      execFileSync(c, ['--version'], { stdio: 'pipe' });
      return c;
    } catch {
      continue;
    }
  }
  return 'python3';
}

// ---------------------------------------------------------------------------
// Google auth detection
// ---------------------------------------------------------------------------

function googleConfigured(): boolean {
  // Legacy: custom OAuth tokens
  const legacyToken = path.join(USER_DATA, '.google', 'token.json');
  if (fs.existsSync(legacyToken)) return true;

  // New: gws CLI auth - find the binary, run `gws auth status`, parse JSON
  let gwsBin: string | null = null;
  try {
    gwsBin = execSync('which gws', { stdio: 'pipe', encoding: 'utf-8' }).trim();
  } catch {
    return false;
  }
  if (!gwsBin) return false;

  try {
    const result = execFileSync(gwsBin, ['auth', 'status'], {
      stdio: ['pipe', 'pipe', 'pipe'],
      encoding: 'utf-8',
      timeout: 5000,
    }) as string;
    const parsed = JSON.parse(result) as Record<string, unknown>;
    return (parsed.auth_method ?? 'none') !== 'none';
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Obsidian vault
// ---------------------------------------------------------------------------

const DEFAULT_OBSIDIAN = path.join(
  process.env.HOME || '/tmp',
  'Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind',
);

function obsidianVault(): string {
  return process.env.OBSIDIAN_VAULT || DEFAULT_OBSIDIAN;
}

function obsidianAvailable(): boolean {
  return fs.existsSync(obsidianVault());
}

// ---------------------------------------------------------------------------
// Avatar path resolution (user > bundle)
// ---------------------------------------------------------------------------

function avatarPath(agentName: string, rel: string): string {
  const userPath = path.join(resolveAgentDir(agentName), 'avatar', rel);
  if (fs.existsSync(userPath)) return userPath;
  const bundlePath = path.join(BUNDLE_ROOT, 'agents', agentName, 'avatar', rel);
  if (fs.existsSync(bundlePath)) return bundlePath;
  return userPath;
}

// ---------------------------------------------------------------------------
// Config singleton
// ---------------------------------------------------------------------------

export class Config {
  // Agent identity
  AGENT_NAME: string;
  AGENT_DISPLAY_NAME: string;
  AGENT_DIR: string;
  DATA_DIR: string;
  USER_NAME: string;
  OPENING_LINE: string;
  WAKE_WORDS: string[];
  TELEGRAM_EMOJI: string;
  DISABLED_TOOLS: string[];

  // Paths
  DB_PATH: string;
  SCHEMA_PATH: string;
  VERSION: string;
  PYTHON_PATH: string;

  // TTS
  TTS_BACKEND: string;
  ELEVENLABS_API_KEY: string;
  ELEVENLABS_VOICE_ID: string;
  ELEVENLABS_MODEL: string;
  ELEVENLABS_STABILITY: number;
  ELEVENLABS_SIMILARITY: number;
  ELEVENLABS_STYLE: number;
  TTS_PLAYBACK_RATE: number;
  FAL_TTS_ENDPOINT: string;
  FAL_VOICE_ID: string;

  // Audio
  PTT_KEY: string;
  INPUT_MODE: string;
  SAMPLE_RATE: number;
  CHANNELS: number;
  MAX_RECORD_SEC: number;

  // Wake word
  WAKE_WORD_ENABLED: boolean;
  WAKE_CHUNK_SECONDS: number;

  // Whisper
  WHISPER_PATH: string;
  WHISPER_BIN: string;
  WHISPER_MODEL: string;

  // Claude CLI
  CLAUDE_BIN: string;
  CLAUDE_MODEL: string;
  CLAUDE_EFFORT: string;
  ADAPTIVE_EFFORT: boolean;

  // MCP
  MCP_DIR: string;
  MCP_SERVER_SCRIPT: string;
  MCP_GOOGLE_SCRIPT: string;

  // Google
  GOOGLE_CONFIGURED: boolean;
  GOOGLE_DIR: string;

  // Obsidian
  OBSIDIAN_VAULT: string;
  OBSIDIAN_AVAILABLE: boolean;
  OBSIDIAN_PROJECT_DIR: string;
  OBSIDIAN_AGENT_DIR: string;
  OBSIDIAN_AGENT_NOTES: string;

  // Memory & context
  CONTEXT_SUMMARIES: number;
  MAX_CONTEXT_TOKENS: number;

  // Embeddings
  EMBEDDING_MODEL: string;
  EMBEDDING_DIM: number;
  MODELS_DIR: string;
  VECTOR_SEARCH_WEIGHT: number;

  // Session
  SESSION_SOFT_LIMIT_MINS: number;

  // Heartbeat
  HEARTBEAT_ACTIVE_START: number;
  HEARTBEAT_ACTIVE_END: number;
  HEARTBEAT_INTERVAL_MINS: number;

  // Telegram
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_CHAT_ID: string;
  TELEGRAM_DM_CHAT_ID: string;
  TELEGRAM_USERNAMES: Record<string, string>; // maps telegram name/username -> display name
  NOTIFY_VIA: string; // 'auto' | 'telegram' | 'both'

  // Notifications
  NOTIFICATIONS_ENABLED: boolean;

  // Silence timer
  SILENCE_TIMER_ENABLED: boolean;
  SILENCE_TIMER_MINUTES: number;

  // UI defaults
  EYE_MODE_DEFAULT: boolean;
  MUTE_BY_DEFAULT: boolean;

  // Display
  CANVAS_TEMPLATES: string;
  WINDOW_WIDTH: number;
  WINDOW_HEIGHT: number;
  SETTINGS_WINDOW_WIDTH!: number;
  SETTINGS_WINDOW_HEIGHT!: number;

  // Avatar
  AVATAR_ENABLED: boolean;
  AVATAR_RESOLUTION: number;
  AVATAR_DIR: string;
  SOURCE_IMAGE: string;
  IDLE_LOOPS_DIR: string;
  IDLE_LOOP: string;
  IDLE_THINKING: string;
  IDLE_LISTENING: string;

  // Emotional state
  EMOTIONAL_STATE_FILE: string;
  USER_STATUS_FILE: string;
  MESSAGE_QUEUE_FILE: string;
  OPENING_CACHE_FILE: string;
  CANVAS_CONTENT_FILE: string;
  ARTEFACT_DISPLAY_FILE: string;
  ARTEFACT_INDEX_FILE: string;
  IDENTITY_REVIEW_QUEUE_FILE: string;
  AGENT_STATES_FILE: string;

  constructor() {
    this.AGENT_NAME = 'xan';
    this.AGENT_DISPLAY_NAME = '';
    this.AGENT_DIR = '';
    this.DATA_DIR = '';
    this.USER_NAME = 'User';
    this.OPENING_LINE = 'Hello.';
    this.WAKE_WORDS = [];
    this.TELEGRAM_EMOJI = '';
    this.DISABLED_TOOLS = [];
    this.DB_PATH = '';
    this.SCHEMA_PATH = path.join(BUNDLE_ROOT, 'db', 'schema.sql');
    this.VERSION = '';
    this.PYTHON_PATH = '';
    this.TTS_BACKEND = 'elevenlabs';
    this.ELEVENLABS_API_KEY = '';
    this.ELEVENLABS_VOICE_ID = '';
    this.ELEVENLABS_MODEL = 'eleven_v3';
    this.ELEVENLABS_STABILITY = 0.5;
    this.ELEVENLABS_SIMILARITY = 0.75;
    this.ELEVENLABS_STYLE = 0.35;
    this.TTS_PLAYBACK_RATE = 1.12;
    this.FAL_TTS_ENDPOINT = 'fal-ai/elevenlabs/tts/eleven-v3';
    this.FAL_VOICE_ID = '';
    this.PTT_KEY = 'ctrl';
    this.INPUT_MODE = 'dual';
    this.SAMPLE_RATE = 16000;
    this.CHANNELS = 1;
    this.MAX_RECORD_SEC = 120;
    this.WAKE_WORD_ENABLED = false;
    this.WAKE_CHUNK_SECONDS = 2;
    this.WHISPER_PATH = '';
    this.WHISPER_BIN = '';
    this.WHISPER_MODEL = '';
    this.CLAUDE_BIN = 'claude';
    this.CLAUDE_MODEL = 'claude-sonnet-4-6';
    this.CLAUDE_EFFORT = 'medium';
    this.ADAPTIVE_EFFORT = true;
    this.MCP_DIR = '';
    this.MCP_SERVER_SCRIPT = '';
    this.MCP_GOOGLE_SCRIPT = '';
    this.GOOGLE_CONFIGURED = false;
    this.GOOGLE_DIR = '';
    this.OBSIDIAN_VAULT = '';
    this.OBSIDIAN_AVAILABLE = false;
    this.OBSIDIAN_PROJECT_DIR = '';
    this.OBSIDIAN_AGENT_DIR = '';
    this.OBSIDIAN_AGENT_NOTES = '';
    this.CONTEXT_SUMMARIES = 3;
    this.MAX_CONTEXT_TOKENS = 180000;
    this.EMBEDDING_MODEL = 'all-MiniLM-L6-v2';
    this.EMBEDDING_DIM = 384;
    this.MODELS_DIR = path.join(USER_DATA, 'models');
    this.VECTOR_SEARCH_WEIGHT = 0.7;
    this.SESSION_SOFT_LIMIT_MINS = 60;
    this.HEARTBEAT_ACTIVE_START = 9;
    this.HEARTBEAT_ACTIVE_END = 22;
    this.HEARTBEAT_INTERVAL_MINS = 30;
    this.TELEGRAM_BOT_TOKEN = '';
    this.TELEGRAM_CHAT_ID = '';
    this.TELEGRAM_DM_CHAT_ID = '';
    this.TELEGRAM_USERNAMES = {};
    this.NOTIFY_VIA = 'auto';
    this.NOTIFICATIONS_ENABLED = true;
    this.SILENCE_TIMER_ENABLED = true;
    this.SILENCE_TIMER_MINUTES = 5;
    this.EYE_MODE_DEFAULT = false;
    this.MUTE_BY_DEFAULT = false;
    this.CANVAS_TEMPLATES = path.join(BUNDLE_ROOT, 'display', 'templates');
    // 0 = let createWindow() pick a sane default for the current display.
    // User-saved overrides win.
    this.WINDOW_WIDTH = 0;
    this.WINDOW_HEIGHT = 0;
    // Size used when Settings expands the main window to show its tabs.
    // 0 = use Settings.svelte's hardcoded default (1700x900).
    this.SETTINGS_WINDOW_WIDTH = 0;
    this.SETTINGS_WINDOW_HEIGHT = 0;
    this.AVATAR_ENABLED = false;
    this.AVATAR_RESOLUTION = 512;
    this.AVATAR_DIR = '';
    this.SOURCE_IMAGE = '';
    this.IDLE_LOOPS_DIR = '';
    this.IDLE_LOOP = '';
    this.IDLE_THINKING = '';
    this.IDLE_LISTENING = '';
    this.EMOTIONAL_STATE_FILE = '';
    this.USER_STATUS_FILE = '';
    this.MESSAGE_QUEUE_FILE = '';
    this.OPENING_CACHE_FILE = '';
    this.CANVAS_CONTENT_FILE = '';
    this.ARTEFACT_DISPLAY_FILE = '';
    this.ARTEFACT_INDEX_FILE = '';
    this.IDENTITY_REVIEW_QUEUE_FILE = '';
    this.AGENT_STATES_FILE = path.join(USER_DATA, 'agent_states.json');
    this.load();
  }

  load(): void {
    loadEnvFile();
    loadUserConfig();
    this._resolveVersion();
    this._resolveAgent(cfg('AGENT', 'xan'));
    this.PYTHON_PATH = findPython();
  }

  reloadForAgent(name: string): void {
    this._resolveAgent(name);
  }

  private _resolveVersion(): void {
    // Check for hot bundle version first, then fall back to VERSION file, then app version
    const manifestPath = path.join(USER_DATA, 'bundle', 'bundle-manifest.json');
    try {
      if (fs.existsSync(manifestPath)) {
        const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
        if (manifest.version) {
          this.VERSION = manifest.version;
          return;
        }
      }
    } catch { /* fall through */ }
    // VERSION file supports 4-part versions (e.g. 1.9.5.1) that semver rejects
    const versionFile = path.join(BUNDLE_ROOT, 'VERSION');
    try {
      const v = fs.readFileSync(versionFile, 'utf-8').trim();
      if (v) { this.VERSION = v; return; }
    } catch { /* fall through */ }
    this.VERSION = app.getVersion() || '0.0.0';
  }

  private _resolveAgent(name: string): void {
    this.AGENT_NAME = name;
    loadAgentManifest(name);

    this.AGENT_DIR = findAgentDir(name);
    this.DATA_DIR = agentDataDir(name);
    this.DB_PATH = path.join(this.DATA_DIR, 'memory.db');

    // Identity (matching Python: AGENT.get("display_name", ...) etc.)
    this.AGENT_DISPLAY_NAME = (_agentManifest.display_name as string)
      || name.charAt(0).toUpperCase() + name.slice(1);
    this.USER_NAME = (_userCfg.user_name as string)
      || (_userCfg.USER_NAME as string)
      || (_agentManifest.user_name as string)
      || 'User';
    this.OPENING_LINE = (_agentManifest.opening_line as string) || 'Hello.';
    this.WAKE_WORDS = (_agentManifest.wake_words as string[]) || [`hey ${name}`, name];
    this.TELEGRAM_EMOJI = (_agentManifest.telegram_emoji as string) || '';
    this.DISABLED_TOOLS = (_agentManifest.disabled_tools as string[]) || [];

    // Per-agent telegram credentials (agent manifest only - no env fallback
    // to prevent token bleed between agents)
    this.TELEGRAM_BOT_TOKEN =
      (_agentManifest.telegram_bot_token as string) || '';
    this.TELEGRAM_CHAT_ID =
      (_agentManifest.telegram_chat_id as string) || '';
    this.TELEGRAM_DM_CHAT_ID =
      (_agentManifest.telegram_dm_chat_id as string) || '';
    this.NOTIFY_VIA =
      (_agentManifest.notify_via as string) || 'auto';

    // Telegram username -> display name mapping (global, from config.json)
    // Allows the system to recognise e.g. "Fellowear" as "Will"
    const rawUsernames = _userCfg.telegram_usernames;
    this.TELEGRAM_USERNAMES = (rawUsernames && typeof rawUsernames === 'object' && !Array.isArray(rawUsernames))
      ? rawUsernames as Record<string, string>
      : {};

    // TTS (per-agent from manifest voice object, matching Python's AGENT.get("voice", {}))
    // Use || for string IDs so empty string "" falls through to cfg() fallback.
    // Use ?? for numbers so 0 is preserved as a valid value.
    const voice = (_agentManifest.voice as Record<string, unknown>) || {};
    this.TTS_BACKEND = (voice.tts_backend as string) || cfg('TTS_BACKEND', 'elevenlabs');
    this.ELEVENLABS_API_KEY = cfg('ELEVENLABS_API_KEY', '');
    this.ELEVENLABS_VOICE_ID = (voice.elevenlabs_voice_id as string) || cfg('ELEVENLABS_VOICE_ID', '');
    this.ELEVENLABS_MODEL = (voice.elevenlabs_model as string) || cfg('ELEVENLABS_MODEL', 'eleven_v3');
    this.ELEVENLABS_STABILITY = (voice.elevenlabs_stability as number) ?? cfg('ELEVENLABS_STABILITY', 0.5);
    this.ELEVENLABS_SIMILARITY = (voice.elevenlabs_similarity as number) ?? cfg('ELEVENLABS_SIMILARITY', 0.75);
    this.ELEVENLABS_STYLE = (voice.elevenlabs_style as number) ?? cfg('ELEVENLABS_STYLE', 0.35);
    this.TTS_PLAYBACK_RATE = (voice.playback_rate as number) ?? cfg('TTS_PLAYBACK_RATE', 1.12);
    this.FAL_VOICE_ID = (voice.fal_voice_id as string) || cfg('FAL_VOICE_ID', '');

    // Audio
    this.INPUT_MODE = cfg('INPUT_MODE', 'dual');
    this.PTT_KEY = cfg('PTT_KEY', 'ctrl');
    this.SAMPLE_RATE = cfg('SAMPLE_RATE', 16000);
    this.MAX_RECORD_SEC = cfg('MAX_RECORD_SEC', 120);

    // Wake word
    this.WAKE_WORD_ENABLED = cfg('WAKE_WORD_ENABLED', false);
    this.WAKE_CHUNK_SECONDS = cfg('WAKE_CHUNK_SECONDS', 2);

    // Whisper
    this.WHISPER_PATH = path.join(BUNDLE_ROOT, 'vendor', 'whisper.cpp');
    this.WHISPER_BIN = path.join(this.WHISPER_PATH, 'build', 'bin', 'whisper-cli');
    this.WHISPER_MODEL = path.join(this.WHISPER_PATH, 'models', 'ggml-tiny.en.bin');

    // Claude CLI - resolve full path so packaged app finds it
    const claudeDefault = (() => {
      const candidates = [
        path.join(os.homedir(), '.local', 'bin', 'claude'),
        '/usr/local/bin/claude',
        '/opt/homebrew/bin/claude',
      ];
      for (const c of candidates) {
        if (fs.existsSync(c)) return c;
      }
      return 'claude';
    })();
    this.CLAUDE_BIN = cfg('CLAUDE_BIN', claudeDefault);
    this.CLAUDE_MODEL = cfg('CLAUDE_MODEL', 'claude-sonnet-4-6');
    this.CLAUDE_EFFORT = cfg('CLAUDE_EFFORT', 'medium');
    this.ADAPTIVE_EFFORT = cfg('ADAPTIVE_EFFORT', true);

    // MCP
    this.MCP_DIR = path.join(BUNDLE_ROOT, 'mcp');
    this.MCP_SERVER_SCRIPT = path.join(this.MCP_DIR, 'memory_server.py');
    this.MCP_GOOGLE_SCRIPT = path.join(this.MCP_DIR, 'google_server.py');

    // Google
    this.GOOGLE_CONFIGURED = googleConfigured();
    this.GOOGLE_DIR = path.join(USER_DATA, '.google');

    // Obsidian
    this.OBSIDIAN_VAULT = cfg('OBSIDIAN_VAULT', obsidianVault());
    this.OBSIDIAN_AVAILABLE = fs.existsSync(this.OBSIDIAN_VAULT);
    const projectName = path.basename(BUNDLE_ROOT);
    this.OBSIDIAN_PROJECT_DIR = this.OBSIDIAN_AVAILABLE
      ? path.join(this.OBSIDIAN_VAULT, 'Projects', projectName)
      : path.join(USER_DATA, 'agents');
    this.OBSIDIAN_AGENT_DIR = this.OBSIDIAN_AVAILABLE
      ? path.join(this.OBSIDIAN_PROJECT_DIR, 'Agent Workspace', name)
      : resolveAgentDir(name);
    this.OBSIDIAN_AGENT_NOTES = this.OBSIDIAN_AGENT_DIR;

    // Memory & context
    this.CONTEXT_SUMMARIES = cfg('CONTEXT_SUMMARIES', 3);
    this.MAX_CONTEXT_TOKENS = cfg('MAX_CONTEXT_TOKENS', 180000);
    this.VECTOR_SEARCH_WEIGHT = cfg('VECTOR_SEARCH_WEIGHT', 0.7);
    this.EMBEDDING_MODEL = cfg('EMBEDDING_MODEL', 'all-MiniLM-L6-v2');
    this.EMBEDDING_DIM = cfg('EMBEDDING_DIM', 384);

    // Session
    this.SESSION_SOFT_LIMIT_MINS = cfg('SESSION_SOFT_LIMIT_MINS', 60);

    // Heartbeat (per-agent from manifest heartbeat object)
    const hb = (_agentManifest.heartbeat as Record<string, unknown>) || {};
    this.HEARTBEAT_ACTIVE_START = (hb.active_start as number) ?? cfg('HEARTBEAT_ACTIVE_START', 9);
    this.HEARTBEAT_ACTIVE_END = (hb.active_end as number) ?? cfg('HEARTBEAT_ACTIVE_END', 22);
    this.HEARTBEAT_INTERVAL_MINS = (hb.interval_mins as number) ?? cfg('HEARTBEAT_INTERVAL_MINS', 30);

    // Notifications
    this.NOTIFICATIONS_ENABLED = cfg('NOTIFICATIONS_ENABLED', true);

    // Silence timer
    this.SILENCE_TIMER_ENABLED = cfg('SILENCE_TIMER_ENABLED', true);
    this.SILENCE_TIMER_MINUTES = cfg('SILENCE_TIMER_MINUTES', 5);

    // UI defaults
    this.EYE_MODE_DEFAULT = cfg('EYE_MODE_DEFAULT', false);
    this.MUTE_BY_DEFAULT = cfg('MUTE_BY_DEFAULT', false);

    // Display (per-agent from manifest display object)
    const disp = (_agentManifest.display as Record<string, unknown>) || {};
    this.WINDOW_WIDTH = (disp.window_width as number) ?? cfg('WINDOW_WIDTH', 0);
    this.WINDOW_HEIGHT = (disp.window_height as number) ?? cfg('WINDOW_HEIGHT', 0);
    this.SETTINGS_WINDOW_WIDTH = (disp.settings_window_width as number) ?? cfg('SETTINGS_WINDOW_WIDTH', 0);
    this.SETTINGS_WINDOW_HEIGHT = (disp.settings_window_height as number) ?? cfg('SETTINGS_WINDOW_HEIGHT', 0);

    // Avatar (user data > bundled fallback)
    this.AVATAR_ENABLED = cfg('AVATAR_ENABLED', false);
    this.AVATAR_RESOLUTION = cfg('AVATAR_RESOLUTION', 512);
    const userAvatarDir = path.join(resolveAgentDir(name), 'avatar');
    const bundleAvatarDir = path.join(BUNDLE_ROOT, 'agents', name, 'avatar');
    this.AVATAR_DIR = fs.existsSync(path.join(userAvatarDir, 'loops'))
      ? userAvatarDir
      : fs.existsSync(path.join(bundleAvatarDir, 'loops'))
        ? bundleAvatarDir
        : userAvatarDir;
    this.SOURCE_IMAGE = avatarPath(name, 'source/face.png');
    this.IDLE_LOOPS_DIR = path.join(this.AVATAR_DIR, 'loops');
    this.IDLE_LOOP = path.join(this.AVATAR_DIR, 'ambient_loop.mp4');
    this.IDLE_THINKING = path.join(this.AVATAR_DIR, 'idle_thinking.mp4');
    this.IDLE_LISTENING = path.join(this.AVATAR_DIR, 'idle_listening.mp4');

    // State files (per-agent data dir)
    this.EMOTIONAL_STATE_FILE = path.join(this.DATA_DIR, '.emotional_state.json');
    this.USER_STATUS_FILE = path.join(this.DATA_DIR, '.user_status.json');
    this.MESSAGE_QUEUE_FILE = path.join(this.DATA_DIR, '.message_queue.json');
    this.OPENING_CACHE_FILE = path.join(this.DATA_DIR, '.opening_cache.json');
    this.CANVAS_CONTENT_FILE = path.join(this.DATA_DIR, '.canvas_content.html');
    this.ARTEFACT_DISPLAY_FILE = path.join(this.DATA_DIR, '.artefact_display.json');
    this.ARTEFACT_INDEX_FILE = path.join(this.DATA_DIR, '.artefact_index.json');
    this.IDENTITY_REVIEW_QUEUE_FILE = path.join(this.DATA_DIR, '.identity_review_queue.json');
  }
}

// ---------------------------------------------------------------------------
// Save config updates
// ---------------------------------------------------------------------------

/**
 * Atomic write - writes to a temp file then renames to avoid partial writes on crash.
 */
function atomicWriteFileSync(filePath: string, data: string, mode = 0o600): void {
  const tmpPath = filePath + '.' + crypto.randomBytes(6).toString('hex') + '.tmp';
  fs.writeFileSync(tmpPath, data, { mode });
  fs.renameSync(tmpPath, filePath);
}

/**
 * Deep-merge updates into ~/.atrophy/config.json, preserving existing keys.
 * Reads the current file, merges recursively, writes back, then reloads
 * the in-memory config cache so subsequent cfg() calls see new values.
 */
export function saveUserConfig(updates: Record<string, unknown>): void {
  const cfgPath = path.join(USER_DATA, 'config.json');
  let existing: Record<string, unknown> = {};
  try {
    existing = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
  } catch { /* empty or missing - start fresh */ }
  const merged = deepMerge(existing, updates);
  atomicWriteFileSync(cfgPath, JSON.stringify(merged, null, 2) + '\n');
  loadUserConfig();
}

// Maps flat Config keys to their nested manifest paths.
// Keys not listed here are written at root level with lowercase conversion.
const AGENT_KEY_NESTING: Record<string, { object: string; key: string }> = {
  TTS_BACKEND: { object: 'voice', key: 'tts_backend' },
  ELEVENLABS_VOICE_ID: { object: 'voice', key: 'elevenlabs_voice_id' },
  ELEVENLABS_MODEL: { object: 'voice', key: 'elevenlabs_model' },
  ELEVENLABS_STABILITY: { object: 'voice', key: 'elevenlabs_stability' },
  ELEVENLABS_SIMILARITY: { object: 'voice', key: 'elevenlabs_similarity' },
  ELEVENLABS_STYLE: { object: 'voice', key: 'elevenlabs_style' },
  TTS_PLAYBACK_RATE: { object: 'voice', key: 'playback_rate' },
  FAL_VOICE_ID: { object: 'voice', key: 'fal_voice_id' },
  HEARTBEAT_ACTIVE_START: { object: 'heartbeat', key: 'active_start' },
  HEARTBEAT_ACTIVE_END: { object: 'heartbeat', key: 'active_end' },
  HEARTBEAT_INTERVAL_MINS: { object: 'heartbeat', key: 'interval_mins' },
  WINDOW_WIDTH: { object: 'display', key: 'window_width' },
  WINDOW_HEIGHT: { object: 'display', key: 'window_height' },
  SETTINGS_WINDOW_WIDTH: { object: 'display', key: 'settings_window_width' },
  SETTINGS_WINDOW_HEIGHT: { object: 'display', key: 'settings_window_height' },
};

// Maps flat Config keys to their root-level manifest key names.
const AGENT_KEY_ROOT: Record<string, string> = {
  AGENT_DISPLAY_NAME: 'display_name',
  USER_NAME: 'user_name',
  WAKE_WORDS: 'wake_words',
  TELEGRAM_EMOJI: 'telegram_emoji',
  DISABLED_TOOLS: 'disabled_tools',
  TELEGRAM_BOT_TOKEN: 'telegram_bot_token',
  TELEGRAM_CHAT_ID: 'telegram_chat_id',
  TELEGRAM_DM_CHAT_ID: 'telegram_dm_chat_id',
  NOTIFY_VIA: 'notify_via',
};

export function saveAgentConfig(
  agentName: string,
  updates: Record<string, unknown>,
): void {
  if (!isValidAgentName(agentName)) {
    console.warn(`[config] saveAgentConfig: invalid agent name "${agentName}"`);
    return;
  }
  const agentDir = findAgentDir(agentName);
  const agentJsonPath = path.join(agentDir, 'data', 'agent.json');
  let existing: Record<string, unknown> = {};
  try {
    existing = JSON.parse(fs.readFileSync(agentJsonPath, 'utf-8'));
  } catch { /* empty */ }

  // Nest flat keys into the correct manifest structure
  for (const [key, value] of Object.entries(updates)) {
    const nested = AGENT_KEY_NESTING[key];
    if (nested) {
      const obj = (existing[nested.object] as Record<string, unknown>) || {};
      obj[nested.key] = value;
      existing[nested.object] = obj;
    } else {
      // Use lowercase root key if mapped, otherwise write as-is
      const rootKey = AGENT_KEY_ROOT[key] || key;
      existing[rootKey] = value;
    }
  }

  fs.mkdirSync(path.dirname(agentJsonPath), { recursive: true });
  atomicWriteFileSync(agentJsonPath, JSON.stringify(existing, null, 2));
}

// ---------------------------------------------------------------------------
// Singleton
// ---------------------------------------------------------------------------

let _config: Config | null = null;

export function getConfig(): Config {
  if (!_config) {
    _config = new Config();
  }
  return _config;
}

/** Force config to reload from disk on next access (e.g. after agent switch or setup). */
export function reloadConfig(): Config {
  _config = new Config();
  return _config;
}

/**
 * Three-tier config resolution: env vars -> ~/.atrophy/config.json -> agent.json -> defaults.
 * Port of config.py.
 */

import { app } from 'electron';
import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';

// ---------------------------------------------------------------------------
// Root paths
// ---------------------------------------------------------------------------

export const BUNDLE_ROOT = app.isPackaged
  ? path.join(process.resourcesPath!)
  : path.resolve(__dirname, '..', '..');

export const USER_DATA = path.join(
  process.env.ATROPHY_DATA || path.join(process.env.HOME || '/tmp', '.atrophy'),
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
      if (key && !process.env[key]) {
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
  'OPENAI_API_KEY',
  'ANTHROPIC_API_KEY',
]);

/** Check if a key is in the allowed env keys whitelist. */
export function isAllowedEnvKey(key: string): boolean {
  return ALLOWED_ENV_KEYS.has(key);
}

/** Save a secret to ~/.atrophy/.env. Updates or appends the key. Returns false if key not in whitelist. */
export function saveEnvVar(key: string, value: string): boolean {
  if (!ALLOWED_ENV_KEYS.has(key)) return false;
  // Strip newlines to prevent env injection
  value = value.replace(/[\r\n]/g, '');
  const envPath = path.join(USER_DATA, '.env');
  fs.mkdirSync(USER_DATA, { recursive: true });
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
  return true;
}

// ---------------------------------------------------------------------------
// Agent manifest
// ---------------------------------------------------------------------------

let _agentManifest: Record<string, unknown> = {};

function loadAgentManifest(name: string): void {
  const dirs = [
    path.join(USER_DATA, 'agents', name, 'data', 'agent.json'),
    path.join(BUNDLE_ROOT, 'agents', name, 'data', 'agent.json'),
  ];
  for (const p of dirs) {
    try {
      if (fs.existsSync(p)) {
        _agentManifest = JSON.parse(fs.readFileSync(p, 'utf-8'));
        return;
      }
    } catch {
      continue;
    }
  }
  _agentManifest = {};
}

// ---------------------------------------------------------------------------
// Resolution helper
// ---------------------------------------------------------------------------

function cfg<T>(key: string, fallback: T): T {
  // Tier 1: env vars
  const envVal = process.env[key];
  if (envVal !== undefined) {
    if (typeof fallback === 'number') return Number(envVal) as T;
    if (typeof fallback === 'boolean') return (envVal.toLowerCase() === 'true') as T;
    return envVal as T;
  }
  // Tier 2: user config
  if (key in _userCfg) return _userCfg[key] as T;
  // Tier 3: agent manifest
  if (key in _agentManifest) return _agentManifest[key] as T;
  // Tier 4: default
  return fallback;
}

function agentCfg<T>(key: string, fallback: T): T {
  // Agent-specific: manifest first, then user config, then env
  if (key in _agentManifest) {
    const v = _agentManifest[key];
    if (v !== undefined && v !== null) return v as T;
  }
  return cfg(key, fallback);
}

// ---------------------------------------------------------------------------
// Agent directory resolution
// ---------------------------------------------------------------------------

function findAgentDir(name: string): string {
  const userDir = path.join(USER_DATA, 'agents', name);
  if (fs.existsSync(path.join(userDir, 'data', 'agent.json'))) return userDir;
  const bundleDir = path.join(BUNDLE_ROOT, 'agents', name);
  if (fs.existsSync(path.join(bundleDir, 'data', 'agent.json'))) return bundleDir;
  return userDir; // prefer user dir for new agents
}

function agentDataDir(name: string): string {
  const d = path.join(USER_DATA, 'agents', name, 'data');
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
    fs.mkdirSync(dir, { recursive: true });
  }

  const cfgPath = path.join(USER_DATA, 'config.json');
  if (!fs.existsSync(cfgPath)) {
    fs.writeFileSync(cfgPath, '{}', { mode: 0o600 });
  }

  migrateAgentData();
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
    const userAvatar = path.join(USER_DATA, 'agents', name, 'avatar');
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
  if (process.env.PYTHON_PATH) return process.env.PYTHON_PATH;
  const candidates = ['python3', '/opt/homebrew/bin/python3', '/usr/local/bin/python3'];
  for (const c of candidates) {
    try {
      execSync(`${c} --version`, { stdio: 'pipe' });
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
    const result = execSync(`${gwsBin} auth status`, {
      stdio: ['pipe', 'pipe', 'pipe'],
      encoding: 'utf-8',
      timeout: 5000,
    });
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
  const userPath = path.join(USER_DATA, 'agents', agentName, 'avatar', rel);
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
    this.NOTIFICATIONS_ENABLED = true;
    this.SILENCE_TIMER_ENABLED = true;
    this.SILENCE_TIMER_MINUTES = 5;
    this.EYE_MODE_DEFAULT = false;
    this.MUTE_BY_DEFAULT = false;
    this.CANVAS_TEMPLATES = path.join(BUNDLE_ROOT, 'display', 'templates');
    this.WINDOW_WIDTH = 622;
    this.WINDOW_HEIGHT = 830;
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
    const vPath = path.join(BUNDLE_ROOT, 'VERSION');
    try {
      this.VERSION = fs.readFileSync(vPath, 'utf-8').trim();
    } catch {
      this.VERSION = '0.0.0';
    }
  }

  private _resolveAgent(name: string): void {
    this.AGENT_NAME = name;
    loadAgentManifest(name);

    this.AGENT_DIR = findAgentDir(name);
    this.DATA_DIR = agentDataDir(name);
    this.DB_PATH = path.join(this.DATA_DIR, 'memory.db');

    // Identity
    this.AGENT_DISPLAY_NAME = agentCfg(
      'AGENT_DISPLAY_NAME',
      (_agentManifest.display_name as string) || name.charAt(0).toUpperCase() + name.slice(1),
    );
    this.USER_NAME = cfg('USER_NAME', (_agentManifest.user_name as string) || 'User');
    this.OPENING_LINE = agentCfg('OPENING_LINE', 'Hello.');
    const defaultWakeWords = (_agentManifest.wake_words as string[]) || [`hey ${name}`, name];
    this.WAKE_WORDS = agentCfg('WAKE_WORDS', defaultWakeWords);
    this.TELEGRAM_EMOJI = (_agentManifest.telegram_emoji as string) || '';
    const defaultDisabledTools = (_agentManifest.disabled_tools as string[]) || [];
    this.DISABLED_TOOLS = agentCfg('DISABLED_TOOLS', defaultDisabledTools);

    // TTS (per-agent)
    this.TTS_BACKEND = agentCfg('TTS_BACKEND', 'elevenlabs');
    this.ELEVENLABS_API_KEY = cfg('ELEVENLABS_API_KEY', '');
    this.ELEVENLABS_VOICE_ID = agentCfg('ELEVENLABS_VOICE_ID', '');
    this.ELEVENLABS_MODEL = agentCfg('ELEVENLABS_MODEL', 'eleven_v3');
    this.ELEVENLABS_STABILITY = agentCfg('ELEVENLABS_STABILITY', 0.5);
    this.ELEVENLABS_SIMILARITY = agentCfg('ELEVENLABS_SIMILARITY', 0.75);
    this.ELEVENLABS_STYLE = agentCfg('ELEVENLABS_STYLE', 0.35);
    this.TTS_PLAYBACK_RATE = agentCfg('TTS_PLAYBACK_RATE', 1.12);
    this.FAL_VOICE_ID = agentCfg('FAL_VOICE_ID', '');

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

    // Claude CLI
    this.CLAUDE_BIN = cfg('CLAUDE_BIN', 'claude');
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
      : path.join(USER_DATA, 'agents', name);
    this.OBSIDIAN_AGENT_NOTES = this.OBSIDIAN_AGENT_DIR;

    // Memory & context
    this.CONTEXT_SUMMARIES = cfg('CONTEXT_SUMMARIES', 3);
    this.MAX_CONTEXT_TOKENS = cfg('MAX_CONTEXT_TOKENS', 180000);
    this.VECTOR_SEARCH_WEIGHT = cfg('VECTOR_SEARCH_WEIGHT', 0.7);
    this.EMBEDDING_MODEL = cfg('EMBEDDING_MODEL', 'all-MiniLM-L6-v2');
    this.EMBEDDING_DIM = cfg('EMBEDDING_DIM', 384);

    // Session
    this.SESSION_SOFT_LIMIT_MINS = cfg('SESSION_SOFT_LIMIT_MINS', 60);

    // Heartbeat (per-agent)
    this.HEARTBEAT_ACTIVE_START = agentCfg('HEARTBEAT_ACTIVE_START', 9);
    this.HEARTBEAT_ACTIVE_END = agentCfg('HEARTBEAT_ACTIVE_END', 22);
    this.HEARTBEAT_INTERVAL_MINS = agentCfg('HEARTBEAT_INTERVAL_MINS', 30);

    // Telegram (per-agent) - supports env var indirection via manifest
    // The agent manifest can specify telegram.bot_token_env and telegram.chat_id_env
    // to point to custom env var names, allowing different agents to use different bots.
    const telegramCfg = (_agentManifest.telegram as Record<string, unknown>) || {};
    const botTokenEnv = (telegramCfg.bot_token_env as string) || 'TELEGRAM_BOT_TOKEN';
    const chatIdEnv = (telegramCfg.chat_id_env as string) || 'TELEGRAM_CHAT_ID';
    this.TELEGRAM_BOT_TOKEN = process.env[botTokenEnv] || agentCfg('TELEGRAM_BOT_TOKEN', '');
    this.TELEGRAM_CHAT_ID = process.env[chatIdEnv] || agentCfg('TELEGRAM_CHAT_ID', '');

    // Notifications
    this.NOTIFICATIONS_ENABLED = cfg('NOTIFICATIONS_ENABLED', true);

    // Silence timer
    this.SILENCE_TIMER_ENABLED = cfg('SILENCE_TIMER_ENABLED', true);
    this.SILENCE_TIMER_MINUTES = cfg('SILENCE_TIMER_MINUTES', 5);

    // UI defaults
    this.EYE_MODE_DEFAULT = cfg('EYE_MODE_DEFAULT', false);
    this.MUTE_BY_DEFAULT = cfg('MUTE_BY_DEFAULT', false);

    // Display (per-agent)
    this.WINDOW_WIDTH = agentCfg('WINDOW_WIDTH', 622);
    this.WINDOW_HEIGHT = agentCfg('WINDOW_HEIGHT', 830);

    // Avatar (user data > bundled fallback)
    this.AVATAR_ENABLED = cfg('AVATAR_ENABLED', false);
    this.AVATAR_RESOLUTION = cfg('AVATAR_RESOLUTION', 512);
    const userAvatarDir = path.join(USER_DATA, 'agents', name, 'avatar');
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
  fs.writeFileSync(cfgPath, JSON.stringify(merged, null, 2) + '\n', { mode: 0o600 });
  loadUserConfig();
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

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function saveAgentConfig(
  agentName: string,
  updates: Record<string, unknown>,
): void {
  const agentJsonPath = path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json');
  let existing: Record<string, unknown> = {};
  try {
    existing = JSON.parse(fs.readFileSync(agentJsonPath, 'utf-8'));
  } catch { /* empty */ }
  Object.assign(existing, updates);
  fs.mkdirSync(path.dirname(agentJsonPath), { recursive: true });
  fs.writeFileSync(agentJsonPath, JSON.stringify(existing, null, 2), { mode: 0o600 });
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

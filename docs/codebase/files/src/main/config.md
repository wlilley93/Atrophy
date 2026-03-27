# src/main/config.ts - Configuration System

**Dependencies:** Electron, Node.js built-ins (`fs`, `path`, `os`, `child_process`, `crypto`)  
**Purpose:** Three-tier configuration resolution, path management, agent manifest loading, secrets management

## Overview

This module implements the foundation of the entire application's configuration system. Every other module depends on it for accessing settings, paths, and agent-specific configuration. The design uses a three-tier resolution scheme that allows deployment-level overrides to take precedence over user preferences, which in turn take precedence over per-agent defaults.

## Three-Tier Resolution

Configuration is resolved in order from highest to lowest priority:

```
1. Environment variables (highest priority - deployment overrides)
2. ~/.atrophy/config.json (user preferences)
3. agents/<name>/data/agent.json (per-agent defaults)
4. Hardcoded defaults (lowest priority)
```

This design enables:
- **Deployment overrides**: Set `ELEVENLABS_API_KEY` in env for CI/testing
- **User preferences**: Set global defaults in `config.json`
- **Agent-specific settings**: Each agent has its own voice, display name, etc.
- **Sensible defaults**: App works out of the box with minimal configuration

## Root Paths

Two constants establish the root paths that the entire application uses:

```typescript
export const BUNDLE_ROOT = app.isPackaged
  ? path.join(process.resourcesPath!)
  : path.resolve(__dirname, '..', '..');

export const USER_DATA = path.join(
  process.env.ATROPHY_DATA || path.join(os.homedir(), '.atrophy'),
);
```

| Constant | Development | Production | Override |
|----------|-------------|-----------|----------|
| `BUNDLE_ROOT` | Project root (`/path/to/project/`) | `Contents/Resources/` in .app bundle | None |
| `USER_DATA` | `~/.atrophy/` | `~/.atrophy/` | `ATROPHY_DATA` env var |

**Why this matters:** All file paths in the application derive from these two roots. The dual-path resolution ensures the same code works in development and production without path changes.

## Environment File Loading

Secrets (API keys, tokens) are stored in `~/.atrophy/.env`, separate from `config.json`:

```typescript
function loadEnvFile(): void {
  const envPath = path.join(USER_DATA, '.env');
  if (!fs.existsSync(envPath)) return;
  
  const content = fs.readFileSync(envPath, 'utf-8');
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eqIdx = trimmed.indexOf('=');
    if (eqIdx === -1) continue;
    const key = trimmed.slice(0, eqIdx).trim();
    let val = trimmed.slice(eqIdx + 1).trim();
    
    // Strip surrounding quotes
    if ((val.startsWith('"') && val.endsWith('"')) || 
        (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    
    // Only load whitelisted keys and reject dangerous env overrides
    const DANGEROUS_KEYS = new Set([
      'NODE_OPTIONS', 'ELECTRON_RUN_AS_NODE', 'LD_PRELOAD',
      'DYLD_INSERT_LIBRARIES', 'PATH', 'HOME',
    ]);
    if (key && !process.env[key] && !DANGEROUS_KEYS.has(key)) {
      process.env[key] = val;
    }
  }
}
```

### Security Features

**Dangerous key whitelist:** Certain environment variables are explicitly blocked to prevent privilege escalation:
- `NODE_OPTIONS`: Could load malicious modules
- `ELECTRON_RUN_AS_NODE`: Could bypass Electron security
- `LD_PRELOAD`/`DYLD_INSERT_LIBRARIES`: Could inject shared libraries
- `PATH`/`HOME`: Could redirect file access

**Only set if not already defined:** The check `!process.env[key]` ensures environment variables take precedence over `.env` file values. This allows users to override secrets at runtime for testing.

### Allowed Secret Keys

```typescript
const ALLOWED_ENV_KEYS = new Set([
  'ELEVENLABS_API_KEY',
  'FAL_KEY',
  'TELEGRAM_BOT_TOKEN',
  'TELEGRAM_CHAT_ID',
  'OPENAI_API_KEY',
  'ANTHROPIC_API_KEY',
]);
```

Only these keys can be saved via the settings UI. This prevents accidental exposure of arbitrary environment variables.

### saveEnvVar Function

```typescript
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
  
  process.env[key] = value;
  return true;
}
```

**File permissions:** Written with mode `0o600` (owner read/write only) to protect secrets from other users on the system.

## Deep Merge Implementation

Configuration merging uses a deep merge strategy where plain objects are merged recursively, but arrays and primitives are overwritten:

```typescript
function deepMerge(
  target: Record<string, unknown>,
  source: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...target };
  for (const key of Object.keys(source)) {
    // Prevent prototype pollution
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
    
    const srcVal = source[key];
    const tgtVal = result[key];
    
    if (isPlainObject(srcVal) && isPlainObject(tgtVal)) {
      result[key] = deepMerge(tgtVal as Record<string, unknown>, srcVal as Record<string, unknown>);
    } else {
      result[key] = srcVal;  // Arrays, primitives, null are overwritten
    }
  }
  return result;
}
```

**Prototype pollution prevention:** The check for `__proto__`, `constructor`, and `prototype` prevents malicious JSON from modifying Object.prototype.

## Agent Manifest Loading

Agent manifests are loaded from both bundle and user data, with user overrides taking precedence:

```typescript
function loadAgentManifest(name: string): void {
  if (!isValidAgentName(name)) {
    _agentManifest = {};
    return;
  }
  
  const bundlePath = path.join(BUNDLE_ROOT, 'agents', name, 'data', 'agent.json');
  const userPath = path.join(USER_DATA, 'agents', name, 'data', 'agent.json');

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
```

**Why both paths:** Bundled agents ship with the app. Users can override by placing a modified `agent.json` in `~/.atrophy/agents/<name>/`. The deep merge ensures only changed fields are overridden.

### Agent Name Validation

```typescript
export function isValidAgentName(name: string): boolean {
  return /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(name) && !name.includes('..');
}
```

- Must start with alphanumeric character
- Can contain alphanumeric, hyphens, underscores
- Cannot contain `..` (path traversal prevention)

## Configuration Resolution Helper

The `cfg()` function implements the three-tier resolution:

```typescript
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
  return fallback;
}
```

**Type coercion:** Environment variables are always strings. The function coerces them to match the fallback type:
- Numbers: `Number(envVal)` with NaN fallback
- Booleans: `'true'` (case-insensitive) → `true`
- Everything else: string as-is

**Note:** Agent manifest values are NOT read through `cfg()` - they use direct nested accessors in `_resolveAgent()` because manifests use snake_case nested objects.

## User Data Directory Setup

```typescript
export function ensureUserData(): void {
  // Create directory structure
  for (const dir of [
    USER_DATA,
    path.join(USER_DATA, 'agents'),
    path.join(USER_DATA, 'logs'),
    path.join(USER_DATA, 'models'),
  ]) {
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  }

  // Create empty config.json if missing
  const cfgPath = path.join(USER_DATA, 'config.json');
  if (!fs.existsSync(cfgPath)) {
    fs.writeFileSync(cfgPath, '{}', { mode: 0o600 });
  }

  // Migrate bundled data to user data
  migrateAgentData();
}
```

**Directory permissions:** `0o700` (owner only) for privacy. Config file is `0o600`.

## Data Migration

```typescript
function migrateAgentData(): void {
  // One-time migration: copy runtime data from bundle to ~/.atrophy/
  // Skips agent.json (manifest) and files that already exist
  const bundleAgents = path.join(BUNDLE_ROOT, 'agents');
  if (!fs.existsSync(bundleAgents)) return;

  for (const name of fs.readdirSync(bundleAgents)) {
    const agentDir = path.join(bundleAgents, name);
    if (!fs.statSync(agentDir).isDirectory()) continue;

    // Migrate data/ files (skip agent.json - manifest)
    const bundleData = path.join(agentDir, 'data');
    if (fs.existsSync(bundleData)) {
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

    // Migrate avatar/ tree recursively
    const bundleAvatar = path.join(agentDir, 'avatar');
    const userAvatar = path.join(USER_DATA, 'agents', name, 'avatar');
    if (fs.existsSync(bundleAvatar)) {
      copyTreeIfMissing(bundleAvatar, userAvatar);
    }
  }
}
```

**Why migration exists:** Bundled agents ship with initial data files (empty databases, starter prompts). These are copied to user data on first launch so users can modify them without touching the app bundle.

**Skip existing files:** Users can modify files in `~/.atrophy/`. The migration skips files that already exist, preserving user changes across app updates.

## Python Path Detection

The app needs to find a Python 3 interpreter for MCP servers and background jobs:

```typescript
function findPython(): string {
  // 1. Check PYTHON_PATH env var (user override)
  if (process.env.PYTHON_PATH) {
    const p = process.env.PYTHON_PATH;
    if (/^[a-zA-Z0-9_.\/~-]+$/.test(p)) return p;
  }

  const home = process.env.HOME || '/Users/williamlilley';
  const candidates = [
    // pyenv shim first - delegates to user's active version
    `${home}/.pyenv/shims/python3`,
    '/opt/homebrew/bin/python3',  // Homebrew Apple Silicon
    '/usr/local/bin/python3',     // Homebrew Intel
    'python3',                     // System PATH
  ];

  // Scan pyenv versions directory for concrete interpreters
  try {
    const pyenvDir = `${home}/.pyenv/versions`;
    const versions = readdirSync(pyenvDir)
      .filter((v: string) => statSync(`${pyenvDir}/${v}`).isDirectory())
      .sort()
      .reverse();  // newest first
    for (const v of versions) {
      candidates.push(`${pyenvDir}/${v}/bin/python3`);
    }
  } catch { /* pyenv not installed */ }

  // Try each candidate
  for (const c of candidates) {
    try {
      execFileSync(c, ['--version'], { stdio: 'pipe' });
      return c;
    } catch { continue; }
  }
  return 'python3';  // Fallback - will fail with clear error
}
```

**Search order rationale:**
1. `PYTHON_PATH` env var - user override
2. pyenv shim - delegates to whatever Python version user has active
3. Homebrew paths - most common macOS Python installation
4. System PATH - last resort
5. pyenv versions - concrete interpreters if shim fails

**Validation:** The regex `/^[a-zA-Z0-9_.\/~-]+$/` rejects paths with shell metacharacters to prevent command injection.

## Google Auth Detection

```typescript
function googleConfigured(): boolean {
  // Legacy: custom OAuth tokens
  const legacyToken = path.join(USER_DATA, '.google', 'token.json');
  if (fs.existsSync(legacyToken)) return true;

  // New: gws CLI auth
  let gwsBin: string | null = null;
  try {
    gwsBin = execSync('which gws', { stdio: 'pipe', encoding: 'utf-8' }).trim();
  } catch { return false; }
  
  if (!gwsBin) return false;

  try {
    const result = execFileSync(gwsBin, ['auth', 'status'], {
      stdio: ['pipe', 'pipe', 'pipe'],
      encoding: 'utf-8',
      timeout: 5000,
    }) as string;
    const parsed = JSON.parse(result) as Record<string, unknown>;
    return (parsed.auth_method ?? 'none') !== 'none';
  } catch { return false; }
}
```

**Two-path support:** Legacy token file (from old OAuth flow) OR gws CLI auth status. The gws CLI approach is more robust and handles token refresh automatically.

## Obsidian Vault Detection

```typescript
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
```

**Default path:** macOS default location for Obsidian vault synced via iCloud. Can be overridden via `OBSIDIAN_VAULT` env var or `config.json`.

## Config Class

The `Config` class is a singleton that holds all resolved configuration values. It is constructed once and cached for the process lifetime.

### Properties (Grouped by Category)

**Agent Identity:**
```typescript
AGENT_NAME: string;              // e.g. 'xan'
AGENT_DISPLAY_NAME: string;      // e.g. 'Xan'
AGENT_DIR: string;               // Full path to agent directory
DATA_DIR: string;                // ~/.atrophy/agents/<name>/data/
USER_NAME: string;               // User's name (default 'User')
OPENING_LINE: string;            // First message (default 'Hello.')
WAKE_WORDS: string[];            // ['hey xan', 'xan']
TELEGRAM_EMOJI: string;          // e.g. '🌙'
DISABLED_TOOLS: string[];        // Tools disabled for this agent
```

**Paths:**
```typescript
DB_PATH: string;                 // ~/.atrophy/agents/<name>/data/memory.db
SCHEMA_PATH: string;             // <bundle>/db/schema.sql
VERSION: string;                 // App version (from package.json or hot bundle)
PYTHON_PATH: string;             // Resolved Python interpreter path
```

**TTS Configuration:**
```typescript
TTS_BACKEND: string;             // 'elevenlabs', 'fal', or 'say'
ELEVENLABS_API_KEY: string;      // API key from .env
ELEVENLABS_VOICE_ID: string;     // Voice ID from agent manifest
ELEVENLABS_MODEL: string;        // 'eleven_v3'
ELEVENLABS_STABILITY: number;    // 0.5 (default)
ELEVENLABS_SIMILARITY: number;   // 0.75 (default)
ELEVENLABS_STYLE: number;        // 0.35 (default)
TTS_PLAYBACK_RATE: number;       // 1.12 (default)
FAL_TTS_ENDPOINT: string;        // 'fal-ai/elevenlabs/tts/eleven-v3'
FAL_VOICE_ID: string;            // Fal voice ID
```

**Audio Configuration:**
```typescript
PTT_KEY: string;                 // 'ctrl'
INPUT_MODE: string;              // 'dual', 'text', 'voice'
SAMPLE_RATE: number;             // 16000
CHANNELS: number;                // 1 (mono)
MAX_RECORD_SEC: number;          // 120
```

**Wake Word:**
```typescript
WAKE_WORD_ENABLED: boolean;      // false (default)
WAKE_CHUNK_SECONDS: number;      // 2
```

**Whisper.cpp:**
```typescript
WHISPER_PATH: string;            // <bundle>/vendor/whisper.cpp
WHISPER_BIN: string;             // <whisper_path>/build/bin/whisper-cli
WHISPER_MODEL: string;           // <whisper_path>/models/ggml-tiny.en.bin
```

**Claude CLI:**
```typescript
CLAUDE_BIN: string;              // 'claude' or full path
CLAUDE_MODEL: string;            // 'claude-sonnet-4-6'
CLAUDE_EFFORT: string;           // 'medium'
ADAPTIVE_EFFORT: boolean;        // true
```

**MCP Servers:**
```typescript
MCP_DIR: string;                 // <bundle>/mcp/
MCP_SERVER_SCRIPT: string;       // <bundle>/mcp/memory_server.py
MCP_GOOGLE_SCRIPT: string;       // <bundle>/mcp/google_server.py
GOOGLE_CONFIGURED: boolean;      // Result of googleConfigured()
GOOGLE_DIR: string;              // <bundle>/mcp/google/
```

**Obsidian:**
```typescript
OBSIDIAN_VAULT: string;          // Vault path
OBSIDIAN_AVAILABLE: boolean;     // Whether vault exists
OBSIDIAN_PROJECT_DIR: string;    // Agent's directory in vault
OBSIDIAN_AGENT_DIR: string;      // Full path to agent's Obsidian dir
OBSIDIAN_AGENT_NOTES: string;    // Notes directory
```

**Memory & Context:**
```typescript
CONTEXT_SUMMARIES: number;       // 3 (number of summaries to inject)
MAX_CONTEXT_TOKENS: number;      // 180000
```

**Embeddings:**
```typescript
EMBEDDING_MODEL: string;         // 'all-MiniLM-L6-v2'
EMBEDDING_DIM: number;           // 384
MODELS_DIR: string;              // ~/.atrophy/models/
VECTOR_SEARCH_WEIGHT: number;    // 0.7 (weight for vector vs keyword search)
```

**Session:**
```typescript
SESSION_SOFT_LIMIT_MINS: number; // 60
```

**Heartbeat:**
```typescript
HEARTBEAT_ACTIVE_START: number;  // 9 (9 AM)
HEARTBEAT_ACTIVE_END: number;    // 22 (10 PM)
HEARTBEAT_INTERVAL_MINS: number; // 30
```

**Telegram:**
```typescript
TELEGRAM_BOT_TOKEN: string;      // From agent manifest
TELEGRAM_CHAT_ID: string;        // From agent manifest
TELEGRAM_DM_CHAT_ID: string;     // For DMs (optional)
```

**UI Defaults:**
```typescript
NOTIFICATIONS_ENABLED: boolean;  // true
SILENCE_TIMER_ENABLED: boolean;  // true
SILENCE_TIMER_MINUTES: number;   // 5
EYE_MODE_DEFAULT: boolean;       // false
MUTE_BY_DEFAULT: boolean;        // false
```

**Display:**
```typescript
CANVAS_TEMPLATES: string;        // <bundle>/display/templates
WINDOW_WIDTH: number;            // 622
WINDOW_HEIGHT: number;           // 830
```

**Avatar:**
```typescript
AVATAR_ENABLED: boolean;         // false
AVATAR_RESOLUTION: number;       // 512
AVATAR_DIR: string;              // ~/.atrophy/agents/<name>/avatar/
SOURCE_IMAGE: string;            // <avatar_dir>/source/face.png
IDLE_LOOPS_DIR: string;          // <avatar_dir>/loops/
IDLE_LOOP: string;               // <idle_loops_dir>/ambient_loop.mp4
IDLE_THINKING: string;           // <idle_loops_dir>/thinking.mp4
IDLE_LISTENING: string;          // <idle_loops_dir>/listening.mp4
```

**State Files:**
```typescript
EMOTIONAL_STATE_FILE: string;    // <DATA_DIR>/.emotional_state.json
USER_STATUS_FILE: string;        // <DATA_DIR>/.user_status.json
MESSAGE_QUEUE_FILE: string;      // <DATA_DIR>/.message_queue.json
OPENING_CACHE_FILE: string;      // <DATA_DIR>/.opening_cache.json
CANVAS_CONTENT_FILE: string;     // <DATA_DIR>/.canvas_content.html
ARTEFACT_DISPLAY_FILE: string;   // <DATA_DIR>/.artefact_display.json
ARTEFACT_INDEX_FILE: string;     // <DATA_DIR>/.artefact_index.json
IDENTITY_REVIEW_QUEUE_FILE: string; // <DATA_DIR>/.identity_review_queue.json
AGENT_STATES_FILE: string;       // ~/.atrophy/agent_states.json (global)
```

### Constructor and Lifecycle

```typescript
constructor() {
  // Initialize all properties to defaults
  this.AGENT_NAME = 'xan';
  this.AGENT_DISPLAY_NAME = '';
  // ... (all other defaults)
  this.AGENT_STATES_FILE = path.join(USER_DATA, 'agent_states.json');
  this.load();  // Load configuration
}

load(): void {
  loadEnvFile();           // Load .env into process.env
  loadUserConfig();        // Load config.json into _userCfg
  this._resolveVersion();  // Resolve version (hot bundle or app)
  this._resolveAgent(cfg('AGENT', 'xan'));  // Resolve agent config
  this.PYTHON_PATH = findPython();  // Find Python interpreter
}

reloadForAgent(name: string): void {
  this._resolveAgent(name);  // Reload agent-specific config only
}
```

**Why `reloadForAgent` exists:** When switching agents, only agent-specific fields need to change. Global settings (TTS backend, window size, etc.) remain stable. This method updates only the agent-specific fields without reconstructing the entire object.

### Version Resolution

```typescript
private _resolveVersion(): void {
  // Check hot bundle version first
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
  
  // Fall back to app version
  this.VERSION = app.getVersion() || '0.0.0';
}
```

**Hot bundle priority:** If a hot bundle exists, its version takes precedence. This ensures the displayed version matches the running code, not the bundled version.

### Agent Resolution

```typescript
private _resolveAgent(name: string): void {
  this.AGENT_NAME = name;
  loadAgentManifest(name);

  this.AGENT_DIR = findAgentDir(name);
  this.DATA_DIR = agentDataDir(name);
  this.DB_PATH = path.join(this.DATA_DIR, 'memory.db');

  // Identity fields
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

  // Telegram credentials (agent manifest only - no env fallback)
  this.TELEGRAM_BOT_TOKEN = (_agentManifest.telegram_bot_token as string) || '';
  this.TELEGRAM_CHAT_ID = (_agentManifest.telegram_chat_id as string) || '';
  this.TELEGRAM_DM_CHAT_ID = (_agentManifest.telegram_dm_chat_id as string) || '';

  // TTS from manifest voice object
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

  // ... (remaining fields resolved similarly)
}
```

**Key distinction:** `||` vs `??` operators:
- `||` for strings: Empty string `""` falls through to config fallback
- `??` for numbers: `0` is a valid value and should NOT fall through

**Telegram credentials:** No environment variable fallback - credentials come ONLY from agent manifest. This prevents token bleed between agents.

## Avatar Path Resolution

```typescript
function avatarPath(agentName: string, rel: string): string {
  const userPath = path.join(USER_DATA, 'agents', agentName, 'avatar', rel);
  if (fs.existsSync(userPath)) return userPath;
  const bundlePath = path.join(BUNDLE_ROOT, 'agents', agentName, 'avatar', rel);
  if (fs.existsSync(bundlePath)) return bundlePath;
  return userPath;  // Prefer user dir for new files
}
```

**User overrides bundle:** Users can modify avatar assets by placing files in `~/.atrophy/agents/<name>/avatar/`. The resolution checks user data first, then bundle.

## Exported Functions Summary

| Function | Purpose |
|----------|---------|
| `ensureUserData()` | Create directory structure and migrate data |
| `getConfig()` | Get Config singleton instance |
| `saveUserConfig(updates)` | Deep-merge updates into config.json |
| `saveAgentConfig(name, updates)` | Deep-merge updates into agent.json |
| `saveEnvVar(key, value)` | Save secret to .env (whitelisted keys only) |
| `isValidAgentName(name)` | Validate agent name format |
| `isAllowedEnvKey(key)` | Check if key is in allowed env keys |

## File I/O Summary

| File | Read/Write | Format | Permissions |
|------|------------|--------|-------------|
| `~/.atrophy/config.json` | Both | JSON | 0o600 |
| `~/.atrophy/.env` | Both | KEY=VALUE lines | 0o600 |
| `~/.atrophy/agents/<name>/data/agent.json` | Both | JSON | 0o644 |
| `~/.atrophy/bundle/bundle-manifest.json` | Read | JSON | 0o644 |
| `<bundle>/agents/<name>/data/agent.json` | Read | JSON | 0o644 |

## See Also

- `src/main/index.ts` - Uses config at startup
- `src/main/app.ts` - Uses config throughout
- `src/main/memory.ts` - Uses DB_PATH from config
- `src/main/mcp-registry.ts` - Uses Python path from config

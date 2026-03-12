# Configuration Reference

All configuration flows through `src/main/config.ts`, which reads from four sources in order of priority:

1. **Environment variables** (from shell or `~/.atrophy/.env`)
2. **User config** (`~/.atrophy/config.json`) - persistent user settings
3. **Agent manifest** (`agents/<name>/data/agent.json`) - per-agent overrides
4. **Hardcoded defaults** in the `Config` class constructor

Environment variables win outright. For agent-specific settings (voice, heartbeat, telegram, display), the agent manifest takes priority over user config and defaults. The user config file at `~/.atrophy/config.json` replaces the old `.env`-based persistence for non-secret settings.

The `Config` class is a singleton, accessed via `getConfig()`. It provides typed properties for every configuration value. Call `reloadForAgent(name)` when switching agents to re-resolve all agent-specific settings.

---

## Resolution Functions

Two internal helpers drive the resolution:

### `cfg<T>(key, fallback)`

Standard resolution for user-level settings:

1. Check `process.env[key]` - if set, coerce to the fallback's type (number, boolean, or string)
2. Check `_userCfg[key]` (from `~/.atrophy/config.json`)
3. Check `_agentManifest[key]` (from `agent.json`)
4. Return `fallback`

### `agentCfg<T>(key, fallback)`

Agent-first resolution for per-agent settings (voice, heartbeat, display):

1. Check `_agentManifest[key]` - if set and not null/undefined, return it
2. Fall through to `cfg(key, fallback)` (env -> user config -> default)

This means agent manifest values take priority over environment variables for these settings.

### Resolution Example

For `TTS_PLAYBACK_RATE` (default `1.12`):

```
agentCfg('TTS_PLAYBACK_RATE', 1.12)
  1. agent.json has TTS_PLAYBACK_RATE = 1.25 -> returns 1.25
  2. (if not in manifest) env TTS_PLAYBACK_RATE=1.3 -> returns 1.3
  3. (if not in env) config.json has TTS_PLAYBACK_RATE = 1.15 -> returns 1.15
  4. (if not anywhere) -> returns 1.12
```

For `CLAUDE_BIN` (default `'claude'`):

```
cfg('CLAUDE_BIN', 'claude')
  1. env CLAUDE_BIN=/usr/local/bin/claude -> returns that path
  2. (if not in env) config.json has CLAUDE_BIN -> returns it
  3. (if not in config) agent.json has CLAUDE_BIN -> returns it
  4. (if not anywhere) -> returns 'claude'
```

---

## Environment Variables

| Variable | Default | Resolution | Description |
|----------|---------|------------|-------------|
| `AGENT` | `xan` | `cfg()` | Active agent name. Determines which `agents/<name>/` directory is loaded |
| `ATROPHY_DATA` | `~/.atrophy` | Direct | Root user data directory. Exported as `USER_DATA` constant |
| `INPUT_MODE` | `dual` | `cfg()` | Input mode: `voice`, `text`, or `dual` |
| `OBSIDIAN_VAULT` | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind` | Direct | Path to the Obsidian vault root |
| `AVATAR_ENABLED` | `false` | `cfg()` | Enable animated avatar in GUI mode |
| `TTS_BACKEND` | `elevenlabs` | `agentCfg()` | TTS engine: `elevenlabs`, `fal`, `macos`, `off` |
| `ELEVENLABS_API_KEY` | `''` | `cfg()` | ElevenLabs API key (shared across agents) |
| `ELEVENLABS_VOICE_ID` | `''` | `agentCfg()` | ElevenLabs voice ID (per-agent) |
| `ELEVENLABS_MODEL` | `eleven_v3` | `agentCfg()` | ElevenLabs model name |
| `ELEVENLABS_STABILITY` | `0.5` | `agentCfg()` | Voice stability (0.0-1.0). Lower = more expressive |
| `ELEVENLABS_SIMILARITY` | `0.75` | `agentCfg()` | Voice similarity boost (0.0-1.0) |
| `ELEVENLABS_STYLE` | `0.35` | `agentCfg()` | Style exaggeration (0.0-1.0) |
| `TTS_PLAYBACK_RATE` | `1.12` | `agentCfg()` | Audio playback speed multiplier |
| `FAL_VOICE_ID` | `''` | `agentCfg()` | Fal TTS voice ID (fallback provider) |
| `CLAUDE_BIN` | `claude` | `cfg()` | Path to the Claude Code CLI binary |
| `CLAUDE_EFFORT` | `medium` | `cfg()` | Default inference effort: `low`, `medium`, `high` |
| `ADAPTIVE_EFFORT` | `true` | `cfg()` | Auto-adjust effort based on conversation complexity |
| `WAKE_WORD_ENABLED` | `false` | `cfg()` | Enable background wake word detection |
| `HEARTBEAT_ACTIVE_START` | `9` | `agentCfg()` | Hour (0-23) when heartbeat checks begin |
| `HEARTBEAT_ACTIVE_END` | `22` | `agentCfg()` | Hour (0-23) when heartbeat checks stop |
| `HEARTBEAT_INTERVAL_MINS` | `30` | `agentCfg()` | Minutes between heartbeat evaluations |
| `TELEGRAM_BOT_TOKEN` | `''` | `agentCfg()` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | `''` | `agentCfg()` | Telegram chat ID |
| `NOTIFICATIONS_ENABLED` | `true` | `cfg()` | Enable macOS native notifications |
| `PYTHON_PATH` | auto-detected | Direct | Python 3 binary path for MCP servers |

---

## .env File (`~/.atrophy/.env`)

Secrets are loaded from this file into `process.env` on startup via `loadEnvFile()`. The parser:
- Skips empty lines and `#` comments
- Splits on the first `=` sign
- Strips surrounding single or double quotes from values
- Only sets variables that are not already in `process.env` (env vars take priority)

### Allowed Secret Keys

Only these keys can be written via `saveEnvVar()` (the setup wizard's `setup:saveSecret` handler):

| Key | Purpose |
|-----|---------|
| `ELEVENLABS_API_KEY` | ElevenLabs TTS authentication |
| `FAL_KEY` | Fal.ai image/video/TTS generation |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API |
| `OPENAI_API_KEY` | OpenAI API (unused in current code but reserved) |
| `ANTHROPIC_API_KEY` | Anthropic API (unused in current code but reserved) |

The `.env` file is written with mode `0o600` (owner read/write only). The `saveEnvVar()` function updates or appends the key, removes trailing blank lines, and ensures a final newline.

---

## User Config (`~/.atrophy/config.json`)

Persistent settings saved via the GUI settings panel. Same keys as environment variables but stored in JSON. Created automatically on first run with empty `{}`.

```json
{
  "CLAUDE_EFFORT": "high",
  "INPUT_MODE": "voice",
  "WAKE_WORD_ENABLED": true,
  "setup_complete": true,
  "USER_NAME": "Will"
}
```

Settings here are overridden by environment variables but take precedence over agent manifest defaults (for `cfg()` resolution) or defaults (for `agentCfg()` resolution).

### Save Mechanism

```typescript
export function saveUserConfig(updates: Record<string, unknown>): void
```

Deep-merges `updates` into the existing `config.json`. Plain objects are merged key-by-key; all other values (arrays, primitives, null) are overwritten from source. Written with mode `0o600`. After writing, reloads the in-memory cache via `loadUserConfig()`.

### Special Keys

| Key | Type | Description |
|-----|------|-------------|
| `setup_complete` | boolean | Set to `true` after the first-launch setup wizard completes. Reset to `false` (or remove) to re-run the wizard |
| `USER_NAME` | string | The user's name, set during setup |

---

## Agent Manifest (`agent.json`)

The agent manifest lives at `agents/<name>/data/agent.json` (in the bundle or `~/.atrophy/agents/<name>/data/agent.json` for user-installed agents).

### Manifest Loading

`loadAgentManifest(name)` searches two locations in order:
1. `~/.atrophy/agents/<name>/data/agent.json` (user data)
2. `<BUNDLE_ROOT>/agents/<name>/data/agent.json` (bundle)

First found wins.

### Agent Directory Resolution

`findAgentDir(name)` resolves the agent's root directory:
1. Check `~/.atrophy/agents/<name>/data/agent.json` - if exists, return user dir
2. Check `<BUNDLE_ROOT>/agents/<name>/data/agent.json` - if exists, return bundle dir
3. Default to user dir (for new agents)

### Properties Read from Manifest

These properties are read directly from the manifest (not through `cfg()`/`agentCfg()`):

| Manifest Key | Config Property | Type | Default |
|--------------|----------------|------|---------|
| `display_name` | `AGENT_DISPLAY_NAME` | string | Agent name, title-cased |
| `user_name` | `USER_NAME` | string | `'User'` |
| `wake_words` | `WAKE_WORDS` | string[] | `['hey <name>', '<name>']` |
| `telegram_emoji` | `TELEGRAM_EMOJI` | string | `''` |
| `disabled_tools` | `DISABLED_TOOLS` | string[] | `[]` |

### Properties Using `agentCfg()` (Manifest-First)

These are resolved with agent manifest taking priority:

| Manifest Key | Config Property | Type | Default |
|--------------|----------------|------|---------|
| `OPENING_LINE` | `OPENING_LINE` | string | `'Hello.'` |
| `TTS_BACKEND` | `TTS_BACKEND` | string | `'elevenlabs'` |
| `ELEVENLABS_VOICE_ID` | `ELEVENLABS_VOICE_ID` | string | `''` |
| `ELEVENLABS_MODEL` | `ELEVENLABS_MODEL` | string | `'eleven_v3'` |
| `ELEVENLABS_STABILITY` | `ELEVENLABS_STABILITY` | number | `0.5` |
| `ELEVENLABS_SIMILARITY` | `ELEVENLABS_SIMILARITY` | number | `0.75` |
| `ELEVENLABS_STYLE` | `ELEVENLABS_STYLE` | number | `0.35` |
| `TTS_PLAYBACK_RATE` | `TTS_PLAYBACK_RATE` | number | `1.12` |
| `FAL_VOICE_ID` | `FAL_VOICE_ID` | string | `''` |
| `HEARTBEAT_ACTIVE_START` | `HEARTBEAT_ACTIVE_START` | number | `9` |
| `HEARTBEAT_ACTIVE_END` | `HEARTBEAT_ACTIVE_END` | number | `22` |
| `HEARTBEAT_INTERVAL_MINS` | `HEARTBEAT_INTERVAL_MINS` | number | `30` |
| `TELEGRAM_BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` | string | `''` |
| `TELEGRAM_CHAT_ID` | `TELEGRAM_CHAT_ID` | string | `''` |
| `WINDOW_WIDTH` | `WINDOW_WIDTH` | number | `622` |
| `WINDOW_HEIGHT` | `WINDOW_HEIGHT` | number | `830` |

### Agent Config Save

```typescript
export function saveAgentConfig(agentName: string, updates: Record<string, unknown>): void
```

Shallow-merges updates into `~/.atrophy/agents/<name>/data/agent.json`. Creates the directory if needed.

### Config Update Routing

When the renderer calls `config:update`, the IPC handler classifies each key:

**Agent-specific keys** (saved to `agent.json`):
`AGENT_DISPLAY_NAME`, `OPENING_LINE`, `TTS_BACKEND`, `TTS_PLAYBACK_RATE`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`, `ELEVENLABS_STABILITY`, `ELEVENLABS_SIMILARITY`, `ELEVENLABS_STYLE`, `FAL_VOICE_ID`, `HEARTBEAT_ACTIVE_START`, `HEARTBEAT_ACTIVE_END`, `HEARTBEAT_INTERVAL_MINS`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `WINDOW_WIDTH`, `WINDOW_HEIGHT`, `DISABLED_TOOLS`

**User-level keys** (saved to `config.json`): everything else.

---

## Derived Config Values

These are computed at construction time and available as instance properties:

| Property | Type | Description |
|----------|------|-------------|
| `AGENT_NAME` | string | Active agent slug |
| `AGENT_DIR` | string | Root agent directory (user data or bundle) |
| `DATA_DIR` | string | `~/.atrophy/agents/<name>/data/` (always user data, created if missing) |
| `DB_PATH` | string | `<DATA_DIR>/memory.db` |
| `SCHEMA_PATH` | string | `<BUNDLE_ROOT>/db/schema.sql` |
| `VERSION` | string | Read from `<BUNDLE_ROOT>/VERSION`, fallback `'0.0.0'` |
| `PYTHON_PATH` | string | Resolved Python 3 binary path |
| `MCP_DIR` | string | `<BUNDLE_ROOT>/mcp/` |
| `MCP_SERVER_SCRIPT` | string | `<MCP_DIR>/memory_server.py` |
| `MCP_GOOGLE_SCRIPT` | string | `<MCP_DIR>/google_server.py` |
| `GOOGLE_CONFIGURED` | boolean | True if Google OAuth tokens exist or gws CLI is authenticated |
| `GOOGLE_DIR` | string | `~/.atrophy/.google/` |
| `OBSIDIAN_AVAILABLE` | boolean | True if vault directory exists on disk |
| `OBSIDIAN_PROJECT_DIR` | string | `<vault>/Projects/<project>` or `~/.atrophy/agents/` |
| `OBSIDIAN_AGENT_DIR` | string | `<vault>/Projects/<project>/Agent Workspace/<name>` or `~/.atrophy/agents/<name>/` |
| `OBSIDIAN_AGENT_NOTES` | string | Same as `OBSIDIAN_AGENT_DIR` |
| `WHISPER_PATH` | string | `<BUNDLE_ROOT>/vendor/whisper.cpp` |
| `WHISPER_BIN` | string | `<WHISPER_PATH>/build/bin/whisper-cli` |
| `WHISPER_MODEL` | string | `<WHISPER_PATH>/models/ggml-tiny.en.bin` |
| `FAL_TTS_ENDPOINT` | string | `'fal-ai/elevenlabs/tts/eleven-v3'` |
| `CANVAS_TEMPLATES` | string | `<BUNDLE_ROOT>/display/templates` |
| `MODELS_DIR` | string | `~/.atrophy/models/` |
| `AGENT_STATES_FILE` | string | `~/.atrophy/agent_states.json` |
| `BUNDLE_ROOT` | string (exported) | `process.resourcesPath` when packaged, project root in dev |
| `USER_DATA` | string (exported) | `~/.atrophy/` (or `ATROPHY_DATA` env var) |

### Per-Agent State File Paths

These are all in `<DATA_DIR>` (i.e. `~/.atrophy/agents/<name>/data/`):

| Property | Filename | Purpose |
|----------|----------|---------|
| `EMOTIONAL_STATE_FILE` | `.emotional_state.json` | Structured emotional state with decay |
| `USER_STATUS_FILE` | `.user_status.json` | User presence tracking |
| `MESSAGE_QUEUE_FILE` | `.message_queue.json` | File-based message queue for background jobs |
| `OPENING_CACHE_FILE` | `.opening_cache.json` | Cached opening lines |
| `CANVAS_CONTENT_FILE` | `.canvas_content.html` | Canvas overlay content |
| `ARTEFACT_DISPLAY_FILE` | `.artefact_display.json` | Current artefact display state |
| `ARTEFACT_INDEX_FILE` | `.artefact_index.json` | Artefact index |
| `IDENTITY_REVIEW_QUEUE_FILE` | `.identity_review_queue.json` | Queued identity reviews |

### Per-Agent Avatar Paths

| Property | Path | Purpose |
|----------|------|---------|
| `AVATAR_DIR` | `~/.atrophy/agents/<name>/avatar/` | Avatar root |
| `SOURCE_IMAGE` | `avatar/source/face.png` (user then bundle) | Source face for video generation |
| `IDLE_LOOPS_DIR` | `<AVATAR_DIR>/loops/` | Generated loop segments |
| `IDLE_LOOP` | `<AVATAR_DIR>/ambient_loop.mp4` | Master ambient loop |
| `IDLE_THINKING` | `<AVATAR_DIR>/idle_thinking.mp4` | Thinking state video |
| `IDLE_LISTENING` | `<AVATAR_DIR>/idle_listening.mp4` | Listening state video |

---

## Google Auth Detection

`googleConfigured()` checks two methods:

1. **Legacy OAuth tokens**: checks if `~/.atrophy/.google/token.json` exists
2. **gws CLI auth**: finds the `gws` binary via `which gws`, runs `gws auth status` with a 5-second timeout, parses the JSON output, returns `true` if `auth_method` is not `'none'`

---

## Data Migration

`migrateAgentData()` runs once on startup via `ensureUserData()`. For each agent in `<BUNDLE_ROOT>/agents/`:

1. **Data files**: copies files from `bundle/agents/<name>/data/` to `~/.atrophy/agents/<name>/data/`, skipping `agent.json` (manifest stays in bundle) and any file that already exists at destination.
2. **Avatar tree**: recursively copies the `avatar/` tree from bundle to user data using `copyTreeIfMissing()`, which only copies files that don't already exist (preserving user modifications).

---

## Constants

These are hardcoded in the `Config` class constructor and not configurable through environment variables:

### Voice Input

| Property | Value | Type | Description |
|----------|-------|------|-------------|
| `PTT_KEY` | `'ctrl'` | string | Push-to-talk key |
| `SAMPLE_RATE` | `16000` | number | Audio capture rate in Hz (whisper expects 16kHz) |
| `CHANNELS` | `1` | number | Mono audio |
| `MAX_RECORD_SEC` | `120` | number | Max recording duration in seconds |
| `WAKE_CHUNK_SECONDS` | `2` | number | Wake word audio chunk duration |

### Memory and Context

| Property | Value | Type | Description |
|----------|-------|------|-------------|
| `CONTEXT_SUMMARIES` | `3` | number | Recent session summaries injected into context |
| `MAX_CONTEXT_TOKENS` | `180000` | number | Maximum context window size |
| `VECTOR_SEARCH_WEIGHT` | `0.7` | number | Semantic vs keyword search balance (0.0-1.0) |
| `EMBEDDING_MODEL` | `'all-MiniLM-L6-v2'` | string | Sentence transformer model |
| `EMBEDDING_DIM` | `384` | number | Embedding vector dimensionality |

### Session

| Property | Value | Type | Description |
|----------|-------|------|-------------|
| `SESSION_SOFT_LIMIT_MINS` | `60` | number | Soft limit before check-in prompt |

### Display

| Property | Value | Type | Description |
|----------|-------|------|-------------|
| `AVATAR_RESOLUTION` | `512` | number | Default avatar render resolution in pixels |

---

## Settings Panel (GUI)

When running in GUI mode, the settings panel provides live configuration. Open with the gear icon or Cmd+,.

The panel is organised into sections:

| Section | Settings |
|---------|----------|
| **Agents** | List of all discovered agents with Switch/Muted/Enabled controls, plus **+ New Agent** |
| **Agent Identity** | Display name, user name, opening line, wake words, Obsidian subdirectory |
| **Tools** | Per-agent checkboxes to enable/disable specific MCP tools |
| **Window** | Width, height, window title, avatar enabled, avatar resolution |
| **Voice & TTS** | TTS backend, ElevenLabs API key, voice ID, model, stability, similarity, style, playback rate, Fal voice ID |
| **Input** | Input mode, push-to-talk key, wake word detection, wake chunk duration |
| **Notifications** | Notifications enabled toggle |
| **Audio Capture** | Sample rate, max record duration |
| **Inference** | Claude binary path, effort level, adaptive effort toggle |
| **Memory & Context** | Context summaries count, max context tokens, vector search weight, embedding model, embedding dimensions |
| **Session** | Soft time limit |
| **Heartbeat** | Active start/end hours, check interval |
| **Paths** | Obsidian vault path, database path (read-only), whisper binary path (read-only) |
| **Telegram** | Bot token, chat ID |
| **About** | Version, install path, Check for Updates / Update Now, Reset Setup Wizard |

Two actions at the bottom:

- **Apply** - applies changes to the running session immediately (in-memory only, lost on restart)
- **Save** - applies changes AND writes them to `~/.atrophy/config.json` (for general settings) and `agent.json` (for agent-specific settings)

---

## Per-Agent Paths

All per-agent paths are derived from the agent name. For an agent named `oracle`:

### Bundle paths (repo / app bundle)

| Path | Description |
|------|-------------|
| `agents/oracle/data/agent.json` | Agent manifest |
| `agents/oracle/prompts/system_prompt.md` | System prompt |
| `agents/oracle/prompts/soul.md` | Identity / personality |
| `agents/oracle/prompts/heartbeat.md` | Outreach decision checklist |
| `agents/oracle/avatar/source/face.png` | Source face image |
| `scripts/agents/oracle/jobs.json` | Scheduled job definitions |
| `scripts/agents/oracle/` | Agent-specific scripts |

### User data paths (`~/.atrophy/`)

| Path | Description |
|------|-------------|
| `~/.atrophy/agents/oracle/data/memory.db` | SQLite memory database |
| `~/.atrophy/agents/oracle/data/` | Runtime state files |
| `~/.atrophy/agents/oracle/avatar/loops/` | Generated loop segments |
| `~/.atrophy/agents/oracle/avatar/ambient_loop.mp4` | Master ambient loop |
| `~/.atrophy/agents/oracle/tools/` | Custom MCP tools |
| `~/.atrophy/logs/oracle/` | Job execution logs |
| `~/.atrophy/config.json` | User config (shared) |
| `~/.atrophy/models/` | Cached embedding models |

---

## Telegram Per-Agent Configuration

Each agent can have its own Telegram bot. The manifest specifies environment variable *names*, not values:

```json
{
  "telegram": {
    "bot_token_env": "TELEGRAM_BOT_TOKEN_ORACLE",
    "chat_id_env": "TELEGRAM_CHAT_ID_ORACLE"
  }
}
```

Then set the actual values in `~/.atrophy/.env`:

```
TELEGRAM_BOT_TOKEN_ORACLE=123456:ABC-DEF...
TELEGRAM_CHAT_ID_ORACLE=987654321
```

---

## Prompt Resolution (Four-Tier)

`src/main/prompts.ts` resolves skill/prompt files through four directories in order:

1. **Obsidian vault** - `Agent Workspace/<agent>/skills/{name}.md`
2. **Local skills** - `~/.atrophy/agents/<agent>/skills/{name}.md`
3. **User prompts** - `~/.atrophy/agents/<agent>/prompts/{name}.md`
4. **Bundle** - `agents/<agent>/prompts/{name}.md`

First match wins.

---

## Google Integration

Google tools are enabled automatically when OAuth2 credentials are present. The system checks at config load time via `googleConfigured()`.

### Setup

```bash
python scripts/google_auth.py              # Authorize (opens browser)
python scripts/google_auth.py --check      # Check credentials
python scripts/google_auth.py --revoke     # Revoke and delete
```

### Credential Storage

| Path | Permissions | Contents |
|------|-------------|----------|
| `config/google_oauth.json` | - | Bundled OAuth2 client credentials |
| `~/.atrophy/.google/` | `0700` | Token storage directory |
| `~/.atrophy/.google/token.json` | `0600` | OAuth2 refresh + access tokens |

### Per-Agent Disabling

```json
{
  "disabled_tools": ["mcp__google__*"]
}
```

Or specific tools: `["mcp__google__gmail_send", "mcp__google__gcal_delete_event"]`

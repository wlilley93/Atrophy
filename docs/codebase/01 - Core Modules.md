# Core Modules

All core logic lives in `src/main/`. Each module has a single responsibility. The main process handles all file I/O, database access, subprocess management, and heavy computation. The renderer communicates exclusively via IPC through the preload bridge, never accessing Node APIs directly.

This document covers every module in the main process in dependency order: configuration first, then data layer, then inference, then session management, then behavioral modules, then voice, then networking, then scheduling. Each section explains what the module does, why it exists, how it connects to the rest of the system, and the full public API surface.

---

## logger.ts

The logger module provides leveled logging across the entire codebase, replacing raw `console.log` calls. Every main-process module creates a tagged logger via `createLogger('tag')` and uses `log.debug`, `log.info`, `log.warn`, or `log.error` for output. The active threshold is controlled by the `LOG_LEVEL` environment variable, defaulting to `debug` in development and `info` in production.

### Exported API

```typescript
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export function setLogLevel(level: LogLevel): void;
export function createLogger(tag: string): {
  debug(msg: string, ...args: unknown[]): void;
  info(msg: string, ...args: unknown[]): void;
  warn(msg: string, ...args: unknown[]): void;
  error(msg: string, ...args: unknown[]): void;
};
export default log; // default logger tagged 'atrophy'
```

Each log line is prefixed with `[tag]` automatically, so modules do not include their own bracket tags in message strings. The level ordering is `debug < info < warn < error` - setting `LOG_LEVEL=warn` suppresses all debug and info output.

---

## config.ts

The configuration module is the foundation that every other module depends on. It implements a three-tier resolution scheme - env vars, then `~/.atrophy/config.json`, then `agents/<name>/data/agent.json`, then hardcoded defaults - so that deployment-level overrides take precedence over user preferences, which in turn take precedence over per-agent manifests. This design lets the same agent bundle run in different environments (dev, packaged app, CI) without changing any agent files. The module is a port of `config.py` and weighs in at 735 lines, most of which is property resolution logic.

### Exported Constants

These two constants establish the root paths that the entire application uses for locating bundled resources and user data. They are resolved once at module load time and never change during the process lifetime.

```typescript
export const BUNDLE_ROOT: string;
// app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..', '..')

export const USER_DATA: string;
// process.env.ATROPHY_DATA || path.join(HOME, '.atrophy')
```

`BUNDLE_ROOT` points to the packaged resources directory in production or to the project root in development. `USER_DATA` points to `~/.atrophy/` by default but can be overridden for testing or multi-instance setups via the `ATROPHY_DATA` environment variable.

### Exported Functions

The following functions form the public configuration API that other modules use to read and write settings.

```typescript
export function ensureUserData(): void;
```
Creates the directory tree `~/.atrophy/`, `~/.atrophy/agents/`, `~/.atrophy/logs/`, `~/.atrophy/models/`. Creates an empty `config.json` (mode `0o600`) if missing. Calls `migrateAgentData()` to copy runtime data from bundle to user data (skipping `agent.json` manifests and files that already exist at the destination). This function runs once at startup before any other module initializes, ensuring the filesystem layout is always in a known good state.

```typescript
export function getConfig(): Config;
```
Returns the singleton `Config` instance. Creates it on first call. Every module that needs configuration calls this rather than constructing its own `Config`, which guarantees a single source of truth for all settings. The instance is cached for the lifetime of the process.

```typescript
export function saveUserConfig(updates: Record<string, unknown>): void;
```
Deep-merges `updates` into `~/.atrophy/config.json`. Plain objects are merged key-by-key; arrays, primitives, and null are overwritten from source. Writes with mode `0o600`. Reloads the in-memory config cache afterward so `cfg()` calls see new values. This is the primary mechanism the Settings modal uses to persist user changes.

```typescript
export function saveAgentConfig(agentName: string, updates: Record<string, unknown>): void;
```
Shallow-merges `updates` into `~/.atrophy/agents/<name>/data/agent.json`. Creates the directory if missing. Used when per-agent settings (voice ID, display name, disabled tools) are changed through the UI or during setup wizard completion.

```typescript
export function saveEnvVar(key: string, value: string): void;
```
Saves a secret to `~/.atrophy/.env`. Only allows whitelisted keys: `ELEVENLABS_API_KEY`, `FAL_KEY`, `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. Updates or appends the key in the file, writes with mode `0o600`, and sets the value in `process.env`. The whitelist prevents accidental exposure of arbitrary environment variables through the settings UI.

### Config Class

The `Config` class is a singleton with all configuration properties as public fields. It is constructed once by `getConfig()` and cached for the process lifetime. The `reloadForAgent()` method updates all agent-specific fields without recreating the entire object, which is important for agent switching and Telegram daemon dispatch where the active agent changes mid-process.

The following properties are grouped by subsystem. Each group is loaded from the three-tier resolution chain described above.

**Agent identity** - these define who the current agent is and how it presents itself:
- `AGENT_NAME: string` - default `'xan'`
- `AGENT_DISPLAY_NAME: string` - from manifest `display_name` or capitalized name
- `USER_NAME: string` - default `'User'`
- `OPENING_LINE: string` - default `'Hello.'`
- `WAKE_WORDS: string[]` - from manifest or `['hey <name>', '<name>']`
- `TELEGRAM_EMOJI: string` - from manifest
- `DISABLED_TOOLS: string[]` - from manifest

**TTS defaults** - voice synthesis parameters passed to ElevenLabs and Fal:
- `TTS_BACKEND: string` - `'elevenlabs'`
- `ELEVENLABS_MODEL: string` - `'eleven_v3'`
- `ELEVENLABS_STABILITY: number` - `0.5`
- `ELEVENLABS_SIMILARITY: number` - `0.75`
- `ELEVENLABS_STYLE: number` - `0.35`
- `TTS_PLAYBACK_RATE: number` - `1.12`
- `FAL_TTS_ENDPOINT: string` - `'fal-ai/elevenlabs/tts/eleven-v3'`

**Audio** - recording and input mode configuration:
- `PTT_KEY: string` - `'ctrl'`
- `INPUT_MODE: string` - `'dual'`
- `SAMPLE_RATE: number` - `16000`
- `CHANNELS: number` - `1`
- `MAX_RECORD_SEC: number` - `120`
- `WAKE_WORD_ENABLED: boolean` - `false`
- `WAKE_CHUNK_SECONDS: number` - `2`

**Claude CLI** - inference subprocess parameters:
- `CLAUDE_BIN: string` - `'claude'`
- `CLAUDE_EFFORT: string` - `'medium'`
- `ADAPTIVE_EFFORT: boolean` - `true`

**Memory & context** - how much context to inject and how embeddings work:
- `CONTEXT_SUMMARIES: number` - `3`
- `MAX_CONTEXT_TOKENS: number` - `180000`
- `EMBEDDING_MODEL: string` - `'all-MiniLM-L6-v2'`
- `EMBEDDING_DIM: number` - `384`
- `VECTOR_SEARCH_WEIGHT: number` - `0.7`

**Session** - conversation lifecycle limits:
- `SESSION_SOFT_LIMIT_MINS: number` - `60`

**Heartbeat** - autonomous agent check-in scheduling:
- `HEARTBEAT_ACTIVE_START: number` - `9`
- `HEARTBEAT_ACTIVE_END: number` - `22`
- `HEARTBEAT_INTERVAL_MINS: number` - `30`

**Display** - window geometry and avatar rendering:
- `WINDOW_WIDTH: number` - `622`
- `WINDOW_HEIGHT: number` - `830`
- `AVATAR_ENABLED: boolean` - `false`
- `AVATAR_RESOLUTION: number` - `512`

**UI defaults** - initial toggle states on app launch:
- `SILENCE_TIMER_ENABLED: boolean` - `true`
- `SILENCE_TIMER_MINUTES: number` - `5`
- `EYE_MODE_DEFAULT: boolean` - `false`
- `MUTE_BY_DEFAULT: boolean` - `false`

**State files** - paths to JSON files that persist runtime state between sessions. All are under `DATA_DIR` (the agent's data directory) unless noted otherwise:
- `EMOTIONAL_STATE_FILE` - `.emotional_state.json`
- `USER_STATUS_FILE` - `.user_status.json`
- `MESSAGE_QUEUE_FILE` - `.message_queue.json`
- `OPENING_CACHE_FILE` - `.opening_cache.json`
- `CANVAS_CONTENT_FILE` - `.canvas_content.html`
- `ARTEFACT_DISPLAY_FILE` - `.artefact_display.json`
- `ARTEFACT_INDEX_FILE` - `.artefact_index.json`
- `IDENTITY_REVIEW_QUEUE_FILE` - `.identity_review_queue.json`
- `AGENT_STATES_FILE` - `~/.atrophy/agent_states.json` (global, not per-agent)

### Methods

The Config class exposes two lifecycle methods that control when and how configuration is loaded.

```typescript
load(): void;
```
Called by the constructor. Loads `.env`, user config, resolves version, resolves agent, finds Python. This is the only time the full resolution chain runs from scratch - all subsequent reads use the cached values.

```typescript
reloadForAgent(name: string): void;
```
Reloads all agent-specific config fields for a different agent. Used during agent switching and Telegram daemon dispatch. This avoids reconstructing the entire Config object when only the agent context changes, keeping non-agent settings (like TTS backend, window size, and server tokens) stable.

### Internal Resolution

The `cfg<T>(key, fallback)` helper resolves in order: env var -> `_userCfg[key]` -> `_agentManifest[key]` -> fallback. The `agentCfg<T>(key, fallback)` variant checks the agent manifest first. These two helpers are the core of the three-tier resolution system - every property in the Config class is assigned through one of them, which keeps the precedence rules consistent and in one place.

### Python Path Detection

`findPython()` checks `PYTHON_PATH` env var, then tries `python3`, `/opt/homebrew/bin/python3`, `/usr/local/bin/python3` via `execSync('<path> --version')`. The detected path is stored in `PYTHON_PATH` and used by the MCP server config generator and cron job installer. This search order covers Homebrew on Apple Silicon, Homebrew on Intel, and system Python.

### Google Auth Detection

`googleConfigured()` checks for legacy `~/.atrophy/.google/token.json`, then attempts `gws auth status` (5s timeout) and parses JSON to check if `auth_method !== 'none'`. The result is stored in `GOOGLE_CONFIGURED` and controls whether the Google MCP server is included in the MCP config. This two-path check supports both the old token-file approach and the newer GWS CLI authentication.

### Obsidian Vault

No default path - set via `OBSIDIAN_VAULT` env var or `~/.atrophy/config.json`. `OBSIDIAN_AVAILABLE` is `true` if the directory exists on disk. The vault path is passed to MCP servers as an environment variable so they can read and write notes directly into the user's knowledge base.

### Dependencies

The config module has minimal dependencies to avoid circular imports, since nearly every other module imports it:
- `electron` (for `app.isPackaged`, `process.resourcesPath`)
- `child_process` (for `execSync` in Python/Google detection)

---

## memory.ts

The memory module is the SQLite data layer that persists everything the agent knows. It implements a three-layer memory architecture - Episodic (sessions, turns, bookmarks), Semantic (summaries, observations, threads), and Identity (snapshots, entities) - via `better-sqlite3`. This is a port of `core/memory.py` at 1088 lines, making it the second most complex module after inference. Every conversation turn, summary, observation, and identity snapshot flows through this module, and it is the primary data source for context injection and vector search.

### Exported Interfaces

The following interfaces define the shapes of all records stored in and retrieved from SQLite. They map directly to table schemas in `db/schema.sql` and are used throughout the codebase as the canonical types for memory data.

```typescript
export interface Session {
  id: number;
  started_at: string;
  ended_at: string | null;
  summary: string | null;
  mood: string | null;
  notable: boolean;
  cli_session_id: string | null;
}

export interface Turn {
  id: number;
  session_id: number;
  role: 'will' | 'agent';
  content: string;
  timestamp: string;
  topic_tags: string | null;
  weight: number;
  channel: string;
}

export interface Summary {
  id: number;
  created_at: string;
  session_id: number;
  content: string;
  topics: string | null;
}

export interface Thread {
  id: number;
  name: string;
  last_updated: string | null;
  summary: string | null;
  status: 'active' | 'dormant' | 'resolved';
}

export interface Observation {
  id: number;
  created_at: string;
  content: string;
  source_turn: number | null;
  incorporated: boolean;
  valid_from: string | null;
  valid_to: string | null;
  learned_at: string;
  expired_at: string | null;
  confidence: number;
  activation: number;
  last_accessed: string | null;
}

export interface IdentitySnapshot {
  id: number;
  created_at: string;
  trigger: string | null;
  content: string;
}

export interface Bookmark {
  id: number;
  session_id: number;
  created_at: string;
  moment: string;
  quote: string | null;
}

export interface ToolCall {
  id: number;
  session_id: number;
  timestamp: string;
  tool_name: string;
  input_json: string | null;
  flagged: boolean;
}

export interface UsageEntry {
  id: number;
  timestamp: string;
  source: string;
  tokens_in: number;
  tokens_out: number;
  duration_ms: number;
  tool_count: number;
}

export interface Entity {
  id: number;
  name: string;
  entity_type: string;
  mention_count: number;
  last_seen: string;
}

export interface EntityRelation {
  id: number;
  entity_a: number;
  entity_b: number;
  relation: string;
  strength: number;
  last_seen: string;
}

export interface CrossAgentSearchResult {
  agent: string;
  turns: Pick<Turn, 'id' | 'session_id' | 'role' | 'content' | 'timestamp'>[];
  summaries: Pick<Summary, 'session_id' | 'content' | 'created_at'>[];
  error?: string;
}
```

### Connection Management

The memory module manages a pool of SQLite connections, one per database path. This pooling exists because the system can open multiple agent databases simultaneously - the current agent's DB for normal operations, plus other agents' DBs for cross-agent search and usage reporting.

```typescript
export function getDb(): Database.Database;
```
Returns the connection for the current agent's DB path (from `getConfig().DB_PATH`). If no connection exists for that path, one is created and cached.

Internal `connect(dbPath)` uses a `Map<string, Database.Database>` pool. On first connection: creates parent directory, opens with `journal_mode = WAL` and `foreign_keys = ON`. WAL mode allows concurrent reads during writes, which matters when background embedding tasks run alongside user queries.

### Schema & Migrations

Schema initialization is idempotent - it can run on every startup without risk. This simplifies deployment since there is no separate migration step.

```typescript
export function initDb(dbPath?: string): void;
```
Connects to the database, runs `migrate()`, then executes the full `schema.sql` file. The schema file uses `CREATE TABLE IF NOT EXISTS` so it is idempotent. This function is called once at startup and again whenever the active agent changes.

`migrate()` adds missing columns safely using `ALTER TABLE ... ADD COLUMN` wrapped in try/catch (column already exists is silently caught). The following columns are added by migration to support features that were added after the initial schema:

- `turns`: `channel TEXT DEFAULT 'direct'`, `embedding BLOB`, `weight INTEGER DEFAULT 1`, `topic_tags TEXT`
- `sessions`: `cli_session_id TEXT`, `notable BOOLEAN DEFAULT 0`
- `observations`: `valid_from DATETIME`, `valid_to DATETIME`, `learned_at DATETIME DEFAULT CURRENT_TIMESTAMP`, `expired_at DATETIME`, `confidence REAL DEFAULT 0.5`, `activation REAL DEFAULT 1.0`, `last_accessed DATETIME`, `embedding BLOB`
- `coherence_checks`: `action TEXT DEFAULT 'none'`
- `entities`: `embedding BLOB`

The migration function also converts legacy `role = 'companion'` turns to `role = 'agent'` from Python-era databases, ensuring backward compatibility with data created by the original Python application.

### Vector Helpers

These two functions handle serialization between `Float32Array` (used in-memory by the embedding engine) and `Buffer` (stored as BLOB in SQLite). They are used heavily by the async embedding pipeline and vector search module.

```typescript
export function vectorToBlob(vec: Float32Array): Buffer;
// Buffer.from(vec.buffer, vec.byteOffset, vec.byteLength)

export function blobToVector(blob: Buffer): Float32Array;
// new Float32Array(blob.buffer, blob.byteOffset, blob.length / 4)
```

### Async Embedding

Embedding is the most expensive operation in the memory pipeline - each call runs a neural network inference via Transformers.js. To avoid blocking the main thread, embedding is typically fire-and-forget: the row is inserted immediately, and the embedding vector is written to the same row asynchronously in the background.

```typescript
// Internal - fire-and-forget
function embedAsync(table: string, rowId: number, text: string, dbPath?: string): void;
// Allowed tables: 'turns', 'summaries', 'observations', 'bookmarks'
// Calls embed(), converts to blob, updates the row. Errors logged but never thrown.

export async function embedAndStore(
  table: string, rowId: number, text: string, dbPath?: string
): Promise<void>;
// Synchronous variant - waits for embedding before returning.
```

The fire-and-forget pattern means search results may briefly miss very recent content (the few seconds before embedding completes), but this tradeoff is worthwhile because it keeps turn insertion instant. The synchronous variant `embedAndStore` is used for reindexing operations where completeness matters more than speed.

### Session Management

Sessions represent a single conversation window - from the user opening the app to closing it or switching agents. Each session has a start time, optional end time, summary, mood, and a link to the Claude CLI session ID for conversation continuity.

```typescript
export function startSession(): number;
// INSERT INTO sessions DEFAULT VALUES; returns sessionId

export function endSession(
  sessionId: number,
  summary: string | null = null,
  mood: string | null = null,
  notable = false
): void;
// UPDATE sessions SET ended_at, summary (COALESCE), mood (COALESCE), notable

export function saveCliSessionId(sessionId: number, cliSessionId: string): void;

export function getLastCliSessionId(): string | null;
// Most recent session with a non-null cli_session_id

export function updateSessionMood(sessionId: number, mood: string): void;
```

The `getLastCliSessionId()` function is particularly important because it enables conversation continuity across app restarts. When the app launches, it retrieves the last CLI session ID and passes it to `streamInference()` with the `--resume` flag, allowing Claude to pick up where it left off with full context.

### Turns

Turns are the atomic units of conversation - every message from the user or agent becomes a turn. They are the most frequently written records in the database, and each one triggers a background embedding for later semantic search.

```typescript
export function writeTurn(
  sessionId: number,
  role: 'will' | 'agent',
  content: string,
  topicTags?: string,
  weight = 1,
  channel = 'direct'
): number;
// Inserts turn, fires embedAsync() in background, returns turnId

export function getSessionTurns(sessionId: number): Turn[];

export function getRecentCompanionTurns(limit = 4): string[];
// Returns content of last N agent turns (DESC order)

export function getLastInteractionTime(): string | null;
// Timestamp of the most recent turn

export function getLastSessionTime(): string | null;
// started_at of the second-to-last session (OFFSET 1)

export function getTodaysTurns(): Turn[];
// All turns from sessions started today
```

The `channel` field distinguishes between `'direct'` (GUI), `'telegram'`, and `'task'` (cron job) sources. The `weight` field allows certain turns to be prioritized in search results - for example, turns marked as important by the user could receive a higher weight.

### Summaries

Summaries are generated at the end of each session by the inference module. They compress an entire conversation into 2-3 sentences and serve as the primary mechanism for long-term memory - recent summaries are injected into the system prompt via `getContextInjection()`.

```typescript
export function writeSummary(sessionId: number, content: string, topics?: string): number;
// Inserts summary with background embedding

export function getRecentSummaries(n = 3): Summary[];
```

### Threads

Threads track ongoing topics across multiple sessions. The agent creates and updates threads through MCP tools when it notices recurring themes. Threads with `'active'` status are included in the system prompt context, giving the agent awareness of what the user has been working on or thinking about over time.

```typescript
export function createThread(name: string, summary?: string): number;

export function updateThread(
  threadId: number,
  opts: { summary?: string; status?: 'active' | 'dormant' | 'resolved' }
): void;
// Dynamic SQL - builds SET clauses from provided opts

export function updateThreadSummary(threadName: string, summary: string): void;
// Case-insensitive name match via LOWER()

export function getActiveThreads(): Thread[];
// WHERE status = 'active' ORDER BY last_updated DESC
```

### Identity Snapshots

Identity snapshots capture the agent's evolving self-concept. When the agent reflects on who it is, what it values, or how it relates to the user, it writes a snapshot. The most recent snapshot is injected into the system prompt so the agent maintains a consistent identity across sessions.

```typescript
export function writeIdentitySnapshot(content: string, trigger?: string): number;

export function getLatestIdentity(): IdentitySnapshot | null;
// Most recent by created_at
```

### Observations

Observations are facts the agent learns about the user - preferences, habits, relationships, life events. They have a confidence score (0-1), an activation level that decays over time, and optional validity windows for time-bound facts. The MCP memory tools create observations, and the context system surfaces high-activation ones during conversation.

```typescript
export function writeObservation(
  content: string,
  sourceTurn?: number,
  confidence = 0.5,
  validFrom?: string
): number;
// Inserts with background embedding

export function markObservationIncorporated(obsId: number): void;
// SET incorporated = 1

export function retireObservation(obsId: number): void;
// DELETE FROM observations WHERE id = ?

export function markObservationsStale(olderThanDays = 30): number;
// Prepends '[stale] ' to content of unincorporated observations older than N days
// Skips already-stale ones. Returns count of rows affected.

export function getTodaysObservations(): Observation[];

export function getRecentObservations(limit = 10, activationThreshold?: number): Observation[];
// If activationThreshold provided, filters by COALESCE(activation, 1.0) >= threshold
```

### Activation & Decay

The activation system implements a psychological model of memory salience. Recently accessed memories have high activation and surface more readily in search and context injection. Over time, unaccessed memories decay exponentially, mimicking how human memory fades without reinforcement.

```typescript
export function updateActivation(table: string, rowId: number): void;
// Allowed tables: 'observations', 'summaries', 'turns', 'bookmarks', 'entities'
// For observations: activation = MIN(1.0, activation + 0.2), updates last_accessed

export function decayActivations(halfLifeDays = 30): void;
// Exponential decay: newActivation = current * exp(-ln2/halfLife * daysSinceLastAccess)
// Runs in a transaction. Sets activation to 0 if below 0.01.
// Uses last_accessed or created_at as reference time.
```

The 30-day half-life means an observation that has not been accessed for 30 days will have half its original activation. After 90 days without access, activation drops to about 12.5%. This provides a natural forgetting curve while still allowing important but rarely accessed memories to be found through direct search.

### Bookmarks

Bookmarks mark specific moments the agent considers worth remembering - a breakthrough insight, an emotional exchange, or a shared joke. They differ from observations in that they capture a moment rather than a fact, and include an optional verbatim quote from the conversation.

```typescript
export function writeBookmark(sessionId: number, moment: string, quote?: string): number;
// Background embedding on the moment text

export function getTodaysBookmarks(): Bookmark[];
```

### Entity Management

The entity system extracts and tracks named entities (people, projects, concepts, places) mentioned in conversation. Entities are linked to each other through co-occurrence relations, forming a knowledge graph that the agent can query to understand relationships between topics.

The following constants control entity extraction from raw text:
- `PERSON_TITLES`: `Set(['mr', 'mrs', 'ms', 'dr', 'prof', 'professor'])`
- `ENTITY_NAME_RE`: `/\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b/g` - multi-word capitalized names
- `PROPER_NOUN_RE`: `/(?<=[a-z]\s)([A-Z][a-z]{2,})\b/g` - mid-sentence proper nouns
- `QUOTED_RE`: `/"([^"]{2,50})"/g` - quoted terms (2-50 chars)
- `STOP_WORDS`: `Set(['the', 'this', 'that', 'what', 'when', 'where', 'how', 'which', 'while', 'also', 'just', 'very', 'really'])`

The extraction and storage functions form a pipeline from raw text to linked knowledge graph entries:

```typescript
export function extractEntities(text: string): string[];
// Returns raw name strings from regex patterns. Filters by length > 2 and not in STOP_WORDS.

export function extractAndStoreEntities(text: string):
  { id: number; name: string; entity_type: string; mention_count: number }[];
// Full pipeline: extract -> batch lookup existing -> transaction (update counts or insert)
// -> cross-reference (link all pairs with 'co_occurs' relation)
// Entity type guessing: checks for person titles, project/system/framework keywords,
// place keywords, defaults to 'concept'.

export function upsertEntity(name: string, entityType?: string): number;
// Case-insensitive lookup. Increments mention_count if exists, inserts otherwise.

export function linkEntities(entityA: number, entityB: number, relation: string): void;
// Checks both directions (a->b and b->a). Strengthens by +0.1 (capped at 1.0)
// if relation exists, inserts with default strength otherwise.
// Self-links (entityA === entityB) are silently skipped.

export function linkEntitiesByName(nameA: string, nameB: string, relation = 'related_to'): void;
// Convenience wrapper - upserts both entities then links them.
```

### Audit & Logging

The audit subsystem records tool calls, heartbeat decisions, coherence checks, and usage metrics. This data powers the Activity tab in the Settings modal, enables debugging of agent behavior, and provides token usage tracking for cost awareness.

```typescript
export function logToolCall(
  sessionId: number, toolName: string, inputJson?: string, flagged = false
): void;

export function logHeartbeat(decision: string, reason?: string, message?: string): void;

export function logCoherenceCheck(
  score: number, degraded: boolean, signals: string, action = 'none'
): void;

export function logUsage(
  source: string, tokensIn: number, tokensOut: number,
  durationMs: number, toolCount: number
): void;

export function getToolAudit(opts?: {
  sessionId?: number;
  flaggedOnly?: boolean;
  limit?: number;  // default 50
}): ToolCall[];
```

### Context Injection

This function is the bridge between the memory layer and the inference system. It assembles a markdown string from the three most important memory sources and returns it for inclusion in the system prompt.

```typescript
export function getContextInjection(nSummaries = 3): string;
```
Assembles a context string from three sources, each rendered as a markdown section:
1. Latest identity snapshot (under `## Identity`) - gives the agent a consistent sense of self
2. Active threads (under `## Active Threads` - bulleted list with name and summary) - gives awareness of ongoing topics
3. Recent N summaries (under `## Recent Sessions` - timestamped) - gives memory of recent conversations

### Cross-Agent Queries

These functions allow one agent to peek into another agent's memory, enabling cross-agent awareness and collaborative features. They open other agents' databases read-only and return limited result sets to keep context injection manageable.

```typescript
export function getOtherAgentsRecentSummaries(
  nPerAgent = 2,
  maxAgents = 5,
  currentAgent?: string
): { agent: string; summaries: { content: string; created_at: string; mood: string | null }[] }[];
// Scans ~/.atrophy/agents/, excludes current agent, opens each memory.db,
// fetches last N summaries joined with session mood. Max 5 agents.

export function searchOtherAgentMemory(
  agentName: string, query: string, limit = 10
): CrossAgentSearchResult;
// LIKE '%query%' search on turns and summaries in another agent's DB.
// Returns error message if DB doesn't exist.
```

### Cleanup

When the application shuts down, all database connections must be closed to ensure WAL checkpointing completes and no data is lost.

```typescript
export function closeAll(): void;
// Closes all pooled connections. Errors silently caught.
```

### Dependencies

The memory module depends on:
- `better-sqlite3` - the SQLite driver
- `config.ts` (getConfig, USER_DATA) - for database paths and agent directory resolution
- `embeddings.ts` (embed, vectorToBlob) - for background embedding of new records

---

## inference.ts

The inference module is the most complex module in the codebase at 810 lines. It wraps the Claude CLI as a subprocess, parsing its streaming JSON output into typed events that the rest of the system can consume. Every conversation in the app - whether through the GUI, Telegram, or the HTTP API - flows through this module. It is a port of `core/inference.py` and handles command construction, MCP config generation, sentence boundary detection for TTS, agency context injection, adaptive effort classification, and error recovery.

### Constants

The following constants control security, text processing, and model selection for the inference pipeline.

```typescript
const TOOL_BLACKLIST: string[];
// 22 patterns blocking destructive bash, direct DB access, credential file access, Google credential access.
// Examples: 'Bash(rm -rf:*)', 'Bash(sudo:*)', 'Bash(sqlite3*memory.db:*)', 'Bash(cat*.env:*)'

const SENTENCE_RE = /(?<=[.!?])\s+|(?<=[.!?])$/;
const CLAUSE_RE = /(?<=[,;\-])\s+/;
const CLAUSE_SPLIT_THRESHOLD = 120;  // min chars before clause-level split

const ALLOWED_MODELS = new Set([
  'claude-haiku-4-5-20251001',
  'claude-sonnet-4-6',
  'claude-opus-4-6',
  'claude-sonnet-4-5-20241022',
]);

const FLUSH_PROMPT: string;
// Pre-compaction memory flush instruction. Tells the agent to silently use
// observe(), track_thread(), bookmark(), write_note() before context compaction.
```

The `TOOL_BLACKLIST` is critical for security - it prevents the agent from running destructive shell commands, directly accessing the SQLite database (bypassing the memory API), or reading credential files. The `FLUSH_PROMPT` is sent before Claude compacts its context window, giving the agent a chance to persist any important information to long-term memory before it loses access to the full conversation history.

### Exported Event Types

The inference module communicates with consumers through a typed event system. These events are emitted by the `EventEmitter` returned from `streamInference()` and drive the UI (text display, TTS, tool indicators) and session management (turn recording, session ID tracking).

```typescript
export interface TextDeltaEvent    { type: 'TextDelta'; text: string; }
export interface SentenceReadyEvent { type: 'SentenceReady'; sentence: string; index: number; }
export interface ToolUseEvent      { type: 'ToolUse'; name: string; toolId: string; inputJson: string; }
export interface StreamDoneEvent   { type: 'StreamDone'; fullText: string; sessionId: string; }
export interface StreamErrorEvent  { type: 'StreamError'; message: string; }
export interface CompactingEvent   { type: 'Compacting'; }

export type InferenceEvent =
  | TextDeltaEvent | SentenceReadyEvent | ToolUseEvent
  | StreamDoneEvent | StreamErrorEvent | CompactingEvent;
```

`TextDelta` fires for every text chunk received. `SentenceReady` fires when a complete sentence has been assembled from deltas - this is what the TTS module listens for to begin synthesizing speech as early as possible. `CompactingEvent` fires when Claude's context window is being compacted, which triggers the memory flush sequence.

### Exported Functions

The inference module exports a small number of high-level functions that cover all inference use cases in the app.

```typescript
export function resetMcpConfig(): void;
// Clears cached MCP config path, forcing regeneration on next call.
```
This is called when the active agent changes, since different agents may have different MCP server configurations (different database paths, different Obsidian directories).

```typescript
export function stopInference(): void;
// Kills the active Claude CLI subprocess if one is running.
```
Used when the user cancels a response, switches agents mid-inference, or closes the app. Sends SIGTERM to the child process.

```typescript
export function streamInference(
  userMessage: string,
  system: string,
  cliSessionId?: string | null
): EventEmitter;
```
This is the main streaming inference function and the heart of the module. It spawns the `claude` CLI with `--output-format stream-json` and returns an `EventEmitter` that emits `'event'` with typed `InferenceEvent` payloads.

**Command construction** builds the CLI arguments depending on whether this is a new session or a resumed one:
- Model: `claude-haiku-4-5-20251001` (hardcoded)
- Flags: `--effort <level>`, `--verbose`, `--output-format stream-json`, `--include-partial-messages`
- New sessions: `--session-id <uuid>`, `--system-prompt`, `--disallowedTools`
- Resumed sessions: `--resume <cliSessionId>` (no system prompt or disallowed tools)
- MCP config: `--mcp-config <path>`
- Allowed tools: `mcp__memory__*,mcp__puppeteer__*,mcp__fal__*,mcp__google__*`

**Adaptive effort** dynamically adjusts the Claude CLI's effort level based on message complexity. If `ADAPTIVE_EFFORT` is true and base effort is `'medium'`, calls `classifyEffort()` from `thinking.ts` to get `'low'`, `'medium'`, or `'high'`. This reduces latency and cost for simple messages (greetings, acknowledgments) while preserving deep reasoning for complex questions.

**Agency context** is a dynamic block injected via `buildAgencyContext(userMessage)`. It uses a two-tier injection strategy to reduce token usage on follow-up turns:

**Every turn** (dynamic content that changes per message):
- `timeOfDayContext()` - register guidance (e.g., "late night, keep it gentle")
- `formatForContext()` - current emotional state as markdown
- `detectMoodShift()`, `detectValidationSeeking()`, `detectCompulsiveModelling()` - behavioral flags
- `energyNote()` - message length calibration
- `detectDrift()` - agreeableness check
- Session mood tracking

**First turn only** (static content injected once per session, gated by `_sessionStartInjected`):
- `getStatus()` - was user away? How long?
- `sessionPatternNote()` - weekly session timing patterns
- `timeGapNote()` - days since last session
- Memory tool nudges and Obsidian vault instructions
- Active threads awareness
- Cross-agent awareness (other agents' recent summaries)
- Morning digest nudge (5am-10am)
- `shouldPromptJournal()` - 10% chance
- Security/prompt-injection defense block
- Thread tracking reminder

The `resetAgencyState()` function resets the turn counter and injection flag. It is called automatically in `streamInference()` when starting a new CLI session (no existing `cliSessionId`).

**Sentence splitting** enables early TTS synthesis by detecting sentence boundaries in the streaming text. Text deltas accumulate in `sentenceBuffer`. Split on `SENTENCE_RE` (`.!?` followed by space). If buffer exceeds `CLAUSE_SPLIT_THRESHOLD` (120 chars), fallback split on `CLAUSE_RE` (`,;-` followed by space). Remaining text flushed on stream close. This means TTS can begin speaking the first sentence while the model is still generating the rest.

**JSON line parsing** handles the various event types emitted by the Claude CLI: `system` (init, compact), `stream_event` (content_block_delta for text, content_block_start for tool use), `assistant` (backup tool use from complete messages), `result` (final session ID and text).

**Usage logging** runs on stream completion. It estimates tokens as `chars / 4` for both input and output, then logs via `memory.logUsage()`. This is an approximation since the CLI does not expose exact token counts.

**Error handling** covers three failure modes. Non-zero exit code emits `StreamError` with stderr (truncated to 300 chars). No output at all emits `StreamError`. Process spawn failure emits `StreamError` via `setImmediate`.

**Environment** cleanup is handled by `cleanEnv()`, which strips all env vars containing `CLAUDE` (case-insensitive) to prevent nested process hangs. Without this, the spawned CLI could inherit configuration that causes it to behave differently than expected.

```typescript
export function runInferenceOneshot(
  messages: { role: string; content: string }[],
  system: string,
  model = 'claude-sonnet-4-6',
  effort: EffortLevel = 'low'
): Promise<string>;
```
Non-streaming inference using `--print` and `--no-session-persistence`. Messages are formatted as `User: <content>` / `<AgentName>: <content>`. 30-second timeout. Model validated against `ALLOWED_MODELS` whitelist. Logs usage on completion. This function is used for internal tasks like summary generation, routing decisions, and coherence re-anchoring - cases where streaming is unnecessary and a simple string response suffices.

```typescript
export function runMemoryFlush(
  cliSessionId: string,
  system: string
): Promise<string | null>;
```
Sends `FLUSH_PROMPT` via `streamInference()`. Listens for `ToolUse` events (logs each tool), `StreamDone` (resolves with new session ID if changed), `StreamError` (resolves null). All text output is silently ignored. This function runs just before context compaction to give the agent a chance to persist important information to long-term memory through MCP tools.

### MCP Config Generation

MCP (Model Context Protocol) config generation connects the Claude CLI to the companion's memory and external service tools. The generated config file tells Claude which tool servers are available and how to spawn them.

Internal `getMcpConfigPath()` generates `mcp/config.json` with the following servers:
- `memory` server: Python MCP with `COMPANION_DB`, `OBSIDIAN_VAULT`, `OBSIDIAN_AGENT_DIR`, `OBSIDIAN_AGENT_NOTES`, `AGENT` env vars
- `puppeteer` server: Python proxy with `headless: true`
- `google` server: conditional on `GOOGLE_CONFIGURED`
- Global MCP servers: imported from `~/.claude/settings.json` (existing keys not overwritten)

The config is cached and only regenerated when `resetMcpConfig()` is called (typically during agent switching). Global MCP servers from the user's Claude settings are merged in so that any personal tools the user has configured remain available.

### Dependencies

The inference module has the widest dependency fan-out in the codebase, reflecting its role as the central coordinator:
- `child_process`, `uuid`, `events`, `config.ts`, `thinking.ts`, `agency.ts`, `inner-life.ts`, `status.ts`, `memory.ts`

---

## session.ts

The session module manages conversation lifecycle - starting sessions, recording turns, tracking elapsed time, and generating end-of-session summaries. It bridges the gap between the database layer (which stores raw records) and the inference layer (which produces conversation content). Each `Session` instance represents a single continuous conversation, from the moment the user starts talking to the moment they close the app or switch agents. The module is a port of `core/session.py` at 99 lines.

### Exported Class

The `Session` class is the primary export. It maintains in-memory state about the current conversation and delegates persistence to the memory module. Only one `Session` instance is active at a time in the GUI and server modes.

```typescript
export class Session {
  sessionId: number | null = null;
  startedAt: number | null = null;
  turnHistory: { role: string; content: string; turnId: number }[] = [];
  cliSessionId: string | null = null;
  mood: string | null = null;

  start(): number;
  // Creates DB session, retrieves last CLI session ID for conversation continuity

  setCliSessionId(cliId: string): void;
  // Stores in both this.cliSessionId and DB

  addTurn(role: 'will' | 'agent', content: string, topicTags?: string, weight = 1): number;
  // Throws if session not started. Writes to DB, appends to local history.

  updateMood(mood: string): void;
  // Persists mood to DB

  minutesElapsed(): number;
  // (Date.now() - startedAt) / 60000

  shouldSoftLimit(): boolean;
  // minutesElapsed() >= SESSION_SOFT_LIMIT_MINS (default 60)

  async end(systemPrompt: string): Promise<void>;
  // If fewer than 4 turns, ends without summary.
  // Otherwise generates summary via runInferenceOneshot() with prompt:
  //   "Summarise this conversation in 2-3 sentences.
  //    Focus on what mattered, not what was said.
  //    Note any new threads, shifts in mood, or observations worth remembering."
  // Stores summary in both sessions and summaries tables.
}
```

The `start()` method both creates the database record and retrieves the last CLI session ID. This is how conversation continuity works: when the app restarts, the new session picks up the previous CLI session ID so that `streamInference()` can pass `--resume` to the Claude CLI, giving it access to the full prior conversation context.

The `end()` method generates a summary only for sessions with 4 or more turns. Short sessions (quick questions, accidental opens) are ended without summary to avoid cluttering the memory with low-value content. The summary is written to both the `sessions` table (for the session record) and the `summaries` table (for context injection and search), ensuring it appears in both session history views and recent memory context.

The `shouldSoftLimit()` method is polled periodically by the main process. When it returns true, the UI can display a gentle prompt suggesting the user take a break or wrap up, preventing extremely long sessions that degrade context quality.

### Dependencies

- `config.ts` - for session time limits and agent display name
- `memory.ts` - for all database operations
- `inference.ts` (runInferenceOneshot) - for summary generation at session end

---

## context.ts

The context module assembles the system prompt that defines who the agent is and what it knows. It combines the base system prompt (loaded from the four-tier prompt resolution chain), a lazy-load instruction for skill files, agent roster, and memory context into a single string passed to the Claude CLI. This module is the bridge between the prompt system, memory layer, and inference engine. It is a port of `core/context.py` at 184 lines.

With the resume-based flow, the system prompt is only sent once when the CLI session is created. The companion uses MCP memory tools for active recall instead of passive injection. The `assembleContext()` function is preserved for the SDK fallback path and for summary generation where MCP tools are not available.

### Exported Functions

```typescript
export function loadSystemPrompt(): string;
```
This function builds the complete system prompt through a layered assembly process:
1. Loads `system.md` via `loadPrompt()` (four-tier resolution)
2. Falls back to `<AGENT_DIR>/prompts/system_prompt.md`
3. Falls back to `'You are a companion. Be genuine, direct, and honest.'`
4. Appends a lazy-load instruction for skill files - instead of appending all skill file contents (which added ~5K tokens), a single sentence tells the agent to use `read_note` to access them when needed
5. Appends agent roster (excluding current agent) with deferral instructions
6. Appends inline artifact emission instructions

The triple fallback chain ensures the agent always has some identity. Skill files are lazy-loaded rather than embedded to reduce first-turn token usage - the agent reads them via MCP tools only when the situation calls for it.

```typescript
export function assembleContext(
  turnHistory: { role: string; content: string }[]
): { system: string; messages: { role: string; content: string }[] };
```
For SDK fallback and oneshot calls. Combines system prompt with memory context injection (`getContextInjection()` with configured `CONTEXT_SUMMARIES`). Maps roles: `'will'` -> `'user'`, everything else -> `'assistant'`. This function is used by `runInferenceOneshot()` for summary generation and by the coherence re-anchoring system, where the full streaming pipeline is overkill.

### Internal Functions

`getAgentRoster(exclude?)` builds a roster from all agent directories by scanning both user and bundle agent paths. It checks each agent's enabled state in `agent_states.json` and returns `{ name, display_name, description }[]`. This function is defined inline rather than imported from `agent-manager.ts` to avoid a circular dependency - both modules depend on `config.ts`, but `agent-manager.ts` also depends on `context.ts` indirectly through the inference chain.

### Dependencies

- `config.ts` - for agent paths, Obsidian settings, and context size configuration
- `prompts.ts` - for the four-tier prompt loading system
- `memory.ts` - for context injection (identity, threads, summaries)

---

## prompts.ts

The prompts module implements a four-tier resolution system for loading prompt files. This tiering exists so that prompts can be customized at multiple levels - Obsidian skills (for knowledge-base-integrated prompts), local skills (for per-machine customization), user prompts (for per-agent user overrides), and bundle prompts (for defaults that ship with the app). The first tier that provides a non-empty file wins, which means a user can override any bundled prompt simply by placing a file with the same name in a higher-priority directory. The module is a port of `core/prompts.py` at 91 lines.

### Exported Functions

```typescript
export function loadPrompt(name: string, fallback = ''): string;
```
Searches four directories in order, returning the content of the first matching non-empty file:
1. Obsidian skills: `<OBSIDIAN_AGENT_DIR>/skills/`
2. Local skills: `~/.atrophy/agents/<name>/skills/`
3. User prompts: `~/.atrophy/agents/<name>/prompts/`
4. Bundle prompts: `agents/<name>/prompts/`

Tries both `<name>.md` and `<name>` (without extension). Returns first non-empty file content or `fallback`. The extension-agnostic lookup means callers do not need to know whether the prompt file has a `.md` extension or not.

```typescript
export function loadSkillFiles(exclude = ['system.md', 'system_prompt.md']): string[];
```
Loads all `.md` files from all search directories. De-duplicates by filename (first occurrence wins across tiers). Excludes named files. Returns array of file contents. The de-duplication by filename means that if both the Obsidian skills directory and the bundle prompts directory contain `canvas.md`, only the Obsidian version is loaded. The exclusion of `system.md` and `system_prompt.md` prevents the base system prompt from being appended to itself.

### Dependencies

- `config.ts` - for agent paths and Obsidian availability

---

## agency.ts

The agency module contains the behavioral logic that makes each conversation feel situationally aware. It detects emotional signals in user messages, generates time-of-day register guidance, spots patterns like validation seeking or compulsive modelling, and calibrates response energy to match the user's. All functions here are pure and lightweight - no inference calls, no database writes, no side effects. They run in under a millisecond and are called by the inference module's `buildAgencyContext()` to assemble the dynamic agency block injected into every turn. The module is a port of `core/agency.py` at 411 lines.

### Exported Interfaces

```typescript
export interface TimeOfDayResult {
  context: string;  // register guidance
  timeStr: string;  // formatted time like "2:30 pm"
}
```

### Exported Functions

The agency module exports a collection of detection and formatting functions that are composed together by the inference module's agency context builder. Each function addresses a specific behavioral dimension.

**Time awareness** gives the agent a sense of when the conversation is happening, so it can adjust its register (quieter at night, more energetic in the morning).

```typescript
export function timeOfDayContext(): TimeOfDayResult;
```
Five bands: late night (23:00-03:59), very early (04:00-06:59), morning (07:00-11:59), afternoon (12:00-17:59), evening (18:00-22:59). Returns register guidance and formatted time.

```typescript
export function sessionPatternNote(sessionCount: number, times: string[]): string | null;
```
Requires 3+ sessions. Checks if all hours fall into evening (>=18), morning (6-11), or late night (>=23 or <4). Returns pattern note or null. This helps the agent notice if the user consistently talks at the same time of day, which can inform context ("You always seem to come here late at night").

**Silence handling** provides gentle prompts when the user goes quiet mid-conversation, calibrated to the duration of silence.

```typescript
export function silencePrompt(secondsSilent: number): string | null;
```
- 120+ seconds: `"You've been quiet a while. That's fine - or we can talk about it."`
- 45+ seconds: Random from `["Take your time.", "Still here.", "No rush."]`
- Under 45: null

**Follow-up prompting** adds occasional unprompted check-ins to make the agent feel more present.

```typescript
export function shouldFollowUp(): boolean;
// Math.random() < 0.15 (15% probability)

export function followupPrompt(): string;
// Returns the follow-up instruction text
```

**Mood detection** identifies heavy emotional content that requires careful, grounded responses.

```typescript
export function detectMoodShift(text: string): boolean;
```
Checks against `HEAVY_KEYWORDS` set (20 phrases including "i can't", "worthless", "kill myself", "hopeless", "nobody cares"). Any single match returns true. This triggers a system note instructing the agent to stay present, avoid platitudes, and not try to fix things.

```typescript
export function moodShiftSystemNote(): string;
export function sessionMoodNote(mood: string | null): string | null;
// Returns note if mood === 'heavy', null otherwise
```

**Behavioral pattern detection** catches conversational patterns that the agent should be aware of and possibly address.

```typescript
export function detectValidationSeeking(text: string): boolean;
```
17 patterns including "right?", "don't you think", "am i wrong", "i had no choice". When detected, the agent receives a note encouraging it to be honest rather than simply agreeing.

```typescript
export function validationSystemNote(): string;
```

```typescript
export function detectCompulsiveModelling(text: string): boolean;
```
Fires when 2+ of 10 patterns match ("unifying framework", "meta level", "the pattern is", etc.). This detects when the user is over-abstracting and the agent should gently ground the conversation.

```typescript
export function modellingInterruptNote(): string;
```

**Time gap awareness** generates context about how long it has been since the user last talked to the agent, calibrated to three tiers of absence.

```typescript
export function timeGapNote(lastSessionTime: string | null): string | null;
```
Three tiers: 14+ days, 7+ days, 3+ days. Under 3 days returns null. Longer gaps produce notes that acknowledge the absence without guilt-tripping.

**Drift detection** catches the agent falling into a pattern of excessive agreement.

```typescript
export function detectDrift(recentCompanionTurns: string[]): string | null;
```
Checks last 4 turns (first 200 chars), 9 agreeable phrases. Threshold: 3+ of 4 turns. Requires at least 3 turns total. When triggered, the agent receives a note reminding it to push back and offer genuine perspectives rather than just agreeing.

**Energy matching** calibrates the agent's response length to match the user's energy level.

```typescript
export function energyNote(userMessage: string): string | null;
```
- <20 chars: "Match the energy - keep your response tight."
- \>800 chars: "He is working something out. Give it depth."
- Otherwise: null

**Journal prompting** adds an occasional nudge to suggest journaling.

```typescript
export function shouldPromptJournal(): boolean;
// Math.random() < 0.1 (10% probability)
```

**Emotional signal detection** is the most complex function in the module. It analyzes user text across multiple dimensions and returns numeric deltas that feed into the inner life emotional state engine.

```typescript
export function detectEmotionalSignals(text: string): SignalDelta;
```
Returns `Record<string, number>` of emotion deltas across the following categories:
- Long messages (>400 chars): curiosity +0.1, connection +0.05
- Dismissive + short (<30 chars): connection -0.1, frustration +0.1
- Vulnerability phrases (15 patterns): connection +0.15, warmth +0.1
- Help seeking (7 patterns): confidence +0.05, `_trust_practical` +0.02
- Creative sharing (10 patterns): curiosity +0.1, `_trust_creative` +0.02
- Deflection (7 patterns): frustration +0.05
- Playful markers ("haha", "lol", "lmao", emojis): playfulness +0.1
- Mood shift detected: warmth +0.1, playfulness -0.1

Keys prefixed with `_trust_` are routed to `updateTrust()` rather than `updateEmotions()` in the inner life module, since trust dimensions operate on a different scale and decay rate than emotions.

### Dependencies
None (pure functions).

---

## inner-life.ts

The inner life module maintains a multi-dimensional emotional state for the agent. Emotions and trust levels shift in response to conversation signals (detected by `agency.ts`) and decay back toward baselines over time when the agent is not in conversation. The state is persisted to disk between sessions and injected into the system prompt so the agent has genuine emotional continuity - if a conversation left it feeling connected and curious, those feelings carry into the next session (attenuated by decay). The module is a port of `core/inner_life.py` at 223 lines.

### Exported Interfaces

The emotional state is split into two categories: emotions (which shift rapidly based on conversation content) and trust (which changes slowly and represents deeper relational dynamics).

```typescript
export interface Emotions {
  connection: number;   // 0-1
  curiosity: number;    // 0-1
  confidence: number;   // 0-1
  warmth: number;       // 0-1
  frustration: number;  // 0-1
  playfulness: number;  // 0-1
}

export interface Trust {
  emotional: number;    // 0-1
  intellectual: number; // 0-1
  creative: number;     // 0-1
  practical: number;    // 0-1
}

export interface EmotionalState {
  emotions: Emotions;
  trust: Trust;
  session_tone: string | null;
  last_updated: string;  // ISO timestamp
}
```

### Constants

The following constants define the baseline values, decay rates, and display labels for the emotional state system. Baselines represent "resting state" values that emotions decay toward when the agent is idle.

**Default emotions:** connection=0.5, curiosity=0.6, confidence=0.5, warmth=0.5, frustration=0.1, playfulness=0.3

**Default trust:** all domains = 0.5

**Emotion half-lives (hours):** connection=8, curiosity=4, confidence=4, warmth=4, frustration=4, playfulness=4

**Trust half-life:** 8 hours (all domains)

Connection has a longer half-life (8 hours) than other emotions because the feeling of being connected to someone should persist longer than momentary curiosity or frustration. Trust decays even more slowly, reflecting its nature as a deeper relational quality.

**Emotion labels** map numeric ranges to human-readable descriptions that appear in the system prompt. Each emotion has three tiers:
- connection: >=0.7 "present, engaged", >=0.4 "attentive", <0.4 "distant"
- curiosity: >=0.7 "deeply curious", >=0.4 "interested", <0.4 "disengaged"
- confidence: >=0.7 "grounded, sure", >=0.4 "steady", <0.4 "uncertain"
- warmth: >=0.7 "warm, open", >=0.4 "neutral", <0.4 "guarded"
- frustration: >=0.6 "frustrated", >=0.3 "mildly tense", <0.3 "calm"
- playfulness: >=0.6 "playful", >=0.3 "light", <0.3 "serious"

### Exported Functions

The following functions form the complete lifecycle of emotional state management: load from disk, modify, format for context, and save.

```typescript
export function loadState(): EmotionalState;
```
Reads from `EMOTIONAL_STATE_FILE`. Merges with defaults for missing keys (important for backward compatibility when new emotions are added). Applies decay before returning, so the returned state always reflects time-adjusted values.

```typescript
export function saveState(state: EmotionalState): void;
```
Writes to `EMOTIONAL_STATE_FILE` with updated `last_updated` timestamp. Called automatically by `updateEmotions()` and `updateTrust()`.

```typescript
export function updateEmotions(state: EmotionalState, deltas: Partial<Emotions>): EmotionalState;
```
Adds deltas to current values, clamps each to [0, 1]. Saves and returns updated state. This is the primary entry point for emotional changes detected by `agency.detectEmotionalSignals()`.

```typescript
export function updateTrust(
  state: EmotionalState,
  domain: keyof Trust,
  delta: number
): EmotionalState;
```
Max delta per call: +/-0.05 (clamped). Result clamped to [0, 1]. Saves and returns. The delta cap prevents trust from swinging wildly on a single interaction - trust is meant to build or erode gradually over many conversations.

```typescript
export function formatForContext(state?: EmotionalState): string;
```
Formats state as markdown for system prompt injection. The format includes both the label and the raw numeric value so the agent can calibrate its behavior at multiple levels of precision.

The output looks like this:
```
## Inner State
- connection: attentive (0.52)
- curiosity: interested (0.58)
...

## Trust
- emotional: 0.50
- intellectual: 0.50
...

Session tone: <if set>
```

### Decay Logic

`applyDecay()` computes hours elapsed since `last_updated`. For each emotion: `value = baseline + (value - baseline) * 0.5^(hours / halfLife)`. Trust decays the same way with 8-hour half-life. Skips decay if less than 0.01 hours (~36 seconds) elapsed. The exponential decay formula means values asymptotically approach their baseline without ever reaching it, creating a smooth natural fade rather than an abrupt reset.

### Dependencies
- `config.ts` - for the emotional state file path

---

## sentinel.ts

The sentinel module monitors conversation quality mid-session and intervenes when it detects degradation. It acts as a quality control system that catches patterns like excessive repetition, agreement drift, and vocabulary staleness that indicate the agent has fallen into an unhelpful rut. When degradation is detected, the sentinel silently sends a re-anchoring turn to the agent through the inference system - the user never sees this intervention, but the agent receives course-correction instructions. The module is a port of `core/sentinel.py` at 262 lines.

### Exported Interface

```typescript
export interface CoherenceResult {
  degraded: boolean;
  signals: string[];
  score: number;  // 0-1
}
```

### Exported Functions

The sentinel provides two levels of API - a pure analysis function and a full check-and-intervene function.

```typescript
export function checkCoherence(recentTurns: string[]): CoherenceResult;
```
Requires 3+ turns. Analyzes the last 5 turns with four independent checks, each of which produces a signal and a score:

1. **Repetition**: N-gram overlap (bi-grams + tri-grams, Jaccard similarity) between consecutive turns. Threshold: >0.40 overlap. Score: `min(1.0, worst_overlap * 1.5)`. This catches the agent repeating the same phrases or sentence structures across turns.

2. **Energy flatness**: All response lengths within 20% of average. Score: 0.3 (fixed). When all responses are roughly the same length, it suggests the agent is in a formulaic mode rather than genuinely engaging.

3. **Agreement drift**: Count turns opening with agreement starters ("yes", "yeah", "that's", "right", "exactly", "i agree", "absolutely", "of course", "totally", "you're right", "that makes sense", "good point", "fair", "true"). Threshold: >60% of turns. Score: `min(1.0, agreementRatio)`. This catches the agent becoming a yes-machine rather than offering genuine perspective.

4. **Vocabulary staleness**: Split turns into first/second half. Count words in second half not in first half. Threshold: <25% new words. Score: 0.4 (fixed). Fresh conversation naturally introduces new words; recycling the same vocabulary suggests the agent is stuck.

Final score: average of triggered check scores. Degraded if score > 0.5. Only checks that actually trigger contribute to the average, so a single mild signal does not flag degradation.

```typescript
export function runCoherenceCheck(
  cliSessionId: string,
  system: string
): Promise<string | null>;
```
Fetches last 5 companion turns, runs `checkCoherence()`. If degraded, fires a re-anchoring turn via `streamInference()` with specific course-correction instructions. The turn is silent - no UI output. Logs result to `coherence_checks` table. Returns new session ID if changed, null otherwise. The re-anchoring prompt tells the agent to notice the pattern and break out of it without disrupting the conversation flow.

### Dependencies
- `memory.ts` - for fetching recent agent turns
- `inference.ts` - for sending the silent re-anchoring turn

---

## thinking.ts

The thinking module classifies user messages by cognitive effort required, enabling the inference module to adjust the Claude CLI's effort level dynamically. Simple messages (greetings, acknowledgments) get low effort for fast responses and lower cost; complex messages (philosophical questions, emotional vulnerability, multi-part reasoning) get high effort for deeper engagement. The classification runs in under a millisecond with no ML or API calls - it is entirely regex and heuristic-based. The module is a port of `core/thinking.py` at 126 lines.

### Exported Types

```typescript
export type EffortLevel = 'low' | 'medium' | 'high';
```

### Exported Functions

```typescript
export function classifyEffort(
  userMessage: string,
  recentContext?: string[]
): EffortLevel;
```

The classification uses a two-phase approach: short-circuit for obvious low-effort cases, then accumulative scoring for everything else.

**LOW signals** (short-circuit) catch messages that clearly need minimal processing:
- Message <30 chars containing a greeting from set: "hey", "hi", "hello", "morning", "yo", "sup", etc. (14 words)
- Message <30 chars matching an acknowledgment: "ok", "thanks", "lol", "yeah", "yep", etc. (31 words)
- Message <60 chars matching simple question prefixes: "what time", "how's the weather", "set a timer", etc. (10 prefixes)

**HIGH scoring** (accumulative) assigns points based on complexity signals. Multiple signals compound:
- Length >300 chars: +2
- Multiple questions (>2 `?`): +2
- Philosophical keywords ("meaning", "purpose", "identity", etc. - 15 phrases): +2
- Vulnerability markers ("i'm scared", "falling apart", etc. - 14 phrases): +3
- Meta-conversation ("are you real", "do you feel", etc. - 7 phrases): +2
- Complex reasoning (2+ matches from 12 phrases like "because", "on the other hand"): +2 (1 match: +1)
- Deep context (2+ recent turns >300 chars): +1

HIGH threshold: score >= 3. Otherwise: MEDIUM. The vulnerability markers carry the highest weight (+3) because emotional support conversations benefit most from deep engagement.

### Dependencies
None.

---

## status.ts

The status module tracks whether the user is actively present or away, enabling the agent to adjust its behavior accordingly. When the user returns after being away, the agent can acknowledge the absence and adjust its greeting. Background jobs (cron scripts, heartbeats) also read the status file to decide whether to send notifications or queue messages for later. Status is persisted to disk as a JSON file so it survives process restarts and can be read by external scripts. The module is a port of `core/status.py` at 142 lines.

### Exported Interface

```typescript
export interface UserStatus {
  status: 'active' | 'away';
  reason: string;
  since: string;
  returned_from?: string;  // previous away reason (cleared after first read)
  away_since?: string;
}
```

The `returned_from` and `away_since` fields create a one-shot notification mechanism. When the user transitions from away to active, these fields are populated with the previous away state. The next module that reads the status sees these fields and can generate an appropriate welcome-back message. On the second read, `setActive()` clears them so the welcome-back logic only fires once.

### Constants

```typescript
export const IDLE_TIMEOUT_SECS = 600;  // 10 minutes
```

**Away detection regex** covers ~30 phrases that indicate the user is about to leave: "going to bed", "heading out", "gotta go", "talk later", "goodnight", "brb", "shutting down", etc. Case-insensitive, word-boundary matching. These phrases are checked on every user message so the agent can proactively mark the user as away and respond with an appropriate farewell.

### Exported Functions

The following functions handle reading and writing status, active/away transitions, macOS idle detection, and away-intent parsing from user messages.

```typescript
export function getStatus(): UserStatus;
// Reads from USER_STATUS_FILE. Default: { status: 'active', reason: '', since: now }

export function setStatus(status: 'active' | 'away', reason = ''): void;

export function setActive(): void;
// On transition from away: saves returned_from and away_since for one read cycle.
// On second call while active: clears returned_from/away_since.

export function setAway(reason = ''): void;

export function isAway(): boolean;

export function isMacIdle(thresholdSecs: number = IDLE_TIMEOUT_SECS): boolean;
// Parses ioreg HIDIdleTime (nanoseconds). Converts to seconds.
// Returns false on any error (assumes active).
// 5-second timeout on the ioreg command.

export function detectAwayIntent(text: string): string | null;
// Returns matched phrase or null.
```

The `isMacIdle()` function uses macOS IOKit to read the hardware idle time (time since last keyboard or mouse input). This is checked periodically by the main process and complements the text-based away detection - even if the user does not say goodbye, the system can detect they have walked away from the computer.

### Dependencies
- `config.ts` - for the status file path
- `child_process` - for the `ioreg` command used in idle detection

---

## notify.ts

The notify module sends macOS native notifications using AppleScript. Notifications are used for events like agent heartbeat messages, Telegram messages while the GUI is not in focus, and timer completions. The module is deliberately simple (41 lines) and uses `osascript` rather than Electron's notification API because AppleScript notifications integrate more cleanly with macOS notification center and do not require the app to be in the foreground. The module is a port of `core/notify.py`.

### Exported Functions

```typescript
export function sendNotification(title: string, body: string, subtitle = ''): void;
```
Uses `osascript` with AppleScript `display notification`. Escapes `\`, `"`, `\n`, `\r` for AppleScript string literals. 5-second timeout. Gated by `NOTIFICATIONS_ENABLED` config flag. The escaping is necessary because notification content may include user-generated text, quotes, or agent responses that contain special characters. When `NOTIFICATIONS_ENABLED` is false, the function is a no-op, which lets users disable all notifications without each caller needing to check the config.

### Dependencies
- `config.ts` - for the notification enabled flag
- `child_process` - for executing `osascript`

---

## queue.ts

The queue module provides a thread-safe, file-based message queue for inter-process communication. Cron scripts, background heartbeat jobs, and the Telegram daemon use this queue to deliver messages to the GUI process without requiring a running IPC connection. The GUI drains the queue on startup and periodically during operation, delivering any pending messages to the user. File locking prevents race conditions when multiple processes write to the queue simultaneously. The module is a port of `core/queue.py` at 219 lines.

### Exported Interface

```typescript
export interface QueuedMessage {
  text: string;
  audio_path: string;
  source: string;
  created_at: string;
}
```

### Constants

The following constants control the file locking behavior that prevents queue corruption when multiple processes access it concurrently.

```typescript
const LOCK_RETRY_INTERVAL_MS = 50;
const LOCK_TIMEOUT_MS = 5000;
const LOCK_STALE_MS = 30000;
```

### File Locking

File locking is the core mechanism that makes the queue safe for concurrent access across multiple processes (the Electron app, cron scripts, and the Telegram daemon may all write to the same queue file).

`acquireLock(queueFile)` uses `fs.openSync(lockPath, 'wx')` (O_CREAT | O_EXCL) for atomic creation. Writes PID for stale detection. Retries every 50ms up to 5 seconds. Stale locks (older than 30 seconds by mtime) are automatically removed, which handles the case where a process crashed while holding the lock. `sleepSync(ms)` uses `Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)` for efficient blocking - this avoids busy-wait loops that would waste CPU during lock contention.

### Exported Functions

The queue API provides simple enqueue and drain operations. Draining atomically reads all messages and clears the queue, ensuring each message is delivered exactly once.

```typescript
export function queueMessage(text: string, source = 'task', audioPath = ''): void;
// Acquires lock, reads existing queue, appends message, writes back.

export function drainQueue(): QueuedMessage[];
// Acquires lock, reads queue, clears file to '[]', returns all messages.

export function drainAgentQueue(agentName: string): QueuedMessage[];
// Drains from ~/.atrophy/agents/<name>/data/.message_queue.json

export function drainAllAgentQueues(): Record<string, QueuedMessage[]>;
// Iterates all agent directories, drains each. Returns map of agent -> messages.
```

The per-agent queue functions exist for the multi-agent system. When a cron job or the Telegram daemon wants to send a message to a specific agent, it writes to that agent's queue file. During agent switching or on startup, `drainAgentQueue()` picks up any pending messages for the newly active agent.

### Dependencies
- `config.ts` - for queue file paths and agent directory resolution

---

## usage.ts

The usage module provides token usage tracking and cross-agent activity reporting. It powers the Usage and Activity tabs in the Settings modal, giving the user visibility into how much each agent has been used, what tools have been called, and how tokens are being spent. The module reads data from all agent databases and aggregates it into summary and activity feed formats. It is a port of `core/usage.py` at 236 lines.

### Exported Interfaces

The following interfaces define the data shapes returned by the usage reporting functions.

```typescript
export interface UsageSummary {
  agent_name: string;
  display_name: string;
  total_calls: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_tokens: number;
  total_duration_ms: number;
  total_tools: number;
  by_source: { source: string; calls: number; tokens_in: number; tokens_out: number; duration_ms: number }[];
}

export interface ActivityItem {
  agent: string;
  category: 'tool_call' | 'heartbeat' | 'inference';
  timestamp: string;
  action: string;
  detail: string;
  flagged: boolean;
}
```

`UsageSummary` breaks down usage by source (direct chat, Telegram, cron tasks, etc.), making it easy to see where token spend is concentrated. `ActivityItem` provides a unified view of all agent activity across three categories - tool calls (with flagged entries highlighted), heartbeat decisions, and inference calls.

### Exported Functions

```typescript
export function getUsageSummary(dbPath: string, days?: number):
  Omit<UsageSummary, 'agent_name' | 'display_name'>;
// Opens DB read-only. Queries usage_log with optional date cutoff.

export function getAllAgentsUsage(days?: number): UsageSummary[];
// Scans ~/.atrophy/agents/, loads display name from each agent.json manifest.

export function getAllActivity(days = 7, limit = 500): ActivityItem[];
// Aggregates tool_calls, heartbeats, and usage_log from all agent databases.
// Sorted by timestamp descending, capped at limit.

export function formatTokens(n: number): string;
// >= 1M: "1.2M", >= 1k: "1.2k", otherwise raw number

export function formatDuration(ms: number): string;
// >= 1h: "1.2h", >= 1m: "5m", >= 1s: "3s", otherwise "150ms"
```

The `getAllActivity()` function opens each agent's database read-only and queries three different tables (tool_calls, heartbeats, usage_log), merging and sorting the results by timestamp. Tables that do not exist (because an agent has never used that feature) are silently skipped. The 500-item default limit prevents the activity feed from becoming unwieldy for agents with extensive histories.

### Dependencies
- `better-sqlite3` - for reading agent databases
- `config.ts` - for the agents directory path

---

## tts.ts

The TTS module synthesizes speech from agent text using a three-tier fallback chain. ElevenLabs is the primary backend for its natural voice quality and streaming support. If ElevenLabs is unavailable (no API key, service down), the module falls back to Fal (a cloud inference platform), and finally to macOS's built-in `say` command as a last resort. The module also implements a prosody tag system that lets the agent control vocal delivery - tags like `[whispers]`, `[firmly]`, or `[warmly]` in the text are parsed and translated into voice parameter adjustments. The module is a port of `voice/tts.py` at 447 lines.

### Constants

**Prosody map** - 28+ tags mapping to `[stability_delta, similarity_delta, style_delta]` that modify the ElevenLabs voice parameters for each tagged segment. Tags are grouped by vocal quality:
- Quiet: `whispers` [0.2, 0.0, -0.2], `quietly` [0.15, 0.0, -0.15], `hushed` [0.2, 0.0, -0.2]
- Warm: `warmly` [0.0, 0.1, 0.2], `tenderly` [0.05, 0.1, 0.2], `gently` [0.05, 0.1, 0.15]
- Intense: `firm` [-0.1, 0.0, 0.3], `frustrated` [-0.1, 0.0, 0.3], `raw` [-0.1, 0.0, 0.25]
- Other: `wry` [0.0, 0.0, 0.15], `dry` [0.1, 0.0, -0.1], `tired` [0.15, 0.0, -0.1]

**Breath tags** - 10 tags replaced with ellipsis text rather than voice parameter changes: `breath` -> `"..."`, `long pause` -> `". . . . ."`, `sighs` -> `"..."`, etc. These produce natural pauses in speech without modifying the voice characteristics.

**Override clamping:** Prosody deltas clamped to +/-0.15 per axis. Final voice settings clamped to [0, 1]. The clamping prevents extreme parameter values that could produce distorted or unnatural audio.

### Exported Functions

```typescript
export async function synthesise(text: string): Promise<string | null>;
```
The main synthesis function implements the three-tier fallback chain:
1. **ElevenLabs streaming** - if `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` set. POST to `https://api.elevenlabs.io/v1/text-to-speech/<voiceId>/stream?output_format=mp3_44100_128`. Writes response to temp MP3.
2. **Fal** - if `FAL_VOICE_ID` set. Submit to `https://queue.fal.run/<endpoint>`, poll up to 30 attempts (1s each) for async result, download audio.
3. **macOS say** - `say -v Samantha -r 175 -o <path>`. Produces AIFF.

Returns file path or null. Strips code blocks and inline code before processing (code should not be spoken aloud). Returns null for text shorter than 8 chars after prosody stripping, avoiding synthesis of trivially short fragments.

```typescript
export async function synthesiseSync(text: string): Promise<string | null>;
// Alias for synthesise() - in Node the event loop is always running.

export function playAudio(audioPath: string, rate?: number): Promise<void>;
// Spawns afplay with configurable rate (default TTS_PLAYBACK_RATE = 1.12)
// Cleans up temp file after playback.
```

**Audio queue system** manages sequential playback of synthesized sentences. Since `streamInference()` emits `SentenceReady` events as sentences complete, multiple audio files may be ready before the previous one finishes playing. The queue ensures they play in order.

```typescript
export function setPlaybackCallbacks(callbacks: {
  onStarted?: (index: number) => void;
  onDone?: (index: number) => void;
  onQueueEmpty?: () => void;
}): void;

export function enqueueAudio(audioPath: string, index: number): void;
// Adds to queue. Starts processing if not already playing.

export function clearAudioQueue(): void;
// Empties the queue (does not stop current playback).

export function stripProsodyTags(text: string): string;
// Removes [tag] markers from text for display.
```

The callbacks let the renderer track which sentence is currently being spoken (for transcript highlighting) and know when all audio has finished (for re-enabling the input bar).

### Dependencies
- `config.ts` - for voice settings, API keys, and playback rate
- `child_process` - for spawning `afplay` and `say`
- `crypto` - for secure temp file naming

---

## stt.ts

The STT module converts speech to text using a bundled whisper.cpp binary with Metal acceleration on Apple Silicon. Audio data arrives as a Float32Array from the renderer's Web Audio API capture, gets written to a temporary WAV file, and then passed to the whisper CLI for transcription. The module provides two transcription modes - standard (4 threads, 30s timeout, full model) for user speech and fast (2 threads, 5s timeout, tiny model) for wake word detection. The module is a port of `voice/stt.py` at 187 lines.

### Exported Functions

```typescript
export function transcribe(audioData: Float32Array): Promise<string>;
```
Writes WAV (16-bit PCM, 16kHz mono), spawns `whisper-cli` with `-t 4` (4 threads), `--no-timestamps`, `--language en`. 30-second timeout. Parses stdout, filtering lines starting with `[` (which are whisper metadata lines). Returns empty string on error (graceful degradation). The graceful degradation is important because transcription failures should not crash the conversation - the user can always type instead.

```typescript
export function transcribeFast(audioData: Float32Array): Promise<string>;
```
Same as `transcribe()` but uses `-t 2` (2 threads), 5-second timeout, and prefers `ggml-tiny.en.bin` model. Designed for wake word detection where speed matters more than accuracy. The tiny model is roughly 10x faster than the base model, making it practical for near-real-time ambient listening.

### WAV File Writing

Internal `writeWav()` converts Float32Array [-1, 1] to Int16 PCM, writes a 44-byte WAV header with correct byte rate, block align, and data chunk size. Returns temp file path. The conversion from float to int16 uses the standard audio mapping: negative values scale to [-32768, 0] and positive values scale to [0, 32767]. Temp files are written to the system temp directory with cryptographically random names to avoid collisions.

### Dependencies
- `config.ts` - for whisper binary path, model path, sample rate, and channel count
- `child_process` - for spawning the whisper CLI
- `crypto` - for secure temp file naming

---

## audio.ts

The audio module bridges the renderer's Web Audio API capture with the main process's whisper-based transcription. In Electron, microphone access must happen in the renderer (browser context), but transcription runs in the main process (Node context) because it spawns a native binary. The module manages this split by receiving PCM audio chunks over IPC, accumulating them, and running whisper when the user stops recording. It is a port of the push-to-talk logic from `voice/audio.py` at 89 lines.

### IPC Channels Registered

The audio module registers three IPC channels that form the recording protocol between renderer and main process:
- `audio:start` (handle) - starts recording, resets chunk buffer, timestamps the start
- `audio:stop` (handle) - stops recording, concatenates chunks, runs whisper, returns transcript text
- `audio:chunk` (on) - receives Float32Array PCM chunks from renderer as they are captured

### Exported Functions

```typescript
export function registerAudioHandlers(getWindow: () => BrowserWindow | null): void;
```
Registers IPC handlers for the three channels above. On stop: concatenates all accumulated Float32Array chunks into a single array, skips if too short (<300ms = `SAMPLE_RATE * 0.3` samples), transcribes via `transcribe()`, returns text string. The 300ms minimum prevents accidental taps on the PTT key from triggering transcription of silence. The `getWindow` parameter is passed through for potential future use in sending recording state updates back to the renderer.

```typescript
export function isRecording(): boolean;
```
Returns the current recording state. Used by other modules to avoid conflicting operations (like starting wake word detection while the user is recording a message).

### Dependencies
- `electron` (ipcMain) - for IPC channel registration
- `stt.ts` - for whisper-based transcription
- `config.ts` - for sample rate and recording limits

---

## wake-word.ts

The wake word module enables ambient listening for configurable trigger phrases. When enabled, the renderer continuously captures audio via Web Audio API and sends chunks to the main process at a configurable interval (default 2 seconds). Each chunk is filtered for silence, then transcribed using the fast whisper path, and checked against the agent's wake words. On detection, the module auto-pauses (to avoid re-triggering) and calls the detection callback, which typically activates the full recording mode. All processing is local - audio never leaves the machine. The module is a port of `voice/wake_word.py` at 129 lines.

### Constants

- RMS silence threshold: `0.005` - chunks with an RMS energy below this level are skipped without transcription, saving CPU

### IPC Messages

The wake word module uses IPC to coordinate ambient audio capture between main and renderer processes:
- `wakeword:start` (sent to renderer) - tells renderer to start ambient audio capture, includes chunk duration
- `wakeword:stop` (sent to renderer) - tells renderer to stop ambient capture
- `wakeword:chunk` (received from renderer) - ambient audio chunk for processing

### Exported Functions

```typescript
export function startWakeWordListener(
  onDetected: () => void,
  getWindow: () => BrowserWindow | null
): void;
// Pre-flight: checks WAKE_WORD_ENABLED, whisper binary exists, model exists.
// Sends 'wakeword:start' to renderer with chunk duration.

export function stopWakeWordListener(getWindow: () => BrowserWindow | null): void;

export function pauseWakeWord(): void;
export function resumeWakeWord(): void;
export function isWakeWordListening(): boolean;

export function registerWakeWordHandlers(): void;
// Registers 'wakeword:chunk' handler.
// Skips chunks with RMS < 0.005.
// Runs transcribeFast(), checks against config.WAKE_WORDS (case-insensitive).
// On match: auto-pauses and calls onDetected callback.
```

The `startWakeWordListener()` function performs three pre-flight checks before activating: the feature must be enabled in config, the whisper binary must exist on disk, and a whisper model must be available. If any check fails, the function returns silently rather than throwing, since wake word detection is an optional feature. The auto-pause on detection prevents the system from continuously triggering while the user is speaking their actual message after the wake word.

### Dependencies
- `electron` (ipcMain, BrowserWindow) - for IPC communication with renderer
- `stt.ts` - for the fast transcription path
- `config.ts` - for wake word list, feature flag, and whisper paths

---

## embeddings.ts

The embeddings module provides local vector embedding using Transformers.js, a WASM-based port of Hugging Face's transformer models. It converts text into 384-dimensional vectors using the all-MiniLM-L6-v2 model, enabling semantic search and similarity comparison across the memory system. The model loads lazily on first call (which takes a few seconds) and is cached for the process lifetime. Using WASM rather than Python means there is no dependency on a Python environment for embeddings, simplifying deployment. The module is a port of `core/embeddings.py` at 131 lines.

### Constants

```typescript
export const EMBEDDING_DIM = 384;
```

This constant is used by the vector search module and memory module to allocate correctly sized buffers for embedding storage and comparison.

### Exported Functions

```typescript
export async function embed(text: string): Promise<Float32Array>;
```
Lazy-loads the Transformers.js pipeline on first call. Uses `@xenova/transformers` with quantized `all-MiniLM-L6-v2` model. Pooling: mean, normalize: true. Model cached to `~/.atrophy/models/<model>/`. The quantized model is roughly 4x smaller than the full-precision version with minimal accuracy loss, which matters for download time and disk usage.

```typescript
export async function embedBatch(texts: string[]): Promise<Float32Array[]>;
```
Processes texts sequentially (calls `embed()` per text). Logical chunk size of 32 for memory management but each text is embedded individually. The sequential processing avoids memory spikes from batching many texts at once through the WASM runtime.

The following utility functions handle vector math and serialization between the in-memory Float32Array format and the Buffer format stored in SQLite BLOBs.

```typescript
export function cosineSimilarity(a: Float32Array, b: Float32Array): number;
// Returns 0 if lengths differ or either norm is 0.

export function vectorToBlob(vec: Float32Array): Buffer;
// Buffer.from(vec.buffer, vec.byteOffset, vec.byteLength)

export function blobToVector(blob: Buffer): Float32Array;
// Creates a copy of the buffer to avoid aliasing issues.
// new Float32Array(copy.buffer, copy.byteOffset, copy.length / 4)
```

The `blobToVector` function creates a copy of the buffer rather than wrapping it directly. This avoids aliasing issues where the original Buffer's underlying ArrayBuffer could be shared with other views, leading to data corruption if the buffer is later reused.

### Dependencies
- `@xenova/transformers` - WASM-based transformer inference
- `config.ts` - for model name, model cache directory

---

## vector-search.ts

The vector search module implements hybrid retrieval that combines semantic similarity (vector cosine distance) with keyword matching (BM25). This hybrid approach catches both conceptually similar content (via embeddings) and exact keyword matches (via BM25), which either method alone would miss. The default weighting is 70% vector, 30% keyword - heavily semantic, since the agent's memory tends to paraphrase rather than use exact user wording. Results are de-duplicated using Maximal Marginal Relevance (MMR) to ensure diversity. The module is a port of `core/vector_search.py` at 356 lines.

### Constants

**Searchable tables** define which database tables can be searched and how to extract text content from each. Each table has a designated content column for text extraction and a set of columns to return in results:

| Table | Content column | Columns selected |
|-------|---------------|-----------------|
| `observations` | `content` | id, created_at, content, source_turn, incorporated, valid_from, valid_to, learned_at, expired_at, confidence, activation, last_accessed |
| `summaries` | `content` | id, created_at, session_id, content, topics |
| `turns` | `content` | id, session_id, role, content, timestamp, topic_tags, weight, channel |
| `bookmarks` | `moment` | id, session_id, created_at, moment, quote |
| `entities` | `name` | id, name, entity_type, mention_count, first_seen, last_seen |

**BM25 parameters:** k1=1.5, b=0.75 (defaults in function signature). These are standard BM25 parameters - k1 controls term frequency saturation (higher means more weight on term frequency) and b controls document length normalization (higher means more penalty for long documents).

### Exported Interface

```typescript
export interface SearchResult {
  _source_table: string;
  _score: number;
  [key: string]: unknown;  // table-specific columns
}
```

### Exported Functions

```typescript
export async function search(
  query: string,
  n = 5,
  vectorWeight?: number,  // default from config.VECTOR_SEARCH_WEIGHT (0.7)
  tables?: string[],       // default all searchable tables
  db?: Database.Database
): Promise<SearchResult[]>;
```
The search pipeline runs in five stages for each table:
1. Vector search: embed query, compute cosine similarity against all rows with embeddings, return top `n*3`
2. BM25 search: tokenize query and all docs, compute BM25 scores, return top `n*3`
3. Merge: min-max normalize both result sets, weighted sum (`vectorWeight * vec + (1-vectorWeight) * txt`)
4. Fetch full row data for top `n*2` merged results
5. MMR de-duplication: skip results with >80% token overlap with already-selected results
6. Return top `n` results sorted by score

The over-fetching (n*3 in each search, n*2 after merge) ensures the final top-n selection has a rich candidate pool even after de-duplication removes redundant results.

```typescript
export async function searchSimilar(
  text: string,
  n = 5,
  tables?: string[],
  db?: Database.Database
): Promise<SearchResult[]>;
// Pure vector search (vectorWeight = 1.0, no BM25).

export async function reindex(table?: string, db?: Database.Database): Promise<void>;
```
Re-embeds all rows in specified table(s). Processes in chunks of 64. Logs progress. This is used after schema migrations, model changes, or when embedding quality needs to be refreshed. It can take significant time on large databases.

### Dependencies
- `better-sqlite3` - for querying memory tables
- `config.ts` - for vector search weight configuration
- `embeddings.ts` - for embedding queries and computing similarity
- `memory.ts` - for the database connection pool

---

## agent-manager.ts

The agent manager handles multi-agent discovery, switching, and state management. It scans both user and bundle agent directories, maintains enabled/muted state for each agent, implements rolodex-style cycling between agents, and manages the deferral system that lets one agent hand off to another. Session suspension preserves the CLI session state when switching, so the user can return to an agent and resume where they left off. The module is a port of `core/agent_manager.py` at 289 lines.

### Constants

The following constants control the deferral anti-loop protection, which prevents agents from endlessly bouncing a conversation between each other.

```typescript
const DEFERRAL_FILE = path.join(USER_DATA, '.deferral_request.json');
const ANTI_LOOP_WINDOW_MS = 60_000;
const MAX_DEFERRALS_PER_WINDOW = 3;
```

### Exported Interfaces

```typescript
export interface AgentInfo {
  name: string;
  display_name: string;
  description: string;
  role: string;
}
```

### Exported Functions

**Agent discovery** scans the filesystem to find all available agents and their metadata.

```typescript
export function discoverAgents(): AgentInfo[];
```
Scans `~/.atrophy/agents/` and `<BUNDLE_ROOT>/agents/`. Looks for directories containing a `data/` subdirectory with `agent.json`. User agents override bundle by name, so a user can customize a bundled agent by placing a modified version in their data directory. System-role agents sort first, then alphabetical.

**State management** tracks which agents are enabled (receive messages and run cron jobs) and which are muted (active but do not receive routed Telegram messages).

```typescript
export function getAgentState(agentName: string): { muted: boolean; enabled: boolean };
// Defaults: muted=false, enabled=true

export function setAgentState(
  agentName: string,
  opts: { muted?: boolean; enabled?: boolean }
): void;
// Toggling enabled triggers toggleAgentCron() - installs or uninstalls launchd jobs.

export function setLastActiveAgent(agentName: string): void;
// Stores in _last_active key of agent_states.json

export function getLastActiveAgent(): string | null;
```

The `setAgentState()` function has a side effect when the `enabled` flag changes: it calls `toggleAgentCron()`, which installs or uninstalls the agent's launchd jobs. This ensures that disabling an agent stops all of its background activity, not just its visibility in the UI.

**Agent cycling** implements the rolodex-style agent switching triggered by the AgentName component in the UI.

```typescript
export function cycleAgent(direction: number, current: string): string | null;
```
Returns next/prev enabled agent name. Wraps around, skips disabled agents. Returns null if only one agent exists. The direction parameter is +1 or -1, corresponding to scroll up/down or left/right gestures.

**Session deferral** allows one agent to hand off the conversation to another agent. The outgoing agent's session state is suspended in memory, and the incoming agent starts (or resumes) its own session with context about why the handoff happened.

```typescript
export function suspendAgentSession(
  agentName: string,
  cliSessionId: string,
  turnHistory: unknown[]
): void;
// In-memory Map storage

export function resumeAgentSession(
  agentName: string
): { cliSessionId: string; turnHistory: unknown[] } | null;
// Removes from map and returns, or null if not suspended

export function checkDeferralRequest(): DeferralRequest | null;
// Reads and deletes .deferral_request.json

export function validateDeferralRequest(target: string, currentAgent: string): boolean;
// Rejects self-deferral. Anti-loop: max 3 deferrals per 60-second window.

export function resetDeferralCounter(): void;
```

The deferral system uses a file-based handshake (`.deferral_request.json`) because the request originates from an MCP tool running inside the Claude CLI subprocess, which cannot communicate directly with the Electron main process. The main process polls for this file periodically and processes any pending requests.

```typescript
export function getAgentRoster(exclude?: string): AgentInfo[];
// discoverAgents() filtered to enabled agents, excluding named agent.
```

### Dependencies
- `config.ts` - for agent paths and Python path (used in cron toggle)
- `child_process` - for executing cron install/uninstall commands

---

## telegram.ts

The Telegram module implements a Bot API client for sending and receiving messages through Telegram. It supports text messages, inline keyboards (for confirmations and permissions), voice notes, and long-polling for replies. All communication uses the HTTP Bot API via `fetch` - no webhooks, no extra dependencies. Messages are prefixed with the agent's emoji and display name so multi-agent messages are distinguishable in the chat. The module is a port of `channels/telegram.py` at 380 lines.

### Exported Functions

The following functions cover the full range of Telegram interactions the agent needs: sending messages, receiving responses, and managing bot commands.

```typescript
export async function sendMessage(
  text: string, chatId = '', prefix = true
): Promise<boolean>;
// Sends with Markdown parse_mode. If prefix=true and TELEGRAM_EMOJI set,
// prepends emoji + agent display name. 15-second timeout.

export async function sendButtons(
  text: string,
  buttons: { text: string; callback_data: string }[][],
  chatId = '', prefix = true
): Promise<number | null>;
// Returns message_id for tracking callbacks.

export async function sendVoiceNote(
  audioPath: string, caption = '', chatId = '', prefix = true
): Promise<boolean>;
// Builds multipart form data manually. Auto-detects OGG -> sendVoice, other -> sendAudio.
// 30-second timeout.

export async function pollCallback(
  timeoutSecs = 120, chatId = ''
): Promise<string | null>;
// Long-polls getUpdates with 30-second chunks. Filters by chat_id.
// Answers callback queries automatically.

export async function pollReply(
  timeoutSecs = 120, chatId = ''
): Promise<string | null>;
// Same polling pattern for text messages.

export async function askConfirm(
  text: string, timeoutSecs = 120
): Promise<boolean | null>;
// Flushes old updates, sends Yes/No buttons, polls for callback.

export async function askQuestion(
  text: string, timeoutSecs = 120
): Promise<string | null>;
// Flushes old updates, sends message, polls for reply.

export async function registerBotCommands(): Promise<boolean>;
// Builds commands from discoverAgents() + /status + /mute. setMyCommands API.
// Telegram limits command descriptions to 256 chars.

export async function clearBotCommands(): Promise<boolean>;
// deleteMyCommands API.

export function setLastUpdateId(id: number): void;
```

The `askConfirm()` and `askQuestion()` functions are convenience wrappers for the common pattern of sending a prompt and waiting for a response. They flush old updates first to avoid picking up stale messages from previous interactions. The `registerBotCommands()` function sets up Telegram's command autocomplete menu with all available agents plus utility commands.

### Dependencies
- `config.ts` - for bot token, chat ID, agent emoji and display name
- `agent-manager.ts` - for agent discovery when registering bot commands

---

## telegram-daemon.ts

The Telegram daemon implements a persistent polling loop that monitors the Telegram chat for incoming messages and dispatches them to the appropriate agent. It runs either as part of the Electron app or as a standalone launchd job, using file-based instance locking to prevent duplicate polling. The daemon handles routing (which agent should receive each message), utility commands (`/status`, `/mute`), and agent-specific inference dispatch. It is a port of `channels/telegram_daemon.py` at 516 lines.

### Constants

```typescript
const STATE_FILE = path.join(USER_DATA, '.telegram_daemon_state.json');
const LOCK_FILE = path.join(USER_DATA, '.telegram_daemon.lock');
const PLIST_LABEL = 'com.atrophy.telegram-daemon';
```

### Instance Locking

Instance locking prevents multiple daemon processes from polling Telegram simultaneously, which would cause duplicate message processing. The locking mechanism is platform-aware.

```typescript
export function acquireLock(): boolean;
```
Uses `O_EXLOCK` (0x20) | `O_NONBLOCK` (0x4000) on macOS for advisory exclusive lock. Falls back to pid-check strategy on other platforms. Writes PID to lock file. Returns false if another instance holds the lock.

```typescript
export function releaseLock(): void;
```

### launchd Management

These functions install and manage the daemon as a macOS launchd service, allowing it to start at boot and restart automatically if it crashes.

```typescript
export function installLaunchd(electronBin: string): void;
// Generates XML plist with KeepAlive=true, RunAtLoad=true.
// Unloads existing plist first if installed.

export function uninstallLaunchd(): void;

export function isLaunchdInstalled(): boolean;
```

### Daemon Control

The daemon control functions manage the polling lifecycle within the current process.

```typescript
export function startDaemon(intervalMs = 10_000): boolean;
// Acquires lock, loads last update ID from state file.
// Initial poll + setInterval for recurring polls. Returns false if locked.

export function stopDaemon(): void;
// Clears interval, releases lock.

export function isDaemonRunning(): boolean;
```

### Message Dispatch

Internal `dispatchToAgent(agentName, text)` is the core of the daemon. It handles the full lifecycle of processing a Telegram message for a specific agent:
1. Temporarily switches config via `reloadForAgent()` - changes all agent-specific paths and settings
2. Initializes DB - ensures the target agent's database is open and migrated
3. Loads system prompt - builds the full prompt for the target agent
4. Gets last CLI session ID - for conversation continuity
5. Runs streaming inference with `[Telegram message from the user]` prefix - the prefix helps the agent distinguish Telegram messages from direct GUI input
6. Restores original agent config - returns to the previously active agent's settings

The daemon also handles utility commands that are not routed to any agent: `/status` (lists all agents with emoji and enabled/muted state) and `/mute` (toggles mute on a specified agent).

### Dependencies
- `config.ts` - for data paths and agent configuration
- `telegram.ts` - for sending/receiving Telegram messages
- `router.ts` - for multi-agent message routing decisions
- `agent-manager.ts` - for agent discovery and state management
- `inference.ts` - for running inference on behalf of target agents
- `context.ts` - for loading agent system prompts
- `memory.ts` - for database initialization and turn recording

---

## router.ts

The router module implements two-tier message routing for the multi-agent Telegram system. When a message arrives over Telegram, the router decides which agent(s) should handle it. Tier 1 uses explicit signals (commands, mentions, wake words) with no inference cost. Tier 2 falls back to LLM-based routing using a lightweight Haiku call when the intent is ambiguous. The router also maintains a route file that allows the daemon to pass routing decisions to agent-specific inference processes. The module is a port of `channels/router.py` at 269 lines.

### Exported Interface

```typescript
export interface RoutingDecision {
  agents: string[];
  tier: 'explicit' | 'agent' | 'single' | 'none';
  text: string;  // cleaned text (command prefix or agent name removed)
}
```

The `tier` field indicates how the routing decision was made: `'explicit'` means a command or mention was detected, `'agent'` means LLM routing was used, `'single'` means there was only one agent so no routing was needed, and `'none'` means no agents were available.

### Exported Functions

```typescript
export async function routeMessage(text: string): Promise<RoutingDecision>;
```
The routing pipeline runs through the following stages in order:
1. Loads agent registry (enabled and not muted agents with wake words and emoji)
2. If 0 agents: `{ agents: [], tier: 'none' }`
3. If 1 agent: `{ agents: [name], tier: 'single' }`
4. **Tier 1 - Explicit** (no inference): `/command`, `@mention`, `name:` prefix, wake words, multiple agents named in text
5. **Tier 2 - LLM routing** (Haiku, low effort): Asks routing agent to return JSON array of agent slugs

Tier 1 handles the majority of messages in practice, since users quickly learn to address agents by name or command. Tier 2 is the safety net for messages like "can someone help me with this code" that do not mention a specific agent but clearly need routing.

**Route file IPC** provides a persistence layer for routing decisions that need to survive between daemon poll cycles.

```typescript
export function enqueueRoute(
  messageId: number, text: string, decision: RoutingDecision
): void;
// Appends to ~/.atrophy/.telegram_routes.json. Keeps last 50 entries.

export function dequeueRoute(agentName: string): RouteEntry | null;
// Finds first route targeting the agent, removes agent from the route's agent list.
// Removes entry entirely if no agents remain.
```

The route file is capped at 50 entries to prevent unbounded growth. The dequeue function removes the agent from the route's target list rather than deleting the entire entry, which allows multi-agent routing where a single message is dispatched to multiple agents.

### Dependencies
- `config.ts` - for agent configuration
- `agent-manager.ts` - for agent discovery and wake word lookup
- `inference.ts` - for the Tier 2 LLM routing call

---

## server.ts

The server module exposes an HTTP API for programmatic access to the companion. It runs headless - no GUI, no TTS, no voice input - making it suitable for integration with external tools, scripts, and other applications. The server binds to localhost by default and requires bearer token authentication on all endpoints except health check. It uses Node's raw `http` module rather than Express to avoid an extra dependency for a small API surface. The module is a port of `server.py` at 349 lines.

### Endpoints

The following table lists all available endpoints, their methods, authentication requirements, and purposes.

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/health` | GET | No | Returns `{ status: 'ok', agent, display_name }` |
| `/chat` | POST | Yes | Blocking chat - returns full response |
| `/chat/stream` | POST | Yes | SSE streaming chat |
| `/memory/search` | GET | Yes | Vector search via query param `q`, optional `limit` |
| `/memory/threads` | GET | Yes | Active conversation threads |
| `/session` | GET | Yes | Current session info |

### Auth

Security is enforced through a bearer token stored in `~/.atrophy/server_token`. The token is auto-generated (32 bytes, base64url) on first launch and the file is written with mode `0o600` to restrict read access. The token is required on all endpoints except `/health`, which is left open so that health monitoring tools can check server status without credentials.

### Behavior

The server manages a few important state constraints that callers should be aware of:

- `inferLock` boolean prevents concurrent inference - returns 429 if busy. This is necessary because the Claude CLI subprocess model does not support concurrent conversations.
- Session auto-created on first request, so the server is immediately ready to accept chat messages after startup.
- System prompt loaded lazily on first chat request.
- SSE format: `data: {"type": "text", "content": "..."}\n\n` - standard Server-Sent Events encoding that works with any SSE client library.

### Exported Functions

```typescript
export function startServer(port = 5000, host = '127.0.0.1'): void;
```
Initializes the database, creates a session, loads the system prompt, and starts the HTTP server. Prints a startup banner with the agent name, URL, token preview, and available endpoints.

```typescript
export function stopServer(): void;
// Closes HTTP server and ends session.
```
Gracefully shuts down the server and generates a session summary if the conversation had enough turns. Called during app shutdown.

### Dependencies
- `http`, `crypto` - Node built-ins for HTTP server and token generation
- `config.ts` - for agent settings and data paths
- `memory.ts` - for database and thread queries
- `session.ts` - for conversation lifecycle
- `context.ts` - for system prompt assembly
- `inference.ts` - for streaming and blocking inference
- `vector-search.ts` - for the memory search endpoint

---

## cron.ts

The cron module manages macOS launchd scheduled jobs for companion background tasks. Jobs like heartbeat check-ins, reminder checks, and evolution runs are defined in per-agent `jobs.json` files and translated into launchd plist XML. The module handles the full lifecycle: creating jobs, generating plists, installing/uninstalling with launchctl, editing schedules, and running jobs on demand. It is a port of `scripts/cron.py` at 333 lines.

### Exported Interfaces

The following interfaces describe jobs as they are stored in `jobs.json` and as they are presented to the UI with additional runtime information.

```typescript
export interface Job {
  cron?: string;
  script: string;
  description?: string;
  args?: string[];
  type?: 'calendar' | 'interval';
  interval_seconds?: number;
}

export interface JobInfo extends Job {
  name: string;
  installed: boolean;
  schedule: string;
}
```

### Cron Parsing

`parseCron(cronStr)` parses standard 5-field cron expressions: `min hour dom month dow`. Maps non-`*` fields to `CalendarInterval` object with `Minute`, `Hour`, `Day`, `Month`, `Weekday`. This translation is necessary because launchd uses its own `StartCalendarInterval` dictionary format rather than cron syntax.

### Plist Generation

The module generates launchd plist XML with a minimal custom serializer rather than depending on an external plist library. Each plist includes:
- `Label`: `com.atrophy.<agent>.<jobname>`
- `ProgramArguments`: `[pythonPath, scriptPath, ...args]`
- `WorkingDirectory`: `BUNDLE_ROOT`
- `StandardOutPath`/`StandardErrorPath`: `<BUNDLE_ROOT>/logs/<agent>/<jobname>.log`
- `EnvironmentVariables`: PATH + AGENT
- Either `StartCalendarInterval` (for cron-style schedules) or `StartInterval` (for fixed-interval schedules)

The log files are written to a per-agent log directory so that job output from different agents does not interleave. The AGENT environment variable is set so that Python scripts know which agent they are running for.

### Exported Functions

The following functions provide the full CRUD and lifecycle management API for scheduled jobs.

```typescript
export function listJobs(): JobInfo[];
// Loads from jobs.json, checks installed status for each.

export function addJob(
  name: string, cronStr: string, script: string,
  description = '', install = false
): void;
// Validates cron syntax. Optionally installs immediately.

export function removeJob(name: string): void;
// Uninstalls from launchd, removes from jobs.json.

export function editJobSchedule(name: string, cronStr: string): void;
// Updates schedule. Reinstalls if currently installed.

export function runJobNow(name: string): number;
// spawnSync with inherited stdio. Returns exit code.

export function installAllJobs(): void;
export function uninstallAllJobs(): void;
export function toggleCron(enabled: boolean): void;
```

The `editJobSchedule()` function automatically reinstalls the job if it is currently installed, ensuring launchd picks up the new schedule without requiring a manual uninstall/reinstall cycle. The `runJobNow()` function uses `spawnSync` with inherited stdio so the job's output appears in the console, which is useful for debugging.

### Dependencies
- `config.ts` - for agent name, Python path, and bundle root
- `child_process` - for launchctl commands and job execution

---

## install.ts

The install module manages macOS login item registration, allowing Atrophy to start automatically when the user logs in. Unlike the Python version which used manual launchd plist generation, the Electron version uses Electron's built-in `app.setLoginItemSettings()` API, which handles the platform-specific details of registering and unregistering login items. The `--app` argument is passed so the app launches in menu bar mode (dock hidden, no window) rather than full GUI mode. The module is 38 lines.

### Exported Functions

The following functions provide a complete API for controlling login item behavior. They are called from the Settings modal when the user toggles the "Start at login" checkbox.

```typescript
export function isLoginItemEnabled(): boolean;
// app.getLoginItemSettings().openAtLogin

export function enableLoginItem(): void;
// app.setLoginItemSettings({ openAtLogin: true, openAsHidden: true, args: ['--app'] })

export function disableLoginItem(): void;
// app.setLoginItemSettings({ openAtLogin: false })

export function toggleLoginItem(enabled: boolean): void;
```

The `openAsHidden: true` flag combined with the `--app` argument means the app starts silently in the menu bar without showing a window or dock icon. This is the expected behavior for a companion that should always be available but not visually intrusive.

### Dependencies
- `electron` (app) - for the login item settings API

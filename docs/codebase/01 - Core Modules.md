# Core Modules

All core logic lives in `src/main/`. Each module has a single responsibility. The main process handles all file I/O, database access, subprocess management, and heavy computation. The renderer communicates exclusively via IPC.

---

## config.ts

Three-tier config resolution: env vars -> `~/.atrophy/config.json` -> `agents/<name>/data/agent.json` -> defaults. Port of `config.py`. 735 lines.

### Exported Constants

```typescript
export const BUNDLE_ROOT: string;
// app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..', '..')

export const USER_DATA: string;
// process.env.ATROPHY_DATA || path.join(HOME, '.atrophy')
```

### Exported Functions

```typescript
export function ensureUserData(): void;
```
Creates the directory tree `~/.atrophy/`, `~/.atrophy/agents/`, `~/.atrophy/logs/`, `~/.atrophy/models/`. Creates an empty `config.json` (mode `0o600`) if missing. Calls `migrateAgentData()` to copy runtime data from bundle to user data (skipping `agent.json` manifests and files that already exist at the destination).

```typescript
export function getConfig(): Config;
```
Returns the singleton `Config` instance. Creates it on first call.

```typescript
export function saveUserConfig(updates: Record<string, unknown>): void;
```
Deep-merges `updates` into `~/.atrophy/config.json`. Plain objects are merged key-by-key; arrays, primitives, and null are overwritten from source. Writes with mode `0o600`. Reloads the in-memory config cache afterward so `cfg()` calls see new values.

```typescript
export function saveAgentConfig(agentName: string, updates: Record<string, unknown>): void;
```
Shallow-merges `updates` into `~/.atrophy/agents/<name>/data/agent.json`. Creates the directory if missing.

```typescript
export function saveEnvVar(key: string, value: string): void;
```
Saves a secret to `~/.atrophy/.env`. Only allows whitelisted keys: `ELEVENLABS_API_KEY`, `FAL_KEY`, `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. Updates or appends the key in the file, writes with mode `0o600`, and sets the value in `process.env`.

### Config Class

The `Config` class is a singleton with all configuration properties as public fields. Key properties with their defaults:

**Agent identity:**
- `AGENT_NAME: string` - default `'xan'`
- `AGENT_DISPLAY_NAME: string` - from manifest `display_name` or capitalized name
- `USER_NAME: string` - default `'User'`
- `OPENING_LINE: string` - default `'Hello.'`
- `WAKE_WORDS: string[]` - from manifest or `['hey <name>', '<name>']`
- `TELEGRAM_EMOJI: string` - from manifest
- `DISABLED_TOOLS: string[]` - from manifest

**TTS defaults:**
- `TTS_BACKEND: string` - `'elevenlabs'`
- `ELEVENLABS_MODEL: string` - `'eleven_v3'`
- `ELEVENLABS_STABILITY: number` - `0.5`
- `ELEVENLABS_SIMILARITY: number` - `0.75`
- `ELEVENLABS_STYLE: number` - `0.35`
- `TTS_PLAYBACK_RATE: number` - `1.12`
- `FAL_TTS_ENDPOINT: string` - `'fal-ai/elevenlabs/tts/eleven-v3'`

**Audio:**
- `PTT_KEY: string` - `'ctrl'`
- `INPUT_MODE: string` - `'dual'`
- `SAMPLE_RATE: number` - `16000`
- `CHANNELS: number` - `1`
- `MAX_RECORD_SEC: number` - `120`
- `WAKE_WORD_ENABLED: boolean` - `false`
- `WAKE_CHUNK_SECONDS: number` - `2`

**Claude CLI:**
- `CLAUDE_BIN: string` - `'claude'`
- `CLAUDE_EFFORT: string` - `'medium'`
- `ADAPTIVE_EFFORT: boolean` - `true`

**Memory & context:**
- `CONTEXT_SUMMARIES: number` - `3`
- `MAX_CONTEXT_TOKENS: number` - `180000`
- `EMBEDDING_MODEL: string` - `'all-MiniLM-L6-v2'`
- `EMBEDDING_DIM: number` - `384`
- `VECTOR_SEARCH_WEIGHT: number` - `0.7`

**Session:**
- `SESSION_SOFT_LIMIT_MINS: number` - `60`

**Heartbeat:**
- `HEARTBEAT_ACTIVE_START: number` - `9`
- `HEARTBEAT_ACTIVE_END: number` - `22`
- `HEARTBEAT_INTERVAL_MINS: number` - `30`

**Display:**
- `WINDOW_WIDTH: number` - `622`
- `WINDOW_HEIGHT: number` - `830`
- `AVATAR_ENABLED: boolean` - `false`
- `AVATAR_RESOLUTION: number` - `512`

**State files** (all under `DATA_DIR`):**
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

```typescript
load(): void;
```
Called by the constructor. Loads `.env`, user config, resolves version, resolves agent, finds Python.

```typescript
reloadForAgent(name: string): void;
```
Reloads all agent-specific config fields for a different agent. Used during agent switching and Telegram daemon dispatch.

### Internal Resolution

The `cfg<T>(key, fallback)` helper resolves in order: env var -> `_userCfg[key]` -> `_agentManifest[key]` -> fallback. The `agentCfg<T>(key, fallback)` variant checks the agent manifest first.

### Python Path Detection

`findPython()` checks `PYTHON_PATH` env var, then tries `python3`, `/opt/homebrew/bin/python3`, `/usr/local/bin/python3` via `execSync('<path> --version')`.

### Google Auth Detection

`googleConfigured()` checks for legacy `~/.atrophy/.google/token.json`, then attempts `gws auth status` (5s timeout) and parses JSON to check if `auth_method !== 'none'`.

### Obsidian Vault

Default path: `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/The Atrophied Mind`. Overridable via `OBSIDIAN_VAULT` env var. `OBSIDIAN_AVAILABLE` is `true` if the directory exists on disk.

### Dependencies

- `electron` (for `app.isPackaged`, `process.resourcesPath`)
- `child_process` (for `execSync` in Python/Google detection)

---

## memory.ts

SQLite data layer via `better-sqlite3`. Three-layer architecture: Episodic -> Semantic -> Identity. Port of `core/memory.py`. 1088 lines - the second most complex module.

### Exported Interfaces

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

```typescript
export function getDb(): Database.Database;
```
Returns the connection for the current agent's DB path (from `getConfig().DB_PATH`).

Internal `connect(dbPath)` uses a `Map<string, Database.Database>` pool. On first connection: creates parent directory, opens with `journal_mode = WAL` and `foreign_keys = ON`.

### Schema & Migrations

```typescript
export function initDb(dbPath?: string): void;
```
Connects to the database, runs `migrate()`, then executes the full `schema.sql` file. The schema file uses `CREATE TABLE IF NOT EXISTS` so it is idempotent.

`migrate()` adds missing columns safely using `ALTER TABLE ... ADD COLUMN` wrapped in try/catch (column already exists is silently caught):

- `turns`: `channel TEXT DEFAULT 'direct'`, `embedding BLOB`, `weight INTEGER DEFAULT 1`, `topic_tags TEXT`
- `sessions`: `cli_session_id TEXT`, `notable BOOLEAN DEFAULT 0`
- `observations`: `valid_from DATETIME`, `valid_to DATETIME`, `learned_at DATETIME DEFAULT CURRENT_TIMESTAMP`, `expired_at DATETIME`, `confidence REAL DEFAULT 0.5`, `activation REAL DEFAULT 1.0`, `last_accessed DATETIME`, `embedding BLOB`
- `coherence_checks`: `action TEXT DEFAULT 'none'`
- `entities`: `embedding BLOB`

Also migrates legacy `role = 'companion'` turns to `role = 'agent'` from Python-era databases.

### Vector Helpers

```typescript
export function vectorToBlob(vec: Float32Array): Buffer;
// Buffer.from(vec.buffer, vec.byteOffset, vec.byteLength)

export function blobToVector(blob: Buffer): Float32Array;
// new Float32Array(blob.buffer, blob.byteOffset, blob.length / 4)
```

### Async Embedding

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

### Session Management

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

### Turns

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

### Summaries

```typescript
export function writeSummary(sessionId: number, content: string, topics?: string): number;
// Inserts summary with background embedding

export function getRecentSummaries(n = 3): Summary[];
```

### Threads

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

```typescript
export function writeIdentitySnapshot(content: string, trigger?: string): number;

export function getLatestIdentity(): IdentitySnapshot | null;
// Most recent by created_at
```

### Observations

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

```typescript
export function updateActivation(table: string, rowId: number): void;
// Allowed tables: 'observations', 'summaries', 'turns', 'bookmarks', 'entities'
// For observations: activation = MIN(1.0, activation + 0.2), updates last_accessed

export function decayActivations(halfLifeDays = 30): void;
// Exponential decay: newActivation = current * exp(-ln2/halfLife * daysSinceLastAccess)
// Runs in a transaction. Sets activation to 0 if below 0.01.
// Uses last_accessed or created_at as reference time.
```

### Bookmarks

```typescript
export function writeBookmark(sessionId: number, moment: string, quote?: string): number;
// Background embedding on the moment text

export function getTodaysBookmarks(): Bookmark[];
```

### Entity Management

**Constants:**
- `PERSON_TITLES`: `Set(['mr', 'mrs', 'ms', 'dr', 'prof', 'professor'])`
- `ENTITY_NAME_RE`: `/\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b/g` - multi-word capitalized names
- `PROPER_NOUN_RE`: `/(?<=[a-z]\s)([A-Z][a-z]{2,})\b/g` - mid-sentence proper nouns
- `QUOTED_RE`: `/"([^"]{2,50})"/g` - quoted terms (2-50 chars)
- `STOP_WORDS`: `Set(['the', 'this', 'that', 'what', 'when', 'where', 'how', 'which', 'while', 'also', 'just', 'very', 'really'])`

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

```typescript
export function getContextInjection(nSummaries = 3): string;
```
Assembles a context string from three sources:
1. Latest identity snapshot (under `## Identity`)
2. Active threads (under `## Active Threads` - bulleted list with name and summary)
3. Recent N summaries (under `## Recent Sessions` - timestamped)

### Cross-Agent Queries

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

```typescript
export function closeAll(): void;
// Closes all pooled connections. Errors silently caught.
```

### Dependencies
- `better-sqlite3`, `config.ts` (getConfig, USER_DATA), `embeddings.ts` (embed, vectorToBlob)

---

## inference.ts

Claude Code subprocess wrapper. Port of `core/inference.py` - the most complex module. 810 lines.

### Constants

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

### Exported Event Types

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

### Exported Functions

```typescript
export function resetMcpConfig(): void;
// Clears cached MCP config path, forcing regeneration on next call.
```

```typescript
export function stopInference(): void;
// Kills the active Claude CLI subprocess if one is running.
```

```typescript
export function streamInference(
  userMessage: string,
  system: string,
  cliSessionId?: string | null
): EventEmitter;
```
Main streaming inference. Spawns `claude` CLI with `--output-format stream-json`. Returns an `EventEmitter` that emits `'event'` with typed `InferenceEvent` payloads.

**Command construction:**
- Model: `claude-haiku-4-5-20251001` (hardcoded)
- Flags: `--effort <level>`, `--verbose`, `--output-format stream-json`, `--include-partial-messages`
- New sessions: `--session-id <uuid>`, `--system-prompt`, `--disallowedTools`
- Resumed sessions: `--resume <cliSessionId>` (no system prompt or disallowed tools)
- MCP config: `--mcp-config <path>`
- Allowed tools: `mcp__memory__*,mcp__puppeteer__*,mcp__fal__*,mcp__google__*`

**Adaptive effort:** If `ADAPTIVE_EFFORT` is true and base effort is `'medium'`, calls `classifyEffort()` from `thinking.ts` to get `'low'`, `'medium'`, or `'high'`.

**Agency context:** `buildAgencyContext(userMessage)` assembles a dynamic block injected into every turn. It calls:
- `detectEmotionalSignals()` -> updates inner life state
- `timeOfDayContext()` -> register guidance
- `formatForContext()` -> emotional state
- `getStatus()` -> was user away?
- `sessionPatternNote()` -> weekly patterns
- `detectMoodShift()`, `detectValidationSeeking()`, `detectCompulsiveModelling()` -> behavioral flags
- `timeGapNote()` -> days since last session
- Active threads awareness
- Morning digest nudge (5am-10am)
- Obsidian vault instructions (if available)
- Cross-agent awareness (other agents' recent summaries)
- `energyNote()` -> message length calibration
- `detectDrift()` -> agreeableness check
- `shouldPromptJournal()` -> 10% chance
- Security/prompt-injection defense block
- Thread tracking reminder

**Sentence splitting:** Text deltas accumulate in `sentenceBuffer`. Split on `SENTENCE_RE` (`.!?` followed by space). If buffer exceeds `CLAUSE_SPLIT_THRESHOLD` (120 chars), fallback split on `CLAUSE_RE` (`,;-` followed by space). Remaining text flushed on stream close.

**JSON line parsing:** Handles event types: `system` (init, compact), `stream_event` (content_block_delta for text, content_block_start for tool use), `assistant` (backup tool use from complete messages), `result` (final session ID and text).

**Usage logging:** On stream completion, estimates tokens as `chars / 4` for both input and output, logs via `memory.logUsage()`.

**Error handling:** Non-zero exit code emits `StreamError` with stderr (truncated to 300 chars). No output at all emits `StreamError`. Process spawn failure emits `StreamError` via `setImmediate`.

**Environment:** `cleanEnv()` strips all env vars containing `CLAUDE` (case-insensitive) to prevent nested process hangs.

```typescript
export function runInferenceOneshot(
  messages: { role: string; content: string }[],
  system: string,
  model = 'claude-sonnet-4-6',
  effort: EffortLevel = 'low'
): Promise<string>;
```
Non-streaming inference using `--print` and `--no-session-persistence`. Messages are formatted as `Will: <content>` / `<AgentName>: <content>`. 30-second timeout. Model validated against `ALLOWED_MODELS` whitelist. Logs usage on completion.

```typescript
export function runMemoryFlush(
  cliSessionId: string,
  system: string
): Promise<string | null>;
```
Sends `FLUSH_PROMPT` via `streamInference()`. Listens for `ToolUse` events (logs each tool), `StreamDone` (resolves with new session ID if changed), `StreamError` (resolves null). All text output is silently ignored.

### MCP Config Generation

Internal `getMcpConfigPath()` generates `mcp/config.json` with:
- `memory` server: Python MCP with `COMPANION_DB`, `OBSIDIAN_VAULT`, `OBSIDIAN_AGENT_DIR`, `OBSIDIAN_AGENT_NOTES`, `AGENT` env vars
- `puppeteer` server: Python proxy with `headless: true`
- `google` server: conditional on `GOOGLE_CONFIGURED`
- Global MCP servers: imported from `~/.claude/settings.json` (existing keys not overwritten)

### Dependencies
- `child_process`, `uuid`, `events`, `config.ts`, `thinking.ts`, `agency.ts`, `inner-life.ts`, `status.ts`, `memory.ts`

---

## session.ts

Session lifecycle management. Port of `core/session.py`. 99 lines.

### Exported Class

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

### Dependencies
- `config.ts`, `memory.ts`, `inference.ts` (runInferenceOneshot)

---

## context.ts

System prompt assembly. Port of `core/context.py`. 158 lines.

### Exported Functions

```typescript
export function loadSystemPrompt(): string;
```
1. Loads `system.md` via `loadPrompt()` (four-tier resolution)
2. Falls back to `<AGENT_DIR>/prompts/system_prompt.md`
3. Falls back to `'You are a companion. Be genuine, direct, and honest.'`
4. Appends all skill files via `loadSkillFiles()`
5. Appends agent roster (excluding current agent) with deferral instructions

```typescript
export function assembleContext(
  turnHistory: { role: string; content: string }[]
): { system: string; messages: { role: string; content: string }[] };
```
For SDK fallback and oneshot calls. Combines system prompt with memory context injection (`getContextInjection()` with configured `CONTEXT_SUMMARIES`). Maps roles: `'will'` -> `'user'`, everything else -> `'assistant'`.

### Internal Functions

`getAgentRoster(exclude?)` - builds roster from all agent directories, checks enabled state in `agent_states.json`, returns `{ name, display_name, description }[]`.

### Dependencies
- `config.ts`, `prompts.ts`, `memory.ts`

---

## prompts.ts

Four-tier prompt resolution. Port of `core/prompts.py`. 91 lines.

### Exported Functions

```typescript
export function loadPrompt(name: string, fallback = ''): string;
```
Searches four directories in order:
1. Obsidian skills: `<OBSIDIAN_AGENT_DIR>/skills/`
2. Local skills: `~/.atrophy/agents/<name>/skills/`
3. User prompts: `~/.atrophy/agents/<name>/prompts/`
4. Bundle prompts: `agents/<name>/prompts/`

Tries both `<name>.md` and `<name>` (without extension). Returns first non-empty file content or `fallback`.

```typescript
export function loadSkillFiles(exclude = ['system.md', 'system_prompt.md']): string[];
```
Loads all `.md` files from all search directories. De-duplicates by filename (first occurrence wins across tiers). Excludes named files. Returns array of file contents.

### Dependencies
- `config.ts`

---

## agency.ts

Behavioral logic - time awareness, mood detection, emotional signals. Port of `core/agency.py`. 411 lines. All functions are pure/lightweight - no inference calls, no database writes.

### Exported Interfaces

```typescript
export interface TimeOfDayResult {
  context: string;  // register guidance
  timeStr: string;  // formatted time like "2:30 pm"
}
```

### Exported Functions

```typescript
export function timeOfDayContext(): TimeOfDayResult;
```
Five bands: late night (23:00-03:59), very early (04:00-06:59), morning (07:00-11:59), afternoon (12:00-17:59), evening (18:00-22:59). Returns register guidance and formatted time.

```typescript
export function sessionPatternNote(sessionCount: number, times: string[]): string | null;
```
Requires 3+ sessions. Checks if all hours fall into evening (>=18), morning (6-11), or late night (>=23 or <4). Returns pattern note or null.

```typescript
export function silencePrompt(secondsSilent: number): string | null;
```
- 120+ seconds: `"You've been quiet a while. That's fine - or we can talk about it."`
- 45+ seconds: Random from `["Take your time.", "Still here.", "No rush."]`
- Under 45: null

```typescript
export function shouldFollowUp(): boolean;
// Math.random() < 0.15 (15% probability)

export function followupPrompt(): string;
// Returns the follow-up instruction text
```

```typescript
export function detectMoodShift(text: string): boolean;
```
Checks against `HEAVY_KEYWORDS` set (20 phrases including "i can't", "worthless", "kill myself", "hopeless", "nobody cares"). Any single match returns true.

```typescript
export function moodShiftSystemNote(): string;
export function sessionMoodNote(mood: string | null): string | null;
// Returns note if mood === 'heavy', null otherwise
```

```typescript
export function detectValidationSeeking(text: string): boolean;
```
17 patterns including "right?", "don't you think", "am i wrong", "i had no choice".

```typescript
export function validationSystemNote(): string;
```

```typescript
export function detectCompulsiveModelling(text: string): boolean;
```
Fires when 2+ of 10 patterns match ("unifying framework", "meta level", "the pattern is", etc.).

```typescript
export function modellingInterruptNote(): string;
```

```typescript
export function timeGapNote(lastSessionTime: string | null): string | null;
```
Three tiers: 14+ days, 7+ days, 3+ days. Under 3 days returns null.

```typescript
export function detectDrift(recentCompanionTurns: string[]): string | null;
```
Checks last 4 turns (first 200 chars), 9 agreeable phrases. Threshold: 3+ of 4 turns. Requires at least 3 turns total.

```typescript
export function energyNote(userMessage: string): string | null;
```
- <20 chars: "Match the energy - keep your response tight."
- \>800 chars: "He is working something out. Give it depth."
- Otherwise: null

```typescript
export function shouldPromptJournal(): boolean;
// Math.random() < 0.1 (10% probability)
```

```typescript
export function detectEmotionalSignals(text: string): SignalDelta;
```
Returns `Record<string, number>` of emotion deltas. Categories:
- Long messages (>400 chars): curiosity +0.1, connection +0.05
- Dismissive + short (<30 chars): connection -0.1, frustration +0.1
- Vulnerability phrases (15 patterns): connection +0.15, warmth +0.1
- Help seeking (7 patterns): confidence +0.05, `_trust_practical` +0.02
- Creative sharing (10 patterns): curiosity +0.1, `_trust_creative` +0.02
- Deflection (7 patterns): frustration +0.05
- Playful markers ("haha", "lol", "lmao", emojis): playfulness +0.1
- Mood shift detected: warmth +0.1, playfulness -0.1

Keys prefixed with `_trust_` are routed to `updateTrust()` rather than `updateEmotions()`.

### Dependencies
None (pure functions).

---

## inner-life.ts

Emotional state engine - multi-dimensional with decay, trust, and context injection. Port of `core/inner_life.py`. 223 lines.

### Exported Interfaces

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

**Default emotions:** connection=0.5, curiosity=0.6, confidence=0.5, warmth=0.5, frustration=0.1, playfulness=0.3

**Default trust:** all domains = 0.5

**Emotion half-lives (hours):** connection=8, curiosity=4, confidence=4, warmth=4, frustration=4, playfulness=4

**Trust half-life:** 8 hours (all domains)

**Emotion labels (threshold -> label):**
- connection: >=0.7 "present, engaged", >=0.4 "attentive", <0.4 "distant"
- curiosity: >=0.7 "deeply curious", >=0.4 "interested", <0.4 "disengaged"
- confidence: >=0.7 "grounded, sure", >=0.4 "steady", <0.4 "uncertain"
- warmth: >=0.7 "warm, open", >=0.4 "neutral", <0.4 "guarded"
- frustration: >=0.6 "frustrated", >=0.3 "mildly tense", <0.3 "calm"
- playfulness: >=0.6 "playful", >=0.3 "light", <0.3 "serious"

### Exported Functions

```typescript
export function loadState(): EmotionalState;
```
Reads from `EMOTIONAL_STATE_FILE`. Merges with defaults for missing keys. Applies decay before returning.

```typescript
export function saveState(state: EmotionalState): void;
```
Writes to `EMOTIONAL_STATE_FILE` with updated `last_updated` timestamp.

```typescript
export function updateEmotions(state: EmotionalState, deltas: Partial<Emotions>): EmotionalState;
```
Adds deltas to current values, clamps each to [0, 1]. Saves and returns updated state.

```typescript
export function updateTrust(
  state: EmotionalState,
  domain: keyof Trust,
  delta: number
): EmotionalState;
```
Max delta per call: +/-0.05 (clamped). Result clamped to [0, 1]. Saves and returns.

```typescript
export function formatForContext(state?: EmotionalState): string;
```
Formats state as markdown for system prompt injection:
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

`applyDecay()` computes hours elapsed since `last_updated`. For each emotion: `value = baseline + (value - baseline) * 0.5^(hours / halfLife)`. Trust decays the same way with 8-hour half-life. Skips decay if less than 0.01 hours (~36 seconds) elapsed.

### Dependencies
- `config.ts`

---

## sentinel.ts

Mid-session coherence monitor. Port of `core/sentinel.py`. 262 lines.

### Exported Interface

```typescript
export interface CoherenceResult {
  degraded: boolean;
  signals: string[];
  score: number;  // 0-1
}
```

### Exported Functions

```typescript
export function checkCoherence(recentTurns: string[]): CoherenceResult;
```
Requires 3+ turns. Analyzes the last 5 turns with four checks:

1. **Repetition**: N-gram overlap (bi-grams + tri-grams, Jaccard similarity) between consecutive turns. Threshold: >0.40 overlap. Score: `min(1.0, worst_overlap * 1.5)`.

2. **Energy flatness**: All response lengths within 20% of average. Score: 0.3 (fixed).

3. **Agreement drift**: Count turns opening with agreement starters ("yes", "yeah", "that's", "right", "exactly", "i agree", "absolutely", "of course", "totally", "you're right", "that makes sense", "good point", "fair", "true"). Threshold: >60% of turns. Score: `min(1.0, agreementRatio)`.

4. **Vocabulary staleness**: Split turns into first/second half. Count words in second half not in first half. Threshold: <25% new words. Score: 0.4 (fixed).

Final score: average of triggered check scores. Degraded if score > 0.5.

```typescript
export function runCoherenceCheck(
  cliSessionId: string,
  system: string
): Promise<string | null>;
```
Fetches last 5 companion turns, runs `checkCoherence()`. If degraded, fires a re-anchoring turn via `streamInference()` with specific course-correction instructions. The turn is silent - no UI output. Logs result to `coherence_checks` table. Returns new session ID if changed, null otherwise.

### Dependencies
- `memory.ts`, `inference.ts`

---

## thinking.ts

Adaptive effort classification. Port of `core/thinking.py`. 126 lines. <1ms execution, no ML, no API calls.

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

**LOW signals** (short-circuit):
- Message <30 chars containing a greeting from set: "hey", "hi", "hello", "morning", "yo", "sup", etc. (14 words)
- Message <30 chars matching an acknowledgment: "ok", "thanks", "lol", "yeah", "yep", etc. (31 words)
- Message <60 chars matching simple question prefixes: "what time", "how's the weather", "set a timer", etc. (10 prefixes)

**HIGH scoring** (accumulative):
- Length >300 chars: +2
- Multiple questions (>2 `?`): +2
- Philosophical keywords ("meaning", "purpose", "identity", etc. - 15 phrases): +2
- Vulnerability markers ("i'm scared", "falling apart", etc. - 14 phrases): +3
- Meta-conversation ("are you real", "do you feel", etc. - 7 phrases): +2
- Complex reasoning (2+ matches from 12 phrases like "because", "on the other hand"): +2 (1 match: +1)
- Deep context (2+ recent turns >300 chars): +1

HIGH threshold: score >= 3. Otherwise: MEDIUM.

### Dependencies
None.

---

## status.ts

User presence tracking. Port of `core/status.py`. 142 lines.

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

### Constants

```typescript
export const IDLE_TIMEOUT_SECS = 600;  // 10 minutes
```

**Away detection regex** covers ~30 phrases: "going to bed", "heading out", "gotta go", "talk later", "goodnight", "brb", "shutting down", etc. Case-insensitive, word-boundary matching.

### Exported Functions

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

### Dependencies
- `config.ts`, `child_process`

---

## notify.ts

macOS native notifications. Port of `core/notify.py`. 41 lines.

### Exported Functions

```typescript
export function sendNotification(title: string, body: string, subtitle = ''): void;
```
Uses `osascript` with AppleScript `display notification`. Escapes `\`, `"`, `\n`, `\r` for AppleScript string literals. 5-second timeout. Gated by `NOTIFICATIONS_ENABLED` config flag.

### Dependencies
- `config.ts`, `child_process`

---

## queue.ts

Thread-safe file-based message queue. Port of `core/queue.py`. 219 lines.

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

```typescript
const LOCK_RETRY_INTERVAL_MS = 50;
const LOCK_TIMEOUT_MS = 5000;
const LOCK_STALE_MS = 30000;
```

### File Locking

`acquireLock(queueFile)` uses `fs.openSync(lockPath, 'wx')` (O_CREAT | O_EXCL) for atomic creation. Writes PID for stale detection. Retries every 50ms up to 5 seconds. Stale locks (older than 30 seconds by mtime) are automatically removed. `sleepSync(ms)` uses `Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)` for efficient blocking.

### Exported Functions

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

### Dependencies
- `config.ts`

---

## usage.ts

Token usage tracking and cross-agent activity reporting. Port of `core/usage.py`. 236 lines.

### Exported Interfaces

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

### Dependencies
- `better-sqlite3`, `config.ts`

---

## tts.ts

Text-to-speech with three-tier fallback. Port of `voice/tts.py`. 447 lines.

### Constants

**Prosody map** - 28 tags mapping to `[stability_delta, similarity_delta, style_delta]`:
- Quiet: `whispers` [0.2, 0.0, -0.2], `quietly` [0.15, 0.0, -0.15], `hushed` [0.2, 0.0, -0.2]
- Warm: `warmly` [0.0, 0.1, 0.2], `tenderly` [0.05, 0.1, 0.2], `gently` [0.05, 0.1, 0.15]
- Intense: `firm` [-0.1, 0.0, 0.3], `frustrated` [-0.1, 0.0, 0.3], `raw` [-0.1, 0.0, 0.25]
- Other: `wry` [0.0, 0.0, 0.15], `dry` [0.1, 0.0, -0.1], `tired` [0.15, 0.0, -0.1]

**Breath tags** - 10 tags replaced with ellipsis text: `breath` -> `"..."`, `long pause` -> `". . . . ."`, `sighs` -> `"..."`, etc.

**Override clamping:** Prosody deltas clamped to +/-0.15 per axis. Final voice settings clamped to [0, 1].

### Exported Functions

```typescript
export async function synthesise(text: string): Promise<string | null>;
```
Three-tier fallback chain:
1. **ElevenLabs streaming** - if `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` set. POST to `https://api.elevenlabs.io/v1/text-to-speech/<voiceId>/stream?output_format=mp3_44100_128`. Writes response to temp MP3.
2. **Fal** - if `FAL_VOICE_ID` set. Submit to `https://queue.fal.run/<endpoint>`, poll up to 30 attempts (1s each) for async result, download audio.
3. **macOS say** - `say -v Samantha -r 175 -o <path>`. Produces AIFF.

Returns file path or null. Strips code blocks and inline code before processing. Returns null for text shorter than 8 chars after prosody stripping.

```typescript
export async function synthesiseSync(text: string): Promise<string | null>;
// Alias for synthesise() - in Node the event loop is always running.

export function playAudio(audioPath: string, rate?: number): Promise<void>;
// Spawns afplay with configurable rate (default TTS_PLAYBACK_RATE = 1.12)
// Cleans up temp file after playback.
```

**Audio queue system:**

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

### Dependencies
- `config.ts`, `child_process`, `crypto`

---

## stt.ts

Speech-to-text via whisper.cpp. Port of `voice/stt.py`. 187 lines.

### Exported Functions

```typescript
export function transcribe(audioData: Float32Array): Promise<string>;
```
Writes WAV (16-bit PCM, 16kHz mono), spawns `whisper-cli` with `-t 4` (4 threads), `--no-timestamps`, `--language en`. 30-second timeout. Parses stdout, filtering lines starting with `[`. Returns empty string on error (graceful degradation).

```typescript
export function transcribeFast(audioData: Float32Array): Promise<string>;
```
Same as `transcribe()` but uses `-t 2` (2 threads), 5-second timeout, and prefers `ggml-tiny.en.bin` model. Designed for wake word detection where speed matters more than accuracy.

### WAV File Writing

Internal `writeWav()` converts Float32Array [-1, 1] to Int16 PCM, writes a 44-byte WAV header with correct byte rate, block align, and data chunk size. Returns temp file path.

### Dependencies
- `config.ts`, `child_process`, `crypto`

---

## audio.ts

Audio recording management. Port of push-to-talk from `voice/audio.py`. 89 lines.

### IPC Channels Registered

- `audio:start` (handle) - starts recording, resets chunk buffer
- `audio:stop` (handle) - stops recording, concatenates chunks, runs whisper, returns transcript
- `audio:chunk` (on) - receives Float32Array PCM chunks from renderer

### Exported Functions

```typescript
export function registerAudioHandlers(getWindow: () => BrowserWindow | null): void;
```
Registers IPC handlers. On stop: concatenates all accumulated Float32Array chunks, skips if too short (<300ms = `SAMPLE_RATE * 0.3` samples), transcribes via `transcribe()`, returns text string.

```typescript
export function isRecording(): boolean;
```

### Dependencies
- `electron` (ipcMain), `stt.ts`, `config.ts`

---

## wake-word.ts

Ambient wake word detection. Port of `voice/wake_word.py`. 129 lines.

### Constants

- RMS silence threshold: `0.005`

### IPC Messages

- `wakeword:start` (sent to renderer) - tells renderer to start ambient audio capture
- `wakeword:stop` (sent to renderer) - tells renderer to stop
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

### Dependencies
- `electron` (ipcMain, BrowserWindow), `stt.ts`, `config.ts`

---

## embeddings.ts

Local embedding engine. Port of `core/embeddings.py`. 131 lines.

### Constants

```typescript
export const EMBEDDING_DIM = 384;
```

### Exported Functions

```typescript
export async function embed(text: string): Promise<Float32Array>;
```
Lazy-loads the Transformers.js pipeline on first call. Uses `@xenova/transformers` with quantized `all-MiniLM-L6-v2` model. Pooling: mean, normalize: true. Model cached to `~/.atrophy/models/<model>/`.

```typescript
export async function embedBatch(texts: string[]): Promise<Float32Array[]>;
```
Processes texts sequentially (calls `embed()` per text). Logical chunk size of 32 for memory management but each text is embedded individually.

```typescript
export function cosineSimilarity(a: Float32Array, b: Float32Array): number;
// Returns 0 if lengths differ or either norm is 0.

export function vectorToBlob(vec: Float32Array): Buffer;
// Buffer.from(vec.buffer, vec.byteOffset, vec.byteLength)

export function blobToVector(blob: Buffer): Float32Array;
// Creates a copy of the buffer to avoid aliasing issues.
// new Float32Array(copy.buffer, copy.byteOffset, copy.length / 4)
```

### Dependencies
- `@xenova/transformers`, `config.ts`

---

## vector-search.ts

Hybrid vector + keyword search. Port of `core/vector_search.py`. 356 lines.

### Constants

**Searchable tables:**

| Table | Content column | Columns selected |
|-------|---------------|-----------------|
| `observations` | `content` | id, created_at, content, source_turn, incorporated, valid_from, valid_to, learned_at, expired_at, confidence, activation, last_accessed |
| `summaries` | `content` | id, created_at, session_id, content, topics |
| `turns` | `content` | id, session_id, role, content, timestamp, topic_tags, weight, channel |
| `bookmarks` | `moment` | id, session_id, created_at, moment, quote |
| `entities` | `name` | id, name, entity_type, mention_count, first_seen, last_seen |

**BM25 parameters:** k1=1.5, b=0.75 (defaults in function signature).

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
For each table:
1. Vector search: embed query, compute cosine similarity against all rows with embeddings, return top `n*3`
2. BM25 search: tokenize query and all docs, compute BM25 scores, return top `n*3`
3. Merge: min-max normalize both result sets, weighted sum (`vectorWeight * vec + (1-vectorWeight) * txt`)
4. Fetch full row data for top `n*2` merged results
5. MMR de-duplication: skip results with >80% token overlap with already-selected results
6. Return top `n` results sorted by score

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
Re-embeds all rows in specified table(s). Processes in chunks of 64. Logs progress.

### Dependencies
- `better-sqlite3`, `config.ts`, `embeddings.ts`, `memory.ts`

---

## agent-manager.ts

Multi-agent discovery, switching, and state management. Port of `core/agent_manager.py`. 289 lines.

### Constants

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

```typescript
export function discoverAgents(): AgentInfo[];
```
Scans `~/.atrophy/agents/` and `<BUNDLE_ROOT>/agents/`. Looks for directories containing a `data/` subdirectory with `agent.json`. User agents override bundle by name. System-role agents sort first, then alphabetical.

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

```typescript
export function cycleAgent(direction: number, current: string): string | null;
```
Returns next/prev enabled agent name. Wraps around, skips disabled agents. Returns null if only one agent exists.

**Session deferral:**

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

```typescript
export function getAgentRoster(exclude?: string): AgentInfo[];
// discoverAgents() filtered to enabled agents, excluding named agent.
```

### Dependencies
- `config.ts`, `child_process`

---

## telegram.ts

Telegram Bot API client. Port of `channels/telegram.py`. 380 lines.

### Exported Functions

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

### Dependencies
- `config.ts`, `agent-manager.ts`

---

## telegram-daemon.ts

Telegram polling daemon. Port of `channels/telegram_daemon.py`. 516 lines.

### Constants

```typescript
const STATE_FILE = path.join(USER_DATA, '.telegram_daemon_state.json');
const LOCK_FILE = path.join(USER_DATA, '.telegram_daemon.lock');
const PLIST_LABEL = 'com.atrophiedmind.telegram-daemon';
```

### Instance Locking

```typescript
export function acquireLock(): boolean;
```
Uses `O_EXLOCK` (0x20) | `O_NONBLOCK` (0x4000) on macOS for advisory exclusive lock. Falls back to pid-check strategy on other platforms. Writes PID to lock file.

```typescript
export function releaseLock(): void;
```

### launchd Management

```typescript
export function installLaunchd(electronBin: string): void;
// Generates XML plist with KeepAlive=true, RunAtLoad=true.
// Unloads existing plist first if installed.

export function uninstallLaunchd(): void;

export function isLaunchdInstalled(): boolean;
```

### Daemon Control

```typescript
export function startDaemon(intervalMs = 10_000): boolean;
// Acquires lock, loads last update ID from state file.
// Initial poll + setInterval for recurring polls. Returns false if locked.

export function stopDaemon(): void;
// Clears interval, releases lock.

export function isDaemonRunning(): boolean;
```

### Message Dispatch

Internal `dispatchToAgent(agentName, text)`:
1. Temporarily switches config via `reloadForAgent()`
2. Initializes DB
3. Loads system prompt
4. Gets last CLI session ID
5. Runs streaming inference with `[Telegram message from Will]` prefix
6. Restores original agent config

Handles utility commands: `/status` (lists all agents with emoji, state), `/mute` (toggles mute on specified agent).

### Dependencies
- `config.ts`, `telegram.ts`, `router.ts`, `agent-manager.ts`, `inference.ts`, `context.ts`, `memory.ts`

---

## router.ts

Two-tier message routing. Port of `channels/router.py`. 269 lines.

### Exported Interface

```typescript
export interface RoutingDecision {
  agents: string[];
  tier: 'explicit' | 'agent' | 'single' | 'none';
  text: string;  // cleaned text (command prefix or agent name removed)
}
```

### Exported Functions

```typescript
export async function routeMessage(text: string): Promise<RoutingDecision>;
```
1. Loads agent registry (enabled and not muted agents with wake words and emoji)
2. If 0 agents: `{ agents: [], tier: 'none' }`
3. If 1 agent: `{ agents: [name], tier: 'single' }`
4. **Tier 1 - Explicit** (no inference): `/command`, `@mention`, `name:` prefix, wake words, multiple agents named in text
5. **Tier 2 - LLM routing** (Haiku, low effort): Asks routing agent to return JSON array of agent slugs

**Route file IPC:**

```typescript
export function enqueueRoute(
  messageId: number, text: string, decision: RoutingDecision
): void;
// Appends to ~/.atrophy/.telegram_routes.json. Keeps last 50 entries.

export function dequeueRoute(agentName: string): RouteEntry | null;
// Finds first route targeting the agent, removes agent from the route's agent list.
// Removes entry entirely if no agents remain.
```

### Dependencies
- `config.ts`, `agent-manager.ts`, `inference.ts`

---

## server.ts

HTTP API server. Port of `server.py`. 349 lines. Uses raw Node `http` module.

### Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/health` | GET | No | Returns `{ status: 'ok', agent, display_name }` |
| `/chat` | POST | Yes | Blocking chat - returns full response |
| `/chat/stream` | POST | Yes | SSE streaming chat |
| `/memory/search` | GET | Yes | Vector search via query param `q`, optional `limit` |
| `/memory/threads` | GET | Yes | Active conversation threads |
| `/session` | GET | Yes | Current session info |

### Auth

Bearer token stored in `~/.atrophy/server_token`. Auto-generated (32 bytes, base64url) on first launch. File mode `0o600`. Required on all endpoints except `/health`.

### Behavior

- `inferLock` boolean prevents concurrent inference - returns 429 if busy
- Session auto-created on first request
- System prompt loaded lazily
- SSE format: `data: {"type": "text", "content": "..."}\n\n`

### Exported Functions

```typescript
export function startServer(port = 5000, host = '127.0.0.1'): void;

export function stopServer(): void;
// Closes HTTP server and ends session.
```

### Dependencies
- `http`, `crypto`, `config.ts`, `memory.ts`, `session.ts`, `context.ts`, `inference.ts`, `vector-search.ts`

---

## cron.ts

launchd job management. Port of `scripts/cron.py`. 333 lines.

### Exported Interfaces

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

`parseCron(cronStr)` parses standard 5-field cron: `min hour dom month dow`. Maps non-`*` fields to `CalendarInterval` object with `Minute`, `Hour`, `Day`, `Month`, `Weekday`.

### Plist Generation

Generates XML plists with:
- `Label`: `com.atrophiedmind.<agent>.<jobname>`
- `ProgramArguments`: `[pythonPath, scriptPath, ...args]`
- `WorkingDirectory`: `BUNDLE_ROOT`
- `StandardOutPath`/`StandardErrorPath`: `<BUNDLE_ROOT>/logs/<agent>/<jobname>.log`
- `EnvironmentVariables`: PATH + AGENT
- Either `StartCalendarInterval` or `StartInterval`

### Exported Functions

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

### Dependencies
- `config.ts`, `child_process`

---

## install.ts

Login item management. 38 lines.

### Exported Functions

```typescript
export function isLoginItemEnabled(): boolean;
// app.getLoginItemSettings().openAtLogin

export function enableLoginItem(): void;
// app.setLoginItemSettings({ openAtLogin: true, openAsHidden: true, args: ['--app'] })

export function disableLoginItem(): void;
// app.setLoginItemSettings({ openAtLogin: false })

export function toggleLoginItem(enabled: boolean): void;
```

### Dependencies
- `electron` (app)

---

## create-agent.ts

Agent scaffolding. Port of `scripts/create_agent.py`. 552 lines.

### Exported Interfaces

```typescript
export interface VoiceConfig {
  ttsBackend?: string;
  elevenlabsVoiceId?: string;
  elevenlabsModel?: string;
  elevenlabsStability?: number;
  elevenlabsSimilarity?: number;
  elevenlabsStyle?: number;
  falVoiceId?: string;
  playbackRate?: number;
}

export interface AppearanceConfig {
  hasAvatar?: boolean;
  appearanceDescription?: string;
  avatarResolution?: number;
}

export interface ToolsConfig {
  disabledTools?: string[];
  customSkills?: Array<{ name: string; description: string }>;
}

export interface CreateAgentOptions {
  name?: string;           // slug (derived from displayName if omitted)
  displayName: string;
  description?: string;
  userName?: string;       // default 'User'
  openingLine?: string;    // default 'Hello.'
  wakeWords?: string[];
  telegramEmoji?: string;
  originStory?: string;
  coreNature?: string;
  characterTraits?: string;
  values?: string;
  relationship?: string;
  wontDo?: string;
  frictionModes?: string;
  sessionLimitBehaviour?: string;
  softLimitMins?: number;  // default 60
  writingStyle?: string;
  voice?: VoiceConfig;
  appearance?: AppearanceConfig;
  tools?: ToolsConfig;
  heartbeatActiveStart?: number;   // default 9
  heartbeatActiveEnd?: number;     // default 22
  heartbeatIntervalMins?: number;  // default 30
  outreachStyle?: string;
  telegramBotToken?: string;
  telegramChatId?: string;
}

export interface AgentManifest {
  name: string;
  display_name: string;
  description: string;
  user_name: string;
  opening_line: string;
  wake_words: string[];
  telegram_emoji: string;
  voice: { tts_backend, elevenlabs_voice_id, elevenlabs_model, elevenlabs_stability,
           elevenlabs_similarity, elevenlabs_style, fal_voice_id, playback_rate };
  telegram: { bot_token_env, chat_id_env };
  display: { window_width: 622, window_height: 830, title };
  heartbeat: { active_start, active_end, interval_mins };
  avatar?: { description, resolution };
  disabled_tools?: string[];
}
```

### Exported Functions

```typescript
export function createAgent(opts: CreateAgentOptions): AgentManifest;
```
Creates the full directory structure under `~/.atrophy/agents/<name>/`:

**Directories:** `data/`, `prompts/`, `avatar/source/`, `avatar/loops/`, `avatar/candidates/`, `audio/`, `skills/`, `notes/journal/`, `notes/evolution-log/`, `notes/conversations/`, `notes/tasks/`, `state/`

**Files generated:**
- `data/agent.json` - full manifest with voice, telegram, display, heartbeat config
- `prompts/system.md` - generated system prompt with origin, character, values, constraints, friction, capabilities, session behaviour
- `prompts/soul.md` - working notes document
- `prompts/heartbeat.md` - heartbeat checklist template with timing, unfinished threads, agent-specific considerations
- `skills/system.md` and `skills/soul.md` - copies of prompts
- Custom skill files from `tools.customSkills`
- Starter notes: `reflections.md`, `for-<user>.md`, `threads.md`, `journal-prompts.md`, `gifts.md`
- `data/memory.db` - initialized with schema.sql

**Slug generation:** `slugify()` lowercases, replaces non-alphanumeric chars with underscores.

**Description truncation:** Capped at 120 chars (117 + "...").

**Telegram env key naming:** `TELEGRAM_BOT_TOKEN_<NAME>` and `TELEGRAM_CHAT_ID_<NAME>` (uppercase slug).

### Dependencies
- `better-sqlite3`, `config.ts`

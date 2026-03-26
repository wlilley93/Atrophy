# src/main/memory.ts - SQLite Memory Layer

**Line count:** ~1524 lines  
**Dependencies:** `better-sqlite3`, `./config`, `./embeddings`, `./logger`  
**Purpose:** Three-layer memory architecture (Episodic → Semantic → Identity) with vector embeddings

## Overview

This module implements the SQLite data layer that persists everything the agent knows. It uses a three-layer memory architecture:

1. **Episodic:** Raw turn-by-turn conversation records (permanent, immutable)
2. **Semantic:** Summaries, threads, observations (distilled understanding)
3. **Identity:** Identity snapshots, trust logs, emotional state (agent's self-model)

Each agent has its own database at `~/.atrophy/agents/<name>/data/memory.db` with WAL mode for concurrent reads.

## Database Connection Management

```typescript
const _connections = new Map<string, Database.Database>();

function connect(dbPath: string): Database.Database {
  let db = _connections.get(dbPath);
  if (db) return db;

  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  db = new Database(dbPath);
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = ON');
  _connections.set(dbPath, db);
  return db;
}

export function getDb(): Database.Database {
  const config = getConfig();
  return connect(config.DB_PATH);
}
```

**Key features:**
- Connection pooling by database path (supports multiple agents)
- WAL mode for concurrent reads during background embedding
- Foreign keys enabled for referential integrity

## Schema & Migrations

```typescript
export function initDb(dbPath?: string): void {
  const p = dbPath || getConfig().DB_PATH;
  const db = connect(p);
  const config = getConfig();
  const schema = fs.readFileSync(config.SCHEMA_PATH, 'utf-8');
  
  try {
    db.exec(schema);
    migrate(db);
  } catch {
    migrate(db);
    db.exec(schema);
  }
}
```

**Why try/catch:** Schema may reference columns that don't exist in old databases. Migration adds missing columns first, then schema creates indexes.

### Migration Function

```typescript
function migrate(db: Database.Database): void {
  const safeAddColumn = (table: string, column: string, typedef: string) => {
    try {
      db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${typedef}`);
    } catch { /* Column already exists */ }
  };
  
  // Migrate turns table (legacy role 'companion' -> 'agent')
  if (tableNames.has('turns')) {
    safeAddColumn('turns', 'channel', "TEXT DEFAULT 'direct'");
    safeAddColumn('turns', 'embedding', 'BLOB');
    safeAddColumn('turns', 'weight', 'INTEGER DEFAULT 1');
    safeAddColumn('turns', 'topic_tags', 'TEXT');
    
    // Migrate legacy role via temp table swap (SQLite can't alter CHECK constraints)
    const checkSql = db.prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='turns'").get();
    if (checkSql && (checkSql.sql || '').includes("'companion'")) {
      // ... recreate turns table with correct CHECK constraint
    }
  }
  
  // Migrate observations (bi-temporal fields)
  if (tableNames.has('observations')) {
    safeAddColumn('observations', 'valid_from', 'DATETIME');
    safeAddColumn('observations', 'valid_to', 'DATETIME');
    safeAddColumn('observations', 'learned_at', 'DATETIME DEFAULT CURRENT_TIMESTAMP');
    safeAddColumn('observations', 'expired_at', 'DATETIME');
    safeAddColumn('observations', 'confidence', 'REAL DEFAULT 0.5');
    safeAddColumn('observations', 'activation', 'REAL DEFAULT 1.0');
    safeAddColumn('observations', 'last_accessed', 'DATETIME');
    safeAddColumn('observations', 'embedding', 'BLOB');
  }
  
  // Create new tables for v2 inner life system
  if (!tableNames.has('state_log')) { /* ... */ }
  if (!tableNames.has('need_events')) { /* ... */ }
  if (!tableNames.has('personality_log')) { /* ... */ }
  if (!tableNames.has('trust_log')) { /* ... */ }
}
```

**Migration strategy:**
- Additive changes use `ALTER TABLE ADD COLUMN`
- CHECK constraint changes require table recreation (SQLite limitation)
- New tables created if missing
- All operations wrapped in try/catch for idempotency

## Embedding Helpers

```typescript
export function vectorToBlob(vec: Float32Array): Buffer {
  return Buffer.from(vec.buffer, vec.byteOffset, vec.byteLength);
}

export function blobToVector(blob: Buffer): Float32Array {
  const copy = Buffer.alloc(blob.length);
  blob.copy(copy);
  return new Float32Array(copy.buffer, copy.byteOffset, copy.length / 4);
}
```

**Why copy the buffer:** better-sqlite3 may reuse the underlying ArrayBuffer. Copying ensures the vector data persists after the query result is released.

### Async Embedding (Fire-and-Forget)

```typescript
function embedAsync(table: string, rowId: number, text: string, dbPath?: string): void {
  const allowed = ['turns', 'summaries', 'observations', 'bookmarks'];
  if (!allowed.includes(table)) return;

  embed(text)
    .then((vec) => {
      const blob = embVectorToBlob(vec);
      const p = dbPath || getConfig().DB_PATH;
      const db = connect(p);
      db.prepare(`UPDATE ${table} SET embedding = ? WHERE id = ?`).run(blob, rowId);
    })
    .catch((err) => {
      log.error(`embed-async failed for ${table}:${rowId}:`, err);
    });
}
```

**Why fire-and-forget:** Turn insertion must be instant for conversational flow. Embedding runs in background and updates the row when complete. Search may miss very recent content (few seconds) but this tradeoff keeps turn insertion instant.

### Synchronous Embedding

```typescript
export async function embedAndStore(
  table: string,
  rowId: number,
  text: string,
  dbPath?: string,
): Promise<void> {
  const allowed = ['turns', 'summaries', 'observations', 'bookmarks'];
  if (!allowed.includes(table)) throw new Error(`embedAndStore: invalid table "${table}"`);
  const vec = await embed(text);
  const blob = embVectorToBlob(vec);
  const p = dbPath || getConfig().DB_PATH;
  const db = connect(p);
  db.prepare(`UPDATE ${table} SET embedding = ? WHERE id = ?`).run(blob, rowId);
}
```

**Use case:** Reindexing operations where completeness matters more than speed.

## Session Management

### startSession

```typescript
export function startSession(): number {
  const db = getDb();
  const result = db.prepare('INSERT INTO sessions DEFAULT VALUES').run();
  return Number(result.lastInsertRowid);
}
```

**Purpose:** Create a new session record. Returns session ID.

### endSession

```typescript
export function endSession(
  sessionId: number,
  summary: string | null = null,
  mood: string | null = null,
  notable = false,
): void {
  const db = getDb();
  db.prepare(
    `UPDATE sessions
     SET ended_at = CURRENT_TIMESTAMP,
         summary = COALESCE(?, summary),
         mood = COALESCE(?, mood),
         notable = ?
     WHERE id = ?`,
  ).run(summary, mood, notable ? 1 : 0, sessionId);
}
```

**COALESCE pattern:** Preserves existing summary/mood if not provided (allows incremental updates).

### closeStaleOpenSessions

```typescript
export function closeStaleOpenSessions(): number {
  const db = getDb();
  const result = db.prepare(
    `UPDATE sessions
     SET ended_at = COALESCE(
       (SELECT MAX(timestamp) FROM turns WHERE turns.session_id = sessions.id),
       started_at,
       CURRENT_TIMESTAMP
     ),
     summary = CASE
       WHEN (SELECT COUNT(*) FROM turns WHERE turns.session_id = sessions.id) > 0
       THEN COALESCE(summary, '[closed - no summary generated]')
       ELSE summary
     END
     WHERE ended_at IS NULL`,
  ).run();
  return result.changes;
}
```

**Purpose:** Close sessions orphaned by crashes or forced quits. Called on startup after `initDb()`.

**Logic:**
- Set `ended_at` to last turn timestamp, or `started_at`, or `CURRENT_TIMESTAMP`
- Sessions with turns get `[closed - no summary generated]` if no summary exists
- Sessions without turns keep null summary
- Returns number of sessions closed

### saveCliSessionId

```typescript
export function saveCliSessionId(sessionId: number, cliSessionId: string): void {
  const db = getDb();
  db.prepare('UPDATE sessions SET cli_session_id = ? WHERE id = ?').run(cliSessionId, sessionId);
}
```

**Purpose:** Link Atrophy session to Claude CLI session for `--resume` continuity.

### getLastCliSessionId

```typescript
export function getLastCliSessionId(): string | null {
  const db = getDb();
  const row = db.prepare(
    'SELECT cli_session_id FROM sessions WHERE cli_session_id IS NOT NULL ORDER BY id DESC LIMIT 1'
  ).get();
  return row?.cli_session_id || null;
}
```

**Purpose:** Retrieve last CLI session ID for conversation continuity across restarts.

### updateSessionMood

```typescript
export function updateSessionMood(sessionId: number, mood: string): void {
  const db = getDb();
  db.prepare('UPDATE sessions SET mood = ? WHERE id = ?').run(mood, sessionId);
}
```

**Purpose:** Update session mood detected during conversation.

## Turn Management

### writeTurn

```typescript
export function writeTurn(
  sessionId: number,
  role: 'will' | 'agent',
  content: string,
  topicTags?: string,
  weight = 1,
  channel = 'direct',
  emotionalVector?: Buffer,
): number {
  const db = getDb();
  const result = db.prepare(
    `INSERT INTO turns (session_id, role, content, topic_tags, weight, channel, emotional_vector)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).run(sessionId, role, content, topicTags || null, weight, channel, emotionalVector ?? null);
  const turnId = Number(result.lastInsertRowid);

  // Background embedding - does not block the conversation pipeline
  embedAsync('turns', turnId, content, getConfig().DB_PATH);

  return turnId;
}
```

**Parameters:**
- `sessionId`: Parent session ID
- `role`: `'will'` (user) or `'agent'`
- `content`: Message text
- `topicTags`: Optional topic labels
- `weight`: 1-5 importance (default 1)
- `channel`: `'direct'`, `'telegram'`, `'task'`
- `emotionalVector`: Optional 32-dim emotional state blob

**Returns:** Turn ID

**Side effect:** Triggers background embedding

### getRecentEmotionalVectors

```typescript
export function getRecentEmotionalVectors(
  hours = 24,
): Array<{ vec: Float32Array; timestamp: number }> {
  const db = getDb();
  const rows = db.prepare(
    `SELECT emotional_vector, timestamp
     FROM turns
     WHERE emotional_vector IS NOT NULL
       AND timestamp >= datetime('now', ? || ' hours')
     ORDER BY timestamp ASC`,
  ).all(`-${hours}`) as Array<{ emotional_vector: Buffer; timestamp: string }>;

  return rows.map((row) => ({
    vec: blobToVector(row.emotional_vector),
    timestamp: new Date(row.timestamp).getTime(),
  }));
}
```

**Purpose:** Retrieve turns with emotional vectors for distributed state computation.

### getSessionTurns

```typescript
export function getSessionTurns(sessionId: number): Turn[] {
  const db = getDb();
  return db.prepare('SELECT * FROM turns WHERE session_id = ? ORDER BY timestamp').all(sessionId) as Turn[];
}
```

**Purpose:** Get all turns from a session in chronological order.

### getRecentCompanionTurns

```typescript
export function getRecentCompanionTurns(limit = 4): string[] {
  const db = getDb();
  const rows = db.prepare(
    "SELECT content FROM turns WHERE role = 'agent' ORDER BY timestamp DESC LIMIT ?"
  ).all(limit) as { content: string }[];
  return rows.map((r) => r.content);
}
```

**Purpose:** Get last N agent turns for context injection.

### getLastInteractionTime

```typescript
export function getLastInteractionTime(): string | null {
  const db = getDb();
  const row = db.prepare(
    'SELECT timestamp FROM turns ORDER BY timestamp DESC LIMIT 1'
  ).get();
  return row?.timestamp || null;
}
```

**Purpose:** Get timestamp of most recent turn (any role).

### getLastSessionTime

```typescript
export function getLastSessionTime(): string | null {
  const db = getDb();
  const row = db.prepare(
    'SELECT started_at FROM sessions ORDER BY id DESC LIMIT 1 OFFSET 1'
  ).get();
  return row?.started_at || null;
}
```

**Purpose:** Get start time of second-to-last session (for time-gap detection).

### getTodaysTurns

```typescript
export function getTodaysTurns(): Turn[] {
  const db = getDb();
  return db.prepare(
    `SELECT t.* FROM turns t
     JOIN sessions s ON t.session_id = s.id
     WHERE DATE(s.started_at) = DATE('now')
     ORDER BY t.timestamp`,
  ).all() as Turn[];
}
```

**Purpose:** Get all turns from sessions started today.

## Summary Management

### writeSummary

```typescript
export function writeSummary(sessionId: number, content: string, topics?: string): number {
  const db = getDb();
  const result = db.prepare(
    `INSERT INTO summaries (session_id, content, topics) VALUES (?, ?, ?)`,
  ).run(sessionId, content, topics || null);
  const summaryId = Number(result.lastInsertRowid);
  embedAsync('summaries', summaryId, content, getConfig().DB_PATH);
  return summaryId;
}
```

**Purpose:** Store session summary with background embedding.

### getRecentSummaries

```typescript
export function getRecentSummaries(n = 3): memory.Summary[] {
  const db = getDb();
  return db.prepare(
    'SELECT * FROM summaries ORDER BY created_at DESC LIMIT ?'
  ).all(n) as memory.Summary[];
}
```

**Purpose:** Get last N summaries for context injection.

## Thread Management

### createThread

```typescript
export function createThread(name: string, summary?: string): number {
  const db = getDb();
  const result = db.prepare(
    `INSERT INTO threads (name, summary, status) VALUES (?, ?, 'active')`,
  ).run(name, summary || null);
  return Number(result.lastInsertRowid);
}
```

### updateThread

```typescript
export function updateThread(
  threadId: number,
  opts: { summary?: string; status?: 'active' | 'dormant' | 'resolved' },
): void {
  const db = getDb();
  const sets: string[] = [];
  const args: unknown[] = [];
  
  if (opts.summary !== undefined) {
    sets.push('summary = ?');
    args.push(opts.summary);
  }
  if (opts.status !== undefined) {
    sets.push('status = ?');
    args.push(opts.status);
  }
  if (sets.length > 0) {
    sets.push('last_updated = CURRENT_TIMESTAMP');
    args.push(threadId);
    db.prepare(`UPDATE threads SET ${sets.join(', ')} WHERE id = ?`).run(...args);
  }
}
```

**Dynamic SQL:** Only updates provided fields.

### getActiveThreads

```typescript
export function getActiveThreads(): Thread[] {
  const db = getDb();
  return db.prepare(
    "SELECT * FROM threads WHERE status = 'active' ORDER BY last_updated DESC"
  ).all() as Thread[];
}
```

## Observation Management

### writeObservation

```typescript
export function writeObservation(
  content: string,
  sourceTurn?: number,
  confidence = 0.5,
  validFrom?: string,
): number {
  const db = getDb();
  const result = db.prepare(
    `INSERT INTO observations (content, source_turn, confidence, valid_from, learned_at)
     VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)`,
  ).run(content, sourceTurn || null, confidence, validFrom || null);
  const obsId = Number(result.lastInsertRowid);
  embedAsync('observations', obsId, content, getConfig().DB_PATH);
  return obsId;
}
```

**Bi-temporal design:**
- `valid_from`: When the fact became true (event time)
- `learned_at`: When the agent learned it (transaction time)

### markObservationIncorporated

```typescript
export function markObservationIncorporated(obsId: number): void {
  const db = getDb();
  db.prepare('UPDATE observations SET incorporated = 1 WHERE id = ?').run(obsId);
}
```

**Purpose:** Mark observation as reviewed and confirmed by the agent.

### retireObservation

```typescript
export function retireObservation(obsId: number): void {
  const db = getDb();
  db.prepare('UPDATE observations SET expired_at = CURRENT_TIMESTAMP WHERE id = ?').run(obsId);
}
```

**Purpose:** Mark observation as no longer valid (person changed).

### markObservationsStale

```typescript
export function markObservationsStale(olderThanDays = 30): number {
  const db = getDb();
  const result = db.prepare(
    `UPDATE observations
     SET content = '[stale] ' || content
     WHERE incorporated = 0
       AND created_at < datetime('now', ? || ' days')
       AND content NOT LIKE '[stale] %'`,
  ).run(`-${olderThanDays}`);
  return result.changes;
}
```

**Purpose:** Flag old, unreviewed observations as stale.

### getTodaysObservations

```typescript
export function getTodaysObservations(): Observation[] {
  const db = getDb();
  return db.prepare(
    "SELECT * FROM observations WHERE DATE(created_at) = DATE('now') ORDER BY created_at"
  ).all() as Observation[];
}
```

## Identity Snapshot Management

### writeIdentitySnapshot

```typescript
export function writeIdentitySnapshot(content: string, trigger?: string): number {
  const db = getDb();
  const result = db.prepare(
    `INSERT INTO identity_snapshots (content, trigger) VALUES (?, ?)`,
  ).run(content, trigger || null);
  return Number(result.lastInsertRowid);
}
```

### getLatestIdentity

```typescript
export function getLatestIdentity(): IdentitySnapshot | null {
  const db = getDb();
  const row = db.prepare(
    'SELECT * FROM identity_snapshots ORDER BY created_at DESC LIMIT 1'
  ).get() as IdentitySnapshot | undefined;
  return row || null;
}
```

## Bookmark Management

### writeBookmark

```typescript
export function writeBookmark(
  sessionId: number,
  moment: string,
  quote?: string,
): number {
  const db = getDb();
  const result = db.prepare(
    `INSERT INTO bookmarks (session_id, moment, quote) VALUES (?, ?, ?)`,
  ).run(sessionId, moment, quote || null);
  const bookmarkId = Number(result.lastInsertRowid);
  embedAsync('bookmarks', bookmarkId, moment, getConfig().DB_PATH);
  return bookmarkId;
}
```

## Tool Call Audit

### writeToolCall

```typescript
export function writeToolCall(
  sessionId: number,
  toolName: string,
  inputJson?: string,
  flagged = false,
): number {
  const db = getDb();
  const result = db.prepare(
    `INSERT INTO tool_calls (session_id, tool_name, input_json, flagged)
     VALUES (?, ?, ?, ?)`,
  ).run(sessionId, toolName, inputJson || null, flagged ? 1 : 0);
  return Number(result.lastInsertRowid);
}
```

## Entity Management

### upsertEntity

```typescript
export function upsertEntity(name: string, entityType: string): number {
  const db = getDb();
  const result = db.prepare(
    `INSERT INTO entities (name, entity_type, mention_count, first_seen, last_seen)
     VALUES (?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
     ON CONFLICT(name) DO UPDATE SET
       mention_count = mention_count + 1,
       last_seen = CURRENT_TIMESTAMP
     RETURNING id`,
  ).get(name, entityType) as { id: number };
  return result.id;
}
```

**Upsert pattern:** Insert or increment mention count on conflict.

### linkEntities

```typescript
export function linkEntities(
  entityA: number,
  entityB: number,
  relation: string,
): void {
  const db = getDb();
  // Check for existing relation in both directions
  const existing = db.prepare(
    `SELECT id FROM entity_relations
     WHERE (entity_a = ? AND entity_b = ?) OR (entity_a = ? AND entity_b = ?)`,
  ).get(entityA, entityB, entityB, entityA) as { id: number } | undefined;
  
  if (existing) {
    db.prepare(
      `UPDATE entity_relations SET strength = MIN(1.0, strength + 0.1), last_seen = CURRENT_TIMESTAMP
       WHERE id = ?`,
    ).run(existing.id);
  } else {
    db.prepare(
      `INSERT INTO entity_relations (entity_a, entity_b, relation, strength, first_seen, last_seen)
       VALUES (?, ?, ?, 0.5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)`,
    ).run(entityA, entityB, relation);
  }
}
```

**Bidirectional check:** Prevents duplicate relations regardless of entity order.

## Trust Log

### writeTrustLog

```typescript
export function writeTrustLog(
  domain: string,
  delta: number,
  newValue: number,
  reason = '',
  source = 'unknown',
): void {
  const db = getDb();
  db.prepare(
    `INSERT INTO trust_log (domain, delta, new_value, reason, source)
     VALUES (?, ?, ?, ?, ?)`,
  ).run(domain, delta, newValue, reason, source);
}
```

### getLatestTrustValues

```typescript
export function getLatestTrustValues(): Record<string, number> {
  const db = getDb();
  const rows = db.prepare(
    `SELECT domain, new_value FROM (
      SELECT domain, new_value, ROW_NUMBER() OVER (PARTITION BY domain ORDER BY timestamp DESC) as rn
      FROM trust_log
    ) WHERE rn = 1`,
  ).all() as Array<{ domain: string; new_value: number }>;
  
  const result: Record<string, number> = {};
  for (const row of rows) {
    result[row.domain] = row.new_value;
  }
  return result;
}
```

**Purpose:** Get latest trust value for each domain (for reconciliation after decay).

## State Log

### writeStateLog

```typescript
export function writeStateLog(
  category: string,
  dimension: string,
  delta: number,
  newValue: number,
  reason = '',
  source = 'unknown',
): void {
  const db = getDb();
  db.prepare(
    `INSERT INTO state_log (category, dimension, delta, new_value, reason, source)
     VALUES (?, ?, ?, ?, ?, ?)`,
  ).run(category, dimension, delta, newValue, reason, source);
}
```

**Purpose:** Audit trail for all dimension changes (emotions, trust, needs, personality, relationship).

## Exported Types

| Interface | Purpose |
|-----------|---------|
| `Session` | Conversation session record |
| `Turn` | Individual message (user or agent) |
| `Summary` | Session summary (2-3 sentences) |
| `Thread` | Ongoing topic across sessions |
| `Observation` | Fact about user (bi-temporal) |
| `IdentitySnapshot` | Agent's self-understanding |
| `Bookmark` | Significant moment marker |
| `ToolCall` | MCP tool call audit record |
| `UsageEntry` | Token usage tracking |
| `Entity` | Knowledge graph node |
| `EntityRelation` | Knowledge graph edge |
| `TrustLogEntry` | Trust change audit record |
| `CrossAgentSearchResult` | Cross-agent search result |

## Exported API Summary

### Connection
| Function | Purpose |
|----------|---------|
| `getDb()` | Get database connection for current agent |
| `initDb(dbPath)` | Initialize schema and run migrations |
| `closeAll()` | Close all database connections |
| `closeForPath(dbPath)` | Close connection for specific path |
| `closeStaleOpenSessions()` | Close orphaned sessions on startup |

### Sessions
| Function | Purpose |
|----------|---------|
| `startSession()` | Create new session |
| `endSession(id, summary, mood, notable)` | End session with summary |
| `saveCliSessionId(id, cliId)` | Link to Claude CLI session |
| `getLastCliSessionId()` | Get last CLI session for resume |
| `updateSessionMood(id, mood)` | Update session mood |

### Turns
| Function | Purpose |
|----------|---------|
| `writeTurn(...)` | Write turn with background embedding |
| `getSessionTurns(sessionId)` | Get all turns from session |
| `getRecentCompanionTurns(limit)` | Get last N agent turns |
| `getLastInteractionTime()` | Get last turn timestamp |
| `getLastSessionTime()` | Get second-to-last session start |
| `getTodaysTurns()` | Get turns from today |
| `getRecentEmotionalVectors(hours)` | Get turns with emotional vectors |

### Summaries
| Function | Purpose |
|----------|---------|
| `writeSummary(sessionId, content, topics)` | Write session summary |
| `getRecentSummaries(n)` | Get last N summaries |

### Threads
| Function | Purpose |
|----------|---------|
| `createThread(name, summary)` | Create new thread |
| `updateThread(id, opts)` | Update thread summary/status |
| `getActiveThreads()` | Get active threads |

### Observations
| Function | Purpose |
|----------|---------|
| `writeObservation(content, sourceTurn, confidence, validFrom)` | Write observation |
| `markObservationIncorporated(obsId)` | Mark as reviewed |
| `retireObservation(obsId)` | Mark as expired |
| `markObservationsStale(days)` | Flag old unreviewed observations |
| `getTodaysObservations()` | Get today's observations |

### Identity
| Function | Purpose |
|----------|---------|
| `writeIdentitySnapshot(content, trigger)` | Write identity snapshot |
| `getLatestIdentity()` | Get most recent snapshot |

### Bookmarks
| Function | Purpose |
|----------|---------|
| `writeBookmark(sessionId, moment, quote)` | Write bookmark |

### Tool Calls
| Function | Purpose |
|----------|---------|
| `writeToolCall(sessionId, toolName, inputJson, flagged)` | Write tool call audit |

### Entities
| Function | Purpose |
|----------|---------|
| `upsertEntity(name, entityType)` | Insert or increment entity |
| `linkEntities(a, b, relation)` | Link entities with relation |

### Trust/State Logs
| Function | Purpose |
|----------|---------|
| `writeTrustLog(domain, delta, newValue, reason, source)` | Log trust change |
| `getLatestTrustValues()` | Get latest trust per domain |
| `writeStateLog(category, dimension, delta, newValue, reason, source)` | Log state change |

### Embedding
| Function | Purpose |
|----------|---------|
| `embedAndStore(table, rowId, text, dbPath)` | Embed and store synchronously |
| `vectorToBlob(vec)` | Serialize vector to blob |
| `blobToVector(blob)` | Deserialize blob to vector |

## See Also

- `db/schema.sql` - Full database schema
- `src/main/embeddings.ts` - Vector embedding engine
- `src/main/vector-search.ts` - Hybrid search implementation
- `src/main/inner-life.ts` - Emotional state management

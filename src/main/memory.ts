/**
 * SQLite memory layer - three-layer architecture: Episodic -> Semantic -> Identity.
 * Port of core/memory.py.
 */

import Database from 'better-sqlite3';
import * as fs from 'fs';
import * as path from 'path';
import { getConfig, USER_DATA, BUNDLE_ROOT } from './config';
import { embed, vectorToBlob as embVectorToBlob } from './embeddings';
import { createLogger } from './logger';

const log = createLogger('memory');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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

export interface TrustLogEntry {
  id: number;
  timestamp: string;
  domain: string;
  delta: number;
  new_value: number;
  reason: string;
  source: string;
}

export interface CrossAgentSearchResult {
  agent: string;
  turns: Pick<Turn, 'id' | 'session_id' | 'role' | 'content' | 'timestamp'>[];
  summaries: Pick<Summary, 'session_id' | 'content' | 'created_at'>[];
  error?: string;
}

// ---------------------------------------------------------------------------
// Embedding helpers
// ---------------------------------------------------------------------------

export function vectorToBlob(vec: Float32Array): Buffer {
  return Buffer.from(vec.buffer, vec.byteOffset, vec.byteLength);
}

export function blobToVector(blob: Buffer): Float32Array {
  // Copy the buffer - better-sqlite3 may reuse the underlying ArrayBuffer
  const copy = Buffer.alloc(blob.length);
  blob.copy(copy);
  return new Float32Array(copy.buffer, copy.byteOffset, copy.length / 4);
}

// ---------------------------------------------------------------------------
// Async embedding helper - fire-and-forget background embedding
// ---------------------------------------------------------------------------

function embedAsync(table: string, rowId: number, text: string, dbPath?: string): void {
  const allowed = ['turns', 'summaries', 'observations', 'bookmarks'];
  if (!allowed.includes(table)) return;

  // Capture DB_PATH at call time, not inside the async callback,
  // because config may have been reloaded for a different agent by then.
  const resolvedDbPath = dbPath || getConfig().DB_PATH;

  embed(text)
    .then((vec) => {
      const blob = embVectorToBlob(vec);
      const p = resolvedDbPath;
      const db = connect(p);
      db.prepare(`UPDATE ${table} SET embedding = ? WHERE id = ?`).run(blob, rowId);
    })
    .catch((err) => {
      log.error(`embed-async failed for ${table}:${rowId}:`, err);
    });
}

/**
 * Embed text and store the vector blob synchronously.
 * Useful when you need to guarantee the embedding is written before continuing.
 */
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

// ---------------------------------------------------------------------------
// Connection management
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Schema & migrations
// ---------------------------------------------------------------------------

export function initDb(dbPath?: string): void {
  const p = dbPath || getConfig().DB_PATH;
  const db = connect(p);
  const config = getConfig();
  const schema = fs.readFileSync(config.SCHEMA_PATH, 'utf-8');
  // Match Python approach: try schema first, then migrate + schema.
  // This handles edge cases where schema references columns not yet migrated.
  // Migrate runs exactly once in either path - not twice.
  try {
    db.exec(schema);
    migrate(db);
  } catch {
    // Schema has new columns/indexes the old DB lacks - migrate first
    migrate(db);
    db.exec(schema);
  }
}

function migrate(db: Database.Database): void {
  // Add missing columns safely
  const safeAddColumn = (table: string, column: string, typedef: string) => {
    try {
      db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${typedef}`);
    } catch {
      // Column already exists
    }
  };

  // Ensure tables exist before migration
  const tables = db
    .prepare("SELECT name FROM sqlite_master WHERE type='table'")
    .all() as { name: string }[];
  const tableNames = new Set(tables.map((t) => t.name));

  if (tableNames.has('turns')) {
    safeAddColumn('turns', 'channel', "TEXT DEFAULT 'direct'");
    safeAddColumn('turns', 'embedding', 'BLOB');
    safeAddColumn('turns', 'weight', 'INTEGER DEFAULT 1');
    safeAddColumn('turns', 'topic_tags', 'TEXT');

    // Migrate legacy role 'companion' -> 'agent' and drop old CHECK constraint.
    // SQLite can't alter CHECK constraints, so we recreate via temp table swap.
    const checkSql = db
      .prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name='turns'")
      .get() as { sql: string } | undefined;
    if (checkSql && (checkSql.sql || '').includes("'companion'")) {
      db.exec(`
        CREATE TABLE turns_tmp (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id  INTEGER REFERENCES sessions(id),
          role        TEXT NOT NULL,
          content     TEXT NOT NULL,
          timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
          topic_tags  TEXT,
          weight      INTEGER DEFAULT 1,
          channel     TEXT DEFAULT 'direct',
          embedding   BLOB
        );
        INSERT INTO turns_tmp SELECT * FROM turns;
        UPDATE turns_tmp SET role = 'agent' WHERE role = 'companion';
        DROP TABLE turns;
        CREATE TABLE turns (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id  INTEGER REFERENCES sessions(id),
          role        TEXT NOT NULL CHECK(role IN ('will', 'agent')),
          content     TEXT NOT NULL,
          timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
          topic_tags  TEXT,
          weight      INTEGER DEFAULT 1 CHECK(weight BETWEEN 1 AND 5),
          channel     TEXT DEFAULT 'direct',
          embedding   BLOB
        );
        INSERT INTO turns SELECT * FROM turns_tmp;
        DROP TABLE turns_tmp;
        CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
        CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp);
      `);
      log.info('migrated turns table: companion -> agent with correct CHECK constraint');
    }
  }

  if (tableNames.has('sessions')) {
    safeAddColumn('sessions', 'cli_session_id', 'TEXT');
    safeAddColumn('sessions', 'notable', 'BOOLEAN DEFAULT 0');
  }

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

  if (tableNames.has('summaries')) {
    try { db.exec('CREATE INDEX IF NOT EXISTS idx_summaries_session_id ON summaries(session_id)'); } catch { /* already exists */ }
  }

  if (tableNames.has('coherence_checks')) {
    safeAddColumn('coherence_checks', 'action', "TEXT DEFAULT 'none'");
  }

  if (tableNames.has('entities')) {
    safeAddColumn('entities', 'embedding', 'BLOB');
  }

  // emotional_vector columns for turns and observations
  if (tableNames.has('turns')) {
    try { db.exec('ALTER TABLE turns ADD COLUMN emotional_vector BLOB'); } catch { /* already exists */ }
  }
  if (tableNames.has('observations')) {
    try { db.exec('ALTER TABLE observations ADD COLUMN emotional_vector BLOB'); } catch { /* already exists */ }
  }

  // state_log table - expanded dimension change audit trail
  if (!tableNames.has('state_log')) {
    db.exec(`
      CREATE TABLE IF NOT EXISTS state_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
        category    TEXT NOT NULL CHECK(category IN (
          'emotion', 'trust', 'need', 'personality', 'relationship'
        )),
        dimension   TEXT NOT NULL,
        delta       REAL NOT NULL,
        new_value   REAL NOT NULL,
        reason      TEXT,
        source      TEXT DEFAULT 'unknown'
      );
      CREATE INDEX IF NOT EXISTS idx_state_log_cat ON state_log(category);
      CREATE INDEX IF NOT EXISTS idx_state_log_dim ON state_log(dimension);
      CREATE INDEX IF NOT EXISTS idx_state_log_ts ON state_log(timestamp);
    `);
    log.info('created state_log table');
  }

  // need_events table - need satisfaction events
  if (!tableNames.has('need_events')) {
    db.exec(`
      CREATE TABLE IF NOT EXISTS need_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
        need        TEXT NOT NULL,
        delta       REAL NOT NULL,
        trigger_desc TEXT,
        session_id  INTEGER REFERENCES sessions(id)
      );
      CREATE INDEX IF NOT EXISTS idx_need_events_need ON need_events(need);
    `);
    log.info('created need_events table');
  }

  // personality_log table - personality evolution audit trail
  if (!tableNames.has('personality_log')) {
    db.exec(`
      CREATE TABLE IF NOT EXISTS personality_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
        trait       TEXT NOT NULL,
        old_value   REAL NOT NULL,
        new_value   REAL NOT NULL,
        reason      TEXT,
        source      TEXT DEFAULT 'evolve'
      );
    `);
    log.info('created personality_log table');
  }

  // Trust log table - durable audit trail for trust changes
  if (!tableNames.has('trust_log')) {
    db.exec(`
      CREATE TABLE IF NOT EXISTS trust_log (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        domain    TEXT NOT NULL CHECK(domain IN ('emotional', 'intellectual', 'creative', 'practical', 'operational', 'personal')),
        delta     REAL NOT NULL,
        new_value REAL NOT NULL,
        reason    TEXT DEFAULT '',
        source    TEXT DEFAULT 'unknown'
      );
      CREATE INDEX IF NOT EXISTS idx_trust_log_domain ON trust_log(domain);
      CREATE INDEX IF NOT EXISTS idx_trust_log_timestamp ON trust_log(timestamp);
    `);
    log.info('created trust_log table');
  } else {
    // Migrate existing trust_log: widen the CHECK constraint so v2 domains
    // (operational, personal) can be logged. SQLite has no ALTER CHECK,
    // so recreate the table if the old constraint is still in place.
    try {
      const sqlRow = db.prepare(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='trust_log'",
      ).get() as { sql: string } | undefined;
      if (sqlRow?.sql && !sqlRow.sql.includes('operational')) {
        db.exec(`
          CREATE TABLE trust_log_new (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            domain    TEXT NOT NULL CHECK(domain IN ('emotional', 'intellectual', 'creative', 'practical', 'operational', 'personal')),
            delta     REAL NOT NULL,
            new_value REAL NOT NULL,
            reason    TEXT DEFAULT '',
            source    TEXT DEFAULT 'unknown'
          );
          INSERT INTO trust_log_new SELECT * FROM trust_log;
          DROP TABLE trust_log;
          ALTER TABLE trust_log_new RENAME TO trust_log;
          CREATE INDEX IF NOT EXISTS idx_trust_log_domain ON trust_log(domain);
          CREATE INDEX IF NOT EXISTS idx_trust_log_timestamp ON trust_log(timestamp);
        `);
        log.info('migrated trust_log CHECK constraint to v2 domains');
      }
    } catch (migErr) {
      log.warn(`trust_log migration skipped: ${migErr}`);
    }
  }
}

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

export function startSession(): number {
  const db = getDb();
  const result = db.prepare('INSERT INTO sessions DEFAULT VALUES').run();
  return Number(result.lastInsertRowid);
}

export function endSession(
  sessionId: number,
  summary: string | null = null,
  mood: string | null = null,
  notable = false,
  dbPath?: string,
): void {
  const db = dbPath ? connect(dbPath) : getDb();
  db.prepare(
    `UPDATE sessions
     SET ended_at = CURRENT_TIMESTAMP,
         summary = COALESCE(?, summary),
         mood = COALESCE(?, mood),
         notable = ?
     WHERE id = ?`,
  ).run(summary, mood, notable ? 1 : 0, sessionId);
}

/**
 * Close any sessions that were left open (ended_at IS NULL).
 *
 * This handles sessions orphaned by crashes, forced quits, or code paths
 * that forgot to call session.end(). Call this on startup after initDb()
 * so the DB starts clean. Sessions with no turns get a null summary;
 * sessions with turns get a "[closed - no summary generated]" marker.
 */
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

export function saveCliSessionId(sessionId: number, cliSessionId: string): void {
  const db = getDb();
  db.prepare('UPDATE sessions SET cli_session_id = ? WHERE id = ?').run(cliSessionId, sessionId);
}

export function getLastCliSessionId(): string | null {
  const db = getDb();
  const row = db
    .prepare('SELECT cli_session_id FROM sessions WHERE cli_session_id IS NOT NULL ORDER BY id DESC LIMIT 1')
    .get() as { cli_session_id: string } | undefined;
  return row?.cli_session_id || null;
}

export function updateSessionMood(sessionId: number, mood: string): void {
  const db = getDb();
  db.prepare('UPDATE sessions SET mood = ? WHERE id = ?').run(mood, sessionId);
}

// ---------------------------------------------------------------------------
// Turns
// ---------------------------------------------------------------------------

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
  const result = db
    .prepare(
      `INSERT INTO turns (session_id, role, content, topic_tags, weight, channel, emotional_vector)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    )
    .run(sessionId, role, content, topicTags || null, weight, channel, emotionalVector ?? null);
  const turnId = Number(result.lastInsertRowid);

  // Background embedding - does not block the conversation pipeline
  embedAsync('turns', turnId, content, getConfig().DB_PATH);

  return turnId;
}

/**
 * Retrieve turns from the last N hours that have an emotional_vector stored.
 * Returns each as a { vec, timestamp } pair for use in computeDistributedState.
 */
export function getRecentEmotionalVectors(
  hours = 24,
): Array<{ vec: Float32Array; timestamp: number }> {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT emotional_vector, timestamp
       FROM turns
       WHERE emotional_vector IS NOT NULL
         AND timestamp >= datetime('now', ? || ' hours')
       ORDER BY timestamp ASC`,
    )
    .all(`-${hours}`) as Array<{ emotional_vector: Buffer; timestamp: string }>;

  return rows.map((row) => ({
    vec: blobToVector(row.emotional_vector),
    timestamp: new Date(row.timestamp).getTime(),
  }));
}

export function getSessionTurns(sessionId: number): Turn[] {
  const db = getDb();
  return db
    .prepare('SELECT * FROM turns WHERE session_id = ? ORDER BY timestamp')
    .all(sessionId) as Turn[];
}

export function getRecentCompanionTurns(limit = 4): string[] {
  const db = getDb();
  const rows = db
    .prepare("SELECT content FROM turns WHERE role = 'agent' ORDER BY timestamp DESC LIMIT ?")
    .all(limit) as { content: string }[];
  return rows.map((r) => r.content);
}

export function getLastInteractionTime(): string | null {
  const db = getDb();
  const row = db
    .prepare('SELECT timestamp FROM turns ORDER BY timestamp DESC LIMIT 1')
    .get() as { timestamp: string } | undefined;
  return row?.timestamp || null;
}

export function getLastSessionTime(): string | null {
  const db = getDb();
  const row = db
    .prepare('SELECT started_at FROM sessions ORDER BY id DESC LIMIT 1 OFFSET 1')
    .get() as { started_at: string } | undefined;
  return row?.started_at || null;
}

export function getTodaysTurns(): Turn[] {
  const db = getDb();
  return db
    .prepare(
      `SELECT t.* FROM turns t
       JOIN sessions s ON t.session_id = s.id
       WHERE date(s.started_at) = date('now')
       ORDER BY t.timestamp`,
    )
    .all() as Turn[];
}

// ---------------------------------------------------------------------------
// Summaries
// ---------------------------------------------------------------------------

export function writeSummary(
  sessionId: number,
  content: string,
  topics?: string,
  dbPath?: string,
): number {
  const db = dbPath ? connect(dbPath) : getDb();
  const result = db
    .prepare('INSERT INTO summaries (session_id, content, topics) VALUES (?, ?, ?)')
    .run(sessionId, content, topics || null);
  const summaryId = Number(result.lastInsertRowid);

  // Background embedding
  embedAsync('summaries', summaryId, content);

  return summaryId;
}

export function getRecentSummaries(n = 3): Summary[] {
  const db = getDb();
  return db
    .prepare('SELECT * FROM summaries ORDER BY created_at DESC LIMIT ?')
    .all(n) as Summary[];
}

// ---------------------------------------------------------------------------
// Threads
// ---------------------------------------------------------------------------

export function createThread(name: string, summary?: string): number {
  const db = getDb();
  const result = db
    .prepare('INSERT INTO threads (name, summary, last_updated) VALUES (?, ?, CURRENT_TIMESTAMP)')
    .run(name, summary || null);
  return Number(result.lastInsertRowid);
}

export function updateThread(
  threadId: number,
  opts: { summary?: string; status?: 'active' | 'dormant' | 'resolved' },
): void {
  const db = getDb();
  const sets: string[] = ['last_updated = CURRENT_TIMESTAMP'];
  const params: unknown[] = [];
  if (opts.summary !== undefined) {
    sets.push('summary = ?');
    params.push(opts.summary);
  }
  if (opts.status !== undefined) {
    sets.push('status = ?');
    params.push(opts.status);
  }
  params.push(threadId);
  db.prepare(`UPDATE threads SET ${sets.join(', ')} WHERE id = ?`).run(...params);
}

export function updateThreadSummary(threadName: string, summary: string): void {
  const db = getDb();
  db.prepare(
    `UPDATE threads SET summary = ?, last_updated = CURRENT_TIMESTAMP
     WHERE LOWER(name) = LOWER(?)`,
  ).run(summary, threadName);
}

export function getActiveThreads(): Thread[] {
  const db = getDb();
  return db
    .prepare("SELECT * FROM threads WHERE status = 'active' ORDER BY last_updated DESC")
    .all() as Thread[];
}

// ---------------------------------------------------------------------------
// Identity snapshots
// ---------------------------------------------------------------------------

export function writeIdentitySnapshot(content: string, trigger?: string): number {
  const db = getDb();
  const result = db
    .prepare('INSERT INTO identity_snapshots (content, trigger) VALUES (?, ?)')
    .run(content, trigger || null);
  return Number(result.lastInsertRowid);
}

export function getLatestIdentity(): IdentitySnapshot | null {
  const db = getDb();
  return (
    (db
      .prepare('SELECT * FROM identity_snapshots ORDER BY created_at DESC LIMIT 1')
      .get() as IdentitySnapshot | undefined) || null
  );
}

// ---------------------------------------------------------------------------
// Observations
// ---------------------------------------------------------------------------

export function writeObservation(
  content: string,
  sourceTurn?: number,
  confidence = 0.5,
  validFrom?: string,
): number {
  const db = getDb();
  const result = db
    .prepare(
      `INSERT INTO observations (content, source_turn, confidence, valid_from)
       VALUES (?, ?, ?, ?)`,
    )
    .run(content, sourceTurn || null, confidence, validFrom || null);
  const obsId = Number(result.lastInsertRowid);

  // Background embedding
  embedAsync('observations', obsId, content);

  return obsId;
}

export function markObservationIncorporated(obsId: number): void {
  const db = getDb();
  db.prepare('UPDATE observations SET incorporated = 1 WHERE id = ?').run(obsId);
}

export function retireObservation(obsId: number): void {
  const db = getDb();
  db.prepare('DELETE FROM observations WHERE id = ?').run(obsId);
}

export function markObservationsStale(olderThanDays = 30): number {
  const db = getDb();
  // Match Python semantics: flag old un-incorporated observations as stale.
  // Uses incorporated = 0 (never reviewed/confirmed) rather than activation threshold.
  const result = db
    .prepare(
      `UPDATE observations
       SET content = '[stale] ' || content
       WHERE incorporated = 0
         AND content NOT LIKE '[stale]%'
         AND created_at < datetime('now', ?)`,
    )
    .run(`-${olderThanDays} days`);
  return result.changes;
}

export function getTodaysObservations(): Observation[] {
  const db = getDb();
  return db
    .prepare(
      `SELECT * FROM observations
       WHERE date(created_at) = date('now')
       ORDER BY created_at`,
    )
    .all() as Observation[];
}

export function getRecentObservations(
  limit = 10,
  activationThreshold?: number,
): Observation[] {
  const db = getDb();
  if (activationThreshold !== undefined) {
    return db
      .prepare(
        `SELECT * FROM observations
         WHERE COALESCE(activation, 1.0) >= ?
         ORDER BY created_at DESC LIMIT ?`,
      )
      .all(activationThreshold, limit) as Observation[];
  }
  return db
    .prepare(
      `SELECT * FROM observations
       ORDER BY created_at DESC LIMIT ?`,
    )
    .all(limit) as Observation[];
}

// ---------------------------------------------------------------------------
// Activation & decay
// ---------------------------------------------------------------------------

export function updateActivation(table: string, rowId: number): void {
  const allowed = ['observations', 'summaries', 'turns', 'bookmarks', 'entities'];
  if (!allowed.includes(table)) return;

  const db = getDb();
  // Tables with activation columns - avoids dynamic PRAGMA for validated tables
  const activationTables = new Set(['observations']);
  if (activationTables.has(table)) {
    db.prepare(
      `UPDATE ${table}
       SET activation = MIN(1.0, COALESCE(activation, 0.5) + 0.2),
           last_accessed = CURRENT_TIMESTAMP
       WHERE id = ?`,
    ).run(rowId);
  }
}

export function decayActivations(halfLifeDays = 30): void {
  const db = getDb();
  const decayConstant = Math.LN2 / halfLifeDays;
  const rows = db
    .prepare(
      `SELECT id, activation, last_accessed, created_at FROM observations
       WHERE activation > 0.01`,
    )
    .all() as {
      id: number;
      activation: number;
      last_accessed: string | null;
      created_at: string;
    }[];

  const update = db.prepare('UPDATE observations SET activation = ? WHERE id = ?');
  const now = Date.now();

  const batch = db.transaction(() => {
    for (const row of rows) {
      const refTime = row.last_accessed || row.created_at;
      const elapsed = Math.max(0, (now - new Date(refTime).getTime()) / (1000 * 60 * 60 * 24));
      let newActivation = row.activation * Math.exp(-decayConstant * elapsed);
      if (newActivation < 0.01) newActivation = 0;
      update.run(newActivation, row.id);
    }
  });
  batch();
}

// ---------------------------------------------------------------------------
// Bookmarks
// ---------------------------------------------------------------------------

export function writeBookmark(
  sessionId: number,
  moment: string,
  quote?: string,
): number {
  const db = getDb();
  const result = db
    .prepare('INSERT INTO bookmarks (session_id, moment, quote) VALUES (?, ?, ?)')
    .run(sessionId, moment, quote || null);
  const bmId = Number(result.lastInsertRowid);

  // Background embedding
  embedAsync('bookmarks', bmId, moment);

  return bmId;
}

export function getTodaysBookmarks(): Bookmark[] {
  const db = getDb();
  return db
    .prepare(
      `SELECT b.* FROM bookmarks b
       JOIN sessions s ON b.session_id = s.id
       WHERE date(s.started_at) = date('now')`,
    )
    .all() as Bookmark[];
}

// ---------------------------------------------------------------------------
// Entity management
// ---------------------------------------------------------------------------

const PERSON_TITLES = new Set(['mr', 'mrs', 'ms', 'dr', 'prof', 'professor']);

// Pattern 1: Capitalized multi-word names (e.g. "John Smith", "The Atrophied Mind")
const ENTITY_NAME_RE = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b/g;
// Pattern 2: Mid-sentence proper nouns (single capitalized word after lowercase)
const PROPER_NOUN_RE = /(?<=[a-z]\s)([A-Z][a-z]{2,})\b/g;
// Pattern 3: Quoted terms
const QUOTED_RE = /"([^"]{2,50})"/g;

const STOP_WORDS = new Set([
  'the', 'this', 'that', 'what', 'when', 'where', 'how',
  'which', 'while', 'also', 'just', 'very', 'really',
]);

function guessEntityType(name: string): string {
  const lower = name.toLowerCase();
  const words = lower.split(/\s+/);
  if (words[0] && PERSON_TITLES.has(words[0])) return 'person';
  if (/\b(project|system|framework|engine|app|tool)\b/.test(lower)) return 'project';
  if (/\b(street|road|city|park|building|country|place)\b/.test(lower)) return 'place';
  return 'concept';
}

/**
 * Extract entity names from text using regex patterns.
 * Returns raw name strings - use extractAndStoreEntities() for full DB integration.
 */
export function extractEntities(text: string): string[] {
  const found = new Set<string>();
  for (const re of [ENTITY_NAME_RE, PROPER_NOUN_RE, QUOTED_RE]) {
    let m: RegExpExecArray | null;
    re.lastIndex = 0;
    while ((m = re.exec(text)) !== null) {
      const name = (m[1] || m[0]).trim();
      if (name.length > 2 && !STOP_WORDS.has(name.toLowerCase())) {
        found.add(name);
      }
    }
  }
  return [...found];
}

/**
 * Full entity extraction with DB storage and cross-referencing.
 * Port of Python's extract_entities() - extracts entities from text,
 * upserts them in the DB, and returns enriched entity objects.
 */
export function extractAndStoreEntities(
  text: string,
): { id: number; name: string; entity_type: string; mention_count: number }[] {
  const db = getDb();
  const entities: { name: string; entity_type: string }[] = [];
  const seen = new Set<string>();

  // Pattern 1: Multi-word capitalized names
  {
    ENTITY_NAME_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = ENTITY_NAME_RE.exec(text)) !== null) {
      const name = m[1].trim();
      if (name.length > 2 && !seen.has(name.toLowerCase())) {
        seen.add(name.toLowerCase());
        entities.push({ name, entity_type: guessEntityType(name) });
      }
    }
  }

  // Pattern 2: Mid-sentence proper nouns
  {
    PROPER_NOUN_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = PROPER_NOUN_RE.exec(text)) !== null) {
      const name = m[1].trim();
      if (!seen.has(name.toLowerCase()) && !STOP_WORDS.has(name.toLowerCase())) {
        seen.add(name.toLowerCase());
        entities.push({ name, entity_type: 'concept' });
      }
    }
  }

  // Pattern 3: Quoted terms
  {
    QUOTED_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = QUOTED_RE.exec(text)) !== null) {
      const term = m[1].trim();
      if (term.length > 2 && !seen.has(term.toLowerCase())) {
        seen.add(term.toLowerCase());
        entities.push({ name: term, entity_type: 'concept' });
      }
    }
  }

  if (entities.length === 0) return [];

  // Batch lookup existing entities
  const placeholders = entities.map(() => '?').join(',');
  const existingRows = db
    .prepare(
      `SELECT id, LOWER(name) as lower_name, mention_count FROM entities
       WHERE LOWER(name) IN (${placeholders})`,
    )
    .all(...entities.map((e) => e.name.toLowerCase())) as {
      id: number;
      lower_name: string;
      mention_count: number;
    }[];
  const existingMap = new Map(existingRows.map((r) => [r.lower_name, r]));

  // Batch updates and inserts in a transaction
  const results: { id: number; name: string; entity_type: string; mention_count: number }[] = [];

  const updateStmt = db.prepare(
    `UPDATE entities SET mention_count = mention_count + 1,
     last_seen = CURRENT_TIMESTAMP WHERE id = ?`,
  );
  const insertStmt = db.prepare(
    `INSERT INTO entities (name, entity_type, last_seen)
     VALUES (?, ?, CURRENT_TIMESTAMP)`,
  );

  const batch = db.transaction(() => {
    for (const ent of entities) {
      const existing = existingMap.get(ent.name.toLowerCase());
      if (existing) {
        updateStmt.run(existing.id);
        results.push({
          id: existing.id,
          name: ent.name,
          entity_type: ent.entity_type,
          mention_count: existing.mention_count + 1,
        });
      } else {
        const res = insertStmt.run(ent.name, ent.entity_type);
        const id = Number(res.lastInsertRowid);
        results.push({
          id,
          name: ent.name,
          entity_type: ent.entity_type,
          mention_count: 1,
        });
      }
    }
  });
  batch();

  // Cross-reference: if multiple entities found in same text, link them
  if (results.length >= 2) {
    for (let i = 0; i < results.length; i++) {
      for (let j = i + 1; j < results.length; j++) {
        linkEntities(results[i].id, results[j].id, 'co_occurs');
      }
    }
  }

  return results;
}

export function upsertEntity(name: string, entityType?: string): number {
  const db = getDb();
  const existing = db
    .prepare('SELECT id, mention_count FROM entities WHERE LOWER(name) = LOWER(?)')
    .get(name) as { id: number; mention_count: number } | undefined;

  if (existing) {
    db.prepare(
      `UPDATE entities SET mention_count = mention_count + 1, last_seen = CURRENT_TIMESTAMP WHERE id = ?`,
    ).run(existing.id);
    return existing.id;
  }

  const result = db
    .prepare('INSERT INTO entities (name, entity_type, last_seen) VALUES (?, ?, CURRENT_TIMESTAMP)')
    .run(name, entityType || guessEntityType(name));
  return Number(result.lastInsertRowid);
}

/**
 * Create or strengthen a relationship between two entities.
 * Checks both directions (a->b and b->a) to avoid duplicates.
 */
export function linkEntities(
  entityA: number,
  entityB: number,
  relation: string,
): void {
  if (entityA === entityB) return;

  const db = getDb();
  // Check both directions
  const existing = db
    .prepare(
      `SELECT id, strength FROM entity_relations
       WHERE (entity_a = ? AND entity_b = ? AND relation = ?)
          OR (entity_a = ? AND entity_b = ? AND relation = ?)`,
    )
    .get(entityA, entityB, relation, entityB, entityA, relation) as
      { id: number; strength: number } | undefined;

  if (existing) {
    const newStrength = Math.min(1.0, (existing.strength || 0.5) + 0.1);
    db.prepare(
      `UPDATE entity_relations
       SET strength = ?, last_seen = CURRENT_TIMESTAMP
       WHERE id = ?`,
    ).run(newStrength, existing.id);
  } else {
    db.prepare(
      'INSERT INTO entity_relations (entity_a, entity_b, relation, last_seen) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
    ).run(entityA, entityB, relation);
  }
}

/**
 * Link two entities by name (convenience wrapper).
 * Creates the entities if they do not exist.
 */
export function linkEntitiesByName(
  nameA: string,
  nameB: string,
  relation = 'related_to',
): void {
  const idA = upsertEntity(nameA);
  const idB = upsertEntity(nameB);
  linkEntities(idA, idB, relation);
}

// ---------------------------------------------------------------------------
// Audit & logging
// ---------------------------------------------------------------------------

export function logToolCall(
  sessionId: number,
  toolName: string,
  inputJson?: string,
  flagged = false,
): void {
  const db = getDb();
  db.prepare(
    'INSERT INTO tool_calls (session_id, tool_name, input_json, flagged) VALUES (?, ?, ?, ?)',
  ).run(sessionId, toolName, inputJson || null, flagged ? 1 : 0);
}

export function logHeartbeat(
  decision: string,
  reason?: string,
  message?: string,
): void {
  const db = getDb();
  db.prepare('INSERT INTO heartbeats (decision, reason, message) VALUES (?, ?, ?)').run(
    decision,
    reason || null,
    message || null,
  );
}

export function logCoherenceCheck(
  score: number,
  degraded: boolean,
  signals: string,
  action = 'none',
): void {
  const db = getDb();
  db.prepare(
    'INSERT INTO coherence_checks (score, degraded, signals, action) VALUES (?, ?, ?, ?)',
  ).run(score, degraded ? 1 : 0, signals, action);
}

export function logUsage(
  source: string,
  tokensIn: number,
  tokensOut: number,
  durationMs: number,
  toolCount: number,
): void {
  const db = getDb();
  db.prepare(
    `INSERT INTO usage_log (source, tokens_in, tokens_out, duration_ms, tool_count)
     VALUES (?, ?, ?, ?, ?)`,
  ).run(source, tokensIn, tokensOut, durationMs, toolCount);
}

export function getToolAudit(opts?: {
  sessionId?: number;
  flaggedOnly?: boolean;
  limit?: number;
}): ToolCall[] {
  const db = getDb();
  const clauses: string[] = [];
  const params: unknown[] = [];

  if (opts?.sessionId) {
    clauses.push('session_id = ?');
    params.push(opts.sessionId);
  }
  if (opts?.flaggedOnly) {
    clauses.push('flagged = 1');
  }

  const where = clauses.length ? `WHERE ${clauses.join(' AND ')}` : '';
  const limit = opts?.limit || 50;
  params.push(limit);

  return db
    .prepare(`SELECT * FROM tool_calls ${where} ORDER BY timestamp DESC LIMIT ?`)
    .all(...params) as ToolCall[];
}

// ---------------------------------------------------------------------------
// Context injection
// ---------------------------------------------------------------------------

export function getContextInjection(nSummaries = 3): string {
  const config = getConfig();
  const userName = config.USER_NAME || 'User';
  const parts: string[] = [];

  // Latest identity snapshot
  const identity = getLatestIdentity();
  if (identity) {
    parts.push(`## Who ${userName} Is (Current Understanding)\n` + identity.content);
  }

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    parts.push(
      '## Active Threads\n' +
        threads.map((t) => `- **${t.name}**: ${t.summary || 'No summary yet'}`).join('\n'),
    );
  }

  // Recent summaries - reversed to show oldest-first (matches Python)
  const summaries = getRecentSummaries(nSummaries);
  if (summaries.length > 0) {
    parts.push(
      '## Recent Sessions\n' +
        summaries
          .reverse()
          .map((s) => `[${s.created_at}] ${s.content}`)
          .join('\n'),
    );
  }

  return parts.join('\n\n');
}

// ---------------------------------------------------------------------------
// Cross-agent queries
// ---------------------------------------------------------------------------

export function getOtherAgentsRecentSummaries(
  nPerAgent = 2,
  maxAgents = 5,
  currentAgent?: string,
): { agent: string; display_name: string; summaries: { content: string; created_at: string; mood: string | null }[] }[] {
  const agentsDir = path.join(USER_DATA, 'agents');
  if (!fs.existsSync(agentsDir)) return [];

  const current = currentAgent || getConfig().AGENT_NAME;
  const results: { agent: string; display_name: string; summaries: { content: string; created_at: string; mood: string | null }[] }[] = [];

  // Collect agents - scan flat entries and recurse one level into org directories
  const allAgents: { name: string; dir: string }[] = [];
  for (const entry of fs.readdirSync(agentsDir)) {
    if (entry === current) continue;
    const entryPath = path.join(agentsDir, entry);
    if (!fs.statSync(entryPath).isDirectory()) continue;
    // Check if this is a direct agent (has data/memory.db) or an org directory
    if (fs.existsSync(path.join(entryPath, 'data', 'memory.db'))) {
      allAgents.push({ name: entry, dir: entryPath });
    } else {
      // Check for nested agents inside org directory
      try {
        for (const sub of fs.readdirSync(entryPath)) {
          const subName = `${entry}/${sub}`;
          if (subName === current) continue;
          const subPath = path.join(entryPath, sub);
          if (fs.statSync(subPath).isDirectory() && fs.existsSync(path.join(subPath, 'data', 'memory.db'))) {
            allAgents.push({ name: subName, dir: subPath });
          }
        }
      } catch { /* non-fatal */ }
    }
  }

  for (const { name: agent, dir: agentDir } of allAgents.slice(0, maxAgents)) {
    const dbPath = path.join(agentDir, 'data', 'memory.db');
    if (!fs.existsSync(dbPath)) continue;

    // Read display_name from agent manifest (check user data then bundle)
    let displayName = agent.charAt(0).toUpperCase() + agent.slice(1);
    const manifestPaths = [
      path.join(agentDir, 'data', 'agent.json'),
      path.join(BUNDLE_ROOT, 'agents', agent, 'data', 'agent.json'),
    ];
    for (const manifestPath of manifestPaths) {
      try {
        if (fs.existsSync(manifestPath)) {
          const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
          if (manifest.display_name) { displayName = manifest.display_name; break; }
        }
      } catch { /* use fallback */ }
    }

    try {
      const db = new Database(dbPath, { readonly: true });
      try {
        const rows = db
          .prepare(
            `SELECT su.content, su.created_at, se.mood
             FROM summaries su
             LEFT JOIN sessions se ON su.session_id = se.id
             ORDER BY su.created_at DESC LIMIT ?`,
          )
          .all(nPerAgent) as { content: string; created_at: string; mood: string | null }[];
        if (rows.length > 0) {
          results.push({ agent, display_name: displayName, summaries: rows });
        }
      } finally {
        db.close();
      }
    } catch {
      continue;
    }
  }

  return results;
}

/**
 * Search another agent's turns and summaries by keyword.
 * Opens the other agent's DB read-only. Does not search observations or identity.
 */
export function searchOtherAgentMemory(
  agentName: string,
  query: string,
  limit = 10,
): CrossAgentSearchResult {
  const dbPath = path.join(USER_DATA, 'agents', agentName, 'data', 'memory.db');
  if (!fs.existsSync(dbPath)) {
    return { agent: agentName, turns: [], summaries: [], error: `Agent '${agentName}' has no memory database.` };
  }

  if (query.length > 500) query = query.slice(0, 500);

  try {
    const db = new Database(dbPath, { readonly: true });
    try {
      const likeQuery = `%${query}%`;

      const turns = db
        .prepare(
          `SELECT id, session_id, role, content, timestamp
           FROM turns WHERE content LIKE ?
           ORDER BY timestamp DESC LIMIT ?`,
        )
        .all(likeQuery, limit) as Pick<Turn, 'id' | 'session_id' | 'role' | 'content' | 'timestamp'>[];

      const summaries = db
        .prepare(
          `SELECT session_id, content, created_at
           FROM summaries WHERE content LIKE ?
           ORDER BY created_at DESC LIMIT ?`,
        )
        .all(likeQuery, limit) as Pick<Summary, 'session_id' | 'content' | 'created_at'>[];

      return { agent: agentName, turns, summaries };
    } finally {
      db.close();
    }
  } catch (err) {
    return {
      agent: agentName,
      turns: [],
      summaries: [],
      error: `Failed to search ${agentName}'s memory: ${err}`,
    };
  }
}

// ---------------------------------------------------------------------------
// Session mood query
// ---------------------------------------------------------------------------

export function getCurrentSessionMood(): string | null {
  const db = getDb();
  const row = db
    .prepare('SELECT mood FROM sessions ORDER BY id DESC LIMIT 1')
    .get() as { mood: string | null } | undefined;
  return row?.mood || null;
}

// ---------------------------------------------------------------------------
// Vector search wrapper - bumps activation on access
// ---------------------------------------------------------------------------

export async function searchMemory(
  query: string,
  n = 5,
): Promise<{ _source_table: string; _score: number; [key: string]: unknown }[]> {
  // Lazy import to avoid circular dependency at module load time
  const { search } = await import('./vector-search');
  const results = await search(query, n);

  // Bump activation for each accessed memory so it doesn't decay without reinforcement
  for (const r of results) {
    const table = r._source_table;
    const rowId = r.id as number | undefined;
    if (table && rowId) {
      updateActivation(table, rowId);
    }
  }

  return results;
}

// ---------------------------------------------------------------------------
// Trust persistence
// ---------------------------------------------------------------------------

export function writeTrustLog(
  domain: string,
  delta: number,
  newValue: number,
  reason = '',
  source = 'unknown',
  dbPath?: string,
): void {
  const p = dbPath || getConfig().DB_PATH;
  const db = connect(p);
  db.prepare(
    'INSERT INTO trust_log (domain, delta, new_value, reason, source) VALUES (?, ?, ?, ?, ?)',
  ).run(domain, delta, newValue, reason, source);
}

export function getLatestTrustValues(dbPath?: string): Record<string, number> {
  const p = dbPath || getConfig().DB_PATH;
  const db = connect(p);
  const rows = db
    .prepare(
      `SELECT domain, new_value FROM trust_log
       WHERE id IN (SELECT MAX(id) FROM trust_log GROUP BY domain)`,
    )
    .all() as { domain: string; new_value: number }[];
  const result: Record<string, number> = {};
  for (const row of rows) {
    result[row.domain] = row.new_value;
  }
  return result;
}

export function getTrustHistory(
  domain?: string,
  limit = 50,
  dbPath?: string,
): TrustLogEntry[] {
  const p = dbPath || getConfig().DB_PATH;
  const db = connect(p);
  if (domain) {
    return db
      .prepare('SELECT * FROM trust_log WHERE domain = ? ORDER BY id DESC LIMIT ?')
      .all(domain, limit) as TrustLogEntry[];
  }
  return db
    .prepare('SELECT * FROM trust_log ORDER BY id DESC LIMIT ?')
    .all(limit) as TrustLogEntry[];
}


// ---------------------------------------------------------------------------
// v2 state persistence
// ---------------------------------------------------------------------------

export function writeStateLog(
  category: string,
  dimension: string,
  delta: number,
  newValue: number,
  reason?: string,
  source?: string,
  dbPath?: string,
): void {
  const p = dbPath || getConfig().DB_PATH;
  const db = connect(p);
  db.prepare(
    'INSERT INTO state_log (category, dimension, delta, new_value, reason, source) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(category, dimension, delta, newValue, reason ?? null, source ?? 'unknown');
}

export function writeNeedEvent(
  need: string,
  delta: number,
  trigger?: string,
  sessionId?: number,
  dbPath?: string,
): void {
  const p = dbPath || getConfig().DB_PATH;
  const db = connect(p);
  db.prepare(
    'INSERT INTO need_events (need, delta, trigger_desc, session_id) VALUES (?, ?, ?, ?)',
  ).run(need, delta, trigger ?? null, sessionId ?? null);
}

export function writePersonalityLog(
  trait: string,
  oldValue: number,
  newValue: number,
  reason?: string,
  source?: string,
  dbPath?: string,
): void {
  const p = dbPath || getConfig().DB_PATH;
  const db = connect(p);
  db.prepare(
    'INSERT INTO personality_log (trait, old_value, new_value, reason, source) VALUES (?, ?, ?, ?, ?)',
  ).run(trait, oldValue, newValue, reason ?? null, source ?? 'evolve');
}

export interface StateLogEntry {
  id: number;
  timestamp: string;
  category: string;
  dimension: string;
  delta: number;
  new_value: number;
  reason: string | null;
  source: string;
}

export function getStateHistory(
  category?: string,
  dimension?: string,
  limit = 50,
  dbPath?: string,
): StateLogEntry[] {
  const p = dbPath || getConfig().DB_PATH;
  const db = connect(p);
  if (category && dimension) {
    return db
      .prepare(
        'SELECT * FROM state_log WHERE category = ? AND dimension = ? ORDER BY id DESC LIMIT ?',
      )
      .all(category, dimension, limit) as StateLogEntry[];
  }
  if (category) {
    return db
      .prepare('SELECT * FROM state_log WHERE category = ? ORDER BY id DESC LIMIT ?')
      .all(category, limit) as StateLogEntry[];
  }
  if (dimension) {
    return db
      .prepare('SELECT * FROM state_log WHERE dimension = ? ORDER BY id DESC LIMIT ?')
      .all(dimension, limit) as StateLogEntry[];
  }
  return db
    .prepare('SELECT * FROM state_log ORDER BY id DESC LIMIT ?')
    .all(limit) as StateLogEntry[];
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

/**
 * Close a specific DB connection by path.
 * Used during agent switches to release the outgoing agent's FD.
 */
export function closeForPath(dbPath: string): void {
  const db = _connections.get(dbPath);
  if (db) {
    try { db.close(); } catch { /* noop */ }
    _connections.delete(dbPath);
  }
}

export function closeAll(): void {
  for (const [, db] of _connections) {
    try {
      db.close();
    } catch { /* noop */ }
  }
  _connections.clear();
}

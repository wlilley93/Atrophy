/**
 * SQLite memory layer - three-layer architecture: Episodic -> Semantic -> Identity.
 * Port of core/memory.py.
 */

import Database from 'better-sqlite3';
import * as fs from 'fs';
import * as path from 'path';
import { getConfig, USER_DATA } from './config';

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

// ---------------------------------------------------------------------------
// Embedding helpers
// ---------------------------------------------------------------------------

export function vectorToBlob(vec: Float32Array): Buffer {
  return Buffer.from(vec.buffer, vec.byteOffset, vec.byteLength);
}

export function blobToVector(blob: Buffer): Float32Array {
  return new Float32Array(blob.buffer, blob.byteOffset, blob.length / 4);
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
  migrate(db);
  const config = getConfig();
  const schema = fs.readFileSync(config.SCHEMA_PATH, 'utf-8');
  db.exec(schema);
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

  if (tableNames.has('coherence_checks')) {
    safeAddColumn('coherence_checks', 'action', "TEXT DEFAULT 'none'");
  }

  if (tableNames.has('entities')) {
    safeAddColumn('entities', 'embedding', 'BLOB');
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
): number {
  const db = getDb();
  const result = db
    .prepare(
      `INSERT INTO turns (session_id, role, content, topic_tags, weight, channel)
       VALUES (?, ?, ?, ?, ?, ?)`,
    )
    .run(sessionId, role, content, topicTags || null, weight, channel);
  return Number(result.lastInsertRowid);
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
): number {
  const db = getDb();
  const result = db
    .prepare('INSERT INTO summaries (session_id, content, topics) VALUES (?, ?, ?)')
    .run(sessionId, content, topics || null);
  return Number(result.lastInsertRowid);
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
  return Number(result.lastInsertRowid);
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
  const result = db
    .prepare(
      `UPDATE observations
       SET content = '[stale] ' || content
       WHERE activation < 0.1
         AND last_accessed < datetime('now', ? || ' days')
         AND content NOT LIKE '[stale]%'`,
    )
    .run(`-${olderThanDays}`);
  return result.changes;
}

// ---------------------------------------------------------------------------
// Activation & decay
// ---------------------------------------------------------------------------

export function updateActivation(table: string, rowId: number): void {
  const allowed = ['observations', 'summaries', 'turns', 'bookmarks', 'entities'];
  if (!allowed.includes(table)) return;

  const db = getDb();
  if (table === 'observations') {
    db.prepare(
      `UPDATE observations
       SET activation = MIN(1.0, activation + 0.2),
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
      const elapsed = (now - new Date(refTime).getTime()) / (1000 * 60 * 60 * 24);
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
  return Number(result.lastInsertRowid);
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

const ENTITY_NAME_RE = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b/g;
const PROPER_NOUN_RE = /(?<=[a-z]\s)([A-Z][a-z]{2,})\b/g;
const QUOTED_RE = /"([^"]{2,30})"/g;

export function extractEntities(text: string): string[] {
  const found = new Set<string>();
  for (const re of [ENTITY_NAME_RE, PROPER_NOUN_RE, QUOTED_RE]) {
    let m: RegExpExecArray | null;
    re.lastIndex = 0;
    while ((m = re.exec(text)) !== null) {
      found.add(m[1] || m[0]);
    }
  }
  return [...found];
}

function guessEntityType(name: string): string {
  const lower = name.toLowerCase();
  if (/\b(he|she|they|mr|ms|dr)\b/.test(lower)) return 'person';
  if (/\b(project|app|tool|system)\b/.test(lower)) return 'project';
  if (/\b(city|country|place|street)\b/.test(lower)) return 'place';
  return 'concept';
}

export function upsertEntity(name: string, entityType?: string): number {
  const db = getDb();
  const existing = db
    .prepare('SELECT id, mention_count FROM entities WHERE name = ?')
    .get(name) as { id: number; mention_count: number } | undefined;

  if (existing) {
    db.prepare(
      `UPDATE entities SET mention_count = mention_count + 1, last_seen = CURRENT_TIMESTAMP WHERE id = ?`,
    ).run(existing.id);
    return existing.id;
  }

  const result = db
    .prepare('INSERT INTO entities (name, entity_type) VALUES (?, ?)')
    .run(name, entityType || guessEntityType(name));
  return Number(result.lastInsertRowid);
}

export function linkEntities(
  entityA: number,
  entityB: number,
  relation: string,
): void {
  const db = getDb();
  const existing = db
    .prepare(
      'SELECT id, strength FROM entity_relations WHERE entity_a = ? AND entity_b = ? AND relation = ?',
    )
    .get(entityA, entityB, relation) as { id: number; strength: number } | undefined;

  if (existing) {
    db.prepare(
      `UPDATE entity_relations
       SET strength = MIN(1.0, strength + 0.1), last_seen = CURRENT_TIMESTAMP
       WHERE id = ?`,
    ).run(existing.id);
  } else {
    db.prepare(
      'INSERT INTO entity_relations (entity_a, entity_b, relation) VALUES (?, ?, ?)',
    ).run(entityA, entityB, relation);
  }
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
  const parts: string[] = [];

  // Latest identity snapshot
  const identity = getLatestIdentity();
  if (identity) {
    parts.push('## Identity\n' + identity.content);
  }

  // Active threads
  const threads = getActiveThreads();
  if (threads.length > 0) {
    parts.push(
      '## Active Threads\n' +
        threads.map((t) => `- **${t.name}**: ${t.summary || '(no summary)'}`).join('\n'),
    );
  }

  // Recent summaries
  const summaries = getRecentSummaries(nSummaries);
  if (summaries.length > 0) {
    parts.push(
      '## Recent Sessions\n' +
        summaries
          .map((s) => `[${s.created_at}] ${s.content}`)
          .join('\n\n'),
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
): { agent: string; summaries: { content: string; created_at: string }[] }[] {
  const agentsDir = path.join(USER_DATA, 'agents');
  if (!fs.existsSync(agentsDir)) return [];

  const current = currentAgent || getConfig().AGENT_NAME;
  const results: { agent: string; summaries: { content: string; created_at: string }[] }[] = [];

  const agents = fs.readdirSync(agentsDir).filter((n) => n !== current);
  for (const agent of agents.slice(0, maxAgents)) {
    const dbPath = path.join(agentsDir, agent, 'data', 'memory.db');
    if (!fs.existsSync(dbPath)) continue;

    try {
      const db = connect(dbPath);
      const rows = db
        .prepare('SELECT content, created_at FROM summaries ORDER BY created_at DESC LIMIT ?')
        .all(nPerAgent) as { content: string; created_at: string }[];
      if (rows.length > 0) {
        results.push({ agent, summaries: rows });
      }
    } catch {
      continue;
    }
  }

  return results;
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

export function closeAll(): void {
  for (const [, db] of _connections) {
    try {
      db.close();
    } catch { /* noop */ }
  }
  _connections.clear();
}

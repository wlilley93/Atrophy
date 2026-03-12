/**
 * Memory browsing, searching, and auditing utilities.
 * Port of scripts/review_memory.py.
 *
 * Exports functions callable via IPC or the HTTP API - no CLI output,
 * just structured data.
 */

import { getDb, type Session, type Turn, type Summary, type Thread, type Observation, type Entity } from './memory';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MemoryType = 'turns' | 'observations' | 'summaries' | 'entities';

export interface BrowseFilters {
  /** Limit results (default 50) */
  limit?: number;
  /** Offset for pagination (default 0) */
  offset?: number;
}

export interface SearchFilters {
  /** Free-text content search (SQL LIKE %q%) */
  q?: string;
  /** ISO date string - inclusive lower bound */
  dateFrom?: string;
  /** ISO date string - inclusive upper bound */
  dateTo?: string;
  /** Filter turns by agent name (requires cross-agent search context) */
  agent?: string;
  /** Filter turns by role */
  role?: 'will' | 'agent';
  /** Filter turns by channel */
  channel?: string;
  /** Limit results (default 50) */
  limit?: number;
  /** Offset for pagination (default 0) */
  offset?: number;
}

export interface SessionBrowseResult {
  id: number;
  started_at: string;
  ended_at: string | null;
  summary: string | null;
  notable: boolean;
  cli_session_id: string | null;
}

export interface ObservationBrowseResult {
  id: number;
  created_at: string;
  content: string;
  incorporated: boolean;
  confidence: number;
  activation: number;
  last_accessed: string | null;
}

export interface AuditStats {
  sessions: { total: number; notable: number; with_summary: number };
  turns: { total: number; by_role: { will: number; agent: number }; with_embedding: number };
  summaries: { total: number; with_embedding: number };
  observations: {
    total: number;
    incorporated: number;
    pending: number;
    stale: number;
    with_embedding: number;
    avg_confidence: number;
    avg_activation: number;
  };
  entities: { total: number; with_embedding: number; by_type: Record<string, number> };
  threads: { total: number; active: number; dormant: number; resolved: number };
  bookmarks: { total: number };
  tool_calls: { total: number; flagged: number };
}

export interface ContextPreview {
  identity: string | null;
  active_threads: { name: string; summary: string | null }[];
  recent_summaries: { session_id: number; content: string; created_at: string }[];
}

// ---------------------------------------------------------------------------
// Browse - paginated listing by memory type
// ---------------------------------------------------------------------------

export function browseSessions(filters?: BrowseFilters): SessionBrowseResult[] {
  const db = getDb();
  const limit = filters?.limit ?? 50;
  const offset = filters?.offset ?? 0;
  return db
    .prepare(
      `SELECT id, started_at, ended_at, summary, notable, cli_session_id
       FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?`,
    )
    .all(limit, offset) as SessionBrowseResult[];
}

export function browseTurns(sessionId?: number, filters?: BrowseFilters): Turn[] {
  const db = getDb();
  const limit = filters?.limit ?? 50;
  const offset = filters?.offset ?? 0;

  if (sessionId !== undefined) {
    return db
      .prepare('SELECT * FROM turns WHERE session_id = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?')
      .all(sessionId, limit, offset) as Turn[];
  }
  return db
    .prepare('SELECT * FROM turns ORDER BY timestamp DESC LIMIT ? OFFSET ?')
    .all(limit, offset) as Turn[];
}

export function browseObservations(filters?: BrowseFilters): ObservationBrowseResult[] {
  const db = getDb();
  const limit = filters?.limit ?? 50;
  const offset = filters?.offset ?? 0;
  return db
    .prepare(
      `SELECT id, created_at, content, incorporated, confidence, activation, last_accessed
       FROM observations ORDER BY created_at DESC LIMIT ? OFFSET ?`,
    )
    .all(limit, offset) as ObservationBrowseResult[];
}

export function browseSummaries(filters?: BrowseFilters): Summary[] {
  const db = getDb();
  const limit = filters?.limit ?? 50;
  const offset = filters?.offset ?? 0;
  return db
    .prepare('SELECT * FROM summaries ORDER BY created_at DESC LIMIT ? OFFSET ?')
    .all(limit, offset) as Summary[];
}

export function browseEntities(filters?: BrowseFilters): Entity[] {
  const db = getDb();
  const limit = filters?.limit ?? 50;
  const offset = filters?.offset ?? 0;
  return db
    .prepare('SELECT * FROM entities ORDER BY mention_count DESC LIMIT ? OFFSET ?')
    .all(limit, offset) as Entity[];
}

export function browseThreads(status?: 'active' | 'dormant' | 'resolved'): Thread[] {
  const db = getDb();
  if (status) {
    return db
      .prepare('SELECT * FROM threads WHERE status = ? ORDER BY last_updated DESC')
      .all(status) as Thread[];
  }
  return db
    .prepare('SELECT * FROM threads ORDER BY last_updated DESC')
    .all() as Thread[];
}

// ---------------------------------------------------------------------------
// Search - filtered queries across memory tables
// ---------------------------------------------------------------------------

export function searchTurns(filters: SearchFilters): Turn[] {
  const db = getDb();
  const clauses: string[] = [];
  const params: unknown[] = [];

  if (filters.q) {
    clauses.push('t.content LIKE ?');
    params.push(`%${filters.q}%`);
  }
  if (filters.role) {
    clauses.push('t.role = ?');
    params.push(filters.role);
  }
  if (filters.channel) {
    clauses.push('t.channel = ?');
    params.push(filters.channel);
  }
  if (filters.dateFrom) {
    clauses.push('t.timestamp >= ?');
    params.push(filters.dateFrom);
  }
  if (filters.dateTo) {
    clauses.push('t.timestamp <= ?');
    params.push(filters.dateTo);
  }

  const where = clauses.length > 0 ? `WHERE ${clauses.join(' AND ')}` : '';
  const limit = filters.limit ?? 50;
  const offset = filters.offset ?? 0;
  params.push(limit, offset);

  return db
    .prepare(`SELECT t.* FROM turns t ${where} ORDER BY t.timestamp DESC LIMIT ? OFFSET ?`)
    .all(...params) as Turn[];
}

export function searchObservations(filters: SearchFilters): ObservationBrowseResult[] {
  const db = getDb();
  const clauses: string[] = [];
  const params: unknown[] = [];

  if (filters.q) {
    clauses.push('content LIKE ?');
    params.push(`%${filters.q}%`);
  }
  if (filters.dateFrom) {
    clauses.push('created_at >= ?');
    params.push(filters.dateFrom);
  }
  if (filters.dateTo) {
    clauses.push('created_at <= ?');
    params.push(filters.dateTo);
  }

  const where = clauses.length > 0 ? `WHERE ${clauses.join(' AND ')}` : '';
  const limit = filters.limit ?? 50;
  const offset = filters.offset ?? 0;
  params.push(limit, offset);

  return db
    .prepare(
      `SELECT id, created_at, content, incorporated, confidence, activation, last_accessed
       FROM observations ${where} ORDER BY created_at DESC LIMIT ? OFFSET ?`,
    )
    .all(...params) as ObservationBrowseResult[];
}

export function searchSummaries(filters: SearchFilters): Summary[] {
  const db = getDb();
  const clauses: string[] = [];
  const params: unknown[] = [];

  if (filters.q) {
    clauses.push('content LIKE ?');
    params.push(`%${filters.q}%`);
  }
  if (filters.dateFrom) {
    clauses.push('created_at >= ?');
    params.push(filters.dateFrom);
  }
  if (filters.dateTo) {
    clauses.push('created_at <= ?');
    params.push(filters.dateTo);
  }

  const where = clauses.length > 0 ? `WHERE ${clauses.join(' AND ')}` : '';
  const limit = filters.limit ?? 50;
  const offset = filters.offset ?? 0;
  params.push(limit, offset);

  return db
    .prepare(`SELECT * FROM summaries ${where} ORDER BY created_at DESC LIMIT ? OFFSET ?`)
    .all(...params) as Summary[];
}

export function searchEntities(filters: SearchFilters): Entity[] {
  const db = getDb();
  const clauses: string[] = [];
  const params: unknown[] = [];

  if (filters.q) {
    clauses.push('name LIKE ?');
    params.push(`%${filters.q}%`);
  }

  const where = clauses.length > 0 ? `WHERE ${clauses.join(' AND ')}` : '';
  const limit = filters.limit ?? 50;
  const offset = filters.offset ?? 0;
  params.push(limit, offset);

  return db
    .prepare(`SELECT * FROM entities ${where} ORDER BY mention_count DESC LIMIT ? OFFSET ?`)
    .all(...params) as Entity[];
}

// ---------------------------------------------------------------------------
// Audit - database health and coverage stats
// ---------------------------------------------------------------------------

export function getAuditStats(): AuditStats {
  const db = getDb();

  // Helper to safely query a count - returns 0 if the table does not exist
  const count = (sql: string, ...params: unknown[]): number => {
    try {
      const row = db.prepare(sql).get(...params) as { n: number } | undefined;
      return row?.n ?? 0;
    } catch {
      return 0;
    }
  };

  // Sessions
  const sessionsTotal = count('SELECT COUNT(*) as n FROM sessions');
  const sessionsNotable = count('SELECT COUNT(*) as n FROM sessions WHERE notable = 1');
  const sessionsWithSummary = count('SELECT COUNT(*) as n FROM sessions WHERE summary IS NOT NULL');

  // Turns
  const turnsTotal = count('SELECT COUNT(*) as n FROM turns');
  const turnsWill = count("SELECT COUNT(*) as n FROM turns WHERE role = 'will'");
  const turnsAgent = count("SELECT COUNT(*) as n FROM turns WHERE role = 'agent'");
  const turnsWithEmbed = count('SELECT COUNT(*) as n FROM turns WHERE embedding IS NOT NULL');

  // Summaries
  const summariesTotal = count('SELECT COUNT(*) as n FROM summaries');
  const summariesWithEmbed = count('SELECT COUNT(*) as n FROM summaries WHERE embedding IS NOT NULL');

  // Observations
  const obsTotal = count('SELECT COUNT(*) as n FROM observations');
  const obsIncorporated = count('SELECT COUNT(*) as n FROM observations WHERE incorporated = 1');
  const obsPending = count('SELECT COUNT(*) as n FROM observations WHERE incorporated = 0');
  const obsStale = count("SELECT COUNT(*) as n FROM observations WHERE content LIKE '[stale]%'");
  const obsWithEmbed = count('SELECT COUNT(*) as n FROM observations WHERE embedding IS NOT NULL');

  let obsAvgConfidence = 0;
  let obsAvgActivation = 0;
  try {
    const avgRow = db
      .prepare('SELECT AVG(confidence) as avg_conf, AVG(activation) as avg_act FROM observations')
      .get() as { avg_conf: number | null; avg_act: number | null } | undefined;
    obsAvgConfidence = avgRow?.avg_conf ?? 0;
    obsAvgActivation = avgRow?.avg_act ?? 0;
  } catch {
    // table may not exist
  }

  // Entities
  const entitiesTotal = count('SELECT COUNT(*) as n FROM entities');
  const entitiesWithEmbed = count('SELECT COUNT(*) as n FROM entities WHERE embedding IS NOT NULL');

  const entityTypes: Record<string, number> = {};
  try {
    const typeRows = db
      .prepare('SELECT entity_type, COUNT(*) as n FROM entities GROUP BY entity_type')
      .all() as { entity_type: string; n: number }[];
    for (const row of typeRows) {
      entityTypes[row.entity_type] = row.n;
    }
  } catch {
    // table may not exist
  }

  // Threads
  const threadsTotal = count('SELECT COUNT(*) as n FROM threads');
  const threadsActive = count("SELECT COUNT(*) as n FROM threads WHERE status = 'active'");
  const threadsDormant = count("SELECT COUNT(*) as n FROM threads WHERE status = 'dormant'");
  const threadsResolved = count("SELECT COUNT(*) as n FROM threads WHERE status = 'resolved'");

  // Bookmarks
  const bookmarksTotal = count('SELECT COUNT(*) as n FROM bookmarks');

  // Tool calls
  const toolCallsTotal = count('SELECT COUNT(*) as n FROM tool_calls');
  const toolCallsFlagged = count('SELECT COUNT(*) as n FROM tool_calls WHERE flagged = 1');

  return {
    sessions: { total: sessionsTotal, notable: sessionsNotable, with_summary: sessionsWithSummary },
    turns: {
      total: turnsTotal,
      by_role: { will: turnsWill, agent: turnsAgent },
      with_embedding: turnsWithEmbed,
    },
    summaries: { total: summariesTotal, with_embedding: summariesWithEmbed },
    observations: {
      total: obsTotal,
      incorporated: obsIncorporated,
      pending: obsPending,
      stale: obsStale,
      with_embedding: obsWithEmbed,
      avg_confidence: Math.round(obsAvgConfidence * 1000) / 1000,
      avg_activation: Math.round(obsAvgActivation * 1000) / 1000,
    },
    entities: { total: entitiesTotal, with_embedding: entitiesWithEmbed, by_type: entityTypes },
    threads: {
      total: threadsTotal,
      active: threadsActive,
      dormant: threadsDormant,
      resolved: threadsResolved,
    },
    bookmarks: { total: bookmarksTotal },
    tool_calls: { total: toolCallsTotal, flagged: toolCallsFlagged },
  };
}

// ---------------------------------------------------------------------------
// Context preview - mirrors the Python review_memory.py output
// ---------------------------------------------------------------------------

export function getContextPreview(): ContextPreview {
  const db = getDb();

  // Latest identity snapshot
  let identity: string | null = null;
  try {
    const row = db
      .prepare('SELECT content FROM identity_snapshots ORDER BY created_at DESC LIMIT 1')
      .get() as { content: string } | undefined;
    identity = row?.content ?? null;
  } catch {
    // table may not exist
  }

  // Active threads
  let activeThreads: { name: string; summary: string | null }[] = [];
  try {
    activeThreads = db
      .prepare("SELECT name, summary FROM threads WHERE status = 'active' ORDER BY last_updated DESC")
      .all() as { name: string; summary: string | null }[];
  } catch {
    // table may not exist
  }

  // Recent summaries
  let recentSummaries: { session_id: number; content: string; created_at: string }[] = [];
  try {
    recentSummaries = db
      .prepare('SELECT session_id, content, created_at FROM summaries ORDER BY created_at DESC LIMIT 5')
      .all() as { session_id: number; content: string; created_at: string }[];
  } catch {
    // table may not exist
  }

  return {
    identity,
    active_threads: activeThreads,
    recent_summaries: recentSummaries,
  };
}

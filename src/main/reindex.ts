/**
 * Regenerate embeddings for memory rows that lack them.
 * Port of scripts/reindex.py + core/vector_search.reindex().
 *
 * Walks turns, summaries, observations, bookmarks, and entities -
 * embeds any row where the embedding column is NULL.
 * Callable from IPC as a long-running background operation.
 */

import { getConfig } from './config';
import { getDb, initDb } from './memory';
import { embed, vectorToBlob } from './embeddings';
import { createLogger } from './logger';

const log = createLogger('reindex');

// ---------------------------------------------------------------------------
// Searchable table definitions - mirrors vector_search.py SEARCHABLE_TABLES
// ---------------------------------------------------------------------------

export const SEARCHABLE_TABLES: Record<string, string> = {
  observations: 'content',
  summaries: 'content',
  turns: 'content',
  bookmarks: 'moment',
  entities: 'name',
};

// ---------------------------------------------------------------------------
// Progress reporting
// ---------------------------------------------------------------------------

export interface ReindexProgress {
  table: string;
  total: number;
  completed: number;
  done: boolean;
}

export type ProgressCallback = (progress: ReindexProgress) => void;

// ---------------------------------------------------------------------------
// Core reindex logic
// ---------------------------------------------------------------------------

async function reindexTable(
  table: string,
  contentColumn: string,
  onProgress?: ProgressCallback,
): Promise<number> {
  const db = getDb();

  // Only rows missing an embedding
  const rows = db
    .prepare(
      `SELECT id, ${contentColumn} FROM ${table} WHERE ${contentColumn} IS NOT NULL AND embedding IS NULL`,
    )
    .all() as { id: number; [key: string]: unknown }[];

  if (rows.length === 0) {
    log.info(`${table}: no rows need embedding`);
    if (onProgress) {
      onProgress({ table, total: 0, completed: 0, done: true });
    }
    return 0;
  }

  log.info(`${table}: embedding ${rows.length} rows...`);

  const updateStmt = db.prepare(`UPDATE ${table} SET embedding = ? WHERE id = ?`);
  let embedded = 0;

  // Process one at a time to avoid memory pressure with large batches.
  // The embed() call is async (WASM pipeline) so we await each one.
  for (const row of rows) {
    const text = row[contentColumn] as string;
    if (!text) continue;

    try {
      const vec = await embed(text);
      const blob = vectorToBlob(vec);
      updateStmt.run(blob, row.id);
      embedded++;
    } catch (err) {
      log.error(`Failed to embed ${table}:${row.id}: ${err}`);
    }

    if (onProgress) {
      onProgress({ table, total: rows.length, completed: embedded, done: false });
    }
  }

  if (onProgress) {
    onProgress({ table, total: rows.length, completed: embedded, done: true });
  }

  log.info(`${table}: done (${embedded} rows embedded)`);
  return embedded;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface ReindexResult {
  tables: Record<string, number>;
  totalEmbedded: number;
  elapsedMs: number;
}

/**
 * Reindex embeddings for all (or specific) searchable tables.
 *
 * Only processes rows where the embedding column is NULL - safe to
 * run multiple times. For a full re-embed (overwriting existing),
 * null out the embedding column first.
 *
 * @param tables - specific table names to reindex, or undefined for all
 * @param onProgress - optional callback fired after each row
 * @returns summary of what was embedded
 */
export async function reindexEmbeddings(
  tables?: string[],
  onProgress?: ProgressCallback,
): Promise<ReindexResult> {
  // Ensure schema is up to date
  initDb();

  const tablesToIndex = tables ?? Object.keys(SEARCHABLE_TABLES);

  // Validate table names
  const unknown = tablesToIndex.filter((t) => !(t in SEARCHABLE_TABLES));
  if (unknown.length > 0) {
    throw new Error(
      `Unknown tables: ${unknown.join(', ')}. Available: ${Object.keys(SEARCHABLE_TABLES).join(', ')}`,
    );
  }

  log.info(`Starting reindex for: ${tablesToIndex.join(', ')}`);
  const t0 = Date.now();

  const result: Record<string, number> = {};
  let totalEmbedded = 0;

  for (const table of tablesToIndex) {
    const contentCol = SEARCHABLE_TABLES[table];
    const count = await reindexTable(table, contentCol, onProgress);
    result[table] = count;
    totalEmbedded += count;
  }

  const elapsedMs = Date.now() - t0;
  log.info(`Complete - ${totalEmbedded} rows in ${(elapsedMs / 1000).toFixed(1)}s`);

  return {
    tables: result,
    totalEmbedded,
    elapsedMs,
  };
}

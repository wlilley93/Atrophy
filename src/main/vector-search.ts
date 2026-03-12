/**
 * Hybrid vector + keyword search over companion memory.
 * Port of core/vector_search.py.
 *
 * Combines cosine similarity (semantic) with BM25 (keyword) for retrieval.
 * Final score: vector_weight * cosine + text_weight * bm25
 * Default weights: 0.7 vector, 0.3 text (semantic-heavy).
 */

import Database from 'better-sqlite3';
import { getConfig } from './config';
import { embed, cosineSimilarity, blobToVector, vectorToBlob, EMBEDDING_DIM, embedBatch } from './embeddings';
import { getDb } from './memory';
import { createLogger } from './logger';

const log = createLogger('vector');

// ---------------------------------------------------------------------------
// Searchable tables
// ---------------------------------------------------------------------------

const SEARCHABLE_TABLES: Record<string, string> = {
  observations: 'content',
  summaries: 'content',
  turns: 'content',
  bookmarks: 'moment',
  entities: 'name',
};

const TABLE_COLUMNS: Record<string, string> = {
  observations: 'id, created_at, content, source_turn, incorporated, valid_from, valid_to, learned_at, expired_at, confidence, activation, last_accessed',
  summaries: 'id, created_at, session_id, content, topics',
  turns: 'id, session_id, role, content, timestamp, topic_tags, weight, channel',
  bookmarks: 'id, session_id, created_at, moment, quote',
  entities: 'id, name, entity_type, mention_count, first_seen, last_seen',
};

// ---------------------------------------------------------------------------
// Tokenizer
// ---------------------------------------------------------------------------

function tokenize(text: string): string[] {
  return (text.toLowerCase().match(/\b\w+\b/g) || []);
}

// ---------------------------------------------------------------------------
// BM25
// ---------------------------------------------------------------------------

function bm25Score(
  queryTokens: string[],
  docTokens: string[],
  avgDl: number,
  nDocs: number,
  df: Map<string, number>,
  k1 = 1.5,
  b = 0.75,
): number {
  if (!docTokens.length || !queryTokens.length) return 0;

  const dl = docTokens.length;
  const tf = new Map<string, number>();
  for (const t of docTokens) {
    tf.set(t, (tf.get(t) || 0) + 1);
  }

  let score = 0;
  for (const term of queryTokens) {
    const termTf = tf.get(term);
    if (termTf === undefined) continue;

    const termDf = df.get(term) || 0;
    const idf = Math.log((nDocs - termDf + 0.5) / (termDf + 0.5) + 1.0);
    const tfNorm = (termTf * (k1 + 1)) / (termTf + k1 * (1 - b + b * dl / Math.max(avgDl, 1)));
    score += idf * tfNorm;
  }

  return score;
}

// ---------------------------------------------------------------------------
// Core search functions
// ---------------------------------------------------------------------------

function vectorSearch(
  queryEmbedding: Float32Array,
  table: string,
  n = 20,
  db?: Database.Database,
): [number, number][] {
  const conn = db || getDb();

  let rows: { id: number; embedding: Buffer }[];
  try {
    rows = conn.prepare(
      `SELECT id, embedding FROM ${table} WHERE embedding IS NOT NULL`,
    ).all() as { id: number; embedding: Buffer }[];
  } catch {
    return [];
  }

  const scored: [number, number][] = [];
  for (const row of rows) {
    const vec = blobToVector(row.embedding);
    if (vec.length !== EMBEDDING_DIM) continue;
    const score = cosineSimilarity(queryEmbedding, vec);
    scored.push([row.id, score]);
  }

  scored.sort((a, b) => b[1] - a[1]);
  return scored.slice(0, n);
}

function bm25Search(
  query: string,
  table: string,
  contentColumn: string,
  n = 20,
  db?: Database.Database,
): [number, number][] {
  const conn = db || getDb();

  let rows: { id: number; [key: string]: unknown }[];
  try {
    rows = conn.prepare(
      `SELECT id, ${contentColumn} FROM ${table} WHERE ${contentColumn} IS NOT NULL`,
    ).all() as { id: number; [key: string]: unknown }[];
  } catch {
    return [];
  }

  if (!rows.length) return [];

  const queryTokens = tokenize(query);
  if (!queryTokens.length) return [];

  const docs = rows.map((row) => ({
    id: row.id,
    tokens: tokenize(String(row[contentColumn] || '')),
  }));

  const nDocs = docs.length;
  const avgDl = docs.reduce((sum, d) => sum + d.tokens.length, 0) / Math.max(nDocs, 1);

  const df = new Map<string, number>();
  for (const doc of docs) {
    const unique = new Set(doc.tokens);
    for (const t of unique) {
      df.set(t, (df.get(t) || 0) + 1);
    }
  }

  const scored: [number, number][] = [];
  for (const doc of docs) {
    const score = bm25Score(queryTokens, doc.tokens, avgDl, nDocs, df);
    if (score > 0) scored.push([doc.id, score]);
  }

  scored.sort((a, b) => b[1] - a[1]);
  return scored.slice(0, n);
}

// ---------------------------------------------------------------------------
// Score normalization and merging
// ---------------------------------------------------------------------------

function normalizeScores(results: [number, number][]): [number, number][] {
  if (!results.length) return [];

  const scores = results.map((r) => r[1]);
  const minS = Math.min(...scores);
  const maxS = Math.max(...scores);
  const rangeS = maxS - minS;

  if (rangeS === 0) return results.map(([id]) => [id, 1.0]);
  return results.map(([id, s]) => [id, (s - minS) / rangeS]);
}

function mergeResults(
  vectorResults: [number, number][],
  textResults: [number, number][],
  vectorWeight = 0.7,
): [number, number][] {
  const textWeight = 1.0 - vectorWeight;

  const vecNorm = normalizeScores(vectorResults);
  const txtNorm = normalizeScores(textResults);

  const combined = new Map<number, number>();
  for (const [id, score] of vecNorm) {
    combined.set(id, (combined.get(id) || 0) + vectorWeight * score);
  }
  for (const [id, score] of txtNorm) {
    combined.set(id, (combined.get(id) || 0) + textWeight * score);
  }

  const ranked = [...combined.entries()];
  ranked.sort((a, b) => b[1] - a[1]);
  return ranked;
}

// ---------------------------------------------------------------------------
// Public search API
// ---------------------------------------------------------------------------

export interface SearchResult {
  _source_table: string;
  _score: number;
  [key: string]: unknown;
}

export async function search(
  query: string,
  n = 5,
  vectorWeight?: number,
  tables?: string[],
  db?: Database.Database,
): Promise<SearchResult[]> {
  const config = getConfig();
  if (vectorWeight === undefined) vectorWeight = config.VECTOR_SEARCH_WEIGHT;
  if (!tables) tables = Object.keys(SEARCHABLE_TABLES);

  const queryEmbedding = await embed(query);
  const conn = db || getDb();
  const allResults: SearchResult[] = [];

  for (const table of tables) {
    if (!(table in SEARCHABLE_TABLES)) continue;
    const contentCol = SEARCHABLE_TABLES[table];

    const vecResults = vectorSearch(queryEmbedding, table, n * 3, conn);
    const txtResults = bm25Search(query, table, contentCol, n * 3, conn);
    const merged = mergeResults(vecResults, txtResults, vectorWeight);

    const topMerged = merged.slice(0, n * 2);
    if (topMerged.length) {
      const rowIds = topMerged.map(([id]) => id);
      const scoreById = new Map(topMerged);
      const placeholders = rowIds.map(() => '?').join(',');
      const cols = TABLE_COLUMNS[table] || '*';

      try {
        const rows = conn.prepare(
          `SELECT ${cols} FROM ${table} WHERE id IN (${placeholders})`,
        ).all(...rowIds) as Record<string, unknown>[];

        const rowsById = new Map(rows.map((r) => [r.id as number, r]));
        for (const rowId of rowIds) {
          const row = rowsById.get(rowId);
          if (row) {
            allResults.push({
              ...row,
              _source_table: table,
              _score: scoreById.get(rowId) || 0,
            });
          }
        }
      } catch { /* table schema mismatch */ }
    }
  }

  allResults.sort((a, b) => b._score - a._score);

  // Simple MMR: skip results with >80% token overlap with already-selected
  const selected: SearchResult[] = [];
  const seenContent: Set<string>[] = [];

  for (const result of allResults) {
    const contentCol = SEARCHABLE_TABLES[result._source_table] || 'content';
    const content = String(result[contentCol] || '');
    const contentTokens = new Set(tokenize(content));

    let isDuplicate = false;
    for (const prevTokens of seenContent) {
      if (!contentTokens.size || !prevTokens.size) continue;

      const intersectionSize = [...contentTokens].filter((t) => prevTokens.has(t)).length;
      const unionSize = new Set([...contentTokens, ...prevTokens]).size;
      const overlap = intersectionSize / Math.max(unionSize, 1);

      if (overlap > 0.8) {
        isDuplicate = true;
        break;
      }
    }

    if (!isDuplicate) {
      selected.push(result);
      seenContent.push(contentTokens);
    }
    if (selected.length >= n) break;
  }

  return selected;
}

export async function searchSimilar(
  text: string,
  n = 5,
  tables?: string[],
  db?: Database.Database,
): Promise<SearchResult[]> {
  return search(text, n, 1.0, tables, db);
}

// ---------------------------------------------------------------------------
// Reindex
// ---------------------------------------------------------------------------

export async function reindex(table?: string, db?: Database.Database): Promise<void> {
  const conn = db || getDb();
  const tablesToIndex = table ? [table] : Object.keys(SEARCHABLE_TABLES);

  for (const tbl of tablesToIndex) {
    if (!(tbl in SEARCHABLE_TABLES)) {
      log.warn(`Unknown table: ${tbl}, skipping`);
      continue;
    }

    const contentCol = SEARCHABLE_TABLES[tbl];
    let rows: { id: number; [key: string]: unknown }[];

    try {
      rows = conn.prepare(
        `SELECT id, ${contentCol} FROM ${tbl} WHERE ${contentCol} IS NOT NULL`,
      ).all() as { id: number; [key: string]: unknown }[];
    } catch {
      log.warn(`${tbl}: table not found or error`);
      continue;
    }

    if (!rows.length) {
      log.info(`${tbl}: no rows to embed`);
      continue;
    }

    log.info(`${tbl}: embedding ${rows.length} rows...`);

    const texts = rows.map((r) => String(r[contentCol] || ''));
    const ids = rows.map((r) => r.id);
    const chunkSize = 64;
    let embedded = 0;

    for (let i = 0; i < texts.length; i += chunkSize) {
      const chunkTexts = texts.slice(i, i + chunkSize);
      const chunkIds = ids.slice(i, i + chunkSize);
      const vectors = await embedBatch(chunkTexts);

      const update = conn.prepare(`UPDATE ${tbl} SET embedding = ? WHERE id = ?`);
      for (let j = 0; j < chunkIds.length; j++) {
        update.run(vectorToBlob(vectors[j]), chunkIds[j]);
      }
      embedded += chunkTexts.length;
    }

    log.info(`${tbl}: done (${embedded} rows embedded)`);
  }
}

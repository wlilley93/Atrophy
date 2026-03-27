# src/main/vector-search.ts - Hybrid Vector + Keyword Search

**Dependencies:** `better-sqlite3`, `./config`, `./embeddings`, `./memory`, `./logger`  
**Purpose:** Hybrid search combining cosine similarity (semantic) with BM25 (keyword) for memory retrieval

## Overview

This module implements hybrid search across the agent's memory database. It combines:
- **Vector search:** Cosine similarity on 384-dim embeddings (semantic meaning)
- **Keyword search:** BM25 scoring (exact term matching)

Final score: `vector_weight * cosine + text_weight * bm25`

Default weights: 0.7 vector, 0.3 text (semantic-heavy for natural language queries).

## Searchable Tables

```typescript
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
```

**Purpose:** Define which tables and columns are searchable. Each table has a text column for embedding and keyword search.

## Tokenizer

```typescript
function tokenize(text: string): string[] {
  return (text.toLowerCase().match(/\b\w+\b/g) || []);
}
```

**Purpose:** Simple whitespace + word boundary tokenizer for BM25. Lowercases all tokens.

## BM25 Implementation

```typescript
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
```

**BM25 parameters:**
- `k1 = 1.5`: Term frequency saturation (higher = more weight on repeated terms)
- `b = 0.75`: Length normalization (higher = more penalty for long documents)

**Formula:** `score = Σ(idf * tfNorm)` where:
- `idf = log((nDocs - df + 0.5) / (df + 0.5) + 1)`
- `tfNorm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgDl))`

## Vector Search

```typescript
function vectorSearch(
  queryEmbedding: Float32Array,
  table: string,
  n = 20,
  db?: Database.Database,
): [number, number][] {
  if (!(table in SEARCHABLE_TABLES)) return [];
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
```

**Process:**
1. Load all rows with embeddings from table
2. Deserialize each embedding blob to Float32Array
3. Compute cosine similarity with query embedding
4. Sort by score descending, return top N

**Why load all rows:** SQLite doesn't support efficient vector similarity search without an index. For small datasets (<10k rows), brute force is acceptable. For larger datasets, consider adding HNSW or IVF index.

## BM25 Search

```typescript
function bm25Search(
  query: string,
  table: string,
  contentColumn: string,
  n = 20,
  db?: Database.Database,
): [number, number][] {
  if (!(table in SEARCHABLE_TABLES)) return [];
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
```

**Process:**
1. Load all rows with content from table
2. Tokenize query and all documents
3. Compute document frequency (df) for each term
4. Calculate BM25 score for each document
5. Sort by score descending, return top N

## Score Normalization

```typescript
function normalizeScores(results: [number, number][]): [number, number][] {
  if (!results.length) return [];

  const scores = results.map((r) => r[1]);
  const minS = Math.min(...scores);
  const maxS = Math.max(...scores);
  const rangeS = maxS - minS;

  if (rangeS === 0) return results.map(([id]) => [id, 1.0]);
  return results.map(([id, s]) => [id, (s - minS) / rangeS]);
}
```

**Purpose:** Normalize scores to [0, 1] range for merging. Min-max normalization ensures vector and keyword scores are on comparable scales.

## Score Merging

```typescript
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
```

**Weighting:**
- `vectorWeight = 0.7` (default): Semantic-heavy for natural language
- `textWeight = 0.3`: Keyword matching for exact terms

**Merging:** Scores are weighted and summed. Documents appearing in both results get both contributions.

## Main Search Function

```typescript
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
```

**Search flow:**
1. Embed query using Transformers.js
2. For each table:
   - Run vector search (top n*3)
   - Run BM25 search (top n*3)
   - Merge and normalize scores
   - Take top n*2 merged results
   - Fetch full rows from database
3. Combine results from all tables
4. Apply MMR (Maximal Marginal Relevance) to remove duplicates
5. Return top N diverse results

**Why n*3 then n*2 then n:** Oversampling at each stage ensures we don't miss good results due to normalization artifacts. Final deduplication ensures diversity.

### MMR (Maximal Marginal Relevance)

```typescript
// Simple MMR: skip results with >80% token overlap with already-selected
const selected: SearchResult[] = [];
const seenContent: Set<string>[] = [];

for (const result of allResults) {
  const content = String(result[contentCol] || '');
  const contentTokens = new Set(tokenize(content));

  let isDuplicate = false;
  for (const prevTokens of seenContent) {
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
```

**Purpose:** Remove near-duplicate results. Jaccard similarity > 0.8 is considered duplicate.

**Why MMR:** Without deduplication, search might return 5 nearly identical turns from the same conversation. MMR ensures diversity.

## searchSimilar Function

```typescript
export async function searchSimilar(
  text: string,
  n = 5,
  tables?: string[],
  db?: Database.Database,
): Promise<SearchResult[]> {
  return search(text, n, 1.0, tables, db);
}
```

**Purpose:** Pure vector search (no keyword component). Use when semantic similarity is all that matters.

## Reindex Function

```typescript
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
      const runBatch = conn.transaction((pairs: [Buffer, number][]) => {
        for (const [blob, id] of pairs) update.run(blob, id);
      });
      runBatch(vectors.map((v, j) => [vectorToBlob(v), chunkIds[j]] as [Buffer, number]));
      embedded += chunkTexts.length;
    }

    log.info(`${tbl}: done (${embedded} rows embedded)`);
  }
}
```

**Purpose:** Embed all rows in a table (or all tables). Used for:
- Initial indexing after schema creation
- Reindexing after model change
- Backfilling embeddings for existing data

**Batching:** Processes 64 rows at a time to manage memory. Uses SQLite transaction for batch updates.

## SearchResult Interface

```typescript
export interface SearchResult {
  _source_table: string;
  _score: number;
  [key: string]: unknown;
}
```

**Fields:**
- `_source_table`: Which table the result came from
- `_score`: Combined hybrid score (0-1)
- Other fields: Table-specific columns (id, content, timestamp, etc.)

## Exported API Summary

| Function | Purpose |
|----------|---------|
| `search(query, n, vectorWeight, tables, db)` | Hybrid vector + keyword search |
| `searchSimilar(text, n, tables, db)` | Pure vector search |
| `reindex(table, db)` | Embed all rows in table(s) |

## Configuration

```typescript
// From config.ts
VECTOR_SEARCH_WEIGHT: number;  // default 0.7
```

**Purpose:** Control balance between semantic (vector) and keyword (BM25) search. Higher = more semantic.

## Performance Considerations

1. **Brute force vector search:** O(n) for each query. Acceptable for <10k rows. For larger datasets, add HNSW index.

2. **BM25 precomputation:** Document frequency (df) is computed per-query. For frequently searched tables, consider precomputing inverted index.

3. **Embedding caching:** Query embeddings are NOT cached. Same query = re-embedding. Consider adding query cache for repeated searches.

4. **Batch reindexing:** Uses chunkSize=64 and transactions for efficiency. Adjust based on available memory.

## See Also

- `src/main/embeddings.ts` - Vector embedding engine
- `src/main/memory.ts` - Database layer
- `db/schema.sql` - Table schemas with embedding columns

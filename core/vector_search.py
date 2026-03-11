"""Hybrid vector + keyword search over companion memory.

Combines cosine similarity (semantic) with BM25 (keyword) for retrieval.
Final score: vector_weight * cosine + text_weight * bm25
Default weights: 0.7 vector, 0.3 text (semantic-heavy).
"""
import math
import re
import sqlite3
from collections import Counter

import numpy as np

from config import DB_PATH, VECTOR_SEARCH_WEIGHT
from core.embeddings import (
    embed, embed_batch, cosine_similarity,
    blob_to_vector, vector_to_blob, EMBEDDING_DIM,
)
from core.memory import _connect


# Tables and their content columns for search
SEARCHABLE_TABLES = {
    "observations": "content",
    "summaries": "content",
    "turns": "content",
    "bookmarks": "moment",
    "entities": "name",
}

# Columns to fetch per table (excludes large embedding BLOBs)
_TABLE_COLUMNS = {
    "observations": "id, created_at, content, source_turn, incorporated, valid_from, valid_to, learned_at, expired_at, confidence, activation, last_accessed",
    "summaries": "id, created_at, session_id, content, topics",
    "turns": "id, session_id, role, content, timestamp, topic_tags, weight, channel",
    "bookmarks": "id, session_id, created_at, moment, quote",
    "entities": "id, name, entity_type, mention_count, first_seen, last_seen",
}


# ── Lightweight BM25 ──

def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer. Lowercased."""
    return re.findall(r'\b\w+\b', text.lower())


def _bm25_score(query_tokens: list[str], doc_tokens: list[str],
                avg_dl: float, n_docs: int, df: dict[str, int],
                k1: float = 1.5, b: float = 0.75) -> float:
    """BM25 score for a single document against a query."""
    if not doc_tokens or not query_tokens:
        return 0.0
    dl = len(doc_tokens)
    tf = Counter(doc_tokens)
    score = 0.0
    for term in query_tokens:
        if term not in tf:
            continue
        term_tf = tf[term]
        term_df = df.get(term, 0)
        # IDF with smoothing
        idf = math.log((n_docs - term_df + 0.5) / (term_df + 0.5) + 1.0)
        # TF normalization
        tf_norm = (term_tf * (k1 + 1)) / (term_tf + k1 * (1 - b + b * dl / max(avg_dl, 1)))
        score += idf * tf_norm
    return score


# ── Core search functions ──

def _vector_search(query_embedding: np.ndarray, table: str,
                   n: int = 20, db_path=DB_PATH) -> list[tuple[int, float]]:
    """Cosine similarity against all embeddings in a table.

    Returns (row_id, score) pairs sorted by score descending.
    Only considers rows that have an embedding.
    """
    conn = _connect(db_path)
    rows = conn.execute(
        f"SELECT id, embedding FROM {table} WHERE embedding IS NOT NULL"
    ).fetchall()
    conn.close()

    scored = []
    for row in rows:
        vec = blob_to_vector(row["embedding"])
        if vec.shape[0] != EMBEDDING_DIM:
            continue
        score = cosine_similarity(query_embedding, vec)
        scored.append((row["id"], score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:n]


def _bm25_search(query: str, table: str, content_column: str,
                 n: int = 20, db_path=DB_PATH) -> list[tuple[int, float]]:
    """Simple BM25 search over a table's content column.

    Returns (row_id, score) pairs sorted by score descending.
    """
    conn = _connect(db_path)
    rows = conn.execute(
        f"SELECT id, {content_column} FROM {table} WHERE {content_column} IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    # Pre-tokenize all docs
    docs = [(row["id"], _tokenize(row[content_column] or "")) for row in rows]
    n_docs = len(docs)
    avg_dl = sum(len(d[1]) for d in docs) / max(n_docs, 1)

    # Document frequency
    df: dict[str, int] = Counter()
    for _, tokens in docs:
        unique = set(tokens)
        for t in unique:
            df[t] += 1

    scored = []
    for row_id, tokens in docs:
        score = _bm25_score(query_tokens, tokens, avg_dl, n_docs, df)
        if score > 0:
            scored.append((row_id, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:n]


def _normalize_scores(results: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """Min-max normalize scores to [0, 1]."""
    if not results:
        return []
    scores = [s for _, s in results]
    min_s = min(scores)
    max_s = max(scores)
    range_s = max_s - min_s
    if range_s == 0:
        return [(rid, 1.0) for rid, _ in results]
    return [(rid, (s - min_s) / range_s) for rid, s in results]


def _merge_results(vector_results: list[tuple[int, float]],
                   text_results: list[tuple[int, float]],
                   vector_weight: float = 0.7,
                   mmr_lambda: float = 0.8) -> list[tuple[int, float]]:
    """Combine and re-rank using weighted scores.

    Applies MMR (Maximal Marginal Relevance) to avoid near-duplicate results.
    """
    text_weight = 1.0 - vector_weight

    # Normalize both result sets
    vec_norm = _normalize_scores(vector_results)
    txt_norm = _normalize_scores(text_results)

    # Merge into combined scores
    combined: dict[int, float] = {}
    for rid, score in vec_norm:
        combined[rid] = combined.get(rid, 0) + vector_weight * score
    for rid, score in txt_norm:
        combined[rid] = combined.get(rid, 0) + text_weight * score

    # Sort by combined score
    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    return ranked


def search(query: str, n: int = 5, vector_weight: float = None,
           tables: list[str] = None, db_path=DB_PATH) -> list[dict]:
    """Hybrid search across all embeddable content.

    Returns ranked results with scores, source table, and content.

    Args:
        query: Search query text
        n: Number of results to return
        vector_weight: Balance between semantic (1.0) and keyword (0.0) search.
                       Defaults to config VECTOR_SEARCH_WEIGHT (0.7).
        tables: Specific tables to search. Defaults to all searchable tables.
    """
    if vector_weight is None:
        vector_weight = VECTOR_SEARCH_WEIGHT

    if tables is None:
        tables = list(SEARCHABLE_TABLES.keys())

    # Get query embedding once
    query_embedding = embed(query)

    all_results = []

    for table in tables:
        if table not in SEARCHABLE_TABLES:
            continue
        content_col = SEARCHABLE_TABLES[table]

        # Run both searches
        vec_results = _vector_search(query_embedding, table, n=n * 3, db_path=db_path)
        txt_results = _bm25_search(query, table, content_col, n=n * 3, db_path=db_path)

        # Merge
        merged = _merge_results(vec_results, txt_results, vector_weight)

        # Fetch content for top results in a single batch query
        top_merged = merged[:n * 2]
        if top_merged:
            row_ids = [row_id for row_id, _ in top_merged]
            score_by_id = {row_id: score for row_id, score in top_merged}
            placeholders = ",".join("?" for _ in row_ids)
            cols = _TABLE_COLUMNS.get(table, "*")
            conn = _connect(db_path)
            rows = conn.execute(
                f"SELECT {cols} FROM {table} WHERE id IN ({placeholders})", row_ids
            ).fetchall()
            conn.close()
            rows_by_id = {row["id"]: row for row in rows}
            for row_id in row_ids:
                row = rows_by_id.get(row_id)
                if row:
                    result = dict(row)
                    result["_source_table"] = table
                    result["_score"] = score_by_id[row_id]
                    all_results.append(result)

    # Sort all results across tables by score
    all_results.sort(key=lambda x: x["_score"], reverse=True)

    # Apply simple MMR: skip results too similar to already-selected ones
    selected = []
    seen_content = []
    for result in all_results:
        content = result.get(SEARCHABLE_TABLES.get(result["_source_table"], "content"), "")
        # Simple dedup: skip if >80% token overlap with any selected result
        content_tokens = set(_tokenize(content))
        is_duplicate = False
        for prev_tokens in seen_content:
            if not content_tokens or not prev_tokens:
                continue
            overlap = len(content_tokens & prev_tokens) / max(len(content_tokens | prev_tokens), 1)
            if overlap > 0.8:
                is_duplicate = True
                break
        if not is_duplicate:
            selected.append(result)
            seen_content.append(content_tokens)
        if len(selected) >= n:
            break

    return selected


def search_similar(text: str, n: int = 5, tables: list[str] = None,
                   db_path=DB_PATH) -> list[dict]:
    """Pure vector search - find semantically similar memories.

    No keyword component. Useful for finding connections the companion
    wouldn't find with exact keyword matching.
    """
    return search(text, n=n, vector_weight=1.0, tables=tables, db_path=db_path)


def reindex(table: str = None, db_path=DB_PATH):
    """Regenerate embeddings for all rows (or a specific table).

    Used for initial setup and periodic maintenance.
    """
    tables_to_index = [table] if table else list(SEARCHABLE_TABLES.keys())

    for tbl in tables_to_index:
        if tbl not in SEARCHABLE_TABLES:
            print(f"  [reindex] Unknown table: {tbl}, skipping")
            continue

        content_col = SEARCHABLE_TABLES[tbl]
        conn = _connect(db_path)
        rows = conn.execute(
            f"SELECT id, {content_col} FROM {tbl} WHERE {content_col} IS NOT NULL"
        ).fetchall()
        conn.close()

        if not rows:
            print(f"  [reindex] {tbl}: no rows to embed")
            continue

        print(f"  [reindex] {tbl}: embedding {len(rows)} rows...")

        # Batch embed
        texts = [row[content_col] or "" for row in rows]
        ids = [row["id"] for row in rows]

        # Process in chunks to manage memory
        chunk_size = 64
        conn = _connect(db_path)
        embedded = 0
        for i in range(0, len(texts), chunk_size):
            chunk_texts = texts[i:i + chunk_size]
            chunk_ids = ids[i:i + chunk_size]
            vectors = embed_batch(chunk_texts)

            update_params = [
                (vector_to_blob(vec), row_id)
                for row_id, vec in zip(chunk_ids, vectors)
            ]
            conn.executemany(
                f"UPDATE {tbl} SET embedding = ? WHERE id = ?",
                update_params,
            )
            embedded += len(chunk_texts)

        conn.commit()
        conn.close()
        print(f"  [reindex] {tbl}: done ({embedded} rows embedded)")

# Memory Lifecycle

This specification describes how data flows through the companion's three-layer memory architecture, from raw turn capture through semantic summarisation to identity-level understanding.

---

## Architecture Overview

The memory system is organised into three layers, each with increasing abstraction and decreasing volume:

```
Layer 1: Episodic    turns, bookmarks              (raw, append-only)
Layer 2: Semantic    summaries, threads, entities   (summarised, mutable)
Layer 3: Identity    observations, identity_snapshots (distilled, curated)
```

All layers are stored in a single SQLite database per agent (`~/.atrophy/agents/<name>/data/memory.db`). The database uses WAL journal mode and foreign key constraints.

---

## 1. Turn Write

**Trigger**: Every user or companion message during a session.

**Sequence**:
1. `Session.add_turn()` calls `memory.write_turn()`.
2. A row is inserted into the `turns` table with: session ID, role (`will` or `companion`), content, timestamp, optional topic tags, weight (1-5), and channel (`direct`, `telegram`, etc.).
3. `_embed_async()` is called, which spawns a daemon thread to compute the embedding without blocking the conversation.
4. The background thread loads `all-MiniLM-L6-v2` (384-dimensional), encodes the text, converts the resulting float32 vector to a BLOB, and writes it back to the `embedding` column on the same row.

**Storage**: Turns are append-only. They are never deleted or modified after creation.

---

## 2. Session Summary

**Trigger**: Session end, when the session has 4 or more turns.

**Sequence**:
1. `Session.end()` concatenates all turn content with role labels.
2. The concatenated text is sent to `run_inference_oneshot()` with a summarisation system prompt: "Summarise this conversation in 2-3 sentences. Focus on what mattered, not what was said. Note any new threads, shifts in mood, or observations worth remembering."
3. The summary is stored in the `summaries` table with session ID, content, and optional topic tags.
4. An async embedding is computed and stored on the summary row.
5. The session row is updated with the summary text, mood, and `ended_at` timestamp.

**Inference**: Uses `claude-sonnet-4-6` at `low` effort. No MCP tools. 30-second timeout.

---

## 3. Thread Management

**Trigger**: Companion calls `track_thread` MCP tool during conversation or memory flush.

**Operations**:
- **Create**: Insert into `threads` table with name, summary, status (`active`), and timestamp.
- **Update**: Modify summary and/or status. Timestamp refreshed on every update.
- **Status transitions**: `active` -> `dormant` -> `resolved`. The companion controls these transitions based on conversational context.

**Injection**: Active threads are surfaced in the agency context at the start of each turn (up to 5 thread names). The `daily_digest` tool returns full thread summaries.

**Thread mentions**: The `thread_mentions` join table links turns to threads, though this is not currently populated automatically -- it is available for future use.

---

## 4. Observation Extraction

**Trigger**: The observer daemon runs periodically (typically every 15 minutes during active hours) via launchd.

**Sequence**:
1. The daemon reads recent turns from the current day.
2. Turns are sent to `run_inference_oneshot()` with a prompt instructing extraction of factual observations about the user -- patterns, tendencies, preferences, and insights.
3. Each extracted observation is stored in the `observations` table with:
   - `content`: The observation text.
   - `source_turn`: Reference to the originating turn (when available).
   - `confidence`: Initial confidence score (default 0.5).
   - `valid_from`: When the observation became true (bi-temporal).
   - `valid_to`: When the observation stopped being true (NULL if still current).
   - `learned_at`: When the system learned this fact.
   - `activation`: Usage frequency tracker (default 1.0).
   - `embedding`: Async-computed vector for semantic search.

**Manual observations**: The companion can also record observations directly via the `observe` MCP tool during conversation, typically when it notices something significant.

**Review and retirement**: The companion can review observations via `review_observations` and retire outdated ones via `retire_observation`. Retired observations are deleted from the database.

---

## 5. Identity Snapshots

**Trigger**: Significant events detected by the introspection daemon, or deliberate companion reflection.

**Sequence**:
1. The introspect daemon gathers recent observations, thread summaries, and conversation patterns.
2. A full-context reflection is sent to inference, asking the model to synthesise a current understanding of the user.
3. The result is stored in `identity_snapshots` with a trigger description (what prompted the snapshot).

**Injection**: The most recent identity snapshot is included in the memory context at session start, under the heading "Who Will Is (Current Understanding)".

---

## 6. Recall

**Trigger**: Companion calls `remember` or `search_similar` MCP tool.

### Hybrid Search (remember)

The `remember` tool uses hybrid retrieval combining vector similarity and keyword matching:

1. **Query embedding**: The search query is encoded using the same `all-MiniLM-L6-v2` model.
2. **Vector search**: Cosine similarity computed against all embedded rows in each searchable table (observations, summaries, turns, bookmarks, entities). Top candidates retrieved.
3. **BM25 search**: Standard BM25 keyword scoring with IDF weighting and TF normalisation. Same tables searched.
4. **Score fusion**: Results from both methods are min-max normalised to [0, 1], then combined with configurable weights (default: 0.7 vector + 0.3 BM25).
5. **MMR deduplication**: Results with >80% token overlap with already-selected results are filtered out.
6. **Activation bump**: Retrieved observations have their `activation` score increased by 0.2 (capped at 1.0) and `last_accessed` updated.

### Pure Vector Search (search_similar)

The `search_similar` tool runs the same pipeline with `vector_weight=1.0`, finding conceptual connections even when keywords differ.

### Fallback

If vector search fails (e.g., embedding model not loaded), the `remember` tool falls back to pure SQL `LIKE` queries across turns, summaries, observations, and threads.

### Searchable Tables

| Table | Content Column | What It Contains |
|---|---|---|
| `observations` | `content` | Facts and patterns about the user |
| `summaries` | `content` | Session summaries |
| `turns` | `content` | Raw conversation turns |
| `bookmarks` | `moment` | Significant moment descriptions |
| `entities` | `name` | Named entities (people, concepts, places) |

---

## 7. Decay and Forgetting

### Activation Decay

The sleep cycle daemon applies exponential decay to observation activation scores:

```
activation *= 2^(-days_since_access / half_life)
```

Default half-life: 30 days. Observations accessed recently stay active; old unreferenced ones fade toward zero. Observations with activation below 0.01 are set to 0.0.

### Staleness Marking

Observations older than 30 days that were never incorporated (reviewed and confirmed by the companion) are prefixed with `[stale]`. Stale observations still exist in the database but are deprioritised in retrieval.

### Bi-temporal Fields

Observations carry two time axes:
- **Transaction time**: `learned_at` (when the system recorded it) and `expired_at` (when it was retired).
- **Valid time**: `valid_from` (when the fact became true) and `valid_to` (when it stopped being true).

This allows the system to distinguish between "when did we learn this" and "when was this actually true", supporting retrospective correction.

### Emotional Decay

The emotional state decays toward baselines between sessions via exponential decay with per-emotion half-lives (4-8 hours). Trust decays more slowly (8-hour half-life). This prevents emotional state from persisting indefinitely without reinforcement.

---

## 8. Entity Graph

### Entity Extraction

`memory.extract_entities()` uses regex-based pattern matching (not ML) to identify:
- **Multi-word proper nouns**: Consecutive capitalised words (e.g., "John Smith", "The Atrophied Mind").
- **Mid-sentence proper nouns**: Single capitalised words following lowercase text.
- **Quoted terms**: Terms in double quotes, treated as significant concepts.

Entity types are heuristically classified: `person` (title prefixes), `project` (keyword matching), `place` (location keywords), or `concept` (default).

### Entity Storage

Entities are stored in the `entities` table with:
- `name`: Unique, case-insensitive matching.
- `entity_type`: Classification.
- `mention_count`: Incremented on each re-extraction.
- `first_seen` / `last_seen`: Temporal bounds.
- `embedding`: Vector for semantic search.

### Entity Relations

The `entity_relations` table stores directed relationships between entities:
- `entity_a`, `entity_b`: Foreign keys to `entities`.
- `relation`: Relationship type (e.g., `related_to`, `discussed_with`, `part_of`).
- `strength`: Float in [0, 1], increased by 0.1 on each re-observation (capped at 1.0).
- `first_seen` / `last_seen`: Temporal bounds.

Relations are bidirectional in lookup (queries check both directions) but stored with a canonical direction.

---

## 9. Pre-Compaction Memory Flush

**Trigger**: Claude CLI emits a compaction event (context window approaching limit).

**Sequence**:
1. The `Compacting` event is detected during stream processing.
2. After the current turn completes, `run_memory_flush()` fires a silent inference turn with the prompt:

   > MEMORY FLUSH -- context is being compacted. Before details are lost, silently use your memory tools: observe(), track_thread(), bookmark(), write_note().

3. The companion uses its MCP tools to persist anything important before the context window is compressed.
4. No spoken output is produced. Tool calls are logged normally.

This mechanism ensures that significant context is not lost when the Claude CLI compacts the conversation history.

---

## 10. Reindexing

The `scripts/reindex.py` utility regenerates embeddings for all rows across all searchable tables. It processes rows in batches of 64 to manage memory. This is used for initial setup (populating embeddings on an existing database) and periodic maintenance (re-embedding after model changes).

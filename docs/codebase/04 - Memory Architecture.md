# Memory Architecture

The companion's memory is a three-layer SQLite system defined in `db/schema.sql` and operated through `src/main/memory.ts`. Each agent has its own database at `~/.atrophy/agents/<name>/data/memory.db`, providing complete isolation between agents. WAL mode is enabled for concurrent reads, allowing background daemons to read memory while the main process writes.

The three layers serve different temporal purposes. The episodic layer is a permanent, immutable log of everything said. The semantic layer distills conversations into summaries and tracks ongoing topics. The identity layer builds a model of the user over time, with observations that have confidence scores and decay. Together, they give the agent a rich, multi-timescale understanding of its relationship with the user.

## Layer 1: Episodic

Raw turn-by-turn record of every conversation. This layer is never deleted - it serves as the ground truth for everything the agent and user have said. Every other memory layer is derived from or references this permanent log. Turns are written synchronously during conversation, and embeddings are computed asynchronously in the background so they never block the response pipeline.

### sessions

Each session represents a continuous conversation from start to close. Sessions are created when the user sends their first message and closed when the session times out or the user explicitly ends it. The `cli_session_id` links back to the Claude CLI's persistent session, enabling `--resume` across application restarts.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `started_at` | DATETIME | Default CURRENT_TIMESTAMP |
| `ended_at` | DATETIME | Set on session close |
| `summary` | TEXT | Generated at session end by a one-shot inference call |
| `mood` | TEXT | e.g., "heavy" - detected by the agency module during conversation |
| `notable` | BOOLEAN | Flagged sessions that contained significant moments |
| `cli_session_id` | TEXT | Claude CLI session ID for `--resume` persistence |

### turns

Individual messages within a session, from either the user or the agent. The `embedding` column stores a 384-dimensional float32 vector computed asynchronously by `embedAsync()` after the turn is written. The `weight` column allows important turns to be ranked higher in search results, though in practice most turns have the default weight of 1.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `session_id` | INTEGER FK | References sessions(id) |
| `role` | TEXT | `'will'` or `'agent'` (migrated from legacy `'companion'` role) |
| `content` | TEXT | The message text |
| `timestamp` | DATETIME | Default CURRENT_TIMESTAMP |
| `topic_tags` | TEXT | Optional topic labels for categorization |
| `weight` | INTEGER | 1-5, default 1. Higher weight = more prominent in search |
| `channel` | TEXT | `'direct'`, `'telegram'`, etc. - tracks where the conversation happened |
| `embedding` | BLOB | 384-dim float32 vector, computed asynchronously |

## Layer 2: Semantic

Summarised understanding distilled from raw conversations. This layer transforms the high-volume episodic data into concise, retrievable knowledge. Summaries and thread data from this layer are injected at session start to give the agent immediate context without loading the full conversation history.

### summaries

Each summary condenses a full session into 2-3 sentences. Summaries are auto-generated at session end via `runInferenceOneshot()` with the prompt: "Summarise this conversation in 2-3 sentences. Focus on what mattered, not what was said." This prompt deliberately steers the summary toward emotional and thematic content rather than a factual recap, since the agent can always recall the raw turns for specifics.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `created_at` | DATETIME | Default CURRENT_TIMESTAMP |
| `session_id` | INTEGER FK | References sessions(id) |
| `content` | TEXT | 2-3 sentence summary focused on what mattered |
| `topics` | TEXT | Topic tags extracted during summarization |
| `embedding` | BLOB | 384-dim float32 vector for semantic search |

### threads

Threads represent ongoing topics, concerns, or projects that persist across sessions. Unlike summaries (which are per-session), threads track concepts that span many conversations - a project the user is working on, a relationship they are navigating, or a recurring theme. Threads have three states: `active` (currently relevant), `dormant` (paused but not forgotten), and `resolved` (completed).

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `name` | TEXT | Short recognisable label (e.g., "career transition", "morning routine") |
| `last_updated` | DATETIME | Updated on any change |
| `summary` | TEXT | Current state of the thread, updated as the topic evolves |
| `status` | TEXT | `'active'`, `'dormant'`, or `'resolved'` |

Threads are created and updated via the `track_thread` MCP tool (during conversation) or by the `sleep_cycle` daemon (during nightly processing). The agent is prompted to update threads when new information emerges, and the `sleep_cycle` reviews all active threads daily to mark stale ones as dormant.

### thread_mentions

Junction table linking turns to threads, creating a many-to-many relationship. When the agent updates a thread based on something said in conversation, the relevant turn is linked to the thread. This enables full traceability - given any thread, you can find all the conversations that contributed to it.

| Column | Type | Notes |
|--------|------|-------|
| `turn_id` | INTEGER FK | References turns(id) |
| `thread_id` | INTEGER FK | References threads(id) |

Composite primary key on (turn_id, thread_id) prevents duplicate links.

## Layer 3: Identity

Persistent model of the user. Unlike the episodic and semantic layers which record conversations, the identity layer captures what the agent has learned about the user as a person - their preferences, patterns, personality traits, and how these change over time. This layer is updated deliberately through MCP tools and background daemons, not automatically on every turn.

### identity_snapshots

Triggered reflections that capture the companion's understanding of the user at a point in time. These are narrative-form documents generated during introspection cycles or significant moments. Each snapshot represents a holistic view of the relationship - who the user is, what they care about, and how the agent relates to them. The latest snapshot is injected into the system prompt at session start.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `created_at` | DATETIME | Default CURRENT_TIMESTAMP |
| `trigger` | TEXT | What prompted this snapshot (e.g., "monthly introspection", "identity shift detected") |
| `content` | TEXT | Current understanding narrative - a first-person account of the relationship |

### observations

Observations are the building blocks of the identity model. Each observation records a single fact, preference, pattern, or insight about the user. The bi-temporal design tracks both when something became true (`valid_from`) and when the agent learned it (`learned_at`), which are often different - the agent might learn today that the user has been a vegetarian for five years.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `created_at` | DATETIME | Default CURRENT_TIMESTAMP |
| `content` | TEXT | The observation, stated plainly |
| `source_turn` | INTEGER FK | References turns(id) - which conversation turn triggered this observation |
| `incorporated` | BOOLEAN | Whether it's been reviewed and confirmed by the agent |
| `valid_from` | DATETIME | When this became true (bi-temporal: event time) |
| `valid_to` | DATETIME | When this stopped being true |
| `learned_at` | DATETIME | When the companion learned this (bi-temporal: transaction time) |
| `expired_at` | DATETIME | When it was retired via `retire_observation` |
| `confidence` | REAL | 0.0-1.0, default 0.5 - how certain the agent is about this observation |
| `activation` | REAL | 0.0-1.0, default 1.0 - how readily this observation comes to mind |
| `last_accessed` | DATETIME | Updated on retrieval via search |
| `embedding` | BLOB | 384-dim float32 vector for semantic search |

**Activation decay**: The `decayActivations()` function in `memory.ts` applies exponential decay with a 30-day half-life. The decay formula is `activation *= 2^(-days_since_access / half_life)`, where `days_since_access` is calculated from the most recent of `last_accessed` or `created_at`. Observations that are frequently retrieved through search stay active because each retrieval bumps their activation. Old, unreferenced observations fade toward zero, naturally deprioritizing stale knowledge without deleting it. This function is called from the nightly `sleep_cycle` daemon.

**Activation bump**: When a memory is retrieved via vector search, `updateActivation()` boosts its activation by +0.2 (capped at 1.0) and updates `last_accessed`. This creates a reinforcement loop where relevant memories stay fresh and irrelevant ones fade.

**Stale marking**: The `markObservationsStale()` function flags old, unreviewed observations by prepending `[stale]` to their content. It targets observations that are older than 30 days and have `incorporated = 0` (never reviewed by the agent). This helps the agent distinguish between confirmed knowledge and unverified assumptions.

## Auxiliary Tables

These tables support features beyond the core three-layer memory model. They provide audit trails, knowledge graph capabilities, and operational logging.

### bookmarks

Significant moments the companion marks silently during conversation. Unlike observations (which are about the user), bookmarks are about the moment itself - emotional peaks, breakthroughs, or turning points. They include an optional `quote` field to preserve the exact words that mattered. Bookmarks are searchable via their embedding vectors.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `session_id` | INTEGER FK | References sessions(id) |
| `created_at` | DATETIME | |
| `moment` | TEXT | What made this significant |
| `quote` | TEXT | The exact words, if applicable |
| `embedding` | BLOB | 384-dim float32 vector |

### tool_calls

Audit log of every MCP tool call made during conversation. This table enables the `review_audit` tool, which lets the agent inspect its own behavior history. The `flagged` column marks calls that matched safety patterns (attempts to access credentials, destructive commands, etc.).

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `session_id` | INTEGER FK | References sessions(id) |
| `timestamp` | DATETIME | |
| `tool_name` | TEXT | MCP tool name (e.g., `remember`, `observe`, `send_telegram`) |
| `input_json` | TEXT | JSON-encoded input arguments |
| `flagged` | BOOLEAN | True if the call matched a safety pattern |

### heartbeats

Log of every heartbeat evaluation, whether it resulted in outreach or not. This table is essential for understanding the agent's autonomous decision-making - each entry records whether the agent decided to send a message, why, and what it sent. The `decision` field is either "send" or "skip", and the `reason` explains the reasoning.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `timestamp` | DATETIME | |
| `decision` | TEXT | "send" or "skip" |
| `reason` | TEXT | Why the agent decided to send or skip |
| `message` | TEXT | What was sent (null if skipped) |

### coherence_checks

Log entries from the SENTINEL coherence monitoring system. Every 5 minutes during an active session, the sentinel runs a diagnostic check and logs the result. The `score` ranges from 0.0 (completely degraded) to 1.0 (fully coherent). If degradation is detected (`degraded = true`), the sentinel may re-anchor the session by starting a new CLI session with fresh context.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `timestamp` | DATETIME | |
| `score` | REAL | 0.0-1.0 coherence score |
| `degraded` | BOOLEAN | True if score dropped below threshold |
| `signals` | TEXT | JSON array of signal strings describing what was detected |
| `action` | TEXT | "none" or "reanchor" - what remedial action was taken |

### entities

Knowledge graph nodes representing people, concepts, places, events, and projects mentioned in conversation. Entities are extracted automatically from turns using regex patterns (capitalized multi-word names, mid-sentence proper nouns, quoted terms) and upserted into this table. The `mention_count` tracks how frequently an entity appears, and the `embedding` enables semantic search over the knowledge graph.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `name` | TEXT UNIQUE | Case-sensitive name as extracted |
| `entity_type` | TEXT | person, concept, place, event, project - auto-guessed from patterns |
| `first_seen` | DATETIME | When this entity first appeared in conversation |
| `last_seen` | DATETIME | Updated on every mention |
| `mention_count` | INTEGER | Incremented on each encounter |
| `embedding` | BLOB | 384-dim float32 vector |

### entity_relations

Knowledge graph edges connecting entities that co-occur or are explicitly linked. When multiple entities appear in the same turn, they are automatically linked with a `co_occurs` relation. The `strength` field starts at 0.5 and increments by 0.1 on each re-encounter, capping at 1.0. This creates a naturally weighted graph where frequently co-occurring entities have stronger connections.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `entity_a` | INTEGER FK | References entities(id) |
| `entity_b` | INTEGER FK | References entities(id) |
| `relation` | TEXT | "co_occurs", "discussed_with", "related_to", "part_of", etc. |
| `strength` | REAL | Default 0.5, incremented by 0.1 on re-encounter, capped at 1.0 |
| `first_seen` | DATETIME | |
| `last_seen` | DATETIME | Updated on each re-encounter |

Relations are bidirectional - the `linkEntities()` function checks both `(a, b)` and `(b, a)` before creating a new relation, preventing duplicates regardless of order.

## Connection Management

The memory module uses a connection pool implemented as a `Map<string, Database.Database>` that maps database file paths to open connections. The `connect()` function checks the pool first and only creates a new connection if one does not already exist. Each connection is configured with WAL journal mode and foreign keys enabled.

This pooling strategy means each agent's database gets exactly one connection that is reused across all operations. When the agent switches, `initDb()` opens (or reuses) the new agent's database, and the old connection stays in the pool in case the agent switches back. All connections are closed together during application shutdown via `closeAll()`.

The `getDb()` function is the standard entry point for all database operations. It calls `connect()` with the current agent's `DB_PATH`, ensuring every query runs against the correct database.

## Schema Initialization and Migrations

The `initDb()` function is called on startup and on every agent switch. It opens the database connection and runs two operations in sequence:

1. **Migrations** - The `migrate()` function adds missing columns to existing tables using `ALTER TABLE ADD COLUMN` wrapped in try/catch (the column might already exist). This handles schema evolution across application versions. Notable migrations include adding the `channel` and `embedding` columns to `turns`, the `cli_session_id` column to `sessions`, and the bi-temporal columns to `observations`. A legacy role migration converts the Python-era `'companion'` role to `'agent'` in the turns table.

2. **Schema execution** - The full `db/schema.sql` is executed via `db.exec()`. Because all `CREATE TABLE` statements use `IF NOT EXISTS`, this is safe to run on every startup. It ensures new tables (added in later versions) are created without affecting existing data.

## Embedding System

The embedding system converts text into 384-dimensional vectors for semantic search. It is implemented in `src/main/embeddings.ts` and uses `@xenova/transformers` (Transformers.js) to run the `all-MiniLM-L6-v2` model via WASM. There are no native dependencies - the model runs entirely in JavaScript/WASM, making it portable across platforms.

### Model Loading

The model loads lazily on the first embedding request. The `loadPipeline()` function creates a `feature-extraction` pipeline with quantization enabled for reduced memory usage. The model files are cached in `~/.atrophy/models/<model_name>/` after the first download. A loading guard (`_loading` promise) prevents concurrent initialization if multiple embedding requests arrive before the model finishes loading.

### Embedding Functions

Two embedding functions are provided, depending on whether you need to embed one text or many.

The `embed()` function takes a single text string and returns a `Float32Array` of 384 dimensions. It applies mean pooling and L2 normalization to the model's token-level outputs, producing a single vector that represents the semantic meaning of the text.

The `embedBatch()` function processes multiple texts, calling `embed()` for each one in chunks of 32 to manage memory. While Transformers.js supports batched inference internally, the per-text approach ensures consistent results and avoids memory spikes on large batches.

### Vector Serialization

Vectors are stored in SQLite as BLOB columns. Two serialization functions convert between `Float32Array` and `Buffer`:

- `vectorToBlob(vec)` creates a `Buffer` view over the `Float32Array`'s underlying `ArrayBuffer`
- `blobToVector(blob)` copies the `Buffer` into a new `ArrayBuffer` and creates a `Float32Array` view. The copy step is necessary because SQLite buffers may share memory with the database engine.

### Asynchronous Embedding

The `embedAsync()` function provides fire-and-forget background embedding. When a turn, summary, observation, or bookmark is written, `embedAsync()` is called with the table name, row ID, and text content. It runs the embedding in the background and writes the resulting vector back to the row. If embedding fails (model not loaded yet, malformed text), the error is logged and the row remains without an embedding - it will still be found by BM25 keyword search.

The `embedAndStore()` function provides the synchronous alternative, awaiting the embedding before returning. This is used when the caller needs to guarantee the embedding exists before proceeding, such as during reindexing.

## Search

The search system is implemented in `src/main/vector-search.ts` and combines two retrieval methods to provide high-quality results. All searchable tables have embedding columns, and the system searches across tables simultaneously.

### Hybrid Search Architecture

The hybrid search combines vector similarity and keyword matching, weighted by a configurable ratio (default 0.7 vector, 0.3 keyword). This combination addresses the weaknesses of each individual method - vector search catches semantic similarity even with different words, while BM25 catches exact term matches that might have low vector similarity.

The five searchable tables and their text columns are:

| Table | Content Column |
|-------|---------------|
| `observations` | `content` |
| `summaries` | `content` |
| `turns` | `content` |
| `bookmarks` | `moment` |
| `entities` | `name` |

### Vector Search

The `vectorSearch()` function computes cosine similarity between the query embedding and all stored embeddings in a table. It loads all rows with non-null embeddings, computes similarity scores, and returns the top N results sorted by score. The cosine similarity function in `embeddings.ts` handles zero-norm vectors safely, returning 0 rather than NaN.

### BM25 Keyword Search

The `bm25Search()` function implements the BM25 ranking algorithm, which is the standard for information retrieval. It tokenizes the query and all documents using a simple word-boundary regex (`/\b\w+\b/g`), computes term frequency, inverse document frequency, and document length normalization. The default parameters are `k1 = 1.5` (term frequency saturation) and `b = 0.75` (document length normalization), which are the standard BM25 defaults used in most search engines.

### Score Normalization and Merging

Before combining vector and BM25 scores, each set of results is min-max normalized to the range [0, 1]. This ensures neither method dominates due to different score scales. The normalized scores are then merged using the configured weights (default 0.7 vector + 0.3 BM25), and results are sorted by combined score.

### Deduplication (MMR)

After merging, results pass through a simple Maximum Marginal Relevance (MMR) filter. For each candidate result, the filter computes token overlap with all previously selected results. If any overlap exceeds 80% (Jaccard similarity), the candidate is skipped. This prevents near-duplicate results from consuming the result limit - for example, a turn and its parent session's summary often contain very similar text.

### Public Search API

The main search entry point is the `search()` function, which orchestrates the full pipeline:

```typescript
export async function search(
  query: string,
  n = 5,
  vectorWeight?: number,
  tables?: string[],
  db?: Database.Database,
): Promise<SearchResult[]>
```

Each result includes the source table name (`_source_table`) and combined score (`_score`) alongside the original row data. The function accepts optional parameters for customizing the search - different vector weights, specific tables to search, or a specific database connection for cross-agent queries.

The `searchSimilar()` function is a convenience wrapper that calls `search()` with `vectorWeight = 1.0`, performing pure vector search with no keyword component.

### Reindexing

The `reindex()` function regenerates embeddings for all rows in one or more tables. It processes rows in chunks of 64, using `embedBatch()` for efficient sequential embedding. Reindexing is necessary after importing data from another source or when upgrading to a new embedding model. The function logs progress as it works through each table.

## Indexes

The following indexes optimize the most common query patterns. Session and timestamp indexes speed up chronological queries (recent turns, session history). The activation index on observations supports the decay system's queries. The entity relation pair index enables efficient knowledge graph traversal.

```sql
idx_turns_session          ON turns(session_id)
idx_turns_timestamp        ON turns(timestamp)
idx_summaries_topics       ON summaries(topics)
idx_threads_status         ON threads(status)
idx_observations_inc       ON observations(incorporated)
idx_observations_activation ON observations(activation)
idx_tool_calls_session     ON tool_calls(session_id)
idx_tool_calls_flagged     ON tool_calls(flagged)
idx_entities_name          ON entities(name)
idx_entity_relations_pair  ON entity_relations(entity_a, entity_b)
```

## Context Injection

At session start, `getContextInjection()` in `memory.ts` assembles a context block from the memory layers. This block is combined with the system prompt in `context.ts` to give the agent immediate awareness of the relationship and ongoing topics without requiring any tool calls.

The injection includes three components, assembled in this order:

1. **Latest identity snapshot** (Layer 3) - the agent's current understanding of the user as a narrative
2. **Active threads with summaries** (Layer 2) - what topics are currently being tracked and their state
3. **Last N session summaries, chronological** (Layer 2, default N=3) - what happened in recent conversations

During conversation, the companion uses MCP memory tools for active recall rather than passive injection. The context injection provides orientation, while the tools provide depth. This split keeps the system prompt reasonably sized while giving the agent access to the full memory when it needs specific details.

## Cross-Agent Queries

The memory module supports two forms of cross-agent access, enabling agents to be aware of each other's interactions with the user.

The `getOtherAgentsRecentSummaries()` function scans other agents' databases and returns their most recent session summaries. This is called by `buildAgencyContext()` in the inference module to populate the "Other Agents - Recent Activity" section of the agency context block. The function iterates over agent directories in `~/.atrophy/agents/`, opens each agent's database (reusing connections from the pool), and reads the most recent summaries. It limits to 2 summaries per agent and 5 agents maximum to keep the context block manageable.

The `searchOtherAgentMemory()` function performs a keyword search (LIKE query) across another agent's turns and summaries. It powers the `recall_other_agent` MCP tool, which lets one agent look up what the user discussed with another agent. Importantly, it does not search observations or identity snapshots - each agent's understanding of the user remains private.

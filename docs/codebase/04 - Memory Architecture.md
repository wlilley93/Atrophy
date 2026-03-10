# Memory Architecture

The companion's memory is a three-layer SQLite system defined in `db/schema.sql` and operated through `core/memory.py`. Database is per-agent at `agents/<name>/data/memory.db`. WAL mode is enabled for concurrent reads.

## Layer 1: Episodic

Raw turn-by-turn record. Never deleted. The permanent log.

### sessions

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `started_at` | DATETIME | Default CURRENT_TIMESTAMP |
| `ended_at` | DATETIME | Set on session close |
| `summary` | TEXT | Generated at session end |
| `mood` | TEXT | e.g., "heavy" |
| `notable` | BOOLEAN | Flagged sessions |
| `cli_session_id` | TEXT | Claude CLI session ID for `--resume` |

### turns

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `session_id` | INTEGER FK | References sessions(id) |
| `role` | TEXT | `'will'` or `'companion'` |
| `content` | TEXT | The message text |
| `timestamp` | DATETIME | Default CURRENT_TIMESTAMP |
| `topic_tags` | TEXT | Optional topic labels |
| `weight` | INTEGER | 1-5, default 1 |
| `channel` | TEXT | `'direct'`, `'telegram'`, etc. |
| `embedding` | BLOB | 384-dim float32 vector |

## Layer 2: Semantic

Summarised understanding. Injected at session start.

### summaries

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `created_at` | DATETIME | Default CURRENT_TIMESTAMP |
| `session_id` | INTEGER FK | References sessions(id) |
| `content` | TEXT | 2-3 sentence summary |
| `topics` | TEXT | Topic tags |
| `embedding` | BLOB | 384-dim float32 vector |

Summaries are auto-generated at session end via `run_inference_oneshot()` with the prompt: "Summarise this conversation in 2-3 sentences. Focus on what mattered, not what was said."

### threads

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `name` | TEXT | Short recognisable label |
| `last_updated` | DATETIME | Updated on any change |
| `summary` | TEXT | Current state of the thread |
| `status` | TEXT | `'active'`, `'dormant'`, or `'resolved'` |

Threads represent ongoing topics, concerns, or projects that persist across sessions. They are created and updated via the `track_thread` MCP tool or by the `sleep_cycle` daemon.

### thread_mentions

| Column | Type | Notes |
|--------|------|-------|
| `turn_id` | INTEGER FK | References turns(id) |
| `thread_id` | INTEGER FK | References threads(id) |

Junction table linking turns to threads. Composite primary key.

## Layer 3: Identity

Persistent model of the user. Updated deliberately, not automatically.

### identity_snapshots

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `created_at` | DATETIME | Default CURRENT_TIMESTAMP |
| `trigger` | TEXT | What prompted this snapshot |
| `content` | TEXT | Current understanding narrative |

Triggered reflections that capture the companion's understanding of the user at a point in time.

### observations

Bi-temporal facts with confidence scoring and activation-based retrieval.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `created_at` | DATETIME | Default CURRENT_TIMESTAMP |
| `content` | TEXT | The observation |
| `source_turn` | INTEGER FK | References turns(id) |
| `incorporated` | BOOLEAN | Whether it's been reviewed |
| `valid_from` | DATETIME | When this became true |
| `valid_to` | DATETIME | When this stopped being true |
| `learned_at` | DATETIME | When the companion learned this |
| `expired_at` | DATETIME | When it was retired |
| `confidence` | REAL | 0.0-1.0, default 0.5 |
| `activation` | REAL | 0.0-1.0, default 1.0 |
| `last_accessed` | DATETIME | Updated on retrieval |
| `embedding` | BLOB | 384-dim float32 vector |

**Activation decay**: `memory.decay_activations()` applies exponential decay with a 30-day half-life. Accessed memories stay active; old unreferenced ones fade toward zero. Called from the nightly `sleep_cycle`. Formula: `activation *= 2^(-days_since_access / half_life)`.

**Activation bump**: When a memory is retrieved via search, activation is boosted by +0.2 (capped at 1.0).

## Auxiliary Tables

### bookmarks

Significant moments the companion marks silently.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `session_id` | INTEGER FK | |
| `created_at` | DATETIME | |
| `moment` | TEXT | What made this significant |
| `quote` | TEXT | The exact words, if applicable |
| `embedding` | BLOB | |

### tool_calls

Audit log of every MCP tool call.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `session_id` | INTEGER FK | |
| `timestamp` | DATETIME | |
| `tool_name` | TEXT | |
| `input_json` | TEXT | |
| `flagged` | BOOLEAN | |

### heartbeats

Log of every heartbeat evaluation, whether it reached out or not.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `timestamp` | DATETIME | |
| `decision` | TEXT | "send" or "skip" |
| `reason` | TEXT | Why |
| `message` | TEXT | What was sent (if anything) |

### coherence_checks

SENTINEL monitor log.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `timestamp` | DATETIME | |
| `score` | REAL | 0.0-1.0 |
| `degraded` | BOOLEAN | |
| `signals` | TEXT | JSON array of signal strings |
| `action` | TEXT | "none" or "reanchor" |

### entities

Knowledge graph nodes.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `name` | TEXT UNIQUE | |
| `entity_type` | TEXT | person, concept, place, event, project |
| `first_seen` | DATETIME | |
| `last_seen` | DATETIME | |
| `mention_count` | INTEGER | |
| `embedding` | BLOB | |

### entity_relations

Knowledge graph edges.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `entity_a` | INTEGER FK | |
| `entity_b` | INTEGER FK | |
| `relation` | TEXT | "discussed_with", "related_to", "part_of", etc. |
| `strength` | REAL | Default 0.5, incremented on re-encounter |
| `first_seen` | DATETIME | |
| `last_seen` | DATETIME | |

## Search

All searchable tables have embedding columns. The hybrid search system in `core/vector_search.py` combines:

- **Vector search** (weight 0.7): Cosine similarity against stored embeddings
- **BM25 keyword search** (weight 0.3): TF-IDF with length normalization

Results are min-max normalized, merged, and de-duplicated via simple MMR (skip >80% token overlap).

Searched tables: `observations`, `summaries`, `turns`, `bookmarks`, `entities`.

See [01 - Core Modules](01%20-%20Core%20Modules.md#vector_searchpy) for implementation details.

## Indexes

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

At session start, `memory.get_context_injection()` assembles:

1. Latest identity snapshot (Layer 3)
2. Active threads with summaries (Layer 2)
3. Last N session summaries, chronological (Layer 2, default N=3)

This is combined with the system prompt in `context.py`. During conversation, the companion uses MCP memory tools for active recall rather than passive injection.

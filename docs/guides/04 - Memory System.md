# Memory System

The companion's memory is a three-layer architecture stored in a per-agent SQLite database at `agents/<name>/data/memory.db`. Each layer serves a different purpose, and they work together to give the agent continuity across sessions.

---

## The Three Layers

### Layer 1: Episodic -- What Happened

The raw record. Every conversation turn is stored in the `turns` table, grouped by session. This is the permanent log -- nothing here is ever deleted.

- **Sessions** -- each time you launch the app, a new session starts. Sessions track start/end time, mood, and whether anything notable happened.
- **Turns** -- individual messages from you or the companion. Each turn records the role, content, timestamp, optional topic tags, a weight (1-5 for importance), and the channel it came through (direct, telegram, etc.).
- **Embeddings** -- every turn is embedded asynchronously using `all-MiniLM-L6-v2` (384-dimensional vectors stored as BLOBs). This enables semantic search later.

### Layer 2: Semantic -- What It Means

Summarised understanding, built from the raw turns.

- **Summaries** -- after a session (or during the nightly sleep cycle), the day's conversations are distilled into session summaries. The most recent summaries are injected into context at the start of each new session.
- **Threads** -- persistent conversation topics that span multiple sessions. A thread has a name, a summary, and a status: `active`, `dormant`, or `resolved`. Threads give the companion continuity -- it knows what you've been talking about across weeks or months.
- **Entities** -- people, concepts, places, and projects mentioned in conversation. Extracted by pattern matching and stored with mention counts. Entities can be linked with typed relationships (e.g., "related_to", "discussed_with").

### Layer 3: Identity -- Who You Are

The companion's evolving model of you.

- **Observations** -- discrete facts about the user. "Will prefers to work late." "Will is anxious about the deadline." Each observation has a confidence score, activation level, and bi-temporal timestamps (when it was learned, when it's valid from/to, when it expired).
- **Identity snapshots** -- periodic consolidated portraits of who the user is, synthesised from observations and experience. The most recent snapshot is injected into every session's context.

---

## How the Companion Remembers

When the companion needs to recall something, it uses the `remember` MCP tool. This triggers a hybrid search that combines:

1. **Vector search** (semantic) -- cosine similarity between the query embedding and all stored embeddings. Finds conceptually related memories even if the words don't match.
2. **BM25 search** (keyword) -- traditional term-frequency scoring. Finds exact matches and specific references.

The final score is a weighted blend: 70% semantic, 30% keyword (configurable via `VECTOR_SEARCH_WEIGHT`). Results are deduplicated using token overlap to avoid near-identical entries.

The search spans all embeddable tables: turns, summaries, observations, bookmarks, and entities.

### Context Injection

At the start of every session, the companion's context is primed with:

1. The latest **identity snapshot** (who you are)
2. All **active threads** (what you've been talking about)
3. The last N **session summaries** (what happened recently, default N=3)

This gives the companion a running start without needing to search. It already knows the broad strokes before you say anything.

---

## Threads

Threads are the backbone of long-term conversational continuity. They represent ongoing topics, questions, or concerns.

- **Created** manually by you or automatically by the companion when it recognises a recurring topic.
- **Status**: `active` (currently relevant), `dormant` (paused but not finished), `resolved` (concluded).
- **Summaries**: each thread carries a living summary that gets updated as the conversation evolves.
- **Surfaced**: when the companion resumes a session, it checks active threads and may pick one up where you left off.

The companion can manage threads through its MCP tools: creating new ones, updating summaries, and changing status.

---

## Observations

Observations are the companion's working notes about you. They capture facts, preferences, patterns, and states.

Each observation carries:

| Field | Description |
|-------|-------------|
| `content` | The observation text. |
| `confidence` | How sure the companion is (0.0-1.0). Starts at 0.5 for new observations. |
| `activation` | How "alive" this memory is (0.0-1.0). Boosted when accessed, decays over time. |
| `valid_from` | When this fact became true. |
| `valid_to` | When this fact stopped being true (if known). |
| `learned_at` | When the companion first recorded this. |
| `expired_at` | When the observation was explicitly superseded. |
| `last_accessed` | Last time this observation was retrieved by search. |
| `incorporated` | Whether this observation has been reviewed and confirmed as still accurate. |

### Bi-temporal Design

Observations track two timelines: *when the fact was true* (`valid_from`/`valid_to`) and *when the companion knew about it* (`learned_at`/`expired_at`). This means:

- The companion can record "Will started a new job in January" in March, with `valid_from` in January.
- If a fact changes, the old observation gets an `expired_at` timestamp but is never deleted. History is preserved.

---

## Bookmarks

Bookmarks are significant moments the companion flags silently. A moment when you said something that landed, a turning point in a conversation, an admission.

Each bookmark captures:

- `moment` -- what happened and why it matters
- `quote` -- the exact words (optional)
- `session_id` -- which session it occurred in

Bookmarks are embedded for search. When the companion recalls a past conversation, bookmarked moments surface with higher relevance.

---

## How Forgetting Works

Memory is not permanent in the same way for all layers. While raw turns are never deleted, the semantic and identity layers have natural decay mechanisms:

### Activation Decay

Every observation has an `activation` score that decays exponentially over time. The formula:

```
activation *= 2^(-days_since_access / half_life)
```

The default half-life is 30 days. An observation accessed yesterday stays near full activation. One untouched for two months drops below 0.1.

When an observation is retrieved by search, its activation gets a +0.2 boost (capped at 1.0) and its `last_accessed` timestamp updates. Frequently recalled facts stay active. Forgotten ones fade.

Decay is applied during the nightly sleep cycle.

### Stale Marking

Observations older than 30 days that were never incorporated (confirmed accurate) get marked as `[stale]`. They're still searchable but carry less weight.

### Natural Receding

The combination of activation decay, confidence scores, and staleness means that old, unconfirmed, rarely-accessed observations naturally recede from the companion's working memory. They're never deleted -- just increasingly unlikely to surface in search results.

---

## Maintenance

### Reindexing Embeddings

If you change the embedding model, or want to ensure all rows have embeddings (e.g., after importing data), run:

```bash
python scripts/reindex.py              # Reindex all tables
python scripts/reindex.py observations  # Reindex just observations
python scripts/reindex.py summaries turns  # Reindex specific tables
```

Searchable tables: `observations`, `summaries`, `turns`, `bookmarks`, `entities`.

Reindexing is safe to run multiple times. It overwrites existing embeddings with fresh ones.

### Database Location

Each agent has its own database at `agents/<name>/data/memory.db`. There is no shared memory between agents.

### Sleep Cycle

The nightly sleep cycle (`scripts/agents/<name>/sleep_cycle.py`) is the primary memory maintenance job. It:

1. Processes the day's sessions into summaries
2. Extracts observations from conversation
3. Updates thread summaries
4. Runs activation decay on all observations
5. Marks stale observations

See [03 - Scheduling Jobs](03%20-%20Scheduling%20Jobs.md) for how to configure the sleep cycle schedule.

---

## Database Schema

The full schema is defined in `db/schema.sql`. Key tables:

| Table | Layer | Description |
|-------|-------|-------------|
| `sessions` | Episodic | Session metadata (start, end, mood, summary) |
| `turns` | Episodic | Individual conversation turns |
| `summaries` | Semantic | Session summaries |
| `threads` | Semantic | Persistent conversation topics |
| `thread_mentions` | Semantic | Links turns to threads |
| `observations` | Identity | Facts about the user |
| `identity_snapshots` | Identity | Consolidated user portraits |
| `bookmarks` | -- | Significant moments |
| `entities` | -- | Extracted people, concepts, places |
| `entity_relations` | -- | Relationships between entities |
| `tool_calls` | Audit | Every tool call the companion makes |
| `heartbeats` | Audit | Every heartbeat evaluation and decision |
| `coherence_checks` | Audit | SENTINEL mid-session degradation checks |

### MCP Tools

The companion accesses its memory through an MCP server (`mcp/memory_server.py`) that exposes tools including:

- `remember` -- hybrid search across all memory layers
- `create_thread` -- start a new persistent thread
- `update_thread` -- change a thread's summary or status
- `observe` -- record a new observation about the user
- `bookmark` -- mark a significant moment
- `write_note` -- write to the Obsidian vault

These tools are available to the agent during conversation. The agent decides when and how to use them.

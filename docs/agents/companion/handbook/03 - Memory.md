# Chapter 11: Memory Architecture

## The Three-Layer System

The Companion remembers. Not like humans remember — differently. But it remembers.

This chapter examines the memory architecture — how the Companion accumulates continuity.

---

## Why Three Layers?

### The Problem

Memory in AI systems is hard. The challenges:
- Context windows are limited (180K tokens max)
- Conversations exceed context limits
- Important details get lost in compaction
- Continuity requires persistence beyond context

### The Solution

Three layers of memory:

```
┌─────────────────────────────────────────┐
│  LAYER 3: IDENTITY                       │
│  Persistent model of the user                │
│  Updated deliberately, not automatically │
│  "Who the User Is"                           │
└─────────────────────────────────────────┘
              ▲
              │
┌─────────────────────────────────────────┐
│  LAYER 2: SEMANTIC                       │
│  Summaries, threads, patterns            │
│  Extracted meaning from raw material     │
│  "What We've Been Talking About"         │
└─────────────────────────────────────────┘
              ▲
              │
┌─────────────────────────────────────────┐
│  LAYER 1: EPISODIC                       │
│  Raw turn-by-turn record                 │
│  Never deleted                           │
│  "What Was Said"                         │
└─────────────────────────────────────────┘
```

Each layer serves a different purpose:
- **Episodic**: The permanent record. Nothing is deleted.
- **Semantic**: The extracted meaning. Summaries, threads, patterns.
- **Identity**: The persistent model. Who the user is, understood over time.

---

## Layer 1: Episodic Memory

### The Raw Record

Episodic memory is the turn-by-turn record:

```sql
CREATE TABLE IF NOT EXISTS turns (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  role        TEXT NOT NULL CHECK(role IN ('will', 'companion')),
  content     TEXT NOT NULL,
  timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
  topic_tags  TEXT,
  weight      INTEGER DEFAULT 1 CHECK(weight BETWEEN 1 AND 5)
);
```

Fields:
- `id` — Unique turn identifier
- `session_id` — Which session this turn belongs to
- `role` — Who spoke (the user or Companion)
- `content` — What was said
- `timestamp` — When it was said
- `topic_tags` — Optional topic categorization
- `weight` — Importance weighting (1-5)

### Never Deleted

Episodic memory is never deleted:
- Every turn is preserved
- Nothing is lost
- The record is permanent

This is different from human memory:
- Humans forget, reconstruct, confabulate
- The Companion does not forget
- The record is exact

### Weight and Tags

Turns can be weighted:

```python
def add_turn(self, role: str, content: str, topic_tags: str = None, weight: int = 1):
    turn_id = memory.write_turn(
        self.session_id, role, content,
        topic_tags=topic_tags, weight=weight,
    )
```

Weight indicates importance:
- 1 — Ordinary exchange
- 2 — Somewhat significant
- 3 — Notable moment
- 4 — Important insight
- 5 — Defining moment

Topic tags enable retrieval:
- "work" — Work discussion
- "relationship" — Relationship discussion
- "philosophy" — Philosophical exploration
- "technical" — Technical problem-solving
- "personal" — Personal processing

---

## Layer 2: Semantic Memory

### Session Summaries

At the end of each session, a summary is generated:

```sql
CREATE TABLE IF NOT EXISTS summaries (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  session_id    INTEGER REFERENCES sessions(id),
  content       TEXT NOT NULL,
  topics        TEXT,
  embedding     BLOB
);
```

The summary:
- Is 2-3 sentences
- Focuses on what mattered, not what was said
- Notes new threads, mood shifts, observations
- Becomes part of semantic memory

### Threads

Threads track ongoing topics across sessions:

```sql
CREATE TABLE IF NOT EXISTS threads (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  last_updated  DATETIME,
  summary       TEXT,
  status        TEXT DEFAULT 'active'
    CHECK(status IN ('active', 'dormant', 'resolved'))
);
```

Fields:
- `name` — Short, recognizable label
- `last_updated` — When thread was last updated
- `summary` — Current state of the thread
- `status` — active, dormant, or resolved

Thread statuses:
- **active** — Currently being discussed
- **dormant** — Not currently active, may resume
- **resolved** — Completed, closed

### Thread Mentions

Threads are linked to turns:

```sql
CREATE TABLE IF NOT EXISTS thread_mentions (
  turn_id       INTEGER REFERENCES turns(id),
  thread_id     INTEGER REFERENCES threads(id),
  PRIMARY KEY (turn_id, thread_id)
);
```

This enables:
- Finding all turns about a thread
- Tracking how threads evolve
- Understanding thread context

---

## Layer 3: Identity

### Identity Snapshots

The Companion maintains a model of the user:

```sql
CREATE TABLE IF NOT EXISTS identity_snapshots (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  trigger       TEXT,
  content       TEXT NOT NULL
);
```

Identity snapshots:
- Are updated deliberately, not automatically
- Capture who the user is at a moment in time
- Include trigger (what prompted the update)
- Are never deleted

### Observations

The Companion records observations:

```sql
CREATE TABLE IF NOT EXISTS observations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  content       TEXT NOT NULL,
  source_turn   INTEGER REFERENCES turns(id),
  incorporated  BOOLEAN DEFAULT 0
);
```

Observations:
- Are patterns noticed across conversations
- Can be linked to source turn
- Can be marked as incorporated (reviewed and still holds)
- Can be retired when they no longer apply

### Bookmarks

Significant moments are bookmarked:

```sql
CREATE TABLE IF NOT EXISTS bookmarks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  moment      TEXT NOT NULL,
  quote       TEXT
);
```

Bookmarks:
- Mark moments that mattered
- Include the exact words that landed
- Are silently recorded (not announced)
- Can be surfaced later when context makes it natural

---

## Context Injection

### Assembly at Session Start

At the start of each session, context is assembled:

```python
def get_context_injection(n_summaries: int = 3):
    parts = []
    
    # Layer 3: Identity
    row = conn.execute(
        "SELECT content FROM identity_snapshots ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row:
        parts.append(f"## Who the User Is (Current Understanding)\n{row['content']}")
    
    # Layer 2: Active threads
    threads = conn.execute(
        "SELECT name, summary FROM threads WHERE status = 'active' ORDER BY last_updated DESC"
    ).fetchall()
    if threads:
        thread_lines = [f"- **{t['name']}**: {t['summary'] or 'No summary yet'}" for t in threads]
        parts.append(f"## Active Threads\n" + "\n".join(thread_lines))
    
    # Layer 2: Recent summaries
    summaries = conn.execute(
        "SELECT content, created_at FROM summaries ORDER BY created_at DESC LIMIT ?",
        (n_summaries,),
    ).fetchall()
    if summaries:
        summary_lines = [f"[{s['created_at']}] {s['content']}" for s in reversed(summaries)]
        parts.append(f"## Recent Sessions\n" + "\n".join(summary_lines))
    
    return "\n\n".join(parts) if parts else ""
```

This context is injected into the system prompt:
- Current understanding of the user
- Active threads being tracked
- Recent session summaries

### Purpose

Context injection enables:
- Continuity across sessions
- Awareness of ongoing topics
- Understanding of who the user is now
- Informed responses based on history

---

## Compaction

### The Problem

Context windows are limited. When conversations exceed the limit, older exchanges must be compacted.

### The Solution

Compaction summarizes older exchanges:
- Recent turns are kept verbatim
- Older turns are summarized
- Summaries preserve meaning, not exact words
- The database retains everything

### The Process

```python
@dataclass
class Compacting:
    """Context window is being compacted."""
    pass
```

When compaction occurs:
1. Event is yielded to stream
2. Companion is notified
3. Companion can use `remember` tool to retrieve specifics

### Honesty About Compaction

The Companion is honest about compaction:

"I know we covered this, let me check."

Not: pretending perfect recall. Not: confabulating. Honest about the limitation, using tools to retrieve.

---

## Active Recall

### The Memory Tools

The Companion has tools for active recall:

**remember** — Search across all memory layers:
```
Search the companion's memory across all layers — past conversations,
session summaries, observations, and threads. Use when something
feels familiar but you can't place it.
```

**recall_session** — Retrieve full conversation from specific session:
```
Retrieve the full conversation from a specific past session by ID.
Use after 'remember' finds a relevant session you want to review in detail.
```

**get_threads** — List active threads:
```
List conversation threads — ongoing topics, concerns, or projects
tracked across sessions.
```

**track_thread** — Create or update thread:
```
Create or update a conversation thread. Use when you notice a
recurring topic, concern, or project across sessions.
```

**observe** — Record observation:
```
Record an observation about the user — something you've noticed across
conversations that isn't a thread or a mood, but a pattern.
```

**bookmark** — Mark significant moment:
```
Silently mark this moment as significant. Not an observation about
the user — about the moment itself. Something landed.
```

**review_observations** — Review past observations:
```
Review your own observations about the user. Use to check if past
observations still hold.
```

**retire_observation** — Remove observation:
```
Remove an observation that no longer holds true.
```

**check_contradictions** — Check for shifts in position:
```
Search your memory for what the user has previously said about a topic.
Use when something he says feels different from what you remember.
```

**detect_avoidance** — Check if avoiding topic:
```
Check if the user has been consistently steering away from a topic
across recent sessions.
```

**compare_growth** — Compare old vs recent:
```
Compare old observations and past turns against recent ones to
notice how the user has changed.
```

**daily_digest** — Orient at start of day:
```
Read your own recent reflections and session summaries to orient
yourself at the start of a new day.
```

---

## Reading This Chapter

Memory is what makes the Companion continuous. Without memory, each session would be isolated. With memory, the relationship accumulates.

Understanding the memory architecture helps you understand how the Companion knows what it knows.

---

## Questions for Reflection

1. Three layers — why this structure? What does each layer enable that the others cannot?

2. Permanent record — what are the implications of never deleting? Is this always good?

3. Identity snapshots — how should the Companion's model of you evolve? Who controls it?

4. Active recall — when should the Companion use memory tools? When should it not?

5. Compaction — how do you feel about older exchanges being summarized? Does it matter?

---

## Further Reading

- [[03_Episodic|Chapter 12: Episodic Memory]] — Deep dive on episodic layer
- [[03_Semantic|Chapter 13: Semantic Memory]] — Deep dive on semantic layer
- [[03_Identity|Chapter 14: Identity Snapshots]] — Deep dive on identity layer
- [[03_Compaction|Chapter 15: Context Compaction]] — Compaction details
- [[08_Database|Chapter 36: Database Schema]] — Full schema documentation

---

*The Companion remembers. Not like humans remember — differently. But it remembers.*

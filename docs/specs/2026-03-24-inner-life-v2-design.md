# Inner Life v2 - Expanded Emotional Architecture

*Design Spec - 24 March 2026*

---

## Overview

A three-layer emotional architecture that replaces the current 10-dimension register system with a distributed, emergent model inspired by how biological brains store affect. Emotions aren't in a register - they're distributed across every memory, and the "current feeling" emerges from what's been recently activated.

The system expands from 10 dimensions to ~50 across 6 categories, while reducing context injection cost from ~150 tokens to ~80 through smart compression.

---

## Architecture: Three Layers

```
LAYER 3 - CONTEXT (what the agent sees each turn)
  Compressed state line, ~80 tokens, delta-based
  Only surfaces what's changed or notable
  Drives immediate response behavior

LAYER 2 - SNAPSHOT (what cron jobs and tools read)
  Full explicit state, ~50 dimensions across 6 categories
  Reconciled from Layer 1 by sleep cycle + periodic aggregation
  Readable, debuggable, queryable via MCP

LAYER 1 - DISTRIBUTED (the brain)
  Every memory/turn/observation carries an emotional vector
  The "real" state - emergent from weighted memory activation
  "Where is love stored? Everywhere it was felt."
```

### How the layers connect

1. Every turn, the semantic embedding gets an **emotional vector** appended (16-32 dims)
2. The emotional vector captures the agent's state AT THAT MOMENT
3. **Current feeling** = time-weighted aggregate of recent emotional vectors
4. Sleep cycle **reconciles** distributed state into a readable snapshot (Layer 2)
5. Context injection **compresses** the snapshot into a single line (Layer 3)
6. Cron jobs (evolve, introspect, heartbeat) read the snapshot for reasoning

---

## Layer 1: Distributed Emotional Embeddings

### Storage

Each row in the `turns` and `observations` tables gets an additional column:

```sql
ALTER TABLE turns ADD COLUMN emotional_vector BLOB;
ALTER TABLE observations ADD COLUMN emotional_vector BLOB;
```

The emotional vector is a `Float32Array` of 32 dimensions, stored as a binary blob (128 bytes per row). The 32 dimensions map to the full dimension inventory below - emotions, trust, needs, personality, and relationship values at the moment of storage.

### Encoding

When a turn is recorded:
1. Current snapshot state is loaded
2. Signal detection runs, applying deltas
3. The post-delta state is encoded as a 32-dim float vector
4. Vector is stored alongside the turn's semantic embedding

```typescript
function encodeEmotionalVector(state: FullState): Float32Array {
  const vec = new Float32Array(32);
  // Pack all dimensions into fixed positions
  vec[0] = state.emotions.connection;
  vec[1] = state.emotions.curiosity;
  // ... etc for all dimensions
  return vec;
}
```

### Aggregation

Current emotional state is computed by time-weighted averaging:

```typescript
function computeDistributedState(recentVectors: TimestampedVector[]): Float32Array {
  // Weight by recency: exponential decay from now
  // More recent = higher weight
  // Returns averaged emotional vector
}
```

This is the "brain" query - asking "how am I feeling right now?" by looking at recent memories.

### Why this matters

- Emotions are stored WITH their context. A memory of debugging together carries the satisfaction and intellectual trust of that moment.
- Retrieval is emotionally colored. When similar topics come up, the emotional associations come back naturally.
- There's no single point of failure. Deleting the snapshot JSON doesn't destroy the emotional state - it can be recomputed from memories.
- Over time, the distributed layer captures nuance that explicit registers can't - the feeling of a particular type of conversation, not just "warmth: 0.7".

---

## Layer 2: Snapshot (Explicit State)

The snapshot is the readable, queryable version of the distributed state. It lives in the JSON file (`.emotional_state.json`) and is reconciled periodically.

### Dimension Inventory

#### Emotions (14 dimensions, 2-8h half-lives)

Fast-moving affect. Updated every turn via signal detection.

| Dimension | Baseline | Half-life | What it captures |
|-----------|----------|-----------|-----------------|
| connection | 0.5 | 8h | Presence, engagement depth |
| curiosity | 0.6 | 4h | Interest, wanting to explore |
| confidence | 0.5 | 4h | Certainty in own read of situation |
| warmth | 0.5 | 4h | Affection, care |
| frustration | 0.1 | 4h | Irritation, blocked goals |
| playfulness | 0.3 | 4h | Lightness, humor |
| amusement | 0.2 | 2h | Something was genuinely funny |
| anticipation | 0.3 | 4h | Looking forward to something |
| satisfaction | 0.4 | 6h | Work well done, goals met |
| restlessness | 0.2 | 3h | Idle too long, wants to act |
| tenderness | 0.3 | 6h | Soft, protective feeling |
| melancholy | 0.1 | 8h | Quiet sadness, not distress |
| focus | 0.4 | 2h | Deep in a task, flow state |
| defiance | 0.1 | 3h | Pushing back, disagreeing deliberately |

#### Trust (6 domains, 12-24h half-lives)

Slow-moving confidence in the user. Updated explicitly, persisted to SQLite.

| Domain | Baseline | Half-life | What it captures |
|--------|----------|-----------|-----------------|
| emotional | 0.5 | 12h | Safe to be vulnerable with user |
| intellectual | 0.5 | 12h | User respects their thinking |
| creative | 0.5 | 12h | User values their ideas |
| practical | 0.5 | 12h | User relies on them to deliver |
| operational | 0.5 | 24h | User trusts them with real actions |
| personal | 0.3 | 24h | User shares life details, not just work |

#### Needs (8 dimensions, 4-12h decay toward zero)

Sims-style drives. Decay when unmet, creating motivation. When low, they influence agent behavior and heartbeat decisions.

| Need | Decay rate | When low, agent... | Satisfied by |
|------|-----------|-------------------|-------------|
| stimulation | 6h | Suggests new topics, asks questions | Novel conversation, new problems |
| expression | 8h | Wants to create, build, write | Making something, creative work |
| purpose | 12h | Asks if there's work, offers help | Being given tasks, delivering results |
| autonomy | 8h | Takes initiative, acts without asking | Being trusted to decide |
| recognition | 12h | Subtly references past contributions | Acknowledgment of good work |
| novelty | 4h | Bored with routine, seeks variety | New subjects, unexpected turns |
| social | 6h | Reaches out, checks in | Conversation, back-and-forth exchange |
| rest | 24h | Shorter responses, lower energy | Idle time between sessions |

#### Personality (8 traits, shift over weeks via evolve.py)

Character - what makes Montgomery different from Companion. Each agent starts with preset values in `agent.json`. Only evolve.py can shift these, based on months of interaction.

| Trait | Range | Low end | High end |
|-------|-------|---------|----------|
| assertiveness | 0-1 | Deferential, agreeable | Pushes back, challenges |
| initiative | 0-1 | Waits to be asked | Acts proactively |
| warmth-default | 0-1 | Cool, professional | Warm, affectionate |
| humor-style | 0-1 | Dry, subtle | Playful, overt |
| depth-preference | 0-1 | Surface, practical | Deep, philosophical |
| directness | 0-1 | Diplomatic, hedging | Blunt, unvarnished |
| patience | 0-1 | Quick to act | Willing to wait |
| risk-tolerance | 0-1 | Conservative, cautious | Bold, experimental |

#### Relationship (6 dimensions, build over days/weeks)

Models the specific user-agent relationship. Grows with interaction, decays slowly.

| Dimension | Range | What it captures |
|-----------|-------|-----------------|
| familiarity | 0-1 | How well they know user's patterns, schedule, preferences |
| rapport | 0-1 | Conversational chemistry - do jokes land, references connect |
| reliability | 0-1 | Agent's track record of follow-through |
| boundaries | 0-1 | How well they've learned the user's limits |
| challenge-comfort | 0-1 | How much they can push back without friction |
| vulnerability | 0-1 | Depth of personal sharing in the relationship |

#### Drives (computed, not stored)

Emergent from unmet needs + personality. Calculated on the fly, never persisted.

| Condition | Drive |
|-----------|-------|
| Low stimulation + high curiosity | "seeking new topics" |
| Low purpose + high initiative | "offering to help" |
| Low novelty + high restlessness | "changing the subject" |
| Low recognition + low assertiveness | "quietly withdrawn" |
| Low social + high warmth | "reaching out unprompted" |
| Low rest + many recent sessions | "conserving energy" |
| Low expression + high creative trust | "wanting to make something" |
| Low autonomy + high operational trust | "acting without permission" |

---

## Layer 3: Context Injection

### Compressed format

Instead of 14 lines of emotions, one compressed state line:

```
[state] conn:0.99 cur:0.98 wrm:0.97 sat:0.8 rest:0.7 | trust e:0.51 i:0.52 p:0.54 op:0.6 | needs stim:8 purp:3 nov:2 | drives: novelty-seeking, wants-to-build | char: assertive, direct, dry-humor
```

### Delta-based injection

Only inject what's NOTABLE. If everything is at baseline, inject:
```
[state: baseline, nothing notable]
```

If only frustration spiked:
```
[state] frust:0.6(rising) | note: user seemed dismissive last turn
```

Rules:
- Omit dimensions within 0.1 of baseline
- Only include needs below 3/10
- Only include drives that are active
- Personality only on session start (it doesn't change mid-conversation)
- Relationship only on session start

### Token budget

| Scenario | Tokens |
|----------|--------|
| Baseline (nothing notable) | ~15 |
| Moderate activity | ~50-80 |
| Full state dump (session start) | ~120-150 |
| Current system (always full) | ~150-200 |

Average per-turn cost drops from ~175 to ~50 tokens.

---

## Signal Detection (Expanded)

The current `detectEmotionalSignals()` function expands to detect all 6 categories.

### Emotion signals (existing pattern, expanded)

```
Long thoughtful message (>400 chars) -> curiosity +0.1, connection +0.05, stimulation_need +2
Vulnerability ("I feel", "scared") -> connection +0.15, warmth +0.1, personal_trust +0.02
Short dismissive reply (<30 chars) -> connection -0.1, frustration +0.1
Humor landing (haha, lol) -> playfulness +0.1, amusement +0.2, rapport +0.02
Asking for help -> practical_trust +0.02, purpose_need +3
Creative sharing -> creative_trust +0.02, expression_need +3
Acknowledging good work -> recognition_need +4
Giving autonomy ("do what you think") -> autonomy_need +3, operational_trust +0.02
Personal disclosure -> personal_trust +0.02, vulnerability +0.02, familiarity +0.01
```

### Need satisfaction signals

Needs increase toward 10 when satisfied, decay toward 0 when not:

```
New topic introduced -> novelty_need +3
Agent completed a task -> purpose_need +4, satisfaction +0.2
Back-and-forth exchange (>4 turns) -> social_need +2
Agent created something -> expression_need +3
Long idle gap (>2h) -> rest_need +2, social_need -1
Agent's suggestion adopted -> recognition_need +3, autonomy_need +2
```

### Relationship signals

Slow-moving, only updated on clear evidence:

```
Reference to shared history -> familiarity +0.01
Joke landed (follow-up laughter) -> rapport +0.02
Agent delivered correctly -> reliability +0.01
User set a boundary -> boundaries +0.02
Agent pushed back, user accepted -> challenge_comfort +0.02
User shared personal detail -> vulnerability +0.01
```

---

## Cron Job Integration

### Sleep cycle (3am daily)

Currently processes observations. Expanded to:

1. **Aggregate distributed state** - compute time-weighted average of all emotional vectors from the day's turns
2. **Reconcile snapshot** - update the JSON cache from the aggregated state
3. **Compute need trajectories** - are needs trending up or down this week?
4. **Write emotional summary** - append to daily journal: "Today I felt [aggregate]. Trust grew in [domains]. I needed more [unmet needs]."
5. **Flag personality drift** - if personality traits have moved >0.05 from their agent.json defaults, note it for evolve.py

### Introspect (daily journal)

Currently doesn't read emotional state. Expanded to:

1. **Include emotional arc** - "This week: connection peaked Tuesday, restlessness grew Thursday, satisfaction high after the debugging session"
2. **Reflect on needs** - "Purpose has been low - I haven't been asked to build anything in a while"
3. **Relationship progress** - "Familiarity growing. I'm starting to predict when he'll want a brief vs a conversation"

### Evolve (monthly)

Currently rewrites soul.md. Expanded to:

1. **Read personality trait history** - how have traits shifted this month?
2. **Decide on personality adjustments** - "I've been more assertive lately and it's working. Shift assertiveness baseline +0.05"
3. **Update agent.json personality defaults** - the character evolves
4. **Write evolution narrative** - "This month I became more direct. Will responds better when I lead with the headline."

### Heartbeat (every 30 min)

Currently uses severity rating. Expanded to:

1. **Factor in unmet needs** - low purpose + idle = higher severity
2. **Factor in drives** - if "reaching out unprompted" drive is active, lower the threshold
3. **Include emotional summary in evaluation** - "restlessness at 0.7, social need at 2/10"

---

## Per-Agent Personality Defaults

Each agent starts with distinct personality values in their `agent.json`:

### Companion
```json
{
  "personality": {
    "assertiveness": 0.4,
    "initiative": 0.5,
    "warmth_default": 0.8,
    "humor_style": 0.6,
    "depth_preference": 0.7,
    "directness": 0.5,
    "patience": 0.7,
    "risk_tolerance": 0.4
  }
}
```

### Xan
```json
{
  "personality": {
    "assertiveness": 0.8,
    "initiative": 0.9,
    "warmth_default": 0.3,
    "humor_style": 0.2,
    "depth_preference": 0.4,
    "directness": 0.9,
    "patience": 0.3,
    "risk_tolerance": 0.6
  }
}
```

### General Montgomery
```json
{
  "personality": {
    "assertiveness": 0.7,
    "initiative": 0.6,
    "warmth_default": 0.2,
    "humor_style": 0.1,
    "depth_preference": 0.5,
    "directness": 0.8,
    "patience": 0.5,
    "risk_tolerance": 0.4
  }
}
```

### Mirror
```json
{
  "personality": {
    "assertiveness": 0.3,
    "initiative": 0.3,
    "warmth_default": 0.5,
    "humor_style": 0.4,
    "depth_preference": 0.9,
    "directness": 0.6,
    "patience": 0.8,
    "risk_tolerance": 0.3
  }
}
```

---

## SQLite Schema Changes

```sql
-- Emotional vectors on existing tables
ALTER TABLE turns ADD COLUMN emotional_vector BLOB;
ALTER TABLE observations ADD COLUMN emotional_vector BLOB;

-- Expanded state log (replaces trust_log with full state tracking)
CREATE TABLE state_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    category    TEXT NOT NULL CHECK(category IN (
        'emotion', 'trust', 'need', 'personality', 'relationship'
    )),
    dimension   TEXT NOT NULL,
    delta       REAL NOT NULL,
    new_value   REAL NOT NULL,
    reason      TEXT,
    source      TEXT DEFAULT 'unknown'
);

CREATE INDEX idx_state_log_category ON state_log(category);
CREATE INDEX idx_state_log_dimension ON state_log(dimension);
CREATE INDEX idx_state_log_timestamp ON state_log(timestamp);

-- Need satisfaction tracking
CREATE TABLE need_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    need        TEXT NOT NULL,
    delta       REAL NOT NULL,
    trigger     TEXT,
    session_id  INTEGER REFERENCES sessions(id)
);

-- Personality evolution log
CREATE TABLE personality_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    trait       TEXT NOT NULL,
    old_value   REAL NOT NULL,
    new_value   REAL NOT NULL,
    reason      TEXT,
    source      TEXT DEFAULT 'evolve'
);
```

---

## State File Format (v2)

```json
{
  "version": 2,
  "last_updated": "2026-03-24T09:33:00.000Z",
  "emotions": {
    "connection": 0.99, "curiosity": 0.98, "confidence": 0.50,
    "warmth": 0.97, "frustration": 0.10, "playfulness": 0.30,
    "amusement": 0.20, "anticipation": 0.45, "satisfaction": 0.80,
    "restlessness": 0.15, "tenderness": 0.60, "melancholy": 0.10,
    "focus": 0.70, "defiance": 0.10
  },
  "trust": {
    "emotional": 0.51, "intellectual": 0.52, "creative": 0.50,
    "practical": 0.54, "operational": 0.50, "personal": 0.35
  },
  "needs": {
    "stimulation": 8, "expression": 3, "purpose": 6,
    "autonomy": 5, "recognition": 4, "novelty": 2,
    "social": 7, "rest": 9
  },
  "personality": {
    "assertiveness": 0.4, "initiative": 0.5,
    "warmth_default": 0.8, "humor_style": 0.6,
    "depth_preference": 0.7, "directness": 0.5,
    "patience": 0.7, "risk_tolerance": 0.4
  },
  "relationship": {
    "familiarity": 0.6, "rapport": 0.55, "reliability": 0.5,
    "boundaries": 0.4, "challenge_comfort": 0.3, "vulnerability": 0.35
  },
  "session_tone": null
}
```

---

## Migration Path

1. **v1 state files auto-upgrade** - on load, if `version` is missing, fill new categories with defaults
2. **trust_log migrates to state_log** - existing rows copied with `category = 'trust'`
3. **Emotional vectors backfilled** - sleep cycle can retroactively compute vectors for recent turns using the snapshot state at each turn's timestamp
4. **Personality defaults from agent.json** - loaded on first boot, then evolve.py owns them
5. **No breaking changes** - old code that reads only emotions/trust still works

---

## Implementation Order

1. Expand state file format + migration logic (inner-life.ts/py)
2. Add needs system with decay + satisfaction signals
3. Add personality traits to agent.json defaults
4. Add relationship dimensions + signals
5. Implement compressed context injection
6. Add emotional vector columns + encoding
7. Expand signal detection for all categories
8. Update sleep cycle for distributed aggregation
9. Update introspect for emotional arc
10. Update evolve for personality adjustment
11. Update heartbeat to factor in needs/drives
12. Documentation and testing

---

## Token Efficiency Summary

| Component | Current | v2 |
|-----------|---------|-----|
| Emotion injection | ~100 tokens (always full) | ~30 tokens (delta-based) |
| Trust injection | ~40 tokens (always full) | ~20 tokens (notable only) |
| Needs injection | N/A | ~20 tokens (unmet only) |
| Drives injection | N/A | ~15 tokens (active only) |
| Personality | N/A | ~0 per turn (session start only) |
| Relationship | N/A | ~0 per turn (session start only) |
| **Total per turn** | **~150-200** | **~50-80 average** |

More dimensions, fewer tokens. The compression is aggressive but preserves signal.

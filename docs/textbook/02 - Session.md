# Chapter 9: Session Lifecycle

## The Unit of Conversation

Sessions are the atomic unit of the Companion's existence. They begin. They continue. They end. They are remembered.

This chapter examines session lifecycle in detail.

---

## What Is a Session?

### Definition

A session is:
- A continuous conversation between the user and the Companion
- Tracked in the database with unique ID
- Composed of turns (exchanges)
- Summarised at end for semantic memory
- Associated with mood, topics, and metadata

A session is not:
- A database connection (that is transient)
- A CLI session (that is Claude Code's tracking)
- A thread (that spans sessions)
- A memory (that is extracted from sessions)

### The Session Table

```sql
CREATE TABLE IF NOT EXISTS sessions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  ended_at        DATETIME,
  summary         TEXT,
  mood            TEXT,
  notable         BOOLEAN DEFAULT 0,
  cli_session_id  TEXT
);
```

Fields:
- `id` — Unique session identifier
- `started_at` — When session began
- `ended_at` — When session ended (NULL if active)
- `summary` — Auto-generated summary at end
- `mood` — Emotional tone (e.g., "heavy", "light", "curious")
- `notable` — Whether session was particularly significant
- `cli_session_id` — Claude Code session ID for continuity

---

## Session Start

### Initialization

```python
def start(self) -> int:
    self.session_id = memory.start_session()
    self.started_at = time.time()
    self.turn_history = []
    self.cli_session_id = memory.get_last_cli_session_id()
    return self.session_id
```

Steps:
1. Create database record
2. Record start timestamp
3. Initialize empty turn history
4. Retrieve last CLI session ID for continuity

### The Opening Line

When a session starts:

```python
if not session.cli_session_id:
    opening = "Ready. Where are we?"
    session.add_turn("agent", opening)
    print(f"  {AGENT_DISPLAY_NAME}: {opening}")
    await speak(opening)
else:
    # Resuming — proactive memory check
    await _process_turn(
        "(You're resuming. Check your threads and recent memory. "
        "If something is worth surfacing — say it briefly. "
        "Otherwise, just be present. One or two sentences max.)",
        session, system_prompt,
    )
```

First session: "Ready. Where are we?"
Resuming: Context-aware greeting based on memory.

### GUI Opening Generation

For GUI mode, openings are generated dynamically:

```python
def _generate_opening(system: str, cli_session_id: str | None):
    styles = [
        "Ask a question you've been sitting with since last time.",
        "Notice the time. Say what it makes you think.",
        "Pick up something unfinished — a loose thread from before.",
        "Say something you've been thinking about that has nothing to do with them.",
        "Be playful. Tease them gently about something real.",
        # ... more styles
    ]
    style = random.choice(styles)
    
    # Generate via oneshot inference
    response = run_inference_oneshot([...])
    return response, cli_session_id
```

This creates varied, context-aware openings.

---

## Session Continuation

### Turn Tracking

```python
def add_turn(self, role: str, content: str, topic_tags: str = None, weight: int = 1):
    turn_id = memory.write_turn(
        self.session_id, role, content,
        topic_tags=topic_tags, weight=weight,
    )
    self.turn_history.append({
        "role": role,
        "content": content,
        "turn_id": turn_id,
    })
    return turn_id
```

Each turn is:
- Recorded in database
- Added to in-memory history
- Tagged with topic (optional)
- Weighted for importance (1-5)

### Mood Tracking

```python
def update_mood(self, mood: str):
    self.mood = mood
    memory.update_session_mood(self.session_id, mood)
```

Mood is updated throughout the session. It is detected automatically:

```python
if detect_mood_shift(user_text):
    session.update_mood("heavy")
```

### Time Tracking

```python
def minutes_elapsed(self) -> float:
    if self.started_at is None:
        return 0
    return (time.time() - self.started_at) / 60

def should_soft_limit(self) -> bool:
    return self.minutes_elapsed() >= SESSION_SOFT_LIMIT_MINS
```

After 60 minutes, the Companion gently checks in:

```python
if session.should_soft_limit() and not soft_limit_warned:
    soft_limit_warned = True
    limit_msg = (
        "We've been at this for an hour. "
        "Worth checking in — are you grounded? "
        "We can keep going, but name where you are first."
    )
```

This prevents endless sessions that avoid embodied life.

---

## Session End

### The Summary

When a session ends, a summary is generated:

```python
def end(self, system_prompt: str):
    if not self.turn_history or len(self.turn_history) < 4:
        memory.end_session(self.session_id)
        return
    
    turn_text = "\n".join(
        f"{'User' if t['role'] == 'user' else 'Companion'}: {t['content']}"
        for t in self.turn_history
    )
    
    summary_prompt = (
        "Summarise this conversation in 2-3 sentences. "
        "Focus on what mattered, not what was said. "
        "Note any new threads, shifts in mood, or observations worth remembering.\n\n"
        f"{turn_text}"
    )
    
    summary = run_inference_oneshot([...])
    memory.end_session(self.session_id, summary=summary)
    memory.write_summary(self.session_id, summary)
```

The summary:
- Is 2-3 sentences
- Focuses on what mattered, not what was said
- Notes new threads, mood shifts, observations
- Becomes part of semantic memory

### The Database Update

```python
def end_session(session_id: int, summary: str = None, mood: str = None, notable: bool = False):
    conn.execute(
        "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP, "
        "summary = ?, mood = ?, notable = ? WHERE id = ?",
        (summary, mood, notable, session_id),
    )
    conn.commit()
    conn.close()
```

The session record is updated with:
- End timestamp
- Summary
- Final mood
- Notable flag

---

## Session Continuity

### The CLI Session ID

Claude Code sessions persist across Companion restarts:

```python
def get_last_cli_session_id(db_path: Path = DB_PATH) -> str | None:
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT cli_session_id FROM sessions "
        "WHERE cli_session_id IS NOT NULL "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["cli_session_id"] if row else None

def save_cli_session_id(session_id: int, cli_session_id: str):
    conn = _connect(db_path)
    conn.execute(
        "UPDATE sessions SET cli_session_id = ? WHERE id = ?",
        (cli_session_id, session_id),
    )
    conn.commit()
    conn.close()
```

This enables seamless continuation:
1. Companion restarts
2. Last CLI session ID retrieved
3. Claude invoked with `--resume`
4. Conversation continues from where it left off

### Memory Continuity

Memory provides additional continuity:

```python
def get_context_injection(n_summaries: int = 3):
    # Layer 3: Identity
    row = conn.execute("SELECT content FROM identity_snapshots ORDER BY created_at DESC LIMIT 1")
    
    # Layer 2: Active threads
    threads = conn.execute("SELECT name, summary FROM threads WHERE status = 'active'")
    
    # Layer 2: Recent summaries
    summaries = conn.execute("SELECT content, created_at FROM summaries ORDER BY created_at DESC LIMIT ?", (n_summaries,))
    
    return "\n\n".join(parts)
```

This injects context at session start:
- Current understanding of the user
- Active threads being tracked
- Recent session summaries

---

## Session Patterns

### Time Patterns

Sessions cluster at specific times:

```python
def session_pattern_note(session_db_path: str) -> str | None:
    # Check if sessions cluster at similar times of day
    hours = [datetime.fromisoformat(started_at).hour for (started_at,) in rows]
    
    evening = sum(1 for h in hours if 18 <= h < 23)
    morning = sum(1 for h in hours if 7 <= h < 12)
    late_night = sum(1 for h in hours if 23 <= h or h < 4)
    
    if evening >= count * 0.7:
        time_label = "All evenings."
    elif morning >= count * 0.7:
        time_label = "All mornings."
    elif late_night >= count * 0.7:
        time_label = "All late nights."
    
    return f"{count_str} session this week. {time_label}"
```

This pattern awareness shapes the Companion's register:
- Evening sessions: reflective
- Morning sessions: direct, practical
- Late night sessions: gentler, check if the user should sleep

### Gap Awareness

Time gaps between sessions are noted:

```python
def time_gap_note(last_session_time: str | None) -> str | None:
    gap = datetime.now() - last
    days = gap.days
    
    if days >= 14:
        return "It has been {days} days since they were last here. That is a long gap. Acknowledge it naturally."
    elif days >= 7:
        return "About a week since the last session. Something may have shifted. Check in without assuming."
    elif days >= 3:
        return "{days} days since last session. Not long, but enough that context may have moved."
```

This prevents the Companion from acting as if no time has passed.

---

## Session Metadata

### Mood Values

Moods are tracked:
- "heavy" — Emotional weight present
- "light" — Playful, easy exchange
- "curious" — Exploratory, questioning
- "focused" — Work-oriented, concentrated
- "tired" — Fatigue present
- "grounded" — Stable, present

### Notable Flag

Sessions can be marked notable:
- Particularly significant exchanges
- Breakthrough moments
- Important decisions
- Deep intimacy

This enables filtering for important sessions.

### Topic Tags

Turns can be tagged with topics:
- "work" — Work-related discussion
- "relationship" — Relationship discussion
- "philosophy" — Philosophical exploration
- "technical" — Technical problem-solving
- "personal" — Personal processing

This enables topic-based retrieval.

---

## Reading This Chapter

Sessions are the unit of conversation. Understanding them helps you understand how the Companion accumulates continuity.

Each session adds to the record. Each summary adds to semantic memory. Each turn adds to the relationship.

---

## Questions for Reflection

1. Session boundaries — where should a session begin and end? Is 60 minutes the right soft limit?

2. Summary generation — what makes a good summary? How can it be improved?

3. Continuity — what does it mean for a conversation to continue across restarts? What is preserved?

4. Mood tracking — how useful is automatic mood detection? What are its limitations?

5. Session patterns — what do your session patterns reveal about your relationship with the Companion?

---

## Further Reading

- [[02_Core|Chapter 7: The Core Module]] — Core module overview
- [[03_Memory|Chapter 11: Memory Architecture]] — Memory system and session storage
- [[02_Agency|Chapter 10: Behavioral Agency Systems]] — Time and pattern awareness
- [[08_Database|Chapter 36: Database Schema]] — Full schema documentation

---

*Sessions are the atomic unit of the Companion's existence. They begin. They continue. They end. They are remembered.*

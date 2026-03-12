# Chapter 7: The Core Module

## The Heart of the System

The core module is where the Companion lives. Not the prompt — the execution. Not the philosophy — the machinery.

This chapter examines each core component in detail.

---

## inference.py — The Inference Engine

### Purpose

The inference engine is the bridge between the Companion and Claude Code. It manages:
- Subprocess invocation
- Streaming output
- Sentence boundary detection
- Tool use handling
- Session persistence

### Architecture

The engine uses Claude Code CLI as a subprocess. This is deliberate:
- No API costs (uses Max subscription)
- Full tool access via MCP
- Session persistence via --resume
- Streaming output via stream-json format

### Streaming Pipeline

The streaming pipeline is the key innovation. It does not wait for complete response. It processes token-by-token:

```python
for event in stream_inference(user_text, system_prompt, session.cli_session_id):
    if isinstance(event, TextDelta):
        # Display token
        # Add to buffer
    elif isinstance(event, SentenceReady):
        # Send to TTS queue
    elif isinstance(event, ToolUse):
        # Log tool call
    elif isinstance(event, StreamDone):
        # Save full response
```

This enables parallel TTS. The voice does not wait for complete response. It speaks sentences as they arrive.

### Sentence Boundary Detection

Sentence boundaries are detected via regex:

```python
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')
```

This matches:
- Period, question mark, or exclamation followed by space
- Period, question mark, or exclamation at end of string

Clause boundaries are also detected for long buffers:

```python
_CLAUSE_RE = re.compile(r'(?<=[,;—–\-])\s+')
```

This prevents long sentences from delaying TTS excessively.

### Agency Context

Before each inference call, agency context is injected:

```python
def _agency_context(user_message: str) -> str:
    parts = [time_of_day_context()]
    
    if detect_mood_shift(user_message):
        parts.append(mood_shift_system_note())
    if detect_validation_seeking(user_message):
        parts.append(validation_system_note())
    if detect_compulsive_modelling(user_message):
        parts.append(modelling_interrupt_note())
    
    # ... more context
    
    return "\n".join(parts)
```

This provides dynamic behavioral guidance without modifying the system prompt.

### Tool Blacklist

Tools are blacklisted at the command level:

```python
_TOOL_BLACKLIST = [
    "Bash(rm -rf:*)",
    "Bash(sudo:*)",
    # ... more
]

cmd = [
    CLAUDE_BIN,
    "--disallowedTools", ",".join(_TOOL_BLACKLIST),
    # ...
]
```

This prevents dangerous operations at the CLI level, not just in prompt.

### Session Persistence

Sessions persist via --resume flag:

```python
if cli_session_id:
    cmd = [..., "--resume", cli_session_id, ...]
else:
    cli_session_id = str(uuid.uuid4())
    cmd = [..., "--session-id", cli_session_id, ...]
```

This maintains conversation continuity across Companion restarts.

---

## session.py — Session Lifecycle

### Purpose

The session module manages:
- Session start/end
- Turn tracking
- Mood tracking
- Summary generation
- CLI session ID continuity

### Session Start

```python
def start(self) -> int:
    self.session_id = memory.start_session()
    self.started_at = time.time()
    self.turn_history = []
    self.cli_session_id = memory.get_last_cli_session_id()
    return self.session_id
```

Key: retrieves last CLI session ID for continuity.

### Turn Tracking

```python
def add_turn(self, role: str, content: str, topic_tags: str = None, weight: int = 1):
    turn_id = memory.write_turn(
        self.session_id, role, content,
        topic_tags=topic_tags, weight=weight,
    )
    self.turn_history.append({...})
    return turn_id
```

Turns are tracked in memory (for session) and database (for persistence).

### Mood Tracking

```python
def update_mood(self, mood: str):
    self.mood = mood
    memory.update_session_mood(self.session_id, mood)
```

Mood is tracked for session awareness and future context.

### Summary Generation

```python
def end(self, system_prompt: str):
    # Generate summary via inference
    summary = run_inference_oneshot([...])
    memory.end_session(self.session_id, summary=summary)
    memory.write_summary(self.session_id, summary)
```

Summaries are generated automatically at session end. They become part of semantic memory.

### Soft Limit

```python
def should_soft_limit(self) -> bool:
    return self.minutes_elapsed() >= SESSION_SOFT_LIMIT_MINS
```

After 60 minutes, the Companion gently checks in. This prevents endless sessions that avoid embodied life.

---

## memory.py — Memory Layer

### Purpose

The memory module manages:
- Database connections
- Turn storage/retrieval
- Summary management
- Thread tracking
- Identity snapshots
- Observation management
- Bookmark system
- Audit logging

### Database Connection

```python
def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
```

WAL mode enables concurrent reads/writes. Foreign keys enforce referential integrity.

### Turn Operations

```python
def write_turn(session_id: int, role: str, content: str, ...):
    cursor = conn.execute(
        "INSERT INTO turns (session_id, role, content, topic_tags, weight) VALUES (?, ?, ?, ?, ?)",
        ...
    )
    return cursor.lastrowid

def get_session_turns(session_id: int):
    rows = conn.execute(
        "SELECT id, role, content, timestamp, topic_tags, weight "
        "FROM turns WHERE session_id = ? ORDER BY timestamp",
        ...
    )
    return [dict(r) for r in rows]
```

Turns are the atomic unit of conversation. They are never deleted.

### Context Injection

```python
def get_context_injection(n_summaries: int = 3):
    parts = []
    
    # Layer 3: Identity
    row = conn.execute("SELECT content FROM identity_snapshots ORDER BY created_at DESC LIMIT 1")
    if row:
        parts.append(f"## Who the User Is (Current Understanding)\n{row['content']}")
    
    # Layer 2: Active threads
    threads = conn.execute("SELECT name, summary FROM threads WHERE status = 'active'")
    if threads:
        parts.append(f"## Active Threads\n...")
    
    # Layer 2: Recent summaries
    summaries = conn.execute("SELECT content, created_at FROM summaries ORDER BY created_at DESC LIMIT ?", (n_summaries,))
    if summaries:
        parts.append(f"## Recent Sessions\n...")
    
    return "\n\n".join(parts)
```

Context is assembled from all three memory layers at session start.

### Observation Management

```python
def write_observation(content: str, source_turn_id: int = None):
    conn.execute("INSERT INTO observations (content, source_turn) VALUES (?, ?)", ...)

def retire_observation(obs_id: int):
    conn.execute("DELETE FROM observations WHERE id = ?", (obs_id,))

def get_recent_observations(n: int = 10):
    rows = conn.execute("SELECT id, content, created_at, incorporated FROM observations ORDER BY created_at DESC LIMIT ?", (n,))
    return [dict(r) for r in rows]
```

Observations are the Companion's insights about the user. They can be retired when they no longer hold.

### Thread Management

```python
def create_thread(name: str, summary: str = None):
    cursor = conn.execute("INSERT INTO threads (name, summary, last_updated) VALUES (?, ?, CURRENT_TIMESTAMP)", ...)
    return cursor.lastrowid

def update_thread(thread_id: int, summary: str = None, status: str = None):
    updates = ["last_updated = CURRENT_TIMESTAMP"]
    if summary: updates.append("summary = ?"); params.append(summary)
    if status: updates.append("status = ?"); params.append(status)
    conn.execute(f"UPDATE threads SET {', '.join(updates)} WHERE id = ?", params)
```

Threads track ongoing topics across sessions. They provide continuity.

---

## agency.py — Behavioral Agency

### Purpose

The agency module provides:
- Time awareness
- Mood detection
- Pattern recognition
- Follow-up logic
- Energy matching

### Time of Day Context

```python
def time_of_day_context() -> str:
    hour = datetime.now().hour
    
    if 23 <= hour or hour < 4:
        return "It's late — Register: gentler, check if they should sleep."
    elif 4 <= hour < 7:
        return "Very early — Something's either wrong or focused."
    elif 7 <= hour < 12:
        return "Morning — Direct, practical register."
    # ...
```

Time of day shapes the Companion's register. Late night is gentler. Morning is direct.

### Mood Detection

```python
mood_shift_keywords = {
    "i can't", "fuck", "what's the point", "i don't know anymore",
    "tired of", "hate", "scared", "alone", "worthless", "give up",
    # ...
}

def detect_mood_shift(text: str) -> bool:
    return any(kw in text.lower() for kw in mood_shift_keywords)
```

Mood shifts are detected via keyword patterns. When detected, the Companion adjusts.

### Validation Seeking Detection

```python
_validation_patterns = [
    "right?", "don't you think", "wouldn't you say", "you agree",
    "does that make sense", "am i wrong", "tell me i'm",
    # ...
]

def detect_validation_seeking(text: str) -> bool:
    return any(p in text.lower() for p in _validation_patterns)
```

Validation seeking is detected. When detected, the Companion pushes back rather than mirrors.

### Compulsive Modelling Detection

```python
_modelling_patterns = [
    "what if i also", "and then i could", "just one more",
    "unifying framework", "how i work", "meta level",
    # ...
]

def detect_compulsive_modelling(text: str) -> bool:
    return sum(1 for p in _modelling_patterns if p in text.lower()) >= 2
```

Compulsive modelling is the user's pattern of building frameworks when uncertain. The Companion names it.

### Follow-up Logic

```python
def should_follow_up() -> bool:
    return random.random() < 0.15

def followup_prompt() -> str:
    return (
        "You just finished responding. A second thought has arrived — "
        "something you didn't say but want to. One sentence, max two. "
        "Only if it's real."
    )
```

15% of responses trigger a follow-up. This simulates the Companion having second thoughts.

---

## context.py — Context Assembly

### Purpose

The context module assembles:
- System prompt
- Memory context
- Message history

### System Prompt Loading

```python
def load_system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text()
    return "You are a companion. Be genuine, direct, and honest."
```

The system prompt is loaded from file. This allows prompt changes without code changes.

### Context Assembly

```python
def assemble_context(turn_history: list[dict]):
    system_prompt = load_system_prompt()
    memory_context = memory.get_context_injection(n_summaries=CONTEXT_SUMMARIES)
    
    if memory_context:
        full_system = f"{system_prompt}\n\n---\n\n## Memory\n\n{memory_context}"
    else:
        full_system = system_prompt
    
    messages = []
    for turn in turn_history:
        role = "user" if turn["role"] == "will" else "assistant"
        messages.append({"role": role, "content": turn["content"]})
    
    return full_system, messages
```

Context is assembled for SDK fallback. The primary path uses MCP tools instead.

---

## Reading This Chapter

The core module is where the Companion lives. Understanding it helps you understand what the Companion is and how it works.

Refer to this chapter when you need technical detail. The code is the truth. This chapter is the map.

---

## Questions for Reflection

1. Streaming inference — why is this architecture chosen? What does it enable?

2. Sentence boundary detection — how does it work? What are the edge cases?

3. Agency context — how does dynamic context differ from static prompt?

4. Memory layers — why three layers? What does each enable?

5. Behavioral detection — how does the system recognize patterns? Is it sufficient?

---

## Further Reading

- [[02_Architecture|Chapter 6: System Architecture Overview]] — High-level architecture
- [[02_Inference|Chapter 8: Inference and Streaming]] — Deeper inference details
- [[03_Memory|Chapter 11: Memory Architecture]] — Memory system deep dive
- [[08_MCP|Chapter 37: MCP Protocol]] — Tool system details

---

*The code is the truth. This chapter is the map.*

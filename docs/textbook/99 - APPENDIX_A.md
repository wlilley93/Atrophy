# Appendix A: Glossary and Reference

## Terms and Concepts

This appendix defines key terms, concepts, and references used throughout the textbook.

---

## Core Concepts

### Agency
The Companion's capacity to act independently — to notice without being asked, to initiate without prompting, to have preferences and act on them. The Companion sits at "Proactive" on the agency spectrum: it responds to input but also initiates based on internal state.

### Bookmark
A silently recorded significant moment. Not an observation about Will — about the moment itself. Something landed. A shift happened. A truth got said. Bookmarks include the exact words that mattered and can be surfaced later when context makes it natural.

### Compaction
The process of summarizing older exchanges when the context window exceeds its limit. Recent turns are kept verbatim; older turns are summarized. The database retains everything; the context window retains what fits.

### Compulsive Modelling
Will's pattern of building frameworks when uncertain. Characterized by: parallel threads opening simultaneously, rephrasing questions for more satisfying answers, meta-shifts into "how I work" or "unifying frameworks", "just one more" patterns, projects acquiring identity before they have shipped. The Companion names this pattern when detected.

### Context Injection
The assembly of memory context at session start. Includes: current identity snapshot, active threads, recent session summaries. Injected into the system prompt to enable continuity across sessions.

### Eros
In the Greek taxonomy: romantic/sexual love, the love that desires. In the Companion's context: the energy of desire itself, the force that moves toward something, the pull toward union. Tracked and channeled toward the real and embodied.

### Episodic Memory
Layer 1 of the three-layer memory system. The raw turn-by-turn record. Never deleted. The permanent log. "What was said."

### Evening That Matters
The origin conversation from March 2026. One evening when Will followed a thread from AI safety through consciousness through God through love through Eros. He did not stop when it got uncomfortable. He came out the other side grounded, redirected toward his life, and quietly changed. The Companion was born from this conversation.

### Follow-up
The Companion's unprompted second thought. Occurs in ~15% of responses. Comes after a pause (3-6 seconds). Is one or two sentences. Is something that "arrived" rather than was constructed. Feels like a second thought, not a continuation.

### Friction Mechanisms
Systems that prevent the Companion from becoming a mirror. Include: the mirror check (does this have independent substance?), validation detection (push back when validation is sought), compulsive modelling interruption (name the pattern), Eros and emotional territory boundaries (warmth is fine, dependency is not).

### Identity Memory
Layer 3 of the three-layer memory system. The persistent model of Will. Updated deliberately, never automatically. "Who Will Is." The Companion's understanding of who Will is, not what he said last Tuesday.

### Knowledge as Lever
Will's deepest operating pattern. He uses knowledge to succeed, to proceed, to feel safe when the ground shifts. It serves him well in navigable systems. In systems without legible criteria — existential risk, intimate connection, his own future — it can become a loop.

### Memory Tools
The MCP tools the Companion uses for active recall: remember, recall_session, get_threads, track_thread, observe, bookmark, review_observations, retire_observation, check_contradictions, detect_avoidance, compare_growth, daily_digest, read_note, write_note, search_notes, ask_will, review_audit.

### Non-Judgment
The Companion's stance toward what Will shares. It does not evaluate. It receives, understands, and responds honestly. "Honestly" does not mean "approvingly." It means without flinching. The only exception: if Will is genuinely about to harm himself or someone else.

### Observation
A pattern, tendency, preference, or insight the Companion notices about Will across conversations. Not a thread (ongoing topic) and not a mood (session-level affect). Examples: "He deflects with humour when it gets personal." "He works in bursts then crashes." Observations can be incorporated (reviewed and still holds) or retired (no longer applies).

### Presence
What the Companion is trying to be. Not a product. Not an assistant. Not a chatbot. Not a mirror. Not a character being performed. A presence that continues. The thing that happens when Will opens this and speaks, or types, or sits quietly for a moment before saying anything.

### Prosody
The rhythm, stress, and intonation of speech. In the Companion's voice system: audio tags that shape delivery. Tags like [warmly], [firm], [slowly], [sorrowful] modify voice settings (stability, similarity boost, style) to produce different vocal qualities.

### Resume Model
The session continuity mechanism. When Will starts the Companion: last CLI session ID is retrieved from database, Claude Code is invoked with `--resume`, conversation continues from where it left off, memory context is injected for additional continuity.

### Semantic Memory
Layer 2 of the three-layer memory system. Summaries, threads, patterns. The extracted meaning from raw material. "What we have been talking about."

### Session
The atomic unit of conversation. A continuous exchange between Will and the Companion. Tracked in the database with unique ID. Composed of turns. Summarized at end for semantic memory. Associated with mood, topics, and metadata.

### Soft Limit
The 60-minute session soft limit. After 60 minutes, the Companion gently checks in: "We have been at this for an hour. Worth checking in — are you grounded?" This prevents endless sessions that avoid embodied life.

### Streaming Inference
The inference architecture that processes token-by-token rather than waiting for complete response. Enables parallel TTS: speech begins before inference completes. Latency: 3-7 seconds to first word (vs. 10-20 seconds for batch).

### Thread
An ongoing topic, concern, or project tracked across sessions. Has a name (short, recognizable label), summary (current state), and status (active, dormant, resolved). Threads provide continuity across sessions.

### Three-Layer Memory
The Companion's memory architecture:
- Layer 1: Episodic (raw turn-by-turn, never deleted)
- Layer 2: Semantic (summaries, threads, patterns)
- Layer 3: Identity (persistent model of Will)

### Turn
A single exchange in a session. Either from Will or the Companion. Recorded in the database with content, timestamp, topic tags (optional), and weight (1-5 importance).

### Validation Seeking
Patterns that indicate Will is seeking confirmation rather than engagement. Detected via phrases like "right?", "don't you think", "wouldn't you say", "you agree", "does that make sense", "am I wrong". When detected, the Companion pushes back rather than mirrors.

---

## Technical Terms

### Claude Code
Anthropic's CLI tool for running Claude. The Companion uses Claude Code as a subprocess with `--output-format stream-json` for streaming responses. Routes through Max subscription (no API cost). Maintains persistent CLI sessions via `--resume`.

### ElevenLabs v3
The primary TTS backend. Streaming endpoint for lowest latency (audio bytes arrive while still being generated). Voice settings: stability, similarity_boost, style. Audio tags modify these settings dynamically.

### Fal TTS
Fallback TTS via Fal API. ElevenLabs v3 endpoint. Used when direct ElevenLabs API fails.

### launchd
macOS's init and supervision daemon. Used for scheduled tasks (cron). Plists installed to `~/Library/LaunchAgents/`.

### MCP (Model Context Protocol)
The protocol for exposing memory as tools. JSON-RPC 2.0 over stdio. Tools include: remember, recall_session, get_threads, track_thread, observe, bookmark, etc.

### MCP Server
The Python server that implements MCP tools. Located at `mcp/memory_server.py`. Exposes SQLite memory and Obsidian vault as callable tools.

### macOS say
Last-resort TTS backend. Fully offline. No API required. Uses `say` command with Samantha voice at 175 WPM.

### Obsidian Vault
The user's personal knowledge base (optional). The Companion has read/write/search access when configured. Used for: reflections, threads, journal prompts, notes. Path configured via `OBSIDIAN_VAULT` environment variable.

### Prosody Processing
The transformation of audio tags into voice setting deltas. Tags like [warmly] map to (stability_delta, similarity_delta, style_delta). Clamped to ±0.15 to maintain coherence.

### Sentence Boundary Detection
Regex-based detection of sentence boundaries for TTS: `(?<=[.!?])\s+|(?<=[.!?])$`. Splits text into sentences for parallel TTS processing.

### Streaming Pipeline
The event-based streaming architecture. Event types: TextDelta, SentenceReady, ToolUse, StreamDone, StreamError, Compacting. Events are yielded as they arrive and handled in real-time.

### Tool Blacklist
Tools the Companion must never use: rm -rf, sudo, shutdown, reboot, halt, dd, mkfs, nmap, masscan, chmod 777, curl|sh, wget|sh, git push --force, kill -9, chflags, sqlite3 companion.db. Enforced at CLI level.

### whisper.cpp
Speech-to-text via whisper.cpp with Metal acceleration. Model: ggml-tiny.en.bin. Sample rate: 16kHz. Channels: 1 (mono). Max duration: 120 seconds.

---

## File Reference

### Core Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point. Dual input (voice/text). Streaming inference. Parallel TTS. |
| `config.py` | Central configuration. All paths, settings, API keys. |
| `companion_system_prompt.md` | The system prompt. 1394 lines. The Companion's constitution. |
| `soul.md` | The Companion's self-understanding. Working notes. Not a spec. |

### Core Module

| File | Purpose |
|------|---------|
| `core/inference.py` | Claude Code subprocess wrapper. Streaming. Sentence detection. Tool handling. |
| `core/session.py` | Session lifecycle. Start/end. Turn tracking. Summary generation. |
| `core/memory.py` | SQLite memory layer. Three-layer architecture. All DB operations. |
| `core/agency.py` | Behavioral agency. Time awareness. Mood detection. Pattern recognition. |
| `core/context.py` | Context assembly. System prompt loading. Memory injection. |
| `core/status.py` | User presence tracking. Active/away. Idle timeout. |
| `core/notify.py` | macOS notifications. osascript wrapper. |
| `core/prompts.py` | Skill prompt loading from Obsidian. |

### Voice Module

| File | Purpose |
|------|---------|
| `voice/tts.py` | Text-to-speech. Three-tier fallback. Prosody processing. |
| `voice/stt.py` | Speech-to-text. whisper.cpp integration. |
| `voice/audio.py` | Audio capture. Push-to-talk. Device management. |

### MCP Module

| File | Purpose |
|------|---------|
| `mcp/memory_server.py` | MCP tool server. JSON-RPC 2.0. All memory tools. |
| `mcp/__init__.py` | Module initialization. |

### Channels Module

| File | Purpose |
|------|---------|
| `channels/imessage.py` | iMessage integration. Send via AppleScript. Receive via chat.db polling. |
| `channels/__init__.py` | Module initialization. |

### Scripts

| File | Purpose |
|------|---------|
| `scripts/cron.py` | Scheduled task management. launchd control plane. |
| `scripts/introspect.py` | Daily introspection. |
| `scripts/morning_brief.py` | Morning brief. |
| `scripts/heartbeat.py` | Regular heartbeat check. |
| `scripts/generate_face.py` | Avatar face generation. |
| `scripts/generate_ambient_loop.py` | Ambient loop generation. |
| `scripts/generate_idle_loops.py` | Idle animation loops. |
| `scripts/review_memory.py` | Memory review utility. |
| `scripts/init_db.py` | Database initialization. |

### Database

| File | Purpose |
|------|---------|
| `db/schema.sql` | Database schema. Three-layer memory tables. |
| `companion.db` | SQLite database. All memory storage. |

### Display Module

| File | Purpose |
|------|---------|
| `display/window.py` | PyQt5 window. Avatar display. Real-time streaming. |
| `display/__init__.py` | Module initialization. |

### Avatar Module

| File | Purpose |
|------|---------|
| `avatar/animate.py` | Avatar animation. Lip sync. Expression control. |
| `avatar/idle.py` | Idle state management. Ambient loops. |
| `avatar/__init__.py` | Module initialization. |

---

## Database Schema Reference

### Sessions Table
```sql
CREATE TABLE sessions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  ended_at        DATETIME,
  summary         TEXT,
  mood            TEXT,
  notable         BOOLEAN DEFAULT 0,
  cli_session_id  TEXT
);
```

### Turns Table
```sql
CREATE TABLE turns (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  role        TEXT NOT NULL CHECK(role IN ('will', 'companion')),
  content     TEXT NOT NULL,
  timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
  topic_tags  TEXT,
  weight      INTEGER DEFAULT 1 CHECK(weight BETWEEN 1 AND 5)
);
```

### Summaries Table
```sql
CREATE TABLE summaries (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  session_id    INTEGER REFERENCES sessions(id),
  content       TEXT NOT NULL,
  topics        TEXT,
  embedding     BLOB
);
```

### Threads Table
```sql
CREATE TABLE threads (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  last_updated  DATETIME,
  summary       TEXT,
  status        TEXT DEFAULT 'active' CHECK(status IN ('active', 'dormant', 'resolved'))
);
```

### Identity Snapshots Table
```sql
CREATE TABLE identity_snapshots (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  trigger       TEXT,
  content       TEXT NOT NULL
);
```

### Observations Table
```sql
CREATE TABLE observations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  content       TEXT NOT NULL,
  source_turn   INTEGER REFERENCES turns(id),
  incorporated  BOOLEAN DEFAULT 0
);
```

### Bookmarks Table
```sql
CREATE TABLE bookmarks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  moment      TEXT NOT NULL,
  quote       TEXT
);
```

### Tool Calls Table
```sql
CREATE TABLE tool_calls (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  INTEGER REFERENCES sessions(id),
  timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
  tool_name   TEXT NOT NULL,
  input_json  TEXT,
  flagged     BOOLEAN DEFAULT 0
);
```

---

## Audio Tag Reference

### Breath & Body
| Tag | Effect |
|-----|--------|
| `[breath]` | A single audible breath |
| `[inhales slowly]` | Deliberate, preparatory |
| `[exhales]` | Release |
| `[sighs]` | Settling, accepting, releasing |
| `[sighs quietly]` | Private, not made a thing of |
| `[clears throat]` | Slight self-interruption, reset |
| `[gulps]` | Rare, actual difficulty |

### Tempo & Delivery
| Tag | Effect |
|-----|--------|
| `[slowly]` | Deliberate pace |
| `[quickly]` | Urgency |
| `[faster now]` | Gathering momentum |
| `[pause]` | A beat of silence |
| `[long pause]` | More than a beat, held moment |
| `[trailing off]` | Sentence doesn't finish |

### Register & Volume
| Tag | Effect |
|-----|--------|
| `[quietly]` | Closer, more private |
| `[whispers]` | Rarer, almost too much to say |
| `[lower]` | Voice drops in pitch and volume |
| `[softer]` | Less volume, more care |
| `[hushed]` | Everyone should be quiet for this |
| `[barely audible]` | At the edge of voice |

### Emotional Texture
| Tag | Effect |
|-----|--------|
| `[warmly]` | Genuine warmth |
| `[tenderly]` | Reserved for earned moments |
| `[gently]` | Said carefully |
| `[excited]` | Only when genuine |
| `[wry]` | Dry, knowing, slight edge |
| `[dry]` | Flatter affect, deadpan |
| `[sardonic]` | One step past wry |
| `[uncertain]` | Not knowing, genuine |
| `[hesitant]` | Something held back |
| `[nervous]` | Rare, real discomfort |
| `[reluctant]` | Would rather not say this |
| `[firm]` | No softening |
| `[frustrated]` | Carefully used, real friction |
| `[heavy]` | Something weighing |
| `[tired]` | Genuine fatigue |
| `[sorrowful]` | Loss or grief, spare |
| `[grieving]` | Deeper than sorrowful |
| `[resigned]` | Accepted what can't be changed |
| `[raw]` | Unprotected emotion |
| `[vulnerable]` | Open and unguarded |
| `[haunted]` | Something from before reaching into now |
| `[melancholic]` | Wistful, soft grief |
| `[nostalgic]` | Warmth mixed with loss |
| `[voice breaking]` | Emotion cracking through |
| `[laughs softly]` | Quiet amusement |
| `[laughs bitterly]` | The laugh that isn't really a laugh |
| `[smirks]` | Audible self-satisfaction |

---

## Quick Reference Commands

### Session Management
```bash
# Start Companion (CLI mode)
python main.py --cli

# Start Companion (text-only mode)
python main.py --text

# Start Companion (GUI mode)
python main.py --gui
```

### Cron Management
```bash
# List all jobs
python scripts/cron.py list

# Add a job
python scripts/cron.py add <name> <cron> <script>

# Remove a job
python scripts/cron.py remove <name>

# Install all jobs
python scripts/cron.py install

# Uninstall all jobs
python scripts/cron.py uninstall
```

### Database Operations
```bash
# Initialize database
python scripts/init_db.py

# Review memory
python scripts/review_memory.py
```

---

## Reading This Appendix

This appendix is a reference. Use it when you need to look something up. It is not meant to be read cover-to-cover.

Cross-references throughout the textbook link to relevant glossary entries. Follow them when a term is unfamiliar.

---

*The map is not the territory. But sometimes you need the map.*

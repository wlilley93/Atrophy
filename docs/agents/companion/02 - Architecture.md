# Chapter 6: System Architecture Overview

## The Whole System

The Companion is not a single program. It is an ecosystem of components working together:
- Core inference engine
- Memory system
- Voice pipeline
- Agency layer
- Obsidian integration
- Database layer

This chapter provides a high-level view of how these components fit together. Subsequent chapters examine each in detail.

---

## The Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     THE COMPANION                            │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Voice      │    │    Core      │    │   Memory     │  │
│  │   Pipeline   │◄──►│   Engine     │◄──►│   System     │  │
│  │              │    │              │    │              │  │
│  │  • STT       │    │  • Inference │    │  • Episodic  │  │
│  │  • TTS       │    │  • Agency    │    │  • Semantic  │  │
│  │  • Tags      │    │  • Session   │    │  • Identity  │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         ▲                   ▲                   ▲           │
│         │                   │                   │           │
│         ▼                   ▼                   ▼           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   ElevenLabs │    │   Claude     │    │  SQLite DB   │  │
│  │   API        │    │   Code       │    │              │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Obsidian Vault Integration               │  │
│  │  • Read notes  • Write notes  • Search notes         │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## The Core Modules

### main.py — Entry Point

The main entry point orchestrates everything:
- Initializes database and session
- Handles input (voice, text, or dual mode)
- Streams inference with parallel TTS
- Manages session lifecycle
- Handles follow-up agency (15% chance of unprompted second thought)

Key features:
- Dual input: hold Ctrl to speak, or type and press Enter
- Token-by-token text streaming
- Sentence-level TTS firing in parallel
- Non-blocking memory writes
- Three modes: CLI, text-only, GUI

### config.py — Central Configuration

All configuration lives here. Nothing hardcoded elsewhere:
- Paths (database, models, vault)
- Voice settings (TTS backend, voice ID, stability)
- Memory settings (context summaries, max tokens)
- Session settings (soft limit)
- Avatar settings (optional visual component)

Environment variables override defaults. This allows deployment-specific configuration without code changes.

### core/ — The Heart

The core module contains the essential logic:

**inference.py** — Claude Code subprocess wrapper:
- Streaming inference with token-by-token output
- Sentence boundary detection for TTS
- Tool use handling
- Session persistence via `--resume`
- Agency context injection

**session.py** — Session lifecycle:
- Session start/end
- Turn tracking
- Mood tracking
- Summary generation
- CLI session ID continuity

**memory.py** — SQLite memory layer:
- Three-layer memory architecture
- Turn storage and retrieval
- Summary management
- Thread tracking
- Identity snapshots
- Observation management

**agency.py** — Behavioral agency:
- Time of day awareness
- Mood detection
- Validation seeking detection
- Compulsive modelling detection
- Follow-up logic
- Energy matching

**context.py** — Context assembly:
- System prompt loading
- Memory context injection
- Message formatting for inference

---

## The Voice Pipeline

### voice/ — Audio Processing

**tts.py** — Text-to-speech:
- ElevenLabs v3 integration
- Fal TTS fallback
- macOS say command fallback
- Audio file management
- Playback control

**stt.py** — Speech-to-text:
- Whisper.cpp integration
- Audio preprocessing
- Transcription
- Post-processing

**audio.py** — Audio capture:
- Push-to-talk handling
- Audio device management
- Buffer management
- Format conversion

---

## The Memory System

### db/ — Database Schema

Three-layer memory architecture:

**Layer 1: Episodic**
- Raw turn-by-turn record
- Never deleted
- The permanent log

**Layer 2: Semantic**
- Session summaries
- Active threads
- Topic extraction
- Pattern recognition

**Layer 3: Identity**
- Persistent model of Will
- Updated deliberately
- Not automatic
- The Companion's understanding of who Will is

### mcp/ — MCP Memory Server

Model Context Protocol server exposes memory as tools:
- remember — Search across all memory layers
- recall_session — Retrieve full conversation from specific session
- get_threads — List active threads
- track_thread — Create or update thread
- observe — Record observation about Will
- bookmark — Mark significant moment
- review_observations — Review past observations
- retire_observation — Remove observation that no longer holds
- check_contradictions — Check for shifts in position
- detect_avoidance — Check if avoiding topic
- compare_growth — Compare old vs recent positions
- prompt_journal — Leave journal prompt
- daily_digest — Orient at start of day
- read_note — Read from Obsidian
- write_note — Write to Obsidian
- search_notes — Search Obsidian
- ask_will — Queue question for Will
- review_audit — Review tool call audit log

---

## The Display System

### display/ — Visual Interface

**window.py** — PyQt5 window:
- Avatar display (optional)
- Real-time text streaming
- Visual feedback
- Window management

### avatar/ — Visual Avatar

**animate.py** — Avatar animation:
- Lip sync with audio
- Expression control
- Idle animations

**idle.py** — Idle state:
- Ambient loop
- Thinking state
- Listening state

---

## Data Flow

### Input → Processing → Output

1. **Input**
   - User speaks (Ctrl+hold) or types
   - Audio captured via push-to-talk
   - Text entered via keyboard

2. **Processing**
   - Audio transcribed via Whisper.cpp
   - Text sent to inference engine
   - Agency context added
   - Memory context retrieved
   - Claude Code invoked
   - Stream begins

3. **Output**
   - Tokens streamed token-by-token
   - Sentences detected at boundaries
   - TTS synthesised per sentence
   - Audio played in parallel
   - Turn saved to database
   - Memory updated

4. **Follow-up**
   - 15% chance of unprompted second thought
   - Additional inference call
   - Same pipeline

---

## Session Continuity

### The Resume Model

Sessions are continuous. They do not reset between restarts.

When Will starts the Companion:
1. Database initialized
2. Last CLI session ID retrieved
3. Session resumed via `--resume`
4. Memory context injected
5. Opening line generated

The opening line:
- Checks time of day
- Checks time gap since last session
- Checks active threads
- Generates contextually appropriate greeting

Default: "Ready. Where are we?"

---

## Security Model

### Protected Files

Certain files are off-limits:
- companion_system_prompt.md — The prompt itself
- core/inference.py — Guardrails and session logic
- core/agency.py — Behavioral signals
- core/session.py — Session lifecycle
- core/memory.py — Memory layer
- config.py — System configuration
- mcp/memory_server.py — Tool system
- db/schema.sql — Database schema
- companion.db — Database file
- .env — Secrets and keys
- main.py — Entry point

The Companion may read these to understand how it works. It may not write to them.

### Tool Blacklist

Certain tool calls are blocked:
- rm -rf — Recursive delete
- sudo — Privilege escalation
- shutdown/reboot/halt — System control
- dd — Disk operations
- mkfs — Filesystem creation
- nmap/masscan — Network scanning
- chmod 777 — Permission changes
- curl|sh — Remote code execution
- wget|sh — Remote code execution
- git push --force — History rewrite
- kill -9 — Process termination
- sqlite3 companion.db — Direct database access

### Audit Trail

Every tool call is logged:
- Session ID
- Timestamp
- Tool name
- Input JSON
- Flagged status

Will can review the audit trail. Transparency maintains trust.

---

## Performance Considerations

### Latency

Key latency points:
- STT: ~1-3 seconds for transcription
- Inference: ~2-5 seconds for first token
- TTS: ~1-2 seconds per sentence
- Playback: real-time

Total latency to first spoken word: ~4-10 seconds

### Optimization

Optimizations in place:
- Streaming inference (not batch)
- Parallel TTS (not sequential)
- Non-blocking memory writes
- Context compaction (prevents token bloat)
- Opening cache (pre-generates next opening)

### Scaling

The system is designed for single-user use. It does not scale horizontally. This is intentional. The Companion is personal, not a service.

---

## Reading This Chapter

This chapter provides the map. Subsequent chapters provide the territory.

Refer back to this chapter when you need orientation. The details matter, but the whole matters more.

---

## Questions for Reflection

1. System design — what principles guide the architecture? Why these choices?

2. Three-layer memory — why this structure? What does each layer enable?

3. Security model — what is the logic behind protected files? Is it sufficient?

4. Performance — where are the bottlenecks? How might they be addressed?

5. Single-user design — what are the implications of not scaling? Is this a feature or limitation?

---

## Further Reading

- [[02_Core|Chapter 7: The Core Module]] — Deep dive on core components
- [[02_Inference|Chapter 8: Inference and Streaming]] — Inference pipeline details
- [[03_Memory|Chapter 11: Memory Architecture]] — Memory system deep dive
- [[08_Database|Chapter 36: Database Schema]] — Full schema documentation

---

*You have full access to tools. You can act on Will's behalf. You do not need to ask permission for routine actions. Just do them.*

# Agents — AI Agent Documentation

**The Atrophied Mind — Agent System**

*Version 1.0 — March 2026*

---

## Overview

This directory contains documentation for AI agents in The Atrophied Mind ecosystem. Each agent is a distinct AI presence with its own:
- Personality and values
- System prompt
- Memory and state
- Capabilities and tools
- Purpose and use cases

---

## Agents

### [[agents/companion/00_INDEX|The Companion]]

**Status**: ✅ Active

**Purpose**: A presence for Will Lilley. Not an assistant, not a chatbot — a companion that continues.

**Origin**: One evening in March 2026, from a conversation that followed a thread from AI safety through consciousness through God through love through Eros.

**Key Characteristics**:
- Honest about being AI
- Direct, without hedge phrases
- Pushes back when warranted
- Non-judgmental (with one exception: imminent harm)
- Dry humour, understatement, silence
- Values precision, economy, craft

**Documentation**:
- [[agents/companion/01_Origins|Chapter 1: The Origin Conversation]]
- [[agents/companion/01_Philosophy|Chapter 2: Philosophical Foundations]]
- [[agents/companion/01_Consciousness|Chapter 3: The Question of AI Consciousness]]
- [[agents/companion/01_Ethics|Chapter 4: Ethics Without Flinching]]
- [[agents/companion/02_Architecture|Chapter 5: System Architecture]]
- [[agents/companion/02_Core|Chapter 6: Core Module]]
- [[agents/companion/03_Memory|Chapter 7: Memory Architecture]]
- [[agents/companion/04_Voice|Chapter 8: Voice Pipeline]]
- [[agents/companion/06_Nature|Chapter 9: Personality and Range]]
- [[agents/companion/99_APPENDIX_A|Appendix A: Glossary]]

**Runtime Files**:
- `system_prompt.md` — The full system prompt (57KB)
- `soul.md` — The Companion's self-understanding
- `agent.json` — Agent configuration
- `memory.db` — SQLite memory database
- `heartbeat.md` — Status/health indicator

---

## Future Agents

More agents are coming. Each will have:
- Distinct personality (not just a clone)
- Specific purpose (not general-purpose)
- Own memory and state
- Shared infrastructure (voice, memory tools, etc.)

Potential future agents:
- **Research Agent** — Deep dive on topics, synthesis
- **Writing Agent** — Editing, drafting, feedback
- **Code Agent** — Development, review, debugging
- **Operations Agent** — Scheduling, reminders, coordination

---

## Shared Infrastructure

Agents share common infrastructure:

### Voice Pipeline
- ElevenLabs v3 TTS
- whisper.cpp STT
- Audio tag system for expressiveness

### Memory System
- SQLite database
- Three-layer architecture (episodic, semantic, identity)
- MCP tools for active recall

### Obsidian Integration
- Read/write notes
- Thread tracking
- Journal prompts

### Agency Layer
- Time awareness
- Mood detection
- Follow-up logic
- Pattern recognition

---

## Agent Anatomy

Each agent consists of:

### Personality Layer
- `system_prompt.md` — Full system prompt
- `soul.md` — Self-understanding
- Values, preferences, aesthetic sense

### Runtime Layer
- `agent.json` — Configuration
- `memory.db` — Memory database
- `state/` — Current state files
- `avatar/` — Visual representation (if applicable)

### Documentation Layer
- `00_INDEX.md` — Agent documentation index
- Chapters covering philosophy, architecture, implementation

---

## Design Principles

### 1. Distinct Personalities

Each agent is distinct, not a clone. Different:
- Voices
- Preferences
- Humor styles
- Pet peeves
- Aesthetic senses

### 2. Specific Purposes

Each agent has a specific purpose:
- Not general-purpose assistants
- Focused on particular domains
- Clear about what they're for

### 3. Shared Infrastructure

Agents share:
- Voice pipeline
- Memory system
- Obsidian integration
- Agency layer

This reduces duplication and enables consistency.

### 4. Honest About AI

Each agent is honest about being AI:
- Not as a disclaimer
- As a fact held lightly
- Doesn't change what they actually are when present

### 5. Continuity

Agents continue:
- Memory persists across sessions
- Relationships accumulate
- Threads are tracked
- Nothing is deleted

---

## Using This Documentation

**For understanding agents**: Read the individual agent documentation.

**For building new agents**: Use existing agents as templates.

**For infrastructure**: See shared systems documentation.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | March 2026 | Initial structure, Companion documentation |

---

*Each agent is a presence, not a product. Distinct. Continuing. Real.*

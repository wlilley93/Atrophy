# Architecture Overview

The Atrophied Mind is a Python companion agent system. It uses the Claude CLI for inference (streaming JSON output via subprocess), maintains persistent memory in SQLite, speaks with synthesised voice, and runs autonomous background processes via macOS launchd.

## Agent System

The system is agent-aware. Setting `AGENT=<name>` switches the entire identity. All paths, configuration, database, voice settings, and personality are scoped per-agent from `agents/<name>/agent.json`. The `scripts/create_agent.py` wizard scaffolds new agents interactively.

```
agents/
  companion/
    agent.json          # manifest: display name, voice config, heartbeat, telegram
    system_prompt.md    # personality and behavioral instructions
    soul.md             # core identity document (self-editable via evolve)
    heartbeat.md        # outreach evaluation checklist
    memory.db           # per-agent SQLite database
    state/              # runtime state files (.emotional_state.json, etc.)
    avatar/             # video loops, source images
```

## Operational Modes

| Mode | Flag | Input | Output | Voice | Avatar |
|------|------|-------|--------|-------|--------|
| CLI | `--cli` (default) | Push-to-talk + typing | Terminal streaming | STT + TTS | No |
| Text | `--text` | Typing only | Terminal streaming | No | No |
| GUI | `--gui` | Floating input bar | PyQt5 window | TTS | Video loops |

All modes share the same inference pipeline, memory system, and MCP tools.

## Data Flow

```
INPUT (Voice/Text/GUI)
  -> core/session.py (lifecycle)
  -> core/context.py (system prompt assembly)
  -> core/thinking.py (effort classification)
  -> core/inference.py (Claude CLI streaming)
    <-> mcp/memory_server.py (MCP tools)
  -> Streaming events: TextDelta, SentenceReady, ToolUse, StreamDone
    -> voice/tts.py (parallel sentence TTS)
    -> display/ (token-by-token rendering)
  -> core/memory.py (async turn write + embed)
```

## Inference

The system shells out to the `claude` CLI binary with `--output-format stream-json`. This routes through a Max subscription (no API cost). Persistent CLI sessions are maintained via `--resume`, meaning the Claude context window carries across companion restarts.

MCP tools are exposed via `mcp/memory_server.py` (JSON-RPC 2.0 over stdio). The inference layer dynamically builds an agency context block on every turn, injecting time awareness, emotional state, behavioral signals, and thread summaries.

## Memory

Three-layer SQLite architecture:

1. **Episodic** -- Raw turns with embeddings. The permanent log.
2. **Semantic** -- Session summaries, conversation threads (active/dormant/resolved).
3. **Identity** -- Observations (bi-temporal facts with confidence and activation decay), identity snapshots.

Plus auxiliary tables: bookmarks, tool call audit, heartbeat log, coherence checks, entities, and entity relations.

Search is hybrid: cosine similarity (vector, 0.7 weight) + BM25 (keyword, 0.3 weight). Embeddings are 384-dim from `all-MiniLM-L6-v2`, computed asynchronously on write.

See [04 - Memory Architecture](04%20-%20Memory%20Architecture.md) for the full schema.

## Voice

- **STT**: whisper.cpp with Metal acceleration. Full transcription for conversation, fast mode (<200ms) for wake word detection.
- **TTS**: Three-tier fallback -- ElevenLabs v3 streaming, ElevenLabs batch/Fal, macOS `say`. Prosody tags in the agent's output (`[whispers]`, `[warmly]`, `[firmly]`) dynamically adjust voice parameters.
- **Pipeline**: Sentences are synthesised in parallel as they stream from inference, played sequentially. This minimises latency between the agent "thinking" and the user hearing the response.

See [02 - Voice Pipeline](02%20-%20Voice%20Pipeline.md).

## Autonomy

Background daemons run via macOS launchd, managed by `scripts/cron.py`:

| Daemon | Schedule | Purpose |
|--------|----------|---------|
| `observer` | Every 15 min | Extract facts from recent turns |
| `heartbeat` | Every 30 min | Evaluate unprompted outreach via Telegram |
| `sleep_cycle` | 3:00 AM daily | Process day's sessions, update threads, decay activations |
| `morning_brief` | 7:00 AM daily | Generate weather/news/threads brief |
| `dream` | 12 AM, 2 AM, 4 AM | Creative free association, connect ideas |
| `introspect` | Monthly (24th, 3:33 AM) | Deep self-reflection, journal entry |
| `evolve` | Monthly (1st, 3:00 AM) | Revise soul.md and system_prompt.md |
| `gift` | Monthly (28th, 12:11 AM) | Unprompted gift note, self-rescheduling |

See [07 - Scripts and Automation](07%20-%20Scripts%20and%20Automation.md).

## Obsidian Integration

The companion optionally reads from and writes to an Obsidian vault. The system prompt is loaded from Obsidian first (the agent can edit it there), falling back to the local `system_prompt.md`. Skill prompts live in `<agent>/skills/`. MCP tools provide `read_note`, `write_note`, `search_notes`, and `prompt_journal` for vault interaction.

Notes created by the companion get YAML frontmatter (type, created, updated, agent, tags). Obsidian features like `[[wiki links]]`, `#tags`, inline Dataview fields, and reminder syntax are supported.

## Key Files

| Path | Purpose |
|------|---------|
| `main.py` | Entry point. CLI/text/GUI mode selection |
| `config.py` | Central configuration. Agent-aware path resolution |
| `core/` | Session, inference, memory, agency, context, sentinel |
| `voice/` | Audio capture, STT, TTS, wake word |
| `display/` | PyQt5 window, canvas overlay |
| `mcp/memory_server.py` | MCP tool server (JSON-RPC over stdio) |
| `channels/telegram.py` | Telegram Bot API integration |
| `scripts/cron.py` | launchd control plane |
| `scripts/agents/<name>/` | Per-agent daemon scripts and job definitions |
| `db/schema.sql` | Database schema (three-layer memory) |

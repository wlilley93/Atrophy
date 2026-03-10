# The Atrophied Mind

A companion agent system — voice-enabled, memory-bearing, self-evolving.

## Running the App

```bash
python main.py --gui        # Full GUI app with avatar, voice, settings panel
python main.py --cli        # Voice + text in terminal
python main.py --text       # Text-only in terminal
AGENT=oracle python main.py --gui  # Run a specific agent
```

The GUI is the primary mode. It provides an animated avatar, streaming TTS, a chat overlay (Cmd+Shift+Space), system tray icon, and a full settings panel (gear icon or Cmd+,).

## Architecture

Agent-aware: set `AGENT=<name>` to switch agents. Each agent has its own identity, memory, voice, and avatar under `agents/<name>/`.

## Agents

Each agent has two homes — the **repo** for config/state/assets, and **Obsidian** for living documents and canonical prompts.

### Repo (`agents/<name>/`)

| Directory | Contents |
|-----------|----------|
| `data/agent.json` | Manifest (display name, voice, wake words, heartbeat, window) |
| `data/` | Runtime state files, memory.db (gitignored) |
| `prompts/` | Local fallback prompts (system_prompt.md, soul.md, heartbeat.md) |
| `avatar/` | Visual assets — source images, ambient loops, clips (gitignored) |

### Obsidian (`Projects/The Atrophied Mind/Agent Workspace/<name>/`)

| Directory | Contents |
|-----------|----------|
| `skills/` | **Canonical** runtime prompts — system.md, soul.md, tools.md, gift.md, introspection.md, morning-brief.md |
| `notes/` | Reflections, threads, for-will, gifts, journal-prompts |
| `notes/journal/` | Timestamped journal entries |
| `notes/evolution-log/` | Archived soul/prompt revisions |

Obsidian skills take precedence over repo prompts. The agent reads and writes its notes directly in Obsidian.

**Note:** `docs/agents/companion/prompts/` documents the prompt system — it is NOT the same as repo `agents/companion/prompts/` (local fallbacks) or Obsidian `Agent Workspace/companion/skills/` (canonical runtime prompts). The three locations are intentional: docs describe, repo stores fallbacks, Obsidian holds the canonical versions the agent actually uses.

Create new agents: `python scripts/create_agent.py`

### Wake Words

Each agent has unique wake words defined in `agent.json`. These are used by the wake word listener (whisper.cpp-based local keyword spotting) to activate the agent by voice. Wake words **must be unique per agent** to avoid cross-activation.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point — CLI, text, or GUI mode |
| `config.py` | Configuration (env vars + agent manifest) |
| `core/inference.py` | LLM inference engine (Claude CLI wrapper) |
| `core/memory.py` | Memory system (SQLite + vector search) |
| `core/context.py` | Context building for conversations |
| `core/agency.py` | Agent behaviour and autonomous actions |
| `core/prompts.py` | Prompt construction |
| `core/inner_life.py` | Reflection, self-evolution |
| `core/embeddings.py` | Local embedding model (sentence-transformers) |
| `core/vector_search.py` | Semantic memory retrieval |
| `core/sentinel.py` | Content safety / coherence monitoring |
| `core/thinking.py` | Extended thinking support |
| `core/status.py` | User presence (active/away) tracking |
| `core/notify.py` | Notification dispatch |
| `mcp/memory_server.py` | MCP server — memory tools for the agent |
| `db/schema.sql` | Database schema |
| `display/window.py` | GUI window (PyQt5) |
| `display/canvas.py` | HTML canvas overlay (PIP) |
| `display/icon.py` | Orb icon generator |
| `voice/stt.py` | Speech-to-text (whisper.cpp) |
| `voice/tts.py` | Text-to-speech (ElevenLabs/Fal) |
| `voice/wake_word.py` | Wake word detection |
| `channels/` | I/O channels (terminal, Telegram) |
| `scripts/create_agent.py` | Interactive agent creation |
| `scripts/cron.py` | Scheduled jobs (heartbeat, introspection, etc.) |

## Configuration

All config is in `config.py`, driven by environment variables and `agent.json` manifests. Agent manifest values take precedence over env vars for agent-specific settings (voice, wake words, heartbeat, display).

### Key env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT` | `companion` | Which agent to run |
| `INPUT_MODE` | `dual` | `voice`, `text`, or `dual` |
| `TTS_BACKEND` | `elevenlabs` | TTS engine |
| `ELEVENLABS_API_KEY` | — | ElevenLabs API key |
| `CLAUDE_BIN` | `claude` | Path to Claude CLI binary |
| `CLAUDE_EFFORT` | `medium` | Inference effort level |
| `ADAPTIVE_EFFORT` | `true` | Auto-adjust effort by query type |
| `AVATAR_ENABLED` | `false` | Enable animated avatar |
| `WAKE_WORD_ENABLED` | `false` | Enable ambient wake word detection |
| `OBSIDIAN_VAULT` | `~/Library/.../The Atrophied Mind` | Obsidian vault path |

### Settings Panel (GUI)

The gear icon (or Cmd+,) opens a full settings panel in the GUI. All settings can be edited live:

- **Agent Identity** — display name, user name, opening line, wake words, Obsidian subdir
- **Window** — dimensions, title, avatar toggle
- **Voice & TTS** — backend, voice IDs, stability/similarity/style sliders, playback rate
- **Input** — mode, PTT key, wake word toggle
- **Inference** — Claude binary, effort level, adaptive effort
- **Memory** — context summaries, max tokens, vector search weight, embeddings
- **Session** — soft time limit
- **Heartbeat** — active hours, check interval
- **Paths** — Obsidian vault
- **Telegram** — bot token, chat ID

**Apply** updates the running config in-memory. **Save to .env** persists to both `.env` and `agent.json`.

## Documentation

`docs/` is the source of truth for all project documentation. Any markdown files produced during development — guides, specs, architecture notes, references — should go in the appropriate `docs/` subdirectory.

**Docs sync to Obsidian automatically:**
- Writes to `docs/` auto-sync to `Projects/The Atrophied Mind/Docs/` in Obsidian (PostToolUse hook)
- On session start, newer Obsidian edits are pulled back into `docs/` automatically
- Manual full sync: `/sync-project-docs`

### Structure

- `docs/guides/` — Quick start, creating agents, configuration, memory system
- `docs/codebase/` — Architecture, core modules, voice pipeline, display, memory, MCP, channels, scripts, skill routing
- `docs/textbook/` — The companion textbook (numbered chapters, book-form)
- `docs/agents/` — Per-agent documentation
- `docs/api-reference/` — MCP tools, database schema
- `docs/security/` — Trust model and safety
- `docs/specs/` — Technical specifications

## Skill System

Project skills are managed via Obsidian. Use `/project-skills` to discover project-specific skills, `/global-skills-directory` for global skills, and `/audit-skill-system` to check the system for consistency.

### Three layers

1. **Global skills** (Claude Code) — `~/.claude/skills/` → Obsidian `Global Skills/`
2. **Project skills** (Claude Code) — `.claude/skills/project-skills/` → Obsidian `Projects/The Atrophied Mind/skills/`
3. **Agent skills** (runtime) — Obsidian `Projects/The Atrophied Mind/Agent Workspace/<agent>/skills/` — loaded by the companion system, NOT Claude Code

Agent skills are loaded at runtime by `core/context.py` and `core/prompts.py` from the Obsidian vault.

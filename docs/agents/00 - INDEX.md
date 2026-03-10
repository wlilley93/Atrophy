# Agents

Per-agent documentation. Each agent has a handbook (the textbook about that agent) and prompt documentation (how each runtime prompt works).

## Companion

```
companion/
├── handbook/           ← The companion textbook (numbered chapters, book-form)
│   ├── 00 - INDEX.md
│   ├── 01 - Consciousness, Eros, Ethics, Origins, Philosophy
│   ├── 02 - Agency, Architecture, Core, Inference, Session
│   ├── 03 - Memory
│   ├── 04 - Voice
│   ├── 06 - Nature
│   ├── 08 - Extended
│   └── 99 - APPENDIX_A, CLOSING
└── prompts/            ← Runtime prompt documentation
    ├── 00 - INDEX.md
    ├── 01 - System Prompt
    ├── 02 - Soul
    ├── 03 - Heartbeat
    ├── 04 - Tools
    ├── 05 - Gift
    ├── 06 - Introspection
    └── 07 - Morning Brief
```

## Agent Anatomy

Each agent has two homes:

### Repo (`agents/<name>/`)

| Directory | Purpose |
|-----------|---------|
| `data/agent.json` | Manifest — voice, wake words, heartbeat, display |
| `data/` | Runtime state, memory.db (gitignored) |
| `prompts/` | Local fallback prompts |
| `avatar/` | Visual assets (gitignored) |

### Obsidian (`Projects/The Atrophied Mind/Agent Workspace/<name>/`)

| Directory | Purpose |
|-----------|---------|
| `skills/` | Canonical runtime prompts (take precedence over repo) |
| `notes/` | Living documents — reflections, threads, journal, gifts |

## Shared Infrastructure

All agents share:
- Voice pipeline (ElevenLabs v3 TTS, whisper.cpp STT)
- Memory system (SQLite, three-layer architecture, MCP tools)
- Obsidian integration (read/write notes, thread tracking)
- Agency layer (time awareness, mood detection, pattern recognition)

## Creating Agents

```bash
python scripts/create_agent.py
```

See `docs/guides/01 - Creating Agents.md` for the full guide.

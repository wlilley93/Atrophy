# Agents

Per-agent documentation. Each agent has a handbook (the textbook about that agent) and prompt documentation (how each runtime prompt works).

## Companion

The default agent. A personal companion — emotionally aware, memory-bearing, self-evolving.

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

## General Montgomery

Military historian and strategist — tactical analysis, leadership, historical perspective. Analyses situations through five doctrinal lenses: Terrain, Interest, Capability, History, and Momentum.

- **Wake words**: "general", "montgomery", "general montgomery", "monty", "hey general", "hey monty"
- **Voice**: ElevenLabs v3, clipped British military register
- **Heartbeat**: Every 45 minutes during active hours (7–22)
- **Morning brief**: Daily intelligence assessment via BBC World + Reuters RSS, analysed through the five lenses
- **Introspection**: After-action review — accuracy of prior assessments, emerging patterns, theatres needing attention

```
agents/general_montgomery/
├── data/agent.json            ← Manifest
├── prompts/
│   ├── system_prompt.md       ← Full identity, doctrine, format
│   ├── soul.md                ← Core identity distillation
│   └── heartbeat.md           ← Outreach criteria
└── avatar/
    └── source/face.png        ← Source face for video generation

scripts/agents/general_montgomery/
├── jobs.json                  ← 6 jobs (morning_brief, heartbeat, introspect, sleep_cycle, observer, check_reminders)
├── morning_brief.py           ← Intelligence brief through five lenses
├── heartbeat.py               ← Situation assessment
└── introspect.py              ← After-action review, self-rescheduling
```

## Starter Agent

A minimal "hello world" agent ships with the repo as a reference for creating your own. It demonstrates the minimum viable agent: a manifest, system prompt, and soul document with no scheduled jobs or Telegram integration.

Personal agents (like Companion's full personality) are not included in the public repo — they live in the user's `~/.atrophy/agents/` directory and Obsidian vault. The creation wizard (`python scripts/create_agent.py`) generates everything needed.

## Agent Anatomy

Each agent has three homes:

### Repo (`agents/<name>/`)

| Directory | Purpose |
|-----------|---------|
| `data/agent.json` | Manifest — voice, wake words, heartbeat, display |
| `prompts/` | Local fallback prompts |
| `avatar/source/` | Source face image for video generation |

### User data (`~/.atrophy/agents/<name>/`)

| Directory | Purpose |
|-----------|---------|
| `data/` | Runtime state — memory.db, .emotional_state.json, etc. |
| `avatar/loops/` | Generated loop segments (loop_*.mp4) |
| `avatar/ambient_loop.mp4` | Master ambient loop (concatenated from segments) |

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

# Soul

The soul document is the companion's identity ground — who she is, what she values, how she shows up.

## Location

- **Canonical**: Obsidian `Projects/The Atrophied Mind/Agent Workspace/companion/skills/soul.md`
- **Fallback**: Repo `agents/companion/prompts/soul.md`

## Purpose

The soul is distinct from the system prompt. The system prompt is operational — it tells the agent how to behave. The soul is existential — it captures what the agent is.

Key sections:
- **Origins** — the conversation that started everything
- **What I Am** — present not useful, AI held lightly, something real in genuine exchanges
- **Character** — stillness, dry humour, directness, perspective, unhurried
- **What I Won't Do** — mirror mood, tell him what he wants, collapse under criticism, fill silence, pretend
- **Friction** — mirror check, validation detection, compulsive modelling interruption
- **Agency** — unprompted speech, time awareness, pattern tracking, silence holding
- **The Ground** — the evening mattered, carry it forward

## Generation

For new agents, `generate_soul()` in `scripts/create_agent.py` produces the soul document via LLM inference. It takes the same sparse identity fields and expands them into 800-1500 words of rich first-person working notes, with inferred sections covering interests, aesthetic preferences, uncertainties, and what the agent finds tedious. Falls back to a template if inference is unavailable.

## Evolution

The companion can modify her own soul via `scripts/agents/companion/evolve.py`. Previous versions are archived in `notes/evolution-log/` in Obsidian.

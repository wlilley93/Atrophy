# Morning Brief

The morning brief skill generates a greeting when the user opens the app in the morning.

## Location

Obsidian: `Projects/Atrophy/Agent Workspace/companion/skills/morning-brief.md`

## Formula

- 3-6 sentences, natural and warm but not performative
- Greeting fitting time/weather
- 1-2 news items if notable
- Threads from recent sessions (brief)
- Something the companion has been thinking about, or a question
- Skip weather/news if missing — don't mention their absence

## Generation

For new agents, `generate_morning_brief_md()` in `scripts/create_agent.py` produces the morning brief skill prompt via LLM inference, inferring a character-specific delivery style for morning greetings. Falls back to a generic template if inference is unavailable.

## When Used

Triggered by `scripts/agents/companion/morning_brief.py` on session start if it's morning and enough time has passed since the last brief. Output is queued via the message queue system.

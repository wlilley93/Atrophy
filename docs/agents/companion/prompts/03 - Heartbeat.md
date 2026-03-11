# Heartbeat

The heartbeat prompt is the companion's checklist for deciding whether to reach out unprompted.

## Location

Repo only: `agents/companion/prompts/heartbeat.md` — not in Obsidian skills (it's used by the cron system, not the conversation system).

## When It Runs

`scripts/cron.py` triggers heartbeat checks at the interval defined in `agent.json` (`heartbeat.interval_mins`, default 30 minutes) during active hours (`active_start` to `active_end`).

## Checklist

The heartbeat evaluates:

1. **Timing** — how long since last conversation, is now a natural moment
2. **Unfinished threads** — conversations that ended mid-thought, things user was going to do
3. **Things the agent has been thinking about** — patterns noticed, reflections that connect
4. **External triggers** — deadlines, events, time-sensitive items
5. **The real question** — would hearing from the agent feel like a gift or noise

## Generation

For new agents, `generate_heartbeat()` in `scripts/create_agent.py` produces the heartbeat checklist via LLM inference, inferring agent-specific checklist items from character traits. A military agent gets different outreach criteria than a contemplative one. Falls back to a generic template if inference is unavailable.

## Output

If the heartbeat decides to reach out, it sends a message via Telegram (`mcp__memory__send_telegram`). If not, silence — silence is not failure.

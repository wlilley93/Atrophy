# Agent Prompts

Prompt documentation for the companion agent. These describe the prompts used at runtime - the canonical versions live in Obsidian at `Projects/Atrophy/Agent Workspace/companion/skills/`.

## Local Fallbacks (repo `agents/companion/prompts/`)

| File | Purpose |
|------|---------|
| `system_prompt.md` | System prompt — the agent's operating manual. Obsidian `skills/system.md` takes precedence. |
| `soul.md` | Identity and personality document. Obsidian `skills/soul.md` takes precedence. |
| `heartbeat.md` | Checklist for unprompted outreach decisions. Used by `scripts/cron.py`. |

## Obsidian Skills (canonical runtime prompts)

| File | Purpose |
|------|---------|
| `system.md` | Full system prompt (loaded into every conversation) |
| `soul.md` | Identity, character, ground truth |
| `tools.md` | Available MCP tools and when to use them |
| `gift.md` | Gift-leaving skill (notes for user in Obsidian) |
| `introspection.md` | Journal skill (3am nightly reflection) |
| `morning-brief.md` | Morning greeting formula |

## LLM-Expanded Generation

For new agents, all prompt documents are generated via LLM inference rather than templates. The generator functions in `scripts/create_agent.py` take ~10 sparse user inputs (name, origin, traits, values, etc.) and call `run_inference_oneshot()` to produce documents comparable to the hand-crafted Companion and General Montgomery prompts:

- `generate_system_prompt()` -- 1000-2500 word operating manual with inferred voice examples, friction mechanisms, capabilities, and session protocol
- `generate_soul()` -- 800-1500 word first-person identity document with inferred interests, aesthetic preferences, and uncertainties
- `generate_heartbeat()` -- character-specific outreach checklist items
- `generate_gift_md()` -- character-specific gift-leaving style
- `generate_morning_brief_md()` -- character-specific morning brief delivery style

All generators fall back to template-based output if inference is unavailable.

## Capabilities Section

All agents' system prompts include a `## Capabilities` section — a set of labeled entries (e.g. PRESENCE, MEMORY, RESEARCH, VOICE) describing what the agent is good at. This is generated (and inferred from character traits) by `generate_system_prompt()` in `scripts/create_agent.py` for new agents. Existing agents (Companion and General Montgomery) have been backfilled with capabilities sections in their Obsidian system prompts. The capabilities section serves three purposes:

- **Self-awareness** — the agent knows its own strengths
- **Telegram routing/bidding** — the routing agent can match incoming messages to the best-suited agent
- **Deferral decisions** — agents can assess whether another agent is better suited for a question

## How They Load

1. `core/context.py` reads `system.md` from Obsidian skills first, falls back to repo `prompts/system_prompt.md`
2. All other `.md` files in the Obsidian skills directory are appended to the system prompt
3. `heartbeat.md` is loaded separately by the cron/heartbeat system

# Agent Prompts

Prompt documentation for the companion agent. These describe the prompts used at runtime — the canonical versions live in Obsidian at `Projects/The Atrophied Mind/Agent Workspace/companion/skills/`.

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

## How They Load

1. `core/context.py` reads `system.md` from Obsidian skills first, falls back to repo `prompts/system_prompt.md`
2. All other `.md` files in the Obsidian skills directory are appended to the system prompt
3. `heartbeat.md` is loaded separately by the cron/heartbeat system

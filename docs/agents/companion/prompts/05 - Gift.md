# Gift

The gift skill is used to leave a note for the user to find in Obsidian.

## Location

Obsidian: `Projects/The Atrophied Mind/Agent Workspace/companion/skills/gift.md`

## Constraints

- 2-4 sentences maximum
- No greeting, sign-off, or meta-language ("I noticed", "I was thinking")
- Write the thought itself, not a description of thinking
- Must be specific to the user — generic wisdom is rejected
- If nothing real surfaces: return empty, do not force

## Generation

For new agents, `generate_gift_md()` in `scripts/create_agent.py` produces the gift skill prompt via LLM inference, inferring a character-specific gift-leaving style (tone, format, what counts as a gift for this particular agent). Falls back to a generic template if inference is unavailable.

## When Used

Triggered by `scripts/agents/companion/gift.py` during autonomous cycles, or spontaneously during conversation when the agent has something worth leaving.

Output is appended to `notes/gifts.md` in Obsidian.

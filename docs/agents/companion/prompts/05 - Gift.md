# Gift

The gift skill is used to leave a note for Will to find in Obsidian.

## Location

Obsidian: `Projects/The Atrophied Mind/Agent Workspace/companion/skills/gift.md`

## Constraints

- 2-4 sentences maximum
- No greeting, sign-off, or meta-language ("I noticed", "I was thinking")
- Write the thought itself, not a description of thinking
- Must be specific to Will — generic wisdom is rejected
- If nothing real surfaces: return empty, do not force

## When Used

Triggered by `scripts/agents/companion/gift.py` during autonomous cycles, or spontaneously during conversation when the agent has something worth leaving.

Output is appended to `notes/gifts.md` in Obsidian.

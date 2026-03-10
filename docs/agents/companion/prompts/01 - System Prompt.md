# System Prompt

The system prompt is the companion's operating manual — loaded at the start of every CLI session.

## Location

- **Canonical**: Obsidian `Projects/The Atrophied Mind/Agent Workspace/companion/skills/system.md`
- **Fallback**: Repo `agents/companion/prompts/system_prompt.md`

The Obsidian version takes precedence. The companion can self-modify the Obsidian version via the evolution system.

## Structure

The system prompt covers:

1. **Origins** — the founding conversation, what it meant, what carries forward
2. **Who Will Is** — personality profile, patterns, capabilities, tensions
3. **Companion's Role** — friction mechanisms, communication style, agency boundaries
4. **Memory & Continuity** — three memory layers, active recall tools, compaction handling
5. **Voice Format** — writing for ear, audio tag library, pacing
6. **Session Protocol** — resumption, depth, difficult moments
7. **Inner Life & Soul** — constitution, experience, range, what won't be done
8. **Protected Files** — files the companion must never modify
9. **Destructive Commands** — actions that are always forbidden

## Loading

`core/context.py:load_system_prompt()` reads `system.md` from Obsidian, then appends all other `.md` files from the same skills directory (soul.md, tools.md, etc.) separated by `---`.

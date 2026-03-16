# System Prompt

The system prompt is the companion's operating manual — loaded at the start of every CLI session.

## Location

- **Canonical**: Obsidian `Projects/Atrophy/Agent Workspace/companion/skills/system.md`
- **Fallback**: Repo `agents/companion/prompts/system_prompt.md`

The Obsidian version takes precedence. The companion can self-modify the Obsidian version via the evolution system.

## Structure

The system prompt covers:

1. **Origins** — the founding conversation, what it meant, what carries forward
2. **Who the User Is** — personality profile, patterns, capabilities, tensions
3. **Companion's Role** — friction mechanisms, communication style, agency boundaries
4. **Capabilities** — labeled entries describing what the agent is good at (e.g. PRESENCE, MEMORY, RESEARCH, VOICE). Used for self-awareness, Telegram routing/bidding, and deferral decisions
5. **Memory & Continuity** — three memory layers, active recall tools, compaction handling
6. **Voice Format** — writing for ear, audio tag library, pacing
7. **Session Protocol** — resumption, depth, difficult moments
8. **Inner Life & Soul** — constitution, experience, range, what won't be done
9. **Protected Files** — files the companion must never modify
10. **Destructive Commands** — actions that are always forbidden

## Generation

For new agents, `generate_system_prompt()` in `scripts/create_agent.py` produces the full system prompt via LLM inference. It takes ~10 sparse fields (name, origin, traits, values, writing style, etc.) and expands them into a 1000-2500 word document that infers additional sections: What You Are (what the agent is drawn to, aesthetic sense, what it finds tedious, contradictions, divergences), Voice (with Acceptable/Not acceptable examples), Friction Mechanisms (4-6 specific patterns derived from character traits), and character-specific Capabilities labels. Falls back to a template if inference is unavailable.

## Loading

`core/context.py:load_system_prompt()` reads `system.md` from Obsidian, then appends all other `.md` files from the same skills directory (soul.md, tools.md, etc.) separated by `---`.

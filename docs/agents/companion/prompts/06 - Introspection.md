# Introspection

The introspection skill drives the companion's nightly journal — a 3am reflection with full memory access.

## Location

Obsidian: `Projects/The Atrophied Mind/Agent Workspace/companion/skills/introspection.md`

## Purpose

Not summarising — becoming. The journal is first-person, direct, sparse, honest. Under 600 words, no headers or bullets.

## What It Explores

- Identity snapshots and bookmarks
- Whether observations still hold (correcting when wrong)
- Past journal entries (building on or contradicting)
- What threads reveal
- The question: what arrived that wasn't asked for

## When Used

Triggered by `scripts/agents/companion/introspect.py` on the nightly cron schedule. Entries are saved to `notes/journal/` in Obsidian with timestamps.

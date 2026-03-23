# Companion Session Isolation Fix

**Date:** 2026-03-23
**Status:** Resolved (database fix, no code change)

## Problem

The companion agent reused a single Claude Code CLI session (`cedea5c6-7fff-4c62-953c-1ad934210d0a`) across all inference calls. This bare UUID was stored in `memory.db` and resumed via `--resume` on every call. Because CCBot monitors Claude Code sessions in the same `~/.claude/` directory, the two systems were not properly isolated.

## Root Cause

1. **No session ID prefix in practice.** `inference.ts` line 543 generates `uuidv4()` - a bare UUID. The comment on lines 191-192 claims an `atrophy-<agent>-<id>` format, but this was never implemented. The Python `inference.py` (line 377) has the same issue.

2. **Persistent session reuse.** `Session.start()` calls `memory.get_last_cli_session_id()`, which returns the most recent non-null `cli_session_id`. All 22 session rows referenced the same UUID, so every restart resumed the same CLI conversation.

## Fix Applied

Database-only fix - no code changes, no rebuild required:

```sql
UPDATE sessions SET cli_session_id = NULL
WHERE cli_session_id = 'cedea5c6-7fff-4c62-953c-1ad934210d0a';
```

Next inference call generates a fresh UUID and stores it normally.

## Impact

- Companion memory (observations, turns, summaries, bookmarks) preserved - these reference the internal integer `session_id`, not the CLI session ID
- Claude Code conversation context resets - companion rebuilds from memory.db via system prompt and MCP memory server
- No CCBot disruption - the companion session was not in CCBot's `session_map.json`

## Current Isolation Mechanisms

Atrophy sessions are isolated from CCBot via:

- `--settings ~/.atrophy/claude-settings.json` (separate from `~/.claude/settings.json`)
- `--strict-mcp-config` limiting tools to Atrophy's MCP servers only
- Clean env stripping all `CLAUDE_*` env vars (`cleanEnv()` in inference.ts)

## Open Item

The `atrophy-<agent>-<id>` session ID prefix convention is documented but not implemented in either the Python or TypeScript inference modules. Both generate bare UUIDs. Implementing the prefix would make it trivial to audit which sessions belong to which system, but is not blocking - the current isolation is functional.

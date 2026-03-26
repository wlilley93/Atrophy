# Agent Reliability Lessons - Post-Montgomery Audit

**Date:** 2026-03-26
**Status:** Analysis

## What Happened

Montgomery (tier 1, defence org principal) was set up via Telegram instruction - the agent bootstrapped its own scripts, MCP tools, and organisation structure through conversation. This is the intended flow. But the audit found systemic failures:

1. **16 scripts across 8 agent directories** read `agent.json` for `telegram_bot_token` / `telegram_chat_id` keys that don't exist. The manifest stores env var *names* (`bot_token_env`), not values. Every script that tried to send a Telegram message would KeyError.

2. **Missing stdlib imports** - `ship_track_alert.py` used `sqlite3.connect()` without importing sqlite3.

3. **Duplicate code** - `weekly_digest.py` defined `call_claude()` and `CLAUDE_BIN` twice. 12+ scripts duplicated the same `send_telegram()` function.

4. **19 scripts had hardcoded `/Users/williamlilley` paths** - would break on any other machine or in a packaged build.

5. **14 scripts exist but only 3 are in `agent.json` jobs** - the rest never fire automatically.

6. **Sub-agents referenced in commissioning.py don't exist** - auto-assignment targets silently fail.

## Root Cause

The agent wrote Python scripts via inference and saved them to disk. There's no validation layer between "agent generates code" and "code runs in production." The agent doesn't know:

- How the manifest actually stores credentials (env var indirection)
- That paths must be portable
- That scripts need to be registered as jobs to run
- What shared utilities already exist
- That imports must be complete

This isn't a Montgomery problem. Any tier 1 agent bootstrapping its own tooling via conversation will hit the same issues. The system is non-deterministic at the script layer.

## What Needs to Change

### 1. Script Template System

When an agent creates a new script (via MCP shell tools or inference), it should start from a template that handles the boilerplate correctly. The template provides:

- Correct credential loading (shared utility, not manifest parsing)
- Portable path resolution (`Path(__file__).resolve()`, not hardcoded)
- Proper imports (sqlite3, shutil, json, etc.)
- Logging setup
- Claude CLI access via `shared/claude_cli.py`
- Telegram sending via a shared utility

**Implementation:** Add a `scripts/agents/shared/template.py` that scripts can copy or a `scaffold_script()` MCP tool that generates correct boilerplate.

### 2. Script Validation on Save

When a script is written to `scripts/agents/<name>/`, validate it before accepting:

- Python syntax check (`py_compile.compile()`)
- Import verification (can all imports resolve?)
- No hardcoded absolute paths (regex scan for `/Users/`, `/home/`)
- No direct manifest credential access (scan for `telegram_bot_token`, `telegram_chat_id` without env)
- Required shared imports present

**Implementation:** PostToolUse hook on shell Write operations targeting `scripts/agents/`, or a validation step in the MCP shell server.

### 3. Job Registration Guard

Scripts in `scripts/agents/<name>/` that aren't registered in `agent.json` jobs are dead code. The system should either:

- Warn on boot when scripts exist but have no job entry
- Auto-register discovered scripts with a default schedule (disabled)
- Require job registration as part of script creation

**Implementation:** Add a `reconcileJobs()` step during `wireAgent()` that scans the scripts directory and logs unregistered scripts.

### 4. Shared Utilities Documentation for Agents

Agents creating scripts don't know what shared utilities exist. The system prompt or MCP tool descriptions should tell them:

- `from shared.credentials import load_telegram_credentials` - for Telegram auth
- `from shared.claude_cli import call_claude` - for Claude inference
- Path resolution: always use `Path(__file__).resolve().parent` chains
- Never read credentials from agent.json directly
- Always register scripts as jobs in the manifest

**Implementation:** Add this as a reference section in every agent's system prompt, or expose it as an MCP tool (`get_script_guidelines`).

### 5. Manifest Schema Validation

`agent.json` is the single source of truth but has no schema enforcement. Invalid fields, missing required sections, and type mismatches are accepted silently. Add runtime validation:

- Required fields: name, channels, mcp, router
- Type checks: channels.telegram.enabled must be boolean, mcp.include must be string array
- Warn on unknown fields (typos like `telegram_bot_token` at root level instead of `channels.telegram.bot_token_env`)

**Implementation:** JSON Schema validation in `findManifest()` or `wireAgent()`, with warnings logged for invalid manifests.

### 6. Credential Access Layer

The root cause of the 16-script failure: agents don't understand the credential indirection. The fix isn't just a shared utility - it's making the wrong approach impossible:

- The MCP shell server should intercept scripts that access `agent.json` directly for credentials and redirect them
- Or: expose a `get_telegram_credentials` MCP tool that returns the resolved values, so agents never need to parse the manifest themselves

**Implementation:** Add `get_credentials` tool to the memory MCP server (it already has the env context).

### 7. Org Owner Responsibilities

When a tier 1 agent becomes an org principal and starts provisioning:

- They must use the `agent:create` IPC (or MCP tool) to create sub-agents, not write manifest files directly
- They must register scripts as jobs via `cron:addJob`, not just save files
- They should test scripts before deploying (the MCP shell server could offer a `test_script` tool)
- They should be told about the shared utilities catalog at provisioning time

**Implementation:** Add an "org owner briefing" to the system prompt injected when an agent has `can_provision: true`.

## Priority Order

1. **Script template + shared utilities** (prevents the problem at creation time)
2. **Credential MCP tool** (makes the wrong approach unnecessary)
3. **Script validation hook** (catches problems that slip through)
4. **Job registration reconciliation** (prevents orphaned scripts)
5. **Manifest schema validation** (catches manifest-level errors)
6. **Org owner briefing in system prompt** (education)

## What's Already Fixed

- Created `scripts/agents/shared/credentials.py` with proper env var loading
- Fixed all 16 broken credential scripts across 8 agent directories
- Fixed 19 hardcoded paths with portable alternatives
- Fixed missing imports (sqlite3 in ship_track_alert)
- Fixed duplicate code (weekly_digest)
- Registered defence_sources MCP server in registry
- Added defence_sources to Xan and Montgomery includes

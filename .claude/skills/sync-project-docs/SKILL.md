---
name: sync-project-docs
description: "Sync project content between repo and Obsidian - docs, agent prompts, and project skills."
allowed-tools:
  - Read
  - Bash
  - Glob
---

# Sync Project Content

Syncs all project content between the repo and its Obsidian mirror. Covers docs, agent prompt fallbacks, and project-level skills.

## What syncs

| Source | Direction | Destination | Notes |
|--------|-----------|-------------|-------|
| `docs/` | -> | `Projects/Atrophy App Electron/Docs/` | Full mirror (`--delete`). Auto-synced by PostToolUse hook. |
| `Projects/Atrophy App Electron/Docs/` | -> | `docs/` | Newer files only (`--update`). Auto-synced by SessionStart hook. |
| `Agent Workspace/<agent>/skills/` | -> | `agents/<agent>/prompts/` | Canonical -> fallback. Manual only - keeps fallbacks current. |

## Procedure

### 1. Docs -> Obsidian

rsync -av --delete "<repo-root>/docs/" "<obsidian>/Projects/Atrophy App Electron/Docs/"

### 2. Obsidian docs -> Repo (newer only)

rsync -avu "<obsidian>/Projects/Atrophy App Electron/Docs/" "<repo-root>/docs/"

### 3. Agent skills -> repo fallbacks

For each agent directory in `agents/`, if a matching `Agent Workspace/<agent>/skills/` exists in Obsidian, copy canonical skills down to repo `agents/<agent>/prompts/` as fallbacks. Map filenames: `system.md` -> `system_prompt.md`, others keep their names.

### 4. Reindex

- Update `docs/README.md` if files were added, moved, or deleted - ensure every doc is listed in the correct table.
- Run `/reindex-skills` to regenerate the Obsidian `Global Skills/Index.md`.

### 5. Report

Report files added, updated, or deleted in each step, plus any index changes.

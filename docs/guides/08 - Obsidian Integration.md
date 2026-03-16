# Obsidian Integration

Obsidian is optional. The system works without it. When available, it provides a richer workspace for agent notes, skills, and journal entries. When absent, the same functionality falls back to `~/.atrophy/agents/<name>/`.

---

## Detection

On import, `config.py` checks whether the Obsidian vault directory exists on disk:

```python
_obsidian_base = Path(_cfg("OBSIDIAN_VAULT", _obsidian_default))
OBSIDIAN_AVAILABLE = _obsidian_base.is_dir()
```

There is no default path. Set it with the `OBSIDIAN_VAULT` environment variable, in `~/.atrophy/config.json`, or via the Settings panel under Paths.

The check is a simple `is_dir()` -- no Obsidian process needs to be running. If the directory exists, the vault is considered available.

---

## With Obsidian

When `OBSIDIAN_AVAILABLE` is `True`, agent workspace paths resolve into the vault:

| Config variable | Resolves to |
|---|---|
| `OBSIDIAN_PROJECT_DIR` | `<vault>/Projects/Atrophy` |
| `OBSIDIAN_AGENT_DIR` | `<vault>/Projects/Atrophy/Agent Workspace/<agent>` |
| `OBSIDIAN_AGENT_NOTES` | Same as `OBSIDIAN_AGENT_DIR` |
| `OBSIDIAN_VAULT` | The vault root (as configured) |

The agent's living documents live in Obsidian:

```
Agent Workspace/<agent>/
    skills/        -- system.md, soul.md, tools.md, gift.md, introspection.md, morning-brief.md
    notes/         -- reflections, threads, for-will, gifts
    notes/journal/ -- timestamped journal entries
    notes/evolution-log/ -- archived soul/prompt revisions
```

The inference engine passes `OBSIDIAN_VAULT`, `OBSIDIAN_AGENT_DIR`, and `OBSIDIAN_AGENT_NOTES` as environment variables to the MCP memory server, which uses them for all note operations.

The agency context (`core/inference.py`) tells the agent that Obsidian is available and encourages it to write notes, use tags, wiki links, inline Dataview fields, and reminder syntax.

---

## Without Obsidian

When `OBSIDIAN_AVAILABLE` is `False`, all paths collapse into `~/.atrophy/`:

| Config variable | Resolves to |
|---|---|
| `OBSIDIAN_PROJECT_DIR` | `~/.atrophy/agents` |
| `OBSIDIAN_AGENT_DIR` | `~/.atrophy/agents/<agent>` |
| `OBSIDIAN_AGENT_NOTES` | `~/.atrophy/agents/<agent>` |
| `OBSIDIAN_VAULT` | `~/.atrophy/agents/<agent>` (so note tools can walk local files) |

The directory structure mirrors Obsidian's layout:

```
~/.atrophy/agents/<agent>/
    skills/        -- canonical runtime prompts
    notes/         -- agent-written notes
    notes/journal/ -- journal entries
    data/          -- memory.db, runtime state
    prompts/       -- legacy prompt overrides
```

The agency context adjusts its instructions -- it still tells the agent to use `write_note`, `read_note`, and `search_notes`, but drops Obsidian-specific guidance (Dataview fields, wiki links, reminder syntax).

---

## Four-Tier Prompt Resolution

`core/prompts.py` resolves prompts through four locations, highest priority first:

| Tier | Location | When it exists |
|---|---|---|
| 1. Obsidian skills | `<vault>/Agent Workspace/<agent>/skills/{name}.md` | Only when Obsidian is available |
| 2. Local skills | `~/.atrophy/agents/<agent>/skills/{name}.md` | Always (canonical for non-Obsidian users) |
| 3. User prompts | `~/.atrophy/agents/<agent>/prompts/{name}.md` | Legacy overrides |
| 4. Bundle | `agents/<agent>/prompts/{name}.md` | Repo/app defaults |

The `load_prompt(name)` function walks these directories in order and returns the first non-empty `.md` file it finds. If none exist, it returns the fallback string (empty by default).

Without Obsidian, tier 2 (local skills) becomes the canonical location. The agent reads and writes there via MCP note tools.

### System Prompt Assembly

`core/context.py` uses a similar but slightly different process for the system prompt specifically:

1. Check Obsidian `skills/system.md`, then local `skills/system.md`
2. Fall back to bundle `prompts/system_prompt.md`
3. Fall back to hardcoded: `"You are a companion. Be genuine, direct, and honest."`

After loading the base system prompt, it appends all other `.md` files from whichever skills directory was found, separated by `---` markers. This means skill files like `soul.md`, `tools.md`, and `gift.md` are concatenated into the system prompt automatically.

---

## MCP Note Tools

The MCP memory server (`mcp/memory_server.py`) provides three note tools. They work identically in both modes -- the only difference is where `VAULT_PATH` points.

### read_note

Reads a note by path relative to the vault root (or `~/.atrophy/agents/<name>/` without Obsidian).

```
read_note(path="notes/journal/2026-03-10.md")
```

Returns the file contents or an error if the file doesn't exist or the path escapes the vault boundary.

### write_note

Writes or appends to a note. New notes automatically get YAML frontmatter:

```yaml
---
type: journal
created: 2026-03-10
updated: 2026-03-10
agent: companion
tags: [companion, journal]
---
```

The `type` and `tags` are inferred from the path -- `journal/` paths get type `journal`, `gifts/` get type `gift`, `reflections/` get type `reflection`. The `agent` field is populated if the path contains an agent name.

Appending to an existing note updates the `updated` timestamp in the frontmatter.

### search_notes

Walks the vault directory tree (or local agent directory), searching all `.md` files for a case-insensitive query match. Returns relative paths and context snippets.

Hidden directories (starting with `.`) are skipped. When the vault is an external Obsidian directory, paths resolving into `~/.atrophy/` are also blocked during the walk.

---

## The Security Model

`_safe_vault_path(path)` is the gatekeeper for all note operations. It prevents path traversal attacks:

1. Joins the requested path with `VAULT_PATH` and resolves it to an absolute path via `os.path.realpath()`
2. Checks that the resolved path starts with the resolved vault path -- rejects anything that escapes the vault boundary (e.g. `../../etc/passwd`)
3. When the vault is an external Obsidian directory (not inside `~/.atrophy/`), blocks any resolved path that falls inside `~/.atrophy/` -- prevents symlink escapes from the vault into runtime data
4. When the vault IS inside `~/.atrophy/` (no-Obsidian mode), the `~/.atrophy` block is skipped since the vault and runtime data are colocated

This means:
- The agent can read and write notes within its vault freely
- It cannot escape the vault boundary via `../` or symlinks
- In Obsidian mode, it cannot reach `~/.atrophy/` (memory DB, config, env vars)
- In local mode, it can access its own agent directory but nothing outside it

---

## Configuring OBSIDIAN_VAULT

Three ways, in priority order:

1. **Environment variable**: `export OBSIDIAN_VAULT=/path/to/vault`
2. **Config file**: Set `"OBSIDIAN_VAULT": "/path/to/vault"` in `~/.atrophy/config.json`
3. **Default**: (unset) - you must configure this to enable Obsidian integration

The GUI settings panel also has an Obsidian vault path field under the **PATHS** section.

If the path doesn't exist, `OBSIDIAN_AVAILABLE` is `False` and everything falls back to local mode. No error is raised -- the system simply adapts.

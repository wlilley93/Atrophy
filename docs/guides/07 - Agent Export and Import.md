# Agent Export and Import

Share agents between machines or with other people. Export creates a portable `.agent.zip` archive containing everything needed to recreate the agent. Import installs it into `~/.atrophy/agents/`.

---

## Exporting an Agent

Open the Settings panel (gear icon or Cmd+,). In the **AGENTS** section, each agent has a **Share** button. Click it to export.

The archive is written to `~/Desktop/<display_name>.agent.zip`. If a file with that name already exists, a counter is appended (`oracle_1.agent.zip`, etc.). After writing, Finder opens with the file selected.

### What's Included

| Path in zip | Source | Purpose |
|---|---|---|
| `<name>/data/agent.json` | Agent manifest | Identity, voice config, wake words, heartbeat, display |
| `<name>/prompts/*.md` | Local prompts dir | System prompt, soul, heartbeat fallbacks |
| `<name>/skills/*.md` | Local skills + Obsidian skills | Runtime prompts (system.md, soul.md, tools.md, etc.) |
| `<name>/avatar/source/*` | Avatar source dir | Face image, voice sample -- files needed to regenerate loops |

Skills are collected from both the local agent directory (`~/.atrophy/agents/<name>/skills/`) and the Obsidian workspace (`Agent Workspace/<name>/skills/`), deduplicated by filename. Local files take precedence.

### What's NOT Included

- **Memory database** (`memory.db`) -- conversations, observations, threads, bookmarks are personal and not portable
- **Generated avatar assets** -- video loops, ambient clips, idle videos (large, machine-specific, regenerable from source)
- **API keys** -- the export process strips `elevenlabs_api_key`, `telegram_bot_token`, `telegram_chat_id`, and `api_key` from the manifest before writing
- **Runtime state** -- emotional state, message queue, user status, canvas content
- **Obsidian notes** -- journal entries, reflections, gifts, evolution logs

### Security

The export strips sensitive fields from `agent.json` before archiving. The recipient will need to supply their own API keys. Source avatar files under 50MB are included; anything larger is skipped.

---

## Importing an Agent

In the Settings panel's **AGENTS** section, click **Import Agent**. A file picker opens, filtered to `.zip` files, defaulting to `~/Desktop`.

### What Happens on Import

1. The zip is opened and the top-level directory name is read as the agent slug
2. If the agent already exists at `~/.atrophy/agents/<name>/`, a confirmation dialog asks whether to overwrite
3. If confirmed (or new agent), the zip contents are extracted into `~/.atrophy/agents/<name>/`
4. A macOS notification confirms success

The importer creates the directory structure if needed:

```
~/.atrophy/agents/<name>/
    data/
        agent.json
    prompts/
        system_prompt.md
        soul.md
        ...
    skills/
        system.md
        soul.md
        tools.md
        ...
    avatar/
        source/
            face.png
```

### Merge vs Overwrite

- **New agent** -- everything is created fresh. No merge needed.
- **Existing agent, user confirms** -- all files from the zip overwrite their counterparts. Files that exist locally but are not in the zip are left untouched. This means:
  - Manifest (`agent.json`) is fully replaced
  - Prompts and skills are replaced file-by-file (extra local files remain)
  - Avatar source files are replaced
  - Memory database, runtime state, and Obsidian notes are never touched

If the user declines the overwrite dialog, nothing changes.

### After Import

The imported agent appears in the AGENTS section on next settings refresh. To switch to it:

- Use Cmd+Up / Cmd+Down to cycle agents
- Select it from the tray icon's Agents submenu
- Or set `AGENT=<name>` and restart

The agent will need its own API keys configured (ElevenLabs, Telegram, etc.) since those are stripped during export.

---

## Sharing Between Machines

The workflow:

1. **Machine A**: Settings > AGENTS > Share on the agent you want to transfer
2. Transfer the `.agent.zip` via AirDrop, email, USB, cloud storage -- it's a standard zip
3. **Machine B**: Settings > AGENTS > Import Agent > select the zip
4. **Machine B**: Configure API keys in Settings (ElevenLabs, Telegram, Fal)
5. **Machine B** (optional): Regenerate avatar video loops if you want ambient animation

The agent arrives with its full identity (personality, prompts, skills, voice configuration, wake words) but starts with a clean memory. It's a personality transplant, not a brain transplant.

If both machines have Obsidian with iCloud sync, the skills from the Obsidian workspace will already be present on Machine B. The imported local skills serve as fallbacks.

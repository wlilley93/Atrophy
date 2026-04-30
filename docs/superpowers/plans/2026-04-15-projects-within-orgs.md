# Projects within Organisations

Date: 2026-04-15
Status: Proposal
Builds on: `2026-03-22-agent-organizations-phase1.md`, `2026-03-26-org-management-ui.md`

## Motivating example

Claude Code Game Studios (CCGS) - a repo at `/Users/williamlilley/Projects/Claude Code Projects/Claude-Code-Game-Studios/` that ships 49 agents, 72 skills, 12 hooks, 11 rules, and 39 templates inside a `.claude/` layout. It's a self-contained studio-in-a-repo that Claude Code consumes natively when run with the repo as CWD. Atrophy needs a way to host this without importing 49 shadow agents or forking the org model.

The proposal: stop trying to model the repo as an org type, and instead introduce **Projects** as first-class children of any org. An org owns zero-or-many projects. A project is a repo binding. Atrophy agents remain the "people" of an org; projects are the "workstreams" they operate inside.

---

## Open org type (breaking change, minor)

Current:
```ts
type OrgType = 'government' | 'company' | 'creative' | 'utility';
```

New:
```ts
type OrgType = string;  // free-form, min 1 char, lowercase recommended
```

### Rationale
A game studio isn't any of the four existing types. Neither is a research lab, a law firm, a podcast network, a holding company, a hackerspace. The enum was load-bearing for nothing - no code branches on `OrgType` beyond the dropdown in `CreateOrgModal.svelte`. Freeing the field costs nothing and makes the system honest.

### Migration
- Remove `VALID_ORG_TYPES` guard in `org-manager.ts:26` and `createOrg` validation at `:155`.
- Keep a **suggested types** array in the UI layer only, as dropdown autocomplete hints. Users can pick one or type their own.
- Existing orgs (`defence` = `government`) stay valid as-is.
- Type is now advisory metadata - useful for grouping and icons, never for logic gating.

### Suggested-types list (UI only)
```
government, company, creative, utility, game-studio, research-lab,
law-firm, agency, collective, newsroom, podcast-network, nonprofit,
holding, personal
```
These live in `CreateOrgModal.svelte` as autocomplete suggestions. Adding a new one doesn't require a code change.

### Icon mapping
A small lookup table `orgTypeIcon(type: string)` returns a default icon for known types and a fallback for anything else. Users can override per-org via `OrgManifest.icon` (new optional field).

---

## Project as first-class child

An org can now declare projects:

```ts
interface OrgProject {
  id: string;                    // slug, unique within org
  name: string;                  // display name
  repo_path: string;             // absolute path on disk
  kind: 'external-repo' | 'internal';
  principal_agent?: string;      // which org agent fronts this project
  default_agent?: string;        // agent opened by default when entering
  active: boolean;               // archived projects stay in manifest but don't surface
  settings_policy: 'merge' | 'project-wins' | 'atrophy-wins';
  mcp?: { include?: string[]; exclude?: string[] };
  icon?: string;
  colour?: string;               // accent colour for UI pills
  created: string;
}

interface OrgManifest {
  ...existing,
  icon?: string;                 // org-level icon override
  projects?: OrgProject[];
}
```

Per-project runtime state lives at:
```
~/.atrophy/orgs/<org-slug>/projects/<project-id>/
  ├─ state.json        # last session id, last active.md mtime, last git head
  ├─ memory.db         # project-scoped memory (org-schema.sql)
  └─ .claude-runtime/  # synthesised settings for this project's sessions
      └─ settings.json # merged hooks/permissions written by Atrophy
```

Agent manifest gets an optional project pin:
```ts
interface AgentOrgSection {
  ...existing,
  default_project?: string;      // project id within the org
}
```

Global config gets the currently active project:
```ts
interface Config {
  ...existing,
  ACTIVE_PROJECT_ID?: string;    // format: "<org-slug>:<project-id>"
}
```

---

## Module-by-module changes

### `src/main/org-manager.ts`
Add:
- `addProjectToOrg(orgSlug, { name, repo_path, kind, ... })` - validates path exists, generates slug, validates `.claude/` layout if `external-repo`, appends to manifest.
- `removeProjectFromOrg(orgSlug, projectId)` - unassigns agents pinned to it, removes entry, **does not delete the repo**.
- `listOrgProjects(orgSlug)` and `getProject(orgSlug, projectId)`.
- `setProjectPrincipal(orgSlug, projectId, agentName)` - must be an agent in the org.
- `scanProjectRoster(repo_path)` - reads `.claude/agents/*.md`, returns synthetic tier/role table for display only. No Atrophy agents are created.
- `scanProjectSkills(repo_path)` - reads `.claude/skills/*/SKILL.md` frontmatter.
- `scanProjectHooks(repo_path)` - reads `.claude/settings.json` hooks array.

Remove `VALID_ORG_TYPES` guard. Keep manifest writes atomic (existing pattern).

### `src/main/inference.ts`
Change `agentCwd()` at line 62:
```ts
function agentCwd(): string {
  const cfg = getConfig();
  if (cfg.ACTIVE_PROJECT_ID) {
    const project = resolveProject(cfg.ACTIVE_PROJECT_ID);
    if (project && fs.existsSync(project.repo_path)) return project.repo_path;
  }
  const name = cfg.AGENT_NAME;
  if (name) {
    const dir = getAgentDir(name);
    if (fs.existsSync(dir)) return dir;
  }
  return os.homedir();
}
```
Mirror the same change in `tmux-inference.ts:349` and `tmux-inference.ts:845`. The jsonl-path computation in `findJsonlPath` also needs the project-aware cwd.

### `src/main/mcp-registry.ts`
Extend the per-agent MCP config builder to merge org-level + project-level MCP:
```
final_mcp = union(org.mcp?.include ?? [],
                  project.mcp?.include ?? [],
                  agent.mcp.include)
         - union(agent.mcp.exclude,
                 project.mcp?.exclude ?? [])
```
Still capped by `provisioning-scope` for the agent's tier.

### New: settings merge at `src/main/project-settings.ts`
For project-bound sessions, write a synthesised `settings.json` to `<project-runtime>/settings.json` and pass `--settings <path>` to Claude CLI.

Merge rules per `settings_policy`:
- `project-wins` - project's hooks + permissions take precedence, Atrophy MCP appended
- `atrophy-wins` - Atrophy hooks + permissions win, project hooks ignored (degraded mode - CCGS won't work right)
- `merge` (default) - hooks union, permissions intersect (stricter wins), clear logging

This preserves the existing invariant ("MCP fully owned by Atrophy") for **persona** sessions while letting **project** sessions honour the repo's hooks. No change to the persona path.

### `src/main/context.ts`
Add a project-context injection strategy. If `ACTIVE_PROJECT_ID` is set:
- Read `<repo>/production/session-state/active.md`.
- Parse the `<!-- STATUS -->` block (epic/feature/task).
- Prepend a short structured block to the system prompt: `You are currently operating inside project <name>. Current focus: <status>. Repo root: <path>.`
- Inner-life stays on for persona-bearing orgs. The agent is still Montgomery; Montgomery now knows they're working inside project Meridian.

New function: `buildProjectContext(project: OrgProject): string`.

### `src/main/agent-manager.ts`
Extend `switchAgent(name, projectId?)`:
- If `projectId` is given, validate it belongs to the agent's org (tier-0 exempt).
- Write `ACTIVE_PROJECT_ID` to config.
- Broadcast IPC `project:switched`.
- Rebuild tray menu.

### `src/main/provisioning-scope.ts`
No change. Project context is orthogonal to tier.

### `src/main/create-agent.ts`
Add `--default_project <id>` flag so agents created for a specific project (e.g. a `studio_front_desk`) open there automatically.

### `src/main/config.ts`
Add `ACTIVE_PROJECT_ID` to the config schema, IPC `config:update`, and persistence.

### `src/main/ipc/agents.ts`
Add handlers:
- `project:list` (returns all projects across all orgs, or scoped by org)
- `project:get`
- `project:create`
- `project:update`
- `project:delete`
- `project:switch` (sets `ACTIVE_PROJECT_ID`)
- `project:scan` (roster/skills/hooks summary for display)

### `src/main/ipc/window.ts`
Add `window:open-project` that sets the project and focuses the main window.

### `src/main/channels/cron/runner.ts`
Extend job manifest to accept optional `project: "<project-id>"`. When present, the cron spawn runs with the project's CWD + merged settings.

### `src/preload/index.ts`
Expose the new IPC surface via `contextBridge`.

---

## UI surfacing - how projects show up everywhere

The guiding principle: **a project is always rendered as a child of an org, never at the top level**. The user always sees `Org → Project → Agent` as the mental model. Two exceptions: the global recent-projects list and the command palette, which are flat for speed.

### 1. Tray menu
Current tray menu shows: current agent name, agent list (cycle), settings, quit.

New structure:
```
◉ General Montgomery                    (current agent, bold)
  Defence Bureau › Meridian             (org › project breadcrumb, muted)
────────────────────────────────────────
Switch Agent                            ▸  [submenu: all agents grouped by org]
Switch Project (Defence)                ▸  [submenu: projects in current org]
Recent Projects                         ▸  [submenu: last 5 across all orgs]
────────────────────────────────────────
No Project (persona only)                   [radio option to clear ACTIVE_PROJECT_ID]
────────────────────────────────────────
Settings...
Quit Atrophy
```

- The "Switch Project" submenu is scoped to the current agent's org.
- "Recent Projects" is flat and cross-org for fast task-switching.
- "No Project" is a first-class choice so the user can drop out of project mode without picking a different agent.
- Selecting a project from a different org's list auto-switches agent to that project's principal.

### 2. Window header / chrome
Current: agent name top-left, orb avatar, window controls.

New: under the agent name, a **project pill**:
```
╔═══════════════════════════════════════╗
║  General Montgomery                   ║
║  📁 Defence › Meridian  ⬇             ║  ← project pill, click to dropdown
║                                       ║
║  [orb]                                ║
╚═══════════════════════════════════════╝
```

- Pill is clickable → opens a lightweight dropdown with: current project (pinned), other projects in the org, recent cross-org projects, "No Project" option, "Manage projects…" link to settings.
- Pill shows the project's accent colour as a left border.
- When no project is active, pill collapses to a small `+ Add Project` affordance that's easy to ignore but discoverable.
- Pill disappears entirely for agents whose org has zero projects (keeps persona-only orgs clean).

### 3. Indicator badges on the pill
The pill can carry small right-side badges:
- 🔴 git has uncommitted changes
- 🟡 active sprint behind schedule (from `production/sprint-*.md` checkbox ratio)
- ✓ gate-check passing
- 🔔 new playtest report in `production/playtest/`

These read from disk lazily (every 30s or on focus) and degrade silently if files don't exist. Keeps CCGS-style projects feeling "live" without polling hard.

### 4. Global command palette (new, Cmd+K)
A new lightweight overlay (reuse `SystemMap.svelte` pattern) triggered by `Cmd+K`:
```
┌────────────────────────────────────────┐
│  🔍  Jump to...                        │
├────────────────────────────────────────┤
│  Agents                                │
│    General Montgomery    [Defence]    │
│    Xan                   [System]     │
│    Companion             [Personal]   │
│                                        │
│  Projects                              │
│    Meridian              [Defence]    │
│    CCGS Game             [Studios]    │
│    Atrophy itself        [Atrophy]    │
│                                        │
│  Slash commands (in CCGS Game)         │
│    /brainstorm                        │
│    /design-system                     │
│    /team-combat                       │
└────────────────────────────────────────┘
```
- Fuzzy-matched across agents, projects, and (if a project is active) its slash commands.
- Enter selects. Arrows navigate. Esc dismisses.
- Switching agent/project here is non-destructive to the current transcript - user returns to it by selecting the same again.

### 5. Settings → Agents tab → Org tree
Current: flat list of agents under each org.

New: each org node is expandable to show two children sections:
```
▼ Defence Bureau (government)
  ▼ Agents
    • General Montgomery      tier 1, Secretary of Defence
    • Librarian               tier 2, Research
  ▼ Projects
    • Meridian                external-repo, principal: Montgomery
    • OSINT Digest            internal
  + Add project
  + Add agent
```
- Projects section is collapsible (default collapsed for persona-only orgs).
- Click a project → opens `ProjectDetail.svelte` in the right pane.
- Drag-drop reorder within each section (v2).

### 6. New: `ProjectDetail.svelte` pane
Replaces the `AgentDetail` pane when a project is selected in the tree.

Sections (top to bottom):
1. **Header** - name, org, kind (external/internal), repo path (copyable), status pill.
2. **Quick actions** - "Open in session" (big button), "Open repo in Finder", "Open in VS Code".
3. **Principal agent** - dropdown from org roster. Changing this is a structural decision so show a confirmation.
4. **Repo summary** - last git commit, branch, uncommitted file count, latest `active.md` timestamp.
5. **.claude/ layout** (for `external-repo`) - counts: X agents, Y skills, Z hooks, N rules. Each click-to-expand list.
6. **Settings policy** - `merge | project-wins | atrophy-wins` radio with inline explanation of consequences.
7. **MCP** - include/exclude lists, merged view shows final set for this project.
8. **Workflow snapshot** (collapsible, v1 read-only) - pulls from `production/` tree. Current sprint, active epic/feature/task, story counts by status, recent gate-check results.
9. **Advanced** - default agent, accent colour, icon, archive toggle.

### 7. New: `CreateProjectModal.svelte`
Fields (in order of disclosure):
- Name (required, free text)
- Repo path (required, folder picker, validated to exist)
- Detected layout (read-only, fills in after path picked: "detected .claude/ - 12 agents, 34 skills, 5 hooks" or "no .claude/ found - internal project")
- Default agent (dropdown from org roster)
- Settings policy (radio, default `merge`)
- Optional: icon, accent colour, description

Submit → calls `project:create`, refreshes tree, optionally switches to the new project.

### 8. New top-level tab: **Projects** (v2, optional)
When project count across all orgs exceeds a threshold (e.g. 3), a dedicated "Projects" tab appears in settings. Flat list with filters (by org, by kind, by active status), quick-switch, bulk actions. Think of it as the "workspaces" view for a power user running a dozen repos.

Until then, projects live inside the Agents tab org tree.

### 9. Telegram surface
Telegram daemon per agent (`src/main/channels/telegram/daemon.ts`) gets a subtle extension: when the user DMs an agent who's in a project, the daemon can include the project context in the Envelope so inference picks it up. User-facing signal: the agent's name in the Telegram group is suffixed, e.g. "Montgomery (Meridian)" when working in a project. Command `/project <name>` in Telegram switches the agent's active project for that chat.

Optional v2: per-chat project binding (conversation A is Meridian, conversation B is free-form).

### 10. Status line / menubar (v2)
Atrophy doesn't host Claude Code's `statusline.sh` natively. Instead, render a 1-line status in the window footer when a project is active:
```
Meridian · Epic: Ingestion · Feature: OSINT Harvest · Task: BBC RSS integration · 43% ctx
```
Read from `active.md`'s `<!-- STATUS -->` block + Atrophy's own token counter.

### 11. `Transcript.svelte` - subagent tree panel
When inference emits a `Task` tool call, render a collapsible tree inline in the transcript:
```
▼ Task: /team-combat [running]
  ├─ game-designer        [completed] 3.2k tokens
  ├─ gameplay-programmer  [running]
  ├─ ai-programmer        [queued]
  └─ technical-artist     [queued]
```
Click a node → expands to show that subagent's output inline (collapsible again). Click a subagent name → opens its source markdown for inspection. This turns CCGS's `team-*` skills from black boxes into observable orchestrations.

### 12. Input bar - slash-command picker
When a project is active, typing `/` in the input bar opens a filtered menu from `<repo>/.claude/skills/*/SKILL.md` frontmatter:
- Grouped by skill-family prefix (design-*, team-*, qa-*, release-*)
- Shows description and required model
- Arrow-keys to navigate, Enter to insert
- Falls back to current behaviour when no project is active

### 13. System map overlay (`SystemMap.svelte`)
Existing overlay shows the switchboard topology. Extend nodes: orgs get a project-count badge; clicking an org expands to show projects as sub-nodes. A project node shows edges to its principal agent and (if cron jobs are bound) its scheduled runs. Gives a single visual snapshot of "what workstreams are live in this Atrophy instance".

### 14. Tray icon colour
Current tray icon reflects the current agent. Extension: when a project is active, the tray icon gets a thin coloured border (the project's accent colour) so at-a-glance the user sees "I'm in a project" without opening the menu. No border when persona-only.

### 15. Keyboard shortcuts
- `Cmd+Shift+Space` - toggle window (unchanged)
- `Cmd+Shift+[/]` - cycle agents (unchanged)
- `Cmd+Shift+Alt+[/]` - cycle projects within the current agent's org (new)
- `Cmd+K` - global palette (new)
- `Cmd+Shift+P` - "No Project" toggle (new)

### 16. First-time surfacing
When a user has zero projects, nothing new shows. The moment they add one, the pill appears, the Cmd+K palette lights up a new section, and the settings tree sprouts a Projects node. Progressive disclosure - persona-only users never see the complexity.

---

## Switchboard / federation (minor)

- Switchboard addresses agents, not projects. No change.
- Cron jobs get optional `project: "<id>"` field.
- Federation links get optional `project` field so cross-instance queries carry project context.

---

## Project memory

Each project gets a SQLite DB at `~/.atrophy/orgs/<org>/projects/<id>/memory.db` using `org-schema.sql`. The `memory` MCP server gets a scope flag: inside a project-bound session, reads prefer project memory, fall through to org memory, then agent memory. Writes go to the session's current scope. Persona-only sessions skip project memory entirely.

---

## Migration

Zero breaking changes to existing installs.
- Existing `OrgManifest`s have no `projects` field → reads as `undefined`.
- Existing `OrgType` values (`government` etc) remain valid strings under the open type.
- Existing agents have no `default_project` → unchanged behaviour.

One-shot optional migration helper: scan configured cron scripts and agent manifests for repo paths, offer to register them as projects under their owning org.

---

## Build order

1. **Open `OrgType`** - remove enum guard, update UI dropdown to autocomplete with suggested-types list. Add `icon` field.
2. **Schema + CRUD** - `OrgProject` type, `addProjectToOrg`, `removeProjectFromOrg`, `listOrgProjects`, `getProject`, `setProjectPrincipal`. Manifest migration-safe.
3. **Config + CWD override** - `ACTIVE_PROJECT_ID` in config, `agentCwd()` change in inference.ts and tmux-inference.ts, IPC broadcasts.
4. **Settings merge** - `src/main/project-settings.ts`, `.claude-runtime/settings.json` writer, `--settings` flag pass-through on inference spawn.
5. **Tray menu** - add Switch Project submenu, Recent Projects, No Project option.
6. **Window pill** - minimal `ProjectPill.svelte` component under AgentName.
7. **Settings tree** - `OrgTree.svelte` gets Projects section under each org node, `ProjectDetail.svelte` pane, `CreateProjectModal.svelte`.
8. **Scan helpers** - `scanProjectRoster`, `scanProjectSkills`, `scanProjectHooks`. Drives the detail pane.
9. **Slash-command picker** - `InputBar.svelte` reads from scanned skills when project active.
10. **Workflow snapshot** - reads `production/` tree, renders in ProjectDetail and window footer.
11. **Task-tree panel** - `Transcript.svelte` parses `Task` tool_use events into a tree.
12. **Per-skill model routing** - intercept slash invocations, pass model flag from skill frontmatter.
13. **Project memory scoping** - MCP memory server changes.
14. **Cmd+K palette** - global fuzzy-finder overlay.
15. **Telegram project suffix + /project command** - daemon extension.
16. **System map integration** - project nodes in topology.
17. **Status line footer** - read active.md STATUS block.

Steps 1-4 are enough to spike CCGS end-to-end: open a new org called "Studios" with any type (e.g. `game-studio`), attach CCGS as its first project, wire a minimal principal agent, and the repo's skills/hooks/rules activate because Claude CLI now runs with the right CWD and merged settings.

Steps 5-10 deliver the UX that makes projects feel native.

Steps 11-17 are polish and observability - worth doing but not load-bearing.

---

## What I'd do first

1. Land step 1 (open org type) as a standalone micro-PR. It's trivial and unblocks honest typing.
2. Land steps 2-4 behind a feature flag (`ATROPHY_PROJECTS=1`).
3. Create a `studios` org with `type: "game-studio"`, add CCGS as its first project, wire `studio_front_desk` (tier 1) as principal.
4. Prove end-to-end that opening the project switches CWD, the repo's hooks fire on Bash/Write, `/brainstorm` works, `Task`-spawned subagents work.
5. Only then commit to the UI lift (steps 5-10).

Anything past step 10 is worth doing when a second or third project is onboarded and the UX gaps start hurting. Don't pre-build for a future that might not arrive.

---

## Open questions

- **Project archival vs deletion** - should archived projects stay in the manifest (hidden from UI) or move to a separate `archived_projects` array? Probably hidden with an `active: false` flag, revealed by a "Show archived" toggle.
- **Multi-project sessions** - does a single Claude CLI session need to span two projects? Currently no, but a future "cross-project research" skill might want this. Defer until demanded.
- **Git branch awareness** - should switching Atrophy projects ever imply a git branch switch? No. The user owns branch state; Atrophy is a spectator.
- **Project templates** - should Atrophy ship template projects (e.g. "Empty Game Studio", "Research Lab")? Maybe v3. Not worth it until project count across users justifies it.
- **Per-project Telegram bot?** - probably not. Agents own bots, projects don't. A project just changes what the agent is doing, not how people reach them.
- **Open type risk** - with a free-form string, typos will proliferate (`game-studio` vs `gamestudio` vs `Game Studio`). Mitigate with autocomplete, casing normalisation on save, and a one-time migration to consolidate duplicates if it becomes a problem.

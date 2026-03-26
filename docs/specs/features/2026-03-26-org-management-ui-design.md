# Org Management UI - Design Spec

**Date:** 2026-03-26
**Status:** Draft

## Summary

Add a dedicated **Agents tab** to Settings that provides full visual management of organisations, agents, and their jobs. Replaces the inline agent list in SettingsTab with a proper hierarchy view.

## Layout

Split-panel design inside the existing Settings modal:

```
+--------------------------------------------------+
| Settings | Agents | Usage | Activity | Jobs | ... |
+--------------------------------------------------+
| LEFT PANEL (300px)    | RIGHT PANEL (flex)        |
|                       |                           |
| [+ New Org]           | DETAIL CARD               |
|                       |                           |
| v Defence Org         | Agent: General Montgomery  |
|   > Gen Montgomery *  | Role: Secretary of Defence |
|   v Tier 2 (11)       | Tier: 1                   |
|     > Red Team        | [Identity] [Jobs] [MCP]   |
|     > SIGINT Analyst   |                           |
|     > Librarian        | --- Identity Tab ---      |
|     > ...              | Display Name: [________]  |
|   v Tier 3 (10)       | Role: [________________]  |
|     > Russia Amb       | Description: [_________]  |
|     > USA Amb          |                           |
|     > ...              | System Prompt:            |
|                       | [                    ]    |
| --- Standalone ---     | [    textarea        ]    |
| > Xan *               | [                    ]    |
| > Companion            |                           |
| > Mirror               | Soul Document:            |
|                       | [    textarea        ]    |
+--------------------------------------------------+
```

### Left Panel - Org Tree

- **Header**: "Organisations" with [+ New Org] button
- **Org nodes**: collapsible, show org name + agent count
  - Agents grouped by tier, each tier collapsible
  - Active agent marked with indicator
  - Each agent node: display name, role badge, enabled/disabled toggle
- **Standalone section**: agents with no `org` field, flat list
- **Footer**: [+ Quick Add Agent] button

### Right Panel - Detail Card

Shows when an agent or org is selected in the tree.

**When an org is selected:**
- Org name, slug, type, purpose, principal
- Stats: agent count by tier, total jobs, active connections
- [Edit] [Dissolve] buttons
- Org-wide job list

**When an agent is selected - three sub-tabs:**

#### Identity Tab
- Display name, role, description (text fields)
- Org assignment dropdown (move between orgs or standalone)
- Tier selector (1/2/3)
- Reports-to dropdown (agents in same org, tier < current)
- `can_address_user` and `can_provision` toggles
- System prompt textarea (loads from prompts/ directory)
- Soul document textarea (loads from prompts/soul.md)
- Opening line textarea
- Wake words list

#### Jobs Tab
- List of jobs from agent manifest `jobs` section
- Each job: name, cron/interval, last run status, next run time
- [Run Now] [Edit Schedule] [Disable/Enable] per job
- [+ Add Job] button
- Run history (last 10 runs) with expandable stdout/stderr

#### MCP Tab
- List of MCP servers: included, excluded, custom
- Toggle switches for each server (include/exclude)
- Server details: description, capabilities, env vars needed
- [+ Add Custom Server] button

#### Router Tab (collapsed by default)
- `accept_from` list editor
- `reject_from` list editor
- `max_queue_depth` number input
- `system_access` and `can_address_agents` toggles

## Agent Creation

### Quick-create (for org agents)
Inline form in the detail panel when [+ Quick Add Agent] is clicked:
- Name (auto-slugified)
- Display name
- Role
- Org assignment
- Tier
- Reports-to
- Specialism (for research fellows)

Creates the agent with default prompt templates for the org/tier. No wizard.

### Full wizard (for standalone agents)
Opens the existing SetupWizard flow when creating a standalone agent or a tier-1 org agent with `can_address_user: true`.

## Org Creation

Simple form:
- Name
- Slug (auto-generated from name)
- Type (government/company/creative/utility dropdown)
- Purpose (textarea)
- Principal agent (dropdown of existing agents, or "create new")

## Deletion

### Agent deletion
- Confirmation dialog with agent name
- Option to reassign jobs to another agent
- Removes: agent directory, switchboard registration, cron jobs, Telegram poller
- Does NOT delete the memory DB (preserved for history)

### Org dissolution
- Confirmation dialog
- Agents become standalone (org field cleared)
- Jobs remain on their agents

## IPC Surface

All handlers already exist in `ipc/system.ts` and `ipc/agents.ts`:

| Channel | Status | Purpose |
|---------|--------|---------|
| `org:list` | Exists | List all orgs |
| `org:detail` | Exists | Get org with roster |
| `org:create` | Exists | Create new org |
| `org:dissolve` | Exists | Remove org |
| `org:addAgent` | Exists | Add agent to org |
| `org:removeAgent` | Exists | Remove agent from org |
| `agent:list` | Exists (UI-filtered) | List UI-visible agents |
| `agent:listFull` | Exists (UI-filtered) | List with details |
| `agent:getState` | Exists | Get enabled/muted state |
| `agent:setState` | Exists | Set enabled/muted |
| `cron:schedule` | Exists | Get all scheduled jobs |
| `cron:runNow` | Exists | Trigger job immediately |

**New IPC needed:**

| Channel | Purpose |
|---------|---------|
| `agent:listAll` | List ALL agents (including tier 2/3) for settings |
| `agent:getManifest` | Read full agent.json for editing |
| `agent:updateManifest` | Write agent.json fields |
| `agent:getPrompt` | Read system prompt / soul doc |
| `agent:updatePrompt` | Write system prompt / soul doc |
| `agent:create` | Create agent (quick-create path) |
| `agent:delete` | Delete agent and clean up |
| `org:update` | Edit org metadata |
| `cron:editJob` | Edit job schedule/config |
| `cron:addJob` | Add new job to agent |
| `cron:deleteJob` | Remove job from agent |

## Components

### New files
- `src/renderer/components/settings/AgentsTab.svelte` - main split-panel container
- `src/renderer/components/settings/OrgTree.svelte` - left panel tree
- `src/renderer/components/settings/AgentDetail.svelte` - right panel detail card
- `src/renderer/components/settings/OrgDetail.svelte` - right panel org view
- `src/renderer/components/settings/AgentCreateForm.svelte` - quick-create inline form
- `src/renderer/components/settings/JobEditor.svelte` - job list + edit within detail card

### Modified files
- `Settings.svelte` - add Agents tab, remove agent list from SettingsTab
- `SettingsTab.svelte` - remove agent list section
- `src/main/ipc/agents.ts` - new handlers
- `src/main/ipc/system.ts` - new cron handlers
- `src/preload/index.ts` - new API methods

## Data Flow

1. `AgentsTab` mounts, calls `api.listOrgs()` + `api.listAllAgents()` + `api.getSchedule()`
2. Builds tree structure: orgs with nested agents by tier, standalone agents separate
3. User clicks agent -> `api.getManifest(name)` + `api.getPrompt(name, 'system')` loaded into detail panel
4. User edits fields -> local state updated, [Save] button activates
5. Save calls `api.updateManifest(name, changes)` + `api.updatePrompt(name, type, content)`
6. Tree refreshes from fresh data after save

## Styling

Follows existing Settings panel dark theme:
- Tree nodes: `rgba(255,255,255,0.04)` background on hover, accent border on selected
- Tier badges: small colored pills (tier 1 = blue, tier 2 = green, tier 3 = grey)
- Collapsible sections: chevron icon, smooth height transition
- Detail panel: same form styling as SettingsTab (input fields, textareas, toggles)
- Org header: slightly larger text, org type icon

## Out of Scope (future)
- AI-assisted prompt generation from structured fields
- Drag-and-drop reordering in the tree
- Bulk operations on multiple agents
- Visual org chart (non-tree) layout
- Real-time status indicators per agent (active inference, etc.)

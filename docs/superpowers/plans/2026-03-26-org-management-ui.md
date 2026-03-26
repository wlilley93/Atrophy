# Org Management UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a split-panel Agents tab to Settings for visual org/agent/job management with full CRUD.

**Architecture:** New `AgentsTab.svelte` with a left-side collapsible org tree (`OrgTree.svelte`) and a right-side detail panel that renders `AgentDetail.svelte`, `OrgDetail.svelte`, or `AgentCreateForm.svelte` depending on selection. New IPC handlers for agent manifest/prompt read-write and job CRUD. Existing `org:*` and `cron:*` IPC is reused.

**Tech Stack:** Svelte 5 (runes mode), TypeScript, Electron IPC, better-sqlite3

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `src/renderer/components/settings/AgentsTab.svelte` | Split-panel container, data loading, selection state |
| `src/renderer/components/settings/OrgTree.svelte` | Left panel: collapsible org/agent tree with tier grouping |
| `src/renderer/components/settings/AgentDetail.svelte` | Right panel: agent identity, prompts, jobs, MCP, router tabs |
| `src/renderer/components/settings/OrgDetail.svelte` | Right panel: org info, stats, edit form, agent list |
| `src/renderer/components/settings/AgentCreateForm.svelte` | Quick-create form for headless org agents |
| `src/renderer/components/settings/JobEditor.svelte` | Job list with run/edit/add/delete inside AgentDetail |

### Modified files
| File | Changes |
|------|---------|
| `src/main/ipc/agents.ts` | Add `agent:listAll`, `agent:getManifest`, `agent:updateManifest`, `agent:getPrompt`, `agent:updatePrompt`, `agent:create`, `agent:delete` |
| `src/main/ipc/system.ts` | Add `org:update`, `cron:editJob`, `cron:addJob`, `cron:deleteJob` |
| `src/preload/index.ts` | Add new API methods to interface + implementation |
| `src/renderer/components/Settings.svelte` | Add Agents tab, import AgentsTab, wire into switchTab |
| `src/renderer/components/settings/SettingsTab.svelte` | Remove agent list section (lines ~190-293) |
| `src/main/agent-manager.ts` | Add `deleteAgent()` function |

---

## Task 1: New IPC Handlers - Agent Manifest & Prompt CRUD

**Files:**
- Modify: `src/main/ipc/agents.ts`
- Modify: `src/main/agent-manager.ts`
- Modify: `src/main/ipc/system.ts`

- [ ] **Step 1: Add `agent:listAll` handler**

In `src/main/ipc/agents.ts`, after the existing `agent:listFull` handler, add:

```typescript
  ipcMain.handle('agent:listAll', () => {
    return discoverAgents();
  });
```

Update the import at the top to include `discoverAgents`:

```typescript
import {
  discoverAgents, discoverUiAgents, cycleAgent, getAgentState, setAgentState,
  setLastActiveAgent, suspendAgentSession, resumeAgentSession,
  writeAskResponse, findManifest,
} from '../agent-manager';
```

- [ ] **Step 2: Add `agent:getManifest` and `agent:updateManifest` handlers**

In `src/main/ipc/agents.ts`:

```typescript
  const AGENT_RE = /^[a-zA-Z0-9_-]+$/;

  ipcMain.handle('agent:getManifest', (_event, name: string) => {
    if (!AGENT_RE.test(name)) throw new Error('Invalid agent name');
    return findManifest(name) || {};
  });

  ipcMain.handle('agent:updateManifest', (_event, name: string, updates: Record<string, unknown>) => {
    if (!AGENT_RE.test(name)) throw new Error('Invalid agent name');
    saveAgentConfig(name, updates);
  });
```

Add `saveAgentConfig` to the config import:

```typescript
import { getConfig, saveAgentConfig, saveUserConfig, saveEnvVar } from '../config';
```

- [ ] **Step 3: Add `agent:getPrompt` and `agent:updatePrompt` handlers**

In `src/main/ipc/agents.ts`:

```typescript
  ipcMain.handle('agent:getPrompt', (_event, name: string, promptName: string) => {
    if (!AGENT_RE.test(name)) throw new Error('Invalid agent name');
    const config = getConfig();
    const originalAgent = config.AGENT_NAME;
    config.reloadForAgent(name);
    const content = loadPrompt(promptName, '');
    config.reloadForAgent(originalAgent);
    return content;
  });

  ipcMain.handle('agent:updatePrompt', (_event, name: string, promptName: string, content: string) => {
    if (!AGENT_RE.test(name)) throw new Error('Invalid agent name');
    const promptPath = path.join(USER_DATA, 'agents', name, 'prompts', `${promptName}.md`);
    fs.mkdirSync(path.dirname(promptPath), { recursive: true });
    fs.writeFileSync(promptPath, content, 'utf-8');
  });
```

Add imports at top:

```typescript
import * as fs from 'fs';
import { loadPrompt } from '../prompts';
import { USER_DATA } from '../config';
```

- [ ] **Step 4: Add `agent:create` (quick-create) handler**

In `src/main/ipc/agents.ts`:

```typescript
  ipcMain.handle('agent:create', async (_event, opts: {
    name: string;
    displayName: string;
    role: string;
    orgSlug?: string;
    tier?: number;
    reportsTo?: string;
    specialism?: string;
  }) => {
    if (!AGENT_RE.test(opts.name)) throw new Error('Invalid agent name');
    const { createAgent } = await import('../create-agent');
    const manifest = await createAgent({
      name: opts.name,
      displayName: opts.displayName,
      role: opts.role,
      orgContext: opts.orgSlug ? {
        slug: opts.orgSlug,
        tier: opts.tier || 2,
        role: opts.role,
        reportsTo: opts.reportsTo || null,
        specialism: opts.specialism,
      } : undefined,
    });
    return manifest;
  });
```

- [ ] **Step 5: Add `deleteAgent` to agent-manager.ts and IPC handler**

In `src/main/agent-manager.ts`, add after the `getAgentRoster` function:

```typescript
export function deleteAgent(name: string): void {
  const agentDir = path.join(USER_DATA, 'agents', name);
  if (!fs.existsSync(agentDir)) throw new Error(`Agent '${name}' not found`);

  // Preserve memory DB but remove everything else
  const dataDir = path.join(agentDir, 'data');
  const dbPath = path.join(dataDir, 'memory.db');
  const dbBackup = path.join(dataDir, 'memory.db.preserved');

  // Backup the DB if it exists
  if (fs.existsSync(dbPath)) {
    fs.renameSync(dbPath, dbBackup);
  }

  // Remove agent directory contents except the preserved DB
  const entries = fs.readdirSync(agentDir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(agentDir, entry.name);
    if (entry.name === 'data') {
      // Clear data dir but keep preserved DB
      const dataEntries = fs.readdirSync(dataDir);
      for (const de of dataEntries) {
        if (de === 'memory.db.preserved') continue;
        const dp = path.join(dataDir, de);
        fs.rmSync(dp, { recursive: true, force: true });
      }
    } else {
      fs.rmSync(fullPath, { recursive: true, force: true });
    }
  }

  // Restore DB to original name
  if (fs.existsSync(dbBackup)) {
    fs.renameSync(dbBackup, dbPath);
  }
}
```

In `src/main/ipc/agents.ts`:

```typescript
  ipcMain.handle('agent:delete', (_event, name: string) => {
    if (!AGENT_RE.test(name)) throw new Error('Invalid agent name');
    const config = getConfig();
    if (name === config.AGENT_NAME) throw new Error('Cannot delete the active agent');
    deleteAgent(name);
  });
```

Add `deleteAgent` to the agent-manager import.

- [ ] **Step 6: Add `org:update`, `cron:addJob`, `cron:editJob`, `cron:deleteJob` handlers**

In `src/main/ipc/system.ts`, after the existing `org:removeAgent` handler:

```typescript
  ipcMain.handle('org:update', (_event, slug: string, updates: { name?: string; purpose?: string }) => {
    const { updateOrg } = require('../org-manager');
    return updateOrg(slug, updates);
  });
```

For cron job CRUD, after the existing `cron:reset` handler:

```typescript
  ipcMain.handle('cron:addJob', (_event, agentName: string, jobName: string, config: { schedule: string; script: string; description?: string }) => {
    if (!NAME_RE.test(agentName) || !NAME_RE.test(jobName)) return;
    const agentConfig = getConfig();
    agentConfig.reloadForAgent(agentName);
    const manifestPath = path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json');
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    if (!manifest.jobs) manifest.jobs = {};
    manifest.jobs[jobName] = config;
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
    cronScheduler.registerAgent(agentName, manifest);
  });

  ipcMain.handle('cron:editJob', (_event, agentName: string, jobName: string, updates: Record<string, unknown>) => {
    if (!NAME_RE.test(agentName) || !NAME_RE.test(jobName)) return;
    const manifestPath = path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json');
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    if (!manifest.jobs?.[jobName]) return;
    Object.assign(manifest.jobs[jobName], updates);
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
    cronScheduler.registerAgent(agentName, manifest);
  });

  ipcMain.handle('cron:deleteJob', (_event, agentName: string, jobName: string) => {
    if (!NAME_RE.test(agentName) || !NAME_RE.test(jobName)) return;
    const manifestPath = path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json');
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    if (manifest.jobs) delete manifest.jobs[jobName];
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
    cronScheduler.unregisterAgent(agentName);
    cronScheduler.registerAgent(agentName, manifest);
  });
```

Add `USER_DATA` and `fs` imports if not present.

- [ ] **Step 7: Type-check and commit**

```bash
npx tsc --noEmit
git add src/main/ipc/agents.ts src/main/ipc/system.ts src/main/agent-manager.ts
git commit -m "feat(ipc): add agent/org/job CRUD handlers for settings UI"
```

---

## Task 2: Preload API Surface

**Files:**
- Modify: `src/preload/index.ts`

- [ ] **Step 1: Add new methods to `AtrophyAPI` interface**

After the existing `updateAgentConfig` line in the interface, add:

```typescript
  // Agent management (settings)
  listAllAgents: () => Promise<{ name: string; display_name: string; description: string; role: string; tier: number }[]>;
  getAgentManifest: (name: string) => Promise<Record<string, unknown>>;
  updateAgentManifest: (name: string, updates: Record<string, unknown>) => Promise<void>;
  getAgentPrompt: (name: string, promptName: string) => Promise<string>;
  updateAgentPrompt: (name: string, promptName: string, content: string) => Promise<void>;
  createAgent: (opts: { name: string; displayName: string; role: string; orgSlug?: string; tier?: number; reportsTo?: string; specialism?: string }) => Promise<Record<string, unknown>>;
  deleteAgent: (name: string) => Promise<void>;

  // Org management (settings)
  updateOrg: (slug: string, updates: { name?: string; purpose?: string }) => Promise<void>;

  // Job CRUD (settings)
  addJob: (agentName: string, jobName: string, config: { schedule: string; script: string; description?: string }) => Promise<void>;
  editJob: (agentName: string, jobName: string, updates: Record<string, unknown>) => Promise<void>;
  deleteJob: (agentName: string, jobName: string) => Promise<void>;
```

- [ ] **Step 2: Add implementations in the contextBridge object**

After the existing `updateAgentConfig` implementation:

```typescript
  // Agent management (settings)
  listAllAgents: () => ipcRenderer.invoke('agent:listAll'),
  getAgentManifest: (name) => ipcRenderer.invoke('agent:getManifest', name),
  updateAgentManifest: (name, updates) => ipcRenderer.invoke('agent:updateManifest', name, updates),
  getAgentPrompt: (name, promptName) => ipcRenderer.invoke('agent:getPrompt', name, promptName),
  updateAgentPrompt: (name, promptName, content) => ipcRenderer.invoke('agent:updatePrompt', name, promptName, content),
  createAgent: (opts) => ipcRenderer.invoke('agent:create', opts),
  deleteAgent: (name) => ipcRenderer.invoke('agent:delete', name),

  // Org management (settings)
  updateOrg: (slug, updates) => ipcRenderer.invoke('org:update', slug, updates),

  // Job CRUD (settings)
  addJob: (agentName, jobName, config) => ipcRenderer.invoke('cron:addJob', agentName, jobName, config),
  editJob: (agentName, jobName, updates) => ipcRenderer.invoke('cron:editJob', agentName, jobName, updates),
  deleteJob: (agentName, jobName) => ipcRenderer.invoke('cron:deleteJob', agentName, jobName),
```

- [ ] **Step 3: Type-check and commit**

```bash
npx tsc --noEmit
git add src/preload/index.ts
git commit -m "feat(preload): add agent/org/job management API surface"
```

---

## Task 3: OrgTree Component (Left Panel)

**Files:**
- Create: `src/renderer/components/settings/OrgTree.svelte`

- [ ] **Step 1: Create OrgTree.svelte**

This component receives org data and agent data as props, renders a collapsible tree, and emits selection events.

```svelte
<script lang="ts">
  import { api } from '../../api';
  import { agents } from '../../stores/agents.svelte';

  interface OrgNode {
    slug: string;
    name: string;
    type: string;
    agents: AgentNode[];
  }

  interface AgentNode {
    name: string;
    display_name: string;
    role: string;
    tier: number;
    orgSlug: string | null;
    enabled: boolean;
  }

  interface Props {
    orgs: OrgNode[];
    standalone: AgentNode[];
    selectedId: string | null;
    selectedType: 'agent' | 'org' | 'create' | null;
    onSelect: (id: string, type: 'agent' | 'org') => void;
    onCreateAgent: () => void;
    onCreateOrg: () => void;
  }

  let { orgs, standalone, selectedId, selectedType, onSelect, onCreateAgent, onCreateOrg }: Props = $props();

  // Collapsible state
  let expandedOrgs = $state<Set<string>>(new Set());
  let expandedTiers = $state<Set<string>>(new Set());

  function toggleOrg(slug: string) {
    const next = new Set(expandedOrgs);
    if (next.has(slug)) next.delete(slug); else next.add(slug);
    expandedOrgs = next;
  }

  function toggleTier(key: string) {
    const next = new Set(expandedTiers);
    if (next.has(key)) next.delete(key); else next.add(key);
    expandedTiers = next;
  }

  function tierLabel(tier: number): string {
    if (tier <= 1) return 'Leadership';
    if (tier === 2) return 'Specialists';
    return 'Tier ' + tier;
  }

  function tierColor(tier: number): string {
    if (tier <= 1) return '#4a9eff';
    if (tier === 2) return '#4CAF50';
    return '#888';
  }

  // Group agents by tier within each org
  function groupByTier(agentList: AgentNode[]): Map<number, AgentNode[]> {
    const groups = new Map<number, AgentNode[]>();
    for (const a of agentList) {
      const tier = a.tier || 1;
      if (!groups.has(tier)) groups.set(tier, []);
      groups.get(tier)!.push(a);
    }
    return new Map([...groups.entries()].sort((a, b) => a[0] - b[0]));
  }

  // Expand all orgs on first render
  $effect(() => {
    if (orgs.length > 0 && expandedOrgs.size === 0) {
      expandedOrgs = new Set(orgs.map(o => o.slug));
      // Also expand all tiers
      const tierKeys = new Set<string>();
      for (const org of orgs) {
        const groups = groupByTier(org.agents);
        for (const tier of groups.keys()) {
          tierKeys.add(`${org.slug}:${tier}`);
        }
      }
      expandedTiers = tierKeys;
    }
  });
</script>

<div class="org-tree">
  <div class="tree-header">
    <span class="tree-title">Organisations</span>
    <button class="tree-action" onclick={onCreateOrg} title="New Organisation">+</button>
  </div>

  {#each orgs as org}
    <div class="org-node">
      <button
        class="tree-row org-row"
        class:selected={selectedId === org.slug && selectedType === 'org'}
        onclick={() => onSelect(org.slug, 'org')}
      >
        <span class="chevron" class:open={expandedOrgs.has(org.slug)} onclick|stopPropagation={() => toggleOrg(org.slug)}>&#9654;</span>
        <span class="org-name">{org.name}</span>
        <span class="org-count">{org.agents.length}</span>
      </button>

      {#if expandedOrgs.has(org.slug)}
        {@const tiers = groupByTier(org.agents)}
        {#each [...tiers.entries()] as [tier, tierAgents]}
          {@const tierKey = `${org.slug}:${tier}`}
          <div class="tier-group">
            <button class="tree-row tier-row" onclick={() => toggleTier(tierKey)}>
              <span class="chevron small" class:open={expandedTiers.has(tierKey)}>&#9654;</span>
              <span class="tier-badge" style="background: {tierColor(tier)}">{tierLabel(tier)}</span>
              <span class="tier-count">({tierAgents.length})</span>
            </button>

            {#if expandedTiers.has(tierKey)}
              {#each tierAgents as agent}
                <button
                  class="tree-row agent-row"
                  class:selected={selectedId === agent.name && selectedType === 'agent'}
                  onclick={() => onSelect(agent.name, 'agent')}
                >
                  {#if agent.name === agents.current}
                    <span class="active-dot"></span>
                  {/if}
                  <span class="agent-label">{agent.display_name}</span>
                  <span class="agent-role-badge">{agent.role}</span>
                </button>
              {/each}
            {/if}
          </div>
        {/each}
      {/if}
    </div>
  {/each}

  {#if standalone.length > 0}
    <div class="standalone-section">
      <div class="tree-divider">Standalone</div>
      {#each standalone as agent}
        <button
          class="tree-row agent-row"
          class:selected={selectedId === agent.name && selectedType === 'agent'}
          onclick={() => onSelect(agent.name, 'agent')}
        >
          {#if agent.name === agents.current}
            <span class="active-dot"></span>
          {/if}
          <span class="agent-label">{agent.display_name}</span>
          {#if agent.role}
            <span class="agent-role-badge">{agent.role}</span>
          {/if}
        </button>
      {/each}
    </div>
  {/if}

  <div class="tree-footer">
    <button class="tree-action-btn" onclick={onCreateAgent}>+ Quick Add Agent</button>
  </div>
</div>

<style>
  .org-tree {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow-y: auto;
    padding: 8px 0;
  }

  .tree-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 12px 8px;
  }

  .tree-title {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgba(255, 255, 255, 0.4);
  }

  .tree-action {
    background: none;
    border: 1px solid rgba(255, 255, 255, 0.15);
    color: rgba(255, 255, 255, 0.5);
    border-radius: 4px;
    width: 22px;
    height: 22px;
    cursor: pointer;
    font-size: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .tree-action:hover {
    border-color: rgba(100, 140, 255, 0.4);
    color: rgba(255, 255, 255, 0.8);
  }

  .tree-row {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 5px 12px;
    background: none;
    border: none;
    border-left: 2px solid transparent;
    color: rgba(255, 255, 255, 0.7);
    cursor: pointer;
    font-size: 13px;
    text-align: left;
  }

  .tree-row:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .tree-row.selected {
    background: rgba(100, 140, 255, 0.08);
    border-left-color: rgba(100, 140, 255, 0.5);
    color: rgba(255, 255, 255, 0.9);
  }

  .org-row { font-weight: 500; }

  .tier-row {
    padding-left: 24px;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.5);
  }

  .agent-row {
    padding-left: 40px;
    font-size: 12px;
  }

  .chevron {
    font-size: 8px;
    transition: transform 0.15s;
    color: rgba(255, 255, 255, 0.3);
    flex-shrink: 0;
  }

  .chevron.open { transform: rotate(90deg); }
  .chevron.small { font-size: 7px; }

  .org-name { flex: 1; }

  .org-count {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.3);
    background: rgba(255, 255, 255, 0.06);
    padding: 1px 6px;
    border-radius: 8px;
  }

  .tier-badge {
    font-size: 9px;
    padding: 1px 6px;
    border-radius: 3px;
    color: white;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .tier-count {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.3);
  }

  .active-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #4CAF50;
    flex-shrink: 0;
  }

  .agent-label { flex: 1; }

  .agent-role-badge {
    font-size: 9px;
    color: rgba(255, 255, 255, 0.3);
    max-width: 80px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .standalone-section { margin-top: 8px; }

  .tree-divider {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: rgba(255, 255, 255, 0.25);
    padding: 8px 12px 4px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }

  .tree-footer {
    padding: 8px 12px;
    margin-top: auto;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }

  .tree-action-btn {
    background: none;
    border: 1px dashed rgba(255, 255, 255, 0.15);
    color: rgba(255, 255, 255, 0.4);
    border-radius: 4px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 11px;
    width: 100%;
  }

  .tree-action-btn:hover {
    border-color: rgba(100, 140, 255, 0.4);
    color: rgba(255, 255, 255, 0.7);
  }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add src/renderer/components/settings/OrgTree.svelte
git commit -m "feat(ui): add OrgTree component for org/agent hierarchy"
```

---

## Task 4: AgentDetail Component (Right Panel)

**Files:**
- Create: `src/renderer/components/settings/AgentDetail.svelte`
- Create: `src/renderer/components/settings/JobEditor.svelte`

- [ ] **Step 1: Create JobEditor.svelte**

A sub-component for the Jobs sub-tab within AgentDetail. Receives agent name, shows job list with run/edit/delete.

This file should be around 150 lines. It displays jobs from the manifest, shows run history from `api.getJobHistory()`, and provides run-now/edit/delete buttons. Create with full implementation including the form for editing cron schedules.

- [ ] **Step 2: Create AgentDetail.svelte**

The main right-panel component when an agent is selected. Has 4 sub-tabs: Identity, Jobs, MCP, Router.

Identity tab: text fields for display_name, role, description, opening_line, wake_words. Textareas for system prompt and soul document. Dropdowns for org assignment, tier, reports_to. Toggles for can_address_user, can_provision.

Jobs tab: renders `JobEditor` component.

MCP tab: list of servers with include/exclude toggles from manifest `mcp.include` and `mcp.exclude`.

Router tab: form fields for accept_from, reject_from (comma-separated), max_queue_depth, system_access, can_address_agents.

Has a [Save] button that calls `api.updateAgentManifest()` + `api.updateAgentPrompt()`.
Has a [Delete] button with confirmation.

This will be a larger file (~400 lines). Create with full implementation.

- [ ] **Step 3: Commit**

```bash
git add src/renderer/components/settings/AgentDetail.svelte src/renderer/components/settings/JobEditor.svelte
git commit -m "feat(ui): add AgentDetail and JobEditor components"
```

---

## Task 5: OrgDetail and AgentCreateForm Components

**Files:**
- Create: `src/renderer/components/settings/OrgDetail.svelte`
- Create: `src/renderer/components/settings/AgentCreateForm.svelte`

- [ ] **Step 1: Create OrgDetail.svelte**

Shows when an org node is selected. Displays org metadata, roster stats, edit form for name/purpose, dissolve button with confirmation.

- [ ] **Step 2: Create AgentCreateForm.svelte**

Quick-create form for headless org agents. Fields: name, display_name, role, org dropdown, tier, reports_to, specialism. Submit calls `api.createAgent()` then fires an `onCreated` callback to refresh the tree.

- [ ] **Step 3: Commit**

```bash
git add src/renderer/components/settings/OrgDetail.svelte src/renderer/components/settings/AgentCreateForm.svelte
git commit -m "feat(ui): add OrgDetail and AgentCreateForm components"
```

---

## Task 6: AgentsTab Container and Settings Integration

**Files:**
- Create: `src/renderer/components/settings/AgentsTab.svelte`
- Modify: `src/renderer/components/Settings.svelte`
- Modify: `src/renderer/components/settings/SettingsTab.svelte`

- [ ] **Step 1: Create AgentsTab.svelte**

The main container. On `load()`, fetches orgs + all agents + schedule. Builds tree data structure. Manages selection state. Renders OrgTree on left, detail panel on right based on selection type.

```svelte
<script lang="ts">
  import { api } from '../../api';
  import OrgTree from './OrgTree.svelte';
  import AgentDetail from './AgentDetail.svelte';
  import OrgDetail from './OrgDetail.svelte';
  import AgentCreateForm from './AgentCreateForm.svelte';

  // Selection state
  let selectedId = $state<string | null>(null);
  let selectedType = $state<'agent' | 'org' | 'create' | null>(null);

  // Data
  let orgs = $state<any[]>([]);
  let allAgents = $state<any[]>([]);
  let schedule = $state<any[]>([]);
  let orgTree = $state<any[]>([]);
  let standalone = $state<any[]>([]);

  export async function load() {
    if (!api) return;
    const [orgList, agentList, schedData] = await Promise.all([
      api.listOrgs(),
      api.listAllAgents(),
      api.getSchedule(),
    ]);
    orgs = orgList || [];
    allAgents = agentList || [];
    schedule = schedData || [];
    buildTree();
  }

  function buildTree() {
    // Build org nodes with nested agents
    const orgNodes = [];
    const orgAgentNames = new Set<string>();

    for (const org of orgs) {
      const detail = /* will fetch */ { roster: [] as any[] };
      // For initial render, derive from agent manifests
      const orgAgents = allAgents.filter(a => {
        const manifest = a as any;
        return manifest.orgSlug === org.slug;
      });
      orgAgents.forEach(a => orgAgentNames.add(a.name));
      orgNodes.push({ ...org, agents: orgAgents });
    }

    orgTree = orgNodes;
    standalone = allAgents.filter(a => !orgAgentNames.has(a.name));
  }

  function handleSelect(id: string, type: 'agent' | 'org') {
    selectedId = id;
    selectedType = type;
  }

  function handleCreateAgent() {
    selectedId = null;
    selectedType = 'create';
  }

  function handleCreateOrg() {
    // Show org creation form in detail panel
    selectedId = '__new_org__';
    selectedType = 'org';
  }

  async function handleRefresh() {
    await load();
  }
</script>

<div class="agents-tab">
  <div class="agents-left">
    <OrgTree
      {orgTree}
      {standalone}
      {selectedId}
      {selectedType}
      onSelect={handleSelect}
      onCreateAgent={handleCreateAgent}
      onCreateOrg={handleCreateOrg}
    />
  </div>
  <div class="agents-right">
    {#if selectedType === 'agent' && selectedId}
      <AgentDetail
        agentName={selectedId}
        {schedule}
        onDeleted={handleRefresh}
        onSaved={handleRefresh}
      />
    {:else if selectedType === 'org' && selectedId}
      <OrgDetail
        orgSlug={selectedId}
        onDissolved={handleRefresh}
        onSaved={handleRefresh}
      />
    {:else if selectedType === 'create'}
      <AgentCreateForm
        {orgs}
        {allAgents}
        onCreated={handleRefresh}
        onCancel={() => { selectedType = null; }}
      />
    {:else}
      <div class="empty-state">
        <p>Select an agent or organisation from the tree to view details.</p>
      </div>
    {/if}
  </div>
</div>

<style>
  .agents-tab {
    display: flex;
    height: 100%;
    gap: 1px;
    background: rgba(255, 255, 255, 0.06);
  }

  .agents-left {
    width: 280px;
    min-width: 220px;
    background: var(--bg, #141418);
    overflow-y: auto;
  }

  .agents-right {
    flex: 1;
    background: var(--bg, #141418);
    overflow-y: auto;
    padding: 16px;
  }

  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: rgba(255, 255, 255, 0.3);
    font-size: 13px;
  }
</style>
```

Note: The actual implementation will need to properly fetch org details to map agents to orgs. The `listAllAgents` result includes `tier` from `AgentInfo`. The org mapping will come from matching agent manifest `org.slug` fields.

- [ ] **Step 2: Wire AgentsTab into Settings.svelte**

In `Settings.svelte`:

Add import:
```typescript
import AgentsTab from './settings/AgentsTab.svelte';
```

Add to `Tab` type:
```typescript
type Tab = 'settings' | 'agents' | 'usage' | 'activity' | 'jobs' | 'updates' | 'console';
```

Add ref:
```typescript
let agentsTab: AgentsTab;
```

Add to `switchTab`:
```typescript
if (tab === 'agents') agentsTab?.load();
```

Add tab button in template after the Settings button:
```html
<button class="tab" class:active={activeTab === 'agents'} onclick={() => switchTab('agents')}>Agents</button>
```

Add render block:
```html
{:else if activeTab === 'agents'}
  <AgentsTab bind:this={agentsTab} />
```

- [ ] **Step 3: Remove agent list from SettingsTab.svelte**

Remove the `<!-- AGENTS -->` section (lines ~190-293) and the related state variables and functions (agentList, agentNotifyVia, switchToAgent, updateNotifyVia, agentTelegramEditing, agentBotToken, agentChatId, agentTelegramStatus, agentTelegramDiscovering).

- [ ] **Step 4: Type-check and commit**

```bash
npx tsc --noEmit
git add src/renderer/components/settings/AgentsTab.svelte src/renderer/components/Settings.svelte src/renderer/components/settings/SettingsTab.svelte
git commit -m "feat(ui): add AgentsTab to Settings, remove inline agent list"
```

---

## Task 7: Data Loading and Org-Agent Mapping

**Files:**
- Modify: `src/main/ipc/agents.ts`
- Modify: `src/renderer/components/settings/AgentsTab.svelte`

- [ ] **Step 1: Enhance `agent:listAll` to include org info**

The `discoverAgents` return type `AgentInfo` only has name, display_name, description, role, tier. For the tree, we also need `orgSlug`, `reportsTo`, `canAddressUser`, and `enabled`. Modify the handler to enrich the data:

```typescript
  ipcMain.handle('agent:listAll', () => {
    const agents = discoverAgents();
    return agents.map((a) => {
      const manifest = findManifest(a.name) || {};
      const org = manifest.org as Record<string, unknown> | undefined;
      const state = getAgentState(a.name);
      return {
        ...a,
        orgSlug: org?.slug as string | null ?? null,
        reportsTo: org?.reports_to as string | null ?? null,
        canAddressUser: (org?.can_address_user as boolean) ?? true,
        enabled: state.enabled,
      };
    });
  });
```

- [ ] **Step 2: Update AgentsTab tree building to use orgSlug from enriched data**

Update `buildTree()` in AgentsTab to properly group agents by their `orgSlug` field rather than needing separate org detail fetches.

- [ ] **Step 3: Type-check and commit**

```bash
npx tsc --noEmit
git add src/main/ipc/agents.ts src/renderer/components/settings/AgentsTab.svelte
git commit -m "feat: enrich agent list with org info for tree building"
```

---

## Task 8: Polish and Final Integration

**Files:**
- Various renderer components

- [ ] **Step 1: Add org creation form to OrgDetail when `orgSlug === '__new_org__'`**

When selectedId is `__new_org__`, OrgDetail renders a creation form instead of the detail view.

- [ ] **Step 2: Add Telegram config to AgentDetail Identity tab**

Move the per-agent Telegram config (bot token, chat ID, auto-detect) from SettingsTab into AgentDetail's Identity tab so it's accessible from the new location.

- [ ] **Step 3: Full type-check and commit**

```bash
npx tsc --noEmit
git add -A
git commit -m "feat: org management UI - polish and final integration"
```

---

## Execution Notes

- Tasks 1-2 (IPC + preload) can be implemented first and tested via the Electron dev console before any UI exists
- Tasks 3-5 (components) are independent of each other and can be built in parallel
- Task 6 (integration) depends on all prior tasks
- Task 7 (data enrichment) refines the data flow once the basic UI is working
- Task 8 (polish) handles remaining details

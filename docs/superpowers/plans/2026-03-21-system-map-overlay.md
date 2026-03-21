# System Map Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone overlay that visualizes and lets users edit agent-to-service connections (MCP, channels, cron) in a three-column layout.

**Architecture:** New `SystemMap.svelte` component mounted in `Window.svelte`, communicating with main process via two new IPC handlers. MCP registry exports internal helpers. Memory server gains optional cross-agent parameter.

**Tech Stack:** Svelte 5 (runes mode), Electron IPC, TypeScript, existing CSS theme variables

**Spec:** `docs/superpowers/specs/2026-03-21-system-map-overlay-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/main/mcp-registry.ts` | Modify | Export `readAgentManifest`, `getAgentMcpSection`, `EXTERNAL_SERVER_META` |
| `src/main/system-topology.ts` | Create | Pure topology data layer (buildTopology, handleToggleConnection) |
| `src/main/ipc-handlers.ts` | Modify | Add `system:getTopology` and `system:toggleConnection` handlers |
| `src/preload/index.ts` | Modify | Add `getTopology`, `toggleConnection` to AtrophyAPI interface and implementation |
| `src/renderer/components/SystemMap.svelte` | Create | Main overlay component (~500 lines) |
| `src/renderer/components/Window.svelte` | Modify | Add `showSystemMap` state, `Cmd+Shift+M` shortcut, conditional render |
| `mcp/memory_server.py` | Modify | Add optional `agent` parameter to activate/deactivate for cross-agent wiring |
| `src/main/__tests__/system-topology.test.ts` | Create | Tests for topology IPC logic |

### Deferred to v2

- **Agent status dots** (green/amber/red) on agent cards - requires new IPC for per-agent inference state
- **Channel detail cards** - daemon status, bot token info
- **Cron detail cards** - last run time, result, schedule
- **Global shortcut** (Cmd+Shift+M when app is unfocused) - renderer-only matches existing shortcuts

---

### Task 1: Export MCP registry internals

**Files:**
- Modify: `src/main/mcp-registry.ts` (lines 104-128 for EXTERNAL_SERVER_META, lines 186-213 for helper functions)

- [ ] **Step 1: Add export to EXTERNAL_SERVER_META**

In `src/main/mcp-registry.ts`, change line 104 from:
```typescript
const EXTERNAL_SERVER_META: Record<string, {
```
to:
```typescript
export const EXTERNAL_SERVER_META: Record<string, {
```

- [ ] **Step 2: Add export to readAgentManifest**

Change the function declaration at ~line 186 from:
```typescript
function readAgentManifest(agentName: string): Record<string, unknown> {
```
to:
```typescript
export function readAgentManifest(agentName: string): Record<string, unknown> {
```

- [ ] **Step 3: Add export to getAgentMcpSection**

Change the function declaration at ~line 205 from:
```typescript
function getAgentMcpSection(agentName: string): AgentMcpConfig {
```
to:
```typescript
export function getAgentMcpSection(agentName: string): AgentMcpConfig {
```

- [ ] **Step 4: Verify build**

Run: `npx tsc --noEmit`
Expected: clean compile, no errors

- [ ] **Step 5: Commit**

```bash
git add src/main/mcp-registry.ts
git commit -m "refactor: export MCP registry helpers for system map"
```

---

### Task 2: Write topology IPC tests

**Files:**
- Create: `src/main/__tests__/system-topology.test.ts`

- [ ] **Step 1: Write test file**

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Tests for the topology data assembly logic.
 * We test the pure data transformation, not the IPC plumbing.
 */

// Mock the modules we depend on
vi.mock('../agent-manager', () => ({
  discoverAgents: vi.fn(() => [
    { name: 'xan', display_name: 'Xan', description: '', role: '' },
    { name: 'companion', display_name: 'Companion', description: '', role: '' },
  ]),
}));

vi.mock('../mcp-registry', async () => {
  const actual = await vi.importActual('../mcp-registry') as Record<string, unknown>;
  return {
    ...actual,
    readAgentManifest: vi.fn((name: string) => {
      if (name === 'xan') {
        return {
          mcp: { include: ['memory', 'shell'], exclude: [], custom: {} },
          channels: { telegram: { enabled: true }, desktop: { enabled: true } },
          jobs: { morning_brief: { schedule: '0 7 * * *' } },
          router: { system_access: true },
        };
      }
      return {
        mcp: { include: ['memory'], exclude: [], custom: {} },
        channels: { desktop: { enabled: true } },
        jobs: {},
        router: { system_access: false },
      };
    }),
    getAgentMcpSection: vi.fn((name: string) => {
      if (name === 'xan') {
        return { include: ['memory', 'shell'], exclude: [], custom: {} };
      }
      return { include: ['memory'], exclude: [], custom: {} };
    }),
    EXTERNAL_SERVER_META: {
      elevenlabs: {
        description: 'ElevenLabs TTS',
        capabilities: ['tts'],
        commandCandidates: ['uvx'],
        args: ['elevenlabs-mcp'],
        requiresEnvKey: 'ELEVENLABS_API_KEY',
      },
    },
    mcpRegistry: {
      getRegistry: vi.fn(() => [
        { name: 'memory', description: 'Memory server', capabilities: ['memory'], bundled: true },
        { name: 'shell', description: 'Shell server', capabilities: ['shell'], bundled: true },
      ]),
      getForAgent: vi.fn((name: string) => {
        if (name === 'xan') {
          return [
            { name: 'memory', description: 'Memory', capabilities: ['memory'], bundled: true },
            { name: 'shell', description: 'Shell', capabilities: ['shell'], bundled: true },
          ];
        }
        return [
          { name: 'memory', description: 'Memory', capabilities: ['memory'], bundled: true },
        ];
      }),
      getServer: vi.fn((name: string) => {
        if (name === 'memory' || name === 'shell') return { name };
        return undefined;
      }),
      activateForAgent: vi.fn(),
      deactivateForAgent: vi.fn(),
      buildConfigForAgent: vi.fn(),
      needsRestart: vi.fn(() => true),
    },
  };
});

// Import after mocks
import { buildTopology, handleToggleConnection } from '../system-topology';

describe('buildTopology', () => {
  it('returns agents with MCP, channels, and jobs', () => {
    const result = buildTopology();
    expect(result.agents).toHaveLength(2);
    expect(result.agents[0].name).toBe('xan');
    expect(result.agents[0].mcp.active).toEqual(['memory', 'shell']);
    expect(result.agents[0].channels).toHaveProperty('telegram');
    expect(result.agents[0].jobs).toHaveProperty('morning_brief');
  });

  it('includes available registered servers', () => {
    const result = buildTopology();
    expect(result.servers.some(s => s.name === 'memory')).toBe(true);
    expect(result.servers.some(s => s.name === 'shell')).toBe(true);
  });

  it('includes unavailable external servers from EXTERNAL_SERVER_META', () => {
    const result = buildTopology();
    const el = result.servers.find(s => s.name === 'elevenlabs');
    expect(el).toBeDefined();
    expect(el!.available).toBe(false);
    expect(el!.missingCommand).toBe(true);
  });

  it('includes router info for cross-agent access checks', () => {
    const result = buildTopology();
    expect(result.agents[0].router).toHaveProperty('system_access', true);
    expect(result.agents[1].router).toHaveProperty('system_access', false);
  });
});

describe('handleToggleConnection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns error for invalid agent', () => {
    const result = handleToggleConnection('../bad', 'memory', true);
    expect(result.success).toBe(false);
    expect(result.error).toContain('Invalid');
  });

  it('returns error for unknown server on activate', () => {
    const result = handleToggleConnection('xan', 'nonexistent', true);
    expect(result.success).toBe(false);
    expect(result.error).toContain('Unknown');
  });

  it('calls activateForAgent and buildConfigForAgent on enable', () => {
    const { mcpRegistry } = require('../mcp-registry');
    const result = handleToggleConnection('xan', 'shell', true);
    expect(result.success).toBe(true);
    expect(mcpRegistry.activateForAgent).toHaveBeenCalledWith('xan', 'shell');
    expect(mcpRegistry.buildConfigForAgent).toHaveBeenCalledWith('xan');
  });

  it('calls deactivateForAgent on disable', () => {
    const { mcpRegistry } = require('../mcp-registry');
    const result = handleToggleConnection('xan', 'shell', false);
    expect(result.success).toBe(true);
    expect(mcpRegistry.deactivateForAgent).toHaveBeenCalledWith('xan', 'shell');
  });

  it('returns needsRestart flag', () => {
    const result = handleToggleConnection('xan', 'shell', true);
    expect(result.needsRestart).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/main/__tests__/system-topology.test.ts`
Expected: FAIL - `Cannot find module '../system-topology'`

- [ ] **Step 3: Commit test file**

```bash
git add src/main/__tests__/system-topology.test.ts
git commit -m "test: add system topology tests (failing - implementation pending)"
```

---

### Task 3: Implement topology data layer

**Files:**
- Create: `src/main/system-topology.ts`

- [ ] **Step 1: Create the topology module**

```typescript
/**
 * Pure data layer for the system map overlay.
 * Assembles topology from agent manifests, MCP registry, and server metadata.
 * Used by IPC handlers - no Electron imports needed.
 */

import { discoverAgents } from './agent-manager';
import {
  mcpRegistry,
  readAgentManifest,
  getAgentMcpSection,
  EXTERNAL_SERVER_META,
  type McpServerDefinition,
} from './mcp-registry';
import { isValidAgentName, saveAgentConfig } from './config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TopologyAgent {
  name: string;
  displayName: string;
  role: string;
  mcp: {
    include: string[];
    exclude: string[];
    active: string[];
  };
  channels: Record<string, unknown>;
  jobs: Record<string, unknown>;
  router: Record<string, unknown>;
}

export interface TopologyServer {
  name: string;
  description: string;
  capabilities: string[];
  bundled: boolean;
  available: boolean;
  missingKey: boolean;
  missingCommand: boolean;
}

export interface Topology {
  agents: TopologyAgent[];
  servers: TopologyServer[];
}

export interface ToggleResult {
  success: boolean;
  error?: string;
  needsRestart?: boolean;
  active?: string[];
}

// ---------------------------------------------------------------------------
// Build topology
// ---------------------------------------------------------------------------

export function buildTopology(): Topology {
  const agentInfos = discoverAgents();

  const agents: TopologyAgent[] = agentInfos.map(info => {
    const manifest = readAgentManifest(info.name);
    const mcpSection = getAgentMcpSection(info.name);
    return {
      name: info.name,
      displayName: info.display_name || info.name,
      role: info.role || '',
      mcp: {
        include: mcpSection.include,
        exclude: mcpSection.exclude,
        active: mcpRegistry.getForAgent(info.name).map(s => s.name),
      },
      channels: (manifest.channels || {}) as Record<string, unknown>,
      jobs: (manifest.jobs || {}) as Record<string, unknown>,
      router: (manifest.router || {}) as Record<string, unknown>,
    };
  });

  // All registered (available) servers
  const registeredServers = mcpRegistry.getRegistry();
  const servers: TopologyServer[] = registeredServers.map(s => ({
    name: s.name,
    description: s.description,
    capabilities: s.capabilities || [],
    bundled: s.bundled,
    available: true,
    missingKey: false,
    missingCommand: false,
  }));

  // Add unavailable external servers that discover() skipped
  for (const [name, meta] of Object.entries(EXTERNAL_SERVER_META)) {
    if (!registeredServers.some(s => s.name === name)) {
      const keyMissing = !!(meta.requiresEnvKey && !process.env[meta.requiresEnvKey]);
      servers.push({
        name,
        description: meta.description,
        capabilities: meta.capabilities,
        bundled: true,
        available: false,
        missingKey: keyMissing,
        missingCommand: !keyMissing, // if key isn't the problem, command is
      });
    }
  }

  return { agents, servers };
}

// ---------------------------------------------------------------------------
// Toggle connection
// ---------------------------------------------------------------------------

export function handleToggleConnection(
  agentName: string,
  serverName: string,
  enabled: boolean,
): ToggleResult {
  if (!isValidAgentName(agentName)) {
    return { success: false, error: `Invalid agent: ${agentName}` };
  }

  if (enabled && !mcpRegistry.getServer(serverName)) {
    return { success: false, error: `Unknown server: ${serverName}` };
  }

  // If agent has empty include list (meaning "all"), populate it explicitly
  // before toggling so the UI semantics are clear
  const mcpSection = getAgentMcpSection(agentName);
  if (mcpSection.include.length === 0) {
    const currentActive = mcpRegistry.getForAgent(agentName).map(s => s.name);
    mcpSection.include = currentActive;
    saveAgentConfig(agentName, { mcp: mcpSection });
  }

  if (enabled) {
    mcpRegistry.activateForAgent(agentName, serverName);
  } else {
    mcpRegistry.deactivateForAgent(agentName, serverName);
  }

  // Rebuild the config.json that Claude CLI reads via --mcp-config
  mcpRegistry.buildConfigForAgent(agentName);

  return {
    success: true,
    needsRestart: mcpRegistry.needsRestart(agentName),
    active: mcpRegistry.getForAgent(agentName).map(s => s.name),
  };
}
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `npx vitest run src/main/__tests__/system-topology.test.ts`
Expected: all tests PASS

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit`
Expected: clean compile

- [ ] **Step 4: Commit**

```bash
git add src/main/system-topology.ts
git commit -m "feat: add system topology data layer"
```

---

### Task 4: Register IPC handlers

**Files:**
- Modify: `src/main/ipc-handlers.ts`

- [ ] **Step 1: Add import at top of file**

After the existing imports (around line 15), add:
```typescript
import { buildTopology, handleToggleConnection } from './system-topology';
```

- [ ] **Step 2: Add handlers at end of registerIpcHandlers function**

At the end of `registerIpcHandlers()` (search for the last `ipcMain.handle` call, e.g. `artefact:getContent`, and add after it):
```typescript
  // ---------------------------------------------------------------------------
  // System map topology
  // ---------------------------------------------------------------------------

  ipcMain.handle('system:getTopology', () => {
    return buildTopology();
  });

  ipcMain.handle('system:toggleConnection', (_, agentName: string, serverName: string, enabled: boolean) => {
    return handleToggleConnection(agentName, serverName, enabled);
  });
```

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit`
Expected: clean compile

- [ ] **Step 4: Commit**

```bash
git add src/main/ipc-handlers.ts
git commit -m "feat: register system topology IPC handlers"
```

---

### Task 5: Expose IPC in preload

**Files:**
- Modify: `src/preload/index.ts`

- [ ] **Step 1: Add to AtrophyAPI interface**

Find the interface definition (starts around line 7). Add these properties before the closing `}`:
```typescript
  // System map
  getTopology: () => Promise<{
    agents: Array<{
      name: string;
      displayName: string;
      role: string;
      mcp: { include: string[]; exclude: string[]; active: string[] };
      channels: Record<string, unknown>;
      jobs: Record<string, unknown>;
      router: Record<string, unknown>;
    }>;
    servers: Array<{
      name: string;
      description: string;
      capabilities: string[];
      bundled: boolean;
      available: boolean;
      missingKey: boolean;
      missingCommand: boolean;
    }>;
  }>;
  toggleConnection: (agent: string, server: string, enabled: boolean) => Promise<{
    success: boolean;
    error?: string;
    needsRestart?: boolean;
    active?: string[];
  }>;
```

- [ ] **Step 2: Add implementation in api object**

In the `const api: AtrophyAPI = {` object (around line 213), add before the closing:
```typescript
  // System map
  getTopology: () => ipcRenderer.invoke('system:getTopology'),
  toggleConnection: (agent, server, enabled) =>
    ipcRenderer.invoke('system:toggleConnection', agent, server, enabled),
```

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit`
Expected: clean compile

- [ ] **Step 4: Commit**

```bash
git add src/preload/index.ts
git commit -m "feat: expose system topology IPC in preload API"
```

---

### Task 6: Create SystemMap.svelte

**Files:**
- Create: `src/renderer/components/SystemMap.svelte`

This is the largest task. The component handles: topology display, pill toggling, detail cards, search, restart banner.

- [ ] **Step 1: Create the component**

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../api';

  // ---------------------------------------------------------------------------
  // Props
  // ---------------------------------------------------------------------------

  interface Props {
    onClose: () => void;
  }
  let { onClose }: Props = $props();

  // ---------------------------------------------------------------------------
  // Types (mirror the IPC response shapes)
  // ---------------------------------------------------------------------------

  interface TopologyAgent {
    name: string;
    displayName: string;
    role: string;
    mcp: { include: string[]; exclude: string[]; active: string[] };
    channels: Record<string, unknown>;
    jobs: Record<string, unknown>;
    router: Record<string, unknown>;
  }

  interface TopologyServer {
    name: string;
    description: string;
    capabilities: string[];
    bundled: boolean;
    available: boolean;
    missingKey: boolean;
  }

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  let agents = $state<TopologyAgent[]>([]);
  let servers = $state<TopologyServer[]>([]);
  let selectedAgent = $state<string>('');
  let searchQuery = $state('');
  let searchFocused = $state(false);
  let expandedGroups = $state<Record<string, Record<string, boolean>>>({});
  let detailPill = $state<{ agent: string; server: string } | null>(null);
  let pendingRestarts = $state<Set<string>>(new Set());
  let loading = $state(true);

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  async function fetchTopology() {
    if (!api) return;
    loading = true;
    try {
      const topo = await api.getTopology();
      agents = topo.agents;
      servers = topo.servers;
      if (!selectedAgent && agents.length > 0) {
        selectedAgent = agents[0].name;
      }
      // Default expansion: MCP expanded, channels expanded, cron collapsed
      for (const agent of agents) {
        if (!expandedGroups[agent.name]) {
          const jobCount = Object.keys(agent.jobs).length;
          const mcpCount = agent.mcp.active.length;
          expandedGroups[agent.name] = {
            mcp: mcpCount < 10,
            channels: true,
            cron: jobCount < 5,
          };
        }
      }
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    fetchTopology();
  });

  // ---------------------------------------------------------------------------
  // Interactions
  // ---------------------------------------------------------------------------

  async function toggleMcp(agentName: string, serverName: string) {
    if (!api) return;
    const agent = agents.find(a => a.name === agentName);
    if (!agent) return;

    const isActive = agent.mcp.active.includes(serverName);
    const result = await api.toggleConnection(agentName, serverName, !isActive);

    if (result.success) {
      // Update local state immediately
      const idx = agents.findIndex(a => a.name === agentName);
      if (idx >= 0 && result.active) {
        agents[idx].mcp.active = result.active;
      }
      if (result.needsRestart) {
        pendingRestarts = new Set([...pendingRestarts, agentName]);
      }
    }
  }

  function toggleGroup(agentName: string, group: string) {
    if (!expandedGroups[agentName]) expandedGroups[agentName] = {};
    expandedGroups[agentName][group] = !expandedGroups[agentName]?.[group];
    // Force reactivity
    expandedGroups = { ...expandedGroups };
  }

  function selectAgent(name: string) {
    selectedAgent = name;
    const el = document.getElementById(`agent-section-${name}`);
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function toggleDetail(agentName: string, serverName: string, e: MouseEvent) {
    if (e.metaKey || e.ctrlKey) {
      e.preventDefault();
      if (detailPill?.agent === agentName && detailPill?.server === serverName) {
        detailPill = null;
      } else {
        detailPill = { agent: agentName, server: serverName };
      }
    } else {
      toggleMcp(agentName, serverName);
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      if (searchFocused && searchQuery) {
        searchQuery = '';
      } else {
        onClose();
      }
      e.preventDefault();
    } else if (e.key === '/' && !searchFocused) {
      e.preventDefault();
      const input = document.getElementById('system-map-search') as HTMLInputElement;
      input?.focus();
    } else if (!searchFocused && e.key >= '1' && e.key <= '9') {
      const idx = parseInt(e.key) - 1;
      if (idx < agents.length) {
        selectAgent(agents[idx].name);
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  function matchesSearch(name: string): boolean {
    if (!searchQuery) return true;
    return name.toLowerCase().includes(searchQuery.toLowerCase());
  }

  function serverInfo(name: string): TopologyServer | undefined {
    return servers.find(s => s.name === name);
  }

  function agentsUsing(serverName: string): string[] {
    return agents.filter(a => a.mcp.active.includes(serverName)).map(a => a.displayName);
  }

  function allMcpForAgent(agent: TopologyAgent): Array<{ name: string; active: boolean; server?: TopologyServer }> {
    const result: Array<{ name: string; active: boolean; server?: TopologyServer }> = [];
    // Active servers first
    for (const name of agent.mcp.active) {
      result.push({ name, active: true, server: serverInfo(name) });
    }
    // Available but inactive servers
    for (const s of servers) {
      if (!agent.mcp.active.includes(s.name)) {
        result.push({ name: s.name, active: false, server: s });
      }
    }
    return result;
  }
</script>

<svelte:window on:keydown={onKeydown} />

<!-- Overlay backdrop -->
<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="overlay" onclick={onClose}>
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="panel" onclick={(e) => e.stopPropagation()}>

    <!-- Header -->
    <div class="header">
      <span class="title">System Map</span>
      <div class="header-right">
        <input
          id="system-map-search"
          type="text"
          class="search-input"
          placeholder="Filter services..."
          bind:value={searchQuery}
          onfocus={() => searchFocused = true}
          onblur={() => searchFocused = false}
        />
        <button class="close-btn" onclick={onClose} aria-label="Close">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </button>
      </div>
    </div>

    {#if loading}
      <div class="loading">Loading topology...</div>
    {:else}
      <div class="columns">

        <!-- Left: Agent cards -->
        <div class="col-agents">
          {#each agents as agent, i}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div
              class="agent-card"
              class:selected={selectedAgent === agent.name}
              onclick={() => selectAgent(agent.name)}
            >
              <div class="agent-name">{agent.displayName}</div>
              {#if agent.role}
                <div class="agent-role">{agent.role}</div>
              {/if}
              <div class="agent-meta">
                <span class="meta-badge mcp">{agent.mcp.active.length}</span>
                <span class="meta-badge channel">{Object.keys(agent.channels).length}</span>
                <span class="meta-badge cron">{Object.keys(agent.jobs).length}</span>
              </div>
            </div>
          {/each}
        </div>

        <!-- Center: Switchboard rail -->
        <div class="col-switchboard">
          <div class="rail-line"></div>
          <div class="rail-icon">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" opacity="0.3">
              <circle cx="8" cy="4" r="2"/>
              <circle cx="4" cy="12" r="2"/>
              <circle cx="12" cy="12" r="2"/>
              <line x1="8" y1="6" x2="4" y2="10" stroke="currentColor" stroke-width="1"/>
              <line x1="8" y1="6" x2="12" y2="10" stroke="currentColor" stroke-width="1"/>
            </svg>
          </div>
        </div>

        <!-- Right: Service sections -->
        <div class="col-services">
          {#each agents as agent}
            <div class="agent-section" id="agent-section-{agent.name}" class:highlighted={selectedAgent === agent.name}>

              <div class="section-name">{agent.displayName}</div>

              <!-- MCP group -->
              <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
              <div class="group-header" onclick={() => toggleGroup(agent.name, 'mcp')}>
                <span class="group-arrow">{expandedGroups[agent.name]?.mcp ? 'v' : '>'}</span>
                <span>MCP</span>
                <span class="count-badge mcp">{agent.mcp.active.length}</span>
              </div>

              {#if expandedGroups[agent.name]?.mcp}
                <div class="pill-grid">
                  {#each allMcpForAgent(agent) as item}
                    {#if matchesSearch(item.name)}
                      <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                      <div class="pill-wrap">
                        <button
                          class="pill mcp"
                          class:active={item.active}
                          class:unavailable={item.server && !item.server.available}
                          class:missing-key={item.server?.missingKey}
                          class:search-dim={searchQuery && !matchesSearch(item.name)}
                          onclick={(e) => toggleDetail(agent.name, item.name, e)}
                          title={item.server?.description || item.name}
                        >
                          {#if item.server?.missingKey}
                            <span class="key-icon" title="API key not set">!</span>
                          {:else if item.server?.missingCommand}
                            <span class="warn-icon" title="Command not found (install required)">!</span>
                          {/if}
                          {item.name}
                        </button>

                        <!-- Detail card -->
                        {#if detailPill?.agent === agent.name && detailPill?.server === item.name}
                          <div class="detail-card">
                            <div class="detail-header">
                              <span>{item.name}</span>
                              <button class="detail-close" onclick={() => detailPill = null}>x</button>
                            </div>
                            <div class="detail-line"></div>
                            <div class="detail-body">
                              <p>{item.server?.description || 'No description'}</p>
                              <div class="detail-row">
                                <span class="detail-label">Type</span>
                                <span>{item.server?.bundled ? 'bundled' : 'custom'}</span>
                              </div>
                              <div class="detail-row">
                                <span class="detail-label">Status</span>
                                <span class="status-dot" class:available={item.server?.available} class:unavailable={!item.server?.available}></span>
                                <span>{item.server?.available ? 'available' : 'unavailable'}</span>
                              </div>
                              {#if item.server?.capabilities?.length}
                                <div class="detail-row">
                                  <span class="detail-label">Capabilities</span>
                                  <span>{item.server.capabilities.join(', ')}</span>
                                </div>
                              {/if}
                              <div class="detail-row">
                                <span class="detail-label">Used by</span>
                                <span>{agentsUsing(item.name).join(', ') || 'none'}</span>
                              </div>
                            </div>
                          </div>
                        {/if}
                      </div>
                    {/if}
                  {/each}
                </div>
              {/if}

              <!-- Channels group -->
              <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
              <div class="group-header" onclick={() => toggleGroup(agent.name, 'channels')}>
                <span class="group-arrow">{expandedGroups[agent.name]?.channels ? 'v' : '>'}</span>
                <span>Channels</span>
                <span class="count-badge channel">{Object.keys(agent.channels).length}</span>
              </div>

              {#if expandedGroups[agent.name]?.channels}
                <div class="pill-grid">
                  {#each Object.entries(agent.channels) as [name, config]}
                    {#if matchesSearch(name)}
                      <button
                        class="pill channel"
                        class:active={true}
                        class:search-dim={searchQuery && !matchesSearch(name)}
                        title={name}
                      >
                        {name}
                      </button>
                    {/if}
                  {/each}
                </div>
              {/if}

              <!-- Cron group -->
              <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
              <div class="group-header" onclick={() => toggleGroup(agent.name, 'cron')}>
                <span class="group-arrow">{expandedGroups[agent.name]?.cron ? 'v' : '>'}</span>
                <span>Cron</span>
                <span class="count-badge cron">{Object.keys(agent.jobs).length}</span>
              </div>

              {#if expandedGroups[agent.name]?.cron}
                <div class="pill-grid">
                  {#each Object.entries(agent.jobs) as [name, config]}
                    {#if matchesSearch(name)}
                      <button
                        class="pill cron"
                        class:active={true}
                        class:search-dim={searchQuery && !matchesSearch(name)}
                        title={name}
                      >
                        {name}
                      </button>
                    {/if}
                  {/each}
                </div>
              {/if}

              <div class="section-divider"></div>
            </div>
          {/each}
        </div>

      </div>
    {/if}

    <!-- Restart banner -->
    {#if pendingRestarts.size > 0}
      <div class="restart-banner">
        <span>{pendingRestarts.size} change{pendingRestarts.size > 1 ? 's' : ''} pending - restart {[...pendingRestarts].join(', ')} to apply</span>
        <div class="restart-buttons">
          {#each [...pendingRestarts] as name}
            <button class="restart-btn" onclick={async () => {
              if (api) await api.switchAgent(name);
              pendingRestarts.delete(name);
              pendingRestarts = new Set(pendingRestarts);
              await fetchTopology(); // refresh state
            }}>
              Restart {name}
            </button>
          {/each}
        </div>
      </div>
    {/if}

  </div>
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(8px);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .panel {
    width: 100%;
    max-width: 680px;
    max-height: 85vh;
    background: var(--bg, #0C0C0E);
    border: 1px solid var(--border, rgba(255,255,255,0.06));
    border-radius: 16px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 20px;
    border-bottom: 1px solid var(--border, rgba(255,255,255,0.06));
    flex-shrink: 0;
  }

  .title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary, rgba(255,255,255,0.85));
    letter-spacing: 0.02em;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .search-input {
    width: 140px;
    height: 28px;
    background: var(--bg-secondary, rgba(255,255,255,0.04));
    border: 1px solid var(--border, rgba(255,255,255,0.06));
    border-radius: 6px;
    color: var(--text-primary, rgba(255,255,255,0.85));
    font-size: 12px;
    padding: 0 8px;
    outline: none;
    transition: border-color 0.15s;
  }
  .search-input:focus {
    border-color: var(--accent, rgba(100,140,255,0.3));
  }
  .search-input::placeholder {
    color: var(--text-dim, rgba(255,255,255,0.3));
  }

  .close-btn {
    background: none;
    border: none;
    color: var(--text-dim, rgba(255,255,255,0.3));
    cursor: pointer;
    padding: 4px;
    display: flex;
    align-items: center;
  }
  .close-btn:hover { color: var(--text-primary, rgba(255,255,255,0.85)); }

  .loading {
    padding: 40px;
    text-align: center;
    color: var(--text-dim, rgba(255,255,255,0.3));
    font-size: 13px;
  }

  /* Three-column layout */
  .columns {
    display: flex;
    flex: 1;
    overflow: hidden;
    min-height: 0;
  }

  .col-agents {
    width: 160px;
    flex-shrink: 0;
    padding: 12px;
    overflow-y: auto;
    border-right: 1px solid var(--border, rgba(255,255,255,0.06));
  }

  .col-switchboard {
    width: 48px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    position: relative;
  }

  .rail-line {
    position: absolute;
    top: 12px;
    bottom: 12px;
    width: 2px;
    background: linear-gradient(
      to bottom,
      transparent,
      rgba(100, 140, 255, 0.15) 15%,
      rgba(100, 140, 255, 0.15) 85%,
      transparent
    );
    border-radius: 1px;
  }

  .rail-icon {
    position: relative;
    z-index: 1;
    color: var(--text-dim, rgba(255,255,255,0.3));
  }

  .col-services {
    flex: 1;
    overflow-y: auto;
    padding: 12px 16px;
    min-width: 0;
  }

  /* Agent cards */
  .agent-card {
    padding: 10px 12px;
    border-radius: 8px;
    cursor: pointer;
    margin-bottom: 6px;
    transition: background 0.15s, border-color 0.15s;
    border: 1px solid transparent;
  }
  .agent-card:hover {
    background: var(--bg-secondary, rgba(255,255,255,0.04));
  }
  .agent-card.selected {
    border-color: var(--accent, rgba(100,140,255,0.3));
    background: rgba(100, 140, 255, 0.06);
  }

  .agent-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, rgba(255,255,255,0.85));
  }

  .agent-role {
    font-size: 11px;
    color: var(--text-dim, rgba(255,255,255,0.3));
    margin-top: 2px;
  }

  .agent-meta {
    display: flex;
    gap: 4px;
    margin-top: 6px;
  }

  .meta-badge {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 8px;
    font-weight: 500;
  }
  .meta-badge.mcp { background: rgba(100, 140, 255, 0.15); color: rgba(100, 140, 255, 0.8); }
  .meta-badge.channel { background: rgba(120, 200, 120, 0.15); color: rgba(120, 200, 120, 0.8); }
  .meta-badge.cron { background: rgba(255, 180, 80, 0.15); color: rgba(255, 180, 80, 0.8); }

  /* Service sections */
  .agent-section {
    margin-bottom: 8px;
    padding: 8px 0;
    transition: background 0.2s;
    border-radius: 8px;
  }
  .agent-section.highlighted {
    background: rgba(100, 140, 255, 0.03);
  }

  .section-name {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-dim, rgba(255,255,255,0.3));
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 0 4px;
    margin-bottom: 6px;
  }

  .section-divider {
    height: 1px;
    background: var(--border, rgba(255,255,255,0.06));
    margin: 8px 0;
  }

  /* Group headers */
  .group-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px;
    cursor: pointer;
    font-size: 11px;
    color: var(--text-secondary, rgba(255,255,255,0.5));
    user-select: none;
  }
  .group-header:hover {
    color: var(--text-primary, rgba(255,255,255,0.85));
  }

  .group-arrow {
    font-size: 10px;
    width: 12px;
    display: inline-block;
    transition: transform 0.15s;
  }

  .count-badge {
    font-size: 10px;
    padding: 0 5px;
    border-radius: 6px;
    font-weight: 500;
    margin-left: auto;
  }
  .count-badge.mcp { background: rgba(100, 140, 255, 0.1); color: rgba(100, 140, 255, 0.6); }
  .count-badge.channel { background: rgba(120, 200, 120, 0.1); color: rgba(120, 200, 120, 0.6); }
  .count-badge.cron { background: rgba(255, 180, 80, 0.1); color: rgba(255, 180, 80, 0.6); }

  /* Pills */
  .pill-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    padding: 4px 4px 8px;
  }

  .pill-wrap {
    position: relative;
  }

  .pill {
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 10px;
    cursor: pointer;
    border: 1px solid transparent;
    background: transparent;
    color: var(--text-dim, rgba(255,255,255,0.3));
    transition: all 0.15s;
    white-space: nowrap;
  }

  /* Active pills */
  .pill.mcp.active {
    background: rgba(100, 140, 255, 0.2);
    color: rgba(180, 200, 255, 0.9);
    border-color: rgba(100, 140, 255, 0.3);
  }
  .pill.channel.active {
    background: rgba(120, 200, 120, 0.2);
    color: rgba(180, 240, 180, 0.9);
    border-color: rgba(120, 200, 120, 0.3);
  }
  .pill.cron.active {
    background: rgba(255, 180, 80, 0.2);
    color: rgba(255, 220, 160, 0.9);
    border-color: rgba(255, 180, 80, 0.3);
  }

  /* Inactive pills */
  .pill:not(.active) {
    border-style: dashed;
    border-color: rgba(255, 255, 255, 0.08);
  }

  /* Hover */
  .pill.mcp:hover { background: rgba(100, 140, 255, 0.3); color: white; }
  .pill.channel:hover { background: rgba(120, 200, 120, 0.3); color: white; }
  .pill.cron:hover { background: rgba(255, 180, 80, 0.3); color: white; }

  /* Unavailable / missing key */
  .pill.unavailable {
    text-decoration: line-through;
    opacity: 0.4;
  }
  .pill.missing-key {
    border-color: rgba(255, 100, 100, 0.3);
  }

  .key-icon, .warn-icon {
    font-size: 9px;
    margin-right: 3px;
    color: rgba(255, 100, 100, 0.7);
  }

  /* Search dim */
  .pill.search-dim {
    opacity: 0.15;
  }

  /* Detail card */
  .detail-card {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    width: 280px;
    background: var(--bg, #0C0C0E);
    border: 1px solid var(--border, rgba(255,255,255,0.1));
    border-radius: 10px;
    padding: 10px 12px;
    z-index: 10;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }

  .detail-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-primary, rgba(255,255,255,0.85));
  }

  .detail-close {
    background: none;
    border: none;
    color: var(--text-dim, rgba(255,255,255,0.3));
    cursor: pointer;
    font-size: 12px;
  }

  .detail-line {
    height: 1px;
    background: var(--border, rgba(255,255,255,0.06));
    margin: 6px 0;
  }

  .detail-body {
    font-size: 11px;
    color: var(--text-secondary, rgba(255,255,255,0.5));
  }
  .detail-body p {
    margin: 0 0 8px;
    line-height: 1.4;
  }

  .detail-row {
    display: flex;
    gap: 8px;
    margin-bottom: 4px;
    align-items: center;
  }

  .detail-label {
    color: var(--text-dim, rgba(255,255,255,0.3));
    min-width: 70px;
    flex-shrink: 0;
  }

  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
  }
  .status-dot.available { background: rgba(120, 200, 120, 0.8); }
  .status-dot.unavailable { background: rgba(255, 100, 100, 0.6); }

  /* Restart banner */
  .restart-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 16px;
    background: rgba(255, 180, 80, 0.08);
    border-top: 1px solid rgba(255, 180, 80, 0.2);
    font-size: 12px;
    color: rgba(255, 200, 120, 0.9);
    flex-shrink: 0;
  }

  .restart-buttons {
    display: flex;
    gap: 6px;
  }

  .restart-btn {
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 6px;
    border: 1px solid rgba(255, 180, 80, 0.3);
    background: rgba(255, 180, 80, 0.1);
    color: rgba(255, 200, 120, 0.9);
    cursor: pointer;
    white-space: nowrap;
  }
  .restart-btn:hover {
    background: rgba(255, 180, 80, 0.2);
  }

  /* Scrollbar styling */
  .col-agents::-webkit-scrollbar,
  .col-services::-webkit-scrollbar {
    width: 4px;
  }
  .col-agents::-webkit-scrollbar-thumb,
  .col-services::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 2px;
  }
</style>
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit`
Expected: clean compile

- [ ] **Step 3: Commit**

```bash
git add src/renderer/components/SystemMap.svelte
git commit -m "feat: create SystemMap overlay component"
```

---

### Task 7: Wire into Window.svelte

**Files:**
- Modify: `src/renderer/components/Window.svelte`

- [ ] **Step 1: Add import**

With the other component imports at the top of the script block, add:
```typescript
import SystemMap from './SystemMap.svelte';
```

- [ ] **Step 2: Add state variable**

After the existing overlay state declarations (around line 51, after `let showArtefact = $state(false)`), add:
```typescript
let showSystemMap = $state(false);
```

- [ ] **Step 3: Add keyboard shortcut**

In the `onKeydown` function, add a new `else if` branch before the Escape handler:
```typescript
  // Cmd+Shift+M : system map
  else if (e.metaKey && e.shiftKey && e.key === 'M') {
    e.preventDefault();
    showSystemMap = !showSystemMap;
  }
```

- [ ] **Step 4: Add Escape handling**

In the Escape priority chain, add system map before settings.
**Note:** SystemMap also handles Escape internally (for clearing search). Both handlers will fire since both use `svelte:window`. This is harmless - the component's `onClose` and Window's `showSystemMap = false` both set the same state. The component handles search-clear Escape internally with `e.preventDefault()`.
```typescript
  else if (e.key === 'Escape') {
    if (showSystemMap) showSystemMap = false;
    else if (showSettings) showSettings = false;
    // ... rest unchanged ...
  }
```

- [ ] **Step 5: Add conditional render**

After the Settings conditional render block (around line 1537), add:
```svelte
{#if showSystemMap}
  <SystemMap onClose={() => showSystemMap = false} />
{/if}
```

- [ ] **Step 6: Type-check and build**

Run: `npx tsc --noEmit`
Expected: clean compile

- [ ] **Step 7: Commit**

```bash
git add src/renderer/components/Window.svelte
git commit -m "feat: wire SystemMap overlay into Window with Cmd+Shift+M"
```

---

### Task 8: Add cross-agent MCP tool parameter

**Files:**
- Modify: `mcp/memory_server.py`

- [ ] **Step 1: Update tool schema**

Find the `mcp` tool definition (around line 378). Add an `agent` property to the `properties` object:
```python
"agent": {
    "type": "string",
    "description": "Target agent name (optional - defaults to self. Requires system_access to target other agents).",
},
```

- [ ] **Step 2: Update activate handler**

In `handle_mcp_activate_server` (around line 2920), after `server_name` extraction, add agent resolution:
```python
    target_agent = args.get("agent", "").strip()
    current_agent = os.environ.get("AGENT", "xan")

    if target_agent and target_agent != current_agent:
        # Cross-agent: check system_access
        manifest, _ = _read_agent_manifest()
        router = manifest.get("router", {})
        if not router.get("system_access", False):
            return f"Error: {current_agent} does not have system_access. Cannot modify {target_agent}."
        # Read target agent's manifest instead
        target_dir = os.path.join(os.path.expanduser("~/.atrophy/agents"), target_agent, "data")
        target_path = os.path.join(target_dir, "agent.json")
        if not os.path.exists(target_path):
            return f"Error: agent '{target_agent}' not found."
        with open(target_path) as f:
            manifest = json.load(f)
        manifest_path = target_path
    else:
        target_agent = current_agent
        manifest, manifest_path = _read_agent_manifest()
```

Then update the rest of the function to use `manifest` and `manifest_path` (already the case) and `target_agent` in the response message.

- [ ] **Step 3: Update deactivate handler similarly**

Apply the same cross-agent logic to `handle_mcp_deactivate_server` (around line 2955).

- [ ] **Step 4: Syntax check**

Run: `python3 -c "import py_compile; py_compile.compile('mcp/memory_server.py', doraise=True)"`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add mcp/memory_server.py
git commit -m "feat: add cross-agent MCP tool parameter (requires system_access)"
```

---

### Task 9: Manual verification

- [ ] **Step 1: Build the app**

```bash
pnpm run dist:mac
```

- [ ] **Step 2: Install and launch**

```bash
osascript -e 'tell application "Atrophy" to quit'; sleep 3
rm -rf ~/Desktop/Atrophy.app
cp -R dist/mac-arm64/Atrophy.app ~/Desktop/Atrophy.app
open ~/Desktop/Atrophy.app
```

- [ ] **Step 3: Verify overlay opens**

Press `Cmd+Shift+M`. Expected: System Map overlay appears with three columns showing all agents and their services.

- [ ] **Step 4: Verify pill toggling**

Click an MCP pill to toggle it off. Expected: pill transitions to inactive state, restart banner appears.

- [ ] **Step 5: Verify detail card**

Cmd+click an MCP pill. Expected: detail card expands below showing description, type, status, capabilities, used-by list.

- [ ] **Step 6: Verify search**

Press `/`, type a server name. Expected: non-matching pills dim, matching pills stay bright.

- [ ] **Step 7: Verify Escape**

Press Escape. Expected: overlay closes.

- [ ] **Step 8: Run tests**

```bash
npx vitest run src/main/__tests__/system-topology.test.ts
```
Expected: all tests pass

- [ ] **Step 9: Final commit**

```bash
git add -A
git commit -m "feat: system map overlay - complete implementation"
```

---

### Task 10: Notarize and push

- [ ] **Step 1: Notarize**

```bash
xcrun notarytool submit "dist/Atrophy-$(node -p 'require("./package.json").version')-arm64.dmg" \
  --apple-id "will.lilley93@gmail.com" --team-id "5B68P8YVT8" \
  --password "oero-hgat-vlwy-qvuy" --wait

xcrun stapler staple "dist/Atrophy-$(node -p 'require("./package.json").version')-arm64.dmg"

xcrun notarytool submit "dist/Atrophy-$(node -p 'require("./package.json").version')-arm64-mac.zip" \
  --apple-id "will.lilley93@gmail.com" --team-id "5B68P8YVT8" \
  --password "oero-hgat-vlwy-qvuy" --wait
```

- [ ] **Step 2: Push**

```bash
git push origin main
```

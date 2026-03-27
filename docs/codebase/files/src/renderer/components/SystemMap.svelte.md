# src/renderer/components/SystemMap.svelte - System Topology Map

**Line count:** ~838 lines  
**Dependencies:** `svelte`, `../api`  
**Purpose:** Interactive system topology visualization showing agents, MCP servers, channels, and jobs

## Overview

This component provides an interactive visualization of the entire system topology, showing all agents, their MCP server configurations, channels, and scheduled jobs. Users can toggle MCP server connections and see which agents are using each server.

## Props

```typescript
interface Props {
  onClose: () => void;
}
```

## Types

### TopologyAgent

```typescript
interface TopologyAgent {
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
```

### TopologyServer

```typescript
interface TopologyServer {
  name: string;
  description: string;
  capabilities: string[];
  bundled: boolean;
  available: boolean;
  missingKey: boolean;
  missingCommand: boolean;
}
```

## State Variables

```typescript
let agents = $state<TopologyAgent[]>([]);
let servers = $state<TopologyServer[]>([]);
let selectedAgent = $state<string>('');
let searchQuery = $state('');
let searchFocused = $state(false);
let expandedGroups = $state<Record<string, Record<string, boolean>>>({});
let detailPill = $state<{ agent: string; server: string } | null>(null);
let pendingRestarts = $state<Set<string>>(new Set());
let loading = $state(true);
```

**Purpose:**
- `agents`, `servers`: Topology data
- `selectedAgent`: Currently selected agent for scrolling
- `searchQuery`: Agent/server search filter
- `expandedGroups`: Per-agent section expansion state
- `detailPill`: Ctrl-click detail view
- `pendingRestarts`: Agents needing restart after config change

## Data Fetching

### fetchTopology

```typescript
async function fetchTopology() {
  if (!api) { loading = false; return; }
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
```

**Purpose:** Load topology from main process.

**Default expansion:**
- MCP: Expanded if < 10 servers
- Channels: Always expanded
- Cron: Expanded if < 5 jobs

### onMount

```typescript
onMount(() => {
  fetchTopology();
});
```

## Interactions

### toggleMcp

```typescript
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
```

**Purpose:** Toggle MCP server connection for agent.

**Optimistic update:** Updates local state immediately, marks agent for restart if needed.

### toggleGroup

```typescript
function toggleGroup(agentName: string, group: string) {
  if (!expandedGroups[agentName]) expandedGroups[agentName] = {};
  expandedGroups[agentName][group] = !expandedGroups[agentName]?.[group];
  expandedGroups = { ...expandedGroups };  // Force reactivity
}
```

**Purpose:** Toggle section expansion (MCP, channels, cron).

### selectAgent

```typescript
function selectAgent(name: string) {
  selectedAgent = name;
  const el = document.getElementById(`agent-section-${name}`);
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
```

**Purpose:** Scroll to selected agent.

### toggleDetail

```typescript
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
```

**Purpose:** Ctrl-click for detail view, regular click to toggle.

### onKeydown

```typescript
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
    const input = document.getElementById('system-map-search');
    input?.focus();
  } else if (!searchFocused && e.key >= '1' && e.key <= '9') {
    const idx = parseInt(e.key) - 1;
    if (idx < agents.length) {
      selectAgent(agents[idx].name);
    }
  }
}
```

**Keyboard shortcuts:**
- `Escape`: Clear search or close
- `/`: Focus search
- `1-9`: Select agent by index

## Derived Functions

### matchesSearch

```typescript
function matchesSearch(name: string): boolean {
  if (!searchQuery) return true;
  return name.toLowerCase().includes(searchQuery.toLowerCase());
}
```

### serverInfo

```typescript
function serverInfo(name: string): TopologyServer | undefined {
  return servers.find(s => s.name === name);
}
```

### agentsUsing

```typescript
function agentsUsing(serverName: string): string[] {
  return agents.filter(a => a.mcp.active.includes(serverName))
    .map(a => a.displayName);
}
```

### allMcpForAgent

```typescript
function allMcpForAgent(agent: TopologyAgent): Array<{ 
  name: string; 
  active: boolean; 
  server?: TopologyServer; 
}> {
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
```

**Purpose:** Get all MCP servers for an agent (active + available).

## Template Structure

```svelte
<svelte:window on:keydown={onKeydown} />

<div class="overlay" onclick={onClose}>
  <div class="panel" onclick={(e) => e.stopPropagation()}>
    <div class="header">
      <span class="title">System Map</span>
      <div class="header-right">
        <input
          id="system-map-search"
          type="text"
          bind:value={searchQuery}
          bind:focused={searchFocused}
          placeholder="Search agents and servers..."
        />
        <button onclick={onClose}>✕</button>
      </div>
    </div>

    <div class="content">
      <!-- Server legend -->
      <div class="server-legend">
        {#each servers as server}
          <div class="legend-item" class:unavailable={!server.available}>
            <span class="legend-name">{server.name}</span>
            <span class="legend-desc">{server.description}</span>
          </div>
        {/each}
      </div>

      <!-- Agent sections -->
      {#each agents as agent}
        <div class="agent-section" id={`agent-section-${agent.name}`}>
          <div class="agent-header">
            <span class="agent-name">{agent.displayName}</span>
            <span class="agent-role">{agent.role}</span>
          </div>

          <!-- MCP section -->
          <div class="section">
            <button class="section-header" onclick={() => toggleGroup(agent.name, 'mcp')}>
              MCP Servers
              <span class="expand-icon}>{expandedGroups[agent.name]?.mcp ? '▼' : '▶'}</span>
            </button>
            
            {#if expandedGroups[agent.name]?.mcp}
              <div class="server-list">
                {#each allMcpForAgent(agent) as item}
                  <div 
                    class="server-item" 
                    class:active={item.active}
                    class:unavailable={!item.server?.available}
                    onclick={(e) => toggleDetail(agent.name, item.name, e)}
                  >
                    <span class="server-name">{item.name}</span>
                    <span class="server-status">
                      {#if item.active}Active{:else}Inactive{/if}
                    </span>
                  </div>
                {/each}
              </div>
            {/if}
          </div>

          <!-- Channels section -->
          <!-- Cron section -->
        </div>
      {/each}
    </div>

    <!-- Detail pill (Ctrl-click) -->
    {#if detailPill}
      <div class="detail-pill">
        <!-- Server details for specific agent -->
      </div>
    {/if}

    <!-- Pending restarts banner -->
    {#if pendingRestarts.size > 0}
      <div class="restart-banner">
        Restart needed for: {[...pendingRestarts].join(', ')}
      </div>
    {/if}
  </div>
</div>
```

## Styling

```css
.overlay {
  position: absolute;
  inset: 0;
  z-index: 100;
  background: rgba(0, 0, 0, 0.9);
  overflow-y: auto;
}

.panel {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.title {
  font-size: 24px;
  font-weight: 700;
  color: white;
}

.agent-section {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  margin-bottom: 20px;
  overflow: hidden;
}

.agent-header {
  display: flex;
  justify-content: space-between;
  padding: 16px 20px;
  background: rgba(255, 255, 255, 0.1);
}

.section-header {
  width: 100%;
  display: flex;
  justify-content: space-between;
  padding: 12px 20px;
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  text-align: left;
}

.server-list {
  padding: 0 20px 20px;
}

.server-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  margin: 4px 0;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 6px;
  cursor: pointer;
}

.server-item.active {
  background: rgba(74, 158, 255, 0.2);
}

.server-item.unavailable {
  opacity: 0.5;
}

.detail-pill {
  position: fixed;
  bottom: 20px;
  right: 20px;
  background: rgba(0, 0, 0, 0.9);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  max-width: 400px;
}

.restart-banner {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(255, 180, 50, 0.9);
  color: black;
  padding: 12px 20px;
  text-align: center;
}
```

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/components/Window.svelte` - Parent component
- `src/main/system-topology.ts` - Topology builder
- `src/main/ipc/system.ts` - system:getTopology, system:toggleConnection IPC

<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../../api';

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
    missingCommand: boolean;
  }

  let agents = $state<TopologyAgent[]>([]);
  let servers = $state<TopologyServer[]>([]);
  let selectedAgent = $state<string>('');
  let searchQuery = $state('');
  let loading = $state(true);
  let pendingRestarts = $state<Set<string>>(new Set());

  export async function load() { await fetchTopology(); }

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
    } finally {
      loading = false;
    }
  }

  async function toggleMcp(agentName: string, serverName: string) {
    if (!api) return;
    const agent = agents.find(a => a.name === agentName);
    if (!agent) return;
    const isActive = agent.mcp.active.includes(serverName);
    await api.toggleConnection(agentName, serverName, !isActive);
    pendingRestarts.add(agentName);
    pendingRestarts = pendingRestarts;
    await fetchTopology();
  }

  function matchesSearch(name: string): boolean {
    if (!searchQuery) return true;
    return name.toLowerCase().includes(searchQuery.toLowerCase());
  }

  function serverInfo(name: string): TopologyServer | undefined {
    return servers.find(s => s.name === name);
  }

  function allMcpForAgent(agent: TopologyAgent): Array<{ name: string; active: boolean; server?: TopologyServer }> {
    const result: Array<{ name: string; active: boolean; server?: TopologyServer }> = [];
    for (const name of agent.mcp.active) {
      result.push({ name, active: true, server: serverInfo(name) });
    }
    for (const s of servers) {
      if (!agent.mcp.active.includes(s.name)) {
        result.push({ name: s.name, active: false, server: s });
      }
    }
    return result;
  }

  onMount(() => { fetchTopology(); });
</script>

{#if loading}
  <div class="loading">Loading topology...</div>
{:else}
  <div class="search-row">
    <input
      type="text"
      class="search-input"
      placeholder="Filter services..."
      bind:value={searchQuery}
    />
  </div>

  <div class="columns">
    <!-- Agent list -->
    <div class="col-agents">
      {#each agents as agent}
        {#if matchesSearch(agent.name) || matchesSearch(agent.displayName)}
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <div
            class="agent-card"
            class:selected={selectedAgent === agent.name}
            onclick={() => selectedAgent = agent.name}
          >
            <div class="agent-card-name">{agent.displayName}</div>
            <div class="agent-card-role">{agent.role}</div>
            <div class="agent-card-stats">
              <span>{agent.mcp.active.length} MCP</span>
              <span>{Object.keys(agent.jobs).length} jobs</span>
              <span>{Object.keys(agent.channels).length} ch</span>
            </div>
            {#if pendingRestarts.has(agent.name)}
              <span class="restart-badge">restart needed</span>
            {/if}
          </div>
        {/if}
      {/each}
    </div>

    <!-- Selected agent detail -->
    <div class="col-detail">
      {#each agents.filter(a => a.name === selectedAgent) as agent}
        <div class="detail-header">
          <span class="detail-name">{agent.displayName}</span>
          <span class="detail-role">{agent.role}</span>
        </div>

        <div class="detail-section">
          <div class="detail-section-title">MCP Servers</div>
          {#each allMcpForAgent(agent) as { name, active, server }}
            {#if matchesSearch(name)}
              <div class="mcp-row">
                <button
                  class="mcp-toggle"
                  class:active
                  onclick={() => toggleMcp(agent.name, name)}
                >
                  <span class="mcp-dot"></span>
                </button>
                <div class="mcp-info">
                  <span class="mcp-name">{name}</span>
                  {#if server?.description}
                    <span class="mcp-desc">{server.description}</span>
                  {/if}
                </div>
                {#if server?.missingKey}
                  <span class="mcp-warn">missing key</span>
                {/if}
                {#if server?.missingCommand}
                  <span class="mcp-warn">not installed</span>
                {/if}
              </div>
            {/if}
          {/each}
        </div>

        <div class="detail-section">
          <div class="detail-section-title">Channels</div>
          {#each Object.entries(agent.channels) as [ch, cfg]}
            <div class="channel-row">
              <span class="channel-name">{ch}</span>
              <span class="channel-status" class:active={(cfg as Record<string, unknown>).enabled !== false}>
                {(cfg as Record<string, unknown>).enabled !== false ? 'active' : 'disabled'}
              </span>
            </div>
          {/each}
          {#if Object.keys(agent.channels).length === 0}
            <span class="empty">No channels</span>
          {/if}
        </div>

        <div class="detail-section">
          <div class="detail-section-title">Router</div>
          <div class="router-info">
            accept: {(agent.router.accept_from as string[] || ['*']).join(', ')}
            | queue: {agent.router.max_queue_depth || 10}
            {#if agent.router.system_access} | system access{/if}
          </div>
        </div>
      {/each}
    </div>
  </div>
{/if}

<style>
  .loading {
    color: var(--text-dim);
    text-align: center;
    padding: 40px;
    font-size: 13px;
  }

  .search-row {
    margin-bottom: 12px;
  }

  .search-input {
    width: 100%;
    height: 32px;
    padding: 0 10px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    color: white;
    font-size: 13px;
    outline: none;
    box-sizing: border-box;
  }

  .search-input::placeholder { color: rgba(255, 255, 255, 0.3); }

  .columns {
    display: flex;
    gap: 16px;
    min-height: 0;
  }

  .col-agents {
    width: 200px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    overflow-y: auto;
  }

  .col-detail {
    flex: 1;
    overflow-y: auto;
    min-width: 0;
  }

  .agent-card {
    padding: 8px 10px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.03);
    cursor: pointer;
    transition: background 0.15s;
  }

  .agent-card:hover { background: rgba(255, 255, 255, 0.06); }
  .agent-card.selected {
    background: rgba(100, 140, 255, 0.12);
    border-left: 2px solid rgba(100, 140, 255, 0.6);
  }

  .agent-card-name {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    font-weight: 600;
  }

  .agent-card-role {
    color: rgba(255, 255, 255, 0.35);
    font-size: 10px;
    margin-top: 2px;
  }

  .agent-card-stats {
    display: flex;
    gap: 8px;
    margin-top: 4px;
    font-size: 10px;
    color: rgba(255, 255, 255, 0.25);
  }

  .restart-badge {
    font-size: 9px;
    color: rgba(255, 180, 50, 0.8);
    background: rgba(255, 180, 50, 0.1);
    padding: 1px 5px;
    border-radius: 3px;
    margin-top: 4px;
    display: inline-block;
  }

  .detail-header {
    margin-bottom: 16px;
  }

  .detail-name {
    color: rgba(255, 255, 255, 0.9);
    font-size: 16px;
    font-weight: bold;
  }

  .detail-role {
    color: rgba(255, 255, 255, 0.4);
    font-size: 12px;
    margin-left: 8px;
  }

  .detail-section {
    margin-bottom: 16px;
  }

  .detail-section-title {
    color: rgba(255, 255, 255, 0.4);
    font-size: 10px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    margin-bottom: 6px;
  }

  .mcp-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
  }

  .mcp-toggle {
    width: 28px;
    height: 16px;
    border-radius: 8px;
    border: none;
    background: rgba(255, 255, 255, 0.1);
    cursor: pointer;
    position: relative;
    transition: background 0.2s;
    flex-shrink: 0;
  }

  .mcp-toggle.active {
    background: rgba(92, 224, 214, 0.4);
  }

  .mcp-dot {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.5);
    transition: transform 0.2s;
  }

  .mcp-toggle.active .mcp-dot {
    transform: translateX(12px);
    background: rgba(92, 224, 214, 0.9);
  }

  .mcp-info {
    flex: 1;
    min-width: 0;
  }

  .mcp-name {
    color: rgba(255, 255, 255, 0.7);
    font-size: 12px;
    font-weight: 500;
  }

  .mcp-desc {
    display: block;
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .mcp-warn {
    font-size: 9px;
    color: rgba(255, 150, 50, 0.7);
    background: rgba(255, 150, 50, 0.1);
    padding: 1px 5px;
    border-radius: 3px;
    flex-shrink: 0;
  }

  .channel-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
  }

  .channel-name {
    color: rgba(255, 255, 255, 0.6);
    font-size: 12px;
  }

  .channel-status {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 4px;
    background: rgba(255, 100, 100, 0.1);
    color: rgba(255, 100, 100, 0.6);
  }

  .channel-status.active {
    background: rgba(92, 224, 214, 0.1);
    color: rgba(92, 224, 214, 0.6);
  }

  .router-info {
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
  }

  .empty {
    color: rgba(255, 255, 255, 0.25);
    font-size: 11px;
    font-style: italic;
  }
</style>

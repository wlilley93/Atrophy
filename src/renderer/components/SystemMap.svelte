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
    missingCommand: boolean;
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

<svelte:window onkeydown={onKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="overlay" onclick={onClose}>
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="panel" onclick={(e) => e.stopPropagation()}>
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
    position: absolute;
    inset: 0;
    z-index: 55; /* Below Settings (60) and ask-overlay (90) */
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

<script lang="ts">
  /**
   * SystemMap - Hub-and-spoke system topology visualization.
   *
   * The switchboard sits at the centre. Everything radiates outward:
   *   - TOP: Channels (telegram, desktop, federation) - blue
   *   - LEFT: Agents (primary agents with avatars) - gold
   *   - RIGHT: MCP Servers (memory, shell, github, etc.) - green
   *   - BOTTOM: Internal sources (cron, MCP queue, system) - amber
   *
   * SVG bezier curves connect each node to the switchboard hub.
   * Hover highlights connections; click shows a detail card.
   */
  import { onMount } from 'svelte';
  import { api } from '../api';

  interface Props {
    onClose: () => void;
    /** When true, renders inline (fills parent) instead of as a fixed overlay. */
    inline?: boolean;
  }
  let { onClose, inline = false }: Props = $props();

  // ---------------------------------------------------------------------------
  // Topology types (mirror IPC shape)
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
  // Quadrant node type
  // ---------------------------------------------------------------------------

  type Quadrant = 'top' | 'left' | 'right' | 'bottom';

  interface MapNode {
    id: string;
    label: string;
    type: string; // badge text
    quadrant: Quadrant;
    meta?: string;
    active: boolean;
    error: boolean;
    avatarUrl?: string | null;
    // Back-reference for detail card
    agent?: TopologyAgent;
    server?: TopologyServer;
  }

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  let allAgents = $state<TopologyAgent[]>([]);
  let allServers = $state<TopologyServer[]>([]);
  let loading = $state(true);
  let hoveredId = $state<string | null>(null);
  let selectedNode = $state<MapNode | null>(null);
  let toggling = $state(false);

  // Element refs for SVG line computation
  let canvasEl = $state<HTMLDivElement | null>(null);
  let hubEl = $state<HTMLDivElement | null>(null);
  let nodeEls = $state<Record<string, HTMLDivElement>>({});
  let svgLines = $state<Array<{
    id: string;
    path: string;
    colour: string;
    active: boolean;
  }>>([]);

  // Agent avatar cache
  let avatarCache = $state<Record<string, string | null>>({});

  // ---------------------------------------------------------------------------
  // Quadrant colours
  // ---------------------------------------------------------------------------

  const COLOURS: Record<Quadrant, string> = {
    top: 'rgba(120, 200, 255, 0.85)',
    left: 'rgba(255, 200, 100, 0.85)',
    right: 'rgba(100, 220, 140, 0.85)',
    bottom: 'rgba(220, 160, 100, 0.85)',
  };

  const COLOURS_DIM: Record<Quadrant, string> = {
    top: 'rgba(120, 200, 255, 0.30)',
    left: 'rgba(255, 200, 100, 0.30)',
    right: 'rgba(100, 220, 140, 0.30)',
    bottom: 'rgba(220, 160, 100, 0.30)',
  };

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  async function fetchTopology() {
    if (!api) {
      loading = false;
      return;
    }
    loading = true;
    try {
      const topo = await api.getTopology();
      allAgents = topo.agents;
      allServers = topo.servers;
      // Load avatars in parallel
      for (const agent of topo.agents) {
        loadAvatar(agent.name);
      }
    } finally {
      loading = false;
    }
  }

  async function loadAvatar(name: string) {
    if (!api || avatarCache[name] !== undefined) return;
    try {
      const url = await api.getAgentAvatarStill(name);
      avatarCache = { ...avatarCache, [name]: url };
    } catch {
      avatarCache = { ...avatarCache, [name]: null };
    }
  }

  onMount(() => {
    fetchTopology();
  });

  // ---------------------------------------------------------------------------
  // Derived: build all map nodes from topology
  // ---------------------------------------------------------------------------

  const nodes = $derived.by((): MapNode[] => {
    const list: MapNode[] = [];

    // Collect all unique channels across all agents
    const channelSet = new Map<string, { name: string; agentCount: number }>();
    for (const agent of allAgents) {
      for (const ch of Object.keys(agent.channels)) {
        const existing = channelSet.get(ch);
        if (existing) {
          existing.agentCount++;
        } else {
          channelSet.set(ch, { name: ch, agentCount: 1 });
        }
      }
    }

    // Also check for federation in router config
    let hasFederation = false;
    for (const agent of allAgents) {
      const router = agent.router as Record<string, unknown>;
      if (router.federation || router.federated_links) {
        hasFederation = true;
        break;
      }
    }

    // TOP: Channels
    for (const [name, info] of channelSet) {
      const channelType = name === 'telegram' ? 'TELEGRAM' : name === 'desktop' ? 'DESKTOP' : name.toUpperCase();
      list.push({
        id: `ch-${name}`,
        label: name,
        type: channelType,
        quadrant: 'top',
        meta: `${info.agentCount} agent${info.agentCount !== 1 ? 's' : ''}`,
        active: true,
        error: false,
      });
    }

    if (hasFederation) {
      list.push({
        id: 'ch-federation',
        label: 'federation',
        type: 'FEDERATION',
        quadrant: 'top',
        meta: 'cross-instance',
        active: true,
        error: false,
      });
    }

    // LEFT: Agents
    for (const agent of allAgents) {
      const jobCount = Object.keys(agent.jobs).length;
      const toolCount = agent.mcp.active.length;
      const channelCount = Object.keys(agent.channels).length;
      list.push({
        id: `agent-${agent.name}`,
        label: agent.displayName,
        type: agent.role ? agent.role.toUpperCase() : 'AGENT',
        quadrant: 'left',
        meta: `${toolCount} tools, ${channelCount} ch, ${jobCount} jobs`,
        active: true,
        error: false,
        avatarUrl: avatarCache[agent.name],
        agent,
      });
    }

    // RIGHT: MCP Servers
    for (const server of allServers) {
      const usedByCount = allAgents.filter(
        (a) => a.mcp.active.includes(server.name) || a.mcp.include.includes(server.name),
      ).length;
      list.push({
        id: `mcp-${server.name}`,
        label: server.name,
        type: server.bundled ? 'BUNDLED' : 'EXTERNAL',
        quadrant: 'right',
        meta: server.available
          ? `${server.capabilities.length} caps, ${usedByCount} agent${usedByCount !== 1 ? 's' : ''}`
          : server.missingKey
            ? 'missing API key'
            : 'unavailable',
        active: server.available,
        error: server.missingKey || server.missingCommand,
        server,
      });
    }

    // BOTTOM: Internal sources
    // Cron scheduler
    const totalJobs = allAgents.reduce((sum, a) => sum + Object.keys(a.jobs).length, 0);
    if (totalJobs > 0) {
      list.push({
        id: 'internal-cron',
        label: 'cron scheduler',
        type: 'CRON',
        quadrant: 'bottom',
        meta: `${totalJobs} jobs across ${allAgents.filter((a) => Object.keys(a.jobs).length > 0).length} agents`,
        active: true,
        error: false,
      });
    }

    // MCP queue (always present)
    list.push({
      id: 'internal-mcp-queue',
      label: 'MCP queue',
      type: 'QUEUE',
      quadrant: 'bottom',
      meta: 'inter-agent messages',
      active: true,
      error: false,
    });

    // System address
    list.push({
      id: 'internal-system',
      label: 'system',
      type: 'SYSTEM',
      quadrant: 'bottom',
      meta: 'lifecycle events',
      active: true,
      error: false,
    });

    return list;
  });

  // Group nodes by quadrant for rendering
  const topNodes = $derived(nodes.filter((n) => n.quadrant === 'top'));
  const leftNodes = $derived(nodes.filter((n) => n.quadrant === 'left'));
  const rightNodes = $derived(nodes.filter((n) => n.quadrant === 'right'));
  const bottomNodes = $derived(nodes.filter((n) => n.quadrant === 'bottom'));

  // ---------------------------------------------------------------------------
  // SVG line computation
  // ---------------------------------------------------------------------------

  function computeLines() {
    if (!canvasEl || !hubEl) return;

    const canvasRect = canvasEl.getBoundingClientRect();
    const hubRect = hubEl.getBoundingClientRect();

    const hubCx = hubRect.left + hubRect.width / 2 - canvasRect.left;
    const hubCy = hubRect.top + hubRect.height / 2 - canvasRect.top;

    const lines: typeof svgLines = [];

    for (const node of nodes) {
      const el = nodeEls[node.id];
      if (!el) continue;

      const rect = el.getBoundingClientRect();
      let nodeCx: number;
      let nodeCy: number;

      // Connect from the edge of the node closest to the hub
      if (node.quadrant === 'top') {
        nodeCx = rect.left + rect.width / 2 - canvasRect.left;
        nodeCy = rect.bottom - canvasRect.top;
      } else if (node.quadrant === 'bottom') {
        nodeCx = rect.left + rect.width / 2 - canvasRect.left;
        nodeCy = rect.top - canvasRect.top;
      } else if (node.quadrant === 'left') {
        nodeCx = rect.right - canvasRect.left;
        nodeCy = rect.top + rect.height / 2 - canvasRect.top;
      } else {
        nodeCx = rect.left - canvasRect.left;
        nodeCy = rect.top + rect.height / 2 - canvasRect.top;
      }

      // Bezier control points - pull toward the hub axis
      let cp1x: number, cp1y: number, cp2x: number, cp2y: number;
      const dx = hubCx - nodeCx;
      const dy = hubCy - nodeCy;

      if (node.quadrant === 'top' || node.quadrant === 'bottom') {
        cp1x = nodeCx;
        cp1y = nodeCy + dy * 0.45;
        cp2x = hubCx;
        cp2y = hubCy - dy * 0.25;
      } else {
        cp1x = nodeCx + dx * 0.45;
        cp1y = nodeCy;
        cp2x = hubCx - dx * 0.25;
        cp2y = hubCy;
      }

      const path = `M ${nodeCx} ${nodeCy} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${hubCx} ${hubCy}`;

      lines.push({
        id: node.id,
        path,
        colour: COLOURS_DIM[node.quadrant],
        active: node.active,
      });
    }

    svgLines = lines;
  }

  // Recompute lines when nodes change or on resize
  $effect(() => {
    // Track dependencies
    void nodes.length;
    void loading;
    // Use a small delay to let DOM settle
    const timer = setTimeout(computeLines, 60);
    return () => clearTimeout(timer);
  });

  // Resize observer
  let resizeObserver: ResizeObserver | null = null;

  $effect(() => {
    if (!canvasEl) return;
    resizeObserver = new ResizeObserver(() => {
      computeLines();
    });
    resizeObserver.observe(canvasEl);
    return () => {
      resizeObserver?.disconnect();
      resizeObserver = null;
    };
  });

  // ---------------------------------------------------------------------------
  // Interaction
  // ---------------------------------------------------------------------------

  function onNodeHover(id: string | null) {
    hoveredId = id;
  }

  function onNodeClick(node: MapNode) {
    if (selectedNode?.id === node.id) {
      selectedNode = null;
    } else {
      selectedNode = node;
    }
  }

  function lineOpacity(lineId: string): number {
    if (!hoveredId) return 1;
    return lineId === hoveredId ? 1 : 0.15;
  }

  function lineStrokeWidth(lineId: string): number {
    if (hoveredId === lineId) return 2.5;
    return 1.5;
  }

  function lineColour(line: typeof svgLines[0]): string {
    if (!hoveredId) return line.colour;
    if (line.id === hoveredId) {
      // Find the node and return the bright colour
      const node = nodes.find((n) => n.id === line.id);
      return node ? COLOURS[node.quadrant] : line.colour;
    }
    return line.colour;
  }

  function nodeOpacity(nodeId: string): number {
    if (!hoveredId) return 1;
    return nodeId === hoveredId ? 1 : 0.35;
  }

  function statusDotColour(node: MapNode): string {
    if (node.error) return 'rgba(255, 100, 100, 0.9)';
    if (!node.active) return 'rgba(140, 140, 140, 0.6)';
    return 'rgba(80, 210, 100, 0.85)';
  }

  // ---------------------------------------------------------------------------
  // Detail card: MCP toggle
  // ---------------------------------------------------------------------------

  async function handleToggle(agentName: string, serverName: string, enable: boolean) {
    if (!api || toggling) return;
    toggling = true;
    try {
      const result = await api.toggleConnection(agentName, serverName, enable);
      if (result.success) {
        // Re-fetch topology to reflect the change
        await fetchTopology();
        // If the selected node was a server, refresh it
        if (selectedNode?.server) {
          const updated = nodes.find((n) => n.id === selectedNode!.id);
          if (updated) selectedNode = updated;
        }
      }
    } finally {
      toggling = false;
    }
  }

  // Which agents use a given server
  function agentsUsingServer(serverName: string): TopologyAgent[] {
    return allAgents.filter(
      (a) => a.mcp.active.includes(serverName) || a.mcp.include.includes(serverName),
    );
  }

  // ---------------------------------------------------------------------------
  // Keyboard
  // ---------------------------------------------------------------------------

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      if (selectedNode) {
        selectedNode = null;
        e.preventDefault();
      } else {
        onClose();
        e.preventDefault();
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Ref binding helper (Svelte action)
  // ---------------------------------------------------------------------------

  function bindNodeRef(el: HTMLDivElement, id: string) {
    nodeEls[id] = el;
    return {
      update(newId: string) {
        nodeEls[newId] = el;
      },
      destroy() {
        delete nodeEls[id];
      },
    };
  }
</script>

<svelte:window onkeydown={(e) => { if (!inline) onKeydown(e); }} />

{#if !inline}
  <div class="overlay" onclick={onClose} role="presentation"></div>
{/if}

<div class={inline ? 'panel panel-inline' : 'panel panel-overlay'} onclick={(e) => e.stopPropagation()} role="presentation">
  <header class="panel-header">
    <div class="title-block">
      <span class="title">System Map</span>
      <span class="title-sub">Switchboard Topology</span>
    </div>
    <div class="header-right">
      <span class="node-count">{nodes.length} nodes</span>
      {#if !inline}
        <button class="close-btn" onclick={onClose} aria-label="Close">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </button>
      {/if}
    </div>
  </header>

    {#if loading}
      <div class="loading">
        <div class="loading-spinner"></div>
        <span>Loading topology...</span>
      </div>
    {:else}
      <div class="canvas" bind:this={canvasEl}>
        <!-- SVG connector overlay -->
        <svg class="svg-overlay" aria-hidden="true">
          {#each svgLines as line (line.id)}
            <path
              d={line.path}
              fill="none"
              stroke={lineColour(line)}
              stroke-width={lineStrokeWidth(line.id)}
              stroke-dasharray={line.active ? 'none' : '6 4'}
              opacity={lineOpacity(line.id)}
              style="transition: opacity 0.25s, stroke 0.25s, stroke-width 0.2s;"
            />
          {/each}
        </svg>

        <!-- TOP: Channels -->
        <div class="quadrant quadrant-top">
          <div class="quadrant-label" style="color: {COLOURS.top}">CHANNELS</div>
          <div class="node-row">
            {#each topNodes as node (node.id)}
              <div
                class="node-card"
                style="--accent: {COLOURS.top}; opacity: {nodeOpacity(node.id)}"
                use:bindNodeRef={node.id}
                onmouseenter={() => onNodeHover(node.id)}
                onmouseleave={() => onNodeHover(null)}
                onclick={() => onNodeClick(node)}
                role="button"
                tabindex="0"
                onkeydown={(e) => e.key === 'Enter' && onNodeClick(node)}
              >
                <div class="node-header">
                  <span class="node-badge" style="color: {COLOURS.top}">{node.type}</span>
                  <span class="status-dot" style="background: {statusDotColour(node)}"></span>
                </div>
                <span class="node-name">{node.label}</span>
                {#if node.meta}
                  <span class="node-meta">{node.meta}</span>
                {/if}
              </div>
            {/each}
          </div>
        </div>

        <!-- Middle row: LEFT agents | HUB | RIGHT servers -->
        <div class="middle-row">
          <!-- LEFT: Agents -->
          <div class="quadrant quadrant-left">
            <div class="quadrant-label" style="color: {COLOURS.left}">AGENTS</div>
            <div class="node-column">
              {#each leftNodes as node (node.id)}
                <div
                  class="node-card agent-node"
                  style="--accent: {COLOURS.left}; opacity: {nodeOpacity(node.id)}"
                  use:bindNodeRef={node.id}
                  onmouseenter={() => onNodeHover(node.id)}
                  onmouseleave={() => onNodeHover(null)}
                  onclick={() => onNodeClick(node)}
                  role="button"
                  tabindex="0"
                  onkeydown={(e) => e.key === 'Enter' && onNodeClick(node)}
                >
                  <div class="agent-row-inner">
                    <div class="agent-avatar-small">
                      {#if node.avatarUrl}
                        <img src={node.avatarUrl} alt="{node.label}" />
                      {:else}
                        <svg viewBox="0 0 32 32" fill="none">
                          <circle cx="16" cy="12" r="5" fill="rgba(255,200,100,0.3)"/>
                          <path d="M6 28 C 6 22, 10 19, 16 19 C 22 19, 26 22, 26 28 Z" fill="rgba(255,200,100,0.2)"/>
                        </svg>
                      {/if}
                    </div>
                    <div class="agent-info">
                      <div class="node-header">
                        <span class="node-badge" style="color: {COLOURS.left}">{node.type}</span>
                        <span class="status-dot" style="background: {statusDotColour(node)}"></span>
                      </div>
                      <span class="node-name">{node.label}</span>
                      {#if node.meta}
                        <span class="node-meta">{node.meta}</span>
                      {/if}
                    </div>
                  </div>
                </div>
              {/each}
            </div>
          </div>

          <!-- HUB: Switchboard -->
          <div class="hub-container">
            <div class="hub" bind:this={hubEl}>
              <div class="hub-icon">
                <svg viewBox="0 0 48 48" fill="none">
                  <!-- Central nexus -->
                  <circle cx="24" cy="24" r="6" fill="rgba(255,255,255,0.15)" stroke="rgba(255,255,255,0.4)" stroke-width="1"/>
                  <!-- Radiating lines -->
                  <line x1="24" y1="6" x2="24" y2="16" stroke="rgba(120,200,255,0.5)" stroke-width="1.5" stroke-linecap="round"/>
                  <line x1="24" y1="32" x2="24" y2="42" stroke="rgba(220,160,100,0.5)" stroke-width="1.5" stroke-linecap="round"/>
                  <line x1="6" y1="24" x2="16" y2="24" stroke="rgba(255,200,100,0.5)" stroke-width="1.5" stroke-linecap="round"/>
                  <line x1="32" y1="24" x2="42" y2="24" stroke="rgba(100,220,140,0.5)" stroke-width="1.5" stroke-linecap="round"/>
                  <!-- Diagonal paths -->
                  <line x1="11" y1="11" x2="18" y2="18" stroke="rgba(255,255,255,0.15)" stroke-width="1" stroke-linecap="round"/>
                  <line x1="30" y1="18" x2="37" y2="11" stroke="rgba(255,255,255,0.15)" stroke-width="1" stroke-linecap="round"/>
                  <line x1="11" y1="37" x2="18" y2="30" stroke="rgba(255,255,255,0.15)" stroke-width="1" stroke-linecap="round"/>
                  <line x1="30" y1="30" x2="37" y2="37" stroke="rgba(255,255,255,0.15)" stroke-width="1" stroke-linecap="round"/>
                  <!-- Inner dots -->
                  <circle cx="24" cy="24" r="2" fill="rgba(255,255,255,0.6)"/>
                </svg>
              </div>
              <span class="hub-label">SWITCHBOARD</span>
              <span class="hub-meta">{allAgents.length} agents, {allServers.length} servers</span>
            </div>
          </div>

          <!-- RIGHT: MCP Servers -->
          <div class="quadrant quadrant-right">
            <div class="quadrant-label" style="color: {COLOURS.right}">MCP SERVERS</div>
            <div class="node-column">
              {#each rightNodes as node (node.id)}
                <div
                  class="node-card"
                  style="--accent: {COLOURS.right}; opacity: {nodeOpacity(node.id)}"
                  class:node-error={node.error}
                  class:node-inactive={!node.active}
                  use:bindNodeRef={node.id}
                  onmouseenter={() => onNodeHover(node.id)}
                  onmouseleave={() => onNodeHover(null)}
                  onclick={() => onNodeClick(node)}
                  role="button"
                  tabindex="0"
                  onkeydown={(e) => e.key === 'Enter' && onNodeClick(node)}
                >
                  <div class="node-header">
                    <span class="node-badge" style="color: {node.error ? 'rgba(255, 180, 80, 0.9)' : COLOURS.right}">
                      {node.type}
                    </span>
                    <span class="status-dot" style="background: {statusDotColour(node)}"></span>
                  </div>
                  <span class="node-name">{node.label}</span>
                  {#if node.meta}
                    <span class="node-meta">{node.meta}</span>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        </div>

        <!-- BOTTOM: Internal Sources -->
        <div class="quadrant quadrant-bottom">
          <div class="quadrant-label" style="color: {COLOURS.bottom}">INTERNAL</div>
          <div class="node-row">
            {#each bottomNodes as node (node.id)}
              <div
                class="node-card"
                style="--accent: {COLOURS.bottom}; opacity: {nodeOpacity(node.id)}"
                use:bindNodeRef={node.id}
                onmouseenter={() => onNodeHover(node.id)}
                onmouseleave={() => onNodeHover(null)}
                onclick={() => onNodeClick(node)}
                role="button"
                tabindex="0"
                onkeydown={(e) => e.key === 'Enter' && onNodeClick(node)}
              >
                <div class="node-header">
                  <span class="node-badge" style="color: {COLOURS.bottom}">{node.type}</span>
                  <span class="status-dot" style="background: {statusDotColour(node)}"></span>
                </div>
                <span class="node-name">{node.label}</span>
                {#if node.meta}
                  <span class="node-meta">{node.meta}</span>
                {/if}
              </div>
            {/each}
          </div>
        </div>
      </div>

      <!-- Detail card overlay -->
      {#if selectedNode}
        <div class="detail-backdrop" onclick={() => (selectedNode = null)} role="presentation"></div>
        <div class="detail-card" style="--detail-accent: {COLOURS[selectedNode.quadrant]}">
          <div class="detail-header">
            <div class="detail-title-row">
              {#if selectedNode.avatarUrl}
                <div class="detail-avatar">
                  <img src={selectedNode.avatarUrl} alt={selectedNode.label} />
                </div>
              {/if}
              <div class="detail-title-col">
                <span class="detail-badge" style="color: {COLOURS[selectedNode.quadrant]}">{selectedNode.type}</span>
                <span class="detail-name">{selectedNode.label}</span>
              </div>
              <button class="detail-close" onclick={() => (selectedNode = null)} aria-label="Close detail">
                <svg width="12" height="12" viewBox="0 0 14 14" fill="none">
                  <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
              </button>
            </div>
            <span class="detail-status" style="color: {statusDotColour(selectedNode)}">
              {selectedNode.error ? 'Error' : selectedNode.active ? 'Active' : 'Inactive'}
            </span>
          </div>

          <!-- Server detail -->
          {#if selectedNode.server}
            {@const srv = selectedNode.server}
            <div class="detail-section">
              <span class="detail-section-label">Description</span>
              <p class="detail-desc">{srv.description || 'No description'}</p>
            </div>
            {#if srv.capabilities.length > 0}
              <div class="detail-section">
                <span class="detail-section-label">Capabilities ({srv.capabilities.length})</span>
                <div class="detail-caps">
                  {#each srv.capabilities as cap}
                    <span class="detail-cap-pill">{cap}</span>
                  {/each}
                </div>
              </div>
            {/if}
            <div class="detail-section">
              <span class="detail-section-label">Used by agents</span>
              <div class="detail-agents-list">
                {#each agentsUsingServer(srv.name) as agent}
                  {@const isActive = agent.mcp.active.includes(srv.name)}
                  <div class="detail-agent-row">
                    <span class="detail-agent-name">{agent.displayName}</span>
                    <span class="detail-agent-status" class:active={isActive}>
                      {isActive ? 'active' : 'configured'}
                    </span>
                    <button
                      class="detail-toggle-btn"
                      class:toggled-on={isActive}
                      disabled={toggling}
                      onclick={() => handleToggle(agent.name, srv.name, !isActive)}
                    >
                      {isActive ? 'Disable' : 'Enable'}
                    </button>
                  </div>
                {/each}
                {#if agentsUsingServer(srv.name).length === 0}
                  <span class="detail-empty">Not configured for any agent</span>
                {/if}
              </div>
            </div>
          {/if}

          <!-- Agent detail -->
          {#if selectedNode.agent}
            {@const ag = selectedNode.agent}
            <div class="detail-section">
              <span class="detail-section-label">Role</span>
              <p class="detail-desc">{ag.role || 'No role defined'}</p>
            </div>
            <div class="detail-section">
              <span class="detail-section-label">Channels ({Object.keys(ag.channels).length})</span>
              <div class="detail-caps">
                {#each Object.keys(ag.channels) as ch}
                  <span class="detail-cap-pill">{ch}</span>
                {/each}
                {#if Object.keys(ag.channels).length === 0}
                  <span class="detail-empty">No channels</span>
                {/if}
              </div>
            </div>
            <div class="detail-section">
              <span class="detail-section-label">Active MCP Servers ({ag.mcp.active.length})</span>
              <div class="detail-caps">
                {#each ag.mcp.active as srv}
                  <span class="detail-cap-pill mcp-pill">{srv}</span>
                {/each}
                {#if ag.mcp.active.length === 0}
                  <span class="detail-empty">No active servers</span>
                {/if}
              </div>
            </div>
            {#if Object.keys(ag.jobs).length > 0}
              <div class="detail-section">
                <span class="detail-section-label">Cron Jobs ({Object.keys(ag.jobs).length})</span>
                <div class="detail-caps">
                  {#each Object.keys(ag.jobs) as job}
                    <span class="detail-cap-pill job-pill">{job}</span>
                  {/each}
                </div>
              </div>
            {/if}
          {/if}

          <!-- Channel/Internal detail (no server or agent) -->
          {#if !selectedNode.server && !selectedNode.agent}
            <div class="detail-section">
              <span class="detail-section-label">Type</span>
              <p class="detail-desc">{selectedNode.type.toLowerCase()} - {selectedNode.meta || 'system component'}</p>
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </div>

<style>
  /* ======================================================================
   * Overlay + Panel shell
   * ====================================================================== */

  /* Inline mode: fills parent instead of floating */
  .panel-inline {
    position: relative;
    width: 100%;
    height: 100%;
    border: none;
    border-radius: 0;
    box-shadow: none;
    background: transparent;
  }

  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    z-index: 200;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  .panel {
    width: min(1180px, calc(100% - 48px));
    height: min(880px, calc(100vh - 60px));
    background: rgba(20, 20, 24, 0.98);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 14px;
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.7);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    position: relative;
  }

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 18px 24px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    flex-shrink: 0;
    background: linear-gradient(180deg, rgba(255,255,255,0.02), transparent);
  }

  .title-block {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .title {
    color: rgba(255, 255, 255, 0.45);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
  }

  .title-sub {
    color: rgba(255, 255, 255, 0.95);
    font-size: 17px;
    font-weight: 600;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .node-count {
    color: rgba(255, 255, 255, 0.35);
    font-size: 12px;
  }

  .close-btn {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.6);
    cursor: pointer;
    padding: 6px;
    border-radius: 6px;
    display: inline-flex;
    transition: color 0.15s, background 0.15s;
  }

  .close-btn:hover {
    color: rgba(255, 255, 255, 0.95);
    background: rgba(255, 255, 255, 0.08);
  }

  /* ======================================================================
   * Loading
   * ====================================================================== */

  .loading {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    color: rgba(255, 255, 255, 0.4);
    font-size: 13px;
  }

  .loading-spinner {
    width: 28px;
    height: 28px;
    border: 2px solid rgba(255, 255, 255, 0.08);
    border-top-color: rgba(255, 255, 255, 0.35);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* ======================================================================
   * Canvas - the main topology area
   * ====================================================================== */

  .canvas {
    flex: 1;
    min-height: 0;
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 24px 28px;
    overflow: auto;
    gap: 0;
  }

  .canvas::-webkit-scrollbar {
    width: 6px;
  }

  .canvas::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 3px;
  }

  /* SVG overlay for connector lines */
  .svg-overlay {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    z-index: 0;
  }

  /* ======================================================================
   * Quadrant layout
   * ====================================================================== */

  .quadrant {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    z-index: 1;
    position: relative;
  }

  .quadrant-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
  }

  .quadrant-top {
    margin-bottom: 16px;
  }

  .quadrant-bottom {
    margin-top: 16px;
  }

  .node-row {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 10px;
  }

  .node-column {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* Middle row: agents | hub | servers */
  .middle-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0;
    width: 100%;
    position: relative;
    z-index: 1;
  }

  .quadrant-left {
    flex: 1;
    align-items: flex-end;
    max-width: 300px;
    padding-right: 24px;
  }

  .quadrant-left .node-column {
    align-items: flex-end;
  }

  .quadrant-right {
    flex: 1;
    align-items: flex-start;
    max-width: 300px;
    padding-left: 24px;
  }

  .quadrant-right .node-column {
    align-items: flex-start;
  }

  /* ======================================================================
   * Hub (switchboard centre)
   * ====================================================================== */

  .hub-container {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px 20px;
  }

  .hub {
    width: 160px;
    height: 160px;
    border-radius: 50%;
    background: radial-gradient(
      circle at center,
      rgba(255, 255, 255, 0.06) 0%,
      rgba(255, 255, 255, 0.02) 60%,
      transparent 100%
    );
    border: 1.5px solid rgba(255, 255, 255, 0.18);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    position: relative;
    animation: hubPulse 3s ease-in-out infinite;
    box-shadow:
      0 0 40px rgba(255, 255, 255, 0.04),
      0 0 80px rgba(120, 180, 255, 0.03);
  }

  @keyframes hubPulse {
    0%, 100% {
      border-color: rgba(255, 255, 255, 0.18);
      box-shadow:
        0 0 40px rgba(255, 255, 255, 0.04),
        0 0 80px rgba(120, 180, 255, 0.03);
    }
    50% {
      border-color: rgba(255, 255, 255, 0.30);
      box-shadow:
        0 0 50px rgba(255, 255, 255, 0.07),
        0 0 100px rgba(120, 180, 255, 0.06);
    }
  }

  .hub-icon {
    width: 48px;
    height: 48px;
    opacity: 0.85;
  }

  .hub-icon svg {
    width: 100%;
    height: 100%;
  }

  .hub-label {
    color: rgba(255, 255, 255, 0.75);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
  }

  .hub-meta {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
  }

  /* ======================================================================
   * Node cards
   * ====================================================================== */

  .node-card {
    --accent: rgba(180, 180, 200, 0.7);
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 120px;
    max-width: 190px;
    padding: 9px 12px 10px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.2s, transform 0.15s, opacity 0.25s;
    position: relative;
  }

  .node-card:hover {
    background: rgba(255, 255, 255, 0.07);
    border-color: var(--accent);
    transform: translateY(-1px);
  }

  .node-card.node-inactive {
    opacity: 0.5;
  }

  .node-card.node-error {
    border-color: rgba(255, 140, 60, 0.3);
  }

  .node-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
  }

  .node-badge {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }

  .status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .node-name {
    color: rgba(255, 255, 255, 0.92);
    font-size: 12.5px;
    font-weight: 600;
    word-break: break-word;
    line-height: 1.3;
  }

  .node-meta {
    color: rgba(255, 255, 255, 0.38);
    font-size: 10.5px;
    line-height: 1.3;
  }

  /* ======================================================================
   * Agent node (with avatar)
   * ====================================================================== */

  .agent-node {
    min-width: 170px;
    max-width: 240px;
    padding: 8px 10px 9px;
  }

  .agent-row-inner {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .agent-avatar-small {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    overflow: hidden;
    flex-shrink: 0;
    background: rgba(255, 200, 100, 0.06);
    border: 1.5px solid rgba(255, 200, 100, 0.25);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .agent-avatar-small img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .agent-avatar-small svg {
    width: 70%;
    height: 70%;
  }

  .agent-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1;
  }

  .agent-info .node-name {
    font-size: 12px;
  }

  .agent-info .node-meta {
    font-size: 10px;
  }

  /* ======================================================================
   * Detail card (floating panel on click)
   * ====================================================================== */

  .detail-backdrop {
    position: absolute;
    inset: 0;
    z-index: 10;
  }

  .detail-card {
    --detail-accent: rgba(180, 180, 200, 0.7);
    position: absolute;
    right: 24px;
    top: 80px;
    width: 320px;
    max-height: calc(100% - 100px);
    overflow-y: auto;
    background: rgba(28, 28, 32, 0.98);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
    box-shadow: 0 16px 60px rgba(0, 0, 0, 0.6), 0 0 1px rgba(255, 255, 255, 0.1);
    z-index: 11;
    padding: 18px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .detail-card::-webkit-scrollbar {
    width: 4px;
  }

  .detail-card::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 2px;
  }

  .detail-header {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .detail-title-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .detail-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    overflow: hidden;
    flex-shrink: 0;
    border: 1.5px solid var(--detail-accent);
  }

  .detail-avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .detail-title-col {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
  }

  .detail-badge {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }

  .detail-name {
    color: rgba(255, 255, 255, 0.95);
    font-size: 16px;
    font-weight: 600;
  }

  .detail-close {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.5);
    cursor: pointer;
    padding: 5px;
    border-radius: 5px;
    display: inline-flex;
    align-self: flex-start;
    transition: color 0.15s, background 0.15s;
  }

  .detail-close:hover {
    color: rgba(255, 255, 255, 0.9);
    background: rgba(255, 255, 255, 0.08);
  }

  .detail-status {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.3px;
  }

  .detail-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .detail-section-label {
    color: rgba(255, 255, 255, 0.4);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }

  .detail-desc {
    color: rgba(255, 255, 255, 0.7);
    font-size: 12px;
    line-height: 1.5;
    margin: 0;
  }

  .detail-caps {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .detail-cap-pill {
    font-size: 10.5px;
    color: rgba(255, 255, 255, 0.65);
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 4px;
    padding: 2px 7px;
  }

  .detail-cap-pill.mcp-pill {
    border-color: rgba(100, 220, 140, 0.2);
    color: rgba(100, 220, 140, 0.75);
  }

  .detail-cap-pill.job-pill {
    border-color: rgba(220, 160, 100, 0.2);
    color: rgba(220, 160, 100, 0.75);
  }

  .detail-agents-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .detail-agent-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 8px;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 5px;
  }

  .detail-agent-name {
    color: rgba(255, 255, 255, 0.8);
    font-size: 12px;
    font-weight: 500;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .detail-agent-status {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.35);
    font-weight: 600;
    letter-spacing: 0.3px;
  }

  .detail-agent-status.active {
    color: rgba(80, 210, 100, 0.7);
  }

  .detail-toggle-btn {
    font-size: 10px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 4px;
    cursor: pointer;
    border: 1px solid rgba(255, 255, 255, 0.12);
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.6);
    transition: background 0.15s, color 0.15s, border-color 0.15s;
    font-family: inherit;
    flex-shrink: 0;
  }

  .detail-toggle-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.9);
    border-color: rgba(255, 255, 255, 0.2);
  }

  .detail-toggle-btn:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .detail-toggle-btn.toggled-on {
    border-color: rgba(255, 100, 100, 0.3);
    color: rgba(255, 140, 140, 0.8);
  }

  .detail-toggle-btn.toggled-on:hover:not(:disabled) {
    background: rgba(255, 80, 80, 0.1);
    border-color: rgba(255, 100, 100, 0.5);
  }

  .detail-empty {
    color: rgba(255, 255, 255, 0.25);
    font-size: 11px;
    font-style: italic;
  }
</style>

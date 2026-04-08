<script lang="ts">
  /**
   * SystemMap - focused single-agent view in organagram style.
   *
   * Centred on one agent (the active one by default, or user-picked from
   * the dropdown). Shows:
   *   - INPUTS row at top: channels and switchboard sources flowing IN
   *   - AGENT card in the middle (the focal point)
   *   - TOOLS row below: MCP servers the agent can call OUT to
   *   - SUBAGENTS row: tier 2+ agents this one can dispatch to (only
   *     for tier-1 leaders with cans_provision)
   *   - CRON row: scheduled jobs the agent runs autonomously
   *
   * Visual style matches the OrgChart component used in Settings > Agents:
   * rounded cards, tier-coloured borders, vertical connector lines.
   */
  import { onMount } from 'svelte';
  import { api } from '../api';
  import { agents as agentsStore } from '../stores/agents.svelte';

  interface Props {
    onClose: () => void;
  }
  let { onClose }: Props = $props();

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
  // State
  // ---------------------------------------------------------------------------

  let allAgents = $state<TopologyAgent[]>([]);
  let servers = $state<TopologyServer[]>([]);
  let selectedName = $state<string>('');
  let loading = $state(true);
  let avatarUrl = $state<string | null>(null);

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
      servers = topo.servers;
      // Default to the currently active agent in the rolodex
      const fallback = agentsStore.current || allAgents[0]?.name || '';
      if (!selectedName) {
        selectedName = allAgents.find((a) => a.name === fallback)?.name || allAgents[0]?.name || '';
      }
    } finally {
      loading = false;
    }
  }

  async function loadAvatar(name: string) {
    if (!api || !name) {
      avatarUrl = null;
      return;
    }
    try {
      avatarUrl = await api.getAgentAvatarStill(name);
    } catch {
      avatarUrl = null;
    }
  }

  // Re-fetch avatar when the selected agent changes
  $effect(() => {
    void loadAvatar(selectedName);
  });

  onMount(fetchTopology);

  // ---------------------------------------------------------------------------
  // Derived view of the focused agent
  // ---------------------------------------------------------------------------

  const focused = $derived(allAgents.find((a) => a.name === selectedName) || null);

  // Channels are the inputs - things that send messages TO the agent.
  // The switchboard also injects cron and federation envelopes addressed
  // to the agent, so we represent those as virtual inputs whenever the
  // agent has cron jobs / federation links configured.
  const inputs = $derived.by(() => {
    if (!focused) return [];
    const list: Array<{ key: string; label: string; kind: string; meta?: string }> = [];

    // Channels (telegram, desktop, etc.) come straight from the manifest
    for (const [name, _cfg] of Object.entries(focused.channels)) {
      list.push({ key: `ch-${name}`, label: name, kind: 'channel' });
    }

    // Cron implicitly creates an input pathway via cron:<agent> in the
    // switchboard, even though jobs aren't channels in the strict sense.
    if (Object.keys(focused.jobs).length > 0) {
      list.push({
        key: 'cron-source',
        label: 'cron',
        kind: 'cron-source',
        meta: `${Object.keys(focused.jobs).length} jobs`,
      });
    }

    // The switchboard itself is the universal input rail
    list.push({ key: 'switchboard', label: 'switchboard', kind: 'system' });

    return list;
  });

  // Tools are the MCP servers this agent can call. Active first, then any
  // additional configured servers that aren't currently active.
  const tools = $derived.by(() => {
    if (!focused) return [];
    const list: Array<{ name: string; active: boolean; server?: TopologyServer }> = [];
    const active = new Set(focused.mcp.active);
    for (const name of focused.mcp.active) {
      list.push({ name, active: true, server: servers.find((s) => s.name === name) });
    }
    // Configured but not currently active
    for (const name of focused.mcp.include) {
      if (!active.has(name)) {
        list.push({ name, active: false, server: servers.find((s) => s.name === name) });
      }
    }
    return list;
  });

  // Cron jobs as a flat list for the auxiliary section
  const cronJobs = $derived.by(() => {
    if (!focused) return [];
    return Object.entries(focused.jobs).map(([name, def]) => {
      const d = (def || {}) as { cron?: string; interval_seconds?: number; description?: string };
      let schedule = '';
      if (d.cron) schedule = d.cron;
      else if (d.interval_seconds) {
        const s = d.interval_seconds;
        if (s >= 3600) schedule = `every ${Math.round(s / 3600)}h`;
        else if (s >= 60) schedule = `every ${Math.round(s / 60)}m`;
        else schedule = `every ${s}s`;
      }
      return { name, schedule, description: d.description || '' };
    });
  });

  // Subagents this agent can dispatch to (other tier-1+ agents with the
  // same org slug, when the focused agent has provisioning rights). For
  // now, just list everyone in the same org slug who isn't the agent
  // themselves.
  const subagents = $derived.by(() => {
    if (!focused) return [];
    const focusedOrg = (focused.router as Record<string, unknown>).org_slug as string | undefined;
    if (!focusedOrg) return [];
    return allAgents
      .filter((a) => a.name !== focused.name && (a.router as Record<string, unknown>).org_slug === focusedOrg)
      .map((a) => ({ name: a.name, displayName: a.displayName, role: a.role }));
  });

  function inputKindColor(kind: string): string {
    if (kind === 'channel') return 'rgba(120, 200, 255, 0.85)';
    if (kind === 'cron-source') return 'rgba(220, 160, 100, 0.85)';
    return 'rgba(180, 180, 200, 0.7)';
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      onClose();
      e.preventDefault();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="overlay" onclick={onClose} role="presentation">
  <div class="panel" onclick={(e) => e.stopPropagation()} role="presentation">
    <header class="panel-header">
      <div class="title-block">
        <span class="title">System Map</span>
        {#if focused}
          <span class="title-sub">{focused.displayName}</span>
        {/if}
      </div>
      <div class="header-right">
        <select class="agent-picker" bind:value={selectedName}>
          {#each allAgents as a}
            <option value={a.name}>{a.displayName}</option>
          {/each}
        </select>
        <button class="close-btn" onclick={onClose} aria-label="Close">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </button>
      </div>
    </header>

    {#if loading}
      <div class="loading">Loading topology...</div>
    {:else if !focused}
      <div class="loading">No agent selected</div>
    {:else}
      <div class="canvas">
        <!-- Inputs row -->
        <div class="tier-label" style="color: rgba(120, 200, 255, 0.85)">INPUTS</div>
        <div class="tier-row">
          {#each inputs as input (input.key)}
            <div class="card input-card" style="--accent: {inputKindColor(input.kind)}">
              <span class="card-badge" style="color: {inputKindColor(input.kind)}">
                {input.kind.toUpperCase()}
              </span>
              <span class="card-name">{input.label}</span>
              {#if input.meta}
                <span class="card-meta">{input.meta}</span>
              {/if}
            </div>
          {/each}
        </div>

        <div class="connector"></div>

        <!-- Agent (focal card) -->
        <div class="agent-card">
          <div class="agent-avatar">
            {#if avatarUrl}
              <img src={avatarUrl} alt="{focused.displayName} avatar"/>
            {:else}
              <svg viewBox="0 0 64 64" fill="none">
                <circle cx="32" cy="22" r="11" fill="rgba(255,255,255,0.15)"/>
                <path d="M10 56 C 10 42, 22 36, 32 36 C 42 36, 54 42, 54 56 Z" fill="rgba(255,255,255,0.15)"/>
              </svg>
            {/if}
          </div>
          <div class="agent-text">
            <span class="agent-name">{focused.displayName}</span>
            {#if focused.role}
              <span class="agent-role">{focused.role}</span>
            {/if}
            <div class="agent-stats">
              <span><strong>{Object.keys(focused.channels).length}</strong> channels</span>
              <span><strong>{focused.mcp.active.length}</strong> tools</span>
              <span><strong>{Object.keys(focused.jobs).length}</strong> jobs</span>
              {#if subagents.length > 0}
                <span><strong>{subagents.length}</strong> subagents</span>
              {/if}
            </div>
          </div>
        </div>

        <div class="connector"></div>

        <!-- Tools row -->
        <div class="tier-label" style="color: rgba(100, 220, 140, 0.85)">TOOLS</div>
        <div class="tier-row">
          {#if tools.length === 0}
            <span class="empty-tier">No MCP tools configured</span>
          {/if}
          {#each tools as tool}
            <div
              class="card tool-card"
              class:disabled={!tool.active}
              class:warn={tool.server && (tool.server.missingKey || tool.server.missingCommand)}
              title={tool.server?.description || tool.name}
            >
              <span class="card-badge tool-badge">
                {#if tool.server?.missingKey}KEY{:else if tool.server?.missingCommand}MISSING{:else if tool.active}ACTIVE{:else}OFF{/if}
              </span>
              <span class="card-name">{tool.name}</span>
              {#if tool.server?.capabilities?.length}
                <span class="card-meta">{tool.server.capabilities.length} caps</span>
              {/if}
            </div>
          {/each}
        </div>

        <!-- Auxiliary sections -->
        {#if cronJobs.length > 0}
          <div class="aux-section">
            <div class="aux-label" style="color: rgba(220, 160, 100, 0.85)">CRON JOBS · {cronJobs.length}</div>
            <div class="aux-pills">
              {#each cronJobs.slice(0, 60) as job}
                <span class="pill" title={job.description || job.schedule}>
                  <span class="pill-name">{job.name}</span>
                  <span class="pill-meta">{job.schedule}</span>
                </span>
              {/each}
              {#if cronJobs.length > 60}
                <span class="pill more">+{cronJobs.length - 60} more</span>
              {/if}
            </div>
          </div>
        {/if}

        {#if subagents.length > 0}
          <div class="aux-section">
            <div class="aux-label" style="color: rgba(180, 180, 200, 0.85)">SUBAGENTS · {subagents.length}</div>
            <div class="aux-pills">
              {#each subagents as sub}
                <span class="pill subagent-pill" title={sub.role}>
                  <span class="pill-name">{sub.displayName}</span>
                </span>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
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
    gap: 10px;
  }

  .agent-picker {
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: rgba(255, 255, 255, 0.92);
    font-size: 12px;
    font-family: inherit;
    padding: 6px 10px;
    border-radius: 6px;
    cursor: pointer;
    min-width: 180px;
  }

  .agent-picker:focus {
    outline: none;
    border-color: rgba(120, 160, 255, 0.5);
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

  .canvas {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 28px 32px 36px;
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .canvas::-webkit-scrollbar {
    width: 6px;
  }

  .canvas::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 3px;
  }

  .loading {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: rgba(255, 255, 255, 0.4);
    font-size: 13px;
  }

  .tier-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
    margin-bottom: 10px;
  }

  .tier-row {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 12px;
    max-width: 100%;
  }

  .empty-tier {
    color: rgba(255, 255, 255, 0.3);
    font-size: 12px;
    padding: 12px 0;
  }

  .connector {
    width: 1px;
    height: 32px;
    background: rgba(255, 255, 255, 0.18);
    margin: 12px 0;
  }

  /* Generic card */
  .card {
    --accent: rgba(180, 180, 200, 0.7);
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
    min-width: 130px;
    max-width: 180px;
    padding: 10px 12px 12px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    transition: background 0.15s, border-color 0.15s, transform 0.15s;
  }

  .card:hover {
    background: rgba(255, 255, 255, 0.06);
    border-color: var(--accent);
    transform: translateY(-1px);
  }

  .input-card {
    --accent: rgba(120, 200, 255, 0.85);
  }

  .tool-card {
    --accent: rgba(100, 220, 140, 0.85);
  }

  .tool-card.disabled {
    opacity: 0.45;
  }

  .tool-card.warn {
    --accent: rgba(255, 200, 100, 0.85);
  }

  .card-badge {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: var(--accent);
  }

  .tool-badge {
    color: var(--accent);
  }

  .card-name {
    color: rgba(255, 255, 255, 0.92);
    font-size: 12.5px;
    font-weight: 600;
    word-break: break-word;
  }

  .card-meta {
    color: rgba(255, 255, 255, 0.4);
    font-size: 10.5px;
  }

  /* Focal agent card - the centrepiece */
  .agent-card {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 18px 24px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 200, 100, 0.4);
    border-radius: 14px;
    box-shadow:
      0 0 60px rgba(255, 200, 100, 0.08),
      0 8px 24px rgba(0, 0, 0, 0.4);
    min-width: 360px;
  }

  .agent-avatar {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    overflow: hidden;
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.04);
    border: 2px solid rgba(255, 200, 100, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .agent-avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .agent-avatar svg {
    width: 60%;
    height: 60%;
  }

  .agent-text {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .agent-name {
    color: rgba(255, 255, 255, 0.95);
    font-size: 17px;
    font-weight: 600;
  }

  .agent-role {
    color: rgba(255, 255, 255, 0.55);
    font-size: 12px;
  }

  .agent-stats {
    display: flex;
    gap: 14px;
    margin-top: 6px;
    color: rgba(255, 255, 255, 0.4);
    font-size: 11px;
  }

  .agent-stats strong {
    color: rgba(255, 255, 255, 0.85);
    font-weight: 600;
  }

  /* Auxiliary sections (cron, subagents) below the main map */
  .aux-section {
    width: 100%;
    margin-top: 32px;
    padding: 16px 20px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 10px;
  }

  .aux-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
    margin-bottom: 10px;
  }

  .aux-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .pill {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    padding: 4px 9px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 4px;
    font-size: 11px;
  }

  .pill-name {
    color: rgba(255, 255, 255, 0.78);
    font-weight: 500;
  }

  .pill-meta {
    color: rgba(255, 255, 255, 0.35);
    font-size: 10px;
    font-family: var(--font-mono, ui-monospace, SFMono-Regular, monospace);
  }

  .pill.more {
    color: rgba(255, 255, 255, 0.4);
    font-style: italic;
  }

  .subagent-pill {
    border-color: rgba(120, 160, 255, 0.2);
    background: rgba(120, 160, 255, 0.05);
  }
</style>

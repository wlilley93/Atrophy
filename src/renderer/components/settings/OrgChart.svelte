<script lang="ts">
  /**
   * OrgChart - top-down organisation chart visualization.
   *
   * Renders the hierarchy as horizontal tier rows with the principal at the
   * top, tier 1 leaders below, then tier 2 specialists, etc. Each card is
   * clickable and emits an `onSelectAgent` callback so the parent can open
   * an edit modal.
   *
   * Pure HTML/CSS - no D3 or external graph libs. Connector lines are drawn
   * with absolute-positioned divs between rows.
   */
  import { agents } from '../../stores/agents.svelte';

  interface AgentNode {
    name: string;
    display_name: string;
    role: string;
    tier: number;
    orgSlug: string | null;
    enabled: boolean;
  }

  interface Org {
    slug: string;
    name: string;
    type: string;
    principal: string | null;
  }

  interface Props {
    org: Org;
    agentsInOrg: AgentNode[];
    onSelectAgent: (name: string) => void;
    onAddAgent: () => void;
  }

  let { org, agentsInOrg, onSelectAgent, onAddAgent }: Props = $props();

  // Group agents by tier
  const tierGroups = $derived.by(() => {
    const map = new Map<number, AgentNode[]>();
    for (const a of agentsInOrg) {
      const t = a.tier || 1;
      if (!map.has(t)) map.set(t, []);
      map.get(t)!.push(a);
    }
    // Sort tiers ascending; sort agents alphabetically within tier.
    const sorted = [...map.entries()].sort((a, b) => a[0] - b[0]);
    for (const [, list] of sorted) {
      list.sort((a, b) => (a.display_name || a.name).localeCompare(b.display_name || b.name));
    }
    return sorted;
  });

  function tierLabel(tier: number): string {
    if (tier === 0) return 'Principal';
    if (tier === 1) return 'Leadership';
    if (tier === 2) return 'Specialists';
    if (tier === 3) return 'Workers';
    return `Tier ${tier}`;
  }

  function tierColor(tier: number): string {
    if (tier === 0) return 'rgba(255, 200, 100, 0.85)';
    if (tier === 1) return 'rgba(120, 160, 255, 0.85)';
    if (tier === 2) return 'rgba(100, 220, 140, 0.85)';
    if (tier === 3) return 'rgba(220, 160, 100, 0.85)';
    return 'rgba(180, 180, 200, 0.7)';
  }
</script>

<div class="org-chart">
  <header class="chart-header">
    <div class="chart-title">
      <span class="org-name">{org.name}</span>
      <span class="org-meta">{org.type} · {agentsInOrg.length} agent{agentsInOrg.length === 1 ? '' : 's'}</span>
    </div>
    <button class="add-btn" onclick={onAddAgent} title="Add agent to {org.name}">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <line x1="12" y1="5" x2="12" y2="19"/>
        <line x1="5" y1="12" x2="19" y2="12"/>
      </svg>
      Add agent
    </button>
  </header>

  <div class="chart-body">
    <!-- Principal (Will / user) at the very top -->
    <div class="principal-row">
      <div class="card principal-card">
        <span class="card-tier" style="color: {tierColor(0)}">PRINCIPAL</span>
        <span class="card-name">You</span>
        <span class="card-role">Owner</span>
      </div>
    </div>

    {#if tierGroups.length === 0}
      <div class="empty-state">
        <p class="empty-line">No agents yet in {org.name}.</p>
        <button class="empty-add" onclick={onAddAgent}>Add the first one</button>
      </div>
    {:else}
      {#each tierGroups as [tier, list]}
        <div class="connector"></div>
        <div class="tier-row">
          <div class="tier-label" style="color: {tierColor(tier)}">{tierLabel(tier)}</div>
          <div class="tier-cards">
            {#each list as agent}
              <button
                class="card agent-card"
                class:active={agent.name === agents.current}
                class:disabled={!agent.enabled}
                onclick={() => onSelectAgent(agent.name)}
              >
                <span class="card-tier" style="color: {tierColor(tier)}">T{tier}</span>
                <span class="card-name">{agent.display_name || agent.name}</span>
                {#if agent.role}
                  <span class="card-role">{agent.role}</span>
                {/if}
                {#if agent.name === agents.current}
                  <span class="active-dot" title="Currently active"></span>
                {/if}
              </button>
            {/each}
          </div>
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .org-chart {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    min-height: 0;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  .chart-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 4px 14px 4px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    margin-bottom: 18px;
    flex-shrink: 0;
  }

  .chart-title {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .org-name {
    color: rgba(255, 255, 255, 0.92);
    font-size: 15px;
    font-weight: 600;
  }

  .org-meta {
    color: rgba(255, 255, 255, 0.35);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .add-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(120, 160, 255, 0.12);
    border: 1px solid rgba(120, 160, 255, 0.3);
    color: rgba(170, 200, 255, 0.95);
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .add-btn:hover {
    background: rgba(120, 160, 255, 0.2);
    border-color: rgba(120, 160, 255, 0.5);
  }

  .chart-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 12px 4px 24px;
  }

  .chart-body::-webkit-scrollbar {
    width: 6px;
  }

  .chart-body::-webkit-scrollbar-track {
    background: transparent;
  }

  .chart-body::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 3px;
  }

  .principal-row {
    display: flex;
    justify-content: center;
  }

  .connector {
    width: 1px;
    height: 28px;
    background: rgba(255, 255, 255, 0.18);
    margin: 0;
  }

  .tier-row {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    width: 100%;
  }

  .tier-label {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 4px;
  }

  .tier-cards {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 14px;
    max-width: 100%;
  }

  .card {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    min-width: 130px;
    max-width: 180px;
    padding: 12px 14px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s, transform 0.15s;
    position: relative;
    text-align: center;
    font-family: inherit;
    color: inherit;
  }

  .card:hover {
    background: rgba(255, 255, 255, 0.07);
    border-color: rgba(255, 255, 255, 0.18);
    transform: translateY(-1px);
  }

  .card.principal-card {
    background: rgba(255, 200, 100, 0.06);
    border-color: rgba(255, 200, 100, 0.3);
    cursor: default;
  }

  .card.principal-card:hover {
    transform: none;
  }

  .card.disabled {
    opacity: 0.5;
  }

  .card.active {
    border-color: rgba(80, 210, 100, 0.6);
    background: rgba(80, 210, 100, 0.05);
  }

  .card-tier {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.6px;
  }

  .card-name {
    color: rgba(255, 255, 255, 0.92);
    font-size: 13px;
    font-weight: 600;
  }

  .card-role {
    color: rgba(255, 255, 255, 0.45);
    font-size: 11px;
  }

  .active-dot {
    position: absolute;
    top: 8px;
    right: 8px;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgba(80, 210, 100, 0.85);
    box-shadow: 0 0 6px rgba(80, 210, 100, 0.6);
  }

  .empty-state {
    margin-top: 40px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
  }

  .empty-line {
    color: rgba(255, 255, 255, 0.4);
    font-size: 13px;
    margin: 0;
  }

  .empty-add {
    background: rgba(120, 160, 255, 0.12);
    border: 1px solid rgba(120, 160, 255, 0.3);
    color: rgba(170, 200, 255, 0.95);
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s;
    font-family: inherit;
  }

  .empty-add:hover {
    background: rgba(120, 160, 255, 0.2);
  }
</style>

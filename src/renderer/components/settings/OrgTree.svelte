<script lang="ts">
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

  let {
    orgs,
    standalone,
    selectedId,
    selectedType,
    onSelect,
    onCreateAgent,
    onCreateOrg,
  }: Props = $props();

  let expandedOrgs = $state<Set<string>>(new Set());
  let expandedTiers = $state<Set<string>>(new Set());

  $effect(() => {
    const newOrgs = new Set<string>();
    const newTiers = new Set<string>();
    for (const org of orgs) {
      newOrgs.add(org.slug);
      const tiers = groupByTier(org.agents);
      for (const tier of tiers.keys()) {
        newTiers.add(`${org.slug}:${tier}`);
      }
    }
    expandedOrgs = newOrgs;
    expandedTiers = newTiers;
  });

  function groupByTier(agentList: AgentNode[]): Map<number, AgentNode[]> {
    const groups = new Map<number, AgentNode[]>();
    for (const a of agentList) {
      const tier = a.tier || 1;
      if (!groups.has(tier)) groups.set(tier, []);
      groups.get(tier)!.push(a);
    }
    return new Map([...groups.entries()].sort((a, b) => a[0] - b[0]));
  }

  function tierLabel(tier: number): string {
    if (tier === 1) return 'Leadership';
    if (tier === 2) return 'Specialists';
    return `Tier ${tier}`;
  }

  function tierColor(tier: number): string {
    if (tier === 1) return 'rgba(100, 140, 255, 0.7)';
    if (tier === 2) return 'rgba(80, 200, 120, 0.7)';
    return 'rgba(180, 180, 180, 0.5)';
  }

  function toggleOrg(slug: string) {
    const next = new Set(expandedOrgs);
    if (next.has(slug)) {
      next.delete(slug);
    } else {
      next.add(slug);
    }
    expandedOrgs = next;
  }

  function toggleTier(key: string) {
    const next = new Set(expandedTiers);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    expandedTiers = next;
  }

  function isOrgSelected(slug: string): boolean {
    return selectedType === 'org' && selectedId === slug;
  }

  function isAgentSelected(name: string): boolean {
    return selectedType === 'agent' && selectedId === name;
  }
</script>

<div class="org-tree">
  <!-- Header -->
  <div class="tree-header">
    <span class="tree-header-label">Organisations</span>
    <button class="header-add-btn" onclick={onCreateOrg} title="New organisation">+</button>
  </div>

  <!-- Org list -->
  {#if orgs.length === 0}
    <p class="empty-hint">No organisations</p>
  {:else}
    {#each orgs as org}
      {@const orgExpanded = expandedOrgs.has(org.slug)}
      {@const tierGroups = groupByTier(org.agents)}

      <!-- Org row -->
      <div
        class="org-row"
        class:selected={isOrgSelected(org.slug)}
        role="button"
        tabindex="0"
        onclick={() => onSelect(org.slug, 'org')}
        onkeydown={(e) => e.key === 'Enter' && onSelect(org.slug, 'org')}
      >
        <button
          class="chevron"
          class:open={orgExpanded}
          onclick={(e) => { e.stopPropagation(); toggleOrg(org.slug); }}
          aria-label={orgExpanded ? 'Collapse' : 'Expand'}
          tabindex="-1"
        >&#9658;</button>
        <span class="org-name">{org.name}</span>
        <span class="org-type">{org.type}</span>
      </div>

      <!-- Tier groups -->
      {#if orgExpanded}
        <div class="org-children">
          {#each tierGroups as [tier, tierAgents]}
            {@const tierKey = `${org.slug}:${tier}`}
            {@const tierExpanded = expandedTiers.has(tierKey)}

            <!-- Tier row -->
            <div class="tier-row">
              <button
                class="chevron tier-chevron"
                class:open={tierExpanded}
                onclick={(e) => { e.stopPropagation(); toggleTier(tierKey); }}
                aria-label={tierExpanded ? 'Collapse tier' : 'Expand tier'}
                tabindex="-1"
              >&#9658;</button>
              <span class="tier-label" style="color: {tierColor(tier)}">{tierLabel(tier)}</span>
              <span class="tier-count">{tierAgents.length}</span>
            </div>

            <!-- Agent rows within tier -->
            {#if tierExpanded}
              <div class="tier-agents">
                {#each tierAgents as agent}
                  <div
                    class="agent-row"
                    class:selected={isAgentSelected(agent.name)}
                    class:disabled={!agent.enabled}
                    role="button"
                    tabindex="0"
                    onclick={() => onSelect(agent.name, 'agent')}
                    onkeydown={(e) => e.key === 'Enter' && onSelect(agent.name, 'agent')}
                  >
                    <span class="agent-display-name">{agent.display_name || agent.name}</span>
                    {#if agent.role}
                      <span class="role-badge">{agent.role.toUpperCase()}</span>
                    {/if}
                    {#if agent.name === agents.current}
                      <span class="active-dot" title="Active agent"></span>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}
          {/each}
        </div>
      {/if}
    {/each}
  {/if}

  <!-- Standalone divider -->
  <div class="divider">
    <span class="divider-label">Standalone</span>
  </div>

  <!-- Standalone agents -->
  {#if standalone.length === 0}
    <p class="empty-hint">No standalone agents</p>
  {:else}
    {#each standalone as agent}
      <div
        class="agent-row standalone"
        class:selected={isAgentSelected(agent.name)}
        class:disabled={!agent.enabled}
        role="button"
        tabindex="0"
        onclick={() => onSelect(agent.name, 'agent')}
        onkeydown={(e) => e.key === 'Enter' && onSelect(agent.name, 'agent')}
      >
        <span class="agent-display-name">{agent.display_name || agent.name}</span>
        {#if agent.role}
          <span class="role-badge">{agent.role.toUpperCase()}</span>
        {/if}
        {#if agent.name === agents.current}
          <span class="active-dot" title="Active agent"></span>
        {/if}
      </div>
    {/each}
  {/if}

  <!-- Footer -->
  <div class="tree-footer">
    <button class="quick-add-btn" onclick={onCreateAgent}>+ Quick Add Agent</button>
  </div>
</div>

<style>
  .org-tree {
    display: flex;
    flex-direction: column;
    width: 100%;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  /* Header */
  .tree-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 4px 6px 4px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    margin-bottom: 4px;
  }

  .tree-header-label {
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .header-add-btn {
    background: none;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 3px;
    color: rgba(255, 255, 255, 0.5);
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    padding: 1px 5px 2px;
    transition: color 0.15s, border-color 0.15s;
  }

  .header-add-btn:hover {
    color: rgba(255, 255, 255, 0.85);
    border-color: rgba(255, 255, 255, 0.3);
  }

  /* Chevron */
  .chevron {
    background: none;
    border: none;
    color: rgba(255, 255, 255, 0.3);
    cursor: pointer;
    font-size: 8px;
    padding: 0;
    flex-shrink: 0;
    transform: rotate(0deg);
    transition: transform 0.15s ease, color 0.15s;
    width: 12px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .chevron.open {
    transform: rotate(90deg);
  }

  .chevron:hover {
    color: rgba(255, 255, 255, 0.6);
  }

  /* Org row */
  .org-row {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 5px 6px;
    border-radius: 4px;
    cursor: pointer;
    border-left: 2px solid transparent;
    transition: background 0.1s;
  }

  .org-row:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .org-row.selected {
    background: rgba(100, 140, 255, 0.08);
    border-left-color: rgba(100, 140, 255, 0.6);
  }

  .org-name {
    color: rgba(255, 255, 255, 0.7);
    font-size: 13px;
    font-weight: 500;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .org-row.selected .org-name {
    color: rgba(255, 255, 255, 0.92);
  }

  .org-type {
    color: rgba(255, 255, 255, 0.25);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    flex-shrink: 0;
  }

  /* Org children container */
  .org-children {
    padding-left: 16px;
  }

  /* Tier row */
  .tier-row {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 3px 4px;
    cursor: default;
  }

  .tier-chevron {
    color: rgba(255, 255, 255, 0.2);
  }

  .tier-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }

  .tier-count {
    color: rgba(255, 255, 255, 0.2);
    font-size: 10px;
    margin-left: auto;
  }

  /* Tier agents container */
  .tier-agents {
    padding-left: 14px;
  }

  /* Agent row */
  .agent-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 6px;
    border-radius: 4px;
    cursor: pointer;
    border-left: 2px solid transparent;
    transition: background 0.1s;
  }

  .agent-row:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .agent-row.selected {
    background: rgba(100, 140, 255, 0.08);
    border-left-color: rgba(100, 140, 255, 0.6);
  }

  .agent-row.disabled {
    opacity: 0.45;
  }

  .agent-row.standalone {
    padding-left: 8px;
  }

  .agent-display-name {
    color: rgba(255, 255, 255, 0.7);
    font-size: 12px;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .agent-row.selected .agent-display-name {
    color: rgba(255, 255, 255, 0.92);
  }

  /* Role badge */
  .role-badge {
    color: rgba(255, 255, 255, 0.3);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.4px;
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.06);
    border-radius: 2px;
    padding: 1px 4px;
  }

  /* Active dot */
  .active-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgba(80, 210, 100, 0.85);
    flex-shrink: 0;
    box-shadow: 0 0 4px rgba(80, 210, 100, 0.4);
  }

  /* Divider */
  .divider {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 10px 0 6px;
    padding: 0 4px;
  }

  .divider::before,
  .divider::after {
    content: '';
    flex: 1;
    height: 1px;
    background: rgba(255, 255, 255, 0.06);
  }

  .divider-label {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    flex-shrink: 0;
  }

  /* Empty hint */
  .empty-hint {
    color: rgba(255, 255, 255, 0.2);
    font-size: 11px;
    padding: 6px 8px;
    text-align: center;
  }

  /* Footer */
  .tree-footer {
    margin-top: 8px;
    padding: 4px 4px 0;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }

  .quick-add-btn {
    background: none;
    border: none;
    color: rgba(100, 140, 255, 0.6);
    cursor: pointer;
    font-size: 12px;
    padding: 6px 2px;
    text-align: left;
    width: 100%;
    transition: color 0.15s;
  }

  .quick-add-btn:hover {
    color: rgba(100, 140, 255, 0.9);
  }
</style>

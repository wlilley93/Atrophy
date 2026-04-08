<script lang="ts">
  /**
   * AgentsSidebar - left rail for the Agents tab.
   *
   * Two flat sections: Primary Agents (top-level standalone) and
   * Organisations. Single-select. The plus button is context-sensitive:
   *   - When a primary agent OR nothing is selected, + opens the
   *     "create organisation" flow.
   *   - When an organisation is selected, + opens the "add agent into
   *     this org" flow.
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

  type Selection =
    | { kind: 'agent'; name: string }
    | { kind: 'org'; slug: string }
    | null;

  interface Props {
    primaryAgents: AgentNode[];
    orgs: Org[];
    selection: Selection;
    onSelect: (sel: Selection) => void;
    onAddOrg: () => void;
    onAddAgentToOrg: (orgSlug: string) => void;
  }

  let {
    primaryAgents,
    orgs,
    selection,
    onSelect,
    onAddOrg,
    onAddAgentToOrg,
  }: Props = $props();

  function isAgentSelected(name: string): boolean {
    return selection?.kind === 'agent' && selection.name === name;
  }

  function isOrgSelected(slug: string): boolean {
    return selection?.kind === 'org' && selection.slug === slug;
  }

  function plusAction() {
    // Context-sensitive plus:
    //   org selected -> add agent into that org
    //   anything else -> create a new org
    if (selection?.kind === 'org') {
      onAddAgentToOrg(selection.slug);
    } else {
      onAddOrg();
    }
  }

  const plusLabel = $derived(
    selection?.kind === 'org' ? `Add agent to ${orgs.find(o => o.slug === selection.slug)?.name ?? 'org'}` : 'New organisation',
  );
</script>

<div class="agents-sidebar">
  <!-- Primary Agents -->
  <section class="section">
    <header class="section-header">
      <span class="section-label">Primary Agents</span>
      <span class="section-count">{primaryAgents.length}</span>
    </header>
    {#if primaryAgents.length === 0}
      <p class="empty">No primary agents</p>
    {:else}
      <ul class="agent-list">
        {#each primaryAgents as a}
          <li>
            <button
              class="row agent-row"
              class:selected={isAgentSelected(a.name)}
              class:disabled={!a.enabled}
              onclick={() => onSelect({ kind: 'agent', name: a.name })}
            >
              <span class="row-name">{a.display_name || a.name}</span>
              {#if a.name === agents.current}
                <span class="active-dot" title="Active"></span>
              {/if}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <!-- Organisations -->
  <section class="section">
    <header class="section-header">
      <span class="section-label">Organisations</span>
      <span class="section-count">{orgs.length}</span>
    </header>
    {#if orgs.length === 0}
      <p class="empty">No organisations yet</p>
    {:else}
      <ul class="agent-list">
        {#each orgs as o}
          <li>
            <button
              class="row org-row"
              class:selected={isOrgSelected(o.slug)}
              onclick={() => onSelect({ kind: 'org', slug: o.slug })}
            >
              <span class="row-name">{o.name}</span>
              <span class="row-meta">{o.type}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <!-- Plus button (context-sensitive) -->
  <div class="footer">
    <button class="plus-btn" onclick={plusAction} title={plusLabel}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <line x1="12" y1="5" x2="12" y2="19"/>
        <line x1="5" y1="12" x2="19" y2="12"/>
      </svg>
      <span>{plusLabel}</span>
    </button>
  </div>
</div>

<style>
  .agents-sidebar {
    display: flex;
    flex-direction: column;
    height: 100%;
    width: 100%;
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui);
  }

  .section {
    margin-bottom: 18px;
  }

  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 6px 6px 6px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    margin-bottom: 6px;
  }

  .section-label {
    color: rgba(255, 255, 255, 0.5);
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
  }

  .section-count {
    color: rgba(255, 255, 255, 0.25);
    font-size: 10px;
  }

  .agent-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 7px 8px;
    background: none;
    border: none;
    border-left: 2px solid transparent;
    border-radius: 4px;
    cursor: pointer;
    text-align: left;
    font-family: inherit;
    transition: background 0.1s;
  }

  .row:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .row.selected {
    background: rgba(120, 160, 255, 0.1);
    border-left-color: rgba(120, 160, 255, 0.6);
  }

  .row.disabled {
    opacity: 0.45;
  }

  .row-name {
    color: rgba(255, 255, 255, 0.78);
    font-size: 13px;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .row.selected .row-name {
    color: rgba(255, 255, 255, 0.95);
  }

  .row-meta {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    flex-shrink: 0;
  }

  .active-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgba(80, 210, 100, 0.85);
    box-shadow: 0 0 4px rgba(80, 210, 100, 0.4);
    flex-shrink: 0;
  }

  .empty {
    color: rgba(255, 255, 255, 0.25);
    font-size: 11px;
    text-align: center;
    padding: 6px 8px;
    margin: 0;
  }

  .footer {
    margin-top: auto;
    padding: 10px 0 0;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }

  .plus-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 9px 10px;
    background: rgba(120, 160, 255, 0.1);
    border: 1px solid rgba(120, 160, 255, 0.25);
    border-radius: 6px;
    color: rgba(170, 200, 255, 0.95);
    font-size: 12px;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .plus-btn:hover {
    background: rgba(120, 160, 255, 0.18);
    border-color: rgba(120, 160, 255, 0.45);
  }
</style>

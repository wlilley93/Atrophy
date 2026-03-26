<script lang="ts">
  import { api } from '../../api';

  let activityItems = $state<any[]>([]);
  let activityFilter = $state('all');
  let activityAgentFilter = $state('all');
  let activitySearch = $state('');
  let activityLoading = $state(false);
  let expandedActivity = $state<number | null>(null);

  const categoryBadges: Record<string, [string, string]> = {
    tool_call: ['TOOL', '#4a9eff'],
    heartbeat: ['\u2764 BEAT', '#e74c3c'],
    inference: ['\uD83E\uDDE0 INFER', '#b07cc6'],
  };

  export async function load() {
    if (!api) return;
    activityLoading = true;
    try {
      activityItems = await api.getActivity(30, 500) || [];
    } catch {
      activityItems = [];
    }
    activityLoading = false;
  }

  function activityAgents(): string[] {
    const s = new Set(activityItems.map((i: any) => i.agent).filter(Boolean));
    return [...s].sort();
  }

  function filteredActivity(): any[] {
    let items = activityItems;
    if (activityFilter === 'flagged') {
      items = items.filter((i: any) => i.flagged);
    } else if (activityFilter !== 'all') {
      items = items.filter((i: any) => i.category === activityFilter);
    }
    if (activityAgentFilter !== 'all') {
      items = items.filter((i: any) => i.agent === activityAgentFilter);
    }
    if (activitySearch) {
      const q = activitySearch.toLowerCase();
      items = items.filter((i: any) =>
        `${i.action || ''} ${i.detail || ''} ${i.agent || ''}`.toLowerCase().includes(q)
      );
    }
    return items.slice(0, 200);
  }

  function formatTimestamp(ts: string): string {
    try {
      const d = new Date(ts);
      return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}  ${d.toLocaleTimeString('en-US', { hour12: false })}`;
    } catch {
      return ts?.slice(0, 19) || '';
    }
  }
</script>

<input
  type="text"
  class="search-input"
  placeholder="Search activity..."
  bind:value={activitySearch}
/>

<div class="filter-row">
  {#each [['All', 'all'], ['Tools', 'tool_call'], ['Heartbeats', 'heartbeat'], ['Inference', 'inference'], ['Flagged', 'flagged']] as [label, key]}
    <button
      class="filter-pill"
      class:active={activityFilter === key}
      onclick={() => activityFilter = key as string}
    >{label}</button>
  {/each}
  <select class="agent-filter-select" bind:value={activityAgentFilter}>
    <option value="all">All agents</option>
    {#each activityAgents() as a}
      <option value={a}>{a.replace(/_/g, ' ')}</option>
    {/each}
  </select>
</div>

<div class="activity-count">
  {#if activityItems.length > 0}
    {filteredActivity().length} of {activityItems.length} entries
  {:else}
    No activity recorded yet
  {/if}
</div>

{#if activityLoading}
  <p class="placeholder">Loading...</p>
{:else}
  {#each filteredActivity() as item, i}
    {@const [badgeText, badgeColor] = categoryBadges[item.category] || [item.category?.toUpperCase() || '?', '#888']}
    <button
      class="activity-card"
      class:expanded={expandedActivity === i}
      onclick={() => expandedActivity = expandedActivity === i ? null : i}
    >
      <div class="activity-summary">
        <span class="activity-badge" style="color: {badgeColor}">{badgeText}</span>
        {#if item.flagged}
          <span class="activity-flag">!</span>
        {/if}
        <span class="activity-action">{item.action || ''}</span>
        <span class="activity-agent">{(item.agent || '').replace(/_/g, ' ')}</span>
        <span class="activity-spacer"></span>
        <span class="activity-time">{formatTimestamp(item.timestamp)}</span>
      </div>
      {#if expandedActivity === i}
        <pre class="activity-detail">{item.detail || '(no detail)'}</pre>
      {/if}
    </button>
  {/each}
{/if}

<style>
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
    margin-bottom: 10px;
    box-sizing: border-box;
  }

  .search-input::placeholder {
    color: rgba(255, 255, 255, 0.3);
  }

  .filter-row {
    display: flex;
    gap: 6px;
    align-items: center;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }

  .filter-pill {
    padding: 4px 12px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.4);
    font-size: 11px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .filter-pill:hover {
    background: rgba(255, 255, 255, 0.08);
  }

  .filter-pill.active {
    background: rgba(255, 255, 255, 0.15);
    color: rgba(255, 255, 255, 0.9);
    border-color: rgba(255, 255, 255, 0.25);
  }

  .agent-filter-select {
    margin-left: auto;
    height: 26px;
    padding: 0 8px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    color: rgba(255, 255, 255, 0.6);
    font-size: 11px;
    min-width: 100px;
    outline: none;
    -webkit-appearance: none;
    appearance: none;
  }

  .agent-filter-select option {
    background: rgb(30, 30, 35);
    color: rgba(255, 255, 255, 0.85);
  }

  .activity-count {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    margin-bottom: 8px;
  }

  .placeholder {
    color: var(--text-dim);
    font-size: 13px;
    text-align: center;
    padding: 40px 0;
  }

  .activity-card {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 6px;
    padding: 6px 10px;
    margin-bottom: 4px;
    cursor: pointer;
    border: none;
    width: 100%;
    text-align: left;
    color: inherit;
    font-family: inherit;
    transition: background 0.15s;
  }

  .activity-card:hover {
    background: rgba(255, 255, 255, 0.05);
  }

  .activity-card.expanded {
    background: rgba(255, 255, 255, 0.06);
  }

  .activity-summary {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 24px;
  }

  .activity-badge {
    font-size: 9px;
    font-weight: bold;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 4px;
    padding: 2px 6px;
    min-width: 52px;
    text-align: center;
    white-space: nowrap;
  }

  .activity-flag {
    color: #ff6b6b;
    font-size: 11px;
    font-weight: bold;
    background: rgba(255, 100, 100, 0.15);
    border-radius: 8px;
    width: 16px;
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .activity-action {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    font-weight: bold;
  }

  .activity-agent {
    color: rgba(255, 255, 255, 0.35);
    font-size: 11px;
  }

  .activity-spacer {
    flex: 1;
  }

  .activity-time {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    white-space: nowrap;
  }

  .activity-detail {
    margin: 6px 0 2px;
    padding: 8px;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 4px;
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
    font-family: var(--font-mono);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 200px;
    overflow-y: auto;
  }
</style>

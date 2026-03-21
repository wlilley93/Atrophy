<script lang="ts">
  import { api } from '../../api';

  let usagePeriod = $state<number | null>(null);
  let usageData = $state<any[]>([]);
  let usageLoading = $state(false);

  export async function load(days?: number | null) {
    if (days !== undefined) usagePeriod = days;
    await loadUsage(usagePeriod);
  }

  async function loadUsage(days: number | null) {
    usagePeriod = days;
    if (!api) return;
    usageLoading = true;
    try {
      usageData = await api.getUsage(days ?? undefined) || [];
    } catch {
      usageData = [];
    }
    usageLoading = false;
  }

  function formatTokens(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
  }

  function formatDuration(ms: number): string {
    const secs = Math.floor(ms / 1000);
    if (secs < 60) return `${secs}s`;
    const mins = Math.floor(secs / 60);
    if (mins < 60) return `${mins}m ${secs % 60}s`;
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ${mins % 60}m`;
  }
</script>

<div class="filter-row">
  {#each [['Today', 1], ['7 days', 7], ['30 days', 30], ['All', null]] as [label, days]}
    <button
      class="filter-pill"
      class:active={usagePeriod === days}
      onclick={() => loadUsage(days as number | null)}
    >{label}</button>
  {/each}
</div>

{#if usageLoading}
  <p class="placeholder">Loading...</p>
{:else if usageData.length === 0 || usageData.every((a: any) => a.total_calls === 0)}
  <p class="placeholder">No usage data yet. Stats will appear after inference calls.</p>
{:else}
  <!-- Totals bar -->
  {@const totalCalls = usageData.reduce((s: number, a: any) => s + (a.total_calls || 0), 0)}
  {@const totalTokens = usageData.reduce((s: number, a: any) => s + (a.total_tokens || 0), 0)}
  {@const totalDuration = usageData.reduce((s: number, a: any) => s + (a.total_duration_ms || 0), 0)}
  {@const totalTools = usageData.reduce((s: number, a: any) => s + (a.total_tools || 0), 0)}

  <div class="totals-bar">
    <div class="total-stat">
      <span class="total-value">{totalCalls}</span>
      <span class="total-label">Inferences</span>
    </div>
    <div class="total-stat">
      <span class="total-value">{formatTokens(totalTokens)}</span>
      <span class="total-label">Tokens (est.)</span>
    </div>
    <div class="total-stat">
      <span class="total-value">{formatDuration(totalDuration)}</span>
      <span class="total-label">Time</span>
    </div>
    <div class="total-stat">
      <span class="total-value">{totalTools}</span>
      <span class="total-label">Tool Calls</span>
    </div>
  </div>

  <!-- Per-agent cards -->
  {#each usageData.filter((a: any) => a.total_calls > 0) as agent}
    <div class="usage-card">
      <div class="usage-card-header">
        <span class="usage-agent-name">{agent.display_name || agent.agent}</span>
        <span class="usage-tokens">{formatTokens(agent.total_tokens)} tokens</span>
      </div>
      <div class="usage-stats-row">
        <span>{agent.total_calls} calls</span>
        <span>in: {formatTokens(agent.total_tokens_in || 0)}</span>
        <span>out: {formatTokens(agent.total_tokens_out || 0)}</span>
        <span>{formatDuration(agent.total_duration_ms || 0)}</span>
        <span>{agent.total_tools || 0} tools</span>
      </div>
      {#if agent.by_source?.length}
        <div class="usage-sources">
          {#each agent.by_source.slice(0, 5) as src}
            <span class="source-pill">{src.source} ({src.calls})</span>
          {/each}
        </div>
      {/if}
    </div>
  {/each}
{/if}

<style>
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

  .placeholder {
    color: var(--text-dim);
    font-size: 13px;
    text-align: center;
    padding: 40px 0;
  }

  .totals-bar {
    display: flex;
    justify-content: space-around;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 12px;
  }

  .total-stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }

  .total-value {
    color: rgba(255, 255, 255, 0.95);
    font-size: 20px;
    font-weight: bold;
  }

  .total-label {
    color: rgba(255, 255, 255, 0.4);
    font-size: 10px;
  }

  .usage-card {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 8px;
  }

  .usage-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }

  .usage-agent-name {
    color: rgba(255, 255, 255, 0.9);
    font-size: 14px;
    font-weight: bold;
  }

  .usage-tokens {
    color: rgba(255, 255, 255, 0.5);
    font-size: 12px;
  }

  .usage-stats-row {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
  }

  .usage-stats-row span {
    color: rgba(255, 255, 255, 0.4);
    font-size: 11px;
  }

  .usage-sources {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 6px;
  }

  .source-pill {
    color: rgba(255, 255, 255, 0.35);
    font-size: 10px;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 4px;
    padding: 1px 6px;
  }
</style>

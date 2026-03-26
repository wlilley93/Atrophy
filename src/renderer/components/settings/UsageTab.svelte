<script lang="ts">
  import { api } from '../../api';

  let usagePeriod = $state<number | null>(null);
  let usageData = $state<any[]>([]);
  let usageLoading = $state(false);

  // Expandable detail state
  let expandedAgent = $state<string | null>(null);
  let detailData = $state<any[]>([]);
  let detailLoading = $state(false);

  export async function load(days?: number | null) {
    if (days !== undefined) usagePeriod = days;
    await loadUsage(usagePeriod);
  }

  async function loadUsage(days: number | null) {
    usagePeriod = days;
    if (!api) return;
    usageLoading = true;
    expandedAgent = null;
    detailData = [];
    try {
      usageData = await api.getUsage(days ?? undefined) || [];
    } catch {
      usageData = [];
    }
    usageLoading = false;
  }

  async function toggleDetail(agentName: string) {
    if (expandedAgent === agentName) {
      expandedAgent = null;
      detailData = [];
      return;
    }
    expandedAgent = agentName;
    detailLoading = true;
    try {
      detailData = await api.getUsageDetail(agentName, usagePeriod ?? undefined) || [];
    } catch {
      detailData = [];
    }
    detailLoading = false;
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

  function formatTime(ts: string): string {
    try {
      const d = new Date(ts + 'Z');
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch { return ts; }
  }

  function formatDate(ts: string): string {
    try {
      const d = new Date(ts + 'Z');
      const today = new Date();
      if (d.toDateString() === today.toDateString()) return 'Today';
      const yesterday = new Date(today);
      yesterday.setDate(yesterday.getDate() - 1);
      if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } catch { return ''; }
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
    <div class="usage-card" class:expanded={expandedAgent === agent.agent_name}>
      <button class="usage-card-header" onclick={() => toggleDetail(agent.agent_name)}>
        <span class="usage-agent-name">{agent.display_name || agent.agent}</span>
        <span class="usage-right">
          <span class="usage-tokens">{formatTokens(agent.total_tokens)} tokens</span>
          <span class="expand-arrow" class:open={expandedAgent === agent.agent_name}>&#9662;</span>
        </span>
      </button>
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

      <!-- Expanded detail view -->
      {#if expandedAgent === agent.agent_name}
        <div class="detail-panel">
          {#if detailLoading}
            <p class="detail-loading">Loading entries...</p>
          {:else if detailData.length === 0}
            <p class="detail-loading">No entries found.</p>
          {:else}
            {#each detailData as entry}
              <div class="detail-entry">
                <div class="detail-meta">
                  <span class="detail-source">{entry.source}</span>
                  <span class="detail-tokens">{formatTokens(entry.tokens_in + entry.tokens_out)} tok</span>
                  <span class="detail-time">{formatDate(entry.timestamp)} {formatTime(entry.timestamp)}</span>
                  {#if entry.duration_ms}
                    <span class="detail-dur">{formatDuration(entry.duration_ms)}</span>
                  {/if}
                  {#if entry.tool_count}
                    <span class="detail-tools">{entry.tool_count} tools</span>
                  {/if}
                </div>
                {#if entry.context?.length}
                  <div class="detail-context">
                    {#each entry.context as turn}
                      <div class="context-turn" class:agent-turn={turn.role === 'agent'}>
                        <span class="turn-role">{turn.role === 'agent' ? 'Agent' : 'Will'}</span>
                        <span class="turn-content">{turn.content}</span>
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            {/each}
          {/if}
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
    transition: background 0.15s;
  }

  .usage-card.expanded {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .usage-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
    width: 100%;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    text-align: left;
  }

  .usage-agent-name {
    color: rgba(255, 255, 255, 0.9);
    font-size: 14px;
    font-weight: bold;
  }

  .usage-right {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .usage-tokens {
    color: rgba(255, 255, 255, 0.5);
    font-size: 12px;
  }

  .expand-arrow {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
    transition: transform 0.2s;
  }

  .expand-arrow.open {
    transform: rotate(180deg);
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

  /* Detail panel */
  .detail-panel {
    margin-top: 10px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    padding-top: 10px;
    max-height: 400px;
    overflow-y: auto;
  }

  .detail-loading {
    color: var(--text-dim);
    font-size: 11px;
    text-align: center;
    padding: 12px 0;
  }

  .detail-entry {
    padding: 8px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }

  .detail-entry:last-child {
    border-bottom: none;
  }

  .detail-meta {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 4px;
  }

  .detail-source {
    color: rgba(176, 124, 198, 0.9);
    font-size: 11px;
    font-weight: 600;
    background: rgba(176, 124, 198, 0.12);
    padding: 1px 6px;
    border-radius: 3px;
  }

  .detail-tokens {
    color: rgba(255, 255, 255, 0.5);
    font-size: 10px;
    font-family: var(--font-mono);
  }

  .detail-time {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
  }

  .detail-dur {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
  }

  .detail-tools {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
  }

  /* Conversation context */
  .detail-context {
    margin-top: 4px;
    padding-left: 8px;
    border-left: 2px solid rgba(255, 255, 255, 0.06);
  }

  .context-turn {
    display: flex;
    gap: 8px;
    padding: 2px 0;
    font-size: 11px;
    line-height: 1.4;
  }

  .turn-role {
    color: rgba(100, 140, 255, 0.7);
    font-size: 10px;
    font-weight: 600;
    min-width: 36px;
    flex-shrink: 0;
  }

  .context-turn.agent-turn .turn-role {
    color: rgba(176, 124, 198, 0.7);
  }

  .turn-content {
    color: rgba(255, 255, 255, 0.55);
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
  }
</style>

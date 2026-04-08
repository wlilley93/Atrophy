<script lang="ts">
  import { api } from '../../api';

  // -- Types --
  interface ActivityItem {
    agent: string;
    category: 'tool_call' | 'heartbeat' | 'inference';
    timestamp: string;
    action: string;
    detail: string;
    flagged: boolean;
  }

  // -- State --
  let activityItems = $state<ActivityItem[]>([]);
  let activityLoading = $state(false);
  let expandedRow = $state<number | null>(null);
  let autoRefresh = $state(false);
  let autoRefreshTimer = $state<ReturnType<typeof setInterval> | null>(null);
  let nowTick = $state(Date.now());
  let tickTimer = $state<ReturnType<typeof setInterval> | null>(null);

  // Filters
  let agentFilter = $state('all');
  let searchQuery = $state('');
  let timeRange = $state<number>(24); // hours: 1, 6, 24, 0=all
  let enabledCategories = $state<Record<string, boolean>>({
    inference: true,
    tool_call: true,
    heartbeat: true,
  });

  // -- Category config --
  const categoryConfig: Record<string, { label: string; color: string; bg: string }> = {
    inference: { label: 'Inference', color: '#648cff', bg: 'rgba(100, 140, 255, 0.12)' },
    tool_call: { label: 'Tool', color: '#5ce0a0', bg: 'rgba(92, 224, 160, 0.12)' },
    heartbeat: { label: 'Heartbeat', color: '#f0a050', bg: 'rgba(240, 160, 80, 0.12)' },
  };

  // -- Derived --
  let agents = $derived.by(() => {
    const s = new Set(activityItems.map(i => i.agent).filter(Boolean));
    return [...s].sort();
  });

  let filtered = $derived.by(() => {
    let items = activityItems;

    // Category filter
    items = items.filter(i => enabledCategories[i.category] !== false);

    // Agent filter
    if (agentFilter !== 'all') {
      items = items.filter(i => i.agent === agentFilter);
    }

    // Search
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      items = items.filter(i =>
        `${i.action || ''} ${i.detail || ''} ${i.agent || ''}`.toLowerCase().includes(q),
      );
    }

    return items.slice(0, 300);
  });

  // -- Time formatting --
  function relativeTime(ts: string): string {
    try {
      const diff = nowTick - new Date(ts).getTime();
      if (diff < 0) return 'just now';
      const secs = Math.floor(diff / 1000);
      if (secs < 60) return `${secs}s ago`;
      const mins = Math.floor(secs / 60);
      if (mins < 60) return `${mins}m ago`;
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return `${hrs}h ago`;
      const days = Math.floor(hrs / 24);
      return `${days}d ago`;
    } catch {
      return '';
    }
  }

  function absoluteTime(ts: string): string {
    try {
      const d = new Date(ts);
      return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} ${d.toLocaleTimeString('en-US', { hour12: false })}`;
    } catch {
      return ts?.slice(0, 19) || '';
    }
  }

  function truncate(s: string, max: number): string {
    if (!s) return '-';
    const clean = s.replace(/\n/g, ' ').trim();
    if (clean.length <= max) return clean;
    return clean.slice(0, max) + '...';
  }

  function formatDuration(detail: string): string {
    // Extract duration from detail string like "~1,234 tokens (600 in, 634 out) | 2.3s | 5 tools"
    const match = detail.match(/(\d+\.?\d*)s/);
    if (match) return `${match[1]}s`;
    return '-';
  }

  function displayAgent(name: string): string {
    return (name || '').replace(/_/g, ' ');
  }

  // -- Data loading --
  export async function load() {
    if (!api) return;
    activityLoading = true;
    try {
      const days = timeRange === 0 ? 365 : Math.ceil(timeRange / 24) || 1;
      activityItems = (await api.getActivity(days, 500)) as ActivityItem[] || [];
    } catch {
      activityItems = [];
    }
    activityLoading = false;
  }

  // -- Auto-refresh --
  function toggleAutoRefresh() {
    autoRefresh = !autoRefresh;
    if (autoRefresh) {
      autoRefreshTimer = setInterval(() => load(), 10_000);
    } else if (autoRefreshTimer) {
      clearInterval(autoRefreshTimer);
      autoRefreshTimer = null;
    }
  }

  // Tick the relative times every 15s
  $effect(() => {
    tickTimer = setInterval(() => {
      nowTick = Date.now();
    }, 15_000);
    return () => {
      if (tickTimer) clearInterval(tickTimer);
      if (autoRefreshTimer) clearInterval(autoRefreshTimer);
    };
  });

  // Reload when time range changes (skip initial mount - Settings.svelte calls load())
  let prevTimeRange = $state(timeRange);
  $effect(() => {
    const current = timeRange;
    if (current !== prevTimeRange) {
      prevTimeRange = current;
      load();
    }
  });
</script>

<!-- Toolbar -->
<div class="toolbar">
  <div class="toolbar-left">
    <!-- Time range -->
    <div class="range-group">
      {#each [['1h', 1], ['6h', 6], ['24h', 24], ['All', 0]] as [label, hours]}
        <button
          class="range-btn"
          class:active={timeRange === hours}
          onclick={() => { timeRange = hours as number; }}
        >{label}</button>
      {/each}
    </div>

    <!-- Agent picker -->
    <select class="agent-select" bind:value={agentFilter}>
      <option value="all">All agents</option>
      {#each agents as a}
        <option value={a}>{displayAgent(a)}</option>
      {/each}
    </select>

    <!-- Category toggles -->
    <div class="category-toggles">
      {#each Object.entries(categoryConfig) as [key, cfg]}
        <label class="cat-toggle" class:checked={enabledCategories[key]}>
          <input type="checkbox" bind:checked={enabledCategories[key]} />
          <span class="cat-dot" style="background: {cfg.color}"></span>
          <span class="cat-label">{cfg.label}</span>
        </label>
      {/each}
    </div>
  </div>

  <div class="toolbar-right">
    <!-- Search -->
    <input
      type="text"
      class="search-input"
      placeholder="Search..."
      bind:value={searchQuery}
    />

    <!-- Auto-refresh -->
    <button
      class="auto-refresh-btn"
      class:active={autoRefresh}
      onclick={toggleAutoRefresh}
      title={autoRefresh ? 'Auto-refresh on (10s)' : 'Auto-refresh off'}
    >
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <path d="M14 8a6 6 0 11-1.5-3.97" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        <path d="M14 2v4h-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
  </div>
</div>

<!-- Count -->
<div class="count-bar">
  {#if activityItems.length > 0}
    <span>{filtered.length} of {activityItems.length} events</span>
  {:else}
    <span>No activity recorded</span>
  {/if}
  {#if autoRefresh}
    <span class="live-dot"></span>
  {/if}
</div>

<!-- Table -->
{#if activityLoading && activityItems.length === 0}
  <p class="placeholder">Loading...</p>
{:else if filtered.length === 0}
  <p class="placeholder">No matching events</p>
{:else}
  <div class="table-wrap">
    <table class="activity-table">
      <thead>
        <tr>
          <th class="col-time">Time</th>
          <th class="col-agent">Agent</th>
          <th class="col-type">Type</th>
          <th class="col-action">Action</th>
          <th class="col-summary">Summary</th>
          <th class="col-dur">Duration</th>
        </tr>
      </thead>
      <tbody>
        {#each filtered as item, i}
          {@const cfg = categoryConfig[item.category] || { label: item.category, color: '#888', bg: 'rgba(136,136,136,0.12)' }}
          <tr
            class="data-row"
            class:expanded={expandedRow === i}
            class:flagged={item.flagged}
            onclick={() => expandedRow = expandedRow === i ? null : i}
          >
            <td class="col-time" title={absoluteTime(item.timestamp)}>
              {relativeTime(item.timestamp)}
            </td>
            <td class="col-agent">{displayAgent(item.agent)}</td>
            <td class="col-type">
              <span class="type-pill" style="color: {cfg.color}; background: {cfg.bg}">
                {cfg.label}
              </span>
              {#if item.flagged}
                <span class="flag-badge">!</span>
              {/if}
            </td>
            <td class="col-action">{item.action || '-'}</td>
            <td class="col-summary">{truncate(item.detail, 80)}</td>
            <td class="col-dur">{item.category === 'inference' ? formatDuration(item.detail) : '-'}</td>
          </tr>
          {#if expandedRow === i}
            <tr class="detail-row">
              <td colspan="6">
                <div class="detail-panel">
                  <div class="detail-header">
                    <span class="detail-agent">{displayAgent(item.agent)}</span>
                    <span class="type-pill" style="color: {cfg.color}; background: {cfg.bg}">{cfg.label}</span>
                    <span class="detail-action">{item.action}</span>
                    <span class="detail-ts">{absoluteTime(item.timestamp)}</span>
                  </div>
                  <pre class="detail-content">{item.detail || '(no detail)'}</pre>
                </div>
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  /* -- Toolbar -- */
  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 10px;
    flex-wrap: wrap;
  }

  .toolbar-left {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .toolbar-right {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  /* Time range buttons */
  .range-group {
    display: flex;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    overflow: hidden;
  }

  .range-btn {
    padding: 4px 10px;
    font-size: 11px;
    font-family: var(--font-sans);
    background: transparent;
    border: none;
    border-right: 1px solid rgba(255, 255, 255, 0.06);
    color: rgba(255, 255, 255, 0.4);
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .range-btn:last-child {
    border-right: none;
  }

  .range-btn:hover {
    background: rgba(255, 255, 255, 0.06);
  }

  .range-btn.active {
    background: rgba(255, 255, 255, 0.12);
    color: rgba(255, 255, 255, 0.9);
  }

  /* Agent select */
  .agent-select {
    height: 26px;
    padding: 0 8px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    color: rgba(255, 255, 255, 0.6);
    font-size: 11px;
    font-family: var(--font-sans);
    min-width: 100px;
    outline: none;
    -webkit-appearance: none;
    appearance: none;
    cursor: pointer;
  }

  .agent-select option {
    background: rgb(30, 30, 35);
    color: rgba(255, 255, 255, 0.85);
  }

  /* Category toggles */
  .category-toggles {
    display: flex;
    gap: 6px;
    align-items: center;
  }

  .cat-toggle {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.3);
    cursor: pointer;
    padding: 3px 8px;
    border-radius: 4px;
    transition: color 0.15s, background 0.15s;
  }

  .cat-toggle:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .cat-toggle.checked {
    color: rgba(255, 255, 255, 0.7);
  }

  .cat-toggle input {
    display: none;
  }

  .cat-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .cat-label {
    white-space: nowrap;
  }

  .cat-toggle:not(.checked) .cat-dot {
    opacity: 0.3;
  }

  /* Search */
  .search-input {
    width: 140px;
    height: 26px;
    padding: 0 8px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    color: white;
    font-size: 11px;
    font-family: var(--font-sans);
    outline: none;
    transition: border-color 0.15s;
  }

  .search-input:focus {
    border-color: rgba(255, 255, 255, 0.2);
  }

  .search-input::placeholder {
    color: rgba(255, 255, 255, 0.25);
  }

  /* Auto-refresh */
  .auto-refresh-btn {
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    color: rgba(255, 255, 255, 0.35);
    cursor: pointer;
    transition: all 0.15s;
  }

  .auto-refresh-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.7);
  }

  .auto-refresh-btn.active {
    background: rgba(100, 140, 255, 0.15);
    border-color: rgba(100, 140, 255, 0.3);
    color: rgba(100, 140, 255, 0.9);
  }

  .auto-refresh-btn.active svg {
    animation: spin 2s linear infinite;
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  /* Count bar */
  .count-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    margin-bottom: 8px;
  }

  .live-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgba(100, 140, 255, 0.8);
    animation: pulse 2s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  /* Placeholder */
  .placeholder {
    color: var(--text-dim);
    font-size: 13px;
    text-align: center;
    padding: 40px 0;
  }

  /* Table */
  .table-wrap {
    overflow-y: auto;
    max-height: calc(100vh - 260px);
    border-radius: 8px;
  }

  .activity-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    font-family: var(--font-sans);
    table-layout: fixed;
  }

  .activity-table thead {
    position: sticky;
    top: 0;
    z-index: 2;
  }

  .activity-table th {
    text-align: left;
    padding: 6px 10px;
    color: rgba(255, 255, 255, 0.4);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    background: var(--bg-alt, #141418);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    white-space: nowrap;
  }

  /* Column widths */
  .col-time { width: 72px; }
  .col-agent { width: 90px; }
  .col-type { width: 90px; }
  .col-action { width: 120px; }
  .col-summary { width: auto; }
  .col-dur { width: 60px; text-align: right; }

  /* Data rows */
  .data-row {
    cursor: pointer;
    transition: background 0.1s;
  }

  .data-row td {
    padding: 5px 10px;
    color: rgba(255, 255, 255, 0.55);
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    vertical-align: middle;
  }

  .data-row:hover td {
    background: rgba(255, 255, 255, 0.03);
  }

  .data-row.expanded td {
    background: rgba(255, 255, 255, 0.04);
    border-bottom-color: transparent;
  }

  .data-row.flagged td:first-child {
    box-shadow: inset 3px 0 0 rgba(255, 100, 100, 0.5);
  }

  /* Time column */
  .data-row .col-time {
    color: rgba(255, 255, 255, 0.35);
    font-size: 11px;
    font-family: var(--font-mono);
  }

  /* Agent column */
  .data-row .col-agent {
    color: rgba(255, 255, 255, 0.45);
    font-size: 11px;
    text-transform: capitalize;
  }

  /* Action column */
  .data-row .col-action {
    color: rgba(255, 255, 255, 0.75);
    font-weight: 500;
    font-size: 12px;
  }

  /* Summary column */
  .data-row .col-summary {
    color: rgba(255, 255, 255, 0.35);
    font-size: 11px;
  }

  /* Duration column */
  .data-row .col-dur {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    font-family: var(--font-mono);
    text-align: right;
  }

  /* Type pill */
  .type-pill {
    display: inline-block;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 7px;
    border-radius: 4px;
    white-space: nowrap;
    letter-spacing: 0.2px;
  }

  /* Flag badge */
  .flag-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: rgba(255, 100, 100, 0.15);
    color: #ff6b6b;
    font-size: 9px;
    font-weight: bold;
    margin-left: 4px;
    vertical-align: middle;
  }

  /* Detail row (expanded) */
  .detail-row td {
    padding: 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    background: rgba(255, 255, 255, 0.02);
  }

  .detail-panel {
    padding: 10px 14px 12px;
  }

  .detail-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }

  .detail-agent {
    color: rgba(255, 255, 255, 0.7);
    font-size: 12px;
    font-weight: 600;
    text-transform: capitalize;
  }

  .detail-action {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    font-weight: 500;
  }

  .detail-ts {
    margin-left: auto;
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    white-space: nowrap;
  }

  .detail-content {
    margin: 0;
    padding: 8px 10px;
    background: rgba(0, 0, 0, 0.25);
    border-radius: 4px;
    color: rgba(255, 255, 255, 0.55);
    font-size: 11px;
    font-family: var(--font-mono);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 220px;
    overflow-y: auto;
    line-height: 1.5;
  }
</style>

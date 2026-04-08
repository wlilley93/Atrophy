<script lang="ts">
  import { api } from '../../api';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  let usagePeriod = $state<number>(14);
  let usageData = $state<any[]>([]);
  let dailyData = $state<any[]>([]);
  let usageLoading = $state(false);

  // Expandable detail state
  let expandedAgent = $state<string | null>(null);
  let detailData = $state<any[]>([]);
  let detailLoading = $state(false);

  // ---------------------------------------------------------------------------
  // Public load method (called by parent)
  // ---------------------------------------------------------------------------

  export async function load(days?: number | null) {
    if (days !== undefined && days !== null) usagePeriod = days;
    await loadUsage(usagePeriod);
  }

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  async function loadUsage(days: number) {
    usagePeriod = days;
    if (!api) return;
    usageLoading = true;
    expandedAgent = null;
    detailData = [];
    try {
      const [summary, daily] = await Promise.all([
        api.getUsage(days) as Promise<any[]>,
        api.getUsageDaily(days) as Promise<any[]>,
      ]);
      usageData = summary || [];
      dailyData = daily || [];
    } catch {
      usageData = [];
      dailyData = [];
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
      detailData = await api!.getUsageDetail(agentName, usagePeriod) as any[] || [];
    } catch {
      detailData = [];
    }
    detailLoading = false;
  }

  // ---------------------------------------------------------------------------
  // Colour generation (deterministic from agent name)
  // ---------------------------------------------------------------------------

  function hashStr(s: string): number {
    let h = 0;
    for (let i = 0; i < s.length; i++) {
      h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    }
    return Math.abs(h);
  }

  function agentColour(name: string): string {
    const palette = [
      '#7c6ef0', '#e06090', '#50b8d0', '#e8a040', '#60c878',
      '#c878d0', '#d07050', '#50a0e0', '#b0b040', '#e07088',
      '#40c0a0', '#a080e0', '#d0a070', '#70b0d0', '#c06090',
    ];
    return palette[hashStr(name) % palette.length];
  }

  // ---------------------------------------------------------------------------
  // Derived data
  // ---------------------------------------------------------------------------

  const activeAgents = $derived(
    usageData.filter((a: any) => a.total_calls > 0)
  );

  const totalTokens = $derived(
    usageData.reduce((s: number, a: any) => s + (a.total_tokens || 0), 0)
  );

  const totalTokensIn = $derived(
    usageData.reduce((s: number, a: any) => s + (a.total_tokens_in || 0), 0)
  );

  const totalTokensOut = $derived(
    usageData.reduce((s: number, a: any) => s + (a.total_tokens_out || 0), 0)
  );

  const avgTokensPerDay = $derived(
    usagePeriod > 0 ? Math.round(totalTokens / usagePeriod) : 0
  );

  const mostActiveAgent = $derived(
    activeAgents.length > 0
      ? activeAgents.reduce((best: any, a: any) =>
          (a.total_tokens || 0) > (best.total_tokens || 0) ? a : best
        )
      : null
  );

  const costEstimate = $derived.by(() => {
    // Rough: $3/M input, $15/M output
    const inputCost = (totalTokensIn / 1_000_000) * 3;
    const outputCost = (totalTokensOut / 1_000_000) * 15;
    return inputCost + outputCost;
  });

  // ---------------------------------------------------------------------------
  // Chart data
  // ---------------------------------------------------------------------------

  // Generate all dates in the period
  const dateRange = $derived.by(() => {
    const dates: string[] = [];
    const now = new Date();
    for (let i = usagePeriod - 1; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      dates.push(d.toISOString().slice(0, 10));
    }
    return dates;
  });

  // Unique agent names in daily data
  const dailyAgentNames = $derived.by(() => {
    const names = new Set<string>();
    for (const row of dailyData) {
      names.add(row.agent_name);
    }
    return Array.from(names);
  });

  // Build stacked data: for each date, per-agent tokens
  const stackedData = $derived.by(() => {
    const agents = dailyAgentNames;
    const lookup = new Map<string, number>(); // "date|agent" -> tokens
    for (const row of dailyData) {
      lookup.set(`${row.date}|${row.agent_name}`, row.tokens || 0);
    }

    // For each date, compute stacked segments
    return dateRange.map(date => {
      const segments: { agent: string; displayName: string; tokens: number; y0: number; y1: number }[] = [];
      let cum = 0;
      for (const agent of agents) {
        const tokens = lookup.get(`${date}|${agent}`) || 0;
        if (tokens > 0) {
          const displayRow = dailyData.find(r => r.agent_name === agent);
          segments.push({
            agent,
            displayName: displayRow?.display_name || agent,
            tokens,
            y0: cum,
            y1: cum + tokens,
          });
          cum += tokens;
        }
      }
      return { date, total: cum, segments };
    });
  });

  const maxDayTokens = $derived(
    Math.max(1, ...stackedData.map(d => d.total))
  );

  // Per-agent daily data for sparklines
  const agentDailyMap = $derived.by(() => {
    const map = new Map<string, number[]>();
    for (const agent of activeAgents) {
      const values = dateRange.map(date => {
        const row = dailyData.find(
          (r: any) => r.date === date && r.agent_name === agent.agent_name
        );
        return row ? row.tokens : 0;
      });
      map.set(agent.agent_name, values);
    }
    return map;
  });

  // ---------------------------------------------------------------------------
  // Formatters
  // ---------------------------------------------------------------------------

  function formatTokens(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
  }

  function formatCost(n: number): string {
    if (n >= 100) return '$' + Math.round(n);
    if (n >= 1) return '$' + n.toFixed(2);
    if (n >= 0.01) return '$' + n.toFixed(2);
    return '<$0.01';
  }

  function formatDateLabel(dateStr: string): string {
    const d = new Date(dateStr + 'T12:00:00');
    const today = new Date();
    today.setHours(12, 0, 0, 0);
    const diff = Math.round((today.getTime() - d.getTime()) / (24 * 60 * 60 * 1000));
    if (diff === 0) return 'Today';
    if (diff === 1) return 'Yest.';
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
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

  // Y-axis tick values
  function yTicks(max: number): number[] {
    if (max <= 0) return [0];
    const magnitude = Math.pow(10, Math.floor(Math.log10(max)));
    let step = magnitude;
    if (max / step < 3) step = magnitude / 2;
    if (max / step > 8) step = magnitude * 2;
    const ticks: number[] = [];
    for (let v = 0; v <= max * 1.05; v += step) {
      ticks.push(Math.round(v));
    }
    if (ticks.length < 2) ticks.push(Math.round(max));
    return ticks;
  }

  // Sparkline path
  function sparklinePath(values: number[], w: number, h: number): string {
    if (!values.length || values.every(v => v === 0)) return '';
    const max = Math.max(1, ...values);
    const step = w / Math.max(1, values.length - 1);
    return values
      .map((v, i) => {
        const x = i * step;
        const y = h - (v / max) * (h - 2) - 1;
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }

  // ---------------------------------------------------------------------------
  // Chart constants
  // ---------------------------------------------------------------------------

  const CHART_H = 220;
  const CHART_PADDING_LEFT = 52;
  const CHART_PADDING_RIGHT = 12;
  const CHART_PADDING_TOP = 12;
  const CHART_PADDING_BOTTOM = 32;

  // Tooltip state
  let tooltipBar = $state<number | null>(null);
  let tooltipX = $state(0);
  let tooltipY = $state(0);
</script>

<!-- Period picker -->
<div class="filter-row">
  {#each [[7, '7 days'], [14, '14 days'], [30, '30 days']] as [days, label]}
    <button
      class="filter-pill"
      class:active={usagePeriod === days}
      onclick={() => loadUsage(days as number)}
    >{label}</button>
  {/each}
</div>

{#if usageLoading}
  <p class="placeholder">Loading...</p>
{:else if usageData.length === 0 || usageData.every((a: any) => a.total_calls === 0)}
  <p class="placeholder">No usage data yet. Stats will appear after inference calls.</p>
{:else}

  <!-- ====== Summary cards ====== -->
  <div class="summary-grid">
    <div class="summary-card">
      <div class="summary-value">{formatTokens(totalTokens)}</div>
      <div class="summary-label">Total tokens</div>
    </div>
    <div class="summary-card">
      <div class="summary-value">{formatTokens(avgTokensPerDay)}</div>
      <div class="summary-label">Avg / day</div>
    </div>
    <div class="summary-card">
      <div class="summary-value">{mostActiveAgent?.display_name || mostActiveAgent?.agent_name || '-'}</div>
      <div class="summary-label">Most active</div>
    </div>
    <div class="summary-card">
      <div class="summary-value">{formatCost(costEstimate)}</div>
      <div class="summary-label">Cost (est.)</div>
    </div>
  </div>

  <!-- ====== Bar chart ====== -->
  {@const data = stackedData}
  {@const max = maxDayTokens}
  {@const ticks = yTicks(max)}
  {@const barAreaW = 600 - CHART_PADDING_LEFT - CHART_PADDING_RIGHT}
  {@const barAreaH = CHART_H - CHART_PADDING_TOP - CHART_PADDING_BOTTOM}
  {@const barCount = data.length}
  {@const barGap = Math.max(2, Math.min(6, barAreaW / barCount * 0.2))}
  {@const barW = Math.max(4, (barAreaW - barGap * barCount) / barCount)}

  <div class="chart-container">
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <svg
      viewBox="0 0 600 {CHART_H}"
      preserveAspectRatio="xMidYMid meet"
      class="chart-svg"
      onmouseleave={() => { tooltipBar = null; }}
    >
      <!-- Y axis gridlines and labels -->
      {#each ticks as tick}
        {@const y = CHART_PADDING_TOP + barAreaH - (tick / max) * barAreaH}
        <line
          x1={CHART_PADDING_LEFT}
          y1={y}
          x2={600 - CHART_PADDING_RIGHT}
          y2={y}
          stroke="rgba(255,255,255,0.06)"
          stroke-width="1"
        />
        <text
          x={CHART_PADDING_LEFT - 6}
          y={y + 2}
          text-anchor="end"
          fill="rgba(255,255,255,0.3)"
          font-size="5"
          font-family="var(--font-sans)"
        >{formatTokens(tick)}</text>
      {/each}

      <!-- Bars -->
      {#each data as day, i}
        {@const x = CHART_PADDING_LEFT + i * (barW + barGap) + barGap / 2}
        <!-- Invisible hit area -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <rect
          x={x}
          y={CHART_PADDING_TOP}
          width={barW}
          height={barAreaH}
          fill="transparent"
          onmouseenter={(e) => { tooltipBar = i; tooltipX = x + barW / 2; tooltipY = CHART_PADDING_TOP; }}
          onmouseleave={() => { tooltipBar = null; }}
        />
        {#each day.segments as seg}
          {@const segH = (seg.tokens / max) * barAreaH}
          {@const segY = CHART_PADDING_TOP + barAreaH - (seg.y1 / max) * barAreaH}
          <rect
            x={x}
            y={segY}
            width={barW}
            height={Math.max(1, segH)}
            rx="2"
            fill={agentColour(seg.agent)}
            opacity={tooltipBar === i ? 1 : 0.8}
            style="transition: opacity 0.15s; pointer-events: none;"
          />
        {/each}

        <!-- X-axis date label (show every Nth to avoid overlap) -->
        {#if barCount <= 14 || i % Math.ceil(barCount / 10) === 0 || i === barCount - 1}
          <text
            x={x + barW / 2}
            y={CHART_H - 4}
            text-anchor="middle"
            fill="rgba(255,255,255,0.35)"
            font-size="5"
            font-family="var(--font-sans)"
          >{formatDateLabel(day.date)}</text>
        {/if}
      {/each}

      <!-- Tooltip -->
      {#if tooltipBar !== null && data[tooltipBar]}
        {@const tip = data[tooltipBar]}
        {@const tw = 90}
        {@const th = 9 + tip.segments.length * 8 + 4}
        {@const tx = Math.min(Math.max(tooltipX - tw / 2, 4), 600 - tw - 4)}
        {@const ty = Math.max(4, tooltipY - th - 5)}
        <rect
          x={tx}
          y={ty}
          width={tw}
          height={th}
          rx="3"
          fill="rgba(20,20,24,0.95)"
          stroke="rgba(255,255,255,0.12)"
          stroke-width="0.3"
        />
        <text x={tx + 4} y={ty + 7} fill="rgba(255,255,255,0.7)" font-size="5" font-family="var(--font-sans)">
          {formatDateLabel(tip.date)} - {formatTokens(tip.total)}
        </text>
        {#each tip.segments as seg, si}
          <circle cx={tx + 6} cy={ty + 13 + si * 8} r="1.5" fill={agentColour(seg.agent)} />
          <text x={tx + 11} y={ty + 15 + si * 8} fill="rgba(255,255,255,0.6)" font-size="5" font-family="var(--font-sans)">
            {seg.displayName}: {formatTokens(seg.tokens)}
          </text>
        {/each}
      {/if}
    </svg>

    <!-- Legend -->
    {#if dailyAgentNames.length > 1}
      <div class="chart-legend">
        {#each dailyAgentNames as agent}
          {@const displayRow = dailyData.find((r: any) => r.agent_name === agent)}
          <span class="legend-item">
            <span class="legend-dot" style="background: {agentColour(agent)}"></span>
            {displayRow?.display_name || agent}
          </span>
        {/each}
      </div>
    {/if}
  </div>

  <!-- ====== Per-agent breakdown table ====== -->
  <div class="breakdown-header">Per-agent breakdown</div>
  <div class="breakdown-table">
    {#each activeAgents
      .slice()
      .sort((a: any, b: any) => (b.total_tokens || 0) - (a.total_tokens || 0)) as agent}
      {@const pct = totalTokens > 0 ? ((agent.total_tokens || 0) / totalTokens * 100) : 0}
      {@const tokIn = agent.total_tokens_in || 0}
      {@const tokOut = agent.total_tokens_out || 0}
      {@const inOutRatio = tokOut > 0 ? (tokIn / tokOut).toFixed(1) : '-'}
      {@const sparkVals = agentDailyMap.get(agent.agent_name) || []}
      {@const colour = agentColour(agent.agent_name)}

      <div class="breakdown-row" class:expanded={expandedAgent === agent.agent_name}>
        <button class="breakdown-row-btn" onclick={() => toggleDetail(agent.agent_name)}>
          <span class="br-colour" style="background: {colour}"></span>
          <span class="br-name">{agent.display_name || agent.agent_name}</span>
          <span class="br-sparkline">
            {#if sparkVals.length > 1}
              <svg viewBox="0 0 60 16" class="sparkline-svg">
                <path
                  d={sparklinePath(sparkVals, 60, 16)}
                  fill="none"
                  stroke={colour}
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            {/if}
          </span>
          <span class="br-tokens">{formatTokens(agent.total_tokens || 0)}</span>
          <span class="br-pct">{pct.toFixed(1)}%</span>
          <span class="br-ratio" title="Input:Output ratio">{inOutRatio}:1</span>
          <span class="br-expand" class:open={expandedAgent === agent.agent_name}>&#9662;</span>
        </button>

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
  </div>
{/if}

<style>
  /* ── Period picker ── */

  .filter-row {
    display: flex;
    gap: 6px;
    align-items: center;
    margin-bottom: 14px;
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
    font-family: var(--font-sans);
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

  /* ── Summary cards ── */

  .summary-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 16px;
  }

  .summary-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    padding: 12px 10px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }

  .summary-value {
    color: rgba(255, 255, 255, 0.92);
    font-size: 14px;
    font-weight: 700;
    font-family: var(--font-sans);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
  }

  .summary-label {
    color: rgba(255, 255, 255, 0.35);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-family: var(--font-sans);
  }

  /* ── Bar chart ── */

  .chart-container {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    padding: 8px 4px 4px;
    margin-bottom: 16px;
  }

  .chart-svg {
    width: 100%;
    height: auto;
    display: block;
  }

  .chart-legend {
    display: flex;
    gap: 12px;
    justify-content: center;
    flex-wrap: wrap;
    padding: 6px 0 4px;
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 4px;
    color: rgba(255, 255, 255, 0.45);
    font-size: 10px;
    font-family: var(--font-sans);
  }

  .legend-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  /* ── Breakdown table ── */

  .breakdown-header {
    color: rgba(255, 255, 255, 0.35);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
    font-family: var(--font-sans);
  }

  .breakdown-table {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .breakdown-row {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 6px;
    transition: background 0.15s;
  }

  .breakdown-row.expanded {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .breakdown-row-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 8px 10px;
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
    font-family: var(--font-sans);
  }

  .breakdown-row-btn:hover {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 6px;
  }

  .br-colour {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    flex-shrink: 0;
  }

  .br-name {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12.5px;
    font-weight: 600;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .br-sparkline {
    width: 60px;
    height: 16px;
    flex-shrink: 0;
  }

  .sparkline-svg {
    width: 60px;
    height: 16px;
    display: block;
  }

  .br-tokens {
    color: rgba(255, 255, 255, 0.6);
    font-size: 11px;
    font-family: var(--font-mono);
    min-width: 48px;
    text-align: right;
  }

  .br-pct {
    color: rgba(255, 255, 255, 0.35);
    font-size: 10px;
    min-width: 36px;
    text-align: right;
  }

  .br-ratio {
    color: rgba(255, 255, 255, 0.25);
    font-size: 10px;
    min-width: 32px;
    text-align: right;
  }

  .br-expand {
    color: rgba(255, 255, 255, 0.25);
    font-size: 10px;
    transition: transform 0.2s;
    flex-shrink: 0;
  }

  .br-expand.open {
    transform: rotate(180deg);
  }

  /* ── Detail panel (expanded row) ── */

  .detail-panel {
    margin: 0 10px 10px;
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

<script lang="ts">
  import { api } from '../../api';

  interface ScheduleEntry {
    name: string;
    agent: string;
    definition: { cron?: string; script: string; description?: string; type?: string; interval_seconds?: number };
    nextRun: string | null;
    lastRun: string | null;
    running: boolean;
    disabled: boolean;
    consecutiveFailures?: number;
  }

  interface HistoryEntry {
    agent: string;
    job: string;
    exitCode: number;
    stdout: string;
    stderr: string;
    durationMs: number;
    timestamp: string;
  }

  interface AgentGroup {
    agent: string;
    jobs: ScheduleEntry[];
  }

  let jobsList = $state<ScheduleEntry[]>([]);
  let jobHistory = $state<HistoryEntry[]>([]);
  let jobsLoading = $state(false);
  let runningJob = $state<string | null>(null);
  let expandedHistory = $state<number | null>(null);
  let collapsedAgents = $state<Set<string>>(new Set());

  // Group jobs by agent
  const grouped: AgentGroup[] = $derived.by(() => {
    const map = new Map<string, ScheduleEntry[]>();
    for (const job of jobsList) {
      const list = map.get(job.agent) || [];
      list.push(job);
      map.set(job.agent, list);
    }
    return Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([agent, jobs]) => ({ agent, jobs }));
  });

  const totalJobs = $derived(jobsList.length);
  const activeJobs = $derived(jobsList.filter((j) => !j.disabled).length);
  const runningJobs = $derived(jobsList.filter((j) => j.running).length);

  export async function load() {
    if (!api) return;
    jobsLoading = true;
    try {
      const [schedule, history] = await Promise.all([
        api.getSchedule(),
        api.getJobHistory(),
      ]);
      jobsList = (schedule || []) as ScheduleEntry[];
      jobHistory = (history || []) as HistoryEntry[];
    } catch { /* ignore */ }
    jobsLoading = false;
  }

  async function triggerJob(agent: string, jobName: string) {
    if (!api || runningJob) return;
    runningJob = jobName;
    try {
      await api.runJobNow(agent, jobName);
      await load();
    } catch { /* ignore */ }
    runningJob = null;
  }

  async function handlePauseAll() {
    // TODO: Wire to api.pauseScheduler() once the IPC handler exists.
    // For now this is a no-op placeholder.
    (api as any)?.pauseScheduler?.();
  }

  async function handleResumeAll() {
    if (!api) return;
    try {
      // cronResetAll re-enables all disabled jobs in the scheduler
      await (window as any).atrophy?.cronResetAll?.()
        ?? (api as any).ipcRenderer?.invoke('cron:resetAll');
      // Fall back to direct IPC invoke if the preload method isn't exposed
    } catch { /* ignore */ }
    // Reload schedule to reflect changes
    await load();
  }

  function toggleAgent(agent: string) {
    const next = new Set(collapsedAgents);
    if (next.has(agent)) {
      next.delete(agent);
    } else {
      next.add(agent);
    }
    collapsedAgents = next;
  }

  // -- Formatting helpers --

  function cronToEnglish(cron: string): string {
    const parts = cron.trim().split(/\s+/);
    if (parts.length < 5) return cron;

    const [minute, hour, day, _month, dow] = parts;

    // every minute
    if (minute === '*' && hour === '*' && day === '*' && dow === '*') {
      return 'every minute';
    }

    // */N * * * * - every N minutes
    const minInterval = minute.match(/^\*\/(\d+)$/);
    if (minInterval && hour === '*' && day === '*' && dow === '*') {
      return `every ${minInterval[1]}m`;
    }

    // 0 */N * * * - every N hours
    const hourInterval = hour.match(/^\*\/(\d+)$/);
    if (minute === '0' && hourInterval && day === '*' && dow === '*') {
      return `every ${hourInterval[1]}h`;
    }

    // Fixed time patterns (minute and hour are numeric)
    const m = parseInt(minute, 10);
    const h = parseInt(hour, 10);
    if (!isNaN(m) && !isNaN(h)) {
      const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;

      // M H * * * - daily
      if (day === '*' && dow === '*') {
        return `daily at ${time}`;
      }

      // Day-of-week patterns
      const dayNames: Record<string, string> = {
        '0': 'Sundays',
        '1': 'Mondays',
        '2': 'Tuesdays',
        '3': 'Wednesdays',
        '4': 'Thursdays',
        '5': 'Fridays',
        '6': 'Saturdays',
        '7': 'Sundays',
      };

      if (day === '*') {
        // M H * * 1-5 - weekdays
        if (dow === '1-5') return `weekdays at ${time}`;
        // M H * * 0,6 or 6,0 - weekends
        if (dow === '0,6' || dow === '6,0') return `weekends at ${time}`;
        // M H * * N - specific day
        if (dayNames[dow]) return `${dayNames[dow]} at ${time}`;

        // Comma-separated days
        const dayList = dow.split(',');
        if (dayList.every((d) => dayNames[d])) {
          const names = dayList.map((d) => dayNames[d]);
          return `${names.join(', ')} at ${time}`;
        }

        // Range like 1-3
        const rangeMatch = dow.match(/^(\d)-(\d)$/);
        if (rangeMatch && dayNames[rangeMatch[1]] && dayNames[rangeMatch[2]]) {
          return `${dayNames[rangeMatch[1]].replace(/s$/, '')}-${dayNames[rangeMatch[2]]} at ${time}`;
        }

        return `${dow} at ${time}`;
      }

      // M H D * * - monthly on day D
      const d = parseInt(day, 10);
      if (!isNaN(d) && dow === '*') {
        const suffix = d === 1 ? 'st' : d === 2 ? 'nd' : d === 3 ? 'rd' : 'th';
        return `monthly on ${d}${suffix} at ${time}`;
      }

      // Best effort for remaining patterns
      return `${day !== '*' ? `day ${day} ` : ''}${dow !== '*' ? `dow ${dow} ` : ''}at ${time}`;
    }

    return cron;
  }

  function formatSchedule(job: ScheduleEntry): string {
    if (job.definition.interval_seconds) {
      const s = job.definition.interval_seconds;
      if (s >= 3600) return `every ${(s / 3600).toFixed(s % 3600 ? 1 : 0)}h`;
      if (s >= 60) return `every ${Math.round(s / 60)}m`;
      return `every ${s}s`;
    }
    if (job.definition.cron) return cronToEnglish(job.definition.cron);
    return '';
  }

  function formatRelativeTime(isoString: string | null): string {
    if (!isoString) return '-';
    try {
      const target = new Date(isoString).getTime();
      const now = Date.now();
      const diffMs = target - now;

      if (Math.abs(diffMs) < 30000) return 'now';

      const absDiff = Math.abs(diffMs);
      const prefix = diffMs > 0 ? 'in ' : '';
      const suffix = diffMs < 0 ? ' ago' : '';

      if (absDiff < 60000) return `${prefix}${Math.round(absDiff / 1000)}s${suffix}`;
      if (absDiff < 3600000) return `${prefix}${Math.round(absDiff / 60000)}m${suffix}`;
      if (absDiff < 86400000) return `${prefix}${(absDiff / 3600000).toFixed(1)}h${suffix}`;
      return `${prefix}${(absDiff / 86400000).toFixed(1)}d${suffix}`;
    } catch {
      return '-';
    }
  }

  function formatTimestamp(ts: string): string {
    try {
      const d = new Date(ts);
      return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}  ${d.toLocaleTimeString('en-US', { hour12: false })}`;
    } catch {
      return ts?.slice(0, 19) || '';
    }
  }

  function statusLabel(job: ScheduleEntry): string {
    if (job.running) return 'running';
    if (job.disabled) return 'disabled';
    return 'active';
  }

  function statusClass(job: ScheduleEntry): string {
    if (job.running) return 'status-running';
    if (job.disabled) return 'status-disabled';
    return 'status-active';
  }
</script>

{#if jobsLoading}
  <p class="placeholder">Loading...</p>
{:else}
  <!-- Toolbar -->
  <div class="toolbar">
    <div class="toolbar-stats">
      <span class="stat">{totalJobs} jobs</span>
      <span class="stat-sep"></span>
      <span class="stat">{activeJobs} active</span>
      {#if runningJobs > 0}
        <span class="stat-sep"></span>
        <span class="stat running">{runningJobs} running</span>
      {/if}
    </div>
    <div class="toolbar-actions">
      <button class="toolbar-btn" onclick={handlePauseAll}>Pause All</button>
      <button class="toolbar-btn primary" onclick={handleResumeAll}>Resume All</button>
    </div>
  </div>

  <!-- Scheduled Jobs -->
  <div class="section">
    <div class="section-header">Scheduled Jobs</div>
    <div class="section-line"></div>

    {#if jobsList.length === 0}
      <p class="placeholder">No jobs configured</p>
    {:else}
      {#each grouped as group}
        <div class="agent-group">
          <button class="agent-header" onclick={() => toggleAgent(group.agent)}>
            <span class="agent-chevron" class:collapsed={collapsedAgents.has(group.agent)}>&#9662;</span>
            <span class="agent-name">{group.agent}</span>
            <span class="agent-badge">{group.jobs.length}</span>
          </button>

          {#if !collapsedAgents.has(group.agent)}
            <table class="jobs-table">
              <thead>
                <tr>
                  <th class="col-job">Job</th>
                  <th class="col-schedule">Schedule</th>
                  <th class="col-status">Status</th>
                  <th class="col-next">Next Run</th>
                  <th class="col-actions">Actions</th>
                </tr>
              </thead>
              <tbody>
                {#each group.jobs as job, idx}
                  <tr class="job-row" class:alt={idx % 2 === 1}>
                    <td class="col-job">
                      <span
                        class="job-name"
                        title={job.definition.description || ''}
                      >{job.name}</span>
                    </td>
                    <td class="col-schedule">
                      <span class="schedule-text">{formatSchedule(job)}</span>
                    </td>
                    <td class="col-status">
                      <span class="status-pill {statusClass(job)}">{statusLabel(job)}</span>
                    </td>
                    <td class="col-next">
                      <span class="next-text">{formatRelativeTime(job.nextRun)}</span>
                    </td>
                    <td class="col-actions">
                      <button
                        class="run-btn"
                        disabled={runningJob !== null}
                        onclick={() => triggerJob(job.agent, job.name)}
                      >
                        {runningJob === job.name ? '...' : 'Run'}
                      </button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        </div>
      {/each}
    {/if}
  </div>

  <!-- Run History -->
  <div class="section">
    <div class="section-header">Run History</div>
    <div class="section-line"></div>

    {#if jobHistory.length === 0}
      <p class="placeholder">No runs yet this session</p>
    {:else}
      <table class="history-table">
        <thead>
          <tr>
            <th class="col-hist-status">Result</th>
            <th class="col-hist-job">Job</th>
            <th class="col-hist-agent">Agent</th>
            <th class="col-hist-duration">Duration</th>
            <th class="col-hist-time">Time</th>
          </tr>
        </thead>
        <tbody>
          {#each jobHistory as entry, i}
            <tr
              class="history-row"
              class:alt={i % 2 === 1}
              class:expanded={expandedHistory === i}
              onclick={() => expandedHistory = expandedHistory === i ? null : i}
            >
              <td class="col-hist-status">
                <span class="result-pill" class:ok={entry.exitCode === 0} class:fail={entry.exitCode !== 0}>
                  {entry.exitCode === 0 ? 'OK' : 'FAIL'}
                </span>
              </td>
              <td class="col-hist-job"><span class="hist-job-name">{entry.job}</span></td>
              <td class="col-hist-agent"><span class="hist-agent">{entry.agent}</span></td>
              <td class="col-hist-duration">
                <span class="hist-duration">{entry.durationMs < 1000 ? entry.durationMs + 'ms' : (entry.durationMs / 1000).toFixed(1) + 's'}</span>
              </td>
              <td class="col-hist-time">
                <span class="hist-time">{formatTimestamp(entry.timestamp)}</span>
              </td>
            </tr>
            {#if expandedHistory === i}
              <tr class="history-detail-row">
                <td colspan="5">
                  <pre class="history-detail">{entry.stdout || '(no output)'}{entry.stderr ? '\n\nSTDERR:\n' + entry.stderr : ''}</pre>
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
{/if}

<style>
  /* -- Toolbar -- */
  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 0 12px 0;
  }

  .toolbar-stats {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .stat {
    color: rgba(255, 255, 255, 0.4);
    font-size: 12px;
  }

  .stat.running {
    color: rgba(100, 160, 255, 0.7);
  }

  .stat-sep {
    width: 1px;
    height: 10px;
    background: rgba(255, 255, 255, 0.1);
  }

  .toolbar-actions {
    display: flex;
    gap: 6px;
  }

  .toolbar-btn {
    padding: 4px 12px;
    font-size: 11px;
    font-family: var(--font-sans);
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.5);
    border-radius: 6px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }

  .toolbar-btn:hover {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.8);
    border-color: rgba(255, 255, 255, 0.15);
  }

  .toolbar-btn.primary {
    background: rgba(92, 224, 214, 0.08);
    border-color: rgba(92, 224, 214, 0.2);
    color: rgba(92, 224, 214, 0.7);
  }

  .toolbar-btn.primary:hover {
    background: rgba(92, 224, 214, 0.14);
    color: rgba(92, 224, 214, 0.9);
    border-color: rgba(92, 224, 214, 0.35);
  }

  /* -- Sections -- */
  .section {
    margin-bottom: 20px;
  }

  .section-header {
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding-bottom: 4px;
  }

  .section-line {
    height: 1px;
    background: rgba(255, 255, 255, 0.08);
    margin-bottom: 10px;
  }

  .placeholder {
    color: var(--text-dim);
    font-size: 13px;
    text-align: center;
    padding: 40px 0;
  }

  /* -- Agent groups -- */
  .agent-group {
    margin-bottom: 8px;
  }

  .agent-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 4px;
    width: 100%;
    background: none;
    border: none;
    cursor: pointer;
    color: inherit;
    font-family: var(--font-sans);
    text-align: left;
    border-radius: 4px;
    transition: background 0.12s;
  }

  .agent-header:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .agent-chevron {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
    transition: transform 0.15s ease;
    display: inline-block;
  }

  .agent-chevron.collapsed {
    transform: rotate(-90deg);
  }

  .agent-name {
    color: rgba(255, 255, 255, 0.75);
    font-size: 13px;
    font-weight: 600;
  }

  .agent-badge {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.4);
    background: rgba(255, 255, 255, 0.06);
    padding: 1px 7px;
    border-radius: 8px;
    font-weight: 600;
  }

  /* -- Jobs table -- */
  .jobs-table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
  }

  .jobs-table thead th {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    padding: 4px 8px;
    text-align: left;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .col-job { width: 30%; }
  .col-schedule { width: 22%; }
  .col-status { width: 14%; }
  .col-next { width: 18%; }
  .col-actions { width: 16%; text-align: right; }

  .jobs-table thead .col-actions {
    text-align: right;
  }

  .job-row {
    transition: background 0.1s;
  }

  .job-row:hover {
    background: rgba(255, 255, 255, 0.03);
  }

  .job-row.alt {
    background: rgba(255, 255, 255, 0.015);
  }

  .job-row.alt:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .job-row td {
    padding: 5px 8px;
    vertical-align: middle;
  }

  .job-name {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    font-weight: 600;
    cursor: default;
  }

  .schedule-text {
    color: rgba(255, 255, 255, 0.4);
    font-size: 11px;
    font-family: var(--font-mono);
  }

  /* -- Status pills -- */
  .status-pill {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 10px;
    display: inline-block;
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }

  .status-active {
    background: rgba(92, 224, 214, 0.1);
    color: rgba(92, 224, 214, 0.7);
  }

  .status-disabled {
    background: rgba(255, 100, 100, 0.1);
    color: rgba(255, 100, 100, 0.6);
  }

  .status-running {
    background: rgba(100, 160, 255, 0.12);
    color: rgba(100, 160, 255, 0.8);
  }

  .next-text {
    color: rgba(255, 255, 255, 0.35);
    font-size: 11px;
    font-family: var(--font-mono);
  }

  .col-actions {
    text-align: right;
  }

  .run-btn {
    padding: 3px 10px;
    font-size: 11px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.5);
    border-radius: 4px;
    cursor: pointer;
    font-family: var(--font-sans);
    transition: background 0.15s, color 0.15s;
  }

  .run-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.8);
  }

  .run-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  /* -- History table -- */
  .history-table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
  }

  .history-table thead th {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    padding: 4px 8px;
    text-align: left;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .col-hist-status { width: 14%; }
  .col-hist-job { width: 28%; }
  .col-hist-agent { width: 18%; }
  .col-hist-duration { width: 16%; }
  .col-hist-time { width: 24%; }

  .history-row {
    cursor: pointer;
    transition: background 0.1s;
  }

  .history-row:hover {
    background: rgba(255, 255, 255, 0.03);
  }

  .history-row.alt {
    background: rgba(255, 255, 255, 0.015);
  }

  .history-row.alt:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .history-row.expanded {
    background: rgba(255, 255, 255, 0.04);
  }

  .history-row td {
    padding: 5px 8px;
    vertical-align: middle;
  }

  .result-pill {
    font-size: 9px;
    font-weight: bold;
    padding: 2px 8px;
    border-radius: 10px;
    display: inline-block;
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }

  .result-pill.ok {
    background: rgba(92, 224, 214, 0.1);
    color: rgba(92, 224, 214, 0.7);
  }

  .result-pill.fail {
    background: rgba(255, 100, 100, 0.1);
    color: rgba(255, 100, 100, 0.6);
  }

  .hist-job-name {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    font-weight: 600;
  }

  .hist-agent {
    color: rgba(255, 255, 255, 0.35);
    font-size: 11px;
  }

  .hist-duration {
    color: rgba(255, 255, 255, 0.25);
    font-size: 10px;
    font-family: var(--font-mono);
  }

  .hist-time {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    white-space: nowrap;
  }

  .history-detail-row td {
    padding: 0 8px 8px 8px;
  }

  .history-detail {
    margin: 0;
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

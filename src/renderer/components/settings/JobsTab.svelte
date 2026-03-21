<script lang="ts">
  import { api } from '../../api';

  let jobsList = $state<any[]>([]);
  let jobHistory = $state<any[]>([]);
  let jobsLoading = $state(false);
  let runningJob = $state<string | null>(null);
  let expandedJob = $state<number | null>(null);
  let jobLogContent = $state('');
  let jobLogName = $state<string | null>(null);

  export async function load() {
    if (!api) return;
    jobsLoading = true;
    try {
      const [jobs, history] = await Promise.all([
        api.getJobs(),
        api.getJobHistory(),
      ]);
      jobsList = jobs || [];
      jobHistory = history || [];
    } catch { /* ignore */ }
    jobsLoading = false;
  }

  async function triggerJob(name: string) {
    if (!api || runningJob) return;
    runningJob = name;
    try {
      await api.runJob(name);
      await load();
    } catch { /* ignore */ }
    runningJob = null;
  }

  async function viewJobLog(name: string) {
    if (!api) return;
    if (jobLogName === name) {
      jobLogName = null;
      jobLogContent = '';
      return;
    }
    jobLogName = name;
    try {
      jobLogContent = await api.readJobLog(name, 100) || '(empty)';
    } catch {
      jobLogContent = '(could not read log)';
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
</script>

{#if jobsLoading}
  <p class="placeholder">Loading...</p>
{:else}
  <!-- Registered jobs -->
  <div class="section">
    <div class="section-header">Scheduled Jobs</div>
    <div class="section-line"></div>

    {#if jobsList.length === 0}
      <p class="placeholder">No jobs configured</p>
    {:else}
      {#each jobsList as job}
        <div class="job-row">
          <div class="job-info">
            <span class="job-name">{job.name}</span>
            <span class="job-schedule">{job.schedule || ''}</span>
            <span class="job-status" class:installed={job.installed}>
              {job.installed ? 'installed' : 'not installed'}
            </span>
          </div>
          <div class="job-actions">
            <button
              class="job-btn"
              disabled={runningJob !== null}
              onclick={() => triggerJob(job.name)}
            >
              {runningJob === job.name ? '...' : 'Run'}
            </button>
            <button class="job-btn" onclick={() => viewJobLog(job.name)}>
              {jobLogName === job.name ? 'Hide' : 'Log'}
            </button>
          </div>
        </div>
        {#if job.description}
          <div class="job-desc">{job.description}</div>
        {/if}
        {#if jobLogName === job.name}
          <pre class="job-log">{jobLogContent}</pre>
        {/if}
      {/each}
    {/if}
  </div>

  <!-- Run history -->
  <div class="section">
    <div class="section-header">Run History</div>
    <div class="section-line"></div>

    {#if jobHistory.length === 0}
      <p class="placeholder">No runs yet this session</p>
    {:else}
      {#each jobHistory as entry, i}
        <button
          class="activity-card"
          class:expanded={expandedJob === i}
          onclick={() => expandedJob = expandedJob === i ? null : i}
        >
          <div class="activity-summary">
            <span class="activity-badge" style="color: {entry.exitCode === 0 ? '#5ce0d6' : '#ff6b6b'}">
              {entry.exitCode === 0 ? 'OK' : 'FAIL'}
            </span>
            <span class="activity-action">{entry.name}</span>
            <span class="activity-agent">{entry.agent}</span>
            <span class="activity-spacer"></span>
            <span class="job-duration">{entry.durationMs < 1000 ? entry.durationMs + 'ms' : (entry.durationMs / 1000).toFixed(1) + 's'}</span>
            <span class="activity-time">{formatTimestamp(entry.timestamp)}</span>
          </div>
          {#if expandedJob === i}
            <pre class="activity-detail">{entry.output || '(no output)'}</pre>
          {/if}
        </button>
      {/each}
    {/if}
  </div>
{/if}

<style>
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

  .job-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }

  .job-info {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1;
    min-width: 0;
  }

  .job-name {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    font-weight: 600;
  }

  .job-schedule {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    font-family: var(--font-mono);
  }

  .job-status {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 4px;
    background: rgba(255, 100, 100, 0.1);
    color: rgba(255, 100, 100, 0.6);
  }

  .job-status.installed {
    background: rgba(92, 224, 214, 0.1);
    color: rgba(92, 224, 214, 0.6);
  }

  .job-actions {
    display: flex;
    gap: 4px;
    flex-shrink: 0;
  }

  .job-btn {
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

  .job-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.8);
  }

  .job-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .job-desc {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    padding: 0 0 6px 0;
  }

  .job-log {
    margin: 4px 0 10px;
    padding: 8px;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 4px;
    color: rgba(255, 255, 255, 0.5);
    font-size: 11px;
    font-family: var(--font-mono);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 300px;
    overflow-y: auto;
  }

  .job-duration {
    color: rgba(255, 255, 255, 0.25);
    font-size: 10px;
    font-family: var(--font-mono);
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
    min-width: 36px;
    text-align: center;
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

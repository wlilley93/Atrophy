<script lang="ts">
  import { api } from '../../api';

  interface JobDef {
    schedule?: string;
    interval_seconds?: number;
    script: string;
    description?: string;
  }

  interface ScheduleEntry {
    name: string;
    agent: string;
    definition: { cron?: string; script: string; description?: string; type?: string; interval_seconds?: number };
    nextRun: string | null;
    lastRun: string | null;
    running: boolean;
    disabled: boolean;
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

  interface Props {
    agentName: string;
    jobs: Record<string, JobDef>;
    schedule: ScheduleEntry[];
    onSave: (jobs: Record<string, JobDef>) => void;
  }

  let { agentName, jobs, schedule, onSave }: Props = $props();

  // Local editable copy of jobs
  let localJobs = $state<Record<string, JobDef>>({ ...jobs });

  // Editing state: which job name is being edited inline (or 'new' for new job form)
  let editingJob = $state<string | null>(null);

  // Edit form buffer
  let editName = $state('');
  let editSchedule = $state('');
  let editScript = $state('');
  let editDescription = $state('');

  // New job form
  let addingNew = $state(false);
  let newName = $state('');
  let newSchedule = $state('');
  let newScript = $state('');
  let newDescription = $state('');

  // Running state per job
  let runningJob = $state<string | null>(null);

  // Delete confirmation
  let deletingJob = $state<string | null>(null);

  // Status messages per job
  let jobStatus = $state<Record<string, string>>({});

  // History entries for this agent (last 5)
  let agentHistory = $derived(
    ((schedule as unknown) as HistoryEntry[])
      .filter((e) => 'job' in e && e.agent === agentName)
      .slice(0, 5) as HistoryEntry[]
  );

  // Schedule entries for this agent
  let agentSchedule = $derived(
    schedule.filter((e) => e.agent === agentName)
  );

  $effect(() => {
    localJobs = { ...jobs };
  });

  function scheduleDisplay(job: JobDef): string {
    if (job.schedule) return job.schedule;
    if (job.interval_seconds) {
      const s = job.interval_seconds;
      if (s >= 3600) return `every ${(s / 3600).toFixed(s % 3600 ? 1 : 0)}h`;
      if (s >= 60) return `every ${Math.round(s / 60)}m`;
      return `every ${s}s`;
    }
    return '-';
  }

  function statusFor(jobName: string): ScheduleEntry | undefined {
    return agentSchedule.find((e) => e.name === jobName);
  }

  function formatTs(ts: string | null): string {
    if (!ts) return 'never';
    try {
      const d = new Date(ts);
      return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} ${d.toLocaleTimeString('en-US', { hour12: false })}`;
    } catch {
      return ts.slice(0, 19);
    }
  }

  function setStatus(jobName: string, msg: string, delayMs = 3000) {
    jobStatus = { ...jobStatus, [jobName]: msg };
    setTimeout(() => {
      jobStatus = { ...jobStatus, [jobName]: '' };
    }, delayMs);
  }

  async function runNow(jobName: string) {
    if (!api || runningJob) return;
    runningJob = jobName;
    try {
      await api.runJobNow(agentName, jobName);
      setStatus(jobName, 'Triggered');
    } catch {
      setStatus(jobName, 'Error');
    }
    runningJob = null;
  }

  function startEdit(jobName: string) {
    const job = localJobs[jobName];
    editName = jobName;
    editSchedule = job.schedule ?? (job.interval_seconds ? `${job.interval_seconds}s` : '');
    editScript = job.script;
    editDescription = job.description ?? '';
    editingJob = jobName;
    addingNew = false;
  }

  function cancelEdit() {
    editingJob = null;
  }

  function saveEdit() {
    if (!editName.trim() || !editScript.trim()) return;
    const updated = { ...localJobs };
    // If name changed, remove old key
    if (editName !== editingJob && editingJob) {
      delete updated[editingJob];
    }
    updated[editName] = {
      schedule: editSchedule || undefined,
      script: editScript,
      description: editDescription || undefined,
    };
    localJobs = updated;
    editingJob = null;
    onSave(localJobs);
  }

  function startDelete(jobName: string) {
    deletingJob = jobName;
  }

  function cancelDelete() {
    deletingJob = null;
  }

  function confirmDelete() {
    if (!deletingJob) return;
    const updated = { ...localJobs };
    delete updated[deletingJob];
    localJobs = updated;
    deletingJob = null;
    onSave(localJobs);
  }

  function startAddNew() {
    newName = '';
    newSchedule = '';
    newScript = '';
    newDescription = '';
    addingNew = true;
    editingJob = null;
  }

  function cancelAddNew() {
    addingNew = false;
  }

  function confirmAddNew() {
    if (!newName.trim() || !newScript.trim()) return;
    const updated = { ...localJobs };
    updated[newName] = {
      schedule: newSchedule || undefined,
      script: newScript,
      description: newDescription || undefined,
    };
    localJobs = updated;
    addingNew = false;
    onSave(localJobs);
  }
</script>

<div class="job-editor">
  {#if Object.keys(localJobs).length === 0 && !addingNew}
    <p class="empty-hint">No jobs configured for this agent.</p>
  {:else}
    {#each Object.entries(localJobs) as [jobName, jobDef]}
      {@const entry = statusFor(jobName)}
      {@const isEditing = editingJob === jobName}
      {@const isDeleting = deletingJob === jobName}

      <div class="job-card" class:editing={isEditing}>
        <!-- Job header row -->
        <div class="job-header">
          <div class="job-meta">
            <span class="job-name">{jobName}</span>
            <span class="job-schedule-badge">{scheduleDisplay(jobDef)}</span>
            {#if entry}
              <span class="status-badge" class:active={!entry.disabled && !entry.running} class:running={entry.running} class:disabled={entry.disabled}>
                {entry.running ? 'running' : entry.disabled ? 'disabled' : 'active'}
              </span>
            {/if}
          </div>
          {#if !isEditing && !isDeleting}
            <div class="job-actions">
              {#if jobStatus[jobName]}
                <span class="inline-status">{jobStatus[jobName]}</span>
              {/if}
              <button
                class="action-btn"
                disabled={runningJob !== null}
                onclick={() => runNow(jobName)}
              >
                {runningJob === jobName ? '...' : 'Run Now'}
              </button>
              <button class="action-btn" onclick={() => startEdit(jobName)}>Edit</button>
              <button class="action-btn delete-btn" onclick={() => startDelete(jobName)}>Delete</button>
            </div>
          {/if}
        </div>

        {#if jobDef.description && !isEditing}
          <p class="job-description">{jobDef.description}</p>
        {/if}

        <!-- Last/next run info -->
        {#if entry && !isEditing}
          <div class="job-timing">
            <span class="timing-item">Last: {formatTs(entry.lastRun)}</span>
            <span class="timing-sep">-</span>
            <span class="timing-item">Next: {formatTs(entry.nextRun)}</span>
          </div>
        {/if}

        <!-- Inline edit form -->
        {#if isEditing}
          <div class="edit-form">
            <div class="form-row">
              <label class="form-label">Name</label>
              <input class="field-input" type="text" bind:value={editName} />
            </div>
            <div class="form-row">
              <label class="form-label">Schedule (cron or interval)</label>
              <input class="field-input" type="text" bind:value={editSchedule} placeholder="0 9 * * * or 3600s" />
            </div>
            <div class="form-row">
              <label class="form-label">Script path</label>
              <input class="field-input" type="text" bind:value={editScript} placeholder="scripts/agents/companion/task.py" />
            </div>
            <div class="form-row">
              <label class="form-label">Description</label>
              <input class="field-input" type="text" bind:value={editDescription} />
            </div>
            <div class="edit-actions">
              <button class="action-btn save-btn" onclick={saveEdit}>Save</button>
              <button class="action-btn" onclick={cancelEdit}>Cancel</button>
            </div>
          </div>
        {/if}

        <!-- Delete confirmation -->
        {#if isDeleting}
          <div class="delete-confirm">
            <span class="delete-confirm-text">Delete job "{jobName}"?</span>
            <button class="action-btn delete-btn" onclick={confirmDelete}>Confirm</button>
            <button class="action-btn" onclick={cancelDelete}>Cancel</button>
          </div>
        {/if}
      </div>
    {/each}
  {/if}

  <!-- Run history section (last 5) -->
  {#if agentHistory.length > 0}
    <div class="history-section">
      <div class="section-label">Recent Runs</div>
      {#each agentHistory as entry}
        <div class="history-row">
          <span class="history-status" class:ok={entry.exitCode === 0} class:fail={entry.exitCode !== 0}>
            {entry.exitCode === 0 ? 'OK' : 'FAIL'}
          </span>
          <span class="history-job">{entry.job}</span>
          <span class="history-duration">
            {entry.durationMs < 1000 ? entry.durationMs + 'ms' : (entry.durationMs / 1000).toFixed(1) + 's'}
          </span>
          <span class="history-time">{formatTs(entry.timestamp)}</span>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Add new job form -->
  {#if addingNew}
    <div class="add-form">
      <div class="section-label">New Job</div>
      <div class="form-row">
        <label class="form-label">Name</label>
        <input class="field-input" type="text" bind:value={newName} placeholder="morning_brief" />
      </div>
      <div class="form-row">
        <label class="form-label">Schedule (cron or interval)</label>
        <input class="field-input" type="text" bind:value={newSchedule} placeholder="0 9 * * * or 3600s" />
      </div>
      <div class="form-row">
        <label class="form-label">Script path</label>
        <input class="field-input" type="text" bind:value={newScript} placeholder="scripts/agents/companion/task.py" />
      </div>
      <div class="form-row">
        <label class="form-label">Description</label>
        <input class="field-input" type="text" bind:value={newDescription} />
      </div>
      <div class="edit-actions">
        <button class="action-btn save-btn" onclick={confirmAddNew}>Add Job</button>
        <button class="action-btn" onclick={cancelAddNew}>Cancel</button>
      </div>
    </div>
  {:else}
    <button class="add-job-btn" onclick={startAddNew}>+ Add Job</button>
  {/if}
</div>

<style>
  .job-editor {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .empty-hint {
    color: rgba(255, 255, 255, 0.25);
    font-size: 12px;
    text-align: center;
    padding: 20px 0 10px;
  }

  /* Job card */
  .job-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 6px;
    padding: 8px 10px;
  }

  .job-card.editing {
    border-color: rgba(100, 140, 255, 0.25);
    background: rgba(100, 140, 255, 0.04);
  }

  .job-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    min-height: 24px;
  }

  .job-meta {
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
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .job-schedule-badge {
    color: rgba(255, 255, 255, 0.3);
    font-size: 10px;
    font-family: var(--font-mono);
    white-space: nowrap;
  }

  .status-badge {
    font-size: 9px;
    padding: 1px 6px;
    border-radius: 4px;
    background: rgba(255, 100, 100, 0.1);
    color: rgba(255, 100, 100, 0.6);
    white-space: nowrap;
  }

  .status-badge.active {
    background: rgba(92, 224, 214, 0.1);
    color: rgba(92, 224, 214, 0.6);
  }

  .status-badge.running {
    background: rgba(100, 140, 255, 0.1);
    color: rgba(100, 140, 255, 0.7);
  }

  .status-badge.disabled {
    background: rgba(255, 200, 80, 0.1);
    color: rgba(255, 200, 80, 0.5);
  }

  .job-actions {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }

  .inline-status {
    color: rgba(92, 224, 214, 0.7);
    font-size: 10px;
    padding-right: 4px;
  }

  .action-btn {
    padding: 3px 9px;
    font-size: 11px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.5);
    border-radius: 4px;
    cursor: pointer;
    font-family: var(--font-sans);
    transition: background 0.15s, color 0.15s;
    white-space: nowrap;
  }

  .action-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.8);
  }

  .action-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .action-btn.delete-btn {
    color: rgba(255, 100, 80, 0.5);
    border-color: rgba(255, 100, 80, 0.15);
  }

  .action-btn.delete-btn:hover {
    background: rgba(255, 100, 80, 0.08);
    color: rgba(255, 100, 80, 0.8);
  }

  .action-btn.save-btn {
    color: rgba(100, 140, 255, 0.8);
    border-color: rgba(100, 140, 255, 0.2);
    background: rgba(100, 140, 255, 0.07);
  }

  .action-btn.save-btn:hover {
    background: rgba(100, 140, 255, 0.15);
    color: rgba(100, 140, 255, 1);
  }

  .job-description {
    color: rgba(255, 255, 255, 0.3);
    font-size: 11px;
    margin: 4px 0 2px;
  }

  .job-timing {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 4px;
  }

  .timing-item {
    color: rgba(255, 255, 255, 0.2);
    font-size: 10px;
    font-family: var(--font-mono);
  }

  .timing-sep {
    color: rgba(255, 255, 255, 0.1);
    font-size: 10px;
  }

  /* Edit / add form */
  .edit-form,
  .add-form {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }

  .section-label {
    color: rgba(255, 255, 255, 0.4);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 2px;
  }

  .form-row {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .form-label {
    color: rgba(255, 255, 255, 0.4);
    font-size: 10px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }

  .field-input {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 5px;
    color: rgba(255, 255, 255, 0.75);
    font-family: var(--font-sans);
    font-size: 12px;
    padding: 5px 8px;
    outline: none;
    transition: border-color 0.15s;
    width: 100%;
    box-sizing: border-box;
  }

  .field-input:focus {
    border-color: rgba(100, 140, 255, 0.4);
  }

  .edit-actions {
    display: flex;
    gap: 6px;
    justify-content: flex-end;
    margin-top: 2px;
  }

  /* Delete confirm */
  .delete-confirm {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid rgba(255, 100, 80, 0.12);
  }

  .delete-confirm-text {
    color: rgba(255, 100, 80, 0.7);
    font-size: 11px;
    flex: 1;
  }

  /* History section */
  .history-section {
    margin-top: 4px;
    padding-top: 10px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .history-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
  }

  .history-status {
    font-size: 9px;
    font-weight: bold;
    padding: 1px 5px;
    border-radius: 3px;
    min-width: 32px;
    text-align: center;
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.3);
  }

  .history-status.ok {
    color: rgba(92, 224, 214, 0.7);
  }

  .history-status.fail {
    color: rgba(255, 100, 80, 0.7);
  }

  .history-job {
    color: rgba(255, 255, 255, 0.6);
    font-size: 11px;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .history-duration {
    color: rgba(255, 255, 255, 0.2);
    font-size: 10px;
    font-family: var(--font-mono);
    flex-shrink: 0;
  }

  .history-time {
    color: rgba(255, 255, 255, 0.2);
    font-size: 10px;
    font-family: var(--font-mono);
    flex-shrink: 0;
  }

  /* Add job button */
  .add-job-btn {
    background: none;
    border: 1px dashed rgba(100, 140, 255, 0.25);
    border-radius: 5px;
    color: rgba(100, 140, 255, 0.5);
    cursor: pointer;
    font-family: var(--font-sans);
    font-size: 12px;
    padding: 8px;
    text-align: center;
    width: 100%;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }

  .add-job-btn:hover {
    background: rgba(100, 140, 255, 0.05);
    border-color: rgba(100, 140, 255, 0.45);
    color: rgba(100, 140, 255, 0.85);
  }
</style>

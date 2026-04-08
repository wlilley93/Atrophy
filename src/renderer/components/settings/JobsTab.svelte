<script lang="ts">
  import { api } from '../../api';

  // -----------------------------------------------------------------------
  // Types
  // -----------------------------------------------------------------------

  interface ScheduleEntry {
    name: string;
    agent: string;
    definition: {
      cron?: string;
      script: string;
      description?: string;
      type?: string;
      interval_seconds?: number;
      timeout_seconds?: number;
      args?: string[];
      route_output_to?: string;
    };
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

  interface TimeSlot {
    day: number;   // 0 = Monday, 6 = Sunday
    hour: number;  // 0-23
    minute: number; // 0-59
  }

  interface CalendarBlock {
    job: ScheduleEntry;
    slot: TimeSlot;
    durationMinutes: number;
    colour: string;
  }

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  let jobsList = $state<ScheduleEntry[]>([]);
  let jobHistory = $state<HistoryEntry[]>([]);
  let jobsLoading = $state(false);
  let runningJob = $state<string | null>(null);

  // View mode
  let viewMode = $state<'week' | 'list'>('week');
  let weekOffset = $state(0);
  let agentFilter = $state('all');

  // Modal state
  let modalOpen = $state(false);
  let modalMode = $state<'add' | 'edit'>('add');
  let modalAgent = $state('');
  let modalJobName = $state('');
  let modalScript = $state('');
  let modalCron = $state('');
  let modalDescription = $state('');
  let modalOriginalAgent = $state('');
  let modalOriginalJobName = $state('');

  // Delete confirm
  let deleteConfirmJob = $state<{ agent: string; name: string } | null>(null);

  // History expansion
  let expandedHistory = $state<number | null>(null);

  // Collapsed agents for list view
  let collapsedAgents = $state<Set<string>>(new Set());

  // Tooltip
  let tooltipJob = $state<CalendarBlock | null>(null);
  let tooltipX = $state(0);
  let tooltipY = $state(0);

  // -----------------------------------------------------------------------
  // Derived
  // -----------------------------------------------------------------------

  const agents: string[] = $derived.by(() => {
    const set = new Set<string>();
    for (const j of jobsList) set.add(j.agent);
    return Array.from(set).sort();
  });

  const filteredJobs = $derived(
    agentFilter === 'all' ? jobsList : jobsList.filter((j) => j.agent === agentFilter)
  );

  const totalJobs = $derived(jobsList.length);
  const activeJobs = $derived(jobsList.filter((j) => !j.disabled).length);
  const runningJobs = $derived(jobsList.filter((j) => j.running).length);

  // Week dates
  const weekDates = $derived.by(() => {
    const now = new Date();
    const dayOfWeek = now.getDay(); // 0=Sun, 1=Mon, ..., 6=Sat
    const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
    const monday = new Date(now);
    monday.setDate(now.getDate() + mondayOffset + weekOffset * 7);
    monday.setHours(0, 0, 0, 0);
    const days: Date[] = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(monday);
      d.setDate(monday.getDate() + i);
      days.push(d);
    }
    return days;
  });

  const weekLabel = $derived.by(() => {
    const mon = weekDates[0];
    const sun = weekDates[6];
    const fmt = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    return `${fmt(mon)} - ${fmt(sun)}`;
  });

  const isThisWeek = $derived(weekOffset === 0);

  // Current time tracking for the red line
  let nowMinutes = $state(new Date().getHours() * 60 + new Date().getMinutes());
  let nowDay = $state(() => {
    const d = new Date().getDay();
    return d === 0 ? 6 : d - 1; // Convert Sun=0 to Mon=0..Sun=6
  });

  $effect(() => {
    const interval = setInterval(() => {
      const now = new Date();
      nowMinutes = now.getHours() * 60 + now.getMinutes();
      const d = now.getDay();
      nowDay = d === 0 ? 6 : d - 1;
    }, 30000); // update every 30s
    return () => clearInterval(interval);
  });

  // Calendar blocks
  const calendarBlocks: CalendarBlock[] = $derived.by(() => {
    const blocks: CalendarBlock[] = [];
    for (const job of filteredJobs) {
      const slots = jobToSlots(job);
      const durationMin = job.definition.timeout_seconds
        ? Math.max(1, Math.round(job.definition.timeout_seconds / 60))
        : 30;
      const colour = agentColour(job.agent);
      for (const slot of slots) {
        blocks.push({ job, slot, durationMinutes: durationMin, colour });
      }
    }
    return blocks;
  });

  // Group jobs by agent for list view
  const grouped = $derived.by(() => {
    const map = new Map<string, ScheduleEntry[]>();
    for (const job of filteredJobs) {
      const list = map.get(job.agent) || [];
      list.push(job);
      map.set(job.agent, list);
    }
    return Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([agent, jobs]) => ({ agent, jobs }));
  });

  // -----------------------------------------------------------------------
  // Hour labels
  // -----------------------------------------------------------------------

  const HOURS = Array.from({ length: 24 }, (_, i) => i);
  const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const HOUR_HEIGHT = 48; // px per hour row
  const GRID_TOP = 36;    // header row height

  // -----------------------------------------------------------------------
  // Colour helper - deterministic hash to colour
  // -----------------------------------------------------------------------

  function agentColour(name: string): string {
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
      hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0;
    }
    const hue = ((hash % 360) + 360) % 360;
    return `hsl(${hue}, 55%, 55%)`;
  }

  function agentColourDim(name: string): string {
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
      hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0;
    }
    const hue = ((hash % 360) + 360) % 360;
    return `hsl(${hue}, 30%, 25%)`;
  }

  // -----------------------------------------------------------------------
  // Cron parsing
  // -----------------------------------------------------------------------

  function parseCronField(field: string, max: number): number[] {
    const results: number[] = [];
    for (const part of field.split(',')) {
      const stepMatch = part.match(/^(\*|\d+(?:-\d+)?)\/(\d+)$/);
      if (stepMatch) {
        const step = parseInt(stepMatch[2], 10);
        let start = 0;
        let end = max - 1;
        if (stepMatch[1] !== '*') {
          const rangeMatch = stepMatch[1].match(/^(\d+)(?:-(\d+))?$/);
          if (rangeMatch) {
            start = parseInt(rangeMatch[1], 10);
            if (rangeMatch[2] !== undefined) end = parseInt(rangeMatch[2], 10);
          }
        }
        for (let i = start; i <= end; i += step) results.push(i);
        continue;
      }
      if (part === '*') {
        for (let i = 0; i < max; i++) results.push(i);
        continue;
      }
      const rangeMatch = part.match(/^(\d+)-(\d+)$/);
      if (rangeMatch) {
        const lo = parseInt(rangeMatch[1], 10);
        const hi = parseInt(rangeMatch[2], 10);
        for (let i = lo; i <= hi; i++) results.push(i);
        continue;
      }
      const num = parseInt(part, 10);
      if (!isNaN(num)) results.push(num);
    }
    return results;
  }

  function cronToSlots(cron: string): TimeSlot[] {
    const parts = cron.trim().split(/\s+/);
    if (parts.length < 5) return [];

    const [minuteStr, hourStr, _dom, _month, dowStr] = parts;

    const minutes = parseCronField(minuteStr, 60);
    const hours = parseCronField(hourStr, 24);

    // Parse day-of-week: cron uses 0=Sun, we use 0=Mon
    let days: number[];
    if (dowStr === '*') {
      days = [0, 1, 2, 3, 4, 5, 6];
    } else {
      const cronDays = parseCronField(dowStr, 8); // 0-7, where 0 and 7 = Sunday
      const daySet = new Set<number>();
      for (const d of cronDays) {
        // Convert from cron DOW (0=Sun) to calendar DOW (0=Mon)
        if (d === 0 || d === 7) daySet.add(6); // Sunday
        else daySet.add(d - 1); // Mon=0..Sat=5
      }
      days = Array.from(daySet).sort();
    }

    const slots: TimeSlot[] = [];

    // For high-frequency jobs (every N minutes across all hours), limit display
    if (minutes.length > 30 && hours.length === 24) {
      // Show one thin slot per hour per day at the first minute
      for (const day of days) {
        for (const hour of hours) {
          slots.push({ day, hour, minute: minutes[0] ?? 0 });
        }
      }
      return slots;
    }

    for (const day of days) {
      for (const hour of hours) {
        for (const minute of minutes) {
          slots.push({ day, hour, minute });
        }
      }
    }

    return slots;
  }

  function jobToSlots(job: ScheduleEntry): TimeSlot[] {
    if (job.definition.cron) {
      return cronToSlots(job.definition.cron);
    }
    if (job.definition.interval_seconds) {
      // Compute occurrences from midnight across all 7 days
      const interval = job.definition.interval_seconds;
      const slots: TimeSlot[] = [];
      for (let day = 0; day < 7; day++) {
        let elapsed = 0;
        while (elapsed < 86400) {
          const hour = Math.floor(elapsed / 3600);
          const minute = Math.floor((elapsed % 3600) / 60);
          slots.push({ day, hour, minute });
          elapsed += interval;
        }
      }
      return slots;
    }
    return [];
  }

  // -----------------------------------------------------------------------
  // Cron to English
  // -----------------------------------------------------------------------

  function cronToEnglish(cron: string): string {
    const parts = cron.trim().split(/\s+/);
    if (parts.length < 5) return cron;

    const [minute, hour, day, _month, dow] = parts;

    if (minute === '*' && hour === '*' && day === '*' && dow === '*') return 'every minute';

    const minInterval = minute.match(/^\*\/(\d+)$/);
    if (minInterval && hour === '*' && day === '*' && dow === '*') return `every ${minInterval[1]}m`;

    const hourInterval = hour.match(/^\*\/(\d+)$/);
    if (minute === '0' && hourInterval && day === '*' && dow === '*') return `every ${hourInterval[1]}h`;

    const m = parseInt(minute, 10);
    const h = parseInt(hour, 10);
    if (!isNaN(m) && !isNaN(h)) {
      const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
      if (day === '*' && dow === '*') return `daily at ${time}`;
      const dayNames: Record<string, string> = {
        '0': 'Sundays', '1': 'Mondays', '2': 'Tuesdays', '3': 'Wednesdays',
        '4': 'Thursdays', '5': 'Fridays', '6': 'Saturdays', '7': 'Sundays',
      };
      if (day === '*') {
        if (dow === '1-5') return `weekdays at ${time}`;
        if (dow === '0,6' || dow === '6,0') return `weekends at ${time}`;
        if (dayNames[dow]) return `${dayNames[dow]} at ${time}`;
        const dayList = dow.split(',');
        if (dayList.every((d) => dayNames[d])) {
          return `${dayList.map((d) => dayNames[d]).join(', ')} at ${time}`;
        }
        return `${dow} at ${time}`;
      }
      return `at ${time}`;
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

  // -----------------------------------------------------------------------
  // Formatting helpers
  // -----------------------------------------------------------------------

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
    } catch { return '-'; }
  }

  function formatTimestamp(ts: string): string {
    try {
      const d = new Date(ts);
      return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}  ${d.toLocaleTimeString('en-US', { hour12: false })}`;
    } catch { return ts?.slice(0, 19) || ''; }
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

  // -----------------------------------------------------------------------
  // API
  // -----------------------------------------------------------------------

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

  async function handleResumeAll() {
    if (!api) return;
    try {
      await (api as any).cronResetAll?.()
        ?? (window as any).atrophy?.cronResetAll?.();
    } catch { /* ignore */ }
    await load();
  }

  async function saveJob() {
    if (!api || !modalAgent || !modalJobName.trim() || !modalScript.trim()) return;
    try {
      if (modalMode === 'edit') {
        await api.editJob(modalOriginalAgent, modalOriginalJobName, {
          cron: modalCron || undefined,
          script: modalScript,
          description: modalDescription || undefined,
        });
      } else {
        await api.addJob(modalAgent, modalJobName, {
          schedule: modalCron,
          script: modalScript,
          description: modalDescription || undefined,
        });
      }
      modalOpen = false;
      await load();
    } catch (err) {
      console.error('Failed to save job:', err);
    }
  }

  async function deleteJob() {
    if (!api || !deleteConfirmJob) return;
    try {
      await api.deleteJob(deleteConfirmJob.agent, deleteConfirmJob.name);
      deleteConfirmJob = null;
      modalOpen = false;
      await load();
    } catch { /* ignore */ }
  }

  // -----------------------------------------------------------------------
  // Calendar interactions
  // -----------------------------------------------------------------------

  function handleSlotClick(day: number, hour: number) {
    // Open add modal pre-filled with the clicked day/hour
    modalMode = 'add';
    modalAgent = agentFilter !== 'all' ? agentFilter : (agents[0] || '');
    modalJobName = '';
    modalScript = '';
    const dowMap = [1, 2, 3, 4, 5, 6, 0]; // Mon=1, ..., Sun=0 in cron
    modalCron = `0 ${hour} * * ${dowMap[day]}`;
    modalDescription = '';
    modalOriginalAgent = '';
    modalOriginalJobName = '';
    modalOpen = true;
  }

  function handleBlockClick(block: CalendarBlock, event: MouseEvent) {
    event.stopPropagation();
    modalMode = 'edit';
    modalAgent = block.job.agent;
    modalJobName = block.job.name;
    modalScript = block.job.definition.script;
    modalCron = block.job.definition.cron || '';
    modalDescription = block.job.definition.description || '';
    modalOriginalAgent = block.job.agent;
    modalOriginalJobName = block.job.name;
    modalOpen = true;
  }

  function handleBlockHover(block: CalendarBlock, event: MouseEvent) {
    tooltipJob = block;
    tooltipX = event.clientX;
    tooltipY = event.clientY;
  }

  function handleBlockLeave() {
    tooltipJob = null;
  }

  function closeModal() {
    modalOpen = false;
    deleteConfirmJob = null;
  }

  // -----------------------------------------------------------------------
  // List view helpers
  // -----------------------------------------------------------------------

  function toggleAgent(agent: string) {
    const next = new Set(collapsedAgents);
    if (next.has(agent)) next.delete(agent);
    else next.add(agent);
    collapsedAgents = next;
  }
</script>

{#if jobsLoading}
  <p class="placeholder">Loading...</p>
{:else}
  <!-- Toolbar -->
  <div class="toolbar">
    <div class="toolbar-left">
      <div class="toolbar-stats">
        <span class="stat">{totalJobs} jobs</span>
        <span class="stat-sep"></span>
        <span class="stat">{activeJobs} active</span>
        {#if runningJobs > 0}
          <span class="stat-sep"></span>
          <span class="stat running">{runningJobs} running</span>
        {/if}
      </div>
    </div>
    <div class="toolbar-right">
      <!-- Agent filter -->
      <select class="filter-select" bind:value={agentFilter}>
        <option value="all">All agents</option>
        {#each agents as a}
          <option value={a}>{a}</option>
        {/each}
      </select>

      <!-- View toggle -->
      <div class="view-toggle">
        <button
          class="toggle-btn"
          class:active={viewMode === 'week'}
          onclick={() => viewMode = 'week'}
        >Week</button>
        <button
          class="toggle-btn"
          class:active={viewMode === 'list'}
          onclick={() => viewMode = 'list'}
        >List</button>
      </div>

      <!-- Week nav (only in week view) -->
      {#if viewMode === 'week'}
        <div class="week-nav">
          <button class="nav-btn" onclick={() => weekOffset--}>&lt;</button>
          <button
            class="nav-label"
            class:current={isThisWeek}
            onclick={() => weekOffset = 0}
          >{isThisWeek ? 'This Week' : weekLabel}</button>
          <button class="nav-btn" onclick={() => weekOffset++}>&gt;</button>
        </div>
      {/if}

      <button class="toolbar-btn primary" onclick={handleResumeAll}>Resume All</button>
    </div>
  </div>

  <!-- Calendar view -->
  {#if viewMode === 'week'}
    <div class="calendar-container">
      <div class="calendar-scroll">
        <div class="calendar-grid" style="height: {HOURS.length * HOUR_HEIGHT + GRID_TOP}px">
          <!-- Day headers -->
          <div class="day-headers" style="height: {GRID_TOP}px">
            <div class="hour-gutter" style="width: 44px; height: {GRID_TOP}px"></div>
            {#each DAY_NAMES as dayName, i}
              <div class="day-header">
                <span class="day-name">{dayName}</span>
                <span class="day-date">{weekDates[i].getDate()}</span>
              </div>
            {/each}
          </div>

          <!-- Grid body -->
          <div class="grid-body" style="top: {GRID_TOP}px">
            <!-- Hour labels + gridlines -->
            {#each HOURS as hour}
              <div class="hour-row" style="top: {hour * HOUR_HEIGHT}px; height: {HOUR_HEIGHT}px">
                <div class="hour-label">{hour % 2 === 0 ? String(hour).padStart(2, '0') : ''}</div>
                <div class="hour-line"></div>
              </div>
            {/each}

            <!-- Clickable day columns -->
            {#each DAY_NAMES as _, dayIdx}
              <div
                class="day-column"
                style="left: calc(44px + {dayIdx} * (100% - 44px) / 7); width: calc((100% - 44px) / 7)"
              >
                {#each HOURS as hour}
                  <button
                    class="slot-cell"
                    style="top: {hour * HOUR_HEIGHT}px; height: {HOUR_HEIGHT}px"
                    onclick={() => handleSlotClick(dayIdx, hour)}
                    aria-label="Add job at {DAY_NAMES[dayIdx]} {String(hour).padStart(2, '0')}:00"
                  ></button>
                {/each}
              </div>
            {/each}

            <!-- Job blocks -->
            {#each calendarBlocks as block}
              {@const topPx = block.slot.hour * HOUR_HEIGHT + (block.slot.minute / 60) * HOUR_HEIGHT}
              {@const heightPx = Math.max(20, (block.durationMinutes / 60) * HOUR_HEIGHT)}
              <button
                class="job-block"
                class:disabled={block.job.disabled}
                class:is-running={block.job.running}
                style="
                  top: {topPx}px;
                  height: {Math.min(heightPx, (24 * HOUR_HEIGHT) - topPx)}px;
                  left: calc(44px + {block.slot.day} * (100% - 44px) / 7 + 2px);
                  width: calc((100% - 44px) / 7 - 4px);
                  --block-colour: {block.colour};
                  --block-colour-dim: {agentColourDim(block.job.agent)};
                "
                onclick={(e) => handleBlockClick(block, e)}
                onmouseenter={(e) => handleBlockHover(block, e)}
                onmouseleave={handleBlockLeave}
              >
                <span class="block-name">{block.job.name}</span>
                <span class="block-agent">{block.job.agent}</span>
              </button>
            {/each}

            <!-- Current time line -->
            {#if isThisWeek}
              {@const currentDay = typeof nowDay === 'function' ? nowDay() : nowDay}
              <div
                class="now-line"
                style="top: {(nowMinutes / 60) * HOUR_HEIGHT}px"
              >
                <div class="now-dot" style="left: calc(44px + {currentDay} * (100% - 44px) / 7 - 4px)"></div>
              </div>
            {/if}
          </div>
        </div>
      </div>
    </div>

  <!-- List view -->
  {:else}
    <div class="section">
      <div class="section-header">Scheduled Jobs</div>
      <div class="section-line"></div>

      {#if filteredJobs.length === 0}
        <p class="placeholder">No jobs configured</p>
      {:else}
        {#each grouped as group}
          <div class="agent-group">
            <button class="agent-header" onclick={() => toggleAgent(group.agent)}>
              <span class="agent-chevron" class:collapsed={collapsedAgents.has(group.agent)}>&#9662;</span>
              <span class="agent-name-text">{group.agent}</span>
              <span class="agent-colour-dot" style="background: {agentColour(group.agent)}"></span>
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
                        <span class="job-name" title={job.definition.description || ''}>{job.name}</span>
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
                        >{runningJob === job.name ? '...' : 'Run'}</button>
                        <button
                          class="run-btn"
                          onclick={() => {
                            modalMode = 'edit';
                            modalAgent = job.agent;
                            modalJobName = job.name;
                            modalScript = job.definition.script;
                            modalCron = job.definition.cron || '';
                            modalDescription = job.definition.description || '';
                            modalOriginalAgent = job.agent;
                            modalOriginalJobName = job.name;
                            modalOpen = true;
                          }}
                        >Edit</button>
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
  {/if}

  <!-- Run History -->
  <div class="section history-section">
    <div class="section-header">Run History</div>
    <div class="section-line"></div>

    {#if jobHistory.length === 0}
      <p class="placeholder">No runs yet this session</p>
    {:else}
      <div class="history-scroll">
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
            {#each jobHistory.slice(0, 20) as entry, i}
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
      </div>
    {/if}
  </div>
{/if}

<!-- Tooltip -->
{#if tooltipJob}
  <div
    class="tooltip"
    style="left: {tooltipX + 12}px; top: {tooltipY - 8}px"
  >
    <div class="tooltip-name">{tooltipJob.job.name}</div>
    <div class="tooltip-agent">{tooltipJob.job.agent}</div>
    {#if tooltipJob.job.definition.description}
      <div class="tooltip-desc">{tooltipJob.job.definition.description}</div>
    {/if}
    <div class="tooltip-schedule">{formatSchedule(tooltipJob.job)}</div>
    {#if tooltipJob.job.nextRun}
      <div class="tooltip-next">Next: {formatRelativeTime(tooltipJob.job.nextRun)}</div>
    {/if}
    <div class="tooltip-status">{statusLabel(tooltipJob.job)}</div>
  </div>
{/if}

<!-- Modal -->
{#if modalOpen}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-overlay" onclick={closeModal} onkeydown={(e) => e.key === 'Escape' && closeModal()}>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="modal" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
      <div class="modal-header">
        <h3 class="modal-title">{modalMode === 'edit' ? 'Edit Job' : 'Add Job'}</h3>
        <button class="modal-close" onclick={closeModal}>&times;</button>
      </div>

      <div class="modal-body">
        <div class="form-row">
          <label class="form-label">Agent</label>
          {#if modalMode === 'edit'}
            <div class="form-value">{modalAgent}</div>
          {:else}
            <select class="field-input" bind:value={modalAgent}>
              {#each agents as a}
                <option value={a}>{a}</option>
              {/each}
            </select>
          {/if}
        </div>

        <div class="form-row">
          <label class="form-label">Job Name</label>
          {#if modalMode === 'edit'}
            <div class="form-value">{modalJobName}</div>
          {:else}
            <input class="field-input" type="text" bind:value={modalJobName} placeholder="morning_brief" />
          {/if}
        </div>

        <div class="form-row">
          <label class="form-label">Script Path</label>
          <input class="field-input" type="text" bind:value={modalScript} placeholder="scripts/agents/xan/task.py" />
        </div>

        <div class="form-row">
          <label class="form-label">Cron Expression</label>
          <input class="field-input mono" type="text" bind:value={modalCron} placeholder="0 9 * * *" />
          {#if modalCron}
            <div class="cron-preview">{cronToEnglish(modalCron)}</div>
          {/if}
        </div>

        <div class="form-row">
          <label class="form-label">Description</label>
          <input class="field-input" type="text" bind:value={modalDescription} placeholder="Optional description" />
        </div>
      </div>

      <div class="modal-footer">
        {#if modalMode === 'edit'}
          <button
            class="action-btn run-now-btn"
            onclick={() => { triggerJob(modalAgent, modalJobName); closeModal(); }}
          >Run Now</button>
          {#if deleteConfirmJob}
            <span class="delete-confirm-text">Delete this job?</span>
            <button class="action-btn delete-btn" onclick={deleteJob}>Confirm</button>
            <button class="action-btn" onclick={() => deleteConfirmJob = null}>Cancel</button>
          {:else}
            <button
              class="action-btn delete-btn"
              onclick={() => deleteConfirmJob = { agent: modalAgent, name: modalJobName }}
            >Delete</button>
          {/if}
        {/if}
        <div class="modal-spacer"></div>
        <button class="action-btn" onclick={closeModal}>Cancel</button>
        <button class="action-btn save-btn" onclick={saveJob}>
          {modalMode === 'edit' ? 'Save' : 'Add Job'}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  /* ------------------------------------------------------------------ */
  /* Toolbar                                                             */
  /* ------------------------------------------------------------------ */

  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 0 12px 0;
    gap: 12px;
    flex-wrap: wrap;
  }

  .toolbar-left {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .toolbar-right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
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

  .filter-select {
    padding: 4px 8px;
    font-size: 11px;
    font-family: var(--font-sans);
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.6);
    border-radius: 6px;
    cursor: pointer;
    outline: none;
    -webkit-appearance: none;
    appearance: none;
    min-width: 100px;
  }

  .filter-select option {
    background: #1a1a1e;
    color: rgba(255, 255, 255, 0.8);
  }

  .view-toggle {
    display: flex;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    overflow: hidden;
  }

  .toggle-btn {
    padding: 4px 12px;
    font-size: 11px;
    font-family: var(--font-sans);
    border: none;
    background: rgba(255, 255, 255, 0.02);
    color: rgba(255, 255, 255, 0.4);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }

  .toggle-btn:first-child {
    border-right: 1px solid rgba(255, 255, 255, 0.1);
  }

  .toggle-btn.active {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.85);
  }

  .toggle-btn:hover:not(.active) {
    background: rgba(255, 255, 255, 0.05);
    color: rgba(255, 255, 255, 0.6);
  }

  .week-nav {
    display: flex;
    align-items: center;
    gap: 2px;
  }

  .nav-btn {
    padding: 4px 8px;
    font-size: 11px;
    font-family: var(--font-mono);
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.03);
    color: rgba(255, 255, 255, 0.4);
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
    line-height: 1;
  }

  .nav-btn:hover {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.8);
  }

  .nav-label {
    padding: 4px 10px;
    font-size: 11px;
    font-family: var(--font-sans);
    font-weight: 600;
    border: 1px solid rgba(255, 255, 255, 0.08);
    background: rgba(255, 255, 255, 0.02);
    color: rgba(255, 255, 255, 0.5);
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
    white-space: nowrap;
  }

  .nav-label.current {
    color: rgba(92, 224, 214, 0.7);
    border-color: rgba(92, 224, 214, 0.15);
    background: rgba(92, 224, 214, 0.04);
  }

  .nav-label:hover {
    background: rgba(255, 255, 255, 0.06);
    color: rgba(255, 255, 255, 0.8);
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

  /* ------------------------------------------------------------------ */
  /* Calendar                                                            */
  /* ------------------------------------------------------------------ */

  .calendar-container {
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.015);
    margin-bottom: 16px;
  }

  .calendar-scroll {
    overflow-y: auto;
    overflow-x: hidden;
    max-height: 520px;
  }

  .calendar-grid {
    position: relative;
    width: 100%;
    min-width: 0;
  }

  /* Day headers */
  .day-headers {
    display: flex;
    position: sticky;
    top: 0;
    z-index: 10;
    background: rgba(12, 12, 14, 0.95);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  }

  .day-header {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 4px 0;
    gap: 1px;
  }

  .day-name {
    font-size: 10px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.4);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .day-date {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.55);
    font-weight: 500;
    font-family: var(--font-mono);
  }

  /* Grid body */
  .grid-body {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
  }

  /* Hour rows */
  .hour-row {
    position: absolute;
    left: 0;
    right: 0;
    display: flex;
    align-items: flex-start;
  }

  .hour-label {
    width: 44px;
    flex-shrink: 0;
    text-align: right;
    padding-right: 8px;
    font-size: 10px;
    font-family: var(--font-mono);
    color: rgba(255, 255, 255, 0.2);
    line-height: 1;
    transform: translateY(-5px);
  }

  .hour-line {
    flex: 1;
    height: 1px;
    background: rgba(255, 255, 255, 0.04);
  }

  /* Day columns (clickable) */
  .day-column {
    position: absolute;
    top: 0;
    bottom: 0;
    border-left: 1px solid rgba(255, 255, 255, 0.03);
  }

  .slot-cell {
    position: absolute;
    left: 0;
    right: 0;
    background: transparent;
    border: none;
    cursor: pointer;
    transition: background 0.1s;
    padding: 0;
    display: block;
  }

  .slot-cell:hover {
    background: rgba(255, 255, 255, 0.025);
  }

  /* Job blocks */
  .job-block {
    position: absolute;
    z-index: 5;
    background: var(--block-colour-dim);
    border: 1px solid var(--block-colour);
    border-radius: 4px;
    padding: 2px 6px;
    cursor: pointer;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    gap: 0;
    transition: filter 0.12s, transform 0.1s;
    text-align: left;
  }

  .job-block:hover {
    filter: brightness(1.3);
    z-index: 8;
    transform: scale(1.02);
  }

  .job-block.disabled {
    opacity: 0.4;
    border-style: dashed;
  }

  .job-block.is-running {
    animation: pulse-block 1.5s ease-in-out infinite;
  }

  @keyframes pulse-block {
    0%, 100% { filter: brightness(1); }
    50% { filter: brightness(1.4); }
  }

  .block-name {
    font-size: 10px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.9);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.3;
  }

  .block-agent {
    font-size: 9px;
    color: rgba(255, 255, 255, 0.45);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.2;
  }

  /* Current time line */
  .now-line {
    position: absolute;
    left: 44px;
    right: 0;
    height: 2px;
    background: rgba(255, 60, 60, 0.6);
    z-index: 6;
    pointer-events: none;
  }

  .now-dot {
    position: absolute;
    top: -4px;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: rgba(255, 60, 60, 0.8);
  }

  /* ------------------------------------------------------------------ */
  /* Tooltip                                                             */
  /* ------------------------------------------------------------------ */

  .tooltip {
    position: fixed;
    z-index: 100;
    background: rgba(20, 20, 24, 0.96);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    padding: 8px 12px;
    pointer-events: none;
    max-width: 260px;
    backdrop-filter: blur(12px);
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
  }

  .tooltip-name {
    font-size: 12px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.9);
    margin-bottom: 2px;
  }

  .tooltip-agent {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.4);
    margin-bottom: 4px;
  }

  .tooltip-desc {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.5);
    margin-bottom: 4px;
    line-height: 1.4;
  }

  .tooltip-schedule {
    font-size: 10px;
    font-family: var(--font-mono);
    color: rgba(255, 255, 255, 0.35);
  }

  .tooltip-next {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.3);
    margin-top: 2px;
  }

  .tooltip-status {
    font-size: 9px;
    color: rgba(92, 224, 214, 0.6);
    text-transform: uppercase;
    letter-spacing: 0.4px;
    margin-top: 3px;
  }

  /* ------------------------------------------------------------------ */
  /* Modal                                                               */
  /* ------------------------------------------------------------------ */

  .modal-overlay {
    position: fixed;
    inset: 0;
    z-index: 200;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    backdrop-filter: blur(4px);
  }

  .modal {
    background: #1a1a1e;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    width: 420px;
    max-width: 90vw;
    box-shadow: 0 8px 40px rgba(0, 0, 0, 0.6);
    overflow: hidden;
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px 10px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .modal-title {
    font-size: 14px;
    font-weight: 700;
    color: rgba(255, 255, 255, 0.85);
    margin: 0;
  }

  .modal-close {
    background: none;
    border: none;
    color: rgba(255, 255, 255, 0.3);
    font-size: 20px;
    cursor: pointer;
    padding: 0 4px;
    line-height: 1;
    transition: color 0.12s;
  }

  .modal-close:hover {
    color: rgba(255, 255, 255, 0.7);
  }

  .modal-body {
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .form-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .form-label {
    color: rgba(255, 255, 255, 0.45);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .form-value {
    color: rgba(255, 255, 255, 0.7);
    font-size: 13px;
    padding: 5px 0;
  }

  .field-input {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    color: rgba(255, 255, 255, 0.8);
    font-family: var(--font-sans);
    font-size: 13px;
    padding: 7px 10px;
    outline: none;
    transition: border-color 0.15s;
    width: 100%;
    box-sizing: border-box;
  }

  .field-input:focus {
    border-color: rgba(100, 140, 255, 0.4);
  }

  .field-input.mono {
    font-family: var(--font-mono);
    letter-spacing: 0.5px;
  }

  select.field-input {
    -webkit-appearance: none;
    appearance: none;
    cursor: pointer;
  }

  select.field-input option {
    background: #1a1a1e;
    color: rgba(255, 255, 255, 0.8);
  }

  .cron-preview {
    font-size: 11px;
    color: rgba(92, 224, 214, 0.6);
    font-family: var(--font-sans);
    padding-top: 2px;
  }

  .modal-footer {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 16px 14px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }

  .modal-spacer {
    flex: 1;
  }

  .action-btn {
    padding: 5px 12px;
    font-size: 11px;
    font-family: var(--font-sans);
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.5);
    border-radius: 6px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
    white-space: nowrap;
  }

  .action-btn:hover {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.8);
  }

  .action-btn.save-btn {
    color: rgba(100, 140, 255, 0.85);
    border-color: rgba(100, 140, 255, 0.25);
    background: rgba(100, 140, 255, 0.08);
  }

  .action-btn.save-btn:hover {
    background: rgba(100, 140, 255, 0.16);
    color: rgba(100, 140, 255, 1);
  }

  .action-btn.delete-btn {
    color: rgba(255, 100, 80, 0.6);
    border-color: rgba(255, 100, 80, 0.2);
  }

  .action-btn.delete-btn:hover {
    background: rgba(255, 100, 80, 0.1);
    color: rgba(255, 100, 80, 0.9);
  }

  .action-btn.run-now-btn {
    color: rgba(92, 224, 214, 0.7);
    border-color: rgba(92, 224, 214, 0.2);
  }

  .action-btn.run-now-btn:hover {
    background: rgba(92, 224, 214, 0.08);
    color: rgba(92, 224, 214, 0.95);
  }

  .delete-confirm-text {
    color: rgba(255, 100, 80, 0.7);
    font-size: 11px;
  }

  /* ------------------------------------------------------------------ */
  /* List view (shared styles from old component)                        */
  /* ------------------------------------------------------------------ */

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

  .agent-name-text {
    color: rgba(255, 255, 255, 0.75);
    font-size: 13px;
    font-weight: 600;
  }

  .agent-colour-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .agent-badge {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.4);
    background: rgba(255, 255, 255, 0.06);
    padding: 1px 7px;
    border-radius: 8px;
    font-weight: 600;
  }

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

  .col-job { width: 28%; }
  .col-schedule { width: 22%; }
  .col-status { width: 14%; }
  .col-next { width: 16%; }
  .col-actions { width: 20%; text-align: right; }

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
    margin-left: 4px;
  }

  .run-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.8);
  }

  .run-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  /* ------------------------------------------------------------------ */
  /* History                                                             */
  /* ------------------------------------------------------------------ */

  .history-section {
    margin-top: 4px;
  }

  .history-scroll {
    max-height: 260px;
    overflow-y: auto;
  }

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

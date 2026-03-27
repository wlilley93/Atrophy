# src/main/channels/cron/scheduler.ts - In-Process Cron Scheduler

**Dependencies:** `fs`, `path`, `../../config`, `../switchboard`, `./runner`, `../../logger`  
**Purpose:** Native JavaScript job scheduler replacing launchd for job timing

## Overview

This module implements an in-process job scheduler that runs within the persistent Electron app. Instead of generating launchd plists, it uses native `setTimeout`/`setInterval` for job timing. Jobs are defined per-agent in `jobs.json` files and support both calendar-based (cron expression) and interval-based scheduling.

**Singleton:** `import { cronScheduler } from './scheduler'`

## Types

### JobDefinition

```typescript
export interface JobDefinition {
  cron?: string;                // cron expression: "min hour dom month dow"
  script: string;               // relative path to script
  description?: string;
  args?: string[];
  type?: 'calendar' | 'interval';
  interval_seconds?: number;
  route_output_to?: string;     // 'self' | specific address | undefined
}
```

### ScheduledJob

```typescript
export interface ScheduledJob {
  name: string;
  agent: string;
  definition: JobDefinition;
  timer: ReturnType<typeof setTimeout> | ReturnType<typeof setInterval> | null;
  nextRun: Date | null;
  lastRun: Date | null;
  running: boolean;
  consecutiveFailures: number;
  disabled: boolean;
}
```

## Persistent State

### Circuit Breaker

```typescript
interface PersistedJobState {
  disabled: boolean;
  consecutiveFailures: number;
  disabledAt?: string;
}

const CRON_STATE_PATH = path.join(USER_DATA, 'cron-state.json');
```

**Purpose:** Persist job disabled state and failure counts across app restarts.

### loadCronState / saveCronState

```typescript
function loadCronState(): Record<string, PersistedJobState> {
  try {
    if (fs.existsSync(CRON_STATE_PATH)) {
      return JSON.parse(fs.readFileSync(CRON_STATE_PATH, 'utf-8'));
    }
  } catch (err) {
    log.warn(`Failed to load cron state: ${err}`);
  }
  return {};
}

function saveCronState(state: Record<string, PersistedJobState>): void {
  try {
    fs.writeFileSync(CRON_STATE_PATH, JSON.stringify(state, null, 2));
  } catch (err) {
    log.warn(`Failed to save cron state: ${err}`);
  }
}
```

## Cron Expression Parsing

### fieldMatches

```typescript
function fieldMatches(field: string, value: number): boolean {
  if (field === '*') return true;
  // Comma-separated list: '0,3,6,9'
  if (field.includes(',')) {
    return field.split(',').some(part => fieldMatches(part.trim(), value));
  }
  // Step: '*/3'
  if (field.startsWith('*/')) {
    const step = parseInt(field.slice(2), 10);
    return step > 0 && value % step === 0;
  }
  // Range: '1-5'
  if (field.includes('-')) {
    const [lo, hi] = field.split('-').map(s => parseInt(s, 10));
    return value >= lo && value <= hi;
  }
  return parseInt(field, 10) === value;
}
```

**Supported formats:**
- `*` - Any value
- `5` - Specific value
- `1,3,5` - Comma-separated list
- `1-5` - Range
- `*/3` - Step values

### getNextRun

```typescript
export function getNextRun(cronStr: string, after?: Date): Date {
  const parts = cronStr.trim().split(/\s+/);
  if (parts.length !== 5) {
    throw new Error(`Invalid cron expression: '${cronStr}'`);
  }

  const [cronMin, cronHour, cronDom, cronMonth, cronDow] = parts;

  // Start from next minute
  const start = after ? new Date(after.getTime()) : new Date();
  start.setSeconds(0, 0);
  start.setMinutes(start.getMinutes() + 1);

  // Scan forward up to ~400 days (576,000 minutes)
  const MAX_ITERATIONS = 576_000;

  const candidate = new Date(start.getTime());
  for (let i = 0; i < MAX_ITERATIONS; i++) {
    const min = candidate.getMinutes();
    const hour = candidate.getHours();
    const dom = candidate.getDate();
    const month = candidate.getMonth() + 1;  // JS months are 0-indexed
    const dow = candidate.getDay();

    if (
      fieldMatches(cronMin, min) &&
      fieldMatches(cronHour, hour) &&
      fieldMatches(cronDom, dom) &&
      fieldMatches(cronMonth, month) &&
      fieldMatches(cronDow, dow)
    ) {
      return candidate;
    }

    candidate.setMinutes(candidate.getMinutes() + 1);
  }

  throw new Error(`Could not find next run for cron: '${cronStr}'`);
}
```

**Format:** `"minute hour day-of-month month day-of-week"`

**Example:** `"30 9 * * 1-5"` = 9:30 AM, Monday-Friday

## CronScheduler Class

### Properties

```typescript
class CronScheduler {
  private jobs: Map<string, ScheduledJob> = new Map();
  private started = false;
}
```

### registerAgent

```typescript
registerAgent(agentName: string, jobs: Record<string, JobDefinition>): void {
  const persisted = loadCronState();

  for (const [jobName, definition] of Object.entries(jobs)) {
    const key = `${agentName}.${jobName}`;
    const existing = this.jobs.get(key);
    
    // Clear existing timer
    if (existing?.timer) {
      if (existing.definition.type === 'interval') {
        clearInterval(existing.timer);
      } else {
        clearTimeout(existing.timer);
      }
    }

    // Restore circuit breaker state
    const saved = persisted[key];

    // Validate cron expression
    let disabledReason: string | undefined;
    const jobType = definition.type || 'calendar';
    if (jobType !== 'interval' && definition.cron) {
      try {
        getNextRun(definition.cron);
      } catch (err) {
        disabledReason = `Invalid cron: ${err}`;
      }
    }

    // Create job entry
    const job: ScheduledJob = {
      name: jobName,
      agent: agentName,
      definition,
      timer: null,
      nextRun: null,
      lastRun: null,
      running: false,
      consecutiveFailures: saved?.consecutiveFailures || 0,
      disabled: saved?.disabled || !!disabledReason,
    };

    this.jobs.set(key, job);

    // Schedule if scheduler is started
    if (this.started && !job.disabled) {
      this.scheduleJob(key, job);
    }
  }
}
```

**Flow:**
1. Load persisted state (circuit breaker)
2. Clear existing timer if re-registering
3. Validate cron expression
4. Create job entry with restored state
5. Schedule if scheduler is started and not disabled

### scheduleJob

```typescript
private scheduleJob(key: string, job: ScheduledJob): void {
  const jobType = job.definition.type || 'calendar';

  if (jobType === 'interval') {
    // Interval-based: run every N seconds
    const intervalMs = (job.definition.interval_seconds || 60) * 1000;
    job.timer = setInterval(() => {
      this.executeJob(key, job);
    }, intervalMs);
    job.nextRun = new Date(Date.now() + intervalMs);
  } else {
    // Calendar-based: run at cron-specified time
    if (!job.definition.cron) return;
    
    job.nextRun = getNextRun(job.definition.cron);
    const delay = job.nextRun.getTime() - Date.now();
    
    job.timer = setTimeout(() => {
      this.executeJob(key, job);
    }, delay);
  }
}
```

**Job types:**
- **calendar:** Run at specific times (cron expression)
- **interval:** Run every N seconds

### executeJob

```typescript
private async executeJob(key: string, job: ScheduledJob): Promise<void> {
  if (job.running || job.disabled) return;
  
  job.running = true;
  job.lastRun = new Date();
  
  try {
    const result = await runJob(job.name, job.agent);
    
    if (result.ran && !result.error) {
      // Success - reset failure count
      job.consecutiveFailures = 0;
    } else {
      // Failed - increment failure count
      job.consecutiveFailures++;
      
      // Circuit breaker: disable after 3 consecutive failures
      if (job.consecutiveFailures >= 3) {
        job.disabled = true;
        this.persistState(key);
        log.warn(`[${key}] Disabled after ${job.consecutiveFailures} failures`);
      }
    }
  } catch (err) {
    job.consecutiveFailures++;
    log.error(`[${key}] Execution error: ${err}`);
  } finally {
    job.running = false;
  }

  // Schedule next run
  if (!job.disabled) {
    this.scheduleJob(key, job);
  }
}
```

**Circuit breaker:**
- After 3 consecutive failures, job is disabled
- State is persisted to disk
- Manual intervention required to re-enable

### persistState

```typescript
private persistState(key: string): void {
  const job = this.jobs.get(key);
  if (!job) return;

  const state = loadCronState();
  state[key] = {
    disabled: job.disabled,
    consecutiveFailures: job.consecutiveFailures,
    disabledAt: job.disabled ? new Date().toISOString() : undefined,
  };
  saveCronState(state);
}
```

### start

```typescript
start(): void {
  if (this.started) return;
  this.started = true;

  // Schedule all enabled jobs
  for (const [key, job] of this.jobs) {
    if (!job.disabled) {
      this.scheduleJob(key, job);
    }
  }

  log.info(`Cron scheduler started with ${this.jobs.size} jobs`);
}
```

### getSchedule

```typescript
getSchedule(): Array<{
  name: string;
  agent: string;
  nextRun: string | null;
  lastRun: string | null;
  disabled: boolean;
  consecutiveFailures: number;
}> {
  return Array.from(this.jobs.values()).map(job => ({
    name: job.name,
    agent: job.agent,
    nextRun: job.nextRun?.toISOString() || null,
    lastRun: job.lastRun?.toISOString() || null,
    disabled: job.disabled,
    consecutiveFailures: job.consecutiveFailures,
  }));
}
```

## Singleton Export

```typescript
export const cronScheduler = new CronScheduler();
```

**Usage:** `import { cronScheduler } from './scheduler'`

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/cron-state.json` | Persistent circuit breaker state |
| `~/.atrophy/agents/<name>/jobs.json` | Per-agent job definitions |

## Exported API

| Function/Class | Purpose |
|----------------|---------|
| `CronScheduler` | Scheduler class |
| `cronScheduler` | Singleton instance |
| `getNextRun(cronStr, after)` | Calculate next cron run time |
| `JobDefinition` | Job definition interface |
| `ScheduledJob` | Runtime job state interface |

## See Also

- `src/main/jobs/index.ts` - Job runner framework
- `src/main/ipc/system.ts` - cron:* IPC handlers
- `scripts/agents/*/jobs.json` - Per-agent job definitions

/**
 * In-process job scheduler - replaces launchd for job timing.
 *
 * The app runs persistently in the tray, so we schedule jobs with
 * native setTimeout/setInterval instead of generating launchd plists.
 * Jobs are defined per-agent in jobs.json files. Supports calendar-based
 * (cron expression) and interval-based scheduling.
 *
 * Singleton - import { cronScheduler } from './scheduler'.
 */

import * as fs from 'fs';
import * as path from 'path';
import { BUNDLE_ROOT, USER_DATA } from '../../config';
import { switchboard } from '../switchboard';
import { runJob } from './runner';
import { createLogger } from '../../logger';

const log = createLogger('cron-scheduler');

// ---------------------------------------------------------------------------
// Persistent circuit breaker state
// ---------------------------------------------------------------------------

interface PersistedJobState {
  disabled: boolean;
  consecutiveFailures: number;
  disabledAt?: string;
}

const CRON_STATE_PATH = path.join(USER_DATA, 'cron-state.json');

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

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Job definition - matches the format in jobs.json.
 */
export interface JobDefinition {
  cron?: string;                // cron expression: "min hour dom month dow"
  script: string;               // relative path to script
  description?: string;
  args?: string[];
  type?: 'calendar' | 'interval';
  interval_seconds?: number;
  route_output_to?: string;     // 'self' | specific address | undefined
}

/**
 * Runtime state for a scheduled job.
 */
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

// ---------------------------------------------------------------------------
// Cron expression parsing
// ---------------------------------------------------------------------------

/**
 * Parse a cron field value against the current date field.
 * Supports: '*', specific numbers, comma lists ('1,3,5'),
 * ranges ('1-5'), and step values ('*&#47;3').
 */
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

/**
 * Calculate the next run time for a 5-field cron expression.
 *
 * Format: "minute hour day-of-month month day-of-week"
 * Supports '*', specific numbers, comma lists, ranges, and step values.
 *
 * Scans forward minute-by-minute from the start time, capped at
 * 400 days to prevent infinite loops.
 */
export function getNextRun(cronStr: string, after?: Date): Date {
  const parts = cronStr.trim().split(/\s+/);
  if (parts.length !== 5) {
    throw new Error(`Invalid cron expression: '${cronStr}' - need 5 fields: min hour dom month dow`);
  }

  const [cronMin, cronHour, cronDom, cronMonth, cronDow] = parts;

  // Start from the next minute after the reference time
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
    // JavaScript months are 0-indexed, cron months are 1-indexed
    const month = candidate.getMonth() + 1;
    const dow = candidate.getDay(); // 0 = Sunday, matches cron convention

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

  // Should not reach here for valid cron expressions
  throw new Error(`Could not find next run for cron: '${cronStr}' within 400 days`);
}

// ---------------------------------------------------------------------------
// Scheduler
// ---------------------------------------------------------------------------

class CronScheduler {
  private jobs: Map<string, ScheduledJob> = new Map();
  private started = false;
  /** Scheduler-level lock - prevents concurrent execution even across re-registration */
  private runningKeys: Set<string> = new Set();

  /**
   * Register all jobs for an agent. Reads the jobs from the provided
   * definitions and sets up timers (if the scheduler is already started).
   */
  registerAgent(agentName: string, jobs: Record<string, JobDefinition>): void {
    const persisted = loadCronState();

    for (const [jobName, definition] of Object.entries(jobs)) {
      const key = `${agentName}.${jobName}`;
      const existing = this.jobs.get(key);
      if (existing?.timer) {
        // Clear existing timer before re-registering
        if (existing.definition.type === 'interval') {
          clearInterval(existing.timer as ReturnType<typeof setInterval>);
        } else {
          clearTimeout(existing.timer as ReturnType<typeof setTimeout>);
        }
      }

      // Restore circuit breaker state from disk
      const saved = persisted[key];

      // Validate cron expression up front so invalid expressions are caught
      // at registration time rather than silently never firing.
      let disabledReason: string | undefined;
      const jobType = definition.type || 'calendar';
      if (jobType !== 'interval' && definition.cron) {
        try {
          getNextRun(definition.cron);
        } catch (err) {
          disabledReason = `invalid cron expression '${definition.cron}': ${err}`;
          log.warn(`Job '${key}' disabled - ${disabledReason}`);
        }
      }

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

      if (disabledReason) {
        // Already logged above - skip normal registration log
      } else if (job.disabled) {
        log.warn(`Job '${key}' restored as disabled (circuit breaker, since ${saved?.disabledAt || 'unknown'})`);
      } else {
        log.info(`Registered job: ${key} - ${definition.description || definition.script}`);
      }

      if (this.started && !job.disabled) {
        this.scheduleJob(job);
      }
    }

    log.info(`Registered ${Object.keys(jobs).length} job(s) for agent '${agentName}'`);
  }

  /**
   * Remove all jobs for an agent and clear their timers.
   */
  unregisterAgent(agentName: string): void {
    const keysToRemove: string[] = [];

    for (const [key, job] of this.jobs) {
      if (job.agent === agentName) {
        this.clearTimer(job);
        keysToRemove.push(key);
      }
    }

    for (const key of keysToRemove) {
      this.jobs.delete(key);
    }

    // Unregister switchboard address
    switchboard.unregister(`cron:${agentName}`);

    log.info(`Unregistered ${keysToRemove.length} job(s) for agent '${agentName}'`);
  }

  /**
   * Start all scheduled timers.
   */
  start(): void {
    if (this.started) return;
    this.started = true;

    for (const job of this.jobs.values()) {
      if (!job.disabled) this.scheduleJob(job);
    }

    log.info(`Started scheduler with ${this.jobs.size} job(s)`);
  }

  /**
   * Stop all timers.
   */
  stop(): void {
    this.started = false;

    for (const job of this.jobs.values()) {
      this.clearTimer(job);
    }

    log.info('Stopped scheduler');
  }

  /**
   * Return all scheduled jobs with their next/last run times.
   */
  getSchedule(): ScheduledJob[] {
    return Array.from(this.jobs.values());
  }

  /**
   * Update the cron expression for an existing job, reschedule its timer,
   * and persist the change to jobs.json on disk.
   */
  editJobSchedule(agentName: string, jobName: string, cronStr: string): void {
    const key = `${agentName}.${jobName}`;
    const job = this.jobs.get(key);

    if (!job) {
      log.warn(`editJobSchedule: job '${key}' not found`);
      return;
    }

    // Validate the new cron expression by parsing it
    getNextRun(cronStr);

    // Update in-memory definition
    job.definition.cron = cronStr;

    // Clear existing timer and reschedule
    this.clearTimer(job);
    if (this.started) {
      this.scheduleJob(job);
    }

    // Persist to agent manifest (source of truth) and jobs.json (fallback)
    const manifestPath = path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json');
    try {
      if (fs.existsSync(manifestPath)) {
        const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
        if (manifest.jobs?.[jobName]) {
          manifest.jobs[jobName].cron = cronStr;
          fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
          log.info(`editJobSchedule: updated manifest '${key}' cron to '${cronStr}'`);
        }
      }
    } catch (err) {
      log.error(`editJobSchedule: failed to update manifest for '${key}': ${err}`);
    }

    // Also update jobs.json for backward compatibility
    const jobsPath = path.join(BUNDLE_ROOT, 'scripts', 'agents', agentName, 'jobs.json');
    try {
      let allJobs: Record<string, Record<string, unknown>> = {};
      if (fs.existsSync(jobsPath)) {
        allJobs = JSON.parse(fs.readFileSync(jobsPath, 'utf-8'));
      }
      if (allJobs[jobName]) {
        allJobs[jobName].cron = cronStr;
        fs.writeFileSync(jobsPath, JSON.stringify(allJobs, null, 2));
      }
    } catch (err) {
      log.error(`editJobSchedule: failed to update jobs.json for '${key}': ${err}`);
    }
  }

  /**
   * Reset the circuit breaker for a job, re-enabling it and rescheduling.
   */
  resetJob(agentName: string, jobName: string): void {
    const key = `${agentName}.${jobName}`;
    const job = this.jobs.get(key);

    if (!job) {
      log.warn(`resetJob: job '${key}' not found`);
      return;
    }

    job.disabled = false;
    job.consecutiveFailures = 0;
    this.persistState();

    if (this.started) {
      this.scheduleJob(job);
    }

    log.info(`Circuit breaker reset for '${key}'`);
  }

  /**
   * Reset all disabled jobs at once. Returns count of jobs reset.
   */
  resetAllDisabled(): number {
    let count = 0;
    for (const [key, job] of this.jobs) {
      if (job.disabled) {
        job.disabled = false;
        job.consecutiveFailures = 0;
        if (this.started) {
          this.scheduleJob(job);
        }
        log.info(`Circuit breaker reset for '${key}'`);
        count++;
      }
    }
    if (count > 0) this.persistState();
    return count;
  }

  /**
   * Immediately trigger a job by name.
   */
  async runNow(agentName: string, jobName: string): Promise<void> {
    const key = `${agentName}.${jobName}`;
    const job = this.jobs.get(key);

    if (!job) {
      log.warn(`Job '${key}' not found`);
      return;
    }

    log.info(`Manual trigger: ${key}`);
    await this.executeJob(job);
  }

  /**
   * Register switchboard addresses for agents that have cron jobs.
   * Each agent gets a `cron:<agent>` address so other parts of the
   * system can send control messages to the scheduler.
   */
  registerWithSwitchboard(): void {
    const agents = new Set<string>();
    for (const job of this.jobs.values()) {
      agents.add(job.agent);
    }

    for (const agentName of agents) {
      const address = `cron:${agentName}`;
      if (!switchboard.hasHandler(address)) {
        switchboard.register(address, async (envelope) => {
          log.info(`Received switchboard message: ${envelope.text}`);

          // Support "run <jobName>" commands
          const match = envelope.text.match(/^run\s+(\S+)$/i);
          if (match) {
            await this.runNow(agentName, match[1]);
          }
        }, {
          type: 'system',
          description: `Cron scheduler for ${agentName}`,
          capabilities: ['run-job', 'schedule'],
        });
      }
    }
  }

  // -----------------------------------------------------------------------
  // Private helpers
  // -----------------------------------------------------------------------

  /**
   * Set up the timer for a single job based on its type.
   */
  private scheduleJob(job: ScheduledJob): void {
    const key = `${job.agent}.${job.name}`;
    const jobType = job.definition.type || 'calendar';

    if (jobType === 'interval' && job.definition.interval_seconds) {
      // Interval-based job - use setInterval
      const intervalMs = job.definition.interval_seconds * 1000;
      job.nextRun = new Date(Date.now() + intervalMs);

      job.timer = setInterval(() => {
        this.executeJob(job).catch((err) => {
          log.error(`Interval job '${key}' failed: ${err}`);
        });
      }, intervalMs);

      log.info(`Scheduled interval job '${key}': every ${job.definition.interval_seconds}s`);
    } else if (job.definition.cron) {
      // Calendar-based job - calculate next run, use setTimeout, then reschedule
      this.scheduleCalendarJob(job);
    } else {
      log.warn(`Job '${key}' has no cron expression or interval - skipping`);
    }
  }

  /**
   * Schedule a calendar-based job. Calculates the next run time from
   * the cron expression, sets a setTimeout, and reschedules after firing.
   */
  private scheduleCalendarJob(job: ScheduledJob): void {
    // Don't reschedule disabled jobs (circuit breaker tripped)
    if (job.disabled) return;

    // Clear any existing timer to prevent orphaned duplicates
    this.clearTimer(job);

    const key = `${job.agent}.${job.name}`;

    try {
      const nextRun = getNextRun(job.definition.cron!);
      job.nextRun = nextRun;

      // Cap delay at 24 hours - for jobs further out, we re-check daily
      // (setTimeout has a max safe delay of ~24.8 days but shorter
      //  intervals let us handle clock drift and DST changes)
      const MAX_DELAY_MS = 24 * 60 * 60 * 1000;
      const delayMs = nextRun.getTime() - Date.now();
      const actualDelay = Math.min(delayMs, MAX_DELAY_MS);

      job.timer = setTimeout(() => {
        // Re-evaluate delay from current time instead of using the
        // closed-over delayMs. The original value is stale after the
        // timer fires and using it caused jobs near the 24h boundary
        // to be skipped entirely.
        const now = Date.now();
        const remainingMs = job.nextRun ? job.nextRun.getTime() - now : 0;

        if (remainingMs <= 5000) {
          // Within 5s of intended fire time, or past it (clock drift/DST) - execute
          this.executeJob(job)
            .catch((err) => {
              log.error(`Calendar job '${key}' failed: ${err}`);
            })
            .finally(() => {
              if (this.started) {
                this.scheduleCalendarJob(job);
              }
            });
        } else {
          // Not yet time - re-check with updated delay
          if (this.started) {
            this.scheduleCalendarJob(job);
          }
        }
      }, actualDelay);

      log.info(`Scheduled calendar job '${key}': next run ${nextRun.toISOString()} (in ${Math.round(delayMs / 1000)}s)`);
    } catch (err) {
      log.error(`Failed to schedule calendar job '${key}': ${err}`);
    }
  }

  /**
   * Execute a job - calls the runner and updates state.
   * Tracks consecutive failures and disables the job after 3 in a row
   * (circuit breaker) to prevent runaway loops.
   */
  private async executeJob(job: ScheduledJob): Promise<void> {
    const key = `${job.agent}.${job.name}`;

    if (job.disabled) {
      log.warn(`Job '${key}' is disabled (circuit breaker) - skipping`);
      return;
    }

    // Scheduler-level dedup - survives re-registration races
    if (this.runningKeys.has(key)) {
      log.warn(`Job '${key}' is already running - skipping duplicate`);
      return;
    }

    // Time-based dedup - prevent re-fire from app restart races and timer drift.
    // Default 30s window catches calendar-job double-fires from boot races.
    // For interval jobs we cap at half the interval so a 60s alert_watch loop
    // never blocks itself (cap = 30s for >=60s interval, smaller for shorter).
    let minRefireMs = 30_000;
    const def = job.definition as { type?: string; interval_seconds?: number };
    if (def.type === 'interval' && typeof def.interval_seconds === 'number') {
      minRefireMs = Math.min(minRefireMs, Math.floor(def.interval_seconds * 1000 / 2));
    }
    if (job.lastRun) {
      const sinceLast = Date.now() - job.lastRun.getTime();
      if (sinceLast < minRefireMs) {
        // Demoted to debug for normal interval drift; only warn on calendar jobs
        const level = def.type === 'interval' ? 'debug' : 'warn';
        log[level](`Job '${key}' ran ${Math.round(sinceLast / 1000)}s ago - skipping (min refire: ${minRefireMs / 1000}s)`);
        return;
      }
    }

    this.runningKeys.add(key);
    job.running = true;
    log.info(`Executing job: ${key}`);

    try {
      const result = await runJob(job.agent, job.name, job.definition);
      job.lastRun = new Date();

      if (result.exitCode !== 0) {
        job.consecutiveFailures++;
        log.warn(`Job '${key}' failed (exit=${result.exitCode}), consecutive failures: ${job.consecutiveFailures}`);
        if (job.consecutiveFailures >= 3) {
          job.disabled = true;
          this.clearTimer(job);
          log.error(`Job '${key}' disabled after ${job.consecutiveFailures} consecutive failures (circuit breaker)`);
        }
        this.persistState();
      } else if (job.consecutiveFailures > 0) {
        // Recovery - clear failure count and persist
        job.consecutiveFailures = 0;
        this.persistState();
      }
    } catch (err) {
      log.error(`Job '${key}' execution error: ${err}`);
      job.lastRun = new Date();
      job.consecutiveFailures++;
      if (job.consecutiveFailures >= 3) {
        job.disabled = true;
        this.clearTimer(job);
        log.error(`Job '${key}' disabled after ${job.consecutiveFailures} consecutive failures (circuit breaker)`);
      }
      this.persistState();
    } finally {
      this.runningKeys.delete(key);
      job.running = false;
    }
  }

  /**
   * Clear the timer for a job.
   */
  private clearTimer(job: ScheduledJob): void {
    if (!job.timer) return;

    const jobType = job.definition.type || 'calendar';
    if (jobType === 'interval') {
      clearInterval(job.timer as ReturnType<typeof setInterval>);
    } else {
      clearTimeout(job.timer as ReturnType<typeof setTimeout>);
    }
    job.timer = null;
  }

  /**
   * Persist circuit breaker state for all jobs to disk.
   * Only saves jobs that have non-zero failure counts or are disabled.
   */
  private persistState(): void {
    // Load existing state so we can preserve original disabledAt timestamps
    const existing = loadCronState();
    const state: Record<string, PersistedJobState> = {};
    for (const [key, job] of this.jobs) {
      if (job.disabled || job.consecutiveFailures > 0) {
        state[key] = {
          disabled: job.disabled,
          consecutiveFailures: job.consecutiveFailures,
          disabledAt: job.disabled ? (existing[key]?.disabledAt || new Date().toISOString()) : undefined,
        };
      }
    }
    saveCronState(state);
  }
}

// ---------------------------------------------------------------------------
// Job file loading helper
// ---------------------------------------------------------------------------

/**
 * Load jobs.json for a given agent from the bundle.
 */
export function loadJobsFile(agentName: string): Record<string, JobDefinition> {
  const jobsPath = path.join(BUNDLE_ROOT, 'scripts', 'agents', agentName, 'jobs.json');
  if (!fs.existsSync(jobsPath)) return {};
  try {
    return JSON.parse(fs.readFileSync(jobsPath, 'utf-8'));
  } catch (err) {
    log.error(`Failed to load jobs.json for '${agentName}': ${err}`);
    return {};
  }
}

// ---------------------------------------------------------------------------
// Singleton
// ---------------------------------------------------------------------------

export const cronScheduler = new CronScheduler();

/**
 * Edit the cron schedule for a job. Standalone wrapper around the singleton.
 */
export function editJobSchedule(agentName: string, jobName: string, cronStr: string): void {
  cronScheduler.editJobSchedule(agentName, jobName, cronStr);
}

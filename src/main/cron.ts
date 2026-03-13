/**
 * launchd job management - scheduled task control plane.
 * Port of scripts/cron.py.
 *
 * Generates launchd plists for companion background jobs. Jobs are defined
 * in per-agent jobs.json files. Supports calendar-based (cron) and
 * interval-based scheduling.
 */

import { execSync, spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { getConfig, BUNDLE_ROOT, USER_DATA } from './config';
import { createLogger } from './logger';

const log = createLogger('cron');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Job {
  cron?: string;
  script: string;
  description?: string;
  args?: string[];
  type?: 'calendar' | 'interval';
  interval_seconds?: number;
}

export interface JobInfo extends Job {
  name: string;
  installed: boolean;
  schedule: string;
}

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

const LAUNCH_AGENTS = path.join(process.env.HOME || '/tmp', 'Library', 'LaunchAgents');

function labelPrefix(): string {
  return `com.atrophiedmind.${getConfig().AGENT_NAME}.`;
}

function jobsFile(): string {
  const config = getConfig();
  return path.join(BUNDLE_ROOT, 'scripts', 'agents', config.AGENT_NAME, 'jobs.json');
}

function logsDir(): string {
  const config = getConfig();
  return path.join(USER_DATA, 'logs', config.AGENT_NAME);
}

function plistPath(name: string): string {
  return path.join(LAUNCH_AGENTS, `${labelPrefix()}${name}.plist`);
}

// ---------------------------------------------------------------------------
// Job storage
// ---------------------------------------------------------------------------

function loadJobs(): Record<string, Job> {
  const p = jobsFile();
  if (!fs.existsSync(p)) return {};
  try {
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch {
    return {};
  }
}

function saveJobs(jobs: Record<string, Job>): void {
  const p = jobsFile();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(jobs, null, 2));
}

// ---------------------------------------------------------------------------
// Cron parsing
// ---------------------------------------------------------------------------

interface CalendarInterval {
  Minute?: number;
  Hour?: number;
  Day?: number;
  Month?: number;
  Weekday?: number;
}

function parseCron(cronStr: string): CalendarInterval {
  const parts = cronStr.split(/\s+/);
  if (parts.length !== 5) {
    throw new Error(`Invalid cron: '${cronStr}' - need 5 fields: min hour dom month dow`);
  }

  const [minute, hour, dom, month, dow] = parts;
  const interval: CalendarInterval = {};

  if (minute !== '*') interval.Minute = parseInt(minute, 10);
  if (hour !== '*') interval.Hour = parseInt(hour, 10);
  if (dom !== '*') interval.Day = parseInt(dom, 10);
  if (month !== '*') interval.Month = parseInt(month, 10);
  if (dow !== '*') interval.Weekday = parseInt(dow, 10);

  return interval;
}

// ---------------------------------------------------------------------------
// Plist generation
// ---------------------------------------------------------------------------

interface PlistDict {
  Label: string;
  ProgramArguments: string[];
  WorkingDirectory: string;
  StandardOutPath: string;
  StandardErrorPath: string;
  EnvironmentVariables: Record<string, string>;
  StartCalendarInterval?: CalendarInterval;
  StartInterval?: number;
}

function generatePlist(name: string, job: Job): PlistDict {
  const config = getConfig();
  const label = `${labelPrefix()}${name}`;
  const scriptPath = path.resolve(BUNDLE_ROOT, job.script);
  const logPath = path.join(logsDir(), `${name}.log`);
  const extraArgs = job.args || [];

  const plist: PlistDict = {
    Label: label,
    ProgramArguments: [config.PYTHON_PATH, scriptPath, ...extraArgs],
    WorkingDirectory: BUNDLE_ROOT,
    StandardOutPath: logPath,
    StandardErrorPath: logPath,
    EnvironmentVariables: {
      PATH: `/usr/local/bin:/usr/bin:/bin:${path.dirname(config.PYTHON_PATH)}`,
      AGENT: config.AGENT_NAME,
    },
  };

  const jobType = job.type || 'calendar';
  if (jobType === 'interval' && job.interval_seconds) {
    plist.StartInterval = job.interval_seconds;
  } else if (job.cron) {
    plist.StartCalendarInterval = parseCron(job.cron);
  }

  return plist;
}

// Serialize plist to XML (minimal implementation)
function plistToXml(plist: PlistDict): string {
  const lines: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
    '<plist version="1.0">',
    '<dict>',
  ];

  function escapeXml(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function addKeyValue(key: string, value: unknown, indent = 1): void {
    const tab = '\t'.repeat(indent);
    if (typeof value === 'string') {
      lines.push(`${tab}<key>${escapeXml(key)}</key>`);
      lines.push(`${tab}<string>${escapeXml(value)}</string>`);
    } else if (typeof value === 'number') {
      lines.push(`${tab}<key>${escapeXml(key)}</key>`);
      lines.push(`${tab}<integer>${value}</integer>`);
    } else if (typeof value === 'boolean') {
      lines.push(`${tab}<key>${escapeXml(key)}</key>`);
      lines.push(`${tab}<${value}/>`);
    } else if (Array.isArray(value)) {
      lines.push(`${tab}<key>${escapeXml(key)}</key>`);
      lines.push(`${tab}<array>`);
      for (const item of value) {
        if (typeof item === 'string') {
          lines.push(`${tab}\t<string>${escapeXml(item)}</string>`);
        }
      }
      lines.push(`${tab}</array>`);
    } else if (typeof value === 'object' && value !== null) {
      lines.push(`${tab}<key>${escapeXml(key)}</key>`);
      lines.push(`${tab}<dict>`);
      for (const [k, v] of Object.entries(value)) {
        addKeyValue(k, v, indent + 1);
      }
      lines.push(`${tab}</dict>`);
    }
  }

  for (const [key, value] of Object.entries(plist)) {
    addKeyValue(key, value);
  }

  lines.push('</dict>');
  lines.push('</plist>');
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Install / Uninstall
// ---------------------------------------------------------------------------

function installJob(name: string, job: Job): void {
  fs.mkdirSync(logsDir(), { recursive: true });
  fs.mkdirSync(LAUNCH_AGENTS, { recursive: true });

  const plist = generatePlist(name, job);
  const pp = plistPath(name);

  fs.writeFileSync(pp, plistToXml(plist));
  spawnSync('launchctl', ['load', pp], { stdio: 'pipe' });
  log.info(`Installed ${name} -> ${pp}`);
}

function uninstallJob(name: string): void {
  const pp = plistPath(name);
  if (fs.existsSync(pp)) {
    spawnSync('launchctl', ['unload', pp], { stdio: 'pipe' });
    fs.unlinkSync(pp);
    log.info(`Uninstalled ${name}`);
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function listJobs(): JobInfo[] {
  const jobs = loadJobs();
  return Object.entries(jobs).map(([name, job]) => ({
    name,
    ...job,
    installed: fs.existsSync(plistPath(name)),
    schedule: job.type === 'interval'
      ? `every ${job.interval_seconds}s`
      : job.cron || '?',
  }));
}

export function addJob(
  name: string,
  cronStr: string,
  script: string,
  description = '',
  install = false,
): void {
  parseCron(cronStr); // validate
  const jobs = loadJobs();
  jobs[name] = { cron: cronStr, script, description };
  saveJobs(jobs);
  log.info(`Added job '${name}': ${cronStr} -> ${script}`);
  if (install) installJob(name, jobs[name]);
}

export function removeJob(name: string): void {
  const jobs = loadJobs();
  if (!(name in jobs)) {
    log.warn(`Job '${name}' not found`);
    return;
  }
  uninstallJob(name);
  delete jobs[name];
  saveJobs(jobs);
  log.info(`Removed job '${name}'`);
}

export function editJobSchedule(name: string, cronStr: string): void {
  const jobs = loadJobs();
  if (!(name in jobs)) {
    log.warn(`Job '${name}' not found`);
    return;
  }
  parseCron(cronStr);
  jobs[name].cron = cronStr;
  saveJobs(jobs);

  // Reinstall if already installed
  if (fs.existsSync(plistPath(name))) {
    uninstallJob(name);
    installJob(name, jobs[name]);
  }
}

// ---------------------------------------------------------------------------
// Job run history (in-memory, last 100 entries)
// ---------------------------------------------------------------------------

export interface JobRunEntry {
  name: string;
  timestamp: string;
  exitCode: number;
  output: string;
  durationMs: number;
  agent: string;
}

const _history: JobRunEntry[] = [];
const MAX_HISTORY = 100;

function pushHistory(entry: JobRunEntry): void {
  _history.push(entry);
  if (_history.length > MAX_HISTORY) _history.splice(0, _history.length - MAX_HISTORY);
}

export function getJobHistory(): JobRunEntry[] {
  return [..._history].reverse();
}

export function runJobNow(name: string): JobRunEntry {
  const jobs = loadJobs();
  const config = getConfig();
  const t0 = Date.now();

  if (!(name in jobs)) {
    log.warn(`Job '${name}' not found`);
    const entry: JobRunEntry = {
      name,
      timestamp: new Date().toISOString(),
      exitCode: 1,
      output: `Job '${name}' not found`,
      durationMs: Date.now() - t0,
      agent: config.AGENT_NAME,
    };
    pushHistory(entry);
    return entry;
  }

  const job = jobs[name];
  const scriptPath = path.resolve(BUNDLE_ROOT, job.script);
  const extraArgs = job.args || [];

  const result = spawnSync(config.PYTHON_PATH, [scriptPath, ...extraArgs], {
    cwd: BUNDLE_ROOT,
    stdio: 'pipe',
    env: { ...process.env, AGENT: config.AGENT_NAME },
    timeout: 120_000,
  });

  const stdout = result.stdout?.toString('utf-8') || '';
  const stderr = result.stderr?.toString('utf-8') || '';
  const output = (stdout + (stderr ? '\n--- stderr ---\n' + stderr : '')).trim();
  const exitCode = result.status ?? 1;

  const entry: JobRunEntry = {
    name,
    timestamp: new Date().toISOString(),
    exitCode,
    output: output.slice(0, 10_000),
    durationMs: Date.now() - t0,
    agent: config.AGENT_NAME,
  };
  pushHistory(entry);

  log.info(`Job '${name}' finished (exit=${exitCode}, ${entry.durationMs}ms)`);
  return entry;
}

/**
 * Read the last N lines of a job's log file.
 */
export function readJobLog(name: string, lines = 200): string {
  const logPath = path.join(logsDir(), `${name}.log`);
  if (!fs.existsSync(logPath)) return '';
  try {
    const content = fs.readFileSync(logPath, 'utf-8');
    const allLines = content.split('\n');
    return allLines.slice(-lines).join('\n');
  } catch {
    return '';
  }
}

export function installAllJobs(): void {
  const jobs = loadJobs();
  if (!Object.keys(jobs).length) {
    log.info('No jobs to install');
    return;
  }
  for (const [name, job] of Object.entries(jobs)) {
    installJob(name, job);
  }
  log.info(`Installed ${Object.keys(jobs).length} job(s)`);
}

export function uninstallAllJobs(): void {
  const jobs = loadJobs();
  for (const name of Object.keys(jobs)) {
    uninstallJob(name);
  }
  log.info(`Uninstalled ${Object.keys(jobs).length} job(s)`);
}

export function toggleCron(enabled: boolean): void {
  if (enabled) {
    installAllJobs();
  } else {
    uninstallAllJobs();
  }
}

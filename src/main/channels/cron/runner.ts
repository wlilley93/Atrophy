/**
 * Job execution engine - spawns scripts, captures output, routes results.
 *
 * Runs job scripts as child processes, captures stdout/stderr, and creates
 * switchboard Envelopes for the results. Keeps an in-memory history of
 * the last 100 job runs for inspection.
 */

import { spawn } from 'child_process';
import * as path from 'path';
import { getConfig, BUNDLE_ROOT, USER_DATA } from '../../config';
import { switchboard } from '../switchboard';
import { createLogger } from '../../logger';
import type { JobDefinition } from './scheduler';

const log = createLogger('cron-runner');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Result of a completed job execution.
 */
export interface JobResult {
  agent: string;
  job: string;
  exitCode: number;
  stdout: string;
  stderr: string;
  durationMs: number;
  timestamp: string;
}

// ---------------------------------------------------------------------------
// Job history (in-memory ring buffer)
// ---------------------------------------------------------------------------

const MAX_HISTORY = 100;
const _history: JobResult[] = [];

function pushHistory(result: JobResult): void {
  _history.push(result);
  if (_history.length > MAX_HISTORY) {
    _history.splice(0, _history.length - MAX_HISTORY);
  }
}

/**
 * Get the job run history, newest first.
 */
export function getJobHistory(): JobResult[] {
  return [..._history].reverse();
}

// ---------------------------------------------------------------------------
// Job execution
// ---------------------------------------------------------------------------

/** Default script timeout in milliseconds. */
const DEFAULT_TIMEOUT_MS = 120_000;

/**
 * Run a job script as a child process.
 *
 * Resolves the script path relative to BUNDLE_ROOT, spawns it with
 * the configured Python interpreter, captures output, and routes
 * the result through the switchboard.
 */
export async function runJob(
  agentName: string,
  jobName: string,
  definition: JobDefinition,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<JobResult> {
  const config = getConfig();
  const scriptPath = path.resolve(BUNDLE_ROOT, definition.script);
  const rawArgs = definition.args || [];
  const extraArgs = typeof rawArgs === 'string' ? (rawArgs as string).split(/\s+/).filter(Boolean) : rawArgs;
  const pythonPath = config.PYTHON_PATH;
  const pythonBinDir = path.dirname(pythonPath);
  const t0 = Date.now();

  log.info(`Running job '${agentName}.${jobName}': ${definition.script}`);

  const result = await new Promise<JobResult>((resolve) => {
    let stdout = '';
    let stderr = '';
    let finished = false;

    const env: Record<string, string> = {
      ...process.env as Record<string, string>,
      PATH: `${pythonBinDir}:/usr/local/bin:/usr/bin:/bin`,
      AGENT: agentName,
      PYTHONPATH: `${BUNDLE_ROOT}:${path.join(USER_DATA, 'src')}`,
    };

    const child = spawn(pythonPath, [scriptPath, ...extraArgs], {
      cwd: BUNDLE_ROOT,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: timeoutMs,
    });

    child.stdout.on('data', (chunk: Buffer) => {
      stdout += chunk.toString('utf-8');
    });

    child.stderr.on('data', (chunk: Buffer) => {
      stderr += chunk.toString('utf-8');
    });

    const finish = (exitCode: number) => {
      if (finished) return;
      finished = true;

      const jobResult: JobResult = {
        agent: agentName,
        job: jobName,
        exitCode,
        stdout: stdout.slice(0, 50_000),
        stderr: stderr.slice(0, 10_000),
        durationMs: Date.now() - t0,
        timestamp: new Date().toISOString(),
      };

      resolve(jobResult);
    };

    child.on('close', (code) => {
      finish(code ?? 1);
    });

    child.on('error', (err) => {
      log.error(`Job '${agentName}.${jobName}' spawn error: ${err.message}`);
      stderr += `\nSpawn error: ${err.message}`;
      finish(1);
    });
  });

  // Record in history
  pushHistory(result);

  log.info(
    `Job '${agentName}.${jobName}' finished (exit=${result.exitCode}, ${result.durationMs}ms)`,
  );

  if (result.stderr && result.exitCode !== 0) {
    log.warn(`Job '${agentName}.${jobName}' stderr: ${result.stderr.slice(0, 500)}`);
  }

  // -----------------------------------------------------------------------
  // Route result through switchboard
  // -----------------------------------------------------------------------

  const outputText = result.stdout.trim() || `Job '${jobName}' completed with exit code ${result.exitCode}`;

  // Primary envelope - send job output to the agent
  const envelope = switchboard.createEnvelope(
    `cron:${agentName}.${jobName}`,
    `agent:${agentName}`,
    outputText,
    {
      type: 'system',
      priority: 'normal',
      metadata: {
        job: jobName,
        exitCode: result.exitCode,
        durationMs: result.durationMs,
        stderr: result.stderr || undefined,
      },
    },
  );

  try {
    await switchboard.route(envelope);
  } catch (err) {
    log.error(`Failed to route job result for '${agentName}.${jobName}': ${err}`);
  }

  // -----------------------------------------------------------------------
  // Notification envelope (if notify_via is set)
  // -----------------------------------------------------------------------

  if (definition.notify_via) {
    const notifyAddress = `${definition.notify_via}:${agentName}`;
    const statusEmoji = result.exitCode === 0 ? '[OK]' : '[FAIL]';
    const summary = [
      `${statusEmoji} Job: ${jobName}`,
      `Exit: ${result.exitCode}`,
      `Duration: ${formatDuration(result.durationMs)}`,
    ];

    if (result.stdout.trim()) {
      const preview = result.stdout.trim().slice(0, 500);
      summary.push(`Output: ${preview}`);
    }

    if (result.stderr.trim() && result.exitCode !== 0) {
      const errPreview = result.stderr.trim().slice(0, 300);
      summary.push(`Error: ${errPreview}`);
    }

    const notifyEnvelope = switchboard.createEnvelope(
      `cron:${agentName}.${jobName}`,
      notifyAddress,
      summary.join('\n'),
      {
        type: 'system',
        priority: result.exitCode === 0 ? 'normal' : 'high',
        metadata: {
          job: jobName,
          exitCode: result.exitCode,
          durationMs: result.durationMs,
        },
      },
    );

    try {
      await switchboard.route(notifyEnvelope);
    } catch (err) {
      log.error(`Failed to route notification for '${agentName}.${jobName}': ${err}`);
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Format a duration in milliseconds to a human-readable string.
 */
function formatDuration(ms: number): string {
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  return `${mins}m ${remSecs}s`;
}

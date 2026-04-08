/**
 * Job execution engine - spawns scripts, captures output, routes results.
 *
 * Runs job scripts as child processes, captures stdout/stderr, and creates
 * switchboard Envelopes for the results. Keeps an in-memory history of
 * the last 100 job runs for inspection.
 */

import { spawn, ChildProcess } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import { getConfig, BUNDLE_ROOT, USER_DATA } from '../../config';
import { switchboard } from '../switchboard';
import { createLogger } from '../../logger';
import type { JobDefinition } from './scheduler';

const log = createLogger('cron-runner');

// ---------------------------------------------------------------------------
// Running process tracking - ensures child processes are killed on shutdown
// ---------------------------------------------------------------------------

const _runningProcesses = new Set<ChildProcess>();

/**
 * Kill all tracked child processes. Called during app shutdown to prevent
 * zombie processes from lingering after the app exits.
 */
export function stopAllJobs(): void {
  for (const child of _runningProcesses) {
    try { child.kill(); } catch { /* already dead */ }
  }
  _runningProcesses.clear();
}

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
  // Inference usage (parsed from stderr [inference] lines emitted by claude_cli.py).
  // Present only when the job actually called the Claude CLI.
  inference?: {
    model: string;
    tokensIn: number;
    tokensOut: number;
    costUsd: number;
  };
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
  // Allow per-job timeout override via manifest (`timeout_seconds`).
  // Long-running data sync jobs (ontology_sync, harvest_articles) need
  // more than the default 2 minutes.
  const def = definition as { timeout_seconds?: number };
  if (typeof def.timeout_seconds === 'number' && def.timeout_seconds > 0) {
    timeoutMs = def.timeout_seconds * 1000;
  }
  const config = getConfig();
  // Check personal scripts dir first (~/.atrophy/scripts/), fall back to bundle.
  // Validate resolved paths stay within their expected directories to prevent traversal.
  const scriptRelative = definition.script.replace(/^scripts\//, '');
  const personalPath = path.resolve(USER_DATA, 'scripts', scriptRelative);
  const bundlePath = path.resolve(BUNDLE_ROOT, definition.script);
  const personalRoot = path.resolve(USER_DATA, 'scripts') + path.sep;
  const bundleRoot = path.resolve(BUNDLE_ROOT) + path.sep;
  const personalSafe = personalPath.startsWith(personalRoot);
  const bundleSafe = bundlePath.startsWith(bundleRoot);
  let scriptPath: string;
  if (personalSafe && fs.existsSync(personalPath)) {
    scriptPath = personalPath;
  } else if (bundleSafe) {
    scriptPath = bundlePath;
  } else {
    log.error(`Job '${agentName}.${jobName}' script path escapes allowed directories: ${definition.script}`);
    return { agent: agentName, job: jobName, stdout: '', stderr: 'Script path rejected - traversal detected', exitCode: 1, durationMs: 0, timestamp: new Date().toISOString() };
  }
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
      JOB_NAME: jobName,
      PYTHONPATH: [
        path.join(USER_DATA, 'scripts', 'agents'),
        path.join(USER_DATA, 'scripts'),
        path.join(BUNDLE_ROOT, 'scripts', 'agents'),
        BUNDLE_ROOT,
        path.join(USER_DATA, 'src'),
      ].join(':'),
      CHANNEL_API_KEY: process.env.CHANNEL_API_KEY || '',
      UPSTASH_REDIS_REST_URL: process.env.UPSTASH_REDIS_REST_URL || '',
      UPSTASH_REDIS_REST_TOKEN: process.env.UPSTASH_REDIS_REST_TOKEN || '',
    };

    const child = spawn(pythonPath, [scriptPath, ...extraArgs], {
      cwd: BUNDLE_ROOT,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: timeoutMs,
    });

    _runningProcesses.add(child);

    child.stdout.on('data', (chunk: Buffer) => {
      stdout += chunk.toString('utf-8');
    });

    child.stderr.on('data', (chunk: Buffer) => {
      stderr += chunk.toString('utf-8');
    });

    const finish = (exitCode: number) => {
      if (finished) return;
      finished = true;
      _runningProcesses.delete(child);

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

  // Extract inference usage from stderr. The Python claude_cli.py helper
  // emits a parseable line: [inference] agent=X job=Y model=Z tokens_in=N tokens_out=M cost_usd=C
  // We surface this prominently in the log so operators can see which cron
  // jobs are burning tokens and how much.
  const inferenceLines = (result.stderr || '').split('\n').filter((l) => l.startsWith('[inference]'));
  let totalTokensIn = 0;
  let totalTokensOut = 0;
  let totalCost = 0;
  let inferenceModel = '';
  for (const line of inferenceLines) {
    const inMatch = line.match(/tokens_in=(\d+)/);
    const outMatch = line.match(/tokens_out=(\d+)/);
    const costMatch = line.match(/cost_usd=([\d.]+)/);
    const modelMatch = line.match(/model=(\S+)/);
    if (inMatch) totalTokensIn += parseInt(inMatch[1], 10);
    if (outMatch) totalTokensOut += parseInt(outMatch[1], 10);
    if (costMatch) totalCost += parseFloat(costMatch[1]);
    if (modelMatch && !inferenceModel) inferenceModel = modelMatch[1];
  }

  if (inferenceLines.length > 0) {
    result.inference = {
      model: inferenceModel,
      tokensIn: totalTokensIn,
      tokensOut: totalTokensOut,
      costUsd: totalCost,
    };
    log.info(
      `Job '${agentName}.${jobName}' finished (exit=${result.exitCode}, ${result.durationMs}ms) ` +
      `[inference: ${inferenceModel} ${totalTokensIn}+${totalTokensOut} tokens, $${totalCost.toFixed(4)}]`,
    );
  } else {
    log.info(
      `Job '${agentName}.${jobName}' finished (exit=${result.exitCode}, ${result.durationMs}ms)`,
    );
  }

  if (result.stderr && result.exitCode !== 0) {
    log.warn(`Job '${agentName}.${jobName}' stderr: ${result.stderr.slice(0, 500)}`);
  }

  // -----------------------------------------------------------------------
  // Route result through switchboard
  // -----------------------------------------------------------------------

  const outputText = result.stdout.trim();

  // Only route through switchboard if the job succeeded and produced output.
  // Silent success (exit 0, no stdout) stays silent. Failed jobs (non-zero
  // exit) are not routed - their tracebacks would confuse the agent.
  if (outputText && result.exitCode === 0) {
    const envelope = switchboard.createEnvelope(
      `cron:${agentName}.${jobName}`,
      `agent:${agentName}`,
      outputText,
      {
        type: 'system',
        priority: 'normal',
        metadata: {
          job: jobName,
          dispatch: !!definition.route_output_to,
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
  }

  // Job status is log-only - no channel notifications.
  // Human-ready output flows through the switchboard envelope above.

  return result;
}


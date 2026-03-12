/**
 * Background job runner framework.
 *
 * Provides a common harness for all background jobs (heartbeat, evolve, etc.).
 * Jobs can be invoked from:
 *   1. launchd - as a standalone Node process via electron CLI
 *   2. The main Electron process - for manual triggers or in-app scheduling
 *
 * Each job implements the JobDefinition interface and is registered here.
 * The runner handles logging, error reporting, and gate checks.
 */

import { getConfig } from '../config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Outcome of a job run. */
export interface JobResult {
  /** Job name */
  job: string;
  /** Whether the job ran (vs. being gated/skipped) */
  ran: boolean;
  /** Human-readable outcome */
  outcome: string;
  /** Duration in milliseconds */
  durationMs: number;
  /** Error if the job threw */
  error?: string;
}

/** Gate function - returns null if OK, or a reason string to skip. */
export type GateCheck = () => string | null;

/** A registered background job. */
export interface JobDefinition {
  /** Unique name, e.g. 'heartbeat', 'evolve' */
  name: string;
  /** Human-readable description */
  description: string;
  /** Pre-run gate checks. If any returns a reason, the job is skipped. */
  gates: GateCheck[];
  /** The actual job logic. Returns a summary string. */
  run: () => Promise<string>;
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

const _registry = new Map<string, JobDefinition>();

export function registerJob(def: JobDefinition): void {
  _registry.set(def.name, def);
}

export function getRegisteredJobs(): JobDefinition[] {
  return [..._registry.values()];
}

export function getJob(name: string): JobDefinition | undefined {
  return _registry.get(name);
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

/**
 * Execute a registered job by name. Runs gate checks first, then the
 * job itself. Returns a structured result. Never throws - errors are
 * captured in the result.
 */
export async function runJob(name: string, agent?: string): Promise<JobResult> {
  const t0 = Date.now();

  // If an agent is specified, reload config for that agent
  if (agent) {
    getConfig().reloadForAgent(agent);
  }

  const def = _registry.get(name);
  if (!def) {
    return {
      job: name,
      ran: false,
      outcome: `Unknown job: ${name}`,
      durationMs: Date.now() - t0,
      error: `Job '${name}' is not registered`,
    };
  }

  console.log(`[job:${name}] Starting...`);

  // Gate checks
  for (const gate of def.gates) {
    const reason = gate();
    if (reason) {
      const elapsed = Date.now() - t0;
      console.log(`[job:${name}] Gated: ${reason}`);
      return {
        job: name,
        ran: false,
        outcome: `Skipped: ${reason}`,
        durationMs: elapsed,
      };
    }
  }

  // Run
  try {
    const outcome = await def.run();
    const elapsed = Date.now() - t0;
    console.log(`[job:${name}] Done (${elapsed}ms): ${outcome.slice(0, 120)}`);
    return {
      job: name,
      ran: true,
      outcome,
      durationMs: elapsed,
    };
  } catch (e) {
    const elapsed = Date.now() - t0;
    const errMsg = e instanceof Error ? e.message : String(e);
    console.error(`[job:${name}] Error (${elapsed}ms): ${errMsg}`);
    return {
      job: name,
      ran: true,
      outcome: `Error: ${errMsg}`,
      durationMs: elapsed,
      error: errMsg,
    };
  }
}

/**
 * Run a job from the command line. Intended for launchd invocations:
 *   electron . --job=heartbeat --agent=companion
 *
 * Exits the process with code 0 on success, 1 on failure.
 */
export async function runJobFromCli(argv: string[]): Promise<void> {
  let jobName = '';
  let agent = '';

  for (const arg of argv) {
    if (arg.startsWith('--job=')) jobName = arg.slice(6);
    if (arg.startsWith('--agent=')) agent = arg.slice(8);
  }

  if (!jobName) {
    console.error('Usage: --job=<name> [--agent=<agent>]');
    process.exit(1);
  }

  if (agent) {
    getConfig().reloadForAgent(agent);
  }

  const result = await runJob(jobName, agent);
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.error ? 1 : 0);
}

// ---------------------------------------------------------------------------
// Common gate factories
// ---------------------------------------------------------------------------

/** Gate: only run during the agent's configured active hours. */
export function activeHoursGate(): string | null {
  const config = getConfig();
  const hour = new Date().getHours();
  if (hour < config.HEARTBEAT_ACTIVE_START || hour >= config.HEARTBEAT_ACTIVE_END) {
    return `Outside active hours (${config.HEARTBEAT_ACTIVE_START}-${config.HEARTBEAT_ACTIVE_END})`;
  }
  return null;
}

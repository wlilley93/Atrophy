# src/main/jobs/index.ts - Background Job Runner

**Dependencies:** `../config`, `../inference`, `../logger`  
**Purpose:** Common harness for all background jobs (heartbeat, evolve, etc.)

## Overview

This module provides a common framework for background jobs that can be invoked from:
1. **launchd** - as a standalone Node process via electron CLI
2. **Electron main process** - for manual triggers or in-app scheduling

Each job implements the `JobDefinition` interface and is registered with the runner. The runner handles logging, error reporting, and gate checks.

## Types

### JobResult

```typescript
export interface JobResult {
  job: string;        // Job name
  ran: boolean;       // Whether job ran (vs. being gated/skipped)
  outcome: string;    // Human-readable outcome
  durationMs: number; // Duration in milliseconds
  error?: string;     // Error if job threw
}
```

### GateCheck

```typescript
export type GateCheck = () => string | null;
```

**Purpose:** Gate function - returns `null` if OK to proceed, or a reason string to skip.

### JobDefinition

```typescript
export interface JobDefinition {
  name: string;           // Unique name, e.g. 'heartbeat', 'evolve'
  description: string;    // Human-readable description
  gates: GateCheck[];     // Pre-run gate checks
  run: () => Promise<string>;  // Job logic, returns summary
}
```

## Registry

### registerJob

```typescript
const _registry = new Map<string, JobDefinition>();

export function registerJob(def: JobDefinition): void {
  _registry.set(def.name, def);
}
```

**Purpose:** Register a job definition

### getRegisteredJobs

```typescript
export function getRegisteredJobs(): JobDefinition[] {
  return [..._registry.values()];
}
```

### getJob

```typescript
export function getJob(name: string): JobDefinition | undefined {
  return _registry.get(name);
}
```

## runJob

```typescript
export async function runJob(name: string, agent?: string): Promise<JobResult> {
  const t0 = Date.now();

  // If agent specified, reload config and reset MCP config
  if (agent) {
    getConfig().reloadForAgent(agent);
    resetMcpConfig();
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

  log.info(`[job:${name}] Starting...`);

  // Gate checks
  for (const gate of def.gates) {
    const reason = gate();
    if (reason) {
      const elapsed = Date.now() - t0;
      log.info(`[job:${name}] Gated: ${reason}`);
      return {
        job: name,
        ran: false,
        outcome: `Skipped: ${reason}`,
        durationMs: elapsed,
      };
    }
  }

  // Run job
  try {
    const outcome = await def.run();
    const elapsed = Date.now() - t0;
    log.info(`[job:${name}] Done (${elapsed}ms): ${outcome.slice(0, 120)}`);
    return {
      job: name,
      ran: true,
      outcome,
      durationMs: elapsed,
    };
  } catch (e) {
    const elapsed = Date.now() - t0;
    const errMsg = e instanceof Error ? e.message : String(e);
    log.error(`[job:${name}] Error (${elapsed}ms): ${errMsg}`);
    return {
      job: name,
      ran: true,
      outcome: `Error: ${errMsg}`,
      durationMs: elapsed,
      error: errMsg,
    };
  }
}
```

**Flow:**
1. Reload config for agent if specified
2. Look up job definition
3. Run gate checks (skip if any fail)
4. Execute job
5. Capture outcome or error

**Error handling:** Never throws - errors captured in result

## runJobFromCli

```typescript
export async function runJobFromCli(argv: string[]): Promise<void> {
  let jobName = '';
  let agent = '';

  // Parse --job=name --agent=name args
  for (const arg of argv) {
    if (arg.startsWith('--job=')) {
      jobName = arg.slice(6);
    } else if (arg.startsWith('--agent=')) {
      agent = arg.slice(8);
    }
  }

  if (!jobName) {
    console.error('Usage: electron . --job=<name> [--agent=<name>]');
    process.exit(1);
  }

  const result = await runJob(jobName, agent || undefined);

  if (result.ran && !result.error) {
    process.exit(0);
  } else {
    console.error(result.outcome);
    process.exit(1);
  }
}
```

**Usage:**
```bash
electron . --job=heartbeat --agent=companion
```

**Exit codes:**
- `0`: Success
- `1`: Failed or gated

## Example Job Definition

```typescript
import { registerJob, runJob } from './jobs/index';
import { getConfig } from './config';
import { getStatus } from './status';

registerJob({
  name: 'heartbeat',
  description: 'Periodic check-in with user',
  gates: [
    () => {
      // Gate: only run if user is active
      const status = getStatus();
      if (status.status === 'away') {
        return 'User is away';
      }
      return null;
    },
    () => {
      // Gate: only run during active hours
      const hour = new Date().getHours();
      const config = getConfig();
      if (hour < config.HEARTBEAT_ACTIVE_START || hour >= config.HEARTBEAT_ACTIVE_END) {
        return 'Outside active hours';
      }
      return null;
    },
  ],
  run: async () => {
    // Job logic here
    const config = getConfig();
    const message = 'Hello! How are you doing?';
    await sendMessage(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, message);
    return `Sent heartbeat: "${message}"`;
  },
});
```

## Integration with Cron Scheduler

The cron scheduler (`src/main/channels/cron/scheduler.ts`) uses this runner:

```typescript
// In scheduler.ts
import { runJob } from './jobs/index';

// When job is due
const result = await runJob(jobName, agentName);
```

## File I/O

None - job runner is purely in-memory. Jobs themselves may read/write files.

## Exported API

| Function | Purpose |
|----------|---------|
| `registerJob(def)` | Register job definition |
| `getRegisteredJobs()` | Get all registered jobs |
| `getJob(name)` | Get job by name |
| `runJob(name, agent)` | Execute job by name |
| `runJobFromCli(argv)` | Run job from command line |
| `JobDefinition` | Job definition interface |
| `JobResult` | Job result interface |
| `GateCheck` | Gate function type |

## See Also

- `src/main/channels/cron/scheduler.ts` - Cron scheduler that invokes jobs
- `src/main/jobs/heartbeat.ts` - Example job implementation
- `src/main/jobs/evolve.ts` - Example job implementation

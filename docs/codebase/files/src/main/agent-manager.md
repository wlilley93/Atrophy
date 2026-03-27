# src/main/agent-manager.ts - Agent Discovery and Management

**Dependencies:** `fs`, `path`, `child_process`, `./config`, `./logger`  
**Purpose:** Multi-agent discovery, switching, state management, and bundled prompt synchronization

## Overview

This module manages agent discovery across user data and bundle directories, agent state (muted/enabled), cycling between agents, and synchronization of bundled prompts to user directories.

## Agent Search Directories

```typescript
function agentSearchDirs(): string[] {
  const dirs: string[] = [];
  const userAgents = path.join(USER_DATA, 'agents');
  const bundleAgents = path.join(BUNDLE_ROOT, 'agents');
  if (fs.existsSync(userAgents)) dirs.push(userAgents);
  if (fs.existsSync(bundleAgents) && 
      path.resolve(bundleAgents) !== path.resolve(userAgents)) {
    dirs.push(bundleAgents);
  }
  return dirs;
}
```

**Search order:**
1. User data: `~/.atrophy/agents/` (user overrides)
2. Bundle: `<bundle>/agents/` (bundled defaults)

**Why both:** Users can override bundled agents by placing modified versions in user data.

## findManifest

```typescript
export function findManifest(name: string): Record<string, unknown> | null {
  for (const agentsDir of agentSearchDirs()) {
    const manifestPath = path.join(agentsDir, name, 'data', 'agent.json');
    if (fs.existsSync(manifestPath)) {
      try {
        return JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
      } catch {
        continue;
      }
    }
  }
  return null;
}
```

**Purpose:** Find agent manifest, checking user data first then bundle.

## AgentInfo Interface

```typescript
export interface AgentInfo {
  name: string;
  display_name: string;
  description: string;
  role: string;
  tier: number;
}
```

## discoverAgents

```typescript
export function discoverAgents(): AgentInfo[] {
  const seen = new Set<string>();
  const agents: AgentInfo[] = [];

  for (const agentsDir of agentSearchDirs()) {
    let entries: string[];
    try {
      entries = fs.readdirSync(agentsDir).sort();
    } catch {
      continue;
    }

    for (const name of entries) {
      if (seen.has(name)) continue;
      const dirPath = path.join(agentsDir, name);
      if (!fs.existsSync(path.join(dirPath, 'data'))) continue;
      seen.add(name);

      const data = findManifest(name) || {};
      const orgSection = data.org as Record<string, unknown> | undefined;
      agents.push({
        name,
        display_name: (data.display_name as string) || 
                      name.charAt(0).toUpperCase() + name.slice(1),
        description: (data.description as string) || '',
        role: (data.role as string) || '',
        tier: (orgSection?.tier as number) ?? 1,
      });
    }
  }

  // Sort by tier ascending (lower = higher priority), then alphabetical
  agents.sort((a, b) => {
    const aTier = a.tier ?? 1;
    const bTier = b.tier ?? 1;
    if (aTier !== bTier) return aTier - bTier;
    return a.name.localeCompare(b.name);
  });

  return agents;
}
```

**Deduplication:** Uses `seen` Set to avoid duplicates when same agent exists in both user and bundle dirs.

**Sorting:** By tier (lower = higher priority), then alphabetically.

**Organization support:** Reads `org.tier` from manifest for hierarchical agent organizations.

## discoverUiAgents

```typescript
export function discoverUiAgents(): AgentInfo[] {
  return discoverAgents().filter((a) => {
    const manifest = findManifest(a.name) || {};
    const org = manifest.org as Record<string, unknown> | undefined;
    if (!org) return true;  // non-org agent - always visible
    return (org.tier as number) <= 1;  // Only tier 0-1 visible in UI
  });
}
```

**Purpose:** Filter agents visible in UI rolodex/cycling.

**Excludes:** Tier 2+ org agents (headless workers that can't address user directly).

## syncBundledPrompts

```typescript
export function syncBundledPrompts(): void {
  const bundleAgents = path.join(BUNDLE_ROOT, 'agents');
  const userAgents = path.join(USER_DATA, 'agents');
  if (!fs.existsSync(bundleAgents)) return;

  let entries: string[];
  try {
    entries = fs.readdirSync(bundleAgents);
  } catch {
    return;
  }

  for (const name of entries) {
    const bundlePrompts = path.join(bundleAgents, name, 'prompts');
    const userPrompts = path.join(userAgents, name, 'prompts');
    if (!fs.existsSync(bundlePrompts)) continue;

    // Ensure user prompts dir exists
    if (!fs.existsSync(userPrompts)) {
      try {
        fs.mkdirSync(userPrompts, { recursive: true });
      } catch {
        continue;
      }
    }

    // Copy missing prompt files (never overwrite existing)
    let files: string[];
    try {
      files = fs.readdirSync(bundlePrompts).filter((f) => f.endsWith('.md'));
    } catch {
      continue;
    }

    for (const file of files) {
      const dest = path.join(userPrompts, file);
      if (!fs.existsSync(dest)) {
        try {
          fs.copyFileSync(path.join(bundlePrompts, file), dest);
          log.info(`Synced bundled prompt ${name}/prompts/${file}`);
        } catch (e) {
          log.warn(`Failed to sync prompt ${name}/prompts/${file}: ${e}`);
        }
      }
    }
  }
}
```

**Purpose:** Copy bundled prompt files to user directories if missing.

**Key behavior:** Never overwrites existing user prompts - bundle files are defaults only.

**When called:** At app startup in `app.ts`

## Agent State Management

```typescript
interface AgentState {
  muted: boolean;
  enabled: boolean;
}

function loadStates(): Record<string, unknown> {
  const config = getConfig();
  try {
    if (fs.existsSync(config.AGENT_STATES_FILE)) {
      return JSON.parse(fs.readFileSync(config.AGENT_STATES_FILE, 'utf-8'));
    }
  } catch { /* empty */ }
  return {};
}

function saveStates(states: Record<string, unknown>): void {
  const config = getConfig();
  // Atomic write via tmp + rename
  const tmp = config.AGENT_STATES_FILE + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(states, null, 2) + '\n');
  fs.renameSync(tmp, config.AGENT_STATES_FILE);
}
```

**Storage:** `~/.atrophy/agent_states.json`

**Atomic writes:** tmp file + rename prevents corruption from concurrent updates.

## getAgentState

```typescript
export function getAgentState(agentName: string): AgentState {
  const states = loadStates();
  const state = states[agentName] as Partial<AgentState> | undefined;

  // If no explicit enabled state, check manifest for default_enabled flag
  let defaultEnabled = true;
  if (state?.enabled === undefined) {
    try {
      for (const base of [
        path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json'),
        path.join(BUNDLE_ROOT, 'agents', agentName, 'data', 'agent.json'),
      ]) {
        if (fs.existsSync(base)) {
          const manifest = JSON.parse(fs.readFileSync(base, 'utf-8'));
          if (manifest.default_enabled === false) {
            defaultEnabled = false;
          }
          break;
        }
      }
    } catch { /* use default */ }
  }

  return {
    muted: state?.muted ?? false,
    enabled: state?.enabled ?? defaultEnabled,
  };
}
```

**Fallback:** If no explicit state, checks manifest `default_enabled` flag.

**Defaults:** `muted: false`, `enabled: true` (or `default_enabled` from manifest)

## setAgentState

```typescript
export function setAgentState(
  agentName: string,
  opts: { muted?: boolean; enabled?: boolean },
): void {
  const states = loadStates();
  const current = (states[agentName] as Record<string, unknown>) || 
                  { muted: false, enabled: true };

  if (opts.muted !== undefined) current.muted = opts.muted;
  if (opts.enabled !== undefined && opts.enabled !== current.enabled) {
    current.enabled = opts.enabled;
    toggleAgentCron(agentName, opts.enabled);
  }

  states[agentName] = current;
  saveStates(states);
}
```

**Side effect:** Calls `toggleAgentCron()` when enabled state changes.

## Last Active Agent

```typescript
export function setLastActiveAgent(agentName: string): void {
  const states = loadStates();
  states._last_active = agentName;
  saveStates(states);
}

export function getLastActiveAgent(): string | null {
  const states = loadStates();
  return (states._last_active as string) || null;
}
```

**Purpose:** Track which agent was last used for resume-on-startup.

## Cron Toggle

```typescript
function toggleAgentCron(agentName: string, enable: boolean): void {
  const config = getConfig();
  const jobsFile = path.join(BUNDLE_ROOT, 'scripts', 'agents', agentName, 'jobs.json');
  if (!fs.existsSync(jobsFile)) {
    log.debug(`No jobs.json for ${agentName} - skipping cron toggle`);
    return;
  }

  const cmd = enable ? 'install' : 'uninstall';
  // Validate agent name to prevent path traversal
  if (!/^[a-zA-Z0-9_-]+$/.test(agentName)) {
    log.warn(`Invalid agent name for cron toggle: ${agentName}`);
    return;
  }
  try {
    execFileSync(
      config.PYTHON_PATH,
      [path.join(BUNDLE_ROOT, 'scripts', 'cron.py'), 
       '--agent', agentName, cmd],
      { cwd: BUNDLE_ROOT, timeout: 10000, stdio: 'pipe' },
    );
    log.info(`Cron ${cmd}: ${agentName}`);
  } catch (e) {
    log.error(`Cron ${cmd} failed for ${agentName}: ${e}`);
  }
}
```

**Purpose:** Install/uninstall launchd jobs when agent enabled state changes.

**Security:** Agent name validation prevents path traversal.

**Command:** `python3 scripts/cron.py --agent <name> install|uninstall`

## Agent Cycling

```typescript
export function cycleAgent(direction: number, current: string): string | null {
  const agents = discoverUiAgents();
  if (agents.length <= 1) return null;

  const names = agents.map((a) => a.name);
  let idx = names.indexOf(current);
  if (idx === -1) return names[0] || null;

  // Walk in direction, skipping disabled agents
  for (let i = 1; i < names.length; i++) {
    const candidate = names[((idx + direction * i) % names.length + names.length) % names.length];
    const state = getAgentState(candidate);
    if (state.enabled) return candidate;
  }

  return null;  // No enabled agents found
}
```

**Purpose:** Cycle to next/previous enabled agent.

**Direction:** +1 for next, -1 for previous

**Skips:** Disabled agents

**Returns:** Next agent name or null if only one agent / no enabled agents

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/agents/<name>/data/agent.json` | findManifest, discoverAgents |
| Read | `<bundle>/agents/<name>/data/agent.json` | findManifest, discoverAgents |
| Read | `~/.atrophy/agents/<name>/prompts/*.md` | syncBundledPrompts |
| Write | `~/.atrophy/agents/<name>/prompts/*.md` | syncBundledPrompts (missing only) |
| Read/Write | `~/.atrophy/agent_states.json` | get/set agent state |
| Read | `<bundle>/scripts/agents/<name>/jobs.json` | toggleAgentCron |
| Execute | `scripts/cron.py` | toggleAgentCron |

## Exported API

| Function | Purpose |
|----------|---------|
| `findManifest(name)` | Find agent manifest |
| `discoverAgents()` | Discover all agents |
| `discoverUiAgents()` | Discover UI-visible agents |
| `syncBundledPrompts()` | Copy bundled prompts to user dirs |
| `getAgentState(name)` | Get agent muted/enabled state |
| `setAgentState(name, opts)` | Set agent state |
| `setLastActiveAgent(name)` | Set last active agent |
| `getLastActiveAgent()` | Get last active agent |
| `cycleAgent(direction, current)` | Cycle to next/prev agent |

## See Also

- `src/main/config.ts` - Config singleton, paths
- `src/main/ipc/agents.ts` - IPC handlers for agent management
- `src/main/app.ts` - Calls syncBundledPrompts at startup
- `scripts/cron.py` - Python cron management script

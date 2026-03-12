/**
 * Multi-agent discovery, switching, and state management.
 * Port of core/agent_manager.py.
 */

import * as fs from 'fs';
import * as path from 'path';
import { execSync } from 'child_process';
import { getConfig, BUNDLE_ROOT, USER_DATA } from './config';

// ---------------------------------------------------------------------------
// Agent search dirs
// ---------------------------------------------------------------------------

function agentSearchDirs(): string[] {
  const dirs: string[] = [];
  const userAgents = path.join(USER_DATA, 'agents');
  const bundleAgents = path.join(BUNDLE_ROOT, 'agents');
  if (fs.existsSync(userAgents)) dirs.push(userAgents);
  if (fs.existsSync(bundleAgents) && path.resolve(bundleAgents) !== path.resolve(userAgents)) {
    dirs.push(bundleAgents);
  }
  return dirs;
}

function findManifest(name: string): Record<string, unknown> | null {
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

// ---------------------------------------------------------------------------
// Discovery
// ---------------------------------------------------------------------------

export interface AgentInfo {
  name: string;
  display_name: string;
  description: string;
  role: string;
}

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
      agents.push({
        name,
        display_name: (data.display_name as string) || name.charAt(0).toUpperCase() + name.slice(1),
        description: (data.description as string) || '',
        role: (data.role as string) || '',
      });
    }
  }

  // System-role agents first, then alphabetical
  agents.sort((a, b) => {
    const aSystem = a.role === 'system' ? 0 : 1;
    const bSystem = b.role === 'system' ? 0 : 1;
    if (aSystem !== bSystem) return aSystem - bSystem;
    return a.name.localeCompare(b.name);
  });

  return agents;
}

// ---------------------------------------------------------------------------
// Agent state (muted/enabled)
// ---------------------------------------------------------------------------

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
  fs.writeFileSync(config.AGENT_STATES_FILE, JSON.stringify(states, null, 2) + '\n');
}

export function getAgentState(agentName: string): AgentState {
  const states = loadStates();
  const state = states[agentName] as Partial<AgentState> | undefined;
  return {
    muted: state?.muted ?? false,
    enabled: state?.enabled ?? true,
  };
}

export function setAgentState(
  agentName: string,
  opts: { muted?: boolean; enabled?: boolean },
): void {
  const states = loadStates();
  const current = (states[agentName] as Record<string, unknown>) || { muted: false, enabled: true };

  if (opts.muted !== undefined) current.muted = opts.muted;
  if (opts.enabled !== undefined && opts.enabled !== current.enabled) {
    current.enabled = opts.enabled;
    toggleAgentCron(agentName, opts.enabled);
  }

  states[agentName] = current;
  saveStates(states);
}

export function setLastActiveAgent(agentName: string): void {
  const states = loadStates();
  states._last_active = agentName;
  saveStates(states);
}

export function getLastActiveAgent(): string | null {
  const states = loadStates();
  return (states._last_active as string) || null;
}

// ---------------------------------------------------------------------------
// Cron toggle
// ---------------------------------------------------------------------------

function toggleAgentCron(agentName: string, enable: boolean): void {
  const config = getConfig();
  const jobsFile = path.join(BUNDLE_ROOT, 'scripts', 'agents', agentName, 'jobs.json');
  if (!fs.existsSync(jobsFile)) {
    console.log(`  [No jobs.json for ${agentName} - skipping cron toggle]`);
    return;
  }

  const cmd = enable ? 'install' : 'uninstall';
  try {
    execSync(
      `${config.PYTHON_PATH} ${path.join(BUNDLE_ROOT, 'scripts', 'cron.py')} --agent ${agentName} ${cmd}`,
      { cwd: BUNDLE_ROOT, timeout: 10000, stdio: 'pipe' },
    );
    console.log(`  [Cron ${cmd}: ${agentName}]`);
  } catch (e) {
    console.log(`  [Cron ${cmd} failed for ${agentName}: ${e}]`);
  }
}

// ---------------------------------------------------------------------------
// Agent cycling
// ---------------------------------------------------------------------------

export function cycleAgent(direction: number, current: string): string | null {
  const agents = discoverAgents();
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

  return null;
}

// ---------------------------------------------------------------------------
// Session suspension for deferral
// ---------------------------------------------------------------------------

const _suspendedSessions = new Map<string, { cliSessionId: string; turnHistory: unknown[] }>();

export function suspendAgentSession(
  agentName: string,
  cliSessionId: string,
  turnHistory: unknown[],
): void {
  _suspendedSessions.set(agentName, { cliSessionId, turnHistory });
}

export function resumeAgentSession(
  agentName: string,
): { cliSessionId: string; turnHistory: unknown[] } | null {
  const session = _suspendedSessions.get(agentName);
  if (session) {
    _suspendedSessions.delete(agentName);
    return session;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Agent roster (for context injection)
// ---------------------------------------------------------------------------

export function getAgentRoster(exclude?: string): AgentInfo[] {
  return discoverAgents().filter((a) => {
    if (a.name === exclude) return false;
    return getAgentState(a.name).enabled;
  });
}

/**
 * Multi-agent discovery, switching, and state management.
 * Port of core/agent_manager.py.
 */

import * as fs from 'fs';
import * as path from 'path';
import { execFileSync } from 'child_process';
import { getConfig, BUNDLE_ROOT, USER_DATA } from './config';
import { createLogger } from './logger';

const log = createLogger('agent-manager');

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

  // Xan always first, then system-role agents, then alphabetical
  agents.sort((a, b) => {
    // Pin xan to position 0
    if (a.name === 'xan') return -1;
    if (b.name === 'xan') return 1;
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
  // Atomic write via tmp + rename to prevent corruption from concurrent updates
  const tmp = config.AGENT_STATES_FILE + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(states, null, 2) + '\n');
  fs.renameSync(tmp, config.AGENT_STATES_FILE);
}

export function getAgentState(agentName: string): AgentState {
  const states = loadStates();
  const state = states[agentName] as Partial<AgentState> | undefined;

  // If no explicit enabled state, check manifest for default_enabled flag
  let defaultEnabled = true;
  if (state?.enabled === undefined) {
    try {
      const { USER_DATA, BUNDLE_ROOT } = require('./config');
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
    log.debug(`No jobs.json for ${agentName} - skipping cron toggle`);
    return;
  }

  const cmd = enable ? 'install' : 'uninstall';
  // Validate agent name to prevent path traversal or injection
  if (!/^[a-zA-Z0-9_-]+$/.test(agentName)) {
    log.warn(`Invalid agent name for cron toggle: ${agentName}`);
    return;
  }
  try {
    execFileSync(
      config.PYTHON_PATH,
      [path.join(BUNDLE_ROOT, 'scripts', 'cron.py'), '--agent', agentName, cmd],
      { cwd: BUNDLE_ROOT, timeout: 10000, stdio: 'pipe' },
    );
    log.info(`Cron ${cmd}: ${agentName}`);
  } catch (e) {
    log.error(`Cron ${cmd} failed for ${agentName}: ${e}`);
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

// ---------------------------------------------------------------------------
// Agent deferral (codec-style handoff)
// ---------------------------------------------------------------------------

const DEFERRAL_FILE = path.join(USER_DATA, '.deferral_request.json');
const ANTI_LOOP_WINDOW_MS = 60_000;
const MAX_DEFERRALS_PER_WINDOW = 3;

interface DeferralRequest {
  target: string;
  context: string;
  user_question: string;
  timestamp?: number;
}

let deferralCount = 0;
let deferralWindowStart = 0;

/** Check for pending deferral requests (called periodically by main process). */
export function checkDeferralRequest(): DeferralRequest | null {
  if (!fs.existsSync(DEFERRAL_FILE)) return null;
  try {
    const data = fs.readFileSync(DEFERRAL_FILE, 'utf-8');
    const request = JSON.parse(data) as DeferralRequest;
    fs.unlinkSync(DEFERRAL_FILE);
    return request;
  } catch {
    return null;
  }
}

/** Validate deferral request against anti-loop protection. */
export function validateDeferralRequest(target: string, currentAgent: string): boolean {
  // Don't defer to self
  if (target === currentAgent) return false;

  // Anti-loop: max 3 deferrals in 60 seconds
  const now = Date.now();
  if (now - deferralWindowStart > ANTI_LOOP_WINDOW_MS) {
    deferralCount = 0;
    deferralWindowStart = now;
  }
  deferralCount++;
  if (deferralCount > MAX_DEFERRALS_PER_WINDOW) {
    log.warn('deferral suppressed - too many in 60s');
    return false;
  }

  return true;
}

/** Reset deferral counter (called after successful deferral). */
export function resetDeferralCounter(): void {
  deferralCount = 0;
  deferralWindowStart = Date.now();
}

// ---------------------------------------------------------------------------
// Ask-user file-based communication (MCP ask_user <-> Electron GUI)
// ---------------------------------------------------------------------------

export interface AskRequest {
  question: string;
  action_type: 'question' | 'confirmation' | 'permission' | 'secure_input';
  request_id: string;
  timestamp: number;
  input_type?: 'password' | 'email' | 'url' | 'number' | 'text';
  label?: string;
  destination?: string;
}

export interface AskResponse {
  request_id: string;
  response: string | boolean | null;
  timestamp: number;
  destination_failed?: boolean;
}

function askRequestPath(): string {
  const config = getConfig();
  return path.join(USER_DATA, 'agents', config.AGENT_NAME, 'data', '.ask_request.json');
}

function askResponsePath(): string {
  const config = getConfig();
  return path.join(USER_DATA, 'agents', config.AGENT_NAME, 'data', '.ask_response.json');
}

/** Check for pending ask_user requests (called periodically by main process). */
export function checkAskRequest(): AskRequest | null {
  const reqPath = askRequestPath();
  if (!fs.existsSync(reqPath)) return null;
  try {
    const data = fs.readFileSync(reqPath, 'utf-8');
    const request = JSON.parse(data) as AskRequest;
    // Don't delete - MCP is still polling. Main process handles it by showing UI.
    // Stale requests older than 3 minutes are ignored.
    if (Date.now() - request.timestamp > 180_000) {
      fs.unlinkSync(reqPath);
      return null;
    }
    return request;
  } catch {
    return null;
  }
}

/** Write the user's response for MCP to pick up. */
export function writeAskResponse(requestId: string, response: string | boolean | null, destinationFailed = false): void {
  const respPath = askResponsePath();
  const dir = path.dirname(respPath);
  fs.mkdirSync(dir, { recursive: true });

  const data: AskResponse = {
    request_id: requestId,
    response,
    timestamp: Date.now(),
    ...(destinationFailed ? { destination_failed: true } : {}),
  };

  // Atomic write via tmp + rename
  const tmp = respPath + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(data));
  fs.renameSync(tmp, respPath);

  // Clean up request file
  const reqPath = askRequestPath();
  try { fs.unlinkSync(reqPath); } catch { /* already gone */ }
  log.info(`ask_user response written for ${requestId}`);
}

/** Clean up stale ask files on startup. */
export function cleanupAskFiles(): void {
  for (const p of [askRequestPath(), askResponsePath()]) {
    try { fs.unlinkSync(p); } catch { /* not found */ }
  }
}

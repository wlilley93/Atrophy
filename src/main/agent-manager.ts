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

// ---------------------------------------------------------------------------
// Discovery
// ---------------------------------------------------------------------------

export interface AgentInfo {
  name: string;
  display_name: string;
  description: string;
  role: string;
  tier: number;
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
      const orgSection = data.org as Record<string, unknown> | undefined;
      agents.push({
        name,
        display_name: (data.display_name as string) || name.charAt(0).toUpperCase() + name.slice(1),
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

/**
 * Discover agents visible in the UI (rolodex, cycling).
 * Excludes org agents at tier 2+ (headless workers that can't address the user).
 * Non-org agents (no org section) and tier-1 org agents are included.
 */
export function discoverUiAgents(): AgentInfo[] {
  return discoverAgents().filter((a) => {
    const manifest = findManifest(a.name) || {};
    const org = manifest.org as Record<string, unknown> | undefined;
    if (!org) return true; // non-org agent - always visible
    return (org.tier as number) <= 1;
  });
}

// ---------------------------------------------------------------------------
// Sync bundled prompts to user directory
// ---------------------------------------------------------------------------

/**
 * For each agent that exists in the bundle, copy any prompt files that are
 * missing from the user's ~/.atrophy/agents/<name>/prompts/ directory.
 * Existing user prompts are never overwritten - bundle files are defaults only.
 */
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

// NOTE: deferral counter intentionally not resettable - the 60s window
// handles natural expiry. Resetting after each deferral defeated the
// anti-loop protection (counter never accumulated past 1).

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

// ---------------------------------------------------------------------------
// Agent deletion (preserves memory.db)
// ---------------------------------------------------------------------------

/**
 * Delete an agent from the user data directory.
 *
 * Backs up memory.db to memory.db.preserved, removes all other files
 * and directories, then restores the memory backup. This preserves the
 * agent's conversation history even after deletion.
 *
 * @throws If agent directory does not exist.
 */
export function deleteAgent(name: string): void {
  const agentDir = path.join(USER_DATA, 'agents', name);
  if (!fs.existsSync(agentDir)) {
    throw new Error(`Agent directory for "${name}" not found`);
  }

  const dbPath = path.join(agentDir, 'memory.db');
  // Back up OUTSIDE agentDir so rmSync doesn't destroy it
  const backupPath = path.join(USER_DATA, 'agents', `${name}.memory.db.preserved`);

  // Back up memory.db if it exists
  let hadDb = false;
  if (fs.existsSync(dbPath)) {
    try {
      fs.copyFileSync(dbPath, backupPath);
      hadDb = true;
    } catch (e) {
      log.warn(`deleteAgent: failed to backup memory.db for "${name}": ${e}`);
    }
  }

  // Remove entire agent directory
  try {
    fs.rmSync(agentDir, { recursive: true, force: true });
  } catch (e) {
    throw new Error(`Failed to remove agent directory for "${name}": ${e}`);
  }

  // Restore memory backup into a fresh data dir
  if (hadDb) {
    try {
      const dataDir = path.join(agentDir, 'data');
      fs.mkdirSync(dataDir, { recursive: true });
      fs.renameSync(backupPath, path.join(dataDir, 'memory.db'));
    } catch (e) {
      log.warn(`deleteAgent: failed to restore memory backup for "${name}": ${e}`);
    }
  }

  log.info(`Deleted agent "${name}" (memory preserved: ${hadDb})`);
}

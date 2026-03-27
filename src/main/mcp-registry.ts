/**
 * MCP server registry - manages available MCP servers and builds
 * per-agent configurations for Claude CLI.
 *
 * Discovers bundled servers in BUNDLE_ROOT/mcp/, user-installed
 * servers in USER_DATA/mcp/custom/, and generates the config.json
 * files that Claude CLI reads via --mcp-config.
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { execFileSync } from 'child_process';
import { getConfig, BUNDLE_ROOT, USER_DATA, saveAgentConfig, isValidAgentName } from './config';
import { createLogger } from './logger';

const log = createLogger('mcp-registry');

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * MCP server definition in the registry.
 */
export interface McpServerDefinition {
  name: string;
  description: string;
  command: string;
  args: string[];
  env?: Record<string, string>;
  capabilities?: string[];
  bundled: boolean;
  requiresAuth?: string[];
}

/**
 * Per-agent MCP configuration in the agent manifest.
 */
export interface AgentMcpConfig {
  include: string[];
  exclude: string[];
  custom: Record<string, {
    command: string;
    args: string[];
    env?: Record<string, string>;
    description?: string;
  }>;
}

/**
 * Tool definition for scaffolding new MCP servers.
 */
export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Bundled server metadata
// ---------------------------------------------------------------------------

/** Static metadata for the bundled MCP servers (Python scripts in mcp/). */
const BUNDLED_SERVER_META: Record<string, {
  description: string;
  capabilities: string[];
  requiresAuth?: string[];
}> = {
  memory_server: {
    description: 'Memory and recall - SQLite-backed conversation history, observations, threads, bookmarks, notes',
    capabilities: ['memory', 'search', 'write', 'recall', 'notes', 'threads'],
  },
  google_server: {
    description: 'Google Workspace - Gmail, Calendar, Drive, Sheets, Docs, YouTube via gws CLI',
    capabilities: ['email', 'calendar', 'drive', 'search', 'write'],
    requiresAuth: ['GOOGLE_CONFIGURED'],
  },
  shell_server: {
    description: 'Sandboxed shell access - scoped commands with allowlist, path restrictions, timeout',
    capabilities: ['shell', 'exec', 'filesystem'],
  },
  github_server: {
    description: 'GitHub operations - repos, issues, PRs, search via gh CLI',
    capabilities: ['github', 'search', 'write'],
  },
  worldmonitor_server: {
    description: 'WorldMonitor intelligence API - news, events, geopolitical data with delta detection',
    capabilities: ['news', 'search', 'intelligence'],
  },
  puppeteer_proxy: {
    description: 'Web browsing proxy - puppeteer with injection detection and content sandboxing',
    capabilities: ['web', 'browse', 'screenshot'],
  },
  defence_sources_server: {
    description: 'Defence primary sources - official feeds, UK/EU procurement, specialist press',
    capabilities: ['feeds', 'procurement', 'intelligence', 'search'],
  },
};

/**
 * External MCP servers that ship with Atrophy but depend on tools installed
 * on the host (uvx, npx). Registered during discover() if the command is
 * found on PATH. Agents include/exclude these the same way as bundled servers.
 *
 * Keys are the registry names (what agents use in mcp.include).
 */
export const EXTERNAL_SERVER_META: Record<string, {
  description: string;
  capabilities: string[];
  /** Candidates to resolve the command binary, tried in order. */
  commandCandidates: string[];
  args: string[];
  requiresAuth?: string[];
  /** Env var name in ~/.atrophy/.env whose presence is required. */
  requiresEnvKey?: string;
}> = {
  elevenlabs: {
    description: 'ElevenLabs - text-to-speech, voice cloning, audio processing, transcription, sound effects',
    capabilities: ['tts', 'stt', 'voice', 'audio', 'clone', 'sound_effects'],
    commandCandidates: ['uvx', path.join(os.homedir(), '.local/bin/uvx'), '/opt/homebrew/bin/uvx'],
    args: ['elevenlabs-mcp'],
    requiresEnvKey: 'ELEVENLABS_API_KEY',
  },
  fal: {
    description: 'Fal.ai - image generation, video, audio, and multimodal AI models',
    capabilities: ['image', 'video', 'audio', 'generation'],
    commandCandidates: ['npx', '/opt/homebrew/bin/npx', '/usr/local/bin/npx'],
    args: ['-y', 'fal-ai-mcp-server@latest'],
    requiresEnvKey: 'FAL_KEY',
  },
};

// ---------------------------------------------------------------------------
// Python path detection (matches inference.ts logic)
// ---------------------------------------------------------------------------

/**
 * Find a working Python 3 binary. Checks PYTHON_PATH env, then
 * common locations, then falls back to bare 'python3'.
 */
function findPythonPath(): string {
  if (process.env.PYTHON_PATH) {
    const p = process.env.PYTHON_PATH;
    if (/^[a-zA-Z0-9_.\/~-]+$/.test(p)) return p;
    log.warn('PYTHON_PATH contains invalid characters, ignoring');
  }

  const home = process.env.HOME || os.homedir();
  const candidates = [
    'python3',
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    `${home}/.pyenv/shims/python3`,
  ];

  try {
    const pyenvDir = `${home}/.pyenv/versions`;
    const { readdirSync, statSync } = require('fs');
    const versions = readdirSync(pyenvDir)
      .filter((v: string) => statSync(`${pyenvDir}/${v}`).isDirectory())
      .sort()
      .reverse();
    for (const v of versions) {
      candidates.push(`${pyenvDir}/${v}/bin/python3`);
    }
  } catch {
    // pyenv not installed
  }

  for (const c of candidates) {
    try {
      execFileSync(c, ['--version'], { stdio: 'pipe' });
      return c;
    } catch {
      continue;
    }
  }
  return 'python3';
}

// ---------------------------------------------------------------------------
// Agent manifest helpers
// ---------------------------------------------------------------------------

/**
 * Read an agent's manifest from user data or bundle.
 * Returns the parsed JSON object, or empty object on failure.
 */
export function readAgentManifest(agentName: string): Record<string, unknown> {
  for (const base of [
    path.join(USER_DATA, 'agents', agentName),
    path.join(BUNDLE_ROOT, 'agents', agentName),
  ]) {
    const mpath = path.join(base, 'data', 'agent.json');
    if (fs.existsSync(mpath)) {
      try {
        return JSON.parse(fs.readFileSync(mpath, 'utf-8'));
      } catch { /* skip */ }
    }
  }
  return {};
}

/**
 * Extract the mcp config section from an agent manifest,
 * providing sensible defaults.
 */
export function getAgentMcpSection(agentName: string): AgentMcpConfig {
  const manifest = readAgentManifest(agentName);
  const mcp = (manifest.mcp as Partial<AgentMcpConfig>) || {};
  return {
    include: Array.isArray(mcp.include) ? mcp.include : [],
    exclude: Array.isArray(mcp.exclude) ? mcp.exclude : [],
    custom: (mcp.custom && typeof mcp.custom === 'object') ? mcp.custom as AgentMcpConfig['custom'] : {},
  };
}

// ---------------------------------------------------------------------------
// McpRegistry
// ---------------------------------------------------------------------------

/**
 * Registry that manages available MCP servers and builds per-agent
 * configurations for the Claude CLI.
 */
export class McpRegistry {
  private servers: Map<string, McpServerDefinition> = new Map();
  private _mcpDirty: Map<string, boolean> = new Map();
  private _lastBuildHash: Map<string, string> = new Map();
  private _pythonPath: string | null = null;

  /**
   * Clear cached config paths and dirty flags.
   * Called when resetting MCP config (e.g. on agent switch).
   */
  clearCache(): void {
    this._mcpDirty.clear();
    this._lastBuildHash.clear();
    this._pythonPath = null;
  }

  /**
   * Lazily resolve and cache the Python path.
   */
  private getPythonPath(): string {
    if (!this._pythonPath) {
      this._pythonPath = findPythonPath();
    }
    return this._pythonPath;
  }

  /**
   * Try a list of command candidates and return the first one that exists.
   * Checks absolute paths with fs.existsSync, bare names with `which`.
   */
  private resolveCommand(candidates: string[]): string | null {
    for (const cmd of candidates) {
      if (cmd.startsWith('/')) {
        if (fs.existsSync(cmd)) return cmd;
      } else {
        try {
          const resolved = execFileSync('which', [cmd], { stdio: 'pipe' }).toString().trim();
          if (resolved) return resolved;
        } catch { continue; }
      }
    }
    return null;
  }

  /**
   * Derive a server name from a Python filename.
   * e.g. "memory_server.py" -> "memory", "puppeteer_proxy.py" -> "puppeteer"
   */
  private serverNameFromFile(filename: string): string {
    const base = path.basename(filename, '.py');
    // Strip common suffixes
    return base
      .replace(/_server$/, '')
      .replace(/_proxy$/, '');
  }

  // -------------------------------------------------------------------------
  // Discovery
  // -------------------------------------------------------------------------

  /**
   * Scan for available MCP servers in bundled and user-installed locations.
   * Populates the internal registry with McpServerDefinition entries.
   */
  discover(): void {
    log.info('Discovering MCP servers...');
    this.servers.clear();

    // 1. Bundled servers in BUNDLE_ROOT/mcp/
    const bundledDir = path.join(BUNDLE_ROOT, 'mcp');
    if (fs.existsSync(bundledDir)) {
      const pyFiles = fs.readdirSync(bundledDir).filter(f => f.endsWith('.py'));
      for (const file of pyFiles) {
        const name = this.serverNameFromFile(file);
        const meta = BUNDLED_SERVER_META[path.basename(file, '.py')] || {
          description: `Bundled MCP server: ${name}`,
          capabilities: [],
        };

        const def: McpServerDefinition = {
          name,
          description: meta.description,
          command: this.getPythonPath(),
          args: [path.join(bundledDir, file)],
          capabilities: meta.capabilities,
          bundled: true,
          requiresAuth: meta.requiresAuth,
        };

        this.servers.set(name, def);
        log.debug(`Registered bundled server: ${name} (${file})`);
      }
    } else {
      log.warn(`Bundled MCP directory not found: ${bundledDir}`);
    }

    // 2. External servers (ship with Atrophy, require host tools)
    for (const [name, meta] of Object.entries(EXTERNAL_SERVER_META)) {
      const resolvedCmd = this.resolveCommand(meta.commandCandidates);
      if (!resolvedCmd) {
        log.info(`External server "${name}" skipped - command not found (tried: ${meta.commandCandidates.join(', ')})`);
        continue;
      }

      // Check for required env key (loaded from ~/.atrophy/.env at startup)
      if (meta.requiresEnvKey && !process.env[meta.requiresEnvKey]) {
        log.info(`External server "${name}" skipped - ${meta.requiresEnvKey} not set`);
        continue;
      }

      const def: McpServerDefinition = {
        name,
        description: meta.description,
        command: resolvedCmd,
        args: [...meta.args],
        capabilities: meta.capabilities,
        bundled: true, // ships with Atrophy - agents can include/exclude
        requiresAuth: meta.requiresAuth,
      };

      this.servers.set(name, def);
      log.info(`Registered external server: ${name} (${resolvedCmd} ${meta.args.join(' ')})`);
    }

    // 3. User-installed servers in USER_DATA/mcp/custom/
    const customDir = path.join(USER_DATA, 'mcp', 'custom');
    if (fs.existsSync(customDir)) {
      const entries = fs.readdirSync(customDir, { withFileTypes: true });
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        const serverDir = path.join(customDir, entry.name);
        const serverPy = path.join(serverDir, 'server.py');
        const metaJson = path.join(serverDir, 'meta.json');

        if (!fs.existsSync(serverPy)) continue;

        // Read optional metadata
        let meta: {
          description?: string;
          capabilities?: string[];
          requiresAuth?: string[];
          env?: Record<string, string>;
        } = {};
        if (fs.existsSync(metaJson)) {
          try {
            meta = JSON.parse(fs.readFileSync(metaJson, 'utf-8'));
          } catch (e) {
            log.warn(`Failed to parse ${metaJson}: ${e}`);
          }
        }

        const def: McpServerDefinition = {
          name: entry.name,
          description: meta.description || `Custom MCP server: ${entry.name}`,
          command: this.getPythonPath(),
          args: [serverPy],
          env: meta.env,
          capabilities: meta.capabilities || [],
          bundled: false,
          requiresAuth: meta.requiresAuth,
        };

        this.servers.set(entry.name, def);
        log.debug(`Registered custom server: ${entry.name}`);
      }
    }

    log.info(`Discovered ${this.servers.size} MCP servers`);
  }

  // -------------------------------------------------------------------------
  // Registry queries
  // -------------------------------------------------------------------------

  /**
   * Return all registered server definitions.
   */
  getRegistry(): McpServerDefinition[] {
    return Array.from(this.servers.values());
  }

  /**
   * Get a single server definition by name, or undefined if not found.
   */
  getServer(name: string): McpServerDefinition | undefined {
    return this.servers.get(name);
  }

  /**
   * Return servers that are active for a given agent.
   *
   * Resolution logic:
   *   - If agent manifest has mcp.include, use only those servers
   *   - If no include list, default to all registered servers
   *   - Apply mcp.exclude to remove blocked servers
   *   - Add custom servers from the manifest
   */
  getForAgent(agentName: string): McpServerDefinition[] {
    const mcpConfig = getAgentMcpSection(agentName);
    const excludeSet = new Set(mcpConfig.exclude);

    let active: McpServerDefinition[];

    if (mcpConfig.include.length > 0) {
      // Only include explicitly listed servers
      active = mcpConfig.include
        .filter(name => !excludeSet.has(name))
        .map(name => this.servers.get(name))
        .filter((s): s is McpServerDefinition => s !== undefined);
    } else {
      // Default: all registered servers minus excluded
      active = Array.from(this.servers.values())
        .filter(s => !excludeSet.has(s.name));
    }

    // Append custom servers as definitions
    for (const [name, custom] of Object.entries(mcpConfig.custom)) {
      if (excludeSet.has(name)) continue;
      active.push({
        name,
        description: custom.description || `Custom server: ${name}`,
        command: custom.command,
        args: custom.args,
        env: custom.env,
        bundled: false,
      });
    }

    return active;
  }

  // -------------------------------------------------------------------------
  // Agent MCP management
  // -------------------------------------------------------------------------

  /**
   * Add a server to an agent's mcp.include list in the manifest.
   * Sets the dirty flag so the next build picks up the change.
   */
  activateForAgent(agentName: string, serverName: string): void {
    if (!isValidAgentName(agentName)) {
      log.warn(`Invalid agent name: ${agentName}`);
      return;
    }
    if (!this.servers.has(serverName)) {
      log.warn(`Unknown server: ${serverName}`);
      return;
    }

    const mcpConfig = getAgentMcpSection(agentName);

    // Add to include if not already present
    if (!mcpConfig.include.includes(serverName)) {
      mcpConfig.include.push(serverName);
    }

    // Remove from exclude if present
    mcpConfig.exclude = mcpConfig.exclude.filter(n => n !== serverName);

    // Save back to agent manifest
    saveAgentConfig(agentName, { mcp: mcpConfig });
    this._mcpDirty.set(agentName, true);
    log.info(`Activated server "${serverName}" for agent "${agentName}"`);
  }

  /**
   * Remove a server from an agent's include list and add to exclude.
   * Sets the dirty flag.
   */
  deactivateForAgent(agentName: string, serverName: string): void {
    if (!isValidAgentName(agentName)) {
      log.warn(`Invalid agent name: ${agentName}`);
      return;
    }

    const mcpConfig = getAgentMcpSection(agentName);

    // Remove from include
    mcpConfig.include = mcpConfig.include.filter(n => n !== serverName);

    // Add to exclude if not already present
    if (!mcpConfig.exclude.includes(serverName)) {
      mcpConfig.exclude.push(serverName);
    }

    // Save back to agent manifest
    saveAgentConfig(agentName, { mcp: mcpConfig });
    this._mcpDirty.set(agentName, true);
    log.info(`Deactivated server "${serverName}" for agent "${agentName}"`);
  }

  // -------------------------------------------------------------------------
  // Config generation
  // -------------------------------------------------------------------------

  /**
   * Build the MCP config.json for Claude CLI for a specific agent.
   *
   * Reads the agent manifest's mcp section, filters the registry,
   * resolves environment variables per server, and writes the config
   * to USER_DATA/mcp/<agentName>.config.json.
   *
   * Returns the absolute path to the generated config file.
   */
  buildConfigForAgent(agentName: string): string {
    const pythonPath = this.getPythonPath();
    const activeServers = this.getForAgent(agentName);
    const mcpConfig = getAgentMcpSection(agentName);

    const servers: Record<string, unknown> = {};

    for (const server of activeServers) {
      // Resolve command - use Python path for .py scripts
      let command = server.command;
      if (server.args.length > 0 && server.args[0].endsWith('.py')) {
        command = pythonPath;
      }

      // Build env vars - for bundled servers, apply built-in env logic.
      // For custom servers (bundled=false), use their env directly to avoid
      // the switch statement injecting built-in server env vars into custom servers
      // that happen to share a name with a built-in.
      const env = server.bundled !== false
        ? this.buildServerEnv(server.name, agentName, server.env)
        : { ...(server.env || {}) };

      const entry: Record<string, unknown> = {
        command,
        args: [...server.args],
      };

      if (env && Object.keys(env).length > 0) {
        entry.env = env;
      }

      servers[server.name] = entry;
    }

    // Add custom servers from agent manifest
    for (const [name, custom] of Object.entries(mcpConfig.custom)) {
      if (name in servers) continue; // already handled by getForAgent
      servers[name] = {
        command: custom.command,
        args: custom.args,
        ...(custom.env && Object.keys(custom.env).length > 0 ? { env: custom.env } : {}),
      };
    }

    // Write config file
    const configPath = path.join(USER_DATA, 'mcp', `${agentName}.config.json`);
    const configContent = { mcpServers: servers };

    fs.mkdirSync(path.dirname(configPath), { recursive: true });

    // Atomic write: tmp file + rename
    const tmpPath = configPath + '.tmp';
    fs.writeFileSync(tmpPath, JSON.stringify(configContent, null, 2), { mode: 0o600 });
    fs.renameSync(tmpPath, configPath);

    // Clear dirty flag and store hash for change detection
    this._mcpDirty.set(agentName, false);
    this._lastBuildHash.set(agentName, JSON.stringify(configContent));

    log.info(`Built MCP config for "${agentName}": ${Object.keys(servers).length} servers -> ${configPath}`);
    return configPath;
  }

  /**
   * Build a restricted MCP config for federation inference.
   * Trust tiers control which servers are available:
   *   - chat: no MCP servers (text response only)
   *   - query: memory (read-only)
   *   - delegate: memory (read/write)
   * Shell, filesystem, GitHub, puppeteer are NEVER included.
   */
  buildFederationConfig(agentName: string, trustTier: 'chat' | 'query' | 'delegate'): string {
    const BLOCKED_SERVERS = new Set([
      'shell', 'github', 'puppeteer', 'fal', 'elevenlabs',
      'worldmonitor', 'defence_sources',
    ]);

    const configPath = path.join(USER_DATA, 'mcp', `${agentName}.federation.config.json`);
    let servers: Record<string, unknown> = {};

    if (trustTier === 'chat') {
      servers = {};
    } else {
      const pythonPath = this.getPythonPath();
      const allServers = this.getForAgent(agentName);
      for (const server of allServers) {
        if (BLOCKED_SERVERS.has(server.name)) continue;
        if (trustTier === 'query' && server.name !== 'memory') continue;
        if (trustTier === 'delegate' && server.name !== 'memory') continue;

        let command = server.command;
        if (server.args.length > 0 && server.args[0].endsWith('.py')) {
          command = pythonPath;
        }
        const env = server.bundled !== false
          ? this.buildServerEnv(server.name, agentName, server.env)
          : { ...(server.env || {}) };

        const entry: Record<string, unknown> = { command, args: [...server.args] };
        if (env && Object.keys(env).length > 0) entry.env = env;
        servers[server.name] = entry;
      }
    }

    const configContent = { mcpServers: servers };
    fs.mkdirSync(path.dirname(configPath), { recursive: true });
    const tmp = configPath + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(configContent, null, 2), { mode: 0o600 });
    fs.renameSync(tmp, configPath);

    log.info(`Built federation MCP config for "${agentName}" (tier=${trustTier}): ${Object.keys(servers).length} servers`);
    return configPath;
  }

  /**
   * Build environment variables for a specific server.
   * Replicates the per-server env logic from inference.ts getMcpConfigPath().
   */
  private buildServerEnv(
    serverName: string,
    agentName: string,
    baseEnv?: Record<string, string>,
  ): Record<string, string> {
    const config = getConfig();
    const env: Record<string, string> = { ...(baseEnv || {}) };

    switch (serverName) {
      case 'memory': {
        env.COMPANION_DB = config.DB_PATH;
        env.OBSIDIAN_VAULT = config.OBSIDIAN_VAULT;
        env.OBSIDIAN_AGENT_DIR = config.OBSIDIAN_AGENT_DIR;
        env.OBSIDIAN_AGENT_NOTES = config.OBSIDIAN_AGENT_NOTES;
        env.TELEGRAM_BOT_TOKEN = config.TELEGRAM_BOT_TOKEN || '';
        env.TELEGRAM_CHAT_ID = config.TELEGRAM_CHAT_ID || '';
        env.AGENT = agentName;

        // Org DB resolution - if agent belongs to a non-personal org,
        // pass the shared org database path to the memory server
        const manifest = readAgentManifest(agentName);
        const orgSlug = (manifest.org as { slug?: string } | undefined)?.slug;
        if (orgSlug && orgSlug !== 'personal' && orgSlug !== 'system') {
          const orgDbPath = path.join(USER_DATA, 'orgs', orgSlug, 'memory.db');
          if (fs.existsSync(orgDbPath)) {
            env.ORG_DB = orgDbPath;
            env.ORG_SLUG = orgSlug;
          }
        }
        break;
      }

      case 'puppeteer':
        env.PUPPETEER_LAUNCH_OPTIONS = JSON.stringify({ headless: true });
        break;

      case 'shell':
        env.SHELL_WORKING_DIR = os.homedir();
        env.SHELL_TIMEOUT = '30';
        env.SHELL_MAX_OUTPUT = '32000';
        break;

      case 'github':
        // github_server.py reads GH_BIN and GH_WORKING_DIR from env but
        // has sensible defaults - no env overrides needed
        break;

      case 'google':
        // google_server.py uses gws CLI auth - no env overrides needed
        break;

      case 'worldmonitor':
        env.WORLDMONITOR_CACHE_DB = path.join(os.homedir(), '.atrophy', 'worldmonitor_cache.db');
        env.WORLDMONITOR_BASE_URL = 'https://api.worldmonitor.app';
        env.WORLDMONITOR_API_KEY = process.env.WORLDMONITOR_API_KEY || '';
        break;

      case 'elevenlabs':
        env.ELEVENLABS_API_KEY = process.env.ELEVENLABS_API_KEY || config.ELEVENLABS_API_KEY || '';
        env.ELEVENLABS_MCP_BASE_PATH = path.join(USER_DATA, 'tts_output');
        break;

      case 'fal':
        env.FAL_KEY = process.env.FAL_KEY || '';
        break;

      default:
        // Custom/unknown servers - use whatever env was provided
        break;
    }

    return env;
  }

  // -------------------------------------------------------------------------
  // Change detection
  // -------------------------------------------------------------------------

  /**
   * Check if the agent's MCP config has changed since the last build.
   * Returns true if activateForAgent/deactivateForAgent was called
   * since the last buildConfigForAgent, or if no build has been done yet.
   */
  needsRestart(agentName: string): boolean {
    // Explicit dirty flag from activate/deactivate calls
    if (this._mcpDirty.get(agentName)) return true;

    // No previous build means we should build
    if (!this._lastBuildHash.has(agentName)) return true;

    // Check if the current config would differ from the last build
    const activeServers = this.getForAgent(agentName);
    const lastHash = this._lastBuildHash.get(agentName);
    if (!lastHash) return true;

    try {
      const lastConfig = JSON.parse(lastHash);
      const lastServerNames = Object.keys(lastConfig.mcpServers || {}).sort();
      const currentServerNames = activeServers.map(s => s.name).sort();
      return JSON.stringify(lastServerNames) !== JSON.stringify(currentServerNames);
    } catch {
      return true;
    }
  }

  // -------------------------------------------------------------------------
  // Server scaffolding
  // -------------------------------------------------------------------------

  /**
   * Generate a new Python MCP server from a template.
   *
   * Creates the server at USER_DATA/mcp/custom/<name>/server.py with
   * tool stubs based on the provided definitions, and a meta.json for
   * registry metadata.
   *
   * Returns the resulting McpServerDefinition.
   */
  scaffoldServer(
    name: string,
    description: string,
    tools: ToolDefinition[],
  ): McpServerDefinition {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(name)) {
      throw new Error(`Invalid server name: "${name}" - use alphanumeric, hyphens, underscores only`);
    }

    const serverDir = path.join(USER_DATA, 'mcp', 'custom', name);
    const serverPy = path.join(serverDir, 'server.py');
    const metaJson = path.join(serverDir, 'meta.json');

    fs.mkdirSync(serverDir, { recursive: true });

    // Generate tool handler stubs
    const toolHandlers = tools.map(tool => `
def handle_${tool.name}(params):
    """${tool.description}"""
    # TODO: implement ${tool.name}
    return {"status": "ok", "message": "${tool.name} not yet implemented"}
`).join('\n');

    // Generate tools list for the server
    const toolsList = tools.map(tool => {
      const schema = JSON.stringify(tool.inputSchema, null, 8)
        .split('\n')
        .map((line, i) => i === 0 ? line : '        ' + line)
        .join('\n');
      return `    {
        "name": "${tool.name}",
        "description": ${JSON.stringify(tool.description)},
        "inputSchema": ${schema},
    }`;
    }).join(',\n');

    // Generate dispatch cases
    const dispatchCases = tools.map(tool =>
      `        elif name == "${tool.name}":\n            result = handle_${tool.name}(params)`,
    ).join('\n');

    // Write server.py
    const serverContent = `#!/usr/bin/env python3
"""${description}

Auto-generated MCP server. Protocol: JSON-RPC 2.0 over stdio.
"""
from __future__ import annotations

import json
import sys


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------
${toolHandlers}

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
${toolsList}
]


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 server
# ---------------------------------------------------------------------------

def send_response(id, result):
    response = {"jsonrpc": "2.0", "id": id, "result": result}
    msg = json.dumps(response)
    sys.stdout.write(f"Content-Length: {len(msg)}\\r\\n\\r\\n{msg}")
    sys.stdout.flush()


def send_error(id, code, message):
    response = {
        "jsonrpc": "2.0",
        "id": id,
        "error": {"code": code, "message": message},
    }
    msg = json.dumps(response)
    sys.stdout.write(f"Content-Length: {len(msg)}\\r\\n\\r\\n{msg}")
    sys.stdout.flush()


def handle_request(request):
    method = request.get("method", "")
    id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        send_response(id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "${name}", "version": "1.0.0"},
        })
    elif method == "tools/list":
        send_response(id, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        if False:
            pass
${dispatchCases}
        else:
            send_error(id, -32601, f"Unknown tool: {name}")
            return
        send_response(id, {
            "content": [{"type": "text", "text": json.dumps(result)}],
        })
    elif method == "notifications/initialized":
        pass  # no response needed
    else:
        if id is not None:
            send_error(id, -32601, f"Unknown method: {method}")


def main():
    buf = ""
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        buf += line
        # Parse Content-Length header
        if buf.startswith("Content-Length:"):
            header_end = buf.find("\\r\\n\\r\\n")
            if header_end == -1:
                continue
            length_str = buf[len("Content-Length:"):header_end].strip()
            length = int(length_str)
            body_start = header_end + 4
            remaining = buf[body_start:]
            while len(remaining) < length:
                remaining += sys.stdin.read(length - len(remaining))
            request = json.loads(remaining[:length])
            buf = remaining[length:]
            handle_request(request)


if __name__ == "__main__":
    main()
`;

    fs.writeFileSync(serverPy, serverContent, { mode: 0o755 });

    // Write meta.json
    const meta = {
      description,
      capabilities: tools.map(t => t.name),
    };
    fs.writeFileSync(metaJson, JSON.stringify(meta, null, 2));

    // Register in the live registry
    const def: McpServerDefinition = {
      name,
      description,
      command: this.getPythonPath(),
      args: [serverPy],
      capabilities: tools.map(t => t.name),
      bundled: false,
    };
    this.servers.set(name, def);

    log.info(`Scaffolded new MCP server: ${name} (${tools.length} tools) at ${serverDir}`);
    return def;
  }

  // -------------------------------------------------------------------------
  // Switchboard integration
  // -------------------------------------------------------------------------

  /**
   * Register all MCP servers with the switchboard service directory
   * as "mcp:<name>" addresses.
   *
   * This is a lazy import to avoid circular dependencies - the switchboard
   * module may import other modules that depend on config.
   */
  registerWithSwitchboard(sb?: {
    register: (
      address: string,
      handler: (envelope: unknown) => Promise<void>,
      meta?: { type?: 'channel' | 'agent' | 'system' | 'webhook' | 'mcp'; description?: string; capabilities?: string[] },
    ) => void;
  }): void {
    // Accept switchboard as a parameter to avoid dynamic require() that breaks
    // when the bundler (Vite) compiles everything into a single app.js.
    // The dynamic require("./channels/switchboard") produced a "Cannot find
    // module" error in packaged builds because no separate file exists.
    let switchboard = sb;

    if (!switchboard) {
      try {
        // Fallback for dev/source runs where modules are separate files
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        const sbModule = require('./channels/switchboard');
        switchboard = sbModule.switchboard;
      } catch {
        log.warn('Switchboard not available - skipping MCP service registration');
        return;
      }
    }

    if (!switchboard) {
      log.warn('Switchboard not available - skipping MCP service registration');
      return;
    }

    for (const server of Array.from(this.servers.values())) {
      const address = `mcp:${server.name}`;
      switchboard.register(
        address,
        async () => {
          // MCP servers communicate via stdio with Claude CLI, not through
          // the switchboard message routing. This registration is purely
          // for service discovery - agents can query the directory to see
          // which MCP tools are available.
          log.debug(`Switchboard message to ${address} (service discovery only)`);
        },
        {
          type: 'mcp',
          description: server.description,
          capabilities: server.capabilities,
        },
      );
    }

    log.info(`Registered ${this.servers.size} MCP servers with switchboard`);
  }
}

// ---------------------------------------------------------------------------
// Singleton
// ---------------------------------------------------------------------------

export const mcpRegistry = new McpRegistry();

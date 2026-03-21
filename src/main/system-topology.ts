/**
 * Pure data layer for the system map overlay.
 * Assembles topology from agent manifests, MCP registry, and server metadata.
 * Used by IPC handlers - no Electron imports needed.
 */

import { discoverAgents } from './agent-manager';
import {
  mcpRegistry,
  readAgentManifest,
  getAgentMcpSection,
  EXTERNAL_SERVER_META,
} from './mcp-registry';
import { isValidAgentName, saveAgentConfig } from './config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TopologyAgent {
  name: string;
  displayName: string;
  role: string;
  mcp: {
    include: string[];
    exclude: string[];
    active: string[];
  };
  channels: Record<string, unknown>;
  jobs: Record<string, unknown>;
  router: Record<string, unknown>;
}

export interface TopologyServer {
  name: string;
  description: string;
  capabilities: string[];
  bundled: boolean;
  available: boolean;
  missingKey: boolean;
  missingCommand: boolean;
}

export interface Topology {
  agents: TopologyAgent[];
  servers: TopologyServer[];
}

export interface ToggleResult {
  success: boolean;
  error?: string;
  needsRestart?: boolean;
  active?: string[];
}

// ---------------------------------------------------------------------------
// Build topology
// ---------------------------------------------------------------------------

export function buildTopology(): Topology {
  const agentInfos = discoverAgents();

  const agents: TopologyAgent[] = agentInfos.map(info => {
    const manifest = readAgentManifest(info.name);
    const mcpSection = getAgentMcpSection(info.name);
    return {
      name: info.name,
      displayName: info.display_name || info.name,
      role: info.role || '',
      mcp: {
        include: mcpSection.include,
        exclude: mcpSection.exclude,
        active: mcpRegistry.getForAgent(info.name).map(s => s.name),
      },
      channels: (manifest.channels || {}) as Record<string, unknown>,
      jobs: (manifest.jobs || {}) as Record<string, unknown>,
      router: (manifest.router || {}) as Record<string, unknown>,
    };
  });

  // All registered (available) servers
  const registeredServers = mcpRegistry.getRegistry();
  const servers: TopologyServer[] = registeredServers.map(s => ({
    name: s.name,
    description: s.description,
    capabilities: s.capabilities || [],
    bundled: s.bundled,
    available: true,
    missingKey: false,
    missingCommand: false,
  }));

  // Add unavailable external servers that discover() skipped
  for (const [name, meta] of Object.entries(EXTERNAL_SERVER_META)) {
    if (!registeredServers.some(s => s.name === name)) {
      const keyMissing = !!(meta.requiresEnvKey && !process.env[meta.requiresEnvKey]);
      servers.push({
        name,
        description: meta.description,
        capabilities: meta.capabilities,
        bundled: true,
        available: false,
        missingKey: keyMissing,
        missingCommand: !keyMissing, // if key isn't the problem, command is
      });
    }
  }

  return { agents, servers };
}

// ---------------------------------------------------------------------------
// Toggle connection
// ---------------------------------------------------------------------------

export function handleToggleConnection(
  agentName: string,
  serverName: string,
  enabled: boolean,
): ToggleResult {
  if (!isValidAgentName(agentName)) {
    return { success: false, error: `Invalid agent: ${agentName}` };
  }

  if (enabled && !mcpRegistry.getServer(serverName)) {
    return { success: false, error: `Unknown server: ${serverName}` };
  }

  // If agent has empty include list (meaning "all"), populate it explicitly
  // before toggling so the UI semantics are clear
  const mcpSection = getAgentMcpSection(agentName);
  if (mcpSection.include.length === 0) {
    const currentActive = mcpRegistry.getForAgent(agentName).map(s => s.name);
    mcpSection.include = currentActive;
    saveAgentConfig(agentName, { mcp: mcpSection });
  }

  if (enabled) {
    mcpRegistry.activateForAgent(agentName, serverName);
  } else {
    mcpRegistry.deactivateForAgent(agentName, serverName);
  }

  // Rebuild the config.json that Claude CLI reads via --mcp-config
  mcpRegistry.buildConfigForAgent(agentName);

  return {
    success: true,
    needsRestart: mcpRegistry.needsRestart(agentName),
    active: mcpRegistry.getForAgent(agentName).map(s => s.name),
  };
}

# src/main/mcp-registry.ts - MCP Server Registry

**Dependencies:** `fs`, `os`, `path`, `child_process`, `./config`, `./logger`  
**Purpose:** Manage MCP server discovery, registration, and per-agent configuration for Claude CLI

## Overview

This module manages the MCP (Model Context Protocol) server registry. It discovers bundled servers, external servers (installed on host), and user custom servers. It builds per-agent configurations that Claude CLI reads via `--mcp-config`.

## Types

### McpServerDefinition

```typescript
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
```

**Fields:**
- `name`: Server identifier (e.g., `memory`, `google`)
- `description`: Human-readable description
- `command`: Binary to execute (e.g., `python3`, `uvx`, `npx`)
- `args`: Command-line arguments
- `env`: Environment variables to pass
- `capabilities`: What the server can do
- `bundled`: Whether server is bundled with app
- `requiresAuth`: List of env vars that must be set

### AgentMcpConfig

```typescript
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
```

**Fields:**
- `include`: Servers to include (empty = all)
- `exclude`: Servers to exclude
- `custom`: Inline custom server definitions

### ToolDefinition

```typescript
export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}
```

**Purpose:** For scaffolding new MCP servers.

## Bundled Server Metadata

```typescript
const BUNDLED_SERVER_META: Record<string, {
  description: string;
  capabilities: string[];
  requiresAuth?: string[];
}> = {
  memory_server: {
    description: 'Memory and recall - SQLite-backed conversation history',
    capabilities: ['memory', 'search', 'write', 'recall', 'notes', 'threads'],
  },
  google_server: {
    description: 'Google Workspace - Gmail, Calendar, Drive, YouTube',
    capabilities: ['email', 'calendar', 'drive', 'search', 'write'],
    requiresAuth: ['GOOGLE_CONFIGURED'],
  },
  shell_server: {
    description: 'Sandboxed shell access with allowlist',
    capabilities: ['shell', 'exec', 'filesystem'],
  },
  github_server: {
    description: 'GitHub operations via gh CLI',
    capabilities: ['github', 'search', 'write'],
  },
  worldmonitor_server: {
    description: 'WorldMonitor intelligence API',
    capabilities: ['news', 'search', 'intelligence'],
  },
  puppeteer_proxy: {
    description: 'Web browsing with injection detection',
    capabilities: ['web', 'browse', 'screenshot'],
  },
};
```

## External Server Metadata

```typescript
export const EXTERNAL_SERVER_META: Record<string, {
  description: string;
  capabilities: string[];
  commandCandidates: string[];
  args: string[];
  requiresAuth?: string[];
  requiresEnvKey?: string;
}> = {
  elevenlabs: {
    description: 'ElevenLabs - TTS, voice cloning, audio processing',
    capabilities: ['tts', 'stt', 'voice', 'audio', 'clone', 'sound_effects'],
    commandCandidates: ['uvx', '~/.local/bin/uvx', '/opt/homebrew/bin/uvx'],
    args: ['elevenlabs-mcp'],
    requiresEnvKey: 'ELEVENLABS_API_KEY',
  },
  fal: {
    description: 'Fal.ai - image, video, audio generation',
    capabilities: ['image', 'video', 'audio', 'generation'],
    commandCandidates: ['npx', '/opt/homebrew/bin/npx', '/usr/local/bin/npx'],
    args: ['-y', 'fal-ai-mcp-server@latest'],
    requiresEnvKey: 'FAL_KEY',
  },
};
```

**External servers:** Ship with Atrophy but depend on host tools (uvx, npx). Registered during `discover()` if command found on PATH.

## Python Path Detection

```typescript
function findPythonPath(): string {
  if (process.env.PYTHON_PATH) {
    const p = process.env.PYTHON_PATH;
    if (/^[a-zA-Z0-9_.\/~-]+$/.test(p)) return p;
  }

  const home = process.env.HOME || os.homedir();
  const candidates = [
    'python3',
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    `${home}/.pyenv/shims/python3`,
  ];

  // Scan pyenv versions
  try {
    const pyenvDir = `${home}/.pyenv/versions`;
    const versions = readdirSync(pyenvDir)
      .filter((v: string) => statSync(`${pyenvDir}/${v}`).isDirectory())
      .sort()
      .reverse();
    for (const v of versions) {
      candidates.push(`${pyenvDir}/${v}/bin/python3`);
    }
  } catch { /* pyenv not installed */ }

  for (const c of candidates) {
    try {
      execFileSync(c, ['--version'], { stdio: 'pipe' });
      return c;
    } catch { continue; }
  }
  return 'python3';
}
```

**Search order:**
1. `PYTHON_PATH` env var (user override)
2. pyenv shim
3. Homebrew (Apple Silicon, Intel)
4. System PATH
5. pyenv versions (newest first)
6. Fallback to `python3`

## McpRegistry Class

### Properties

```typescript
class McpRegistry {
  private servers: Map<string, McpServerDefinition> = new Map();
  private _mcpDirty: Map<string, boolean> = new Map();
  private _lastBuildHash: Map<string, string> = new Map();
  private _pythonPath: string | null = null;
}
```

**Fields:**
- `servers`: Discovered server definitions
- `_mcpDirty`: Track which agents need config rebuild
- `_lastBuildHash`: Cache to detect config changes
- `_pythonPath`: Cached Python path

### clearCache

```typescript
clearCache(): void {
  this._mcpDirty.clear();
  this._lastBuildHash.clear();
  this._pythonPath = null;
}
```

**Purpose:** Clear cached config paths and dirty flags. Called on agent switch.

### resolveCommand

```typescript
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
```

**Purpose:** Find first available command from candidate list.

**Search strategy:**
1. Absolute paths: Check `fs.existsSync()`
2. Bare names: Use `which` command

### serverNameFromFile

```typescript
private serverNameFromFile(filename: string): string {
  const base = path.basename(filename, '.py');
  return base.replace(/_server$/, '').replace(/_proxy$/, '');
}
```

**Examples:**
- `memory_server.py` → `memory`
- `puppeteer_proxy.py` → `puppeteer`

### discover

```typescript
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
      this.servers.set(name, {
        name,
        description: meta.description,
        command: this.getPythonPath(),
        args: [path.join(bundledDir, file)],
        env: {},
        capabilities: meta.capabilities,
        bundled: true,
        requiresAuth: meta.requiresAuth,
      });
    }
  }

  // 2. External servers (uvx, npx)
  for (const [name, meta] of Object.entries(EXTERNAL_SERVER_META)) {
    const cmd = this.resolveCommand(meta.commandCandidates);
    if (!cmd) {
      log.debug(`External server ${name}: command not found`);
      continue;
    }
    if (meta.requiresEnvKey && !process.env[meta.requiresEnvKey]) {
      log.debug(`External server ${name}: missing ${meta.requiresEnvKey}`);
      continue;
    }
    this.servers.set(name, {
      name,
      description: meta.description,
      command: cmd,
      args: meta.args,
      env: {},
      capabilities: meta.capabilities,
      bundled: false,
      requiresAuth: meta.requiresAuth,
    });
  }

  // 3. User custom servers in USER_DATA/mcp/custom/
  const customDir = path.join(USER_DATA, 'mcp', 'custom');
  if (fs.existsSync(customDir)) {
    for (const entry of fs.readdirSync(customDir, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const serverPy = path.join(customDir, entry.name, 'server.py');
      const metaJson = path.join(customDir, entry.name, 'meta.json');
      if (fs.existsSync(serverPy)) {
        let meta = { description: `Custom server: ${entry.name}`, capabilities: [] };
        if (fs.existsSync(metaJson)) {
          meta = { ...meta, ...JSON.parse(fs.readFileSync(metaJson, 'utf-8')) };
        }
        this.servers.set(entry.name, {
          name: entry.name,
          description: meta.description,
          command: this.getPythonPath(),
          args: [serverPy],
          env: {},
          capabilities: meta.capabilities || [],
          bundled: false,
        });
      }
    }
  }

  log.info(`Discovered ${this.servers.size} MCP server(s)`);
}
```

**Discovery order:**
1. **Bundled:** Python scripts in `BUNDLE_ROOT/mcp/`
2. **External:** uvx/npx commands if available and env keys present
3. **Custom:** User servers in `USER_DATA/mcp/custom/<name>/`

### buildConfigForAgent

```typescript
buildConfigForAgent(agentName: string): string {
  if (!isValidAgentName(agentName)) {
    throw new Error(`Invalid agent name: ${agentName}`);
  }

  const mcpConfig = getAgentMcpSection(agentName);
  const configDir = path.join(USER_DATA, 'mcp');
  fs.mkdirSync(configDir, { recursive: true });
  const configPath = path.join(configDir, `${agentName}.config.json`);

  // Build server list
  const activeServers: McpServerDefinition[] = [];
  for (const [name, def] of this.servers) {
    // Check include list
    if (mcpConfig.include.length > 0 && !mcpConfig.include.includes(name)) {
      continue;
    }
    // Check exclude list
    if (mcpConfig.exclude.includes(name)) {
      continue;
    }
    // Check auth requirements
    if (def.requiresAuth) {
      const missing = def.requiresAuth.filter(key => !process.env[key]);
      if (missing.length > 0) {
        log.debug(`Server ${name} missing auth: ${missing.join(', ')}`);
        continue;
      }
    }
    activeServers.push(def);
  }

  // Add custom servers
  for (const [name, custom] of Object.entries(mcpConfig.custom)) {
    activeServers.push({
      name,
      description: custom.description || `Custom server: ${name}`,
      command: custom.command,
      args: custom.args,
      env: custom.env,
      bundled: false,
    });
  }

  // Build Claude CLI config
  const claudeConfig: Record<string, { command: string; args: string[]; env?: Record<string, string> }> = {};
  for (const server of activeServers) {
    claudeConfig[server.name] = {
      command: server.command,
      args: server.args,
      env: server.env,
    };
  }

  // Write atomically
  const newHash = JSON.stringify(claudeConfig);
  const tmpPath = configPath + `.tmp.${process.pid}`;
  fs.writeFileSync(tmpPath, JSON.stringify({ mcpServers: claudeConfig }, null, 2));
  fs.renameSync(tmpPath, configPath);

  this._lastBuildHash.set(agentName, newHash);
  this._mcpDirty.delete(agentName);

  log.debug(`Built MCP config for ${agentName}: ${activeServers.length} server(s)`);
  return configPath;
}
```

**Config building:**
1. Load agent's MCP section from manifest
2. Filter servers by include/exclude lists
3. Check auth requirements (env vars)
4. Add custom servers from manifest
5. Build Claude CLI config format
6. Write atomically (tmp + rename)

**Returns:** Path to generated config file

### needsRestart

```typescript
needsRestart(agentName: string): boolean {
  return this._mcpDirty.get(agentName) || false;
}
```

**Purpose:** Check if agent's config needs rebuild.

### activateForAgent / deactivateForAgent

```typescript
activateForAgent(agentName: string, serverName: string): void {
  const manifestPath = path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json');
  const manifest = readAgentManifest(agentName);
  const mcp = getAgentMcpSection(agentName);

  if (!mcp.include.includes(serverName)) {
    mcp.include.push(serverName);
  }
  mcp.exclude = mcp.exclude.filter(s => s !== serverName);

  manifest.mcp = mcp;
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  this._mcpDirty.set(agentName, true);
}

deactivateForAgent(agentName: string, serverName: string): void {
  const manifestPath = path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json');
  const manifest = readAgentManifest(agentName);
  const mcp = getAgentMcpSection(agentName);

  if (!mcp.exclude.includes(serverName)) {
    mcp.exclude.push(serverName);
  }

  manifest.mcp = mcp;
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  this._mcpDirty.set(agentName, true);
}
```

**Purpose:** Enable/disable MCP server for agent by updating manifest.

### registerWithSwitchboard

```typescript
registerWithSwitchboard(switchboard: Switchboard): void {
  for (const [name, server] of this.servers) {
    switchboard.register(`mcp:${name}`, async (envelope) => {
      // Route MCP tool calls through switchboard
      // Implementation delegates to actual MCP server via stdio
    }, {
      type: 'mcp',
      description: server.description,
      capabilities: server.capabilities,
    });
  }
}
```

**Purpose:** Register MCP servers with switchboard for service discovery.

### getRegistry / getForAgent

```typescript
getRegistry(): McpServerDefinition[] {
  return Array.from(this.servers.values());
}

getForAgent(agentName: string): McpServerDefinition[] {
  const mcpConfig = getAgentMcpSection(agentName);
  const result: McpServerDefinition[] = [];
  for (const [name, def] of this.servers) {
    if (mcpConfig.include.length > 0 && !mcpConfig.include.includes(name)) continue;
    if (mcpConfig.exclude.includes(name)) continue;
    result.push(def);
  }
  return result;
}
```

**Purpose:** Get server list (all or filtered for agent).

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `BUNDLE_ROOT/mcp/*.py` | discover() - bundled servers |
| Read | `USER_DATA/mcp/custom/<name>/server.py` | discover() - custom servers |
| Read | `USER_DATA/mcp/custom/<name>/meta.json` | discover() - custom metadata |
| Read | `~/.atrophy/agents/<name>/data/agent.json` | getAgentMcpSection() |
| Write | `~/.atrophy/mcp/<agent>.config.json` | buildConfigForAgent() |
| Write | `~/.atrophy/agents/<name>/data/agent.json` | activateForAgent/deactivateForAgent |

## Exported API

| Function/Class | Purpose |
|----------------|---------|
| `McpRegistry` | Main registry class |
| `readAgentManifest(agentName)` | Read agent manifest from disk |
| `getAgentMcpSection(agentName)` | Extract MCP config from manifest |
| `EXTERNAL_SERVER_META` | External server metadata |

## Singleton

```typescript
export const mcpRegistry = new McpRegistry();
```

**Usage:** `import { mcpRegistry } from './mcp-registry'`

## See Also

- `src/main/inference.ts` - Uses MCP config for Claude CLI
- `src/main/channels/switchboard.ts` - Service registration
- `src/main/config.ts` - Agent manifest loading

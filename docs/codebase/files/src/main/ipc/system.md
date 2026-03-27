# src/main/ipc/system.ts - System IPC Handlers

**Dependencies:** `electron`, `fs`, `child_process`, `../config`, `../usage`, `../server`, `../channels/cron`, `../mcp-registry`, `../vector-search`, `../install`, `../updater`, `../bundle-updater`, `../logger`, `../system-topology`, `../org-manager`, `../ipc-handlers`  
**Purpose:** IPC handlers for system operations, usage analytics, cron, MCP, server, updates, logs, GitHub auth, organizations

## Overview

This module provides the renderer with controls for:
- Log access and forwarding
- Usage and activity analytics
- Cron job management
- MCP server registry
- Keep awake (prevent sleep)
- HTTP API server
- Vector memory search
- Login item (launch at login)
- Auto-updater
- Hot bundle updates
- GitHub authentication
- System topology
- Organization management

## IPC Handlers

### Logs

#### logs:getBuffer

```typescript
ipcMain.handle('logs:getBuffer', () => {
  return getLogBuffer();
});
```

**Returns:** Array of buffered log entries (up to 500 most recent)

#### logs:entry (send)

```typescript
setLogForwarder((entry) => {
  if (ctx.mainWindow && !ctx.mainWindow.isDestroyed()) {
    ctx.mainWindow.webContents.send('logs:entry', entry);
  }
});
```

**Purpose:** Forward live log entries to renderer for in-app console.

### Usage & Activity

#### usage:all

```typescript
ipcMain.handle('usage:all', (_event, days?: number) => {
  return getAllAgentsUsage(days);
});
```

**Returns:** Usage data for all agents, optionally filtered by days

#### activity:all

```typescript
ipcMain.handle('activity:all', (_event, days?: number, limit?: number) => {
  return getAllActivity(days, limit);
});
```

**Returns:** Activity data for all agents, filtered by days and limit

### Cron (In-Process Scheduler)

#### cron:schedule

```typescript
ipcMain.handle('cron:schedule', () => {
  return cronScheduler.getSchedule();
});
```

**Returns:** Current cron schedule with all jobs and their next run times

#### cron:history

```typescript
ipcMain.handle('cron:history', () => {
  return getJobHistory();
});
```

**Returns:** History of job executions

#### cron:runNow

```typescript
ipcMain.handle('cron:runNow', (_event, agentName: string, jobName: string) => {
  if (!NAME_RE.test(agentName) || !NAME_RE.test(jobName)) return;
  return cronScheduler.runNow(agentName, jobName);
});
```

**Security:** Agent and job name validation prevents injection.

**Returns:** Exit code (0 = success)

#### cron:reset

```typescript
ipcMain.handle('cron:reset', (_event, agentName: string, jobName: string) => {
  if (!NAME_RE.test(agentName) || !NAME_RE.test(jobName)) return;
  cronScheduler.resetJob(agentName, jobName);
});
```

**Purpose:** Reset a job's schedule (e.g., after manual run)

#### cron:schedulerStatus

```typescript
ipcMain.handle('cron:schedulerStatus', () => {
  return { schedule: cronScheduler.getSchedule() };
});
```

**Returns:** Current scheduler status

### MCP Registry

#### mcp:list

```typescript
ipcMain.handle('mcp:list', () => {
  return mcpRegistry.getRegistry();
});
```

**Returns:** List of all discovered MCP servers

#### mcp:forAgent

```typescript
ipcMain.handle('mcp:forAgent', (_event, agentName: string) => {
  return mcpRegistry.getForAgent(agentName);
});
```

**Returns:** MCP servers active for specific agent

#### mcp:activate

```typescript
ipcMain.handle('mcp:activate', (_event, agentName: string, serverName: string) => {
  mcpRegistry.activateForAgent(agentName, serverName);
});
```

**Purpose:** Enable an MCP server for an agent

#### mcp:deactivate

```typescript
ipcMain.handle('mcp:deactivate', (_event, agentName: string, serverName: string) => {
  mcpRegistry.deactivateForAgent(agentName, serverName);
});
```

**Purpose:** Disable an MCP server for an agent

### Keep Awake

#### keepAwake:toggle

```typescript
ipcMain.handle('keepAwake:toggle', () => {
  ctx.toggleKeepAwake();
  return ctx.isKeepAwakeActive();
});
```

**Returns:** New keep-awake state

#### keepAwake:isActive

```typescript
ipcMain.handle('keepAwake:isActive', () => {
  return ctx.isKeepAwakeActive();
});
```

**Returns:** Current keep-awake state

### HTTP API Server

#### server:start

```typescript
ipcMain.handle('server:start', (_event, port?: number) => {
  startServer(port);
});
```

**Purpose:** Start HTTP API server on optional port (default 5000)

#### server:stop

```typescript
ipcMain.handle('server:stop', async () => {
  await stopServer();
});
```

**Purpose:** Stop HTTP API server

### Vector Search

#### memory:search

```typescript
ipcMain.handle('memory:search', async (_event, query: string, n?: number) => {
  return vectorSearch(query, n);
});
```

**Returns:** Search results from memory database

### Login Item

#### install:isEnabled

```typescript
ipcMain.handle('install:isEnabled', () => {
  return isLoginItemEnabled();
});
```

**Returns:** Whether app launches at login

#### install:toggle

```typescript
ipcMain.handle('install:toggle', (_event, enabled: boolean) => {
  toggleLoginItem(enabled);
});
```

**Purpose:** Enable/disable launch at login

### Auto-Updater

#### updater:check

```typescript
ipcMain.handle('updater:check', () => {
  checkForUpdates();
});
```

**Purpose:** Check for DMG updates from GitHub Releases

#### updater:download

```typescript
ipcMain.handle('updater:download', () => {
  downloadUpdate();
});
```

**Purpose:** Download available update

#### updater:quitAndInstall

```typescript
ipcMain.handle('updater:quitAndInstall', () => {
  quitAndInstall();
});
```

**Purpose:** Quit and install downloaded update

### Bundle Updater (Hot Bundles)

#### bundle:getStatus

```typescript
ipcMain.handle('bundle:getStatus', () => {
  return {
    activeVersion: getActiveBundleVersion(),
    hotBundleActive: !!ctx.hotBundle,
    hotBundleVersion: ctx.hotBundle?.version ?? null,
    pending: getPendingBundleInfo(),
  };
});
```

**Returns:** Current bundle status including hot bundle info

#### bundle:checkNow

```typescript
ipcMain.handle('bundle:checkNow', async () => {
  const newVersion = await checkForBundleUpdate((percent) => {
    ctx.mainWindow?.webContents.send('bundle:downloadProgress', percent);
  });
  if (newVersion) {
    ctx.pendingBundleVersion = newVersion;
    ctx.rebuildTrayMenu();
  }
  return newVersion;
});
```

**Purpose:** Manually check for hot bundle update

**Events:** Sends `bundle:downloadProgress` to renderer during download

#### bundle:clear

```typescript
ipcMain.handle('bundle:clear', () => {
  clearHotBundle();
});
```

**Purpose:** Clear hot bundle and revert to frozen version

### App Restart

#### app:restartForUpdate

```typescript
ipcMain.handle('app:restartForUpdate', () => {
  app.relaunch();
  app.exit();
});
```

**Purpose:** Restart app (used after update installation)

### GitHub Authentication

#### github:authStatus

```typescript
ipcMain.handle('github:authStatus', async () => {
  const ghBin = findGhBin();
  if (!ghBin) {
    return { installed: false, authenticated: false, account: '' };
  }
  return new Promise((resolve) => {
    execFile(ghBin, ['auth', 'status'], { timeout: 10_000 }, (_err, stdout, stderr) => {
      const output = (stdout || '') + (stderr || '');
      const authed = output.includes('Logged in');
      const match = output.match(/account\s+(\S+)/);
      resolve({ installed: true, authenticated: authed, account: match?.[1] || '' });
    });
  });
});
```

**Returns:** `{ installed: boolean; authenticated: boolean; account: string }`

#### github:authLogin

```typescript
ipcMain.handle('github:authLogin', async () => {
  const ghBin = findGhBin();
  if (!ghBin) return { success: false, error: 'gh CLI not installed' };

  return new Promise((resolve) => {
    const proc = spawn(ghBin, [
      'auth', 'login',
      '--hostname', 'github.com',
      '--git-protocol', 'https',
      '--web',
    ], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    // Pipe newlines to accept defaults
    proc.stdin?.write('\n');
    const stdinTimer = setTimeout(() => {
      try { proc.stdin?.write('\n'); } catch { /* closed */ }
    }, 1000);

    proc.on('close', (code) => {
      resolve(code === 0 ? { success: true } : { success: false, error: output.slice(0, 500) });
    });

    // Timeout after 5 minutes
    const timeoutTimer = setTimeout(() => {
      try { proc.kill(); } catch { /* already dead */ }
      resolve({ success: false, error: 'Timed out waiting for browser auth' });
    }, 300_000);
  });
});
```

**Purpose:** Launch GitHub OAuth flow in browser

**Flow:**
1. Spawn `gh auth login --web`
2. Browser opens for OAuth authentication
3. Wait for close or timeout (5 minutes)

### System Topology

#### system:getTopology

```typescript
ipcMain.handle('system:getTopology', () => {
  return buildTopology();
});
```

**Returns:** Full system topology with agents, MCP servers, channels

#### system:toggleConnection

```typescript
ipcMain.handle('system:toggleConnection', (_, agentName: string, serverName: string, enabled: boolean) => {
  return handleToggleConnection(agentName, serverName, enabled);
});
```

**Purpose:** Enable/disable MCP server connection for agent

### Organizations

#### org:list

```typescript
ipcMain.handle('org:list', () => {
  return listOrgs();
});
```

**Returns:** List of all organizations

#### org:detail

```typescript
ipcMain.handle('org:detail', (_event, slug: string) => {
  return getOrgDetail(slug);
});
```

**Returns:** Organization details with members

#### org:create

```typescript
ipcMain.handle('org:create', (_event, name: string, type: OrgType, purpose: string) => {
  return createOrg(name, type, purpose);
});
```

**Purpose:** Create new organization

#### org:dissolve

```typescript
ipcMain.handle('org:dissolve', (_event, slug: string) => {
  dissolveOrg(slug);
});
```

**Purpose:** Dissolve organization

#### org:addAgent

```typescript
ipcMain.handle('org:addAgent', (_event, orgSlug: string, agentName: string, role: string, tier: number, reportsTo: string | null) => {
  addAgentToOrg(orgSlug, agentName, role, tier, reportsTo);
});
```

**Purpose:** Add agent to organization

#### org:removeAgent

```typescript
ipcMain.handle('org:removeAgent', (_event, agentName: string) => {
  removeAgentFromOrg(agentName);
});
```

**Purpose:** Remove agent from organization

## Helper Functions

### findGhBin

```typescript
function findGhBin(): string | null {
  const paths = ['/opt/homebrew/bin/gh', '/usr/local/bin/gh', '/usr/bin/gh'];
  for (const p of paths) {
    if (fs.existsSync(p)) return p;
  }
  try {
    return execSync('which gh', { encoding: 'utf-8', timeout: 3000 }).trim() || null;
  } catch {
    return null;
  }
}
```

**Purpose:** Find GitHub CLI binary.

## Security Considerations

### Name Validation

```typescript
const NAME_RE = /^[a-zA-Z0-9_-]+$/;
```

Prevents injection attacks in agent/job names.

### Timeout Protection

All subprocess calls have timeouts:
- GitHub auth status: 10 seconds
- GitHub auth login: 5 minutes

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/agents/*/data/memory.db` | usage:all, activity:all |
| Read | `~/.atrophy/.switchboard_queue.json` | Queue polling |
| Read/Write | `~/.atrophy/mcp/<agent>.config.json` | MCP registry |
| Read | `~/.atrophy/config.json` | Various |
| Read | `~/.atrophy/agent_states.json` | Various |

## Exported API

| Function | Purpose |
|----------|---------|
| `registerSystemHandlers(ctx)` | Register all system IPC handlers |

## See Also

- `src/main/usage.ts` - Usage analytics
- `src/main/server.ts` - HTTP API server
- `src/main/channels/cron.ts` - Cron scheduler
- `src/main/mcp-registry.ts` - MCP server registry
- `src/main/vector-search.ts` - Vector search
- `src/main/install.ts` - Login item management
- `src/main/updater.ts` - Auto-updater
- `src/main/bundle-updater.ts` - Hot bundle updates
- `src/main/system-topology.ts` - System topology builder
- `src/main/org-manager.ts` - Organization management

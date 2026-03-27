/**
 * IPC handlers for system operations, usage, cron, MCP, server, updates, etc.
 * Channels: system:getTopology, system:toggleConnection, usage:all, activity:all,
 *           cron:*, mcp:*, keepAwake:*, server:*, memory:search, install:*,
 *           updater:*, github:*, bundle:*, app:restartForUpdate, logs:*
 */

import { app, ipcMain } from 'electron';
import * as fs from 'fs';
import * as path from 'path';
import { execFile, execSync, spawn } from 'child_process';
import { getConfig, USER_DATA } from '../config';
import { getAllAgentsUsage, getAllActivity, getAgentUsageDetail } from '../usage';
import { startServer, stopServer } from '../server';
import { cronScheduler, getJobHistory } from '../channels/cron';
import type { JobDefinition } from '../channels/cron';
import { mcpRegistry } from '../mcp-registry';
import { search as vectorSearch } from '../vector-search';
import { isLoginItemEnabled, toggleLoginItem } from '../install';
import { checkForUpdates, downloadUpdate, quitAndInstall } from '../updater';
import { getActiveBundleVersion, checkForBundleUpdate, getPendingBundleInfo, clearHotBundle } from '../bundle-updater';
import { createLogger, setLogForwarder, getLogBuffer, readLogFile, readPrevLogFile, parseLogFile } from '../logger';
import type { LogLevel } from '../logger';
import { buildTopology, handleToggleConnection } from '../system-topology';
import { listOrgs, getOrgDetail, createOrg, dissolveOrg, addAgentToOrg, removeAgentFromOrg, updateOrg } from '../org-manager';
import type { OrgType } from '../org-manager';
import type { IpcContext } from '../ipc-handlers';

const log = createLogger('ipc:system');

// Helper to find gh binary
function findGhBin(): string | null {
  const paths = [
    '/opt/homebrew/bin/gh',
    '/usr/local/bin/gh',
    '/usr/bin/gh',
  ];
  for (const p of paths) {
    if (fs.existsSync(p)) return p;
  }
  try {
    return execSync('which gh', { encoding: 'utf-8', timeout: 3000 }).trim() || null;
  } catch {
    return null;
  }
}

export function registerSystemHandlers(ctx: IpcContext): void {
  // -- Logs --

  ipcMain.handle('logs:getBuffer', () => {
    return getLogBuffer();
  });

  // Renderer-to-main log forwarding: renderer calls api.log() which arrives here
  const rendererLogger = createLogger('renderer');
  ipcMain.handle('logs:write', (_event, level: string, tag: string, message: string) => {
    const lvl = (['debug', 'info', 'warn', 'error'].includes(level) ? level : 'info') as LogLevel;
    rendererLogger[lvl](`[${tag}] ${message}`);
  });

  // Read persisted log file (for viewing previous boot logs)
  ipcMain.handle('logs:readFile', () => {
    return readLogFile();
  });
  ipcMain.handle('logs:readPrevFile', () => {
    return readPrevLogFile();
  });
  ipcMain.handle('logs:parseFile', (_event, contents: string) => {
    return parseLogFile(contents);
  });

  // Forward live log entries to renderer
  setLogForwarder((entry) => {
    if (ctx.mainWindow && !ctx.mainWindow.isDestroyed()) {
      ctx.mainWindow.webContents.send('logs:entry', entry);
    }
  });

  // -- Usage & Activity --

  ipcMain.handle('usage:all', (_event, days?: number) => {
    return getAllAgentsUsage(days);
  });

  ipcMain.handle('activity:all', (_event, days?: number, limit?: number) => {
    return getAllActivity(days, limit);
  });

  ipcMain.handle('usage:detail', (_event, agentName: string, days?: number) => {
    return getAgentUsageDetail(agentName, days);
  });

  // -- Cron (in-process scheduler via switchboard) --

  ipcMain.handle('cron:schedule', () => {
    return cronScheduler.getSchedule();
  });

  ipcMain.handle('cron:history', () => {
    return getJobHistory();
  });

  const NAME_RE = /^[a-zA-Z0-9_-]+$/;

  ipcMain.handle('cron:runNow', (_event, agentName: string, jobName: string) => {
    if (!NAME_RE.test(agentName) || !NAME_RE.test(jobName)) return;
    return cronScheduler.runNow(agentName, jobName);
  });

  ipcMain.handle('cron:reset', (_event, agentName: string, jobName: string) => {
    if (!NAME_RE.test(agentName) || !NAME_RE.test(jobName)) return;
    cronScheduler.resetJob(agentName, jobName);
  });

  ipcMain.handle('cron:schedulerStatus', () => {
    return {
      schedule: cronScheduler.getSchedule(),
    };
  });

  // -- MCP Registry --

  ipcMain.handle('mcp:list', () => {
    return mcpRegistry.getRegistry();
  });

  ipcMain.handle('mcp:forAgent', (_event, agentName: string) => {
    return mcpRegistry.getForAgent(agentName);
  });

  ipcMain.handle('mcp:activate', (_event, agentName: string, serverName: string) => {
    mcpRegistry.activateForAgent(agentName, serverName);
  });

  ipcMain.handle('mcp:deactivate', (_event, agentName: string, serverName: string) => {
    mcpRegistry.deactivateForAgent(agentName, serverName);
  });

  // -- Keep Awake --

  ipcMain.handle('keepAwake:toggle', () => {
    ctx.toggleKeepAwake();
    return ctx.isKeepAwakeActive();
  });

  ipcMain.handle('keepAwake:isActive', () => {
    return ctx.isKeepAwakeActive();
  });

  // -- Server --

  ipcMain.handle('server:start', (_event, port?: number) => {
    startServer(port);
  });

  ipcMain.handle('server:stop', async () => {
    await stopServer();
  });

  // -- Vector search --

  ipcMain.handle('memory:search', async (_event, query: string, n?: number) => {
    return vectorSearch(query, n);
  });

  // -- Login item --

  ipcMain.handle('install:isEnabled', () => {
    return isLoginItemEnabled();
  });

  ipcMain.handle('install:toggle', (_event, enabled: boolean) => {
    toggleLoginItem(enabled);
  });

  // -- Auto-updater --

  ipcMain.handle('updater:check', () => {
    checkForUpdates();
  });

  ipcMain.handle('updater:download', () => {
    downloadUpdate();
  });

  ipcMain.handle('updater:quitAndInstall', () => {
    quitAndInstall();
  });

  // -- Bundle updater --

  ipcMain.handle('bundle:getStatus', () => {
    return {
      activeVersion: getActiveBundleVersion(),
      hotBundleActive: !!ctx.hotBundle,
      hotBundleVersion: ctx.hotBundle?.version ?? null,
      pending: getPendingBundleInfo(),
    };
  });

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

  ipcMain.handle('bundle:clear', () => {
    clearHotBundle();
  });

  // -- Restart for update --

  ipcMain.handle('app:restartForUpdate', () => {
    app.relaunch();
    app.exit();
  });

  // -- GitHub auth --

  ipcMain.handle('github:authStatus', async () => {
    const ghBin = findGhBin();
    if (!ghBin) {
      return { installed: false, authenticated: false, account: '' };
    }
    return new Promise<{ installed: boolean; authenticated: boolean; account: string }>((resolve) => {
      execFile(ghBin, ['auth', 'status'], { timeout: 10_000 }, (_err, stdout, stderr) => {
        const output = (stdout || '') + (stderr || '');
        const authed = output.includes('Logged in');
        const match = output.match(/account\s+(\S+)/);
        resolve({ installed: true, authenticated: authed, account: match?.[1] || '' });
      });
    });
  });

  ipcMain.handle('github:authLogin', async () => {
    const ghBin = findGhBin();
    if (!ghBin) return { success: false, error: 'gh CLI not installed. Run: brew install gh' };

    // gh auth login requires interactive stdin for prompts.
    // Use --hostname and --git-protocol to skip interactive questions,
    // then --web opens the browser for the actual OAuth flow.
    return new Promise<{ success: boolean; error?: string }>((resolve) => {
      let resolved = false;
      const done = (result: { success: boolean; error?: string }) => {
        if (resolved) return;
        resolved = true;
        clearTimeout(stdinTimer);
        clearTimeout(timeoutTimer);
        resolve(result);
      };

      const proc = spawn(ghBin, [
        'auth', 'login',
        '--hostname', 'github.com',
        '--git-protocol', 'https',
        '--web',
      ], {
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      let output = '';
      proc.stdout?.on('data', (d: Buffer) => { output += d.toString(); });
      proc.stderr?.on('data', (d: Buffer) => { output += d.toString(); });

      // gh may still prompt - pipe newlines to accept defaults
      proc.stdin?.write('\n');
      const stdinTimer = setTimeout(() => { try { proc.stdin?.write('\n'); } catch { /* closed */ } }, 1000);

      proc.on('close', (code) => {
        done(code === 0
          ? { success: true }
          : { success: false, error: output.slice(0, 500) || 'Auth failed' });
      });
      proc.on('error', (e) => {
        done({ success: false, error: e.message });
      });

      // Timeout after 5 minutes
      const timeoutTimer = setTimeout(() => {
        try { proc.kill(); } catch { /* already dead */ }
        done({ success: false, error: 'Timed out waiting for browser auth' });
      }, 300_000);
    });
  });

  // -- System map topology --

  ipcMain.handle('system:getTopology', () => {
    return buildTopology();
  });

  ipcMain.handle('system:toggleConnection', (_, agentName: string, serverName: string, enabled: boolean) => {
    return handleToggleConnection(agentName, serverName, enabled);
  });

  // -- Organizations --

  ipcMain.handle('org:list', () => {
    return listOrgs();
  });

  ipcMain.handle('org:detail', (_event, slug: string) => {
    return getOrgDetail(slug);
  });

  ipcMain.handle('org:create', (_event, name: string, type: OrgType, purpose: string) => {
    return createOrg(name, type, purpose);
  });

  ipcMain.handle('org:dissolve', (_event, slug: string) => {
    dissolveOrg(slug);
  });

  ipcMain.handle('org:addAgent', (_event, orgSlug: string, agentName: string, role: string, tier: number, reportsTo: string | null) => {
    addAgentToOrg(orgSlug, agentName, role, tier, reportsTo);
  });

  ipcMain.handle('org:removeAgent', (_event, agentName: string) => {
    removeAgentFromOrg(agentName);
  });

  ipcMain.handle('org:update', (_event, slug: string, updates: { name?: string; purpose?: string }) => {
    updateOrg(slug, updates);
  });

  // -- Cron job CRUD --

  function readAgentManifestRaw(agentName: string): Record<string, unknown> {
    const manifestPath = path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json');
    if (!fs.existsSync(manifestPath)) return {};
    return JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
  }

  function writeAgentManifestRaw(agentName: string, manifest: Record<string, unknown>): void {
    const manifestPath = path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json');
    const tmp = manifestPath + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(manifest, null, 2) + '\n');
    fs.renameSync(tmp, manifestPath);
  }

  ipcMain.handle('cron:addJob', (_event, agentName: string, jobName: string, jobDef: JobDefinition) => {
    if (!NAME_RE.test(agentName) || !NAME_RE.test(jobName)) {
      throw new Error('Invalid agent or job name');
    }
    const manifest = readAgentManifestRaw(agentName);
    const jobs = (manifest.jobs as Record<string, JobDefinition>) || {};
    if (jobs[jobName]) throw new Error(`Job "${jobName}" already exists for agent "${agentName}"`);
    jobs[jobName] = jobDef;
    manifest.jobs = jobs;
    writeAgentManifestRaw(agentName, manifest);
    cronScheduler.registerAgent(agentName, { [jobName]: jobDef });
  });

  ipcMain.handle('cron:editJob', (_event, agentName: string, jobName: string, updates: Partial<JobDefinition>) => {
    if (!NAME_RE.test(agentName) || !NAME_RE.test(jobName)) {
      throw new Error('Invalid agent or job name');
    }
    const manifest = readAgentManifestRaw(agentName);
    const jobs = (manifest.jobs as Record<string, JobDefinition>) || {};
    if (!jobs[jobName]) throw new Error(`Job "${jobName}" not found for agent "${agentName}"`);
    jobs[jobName] = { ...jobs[jobName], ...updates };
    manifest.jobs = jobs;
    writeAgentManifestRaw(agentName, manifest);
    // Re-register all jobs for agent so the timer is updated
    cronScheduler.registerAgent(agentName, jobs as Record<string, JobDefinition>);
  });

  ipcMain.handle('cron:deleteJob', (_event, agentName: string, jobName: string) => {
    if (!NAME_RE.test(agentName) || !NAME_RE.test(jobName)) {
      throw new Error('Invalid agent or job name');
    }
    const manifest = readAgentManifestRaw(agentName);
    const jobs = (manifest.jobs as Record<string, JobDefinition>) || {};
    if (!jobs[jobName]) return; // Already gone - idempotent
    delete jobs[jobName];
    manifest.jobs = jobs;
    writeAgentManifestRaw(agentName, manifest);
    cronScheduler.unregisterAgent(agentName);
    if (Object.keys(jobs).length > 0) {
      cronScheduler.registerAgent(agentName, jobs as Record<string, JobDefinition>);
    }
  });
}

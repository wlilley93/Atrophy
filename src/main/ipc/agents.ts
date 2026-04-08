/**
 * IPC handlers for agent management.
 * Channels: agent:list, agent:listFull, agent:cycle, agent:getState, agent:setState,
 *           agent:switch, deferral:complete, queue:*, mirror:*
 */

import { ipcMain, shell } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { getConfig, isValidAgentName, saveAgentConfig, saveUserConfig, saveEnvVar, USER_DATA, BUNDLE_ROOT } from '../config';
import {
  discoverUiAgents, discoverAgents, cycleAgent, getAgentState, setAgentState,
  suspendAgentSession, resumeAgentSession,
  writeAskResponse, findManifest, deleteAgent,
} from '../agent-manager';
import { loadPrompt } from '../prompts';
import { endSession as endSessionInDb } from '../memory';
import { saveUserPhoto, generateMirrorAvatar, isMirrorSetupComplete, hasMirrorSourcePhoto } from '../jobs/generate-mirror-avatar';
import type { MirrorAvatarProgress } from '../jobs/generate-mirror-avatar';
import { ensureAvatarAssets } from '../avatar-downloader';
import { drainAgentQueue, drainAllAgentQueues } from '../queue';
import { Session } from '../session';
import { createLogger } from '../logger';
import type { IpcContext } from '../ipc-handlers';

const log = createLogger('ipc:agents');

export function registerAgentHandlers(ctx: IpcContext): void {
  ipcMain.handle('agent:list', () => {
    return discoverUiAgents().map(a => a.name);
  });

  ipcMain.handle('agent:listFull', () => {
    return discoverUiAgents();
  });

  ipcMain.handle('agent:cycle', (_event, direction: number) => {
    const next = cycleAgent(direction, getConfig().AGENT_NAME);
    return next;
  });

  ipcMain.handle('agent:getState', (_event, name: string) => {
    return getAgentState(name);
  });

  ipcMain.handle('agent:setState', (_event, name: string, opts: { muted?: boolean; enabled?: boolean }) => {
    setAgentState(name, opts);
  });

  // -- Agent switching (extended) --

  ipcMain.handle('agent:switch', async (_event, name: string) => {
    return ctx.switchAgent(name);
  });

  // -- Mirror setup --

  ipcMain.handle('mirror:uploadPhoto', async (_event, photoData: ArrayBuffer, filename: string) => {
    const c = getConfig();
    const ext = path.extname(filename).toLowerCase() || '.jpg';
    if (!['.png', '.jpg', '.jpeg', '.webp'].includes(ext)) {
      throw new Error('Unsupported image format. Use PNG, JPG, or WebP.');
    }
    const saved = saveUserPhoto(c.AGENT_NAME, Buffer.from(photoData), ext);
    return saved;
  });

  ipcMain.handle('mirror:generateAvatar', async () => {
    const c = getConfig();
    const clips = await generateMirrorAvatar(c.AGENT_NAME, (progress: MirrorAvatarProgress) => {
      if (ctx.mainWindow) {
        ctx.mainWindow.webContents.send('mirror:avatarProgress', progress);
      }
    });
    return clips;
  });

  ipcMain.handle('mirror:saveVoiceId', async (_event, voiceId: string) => {
    const c = getConfig();
    saveAgentConfig(c.AGENT_NAME, { ELEVENLABS_VOICE_ID: voiceId });
    c.ELEVENLABS_VOICE_ID = voiceId;
  });

  ipcMain.handle('mirror:checkSetup', () => {
    const c = getConfig();
    return {
      hasPhoto: hasMirrorSourcePhoto(c.AGENT_NAME),
      hasLoops: isMirrorSetupComplete(c.AGENT_NAME),
    };
  });

  ipcMain.handle('mirror:openExternal', (_event, url: string) => {
    // Only allow specific trusted URLs
    const allowed = [
      'https://elevenlabs.io',
      'https://www.elevenlabs.io',
    ];
    if (allowed.some((prefix) => url.startsWith(prefix))) {
      shell.openExternal(url);
    }
  });

  ipcMain.handle('mirror:downloadAssets', async () => {
    const c = getConfig();
    await ensureAvatarAssets(c.AGENT_NAME, ctx.mainWindow);
  });

  // -- Agent deferral --

  ipcMain.handle('deferral:complete', async (_event, data: { target: string; context: string; user_question: string }) => {
    if (!/^[a-zA-Z0-9_-]+$/.test(data.target)) throw new Error('Invalid agent name');
    try {
      // Suspend (not end) current agent's session so it can be resumed later
      if (ctx.currentSession) {
        if (ctx.currentSession.cliSessionId && ctx.currentAgentName) {
          suspendAgentSession(ctx.currentAgentName, ctx.currentSession.cliSessionId, ctx.currentSession.turnHistory);
        }
        // Close the session in the DB so ended_at is set
        if (ctx.currentSession.sessionId != null) {
          try {
            endSessionInDb(ctx.currentSession.sessionId, null, ctx.currentSession.mood);
          } catch { /* non-fatal */ }
        }
        // Null out before switchAgent so it skips its own session.end() call
        ctx.currentSession = null;
      }

      // Use the canonical switchAgent (handles config, DB, MCP, caches, prefetch)
      const result = await ctx.switchAgent(data.target);

      // Resume a previously suspended session for the target agent, or start fresh
      const resumed = resumeAgentSession(data.target);
      ctx.currentSession = new Session();
      ctx.currentSession.start();
      if (resumed) {
        ctx.currentSession.setCliSessionId(resumed.cliSessionId);
        ctx.currentSession.turnHistory = resumed.turnHistory as typeof ctx.currentSession.turnHistory;
      } else {
        ctx.currentSession.inheritCliSessionId();
      }
      ctx.systemPrompt = null; // Force reload for new agent

      return {
        agentName: result.agentName,
        agentDisplayName: result.agentDisplayName,
      };
    } catch (err) {
      log.error(`deferral:complete failed: ${err}`);
      throw err;
    }
  });

  // -- Agent message queues --

  ipcMain.handle('queue:drainAgent', (_event, agentName: string) => {
    // Validate agent name to prevent path traversal
    if (!/^[a-zA-Z0-9_-]+$/.test(agentName)) return [];
    return drainAgentQueue(agentName);
  });

  ipcMain.handle('queue:drainAll', () => {
    return drainAllAgentQueues();
  });

  // -- Agent detail (full manifest for settings display) --

  ipcMain.handle('agent:getDetail', (_event, agentName: string) => {
    if (!/^[a-zA-Z0-9_-]+$/.test(agentName)) return null;
    const manifest = findManifest(agentName);
    if (!manifest) return null;

    return {
      name: agentName,
      displayName: (manifest.display_name as string) || agentName,
      description: (manifest.description as string) || '',
      notifyVia: (manifest.notify_via as string) || 'auto',
      org: manifest.org || null,
      channels: manifest.channels || {},
      mcp: manifest.mcp || { include: [], exclude: [], custom: {} },
      jobs: manifest.jobs || {},
      router: manifest.router || {},
      voice: manifest.voice || {},
      heartbeat: manifest.heartbeat || {},
      personality: manifest.personality || {},
    };
  });

  // -- Per-agent config read/write --

  ipcMain.handle('agent:getNotifyVia', (_event, agentName: string) => {
    if (!/^[a-zA-Z0-9_-]+$/.test(agentName)) return 'auto';
    const agentJsonPath = path.join(USER_DATA, 'agents', agentName, 'data', 'agent.json');
    try {
      const manifest = JSON.parse(fs.readFileSync(agentJsonPath, 'utf-8'));
      return (manifest.notify_via as string) || 'auto';
    } catch {
      return 'auto';
    }
  });

  ipcMain.handle('agent:updateConfig', (_event, agentName: string, updates: Record<string, unknown>) => {
    if (!/^[a-zA-Z0-9_-]+$/.test(agentName)) {
      log.warn(`agent:updateConfig: invalid agent name "${agentName}"`);
      return;
    }
    saveAgentConfig(agentName, updates);
  });

  // -- Ask-user (MCP ask_user -> GUI dialog) --

  ipcMain.handle('ask:respond', (_event, requestId: string, response: string | boolean | null) => {
    // Verify the requestId matches the active ask dialog to prevent stale/fabricated responses
    if (!ctx.pendingAskId || ctx.pendingAskId !== requestId) {
      log.warn(`ask:respond ignored: requestId mismatch (expected ${ctx.pendingAskId}, got ${requestId})`);
      return;
    }
    // If a destination was set (secure_input), route the value before writing the response
    let destinationFailed = false;
    if (ctx.pendingAskDestination && typeof response === 'string' && response) {
      const dest = ctx.pendingAskDestination;
      if (dest.startsWith('secret:')) {
        const key = dest.slice('secret:'.length);
        if (!saveEnvVar(key, response)) {
          log.warn(`ask:respond - secret key rejected by whitelist: ${key}`);
          destinationFailed = true;
        }
      } else if (dest.startsWith('config:')) {
        const key = dest.slice('config:'.length);
        // Only allow safe config keys - reject anything that could change
        // executable paths, binary locations, or security-sensitive settings
        const SAFE_CONFIG_KEYS = new Set([
          'USER_NAME', 'MUTE_BY_DEFAULT', 'EYE_MODE_DEFAULT',
          'INPUT_MODE', 'VOICE_CALL_MODE', 'WAKE_WORD_ENABLED', 'ADAPTIVE_EFFORT',
          'NOTIFICATIONS_ENABLED', 'WINDOW_WIDTH', 'WINDOW_HEIGHT',
        ]);
        if (!SAFE_CONFIG_KEYS.has(key)) {
          log.warn(`ask:respond - config key rejected by allowlist: ${key}`);
          destinationFailed = true;
        } else {
          saveUserConfig({ [key]: response });
        }
      }
    }
    writeAskResponse(requestId, response, destinationFailed, ctx.pendingAskAgent || undefined);
    ctx.pendingAskId = null;
    ctx.pendingAskDestination = null;
    ctx.pendingAskAgent = null;
  });

  // -- Agent CRUD (for org management UI) --

  ipcMain.handle('agent:listAll', () => {
    // We also expose `topLevel` so the Settings UI can split agents into
    // "Primary Agents" (top-level standalone, lives at agents/<name>/data)
    // and "Organisations" (nested at agents/<org>/<name>/data) without
    // conflating with the org.slug label which is used for categorization
    // even on standalone agents (e.g. xan has slug='system').
    return discoverAgents().map((a) => {
      const manifest = findManifest(a.name) || {};
      const org = manifest.org as Record<string, unknown> | undefined;
      const state = getAgentState(a.name);
      const topLevel = fs.existsSync(path.join(USER_DATA, 'agents', a.name, 'data'));
      return {
        ...a,
        orgSlug: (org?.slug as string) ?? null,
        reportsTo: (org?.reports_to as string) ?? null,
        canAddressUser: (org?.can_address_user as boolean) ?? ((org?.tier as number) ?? 1) <= 1,
        enabled: state.enabled,
        topLevel,
      };
    });
  });

  ipcMain.handle('agent:getManifest', (_event, name: string) => {
    if (!isValidAgentName(name)) throw new Error('Invalid agent name');
    const manifest = findManifest(name);
    if (!manifest) return null;
    return manifest;
  });

  ipcMain.handle('agent:updateManifest', (_event, name: string, updates: Record<string, unknown>) => {
    if (!isValidAgentName(name)) throw new Error('Invalid agent name');
    saveAgentConfig(name, updates);
  });

  ipcMain.handle('agent:getPrompt', (_event, name: string, promptName: string) => {
    if (!isValidAgentName(name)) throw new Error('Invalid agent name');
    if (!/^[a-zA-Z0-9_-]+$/.test(promptName.replace(/\.md$/, ''))) {
      throw new Error('Invalid prompt name');
    }
    // Read directly from agent's prompts directory without mutating config singleton.
    // This avoids the TOCTOU race where reloadForAgent corrupts config for concurrent callers.
    const stem = promptName.endsWith('.md') ? promptName.slice(0, -3) : promptName;
    // The on-disk convention is `<name>_prompt.md` for the system prompt and
    // plain `<name>.md` for everything else (soul.md, heartbeat.md). Callers
    // historically pass either `system` or `system_prompt` - try both stems
    // so neither breaks. Order matters: prefer the underscore form first
    // since that's what the bootstrap actually writes.
    const candidates = stem === 'system'
      ? ['system_prompt.md', 'system.md']
      : [`${stem}.md`];
    const searchDirs = [
      path.join(USER_DATA, 'agents', name, 'prompts'),
      path.join(BUNDLE_ROOT, 'agents', name, 'prompts'),
    ];
    for (const dir of searchDirs) {
      for (const filename of candidates) {
        const fp = path.join(dir, filename);
        if (fs.existsSync(fp)) {
          return fs.readFileSync(fp, 'utf-8');
        }
      }
    }
    return '';
  });

  ipcMain.handle('agent:updatePrompt', (_event, name: string, promptName: string, content: string) => {
    if (!isValidAgentName(name)) throw new Error('Invalid agent name');
    // Validate promptName - only allow simple filenames, no path traversal
    if (!/^[a-zA-Z0-9_-]+$/.test(promptName.replace(/\.md$/, ''))) {
      throw new Error('Invalid prompt name');
    }
    // Mirror the read-side aliasing: callers may pass `system` but the
    // canonical on-disk filename is `system_prompt.md`. Without this
    // remapping, saving from the editor would create a stale `system.md`
    // alongside the real `system_prompt.md` that the boot path actually
    // loads, and edits would silently never take effect.
    const stem = promptName.endsWith('.md') ? promptName.slice(0, -3) : promptName;
    const filename = stem === 'system' ? 'system_prompt.md' : `${stem}.md`;
    const promptsDir = path.join(USER_DATA, 'agents', name, 'prompts');
    fs.mkdirSync(promptsDir, { recursive: true });
    const promptPath = path.join(promptsDir, filename);
    fs.writeFileSync(promptPath, content, 'utf-8');
  });

  ipcMain.handle('agent:create', async (_event, opts: Record<string, unknown>) => {
    const { createAgent } = await import('../create-agent');
    return createAgent(opts as unknown as Parameters<typeof createAgent>[0]);
  });

  ipcMain.handle('agent:delete', (_event, name: string) => {
    if (!isValidAgentName(name)) throw new Error('Invalid agent name');
    deleteAgent(name);
  });
}

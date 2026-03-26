/**
 * IPC handlers for agent management.
 * Channels: agent:list, agent:listFull, agent:cycle, agent:getState, agent:setState,
 *           agent:switch, deferral:complete, queue:*, mirror:*
 */

import { ipcMain, shell } from 'electron';
import * as path from 'path';
import { getConfig, saveAgentConfig, saveUserConfig, saveEnvVar } from '../config';
import {
  discoverUiAgents, cycleAgent, getAgentState, setAgentState,
  suspendAgentSession, resumeAgentSession,
  writeAskResponse,
} from '../agent-manager';
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
        if (ctx.currentSession.cliSessionId) {
          suspendAgentSession(ctx.currentAgentName!, ctx.currentSession.cliSessionId, ctx.currentSession.turnHistory);
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
    writeAskResponse(requestId, response, destinationFailed);
    ctx.pendingAskId = null;
    ctx.pendingAskDestination = null;
  });
}

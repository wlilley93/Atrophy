/**
 * IPC handlers for Telegram daemon and bot management.
 * Channels: telegram:startDaemon, telegram:stopDaemon, telegram:isRunning,
 *           telegram:discoverChatId, telegram:saveAgentBotToken,
 *           telegram:setBotPhoto, telegram:getAgentConfig
 */

import { ipcMain } from 'electron';
import { getConfig, saveAgentConfig } from '../config';
import { findManifest } from '../agent-manager';
import { startDaemon, stopDaemon, isDaemonRunning, discoverChatId } from '../channels/telegram';
import type { IpcContext } from '../ipc-handlers';

const AGENT_NAME_RE = /^[a-zA-Z0-9_-]+$/;

export function registerTelegramHandlers(_ctx: IpcContext): void {
  ipcMain.handle('telegram:startDaemon', () => {
    return startDaemon();
  });

  ipcMain.handle('telegram:stopDaemon', () => {
    stopDaemon();
  });

  ipcMain.handle('telegram:isRunning', () => {
    return isDaemonRunning();
  });

  ipcMain.handle('telegram:discoverChatId', async (_event, botToken: string, agentName?: string) => {
    if (agentName && !AGENT_NAME_RE.test(agentName)) throw new Error('Invalid agent name');
    const result = await discoverChatId(botToken);
    if (result) {
      const c = getConfig();
      const targetAgent = agentName || c.AGENT_NAME;
      saveAgentConfig(targetAgent, { TELEGRAM_CHAT_ID: result.chatId });
      if (targetAgent === c.AGENT_NAME) {
        (c as unknown as Record<string, unknown>).TELEGRAM_CHAT_ID = result.chatId;
      }
    }
    return result;
  });

  ipcMain.handle('telegram:saveAgentBotToken', async (_event, agentName: string, botToken: string) => {
    if (!AGENT_NAME_RE.test(agentName)) throw new Error('Invalid agent name');
    saveAgentConfig(agentName, { TELEGRAM_BOT_TOKEN: botToken });
    const c = getConfig();
    if (agentName === c.AGENT_NAME) {
      (c as unknown as Record<string, unknown>).TELEGRAM_BOT_TOKEN = botToken;
    }
  });

  ipcMain.handle('telegram:setBotPhoto', async (_event, agentName: string, botToken: string) => {
    if (!AGENT_NAME_RE.test(agentName)) throw new Error('Invalid agent name');
    const { getReferenceImages } = await import('../jobs/generate-avatar');
    const { setBotProfilePhoto } = await import('../channels/telegram');
    const refs = getReferenceImages(agentName);
    if (refs.length === 0) return false;
    return setBotProfilePhoto(refs[0], botToken);
  });

  // Read agent's Telegram config directly from manifest to avoid mutating
  // the shared config singleton (which races with the Telegram daemon).
  ipcMain.handle('telegram:getAgentConfig', async (_event, agentName: string) => {
    if (!AGENT_NAME_RE.test(agentName)) throw new Error('Invalid agent name');
    const manifest = findManifest(agentName) || {};
    const channels = (manifest.channels as Record<string, Record<string, string>> | undefined) || {};
    const tg = channels.telegram || {};
    // Resolve env var references from the manifest
    const botTokenEnv = tg.bot_token_env;
    const chatIdEnv = tg.chat_id_env;
    return {
      botToken: botTokenEnv && process.env[botTokenEnv] ? '***' : '',
      chatId: chatIdEnv ? process.env[chatIdEnv] || '' : '',
    };
  });
}

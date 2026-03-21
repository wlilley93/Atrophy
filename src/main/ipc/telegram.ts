/**
 * IPC handlers for Telegram daemon and bot management.
 * Channels: telegram:startDaemon, telegram:stopDaemon, telegram:isRunning,
 *           telegram:discoverChatId, telegram:saveAgentBotToken,
 *           telegram:setBotPhoto, telegram:getAgentConfig
 */

import { ipcMain } from 'electron';
import { getConfig, saveAgentConfig } from '../config';
import { startDaemon, stopDaemon, isDaemonRunning, discoverChatId } from '../channels/telegram';
import type { IpcContext } from '../ipc-handlers';

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
    saveAgentConfig(agentName, { TELEGRAM_BOT_TOKEN: botToken });
    const c = getConfig();
    if (agentName === c.AGENT_NAME) {
      (c as unknown as Record<string, unknown>).TELEGRAM_BOT_TOKEN = botToken;
    }
  });

  ipcMain.handle('telegram:setBotPhoto', async (_event, agentName: string, botToken: string) => {
    const { getReferenceImages } = await import('../jobs/generate-avatar');
    const { setBotProfilePhoto } = await import('../channels/telegram');
    const refs = getReferenceImages(agentName);
    if (refs.length === 0) return false;
    return setBotProfilePhoto(refs[0], botToken);
  });

  ipcMain.handle('telegram:getAgentConfig', async (_event, agentName: string) => {
    const c = getConfig();
    const original = c.AGENT_NAME;
    c.reloadForAgent(agentName);
    const result = {
      botToken: c.TELEGRAM_BOT_TOKEN ? '***' : '',
      chatId: c.TELEGRAM_CHAT_ID,
    };
    c.reloadForAgent(original);
    return result;
  });
}

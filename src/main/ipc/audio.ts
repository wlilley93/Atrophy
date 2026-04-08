/**
 * IPC handlers for audio playback, muting, and voice agent.
 * Channels: audio:playIntro, audio:playAgentAudio, audio:stopPlayback,
 *           audio:setMuted, audio:isMuted, voice-agent:*
 */

import { ipcMain } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { getConfig, BUNDLE_ROOT } from '../config';
import { getAgentDir } from '../agent-manager';
import { playAudio, clearAudioQueue, stopCurrentPlayback, setMuted, isMuted } from '../tts';
import type { IpcContext } from '../ipc-handlers';

export function registerAudioHandlers(_ctx: IpcContext): void {
  // -- Intro audio --

  ipcMain.handle('audio:playIntro', async () => {
    const c = getConfig();
    const introCandidates = [
      path.join(getAgentDir(c.AGENT_NAME), 'audio', 'intro.mp3'),
      path.join(BUNDLE_ROOT, 'agents', c.AGENT_NAME, 'audio', 'intro.mp3'),
    ];
    for (const introPath of introCandidates) {
      if (fs.existsSync(introPath)) {
        try {
          await playAudio(introPath, undefined, false);
        } catch { /* non-critical */ }
        break;
      }
    }
  });

  // Play any named audio file from the current agent's audio/ directory
  ipcMain.handle('audio:playAgentAudio', async (_event, filename: string) => {
    // Validate filename to prevent path traversal
    if (!/^[a-zA-Z0-9_-]+\.(mp3|wav|m4a)$/.test(filename)) return;
    const c = getConfig();
    // Check user data first, then bundle
    const candidates = [
      path.join(getAgentDir(c.AGENT_NAME), 'audio', filename),
      path.join(BUNDLE_ROOT, 'agents', c.AGENT_NAME, 'audio', filename),
    ];
    for (const audioPath of candidates) {
      if (fs.existsSync(audioPath)) {
        try {
          await playAudio(audioPath, undefined, false);
        } catch { /* non-critical */ }
        break;
      }
    }
  });

  ipcMain.handle('audio:stopPlayback', () => {
    clearAudioQueue();
    stopCurrentPlayback();
  });

  ipcMain.handle('audio:setMuted', (_event, muted: boolean) => {
    setMuted(muted);
  });

  ipcMain.handle('audio:isMuted', () => {
    return isMuted();
  });

  // -- Voice agent --

  ipcMain.handle('voice-agent:start', async () => {
    const { startVoiceAgent } = await import('../voice-agent');
    return startVoiceAgent();
  });

  ipcMain.handle('voice-agent:stop', async () => {
    const { stopVoiceAgent } = await import('../voice-agent');
    stopVoiceAgent();
  });

  ipcMain.handle('voice-agent:sendText', async (_event, text: string) => {
    const { sendText } = await import('../voice-agent');
    await sendText(text);
  });

  ipcMain.handle('voice-agent:status', async () => {
    const { getVoiceAgentStatus } = await import('../voice-agent');
    return getVoiceAgentStatus();
  });

  ipcMain.handle('voice-agent:setMic', async (_event, muted: boolean) => {
    const { setMicMuted } = await import('../voice-agent');
    setMicMuted(muted);
  });

  ipcMain.handle('voice-agent:setAudio', async (_event, enabled: boolean) => {
    const { setAudioOutputEnabled } = await import('../voice-agent');
    setAudioOutputEnabled(enabled);
  });
}

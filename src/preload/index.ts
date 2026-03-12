/**
 * Preload script - exposes typed API to renderer via contextBridge.
 */

import { contextBridge, ipcRenderer } from 'electron';

export interface AtrophyAPI {
  // Inference
  sendMessage: (text: string) => Promise<void>;
  onTextDelta: (cb: (text: string) => void) => () => void;
  onSentenceReady: (cb: (sentence: string, audioPath: string) => void) => () => void;
  onToolUse: (cb: (name: string) => void) => () => void;
  onDone: (cb: (fullText: string) => void) => () => void;
  onCompacting: (cb: () => void) => () => void;
  onError: (cb: (message: string) => void) => () => void;
  stopInference: () => Promise<void>;

  // Audio capture
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<string>;
  sendAudioChunk: (buffer: ArrayBuffer) => void;

  // TTS playback events
  onTtsStarted: (cb: (index: number) => void) => () => void;
  onTtsDone: (cb: (index: number) => void) => () => void;
  onTtsQueueEmpty: (cb: () => void) => () => void;

  // Wake word
  onWakeWordStart: (cb: (chunkSeconds: number) => void) => () => void;
  onWakeWordStop: (cb: () => void) => () => void;
  sendWakeWordChunk: (buffer: ArrayBuffer) => void;

  // Agents
  switchAgent: (name: string) => Promise<{ agentName: string; agentDisplayName: string }>;
  getAgents: () => Promise<string[]>;
  getAgentsFull: () => Promise<{ name: string; display_name: string; description: string; role: string }[]>;

  // Config
  getConfig: () => Promise<Record<string, unknown>>;
  updateConfig: (updates: Record<string, unknown>) => Promise<void>;

  // Setup
  needsSetup: () => Promise<boolean>;
  wizardInference: (text: string) => Promise<string>;

  // Window
  toggleFullscreen: () => Promise<void>;
  minimizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;

  // Queue messages (from background jobs)
  onQueueMessage: (cb: (msg: { text: string; source: string }) => void) => () => void;

  // Opening line
  getOpeningLine: () => Promise<string>;

  // Login item
  isLoginItemEnabled: () => Promise<boolean>;
  toggleLoginItem: (enabled: boolean) => Promise<void>;

  // Avatar
  getAvatarVideoPath: (colour?: string, clip?: string) => Promise<string | null>;

  // Usage & activity
  getUsage: (days?: number) => Promise<unknown>;
  getActivity: (days?: number, limit?: number) => Promise<unknown>;
}

function createListener(channel: string) {
  return (cb: (...args: unknown[]) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, ...args: unknown[]) => cb(...args);
    ipcRenderer.on(channel, handler);
    return () => ipcRenderer.removeListener(channel, handler);
  };
}

const api: AtrophyAPI = {
  // Inference
  sendMessage: (text) => ipcRenderer.invoke('inference:send', text),
  onTextDelta: createListener('inference:textDelta') as AtrophyAPI['onTextDelta'],
  onSentenceReady: createListener('inference:sentenceReady') as AtrophyAPI['onSentenceReady'],
  onToolUse: createListener('inference:toolUse') as AtrophyAPI['onToolUse'],
  onDone: createListener('inference:done') as AtrophyAPI['onDone'],
  onCompacting: createListener('inference:compacting') as AtrophyAPI['onCompacting'],
  onError: createListener('inference:error') as AtrophyAPI['onError'],
  stopInference: () => ipcRenderer.invoke('inference:stop'),

  // Audio capture
  startRecording: () => ipcRenderer.invoke('audio:start'),
  stopRecording: () => ipcRenderer.invoke('audio:stop'),
  sendAudioChunk: (buffer) => ipcRenderer.send('audio:chunk', buffer),

  // TTS playback events
  onTtsStarted: createListener('tts:started') as AtrophyAPI['onTtsStarted'],
  onTtsDone: createListener('tts:done') as AtrophyAPI['onTtsDone'],
  onTtsQueueEmpty: createListener('tts:queueEmpty') as AtrophyAPI['onTtsQueueEmpty'],

  // Wake word
  onWakeWordStart: createListener('wakeword:start') as AtrophyAPI['onWakeWordStart'],
  onWakeWordStop: createListener('wakeword:stop') as AtrophyAPI['onWakeWordStop'],
  sendWakeWordChunk: (buffer) => ipcRenderer.send('wakeword:chunk', buffer),

  // Agents
  switchAgent: (name) => ipcRenderer.invoke('agent:switch', name),
  getAgents: () => ipcRenderer.invoke('agent:list'),
  getAgentsFull: () => ipcRenderer.invoke('agent:listFull'),

  // Config
  getConfig: () => ipcRenderer.invoke('config:get'),
  updateConfig: (updates) => ipcRenderer.invoke('config:update', updates),

  // Setup
  needsSetup: () => ipcRenderer.invoke('setup:check'),
  wizardInference: (text) => ipcRenderer.invoke('setup:inference', text),

  // Window
  toggleFullscreen: () => ipcRenderer.invoke('window:toggleFullscreen'),
  minimizeWindow: () => ipcRenderer.invoke('window:minimize'),
  closeWindow: () => ipcRenderer.invoke('window:close'),

  // Queue messages
  onQueueMessage: createListener('queue:message') as AtrophyAPI['onQueueMessage'],

  // Opening line
  getOpeningLine: () => ipcRenderer.invoke('opening:get'),

  // Login item
  isLoginItemEnabled: () => ipcRenderer.invoke('install:isEnabled'),
  toggleLoginItem: (enabled) => ipcRenderer.invoke('install:toggle', enabled),

  // Avatar
  getAvatarVideoPath: (colour, clip) => ipcRenderer.invoke('avatar:getVideoPath', colour, clip),

  // Usage & activity
  getUsage: (days) => ipcRenderer.invoke('usage:all', days),
  getActivity: (days, limit) => ipcRenderer.invoke('activity:all', days, limit),
};

contextBridge.exposeInMainWorld('atrophy', api);

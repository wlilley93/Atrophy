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
  switchAgent: (name: string) => Promise<{ agentName: string; agentDisplayName: string; customSetup: string | null }>;
  getAgents: () => Promise<string[]>;
  getAgentsFull: () => Promise<{ name: string; display_name: string; description: string; role: string }[]>;

  // Config
  getConfig: () => Promise<Record<string, unknown>>;
  reloadConfig: () => Promise<void>;
  applyConfig: (updates: Record<string, unknown>) => Promise<void>;
  updateConfig: (updates: Record<string, unknown>) => Promise<void>;

  // Setup
  needsSetup: () => Promise<boolean>;
  wizardInference: (text: string) => Promise<string>;
  createAgent: (config: Record<string, string>) => Promise<Record<string, unknown>>;
  saveSecret: (key: string, value: string) => Promise<void>;
  setupSpeak: (text: string) => Promise<void>;
  startGoogleOAuth: (wantWorkspace: boolean, wantExtra: boolean) => Promise<string>;

  // Window
  toggleFullscreen: () => Promise<void>;
  toggleAlwaysOnTop: () => Promise<void>;
  minimizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;

  // Queue messages (from background jobs)
  onQueueMessage: (cb: (msg: { text: string; source: string }) => void) => () => void;

  // Opening line
  getOpeningLine: () => Promise<string>;

  // Login item
  isLoginItemEnabled: () => Promise<boolean>;
  toggleLoginItem: (enabled: boolean) => Promise<void>;

  // Auto-updater
  checkForUpdates: () => Promise<void>;
  downloadUpdate: () => Promise<void>;
  quitAndInstall: () => Promise<void>;
  onUpdateAvailable: (cb: (info: { version: string; releaseNotes: unknown }) => void) => () => void;
  onUpdateNotAvailable: (cb: () => void) => () => void;
  onUpdateProgress: (cb: (progress: { percent: number; bytesPerSecond: number; transferred: number; total: number }) => void) => () => void;
  onUpdateDownloaded: (cb: (info: { version: string }) => void) => () => void;
  onUpdateError: (cb: (message: string) => void) => () => void;

  // Avatar
  getAvatarAmbientPath: () => Promise<string | null>;
  getAvatarVideoPath: (colour?: string, clip?: string) => Promise<string | null>;
  listAvatarLoops: () => Promise<string[]>;
  onAvatarDownloadStart: (cb: () => void) => () => void;
  onAvatarDownloadProgress: (cb: (data: { percent: number; transferred: number; total: number }) => void) => () => void;
  onAvatarDownloadComplete: (cb: () => void) => () => void;
  onAvatarDownloadError: (cb: (message: string) => void) => () => void;

  // Intro audio
  playIntroAudio: () => Promise<void>;
  playAgentAudio: (filename: string) => Promise<void>;
  stopPlayback: () => Promise<void>;
  setMuted: (muted: boolean) => Promise<void>;
  isMuted: () => Promise<boolean>;

  // GitHub auth
  githubAuthStatus: () => Promise<{ installed: boolean; authenticated: boolean; account: string }>;
  githubAuthLogin: () => Promise<{ success: boolean; error?: string }>;

  // Shutdown
  requestShutdown: () => Promise<void>;
  onShutdownRequested: (cb: () => void) => () => void;

  // Usage & activity
  getUsage: (days?: number) => Promise<unknown>;
  getActivity: (days?: number, limit?: number) => Promise<unknown>;

  // Agent deferral
  completeDeferral: (data: { target: string; context: string; user_question: string }) => Promise<{ agentName: string; agentDisplayName: string }>;
  onDeferralRequest: (cb: (data: { target: string; context: string; user_question: string }) => void) => () => void;

  // Ask-user (agent asks user a question via MCP)
  onAskUser: (cb: (data: { question: string; action_type: string; request_id: string; input_type?: string; label?: string; destination?: string }) => void) => () => void;
  respondToAsk: (requestId: string, response: string | boolean | null) => Promise<void>;

  // Artefacts
  getArtefactGallery: () => Promise<unknown[]>;
  getArtefactContent: (filePath: string) => Promise<string | null>;
  onArtefactLoading: (cb: (data: { name: string; type: string }) => void) => () => void;

  // Inline artifacts (emitted from agent response text)
  onArtifact: (cb: (artifact: { id: string; type: string; title: string; language: string; content: string }) => void) => () => void;

  // Jobs / Cron
  getJobs: () => Promise<unknown[]>;
  toggleCron: (enabled: boolean) => Promise<void>;
  runJob: (name: string) => Promise<unknown>;
  getJobHistory: () => Promise<unknown[]>;
  readJobLog: (name: string, lines?: number) => Promise<string>;

  // Keep Awake
  toggleKeepAwake: () => Promise<boolean>;
  isKeepAwakeActive: () => Promise<boolean>;

  // Telegram daemon
  startTelegramDaemon: () => Promise<boolean>;
  stopTelegramDaemon: () => Promise<void>;
  isTelegramDaemonRunning: () => Promise<boolean>;
  discoverTelegramChatId: (botToken: string) => Promise<{ chatId: string; username?: string } | null>;

  // Mirror setup
  mirrorUploadPhoto: (photoData: ArrayBuffer, filename: string) => Promise<string>;
  mirrorGenerateAvatar: () => Promise<string[]>;
  mirrorSaveVoiceId: (voiceId: string) => Promise<void>;
  mirrorCheckSetup: () => Promise<{ hasPhoto: boolean; hasLoops: boolean }>;
  mirrorOpenExternal: (url: string) => Promise<void>;
  mirrorDownloadAssets: () => Promise<void>;
  onMirrorAvatarProgress: (cb: (progress: { phase: string; clipIndex?: number; totalClips?: number; message?: string }) => void) => () => void;

  // Agent message queues
  drainAgentQueue: (agentName: string) => Promise<unknown[]>;
  drainAllAgentQueues: () => Promise<Record<string, unknown[]>>;

  // Voice call mode
  startCall: () => Promise<void>;
  stopCall: () => Promise<void>;
  getCallStatus: () => Promise<{ active: boolean; status: string; muted: boolean }>;
  setCallMuted: (muted: boolean) => Promise<void>;
  sendCallChunk: (buffer: ArrayBuffer) => void;
  onCallStatusChanged: (cb: (status: string) => void) => () => void;

  // Status (active/away)
  getStatus: () => Promise<{ status: string; reason: string; since: string }>;
  setStatus: (status: 'active' | 'away', reason?: string) => Promise<void>;
  onStatusChanged: (cb: (status: string) => void) => () => void;

  // Bundle updater (hot code reload)
  getBundleStatus: () => Promise<{
    activeVersion: string;
    hotBundleActive: boolean;
    hotBundleVersion: string | null;
    pending: { version: string; pendingRestart: boolean } | null;
  }>;
  checkBundleUpdate: () => Promise<string | null>;
  clearHotBundle: () => Promise<void>;
  onBundleReady: (cb: (info: { version: string }) => void) => () => void;
  onBundleProgress: (cb: (percent: number) => void) => () => void;

  // Generic listener
  on: (channel: string, cb: (...args: unknown[]) => void) => () => void;
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
  reloadConfig: () => ipcRenderer.invoke('config:reload'),
  applyConfig: (updates) => ipcRenderer.invoke('config:apply', updates),
  updateConfig: (updates) => ipcRenderer.invoke('config:update', updates),

  // Setup
  needsSetup: () => ipcRenderer.invoke('setup:check'),
  wizardInference: (text) => ipcRenderer.invoke('setup:inference', text),
  createAgent: (config) => ipcRenderer.invoke('setup:createAgent', config),
  saveSecret: (key, value) => ipcRenderer.invoke('setup:saveSecret', key, value),
  setupSpeak: (text) => ipcRenderer.invoke('setup:speak', text),
  startGoogleOAuth: (wantWorkspace, wantExtra) => ipcRenderer.invoke('setup:googleOAuth', wantWorkspace, wantExtra),

  // Window
  toggleFullscreen: () => ipcRenderer.invoke('window:toggleFullscreen'),
  toggleAlwaysOnTop: () => ipcRenderer.invoke('window:toggleAlwaysOnTop'),
  minimizeWindow: () => ipcRenderer.invoke('window:minimize'),
  closeWindow: () => ipcRenderer.invoke('window:close'),

  // Queue messages
  onQueueMessage: createListener('queue:message') as AtrophyAPI['onQueueMessage'],

  // Opening line
  getOpeningLine: () => ipcRenderer.invoke('opening:get'),

  // Login item
  isLoginItemEnabled: () => ipcRenderer.invoke('install:isEnabled'),
  toggleLoginItem: (enabled) => ipcRenderer.invoke('install:toggle', enabled),

  // Auto-updater
  checkForUpdates: () => ipcRenderer.invoke('updater:check'),
  downloadUpdate: () => ipcRenderer.invoke('updater:download'),
  quitAndInstall: () => ipcRenderer.invoke('updater:quitAndInstall'),
  onUpdateAvailable: createListener('updater:available') as AtrophyAPI['onUpdateAvailable'],
  onUpdateNotAvailable: createListener('updater:not-available') as AtrophyAPI['onUpdateNotAvailable'],
  onUpdateProgress: createListener('updater:progress') as AtrophyAPI['onUpdateProgress'],
  onUpdateDownloaded: createListener('updater:downloaded') as AtrophyAPI['onUpdateDownloaded'],
  onUpdateError: createListener('updater:error') as AtrophyAPI['onUpdateError'],

  // Avatar
  getAvatarAmbientPath: () => ipcRenderer.invoke('avatar:getAmbientPath'),
  getAvatarVideoPath: (colour, clip) => ipcRenderer.invoke('avatar:getVideoPath', colour, clip),
  listAvatarLoops: () => ipcRenderer.invoke('avatar:listLoops'),
  onAvatarDownloadStart: createListener('avatar:download-start') as AtrophyAPI['onAvatarDownloadStart'],
  onAvatarDownloadProgress: createListener('avatar:download-progress') as AtrophyAPI['onAvatarDownloadProgress'],
  onAvatarDownloadComplete: createListener('avatar:download-complete') as AtrophyAPI['onAvatarDownloadComplete'],
  onAvatarDownloadError: createListener('avatar:download-error') as AtrophyAPI['onAvatarDownloadError'],

  // Intro audio
  playIntroAudio: () => ipcRenderer.invoke('audio:playIntro'),
  playAgentAudio: (filename) => ipcRenderer.invoke('audio:playAgentAudio', filename),
  stopPlayback: () => ipcRenderer.invoke('audio:stopPlayback'),
  setMuted: (muted) => ipcRenderer.invoke('audio:setMuted', muted),
  isMuted: () => ipcRenderer.invoke('audio:isMuted'),

  // GitHub auth
  githubAuthStatus: () => ipcRenderer.invoke('github:authStatus'),
  githubAuthLogin: () => ipcRenderer.invoke('github:authLogin'),

  // Shutdown
  requestShutdown: () => ipcRenderer.invoke('app:shutdown'),
  onShutdownRequested: createListener('app:shutdownRequested') as AtrophyAPI['onShutdownRequested'],

  // Usage & activity
  getUsage: (days) => ipcRenderer.invoke('usage:all', days),
  getActivity: (days, limit) => ipcRenderer.invoke('activity:all', days, limit),

  // Agent deferral
  completeDeferral: (data) => ipcRenderer.invoke('deferral:complete', data),
  onDeferralRequest: createListener('deferral:request') as AtrophyAPI['onDeferralRequest'],

  // Ask-user
  onAskUser: createListener('ask:request') as AtrophyAPI['onAskUser'],
  respondToAsk: (requestId, response) => ipcRenderer.invoke('ask:respond', requestId, response),

  // Artefacts
  getArtefactGallery: () => ipcRenderer.invoke('artefact:getGallery'),
  getArtefactContent: (filePath) => ipcRenderer.invoke('artefact:getContent', filePath),
  onArtefactLoading: createListener('artefact:loading') as AtrophyAPI['onArtefactLoading'],

  // Inline artifacts
  onArtifact: createListener('inference:artifact') as AtrophyAPI['onArtifact'],

  // Jobs / Cron
  getJobs: () => ipcRenderer.invoke('cron:list'),
  toggleCron: (enabled) => ipcRenderer.invoke('cron:toggle', enabled),
  runJob: (name) => ipcRenderer.invoke('cron:run', name),
  getJobHistory: () => ipcRenderer.invoke('cron:history'),
  readJobLog: (name, lines) => ipcRenderer.invoke('cron:readLog', name, lines),

  // Keep Awake
  toggleKeepAwake: () => ipcRenderer.invoke('keepAwake:toggle'),
  isKeepAwakeActive: () => ipcRenderer.invoke('keepAwake:isActive'),

  // Telegram daemon
  startTelegramDaemon: () => ipcRenderer.invoke('telegram:startDaemon'),
  stopTelegramDaemon: () => ipcRenderer.invoke('telegram:stopDaemon'),
  isTelegramDaemonRunning: () => ipcRenderer.invoke('telegram:isRunning'),
  discoverTelegramChatId: (botToken) => ipcRenderer.invoke('telegram:discoverChatId', botToken),

  // Mirror setup
  mirrorUploadPhoto: (photoData, filename) => ipcRenderer.invoke('mirror:uploadPhoto', photoData, filename),
  mirrorGenerateAvatar: () => ipcRenderer.invoke('mirror:generateAvatar'),
  mirrorSaveVoiceId: (voiceId) => ipcRenderer.invoke('mirror:saveVoiceId', voiceId),
  mirrorCheckSetup: () => ipcRenderer.invoke('mirror:checkSetup'),
  mirrorOpenExternal: (url) => ipcRenderer.invoke('mirror:openExternal', url),
  mirrorDownloadAssets: () => ipcRenderer.invoke('mirror:downloadAssets'),
  onMirrorAvatarProgress: createListener('mirror:avatarProgress') as AtrophyAPI['onMirrorAvatarProgress'],

  // Agent message queues
  drainAgentQueue: (agentName: string) => ipcRenderer.invoke('queue:drainAgent', agentName),
  drainAllAgentQueues: () => ipcRenderer.invoke('queue:drainAll'),

  // Voice call mode
  startCall: () => ipcRenderer.invoke('call:start', null, null),
  stopCall: () => ipcRenderer.invoke('call:stop'),
  getCallStatus: () => ipcRenderer.invoke('call:status'),
  setCallMuted: (muted) => ipcRenderer.invoke('call:setMuted', muted),
  sendCallChunk: (buffer) => ipcRenderer.send('call:chunk', buffer),
  onCallStatusChanged: createListener('call:statusChanged') as AtrophyAPI['onCallStatusChanged'],

  // Status (active/away)
  getStatus: () => ipcRenderer.invoke('status:get'),
  setStatus: (status, reason) => ipcRenderer.invoke('status:set', status, reason),
  onStatusChanged: createListener('status:changed') as AtrophyAPI['onStatusChanged'],

  // Bundle updater
  getBundleStatus: () => ipcRenderer.invoke('bundle:getStatus'),
  checkBundleUpdate: () => ipcRenderer.invoke('bundle:checkNow'),
  clearHotBundle: () => ipcRenderer.invoke('bundle:clear'),
  onBundleReady: createListener('bundle:ready') as AtrophyAPI['onBundleReady'],
  onBundleProgress: createListener('bundle:downloadProgress') as AtrophyAPI['onBundleProgress'],

  // Channel listener with allowlist
  on: (channel, cb) => {
    const ALLOWED_CHANNELS = new Set([
      'inference:textDelta', 'inference:sentenceReady', 'inference:toolUse',
      'inference:done', 'inference:compacting', 'inference:error',
      'tts:started', 'tts:done', 'tts:queueEmpty',
      'wakeword:start', 'wakeword:stop',
      'queue:message', 'deferral:request',
      'updater:available', 'updater:not-available', 'updater:progress',
      'updater:downloaded', 'updater:error',
      'canvas:updated', 'artefact:updated', 'artefact:loading', 'ask:request',
      'inference:artifact', 'inference:contextUsage',
      'journal:nudge', 'status:changed',
      'avatar:download-start', 'avatar:download-progress',
      'avatar:download-complete', 'avatar:download-error',
      'mirror:avatarProgress',
      'call:statusChanged',
      'app:shutdownRequested',
      'bundle:ready', 'bundle:downloadProgress',
    ]);
    if (!ALLOWED_CHANNELS.has(channel)) {
      console.warn(`IPC channel not allowed: ${channel}`);
      return () => {};
    }
    const handler = (_event: Electron.IpcRendererEvent, ...args: unknown[]) => cb(...args);
    ipcRenderer.on(channel, handler);
    return () => ipcRenderer.removeListener(channel, handler);
  },
};

contextBridge.exposeInMainWorld('atrophy', api);

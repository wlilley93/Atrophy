/**
 * Preload script - exposes typed API to renderer via contextBridge.
 */

import { contextBridge, ipcRenderer } from 'electron';

export interface AtrophyAPI {
  // Inference
  sendMessage: (text: string) => Promise<void>;
  onTextDelta: (cb: (text: string) => void) => () => void;
  onSentenceReady: (cb: (sentence: string, index: number, ttsActive: boolean) => void) => () => void;
  onToolUse: (cb: (name: string, toolId?: string) => void) => () => void;
  onToolResult: (cb: (toolId: string, toolName: string, output: string) => void) => () => void;
  onThinkingDelta: (cb: (text: string) => void) => () => void;
  onDone: (cb: (fullText: string) => void) => () => void;
  onCompacting: (cb: () => void) => () => void;
  onError: (cb: (message: string) => void) => () => void;
  onEmotionUpdated: (cb: (data: { emotions: Record<string, number>; trust: Record<string, number> }) => void) => () => void;
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
  cycleAgent: (direction: number) => Promise<string | null>;
  getAgents: () => Promise<string[]>;
  getAgentsFull: () => Promise<{ name: string; display_name: string; description: string; role: string }[]>;
  onAgentSwitched: (cb: (data: { agentName: string; agentDisplayName: string; customSetup?: string | null }) => void) => () => void;
  getAgentNotifyVia: (agentName: string) => Promise<string>;
  getAgentDetail: (agentName: string) => Promise<Record<string, unknown> | null>;
  updateAgentConfig: (agentName: string, updates: Record<string, unknown>) => Promise<void>;

  // Agent management (settings)
  listAllAgents: () => Promise<{ name: string; display_name: string; description: string; role: string; tier: number; orgSlug: string | null; reportsTo: string | null; canAddressUser: boolean; enabled: boolean }[]>;
  getAgentManifest: (name: string) => Promise<Record<string, unknown>>;
  updateAgentManifest: (name: string, updates: Record<string, unknown>) => Promise<void>;
  getAgentPrompt: (name: string, promptName: string) => Promise<string>;
  updateAgentPrompt: (name: string, promptName: string, content: string) => Promise<void>;
  quickCreateAgent: (opts: { name: string; displayName: string; role: string; orgSlug?: string; tier?: number; reportsTo?: string; specialism?: string }) => Promise<Record<string, unknown>>;
  deleteAgent: (name: string) => Promise<void>;

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
  verifyElevenLabs: (key: string) => Promise<{ ok: boolean; error?: string }>;
  verifyFal: (key: string) => Promise<{ ok: boolean; error?: string }>;
  verifyTelegram: (token: string) => Promise<{ ok: boolean; error?: string }>;
  setupSpeak: (text: string) => Promise<void>;
  startGoogleOAuth: (wantWorkspace: boolean, wantExtra: boolean) => Promise<string>;
  healthCheck: () => Promise<{ ok: boolean; version?: string; bin?: string; hint?: string; error?: string; help?: string }>;

  // Window
  toggleFullscreen: () => Promise<void>;
  toggleAlwaysOnTop: () => Promise<void>;
  minimizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;
  getWindowSize: () => Promise<{ width: number; height: number }>;
  setWindowSize: (width: number, height: number, animate?: boolean) => Promise<void>;

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
  getUsageDetail: (agentName: string, days?: number) => Promise<unknown>;
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

  // Jobs / Cron (v2 - in-process scheduler)
  getSchedule: () => Promise<unknown[]>;
  getJobHistory: () => Promise<unknown[]>;
  runJobNow: (agentName: string, jobName: string) => Promise<void>;
  getSchedulerStatus: () => Promise<{ schedule: unknown[] }>;
  addJob: (agentName: string, jobName: string, config: { schedule: string; script: string; description?: string }) => Promise<void>;
  editJob: (agentName: string, jobName: string, updates: Record<string, unknown>) => Promise<void>;
  deleteJob: (agentName: string, jobName: string) => Promise<void>;

  // Keep Awake
  toggleKeepAwake: () => Promise<boolean>;
  isKeepAwakeActive: () => Promise<boolean>;

  // Telegram daemon
  startTelegramDaemon: () => Promise<boolean>;
  stopTelegramDaemon: () => Promise<void>;
  isTelegramDaemonRunning: () => Promise<boolean>;
  discoverTelegramChatId: (botToken: string, agentName?: string) => Promise<{ chatId: string; username?: string } | null>;
  saveTelegramBotToken: (agentName: string, botToken: string) => Promise<void>;
  setTelegramBotPhoto: (agentName: string, botToken: string) => Promise<boolean>;
  getTelegramAgentConfig: (agentName: string) => Promise<{ botToken: string; chatId: string }>;

  // Logs
  getLogBuffer: () => Promise<{ timestamp: number; level: string; tag: string; message: string }[]>;
  onLogEntry: (cb: (entry: { timestamp: number; level: string; tag: string; message: string }) => void) => () => void;
  log: (level: string, tag: string, message: string) => void;
  readLogFile: () => Promise<string>;
  readPrevLogFile: () => Promise<string>;
  parseLogFile: (contents: string) => Promise<{ timestamp: number; level: string; tag: string; message: string }[]>;

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

  // Voice agent
  voiceAgent: {
    start: () => Promise<boolean>;
    stop: () => Promise<void>;
    sendText: (text: string) => Promise<void>;
    status: () => Promise<unknown>;
    setMic: (muted: boolean) => Promise<void>;
    setAudio: (enabled: boolean) => Promise<void>;
    onAudio: (cb: (data: ArrayBuffer) => void) => () => void;
    onStatus: (cb: (status: string) => void) => () => void;
    onTranscript: (cb: (text: string) => void) => () => void;
    onResponse: (cb: (text: string) => void) => () => void;
  };

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

  // Restart for update
  restartForUpdate: () => Promise<void>;

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

  // Organizations
  listOrgs: () => Promise<Array<{ name: string; slug: string; type: string; purpose: string; created: string; principal: string | null }>>;
  getOrgDetail: (slug: string) => Promise<{
    manifest: { name: string; slug: string; type: string; purpose: string; created: string; principal: string | null };
    roster: Array<{ name: string; tier: number; role: string; reports_to: string | null; direct_reports: string[]; can_address_user: boolean }>;
  }>;
  createOrg: (name: string, type: string, purpose: string) => Promise<{ name: string; slug: string; type: string; purpose: string; created: string; principal: string | null }>;
  dissolveOrg: (slug: string) => Promise<void>;
  addAgentToOrg: (orgSlug: string, agentName: string, role: string, tier: number, reportsTo: string | null) => Promise<void>;
  removeAgentFromOrg: (agentName: string) => Promise<void>;
  updateOrg: (slug: string, updates: { name?: string; purpose?: string }) => Promise<void>;

  // System map
  getTopology: () => Promise<{
    agents: Array<{
      name: string;
      displayName: string;
      role: string;
      mcp: { include: string[]; exclude: string[]; active: string[] };
      channels: Record<string, unknown>;
      jobs: Record<string, unknown>;
      router: Record<string, unknown>;
    }>;
    servers: Array<{
      name: string;
      description: string;
      capabilities: string[];
      bundled: boolean;
      available: boolean;
      missingKey: boolean;
      missingCommand: boolean;
    }>;
  }>;
  toggleConnection: (agent: string, server: string, enabled: boolean) => Promise<{
    success: boolean;
    error?: string;
    needsRestart?: boolean;
    active?: string[];
  }>;

  // Federation
  federationGetConfig: () => Promise<unknown>;
  federationUpdateLink: (name: string, updates: Record<string, unknown>) => Promise<void>;
  federationAddLink: (name: string, link: Record<string, unknown>) => Promise<void>;
  federationRemoveLink: (name: string) => Promise<void>;
  federationGetTranscript: (linkName: string, limit?: number, offset?: number) => Promise<unknown[]>;
  federationGetStats: (linkName: string) => Promise<unknown>;
  federationGetActivePollers: () => Promise<string[]>;
  federationGenerateInvite: (localBotUsername: string, telegramGroupId: string, localAgent: string, description: string, botToken: string) => Promise<string>;
  federationAcceptInvite: (token: string, localAgent: string) => Promise<string>;
  federationParseInvite: (token: string) => Promise<{ remoteBotUsername: string; telegramGroupId: string; remoteAgent: string; description: string; expiresAt: number }>;

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
  onToolResult: createListener('inference:toolResult') as AtrophyAPI['onToolResult'],
  onThinkingDelta: createListener('inference:thinkingDelta') as AtrophyAPI['onThinkingDelta'],
  onDone: createListener('inference:done') as AtrophyAPI['onDone'],
  onCompacting: createListener('inference:compacting') as AtrophyAPI['onCompacting'],
  onError: createListener('inference:error') as AtrophyAPI['onError'],
  onEmotionUpdated: createListener('emotion:updated') as AtrophyAPI['onEmotionUpdated'],
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
  cycleAgent: (direction) => ipcRenderer.invoke('agent:cycle', direction),
  getAgents: () => ipcRenderer.invoke('agent:list'),
  getAgentsFull: () => ipcRenderer.invoke('agent:listFull'),
  onAgentSwitched: createListener('agent:switched') as AtrophyAPI['onAgentSwitched'],
  getAgentNotifyVia: (agentName) => ipcRenderer.invoke('agent:getNotifyVia', agentName),
  getAgentDetail: (agentName) => ipcRenderer.invoke('agent:getDetail', agentName),
  updateAgentConfig: (agentName, updates) => ipcRenderer.invoke('agent:updateConfig', agentName, updates),
  listAllAgents: () => ipcRenderer.invoke('agent:listAll'),
  getAgentManifest: (name) => ipcRenderer.invoke('agent:getManifest', name),
  updateAgentManifest: (name, updates) => ipcRenderer.invoke('agent:updateManifest', name, updates),
  getAgentPrompt: (name, promptName) => ipcRenderer.invoke('agent:getPrompt', name, promptName),
  updateAgentPrompt: (name, promptName, content) => ipcRenderer.invoke('agent:updatePrompt', name, promptName, content),
  quickCreateAgent: (opts) => ipcRenderer.invoke('agent:create', opts),
  deleteAgent: (name) => ipcRenderer.invoke('agent:delete', name),

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
  verifyElevenLabs: (key) => ipcRenderer.invoke('setup:verifyElevenLabs', key),
  verifyFal: (key) => ipcRenderer.invoke('setup:verifyFal', key),
  verifyTelegram: (token) => ipcRenderer.invoke('setup:verifyTelegram', token),
  setupSpeak: (text) => ipcRenderer.invoke('setup:speak', text),
  startGoogleOAuth: (wantWorkspace, wantExtra) => ipcRenderer.invoke('setup:googleOAuth', wantWorkspace, wantExtra),
  healthCheck: () => ipcRenderer.invoke('setup:healthCheck'),

  // Window
  toggleFullscreen: () => ipcRenderer.invoke('window:toggleFullscreen'),
  toggleAlwaysOnTop: () => ipcRenderer.invoke('window:toggleAlwaysOnTop'),
  minimizeWindow: () => ipcRenderer.invoke('window:minimize'),
  closeWindow: () => ipcRenderer.invoke('window:close'),
  getWindowSize: () => ipcRenderer.invoke('window:getSize'),
  setWindowSize: (width, height, animate = true) => ipcRenderer.invoke('window:setSize', width, height, animate),

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
  getUsageDetail: (agentName, days) => ipcRenderer.invoke('usage:detail', agentName, days),
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

  // Jobs / Cron (v2 - in-process scheduler)
  getSchedule: () => ipcRenderer.invoke('cron:schedule'),
  getJobHistory: () => ipcRenderer.invoke('cron:history'),
  runJobNow: (agentName: string, jobName: string) => ipcRenderer.invoke('cron:runNow', agentName, jobName),
  getSchedulerStatus: () => ipcRenderer.invoke('cron:schedulerStatus'),
  addJob: (agentName, jobName, config) => ipcRenderer.invoke('cron:addJob', agentName, jobName, config),
  editJob: (agentName, jobName, updates) => ipcRenderer.invoke('cron:editJob', agentName, jobName, updates),
  deleteJob: (agentName, jobName) => ipcRenderer.invoke('cron:deleteJob', agentName, jobName),

  // Keep Awake
  toggleKeepAwake: () => ipcRenderer.invoke('keepAwake:toggle'),
  isKeepAwakeActive: () => ipcRenderer.invoke('keepAwake:isActive'),

  // Telegram daemon
  startTelegramDaemon: () => ipcRenderer.invoke('telegram:startDaemon'),
  stopTelegramDaemon: () => ipcRenderer.invoke('telegram:stopDaemon'),
  isTelegramDaemonRunning: () => ipcRenderer.invoke('telegram:isRunning'),
  discoverTelegramChatId: (botToken, agentName) =>
    ipcRenderer.invoke('telegram:discoverChatId', botToken, agentName),
  saveTelegramBotToken: (agentName, botToken) =>
    ipcRenderer.invoke('telegram:saveAgentBotToken', agentName, botToken),
  setTelegramBotPhoto: (agentName, botToken) =>
    ipcRenderer.invoke('telegram:setBotPhoto', agentName, botToken),
  getTelegramAgentConfig: (agentName) =>
    ipcRenderer.invoke('telegram:getAgentConfig', agentName),

  // Logs
  getLogBuffer: () => ipcRenderer.invoke('logs:getBuffer'),
  onLogEntry: (cb) => {
    const handler = (_event: unknown, entry: { timestamp: number; level: string; tag: string; message: string }) => cb(entry);
    ipcRenderer.on('logs:entry', handler);
    return () => ipcRenderer.removeListener('logs:entry', handler);
  },
  log: (level, tag, message) => {
    ipcRenderer.invoke('logs:write', level, tag, message);
  },
  readLogFile: () => ipcRenderer.invoke('logs:readFile'),
  readPrevLogFile: () => ipcRenderer.invoke('logs:readPrevFile'),
  parseLogFile: (contents) => ipcRenderer.invoke('logs:parseFile', contents),

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

  // Voice agent
  voiceAgent: {
    start: () => ipcRenderer.invoke('voice-agent:start'),
    stop: () => ipcRenderer.invoke('voice-agent:stop'),
    sendText: (text: string) => ipcRenderer.invoke('voice-agent:sendText', text),
    status: () => ipcRenderer.invoke('voice-agent:status'),
    setMic: (muted: boolean) => ipcRenderer.invoke('voice-agent:setMic', muted),
    setAudio: (enabled: boolean) => ipcRenderer.invoke('voice-agent:setAudio', enabled),
    onAudio: (cb: (data: ArrayBuffer) => void) => {
      const handler = (_e: Electron.IpcRendererEvent, data: ArrayBuffer) => cb(data);
      ipcRenderer.on('voice-agent:audio', handler);
      return () => ipcRenderer.removeListener('voice-agent:audio', handler);
    },
    onStatus: (cb: (status: string) => void) => {
      const handler = (_e: Electron.IpcRendererEvent, status: string) => cb(status);
      ipcRenderer.on('voice-agent:status', handler);
      return () => ipcRenderer.removeListener('voice-agent:status', handler);
    },
    onTranscript: (cb: (text: string) => void) => {
      const handler = (_e: Electron.IpcRendererEvent, text: string) => cb(text);
      ipcRenderer.on('voice-agent:userTranscript', handler);
      return () => ipcRenderer.removeListener('voice-agent:userTranscript', handler);
    },
    onResponse: (cb: (text: string) => void) => {
      const handler = (_e: Electron.IpcRendererEvent, text: string) => cb(text);
      ipcRenderer.on('voice-agent:agentResponse', handler);
      return () => ipcRenderer.removeListener('voice-agent:agentResponse', handler);
    },
  },

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

  // Restart for update
  restartForUpdate: () => ipcRenderer.invoke('app:restartForUpdate'),

  // Bundle updater
  getBundleStatus: () => ipcRenderer.invoke('bundle:getStatus'),
  checkBundleUpdate: () => ipcRenderer.invoke('bundle:checkNow'),
  clearHotBundle: () => ipcRenderer.invoke('bundle:clear'),
  onBundleReady: createListener('bundle:ready') as AtrophyAPI['onBundleReady'],
  onBundleProgress: createListener('bundle:downloadProgress') as AtrophyAPI['onBundleProgress'],

  // Organizations
  listOrgs: () => ipcRenderer.invoke('org:list'),
  getOrgDetail: (slug) => ipcRenderer.invoke('org:detail', slug),
  createOrg: (name, type, purpose) => ipcRenderer.invoke('org:create', name, type, purpose),
  dissolveOrg: (slug) => ipcRenderer.invoke('org:dissolve', slug),
  addAgentToOrg: (orgSlug, agentName, role, tier, reportsTo) =>
    ipcRenderer.invoke('org:addAgent', orgSlug, agentName, role, tier, reportsTo),
  removeAgentFromOrg: (agentName) => ipcRenderer.invoke('org:removeAgent', agentName),
  updateOrg: (slug, updates) => ipcRenderer.invoke('org:update', slug, updates),

  // System map
  getTopology: () => ipcRenderer.invoke('system:getTopology'),
  toggleConnection: (agent, server, enabled) =>
    ipcRenderer.invoke('system:toggleConnection', agent, server, enabled),

  // Federation
  federationGetConfig: () => ipcRenderer.invoke('federation:getConfig'),
  federationUpdateLink: (name: string, updates: Record<string, unknown>) => ipcRenderer.invoke('federation:updateLink', name, updates),
  federationAddLink: (name: string, link: Record<string, unknown>) => ipcRenderer.invoke('federation:addLink', name, link),
  federationRemoveLink: (name: string) => ipcRenderer.invoke('federation:removeLink', name),
  federationGetTranscript: (linkName: string, limit?: number, offset?: number) => ipcRenderer.invoke('federation:getTranscript', linkName, limit, offset),
  federationGetStats: (linkName: string) => ipcRenderer.invoke('federation:getStats', linkName),
  federationGetActivePollers: () => ipcRenderer.invoke('federation:getActivePollers'),
  federationGenerateInvite: (localBotUsername: string, telegramGroupId: string, localAgent: string, description: string, botToken: string) => ipcRenderer.invoke('federation:generateInvite', localBotUsername, telegramGroupId, localAgent, description, botToken),
  federationAcceptInvite: (token: string, localAgent: string) => ipcRenderer.invoke('federation:acceptInvite', token, localAgent),
  federationParseInvite: (token: string) => ipcRenderer.invoke('federation:parseInvite', token),

  // Channel listener with allowlist
  on: (channel, cb) => {
    const ALLOWED_CHANNELS = new Set([
      'inference:textDelta', 'inference:sentenceReady', 'inference:toolUse',
      'inference:toolResult', 'inference:thinkingDelta',
      'inference:done', 'inference:compacting', 'inference:error',
      'tts:started', 'tts:done', 'tts:queueEmpty',
      'wakeword:start', 'wakeword:stop',
      'queue:message', 'deferral:request',
      'updater:available', 'updater:not-available', 'updater:progress',
      'updater:downloaded', 'updater:error',
      'agent:switched',
      'canvas:updated', 'artefact:updated', 'artefact:loading', 'ask:request',
      'inference:artifact', 'inference:contextUsage',
      'journal:nudge', 'status:changed',
      'avatar:download-start', 'avatar:download-progress',
      'avatar:download-complete', 'avatar:download-error',
      'mirror:avatarProgress',
      'call:statusChanged',
      'voice-agent:audio', 'voice-agent:status',
      'voice-agent:userTranscript', 'voice-agent:agentResponse',
      'voice-agent:agentResponseCorrection',
      'app:shutdownRequested', 'app:openSettings',
      'bundle:ready', 'bundle:downloadProgress',
      'cron:desktopDelivery',
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

/**
 * IPC handlers for configuration management.
 * Channels: config:reload, config:get, config:apply, config:update
 */

import { ipcMain } from 'electron';
import { getConfig, reloadConfig, saveUserConfig, saveAgentConfig } from '../config';
import { writeObservation } from '../memory';
import { isDaemonRunning } from '../channels/telegram';
import { BUNDLE_ROOT } from '../config';
import { listDownloadedModels, isPiperAvailable } from '../piper';
import type { IpcContext } from '../ipc-handlers';

// Allowlist of keys safe to update from the renderer
const agentKeys = new Set([
  'AGENT_DISPLAY_NAME', 'TTS_BACKEND', 'TTS_PLAYBACK_RATE',
  'ELEVENLABS_VOICE_ID', 'ELEVENLABS_MODEL', 'ELEVENLABS_STABILITY',
  'ELEVENLABS_SIMILARITY', 'ELEVENLABS_STYLE', 'FAL_VOICE_ID', 'PIPER_VOICE',
  'HEARTBEAT_ACTIVE_START', 'HEARTBEAT_ACTIVE_END', 'HEARTBEAT_INTERVAL_MINS',
  'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'WINDOW_WIDTH', 'WINDOW_HEIGHT',
  'SETTINGS_WINDOW_WIDTH', 'SETTINGS_WINDOW_HEIGHT',
  'DISABLED_TOOLS', 'WAKE_WORDS',
]);
const userKeys = new Set([
  'USER_NAME', 'INPUT_MODE', 'PTT_KEY', 'WAKE_WORD_ENABLED',
  'WAKE_CHUNK_SECONDS', 'SAMPLE_RATE', 'MAX_RECORD_SEC',
  'CLAUDE_BIN', 'CLAUDE_MODEL', 'CLAUDE_EFFORT', 'ADAPTIVE_EFFORT', 'INFERENCE_PROVIDER', 'QWEN_BIN', 'QWEN_MODEL', 'CONTEXT_SUMMARIES',
  'MAX_CONTEXT_TOKENS', 'VECTOR_SEARCH_WEIGHT', 'EMBEDDING_MODEL',
  'EMBEDDING_DIM', 'SESSION_SOFT_LIMIT_MINS', 'NOTIFICATIONS_ENABLED',
  'SILENCE_TIMER_ENABLED', 'SILENCE_TIMER_MINUTES',
  'EYE_MODE_DEFAULT', 'MUTE_BY_DEFAULT',
  'AVATAR_ENABLED', 'AVATAR_RESOLUTION', 'OBSIDIAN_VAULT',
  'setup_complete',
]);
const safeKeys = new Set([...agentKeys, ...userKeys, 'TELEGRAM_USERNAME']);

export function registerConfigHandlers(ctx: IpcContext): void {
  ipcMain.handle('config:reload', () => {
    reloadConfig();
  });

  ipcMain.handle('config:get', () => {
    const c = getConfig();
    return {
      // Identity
      agentName: c.AGENT_NAME,
      agentDisplayName: c.AGENT_DISPLAY_NAME,
      userName: c.USER_NAME,
      wakeWords: c.WAKE_WORDS,
      disabledTools: c.DISABLED_TOOLS,
      // Voice
      ttsBackend: c.TTS_BACKEND,
      elevenlabsApiKey: c.ELEVENLABS_API_KEY ? '***' : '',
      elevenlabsVoiceId: c.ELEVENLABS_VOICE_ID,
      elevenlabsModel: c.ELEVENLABS_MODEL,
      elevenlabsStability: c.ELEVENLABS_STABILITY,
      elevenlabsSimilarity: c.ELEVENLABS_SIMILARITY,
      elevenlabsStyle: c.ELEVENLABS_STYLE,
      ttsPlaybackRate: c.TTS_PLAYBACK_RATE,
      falApiKey: process.env.FAL_KEY ? '***' : '',
      falVoiceId: c.FAL_VOICE_ID,
      piperVoice: c.PIPER_VOICE,
      piperModels: listDownloadedModels(),
      piperAvailable: isPiperAvailable(),
      // Input
      inputMode: c.INPUT_MODE,
      pttKey: c.PTT_KEY,
      wakeWordEnabled: c.WAKE_WORD_ENABLED,
      wakeChunkSeconds: c.WAKE_CHUNK_SECONDS,
      // Audio
      sampleRate: c.SAMPLE_RATE,
      maxRecordSec: c.MAX_RECORD_SEC,
      // Inference
      claudeBin: c.CLAUDE_BIN,
      claudeModel: c.CLAUDE_MODEL,
      claudeEffort: c.CLAUDE_EFFORT,
      adaptiveEffort: c.ADAPTIVE_EFFORT,
      inferenceProvider: c.INFERENCE_PROVIDER,
      qwenBin: c.QWEN_BIN,
      qwenModel: c.QWEN_MODEL,
      // Memory
      contextSummaries: c.CONTEXT_SUMMARIES,
      maxContextTokens: c.MAX_CONTEXT_TOKENS,
      vectorSearchWeight: c.VECTOR_SEARCH_WEIGHT,
      embeddingModel: c.EMBEDDING_MODEL,
      embeddingDim: c.EMBEDDING_DIM,
      // Session
      sessionSoftLimitMins: c.SESSION_SOFT_LIMIT_MINS,
      // Heartbeat
      heartbeatActiveStart: c.HEARTBEAT_ACTIVE_START,
      heartbeatActiveEnd: c.HEARTBEAT_ACTIVE_END,
      heartbeatIntervalMins: c.HEARTBEAT_INTERVAL_MINS,
      // Telegram
      telegramBotToken: c.TELEGRAM_BOT_TOKEN ? '***' : '',
      telegramChatId: c.TELEGRAM_CHAT_ID,
      telegramUsername: Object.keys(c.TELEGRAM_USERNAMES).find(k => c.TELEGRAM_USERNAMES[k] === c.USER_NAME) || '',
      telegramDaemonRunning: isDaemonRunning(),
      // Keep Awake
      keepAwakeActive: ctx.isKeepAwakeActive(),
      // Notifications
      notificationsEnabled: c.NOTIFICATIONS_ENABLED,
      // Silence timer
      silenceTimerEnabled: c.SILENCE_TIMER_ENABLED,
      silenceTimerMinutes: c.SILENCE_TIMER_MINUTES,
      // UI defaults
      eyeModeDefault: c.EYE_MODE_DEFAULT,
      muteByDefault: c.MUTE_BY_DEFAULT,
      // Window
      windowWidth: c.WINDOW_WIDTH,
      windowHeight: c.WINDOW_HEIGHT,
      settingsWindowWidth: c.SETTINGS_WINDOW_WIDTH,
      settingsWindowHeight: c.SETTINGS_WINDOW_HEIGHT,
      avatarEnabled: c.AVATAR_ENABLED,
      avatarResolution: c.AVATAR_RESOLUTION,
      // Paths
      obsidianVault: c.OBSIDIAN_VAULT,
      dbPath: c.DB_PATH,
      whisperBin: c.WHISPER_BIN,
      // Google
      googleConfigured: c.GOOGLE_CONFIGURED,
      // About
      version: c.VERSION,
      bundleVersion: ctx.hotBundle?.version ?? null,
      bundleRoot: BUNDLE_ROOT,
    };
  });

  // Apply updates to running config only - no disk write.
  // Lets users test runtime changes before committing them.
  ipcMain.handle('config:apply', (_event, updates: Record<string, unknown>) => {
    const c = getConfig();
    for (const [key, value] of Object.entries(updates)) {
      if (!safeKeys.has(key)) continue;
      if (key in c) {
        (c as unknown as Record<string, unknown>)[key] = value;
      }
    }
  });

  // Apply updates to running config AND persist to disk.
  ipcMain.handle('config:update', (_event, updates: Record<string, unknown>) => {
    const c = getConfig();
    const userUpdates: Record<string, unknown> = {};
    const agentUpdates: Record<string, unknown> = {};

    const previousUserName = c.USER_NAME;

    for (const [key, value] of Object.entries(updates)) {
      if (!safeKeys.has(key)) continue;
      if (key in c) {
        (c as unknown as Record<string, unknown>)[key] = value;
      }
      if (agentKeys.has(key)) {
        agentUpdates[key] = value;
      } else {
        userUpdates[key] = value;
      }
    }
    // When USER_NAME changes, also update agent.json user_name and record it
    if ('USER_NAME' in userUpdates) {
      const newName = String(userUpdates.USER_NAME);
      agentUpdates['user_name'] = newName;
      if (previousUserName && previousUserName !== newName) {
        try {
          writeObservation(
            `[system] The user changed their name from "${previousUserName}" to "${newName}". ` +
            `Address them as ${newName} going forward.`,
          );
        } catch { /* non-critical */ }
      }
    }

    // Handle telegram username mapping: UI sends TELEGRAM_USERNAME as a flat
    // string, but we store it as telegram_usernames: { name: USER_NAME } in config.json.
    if ('TELEGRAM_USERNAME' in updates) {
      const tgName = String(updates.TELEGRAM_USERNAME || '').trim().toLowerCase();
      const displayName = c.USER_NAME || 'User';
      // Rebuild the map: remove old entries pointing to this user, add new one
      const existing = { ...c.TELEGRAM_USERNAMES };
      for (const [k, v] of Object.entries(existing)) {
        if (v === displayName) delete existing[k];
      }
      if (tgName) existing[tgName] = displayName;
      c.TELEGRAM_USERNAMES = existing;
      userUpdates['telegram_usernames'] = existing;
      delete userUpdates['TELEGRAM_USERNAME'];
    }

    if (Object.keys(userUpdates).length > 0) {
      saveUserConfig(userUpdates);
    }
    if (Object.keys(agentUpdates).length > 0) {
      saveAgentConfig(c.AGENT_NAME, agentUpdates);
    }
  });
}

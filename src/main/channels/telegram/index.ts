/**
 * Telegram channel - re-exports from api and daemon modules.
 *
 * Usage:
 *   import { sendMessage, startDaemon } from './channels/telegram';
 */

// API helpers (sending, receiving, bot commands, file downloads)
export {
  post,
  sendMessage,
  sendMessageGetId,
  editMessage,
  sendButtons,
  sendVoiceNote,
  sendPhoto,
  sendVideo,
  sendDocument,
  sendArtefact,
  downloadTelegramFile,
  pollCallback,
  pollReply,
  askConfirm,
  askQuestion,
  registerBotCommands,
  clearBotCommands,
  discoverChatId,
  setBotProfilePhoto,
  setLastUpdateId,
} from './api';

// Daemon lifecycle (polling, dispatch, launchd)
export {
  startDaemon,
  stopDaemon,
  isDaemonRunning,
  acquireLock,
  releaseLock,
  installLaunchd,
  uninstallLaunchd,
  isLaunchdInstalled,
  setMainWindowAccessor,
} from './daemon';

/**
 * Electron main process entry point.
 * Loaded by bootstrap.ts - either from the frozen asar or a hot bundle.
 *
 * This file owns ONLY Electron lifecycle hooks. All domain logic lives in:
 * - boot.ts          (startup orchestration)
 * - timers.ts        (interval timers, journal nudge, keep-awake)
 * - tray-manager.ts  (system tray, context menu)
 * - window-manager.ts (window creation, global shortcuts)
 * - app-context.ts   (shared mutable state)
 */

import { app } from 'electron';

// Boot-phase logging uses the main logger (writes to ~/.atrophy/logs/app.log).
import { createLogger } from './logger';
const log = createLogger('main');

// Performance: increase V8 heap limit and enable concurrent GC
app.commandLine.appendSwitch('js-flags', '--max-old-space-size=4096');
app.commandLine.appendSwitch('enable-features', 'V8ConcurrentSparkplug');

import { BUNDLE_ROOT } from './config';
import { closeAll as closeAllDbs, endSession } from './memory';
import { stopAllInference } from './inference';
import { stopWakeWordListener } from './wake-word';
import { stopDaemonSync } from './channels/telegram';
import { stopFederation } from './channels/federation';
import { stopAllJobs } from './channels/cron';
import { stopServer, stopMeridianServer } from './server';
import { createAppContext } from './app-context';
import { boot, recordCrash } from './boot';
import { createMainWindow, unregisterGlobalShortcuts } from './window-manager';
import type { HotBundlePaths } from './bundle-updater';
import { getHotBundlePaths } from './bundle-updater';

// ---------------------------------------------------------------------------
// Hot bundle detection
// ---------------------------------------------------------------------------

const hotBundle: HotBundlePaths | null = (() => {
  if (process.env.ATROPHY_HOT_BOOT !== '1') return null;
  try {
    return getHotBundlePaths();
  } catch (err) {
    console.error('Hot bundle paths failed, using frozen bundle:', err);
    return null;
  }
})();

// ---------------------------------------------------------------------------
// Shared state
// ---------------------------------------------------------------------------

const ctx = createAppContext(hotBundle);

// ---------------------------------------------------------------------------
// Single instance lock
// ---------------------------------------------------------------------------

const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (ctx.mainWindow) {
      if (ctx.mainWindow.isMinimized()) ctx.mainWindow.restore();
      ctx.mainWindow.focus();
    }
  });
}

// Record boot for crash loop detection (primary instance only)
if (gotTheLock) recordCrash();

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

app.whenReady().then(() => boot(ctx));

// ---------------------------------------------------------------------------
// Lifecycle hooks
// ---------------------------------------------------------------------------

// Cmd+Q hides instead of quitting. Only tray Quit sets forceQuit.
app.on('before-quit', (e) => {
  if (!ctx.forceQuit) {
    e.preventDefault();
    if (ctx.mainWindow) {
      ctx.mainWindow.hide();
      if (process.platform === 'darwin') app.dock?.hide();
    }
  }
});

app.on('window-all-closed', () => {
  // Never quit on window close - app lives in tray
});

app.on('activate', () => {
  if (ctx.mainWindow === null) {
    ctx.mainWindow = createMainWindow(ctx.hotBundle);
  } else {
    ctx.mainWindow.show();
  }
  if (process.platform === 'darwin') app.dock?.show();
});

app.on('will-quit', () => {
  unregisterGlobalShortcuts();
  ctx.timers?.stopAll();
  ctx.tray?.destroy();
  stopAllInference();
  stopAllJobs();
  stopWakeWordListener(() => ctx.mainWindow);
  stopDaemonSync();
  stopFederation();
  stopServer();
  stopMeridianServer();

  if (ctx.currentSession?.sessionId != null) {
    try {
      endSession(ctx.currentSession.sessionId, null, ctx.currentSession.mood);
    } catch { /* DB may already be closing */ }
    ctx.currentSession = null;
  }

  closeAllDbs();

  setTimeout(() => {
    log.warn('Force exiting - async cleanup took too long');
    process.exit(0);
  }, 2000).unref();
});

// ---------------------------------------------------------------------------
// Graceful shutdown on SIGTERM/SIGINT
// ---------------------------------------------------------------------------

function gracefulShutdown(signal: string): void {
  log.info(`received ${signal} - shutting down gracefully`);
  ctx.forceQuit = true;
  app.quit();
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

// ---------------------------------------------------------------------------
// Global error handlers
// ---------------------------------------------------------------------------

process.on('uncaughtException', (error) => {
  log.error(`uncaughtException: ${error.message}\n${error.stack}`);
});

process.on('unhandledRejection', (reason) => {
  const message = reason instanceof Error ? `${reason.message}\n${reason.stack}` : String(reason);
  log.error(`unhandledRejection: ${message}`);
});

// Keep BUNDLE_ROOT referenced so it doesn't get tree-shaken
void BUNDLE_ROOT;

/**
 * Auto-updater - checks GitHub Releases for new versions.
 *
 * Uses electron-updater with the `publish` config from electron-builder.yml.
 * In dev mode, update checks are skipped.
 */

import pkg from 'electron-updater';
const { autoUpdater } = pkg;
import { BrowserWindow } from 'electron';

let win: BrowserWindow | null = null;

/** Initialise auto-updater and bind IPC events to a window. */
export function initAutoUpdater(mainWindow: BrowserWindow): void {
  if (!mainWindow || process.env.ELECTRON_RENDERER_URL) return;

  win = mainWindow;

  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-available', (info: any) => {
    win?.webContents.send('updater:available', {
      version: info.version,
      releaseNotes: info.releaseNotes,
    });
  });

  autoUpdater.on('update-not-available', () => {
    win?.webContents.send('updater:not-available');
  });

  autoUpdater.on('download-progress', (progress) => {
    win?.webContents.send('updater:progress', {
      percent: progress.percent,
      bytesPerSecond: progress.bytesPerSecond,
      transferred: progress.transferred,
      total: progress.total,
    });
  });

  autoUpdater.on('update-downloaded', (info: any) => {
    win?.webContents.send('updater:downloaded', {
      version: info.version,
    });
  });

  autoUpdater.on('error', (err) => {
    win?.webContents.send('updater:error', err.message);
  });

  // Update check is triggered by the renderer during splash screen boot sequence.
  // No automatic delay needed here.
}

/** Manually trigger an update check. */
export function checkForUpdates(): void {
  if (process.env.ELECTRON_RENDERER_URL) return;
  autoUpdater.checkForUpdates().catch(() => {});
}

/** Download an available update. */
export function downloadUpdate(): void {
  autoUpdater.downloadUpdate().catch(() => {});
}

/** Quit and install a downloaded update. */
export function quitAndInstall(): void {
  autoUpdater.quitAndInstall();
}

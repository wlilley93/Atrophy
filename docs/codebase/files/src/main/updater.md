# src/main/updater.ts - Auto-Updater (DMG)

**Line count:** ~70 lines  
**Dependencies:** `electron-updater`, `electron`  
**Purpose:** Check GitHub Releases for new DMG versions using electron-updater

## Overview

This module uses `electron-updater` with the `publish` config from `electron-builder.yml` to check for and download new DMG releases from GitHub. In dev mode, update checks are skipped.

## Initialization

```typescript
import pkg from 'electron-updater';
const { autoUpdater } = pkg;
import { BrowserWindow } from 'electron';

let win: BrowserWindow | null = null;

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

  // Update check is triggered by the renderer during splash screen boot sequence
}
```

**Configuration:**
- `autoDownload = false`: User must explicitly choose to download
- `autoInstallOnAppQuit = true`: Install on next quit (not immediate)

**Events forwarded to renderer:**
- `updater:available` - New version available
- `updater:not-available` - Already up to date
- `updater:progress` - Download progress
- `updater:downloaded` - Download complete
- `updater:error` - Error occurred

## Manual Trigger Functions

### checkForUpdates

```typescript
export function checkForUpdates(): void {
  if (process.env.ELECTRON_RENDERER_URL) return;
  autoUpdater.checkForUpdates().catch(() => {});
}
```

**Purpose:** Manually trigger update check

### downloadUpdate

```typescript
export function downloadUpdate(): void {
  autoUpdater.downloadUpdate().catch(() => {});
}
```

**Purpose:** Download available update

### quitAndInstall

```typescript
export function quitAndInstall(): void {
  autoUpdater.quitAndInstall();
}
```

**Purpose:** Quit and install downloaded update

## IPC Handlers

In `src/main/ipc/system.ts`:

```typescript
ipcMain.handle('updater:check', () => {
  checkForUpdates();
});

ipcMain.handle('updater:download', () => {
  downloadUpdate();
});

ipcMain.handle('updater:quitAndInstall', () => {
  quitAndInstall();
});
```

## electron-builder.yml Configuration

```yaml
publish:
  provider: github
  owner: wlilley93
  repo: Atrophy
```

**Purpose:** Tell electron-updater where to check for releases

## Dev Mode Skip

```typescript
if (process.env.ELECTRON_RENDERER_URL) return;
```

**Purpose:** Skip update checks in development mode (ELECTRON_RENDERER_URL is set by electron-vite dev server)

## Exported API

| Function | Purpose |
|----------|---------|
| `initAutoUpdater(mainWindow)` | Initialize auto-updater with window |
| `checkForUpdates()` | Manually trigger update check |
| `downloadUpdate()` | Download available update |
| `quitAndInstall()` | Quit and install downloaded update |

## See Also

- `src/main/bundle-updater.ts` - Hot bundle updates (OTA without DMG)
- `src/main/ipc/system.ts` - updater:* IPC handlers
- `electron-builder.yml` - Publish configuration
- `src/renderer/components/Settings.svelte` - Update UI

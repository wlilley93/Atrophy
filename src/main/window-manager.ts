/**
 * Window creation and global keyboard shortcuts.
 * Stateless module - the BrowserWindow is returned to the caller.
 */

import { app, BrowserWindow, globalShortcut, screen, shell } from 'electron';
import * as path from 'path';
import type { AppContext } from './app-context';
import type { HotBundlePaths } from './bundle-updater';
import { getConfig } from './config';
import { cycleAgent } from './agent-manager';
import { createLogger } from './logger';

const log = createLogger('window');

export function createMainWindow(hotBundle: HotBundlePaths | null): BrowserWindow {
  const config = getConfig();

  let winWidth = config.WINDOW_WIDTH;
  let winHeight = config.WINDOW_HEIGHT;
  if (!winWidth || !winHeight) {
    const { workAreaSize } = screen.getPrimaryDisplay();
    winWidth = Math.min(640, workAreaSize.width - 40);
    winHeight = Math.min(960, workAreaSize.height - 40);
    log.info(`auto-fit window: ${winWidth}x${winHeight} (workArea ${workAreaSize.width}x${workAreaSize.height})`);
  }

  const win = new BrowserWindow({
    width: winWidth,
    height: winHeight,
    minWidth: 360,
    minHeight: 480,
    maxWidth: 2000,
    maxHeight: 1400,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 14, y: 14 },
    vibrancy: 'under-window',
    visualEffectState: 'active',
    backgroundColor: '#00000000',
    show: false,
    fullscreenable: false,
    webPreferences: {
      preload: hotBundle?.preload ?? path.join(__dirname, '..', 'preload', 'index.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      // Dev mode loads renderer from http://localhost which blocks file:// video/image sources.
      // Disable web security in dev so file:// avatar videos load correctly.
      ...(process.env.ELECTRON_RENDERER_URL ? { webSecurity: false } : {}),
    },
  });

  // Content Security Policy
  win.webContents.session.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: file:; media-src 'self' file:; font-src 'self' https://fonts.gstatic.com; connect-src 'self' https:; frame-src 'self' blob:; form-action 'none'; base-uri 'self'",
        ],
      },
    });
  });

  // Load renderer
  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (devUrl && /^https?:\/\/localhost[:/]/.test(devUrl)) {
    log.info(`loadURL: ${devUrl}`);
    win.loadURL(devUrl);
  } else {
    const rendererPath = hotBundle?.renderer ?? path.join(__dirname, '..', 'renderer', 'index.html');
    log.info(`loadFile: ${rendererPath}`);
    win.loadFile(rendererPath);
  }

  // Renderer lifecycle diagnostics
  win.webContents.on('did-finish-load', () => {
    log.info('renderer did-finish-load');
  });
  win.webContents.on('did-fail-load', (_event, errorCode, errorDescription) => {
    log.error(`renderer did-fail-load: ${errorCode} ${errorDescription}`);
  });
  win.webContents.on('render-process-gone', (_event, details) => {
    log.error(`renderer process gone: ${details.reason} exitCode=${details.exitCode}`);
  });
  win.webContents.on('unresponsive', () => {
    log.warn('renderer unresponsive');
  });
  win.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    // Forward renderer console.error to the main log file for crash diagnostics
    if (level >= 2) { // 2 = warning, 3 = error
      const lvl = level >= 3 ? 'error' : 'warn';
      log.info(`renderer:console[${lvl}] ${message} (${sourceId}:${line})`);
    }
  });

  // Open external links in the system browser instead of in-app
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('http://')) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  // Prevent in-app navigation to external URLs
  win.webContents.on('will-navigate', (event, url) => {
    // Allow same-origin navigation (file:// for the renderer)
    if (!url.startsWith('file://') && !url.startsWith('devtools://')) {
      event.preventDefault();
      if (url.startsWith('https://') || url.startsWith('http://')) {
        shell.openExternal(url);
      }
    }
  });

  return win;
}

export function registerGlobalShortcuts(ctx: AppContext): void {
  // Cmd+Shift+Space - toggle window visibility
  globalShortcut.register('CommandOrControl+Shift+Space', () => {
    if (!ctx.mainWindow) {
      ctx.mainWindow = createMainWindow(ctx.hotBundle);
      ctx.mainWindow.show();
      ctx.mainWindow.focus();
      if (process.platform === 'darwin') app.dock?.show();
    } else if (ctx.mainWindow.isVisible()) {
      ctx.mainWindow.hide();
      if (process.platform === 'darwin') app.dock?.hide();
    } else {
      ctx.mainWindow.show();
      ctx.mainWindow.focus();
      if (process.platform === 'darwin') app.dock?.show();
    }
  });

  // Agent cycling via global shortcuts (switchAgent has its own mutex)
  async function doCycleAgent(direction: 1 | -1): Promise<void> {
    const cfg = getConfig();
    const target = cycleAgent(direction, cfg.AGENT_NAME);
    if (!target || target === cfg.AGENT_NAME) return;

    try {
      const result = await ctx.switchAgent(target);
      ctx.mainWindow?.webContents.send('agent:switched', result);
      ctx.tray.rebuildMenu();
    } catch {
      // switchAgent throws if already in progress - silently ignore for cycling
    }
  }

  // Cmd+Shift+] / [ - cycle agents
  // NOTE: Shift+Up/Down were removed - they are standard text selection
  // shortcuts and globalShortcut intercepts them system-wide in all apps.
  globalShortcut.register('CommandOrControl+Shift+]', () => { doCycleAgent(1); });
  globalShortcut.register('CommandOrControl+Shift+[', () => { doCycleAgent(-1); });
}

export function unregisterGlobalShortcuts(): void {
  globalShortcut.unregisterAll();
}

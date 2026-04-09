/**
 * System tray management.
 * Owns tray creation, context menu building, and icon state updates.
 */

import { app, Tray, Menu, nativeImage } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import type { AppContext } from './app-context';
import { getConfig, USER_DATA, BUNDLE_ROOT } from './config';
import { discoverUiAgents, getAgentDir } from './agent-manager';
import { getStatus, setActive, setAway } from './status';
import { getTrayIcon, type TrayState } from './icon';
import { isMirrorSetupComplete } from './jobs/generate-mirror-avatar';
import { createLogger } from './logger';

const log = createLogger('tray');

export class TrayManager {
  private tray: Tray | null = null;
  private usesBrainIcon = false;
  private cachedAgents: ReturnType<typeof discoverUiAgents> | null = null;

  constructor(private ctx: AppContext) {}

  create(): void {
    try {
      const iconDir = app.isPackaged
        ? path.join(process.resourcesPath, 'icons')
        : path.join(__dirname, '..', '..', 'resources', 'icons');

      log.info(`iconDir=${iconDir} exists=${fs.existsSync(iconDir)}`);

      const icon2x = path.join(iconDir, 'menubar_brain@2x.png');
      const icon1x = path.join(iconDir, 'menubar_brain.png');
      const brainPath = fs.existsSync(icon2x) ? icon2x : fs.existsSync(icon1x) ? icon1x : '';

      log.info(`brainPath=${brainPath || 'NONE'}`);

      let trayIcon: Electron.NativeImage;
      if (brainPath) {
        trayIcon = nativeImage.createFromPath(brainPath);
        trayIcon.setTemplateImage(true);
        this.usesBrainIcon = !trayIcon.isEmpty();
        log.info(`loaded brain icon: ${trayIcon.getSize().width}x${trayIcon.getSize().height} empty=${trayIcon.isEmpty()}`);
      } else {
        trayIcon = getTrayIcon('active');
        log.info('using procedural fallback');
      }

      this.tray = new Tray(trayIcon);
      this.rebuildMenu();

      this.tray.on('click', () => {
        if (this.ctx.mainWindow) {
          this.ctx.mainWindow.show();
          this.ctx.mainWindow.focus();
        }
      });

      log.info('created successfully');
    } catch (err) {
      log.error('failed to create:', err);
    }
  }

  rebuildMenu(): void {
    if (!this.tray) return;

    const awake = this.ctx.timers.isKeepAwakeActive();
    const config = getConfig();
    const status = getStatus();
    const agents = this.getCachedAgents();

    const statusLabel = status.status === 'active' ? 'Online' : 'Away';
    const statusIcon = status.status === 'active' ? '🟢' : '🟡';

    const template: Electron.MenuItemConstructorOptions[] = [
      {
        label: `${statusIcon} ${config.AGENT_DISPLAY_NAME} - ${statusLabel}`,
        enabled: false,
      },
      { type: 'separator' },
      {
        label: 'Show Window',
        accelerator: 'CommandOrControl+Shift+Space',
        click: () => {
          if (!this.ctx.mainWindow) {
            const { createMainWindow } = require('./window-manager');
            this.ctx.mainWindow = createMainWindow(this.ctx.hotBundle);
          }
          this.ctx.mainWindow!.show();
          this.ctx.mainWindow!.focus();
          if (process.platform === 'darwin') app.dock?.show();
        },
      },
      {
        label: 'Settings',
        click: () => {
          if (this.ctx.mainWindow) {
            this.ctx.mainWindow.show();
            this.ctx.mainWindow.focus();
            this.ctx.mainWindow.webContents.send('app:openSettings');
          }
        },
      },
      { type: 'separator' },
      {
        label: 'Set Online',
        type: 'radio',
        checked: status.status === 'active',
        click: () => {
          setActive();
          this.updateState('active');
          this.ctx.mainWindow?.webContents.send('status:changed', 'active');
          this.rebuildMenu();
        },
      },
      {
        label: 'Set Away',
        type: 'radio',
        checked: status.status === 'away',
        click: () => {
          setAway('manual');
          this.updateState('away');
          this.ctx.mainWindow?.webContents.send('status:changed', 'away');
          this.rebuildMenu();
        },
      },
      { type: 'separator' },
      {
        label: 'Switch Agent',
        submenu: agents.map((agent) => ({
          label: agent.display_name || agent.name,
          type: 'radio' as const,
          checked: agent.name === config.AGENT_NAME,
          click: async () => {
            if (agent.name === config.AGENT_NAME) return;
            const result = await this.ctx.switchAgent(agent.name);
            this.ctx.mainWindow?.webContents.send('agent:switched', result);
            this.rebuildMenu();
          },
        })),
      },
      { type: 'separator' },
      {
        label: 'Keep Computer Awake',
        type: 'checkbox',
        checked: awake,
        click: () => {
          this.ctx.timers.toggleKeepAwake();
          this.rebuildMenu();
        },
      },
      { type: 'separator' },
      ...(this.ctx.pendingBundleVersion ? [{
        label: `Update Available (v${this.ctx.pendingBundleVersion})`,
        click: () => { app.relaunch(); app.exit(); },
      }] : []),
      {
        label: 'Quit',
        click: () => {
          this.ctx.forceQuit = true;
          app.quit();
        },
      },
    ];

    const contextMenu = Menu.buildFromTemplate(template);
    this.tray.setContextMenu(contextMenu);
    this.tray.setToolTip(`Atrophy - ${config.AGENT_DISPLAY_NAME} (${statusLabel})`);
  }

  updateState(state: TrayState): void {
    if (!this.tray) return;
    if (!this.usesBrainIcon) {
      this.tray.setImage(getTrayIcon(state));
    }
    this.rebuildMenu();
  }

  invalidateAgentCache(): void {
    this.cachedAgents = null;
  }

  destroy(): void {
    if (this.tray) {
      this.tray.destroy();
      this.tray = null;
    }
  }

  private getCachedAgents(): ReturnType<typeof discoverUiAgents> {
    if (!this.cachedAgents) this.cachedAgents = discoverUiAgents();
    return this.cachedAgents;
  }
}

/** Check if an agent needs custom setup (e.g. mirror wizard). */
export function getCustomSetup(name: string): string | null {
  for (const base of [USER_DATA, BUNDLE_ROOT]) {
    const jsonPath = path.join(base, 'agents', name, 'data', 'agent.json');
    try {
      if (!fs.existsSync(jsonPath)) continue;
      const manifest = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));
      if (manifest.custom_setup && !isMirrorSetupComplete(name)) {
        return manifest.custom_setup;
      }
      break;
    } catch { continue; }
  }
  return null;
}

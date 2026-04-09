# App.ts Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose the 1,478-line `src/main/app.ts` god object into 5 focused domain modules, reducing it to ~150 lines of Electron lifecycle plumbing.

**Architecture:** Domain-based extraction. Shared mutable state flows through a single `AppContext` object (extending the proven `IpcContext` pattern). Each domain module owns its state, setup, and teardown. No behavioral changes - same boot order, timer intervals, shutdown sequence.

**Tech Stack:** Electron 35, TypeScript 5.9 (strict mode), Vite + electron-vite

**Spec:** `docs/superpowers/specs/2026-04-09-app-decomposition-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/main/app-context.ts` | Shared mutable state + type definitions |
| Create | `src/main/timers.ts` | 9 interval timers + journal nudge + keep-awake |
| Create | `src/main/tray-manager.ts` | Tray creation, menu building, icon state |
| Create | `src/main/window-manager.ts` | Window creation + global shortcuts |
| Create | `src/main/boot.ts` | Sequential boot orchestration |
| Modify | `src/main/app.ts` | Strip down to lifecycle hooks only |
| Modify | `src/main/ipc-handlers.ts:33-52` | `IpcContext` becomes alias for `AppContext` |

---

### Task 1: Create `app-context.ts` - Shared State Object

**Files:**
- Create: `src/main/app-context.ts`

This is the foundation. Every subsequent module depends on this type.

- [ ] **Step 1: Create `src/main/app-context.ts`**

```typescript
/**
 * Shared mutable application state.
 * Passed by reference to all extracted domain modules.
 * Replaces the 30+ module-level variables formerly in app.ts.
 */

import type { BrowserWindow } from 'electron';
import type { Session } from './session';
import type { HotBundlePaths } from './bundle-updater';
import type { TrayState } from './icon';
import type { TimerManager } from './timers';
import type { TrayManager } from './tray-manager';

export interface SwitchAgentResult {
  agentName: string;
  agentDisplayName: string;
  customSetup: string | null;
}

export interface AppContext {
  // Window
  mainWindow: BrowserWindow | null;
  isMenuBarMode: boolean;
  forceQuit: boolean;

  // Session
  currentSession: Session | null;
  systemPrompt: string | null;
  currentAgentName: string | null;

  // Ask-user state
  pendingAskId: string | null;
  pendingAskDestination: string | null;
  pendingAskAgent: string | null;

  // Bundle
  readonly hotBundle: HotBundlePaths | null;
  pendingBundleVersion: string | null;

  // Managers (set during boot, before any consumer reads them)
  timers: TimerManager;
  tray: TrayManager;

  // Functions (set during boot)
  switchAgent: (name: string) => Promise<SwitchAgentResult>;
}

export function createAppContext(hotBundle: HotBundlePaths | null): AppContext {
  return {
    mainWindow: null,
    isMenuBarMode: false,
    forceQuit: false,
    currentSession: null,
    systemPrompt: null,
    currentAgentName: null,
    pendingAskId: null,
    pendingAskDestination: null,
    pendingAskAgent: null,
    hotBundle,
    pendingBundleVersion: null,
    // Managers and functions are set during boot - use null! to satisfy
    // the type checker. They are always assigned before any consumer runs.
    timers: null!,
    tray: null!,
    switchAgent: null!,
  };
}
```

- [ ] **Step 2: Verify typecheck passes**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit -p tsconfig.node.json 2>&1 | tail -5`
Expected: No errors (new file, no consumers yet)

- [ ] **Step 3: Commit**

```bash
git add src/main/app-context.ts
git commit -m "refactor: add AppContext shared state type for app.ts decomposition"
```

---

### Task 2: Create `timers.ts` - Timer Manager

**Files:**
- Create: `src/main/timers.ts`

Extracts all 9 interval timers, the journal nudge timeout, and the keep-awake power saver blocker from `app.ts`. Each timer callback is a named method.

- [ ] **Step 1: Create `src/main/timers.ts`**

```typescript
/**
 * Timer management for the Electron main process.
 * Owns all interval timers, the journal nudge timeout, and the keep-awake blocker.
 * Each timer callback is a named method for readability and testability.
 */

import { powerSaveBlocker } from 'electron';
import * as fs from 'fs';
import * as path from 'path';
import type { AppContext } from './app-context';
import { getConfig, USER_DATA } from './config';
import { closeStaleOpenSessions, endSession, getLastCliSessionId } from './memory';
import { runCoherenceCheck } from './sentinel';
import { drainAllAgentQueues } from './queue';
import { switchboard } from './channels/switchboard';
import {
  checkDeferralRequest,
  validateDeferralRequest,
  checkAskRequest,
  cleanupAskFiles,
  getAgentDir,
} from './agent-manager';
import { setActive, setAway, isAway, isMacIdle, getStatus, IDLE_TIMEOUT_SECS } from './status';
import { loadSystemPrompt } from './context';
import { createLogger } from './logger';
import type { TrayState } from './icon';

const log = createLogger('timers');

export class TimerManager {
  private intervals: Map<string, ReturnType<typeof setInterval>> = new Map();
  private timeouts: Map<string, ReturnType<typeof setTimeout>> = new Map();

  // Keep-awake state
  private keepAwakeBlockerId: number | null = null;

  // Journal nudge state
  private journalNudgeSent = false;
  private lastUserInputTime = Date.now();

  // Canvas mtime tracking
  private canvasLastMtime = 0;

  // Constants
  private static readonly JOURNAL_NUDGE_DELAY_MS = 5 * 60 * 1000;
  private static readonly JOURNAL_NUDGE_PROBABILITY = 0.10;
  private static readonly SESSION_IDLE_THRESHOLD_MS = 30 * 60 * 1000;

  constructor(private ctx: AppContext) {}

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  startAll(): void {
    // Clean up stale ask files before starting the watcher
    cleanupAskFiles();

    this.intervals.set('sentinel', setInterval(() => this.pollSentinel(), 5 * 60 * 1000));
    this.intervals.set('queue', setInterval(() => this.pollQueue(), 10_000));
    this.intervals.set('mcpState', setInterval(() => this.writeMcpState(), 5_000));
    this.intervals.set('deferral', setInterval(() => this.pollDeferral(), 5_000));
    this.intervals.set('askUser', setInterval(() => this.pollAskUser(), 3_000));
    this.intervals.set('artefact', setInterval(() => this.pollArtefact(), 5_000));
    this.intervals.set('canvas', setInterval(() => this.pollCanvas(), 2_000));
    this.intervals.set('status', setInterval(() => this.pollStatus(), 60_000));
    this.intervals.set('sessionIdle', setInterval(() => this.pollSessionIdle(), 60_000));

    log.info(`started ${this.intervals.size} timers`);
  }

  stopAll(): void {
    for (const [name, timer] of this.intervals) {
      clearInterval(timer);
    }
    this.intervals.clear();

    for (const [name, timer] of this.timeouts) {
      clearTimeout(timer);
    }
    this.timeouts.clear();

    this.disableKeepAwake();
    log.info('all timers stopped');
  }

  // ---------------------------------------------------------------------------
  // Journal nudge
  // ---------------------------------------------------------------------------

  resetJournalNudge(): void {
    this.lastUserInputTime = Date.now();
    const existing = this.timeouts.get('journalNudge');
    if (existing) clearTimeout(existing);
    if (this.journalNudgeSent) return;

    const timer = setTimeout(() => {
      if (this.journalNudgeSent) return;
      if (Math.random() > TimerManager.JOURNAL_NUDGE_PROBABILITY) return;
      this.journalNudgeSent = true;
      this.ctx.mainWindow?.webContents.send('journal:nudge');
    }, TimerManager.JOURNAL_NUDGE_DELAY_MS);

    this.timeouts.set('journalNudge', timer);
  }

  recordUserInput(): void {
    this.lastUserInputTime = Date.now();
  }

  // ---------------------------------------------------------------------------
  // Keep-awake (power save blocker)
  // ---------------------------------------------------------------------------

  isKeepAwakeActive(): boolean {
    return this.keepAwakeBlockerId !== null && powerSaveBlocker.isStarted(this.keepAwakeBlockerId);
  }

  enableKeepAwake(): void {
    if (this.isKeepAwakeActive()) return;
    this.keepAwakeBlockerId = powerSaveBlocker.start('prevent-display-sleep');
    log.info(`keep awake enabled (blocker id=${this.keepAwakeBlockerId})`);
    this.ctx.tray.rebuildMenu();
  }

  disableKeepAwake(): void {
    if (this.keepAwakeBlockerId !== null) {
      try { powerSaveBlocker.stop(this.keepAwakeBlockerId); } catch { /* already stopped */ }
      log.info(`keep awake disabled (blocker id=${this.keepAwakeBlockerId})`);
      this.keepAwakeBlockerId = null;
    }
  }

  toggleKeepAwake(): void {
    if (this.isKeepAwakeActive()) {
      this.disableKeepAwake();
    } else {
      this.enableKeepAwake();
    }
    this.ctx.tray.rebuildMenu();
  }

  // ---------------------------------------------------------------------------
  // Private timer callbacks
  // ---------------------------------------------------------------------------

  private pollSentinel(): void {
    if (this.ctx.currentSession?.cliSessionId && this.ctx.systemPrompt) {
      runCoherenceCheck(this.ctx.currentSession.cliSessionId, this.ctx.systemPrompt).then((newId) => {
        if (newId && this.ctx.currentSession) {
          this.ctx.currentSession.setCliSessionId(newId);
        }
      }).catch((err) => { log.debug(`sentinel coherence check failed: ${err}`); });
    }
  }

  private pollQueue(): void {
    (async () => {
      const allMessages = await drainAllAgentQueues();
      for (const [, messages] of Object.entries(allMessages)) {
        for (const msg of messages) {
          this.ctx.mainWindow?.webContents.send('queue:message', msg);
        }
      }
    })().catch(err => log.error('queue poll error:', err));
  }

  private pollDeferral(): void {
    if (!this.ctx.mainWindow || !this.ctx.currentAgentName) return;
    const request = checkDeferralRequest();
    if (!request) return;

    if (!validateDeferralRequest(request.target, this.ctx.currentAgentName)) {
      return;
    }

    this.ctx.mainWindow.webContents.send('deferral:request', {
      target: request.target,
      context: request.context,
      user_question: request.user_question,
    });
  }

  private pollAskUser(): void {
    if (!this.ctx.mainWindow) return;
    if (this.ctx.pendingAskId) return;
    const request = checkAskRequest();
    if (!request) return;

    this.ctx.pendingAskId = request.request_id;
    this.ctx.pendingAskDestination = request.destination || null;
    this.ctx.pendingAskAgent = (request as any)._agent || null;
    this.ctx.mainWindow.webContents.send('ask:request', {
      question: request.question,
      action_type: request.action_type,
      request_id: request.request_id,
      input_type: request.input_type,
      label: request.label,
      destination: request.destination,
    });
  }

  private pollArtefact(): void {
    if (!this.ctx.mainWindow) return;
    const config = getConfig();
    const displayFile = config.ARTEFACT_DISPLAY_FILE;
    if (!displayFile || !fs.existsSync(displayFile)) return;

    try {
      const raw = fs.readFileSync(displayFile, 'utf-8');
      const data = JSON.parse(raw) as {
        status?: string;
        type?: string;
        name?: string;
        path?: string;
        file?: string;
      };

      if (data.status === 'generating') {
        this.ctx.mainWindow.webContents.send('artefact:loading', { name: data.name, type: data.type });
        return;
      }

      fs.unlinkSync(displayFile);

      const artefactType = data.type || 'html';
      let content = '';
      let src = '';

      if (data.file) {
        const c = getConfig();
        const artefactsBase = path.resolve(path.join(getAgentDir(c.AGENT_NAME), 'artefacts'));
        let resolvedFile: string;
        try {
          resolvedFile = fs.realpathSync(path.resolve(data.file));
        } catch {
          resolvedFile = '';
        }
        if (!resolvedFile || (!resolvedFile.startsWith(artefactsBase + path.sep) && resolvedFile !== artefactsBase)) {
          log.warn(`artefact watcher blocked path traversal: ${data.file}`);
          return;
        }

        if (artefactType === 'html') {
          try {
            content = fs.readFileSync(resolvedFile, 'utf-8');
          } catch { /* file missing */ }
        } else if (artefactType === 'image' || artefactType === 'video') {
          src = `file://${resolvedFile}`;
        }
      }

      this.ctx.mainWindow.webContents.send('artefact:updated', {
        type: artefactType,
        content,
        src,
        title: data.name || '',
      });
    } catch {
      try { fs.unlinkSync(displayFile); } catch { /* already gone */ }
    }
  }

  private pollCanvas(): void {
    if (!this.ctx.mainWindow) return;
    const config = getConfig();
    const canvasFile = config.CANVAS_CONTENT_FILE;
    if (!canvasFile || !fs.existsSync(canvasFile)) return;

    try {
      const stat = fs.statSync(canvasFile);
      const mtime = stat.mtimeMs;
      if (mtime <= this.canvasLastMtime) return;
      this.canvasLastMtime = mtime;

      const fileUrl = `file://${canvasFile}`;
      this.ctx.mainWindow.webContents.send('canvas:updated', fileUrl);
    } catch { /* file gone mid-read */ }
  }

  private pollStatus(): void {
    (async () => {
      const wasAway = isAway();
      if (await isMacIdle(IDLE_TIMEOUT_SECS)) {
        if (!wasAway) {
          setAway('idle');
          log.info('user idle - setting away');
          this.ctx.tray.updateState('away');
          this.ctx.mainWindow?.webContents.send('status:changed', 'away');
        }
      } else {
        if (wasAway) {
          setActive();
          log.info('user active - setting online');
          this.ctx.tray.updateState('active');
          this.ctx.mainWindow?.webContents.send('status:changed', 'active');
        }
      }
    })().catch(err => log.error('status poll error:', err));
  }

  private pollSessionIdle(): void {
    (async () => {
      if (!this.ctx.currentSession || this.ctx.currentSession.sessionId === null) return;
      if (this.ctx.currentSession.turnHistory.length === 0) return;

      const lastActivity = this.ctx.currentSession.lastActivityAt ?? this.lastUserInputTime;
      const gap = Date.now() - lastActivity;
      if (gap < TimerManager.SESSION_IDLE_THRESHOLD_MS) return;

      const oldSession = this.ctx.currentSession;
      const sys = this.ctx.systemPrompt || loadSystemPrompt();
      try {
        await oldSession.end(sys);
        log.info(`rotated idle session (gap: ${Math.round(gap / 60000)}m, turns: ${oldSession.turnHistory.length})`);
      } catch (e) {
        log.error(`failed to end idle session: ${e}`);
      }
      if (this.ctx.currentSession === oldSession) this.ctx.currentSession = null;
    })().catch(err => log.error('session idle rotation error:', err));
  }

  private writeMcpState(): void {
    switchboard.writeStateForMCP();
  }
}
```

- [ ] **Step 2: Verify typecheck passes**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit -p tsconfig.node.json 2>&1 | tail -10`
Expected: No errors (new file, no consumers yet - the import of `TrayManager` from `./tray-manager` will fail until Task 3 creates it, so if this is being built sequentially, expect that one error and continue)

- [ ] **Step 3: Commit**

```bash
git add src/main/timers.ts
git commit -m "refactor: extract TimerManager from app.ts (9 intervals + journal nudge + keep-awake)"
```

---

### Task 3: Create `tray-manager.ts` - Tray Manager

**Files:**
- Create: `src/main/tray-manager.ts`

Extracts tray creation (`createTray`), menu building (`rebuildTrayMenu`), icon state updates (`updateTrayState`), and the agent cache used by the tray menu.

- [ ] **Step 1: Create `src/main/tray-manager.ts`**

```typescript
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

  // Cache agent list for tray menu - refreshed on agent switch, not every rebuild.
  // Tray switcher excludes tier 2+ org agents (research fellows, ambassadors,
  // specialists) since they are headless background workers.
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
```

- [ ] **Step 2: Verify typecheck passes**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit -p tsconfig.node.json 2>&1 | tail -10`
Expected: No errors (or only errors from `window-manager` not existing yet - that `require()` in the Show Window click handler is a lazy import that only runs at click time)

- [ ] **Step 3: Commit**

```bash
git add src/main/tray-manager.ts
git commit -m "refactor: extract TrayManager from app.ts (tray, menu, icon state, agent cache)"
```

---

### Task 4: Create `window-manager.ts` - Window Creation + Shortcuts

**Files:**
- Create: `src/main/window-manager.ts`

Extracts `createWindow()` and global shortcut registration. Pure functions - no class needed.

- [ ] **Step 1: Create `src/main/window-manager.ts`**

```typescript
/**
 * Window creation and global keyboard shortcuts.
 * Stateless module - the BrowserWindow is returned to the caller.
 */

import { app, BrowserWindow, globalShortcut, screen } from 'electron';
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
    if (level >= 2) {
      const lvl = level >= 3 ? 'error' : 'warn';
      log.info(`renderer:console[${lvl}] ${message} (${sourceId}:${line})`);
    }
  });

  // Open external links in system browser
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http:') || url.startsWith('https:')) {
      require('electron').shell.openExternal(url);
    }
    return { action: 'deny' };
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

  // Cmd+Shift+] / [ - cycle agents
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

  globalShortcut.register('CommandOrControl+Shift+]', () => { doCycleAgent(1); });
  globalShortcut.register('CommandOrControl+Shift+[', () => { doCycleAgent(-1); });
}

export function unregisterGlobalShortcuts(): void {
  globalShortcut.unregisterAll();
}
```

- [ ] **Step 2: Verify typecheck passes**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit -p tsconfig.node.json 2>&1 | tail -10`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/main/window-manager.ts
git commit -m "refactor: extract window creation and global shortcuts from app.ts"
```

---

### Task 5: Create `boot.ts` - Boot Sequence Orchestrator

**Files:**
- Create: `src/main/boot.ts`

Extracts the entire `whenReady()` body into a sequential, labeled boot function. Each phase is a helper function.

- [ ] **Step 1: Create `src/main/boot.ts`**

```typescript
/**
 * Boot sequence orchestrator.
 * Called from app.ts on app.whenReady(). Each phase is labeled and sequential.
 * This file replaces the 650+ line whenReady() callback.
 */

import { app, ipcMain } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { v4 as uuidv4 } from 'uuid';
import type { AppContext } from './app-context';
import { TimerManager } from './timers';
import { TrayManager } from './tray-manager';
import { createMainWindow, registerGlobalShortcuts } from './window-manager';
import { ensureUserData, getConfig, BUNDLE_ROOT, USER_DATA } from './config';
import { initDb, closeStaleOpenSessions, endSession, getLastCliSessionId } from './memory';
import { stopInference, resetMcpConfig, prefetchContext, invalidateContextCache, getTmuxPool } from './inference';
import { clearAudioQueue, synthesise, playAudio, waitForAudioIdle, setPlaybackCallbacks } from './tts';
import { Session } from './session';
import { loadSystemPrompt } from './context';
import { sendCronNotification } from './notify';
import { cronOutputEmitter } from './channels/telegram/daemon';
import { registerAudioHandlers } from './audio';
import { registerWakeWordHandlers, pauseWakeWord, resumeWakeWord } from './wake-word';
import {
  discoverAgents,
  getAgentDir,
  syncBundledPrompts,
  setLastActiveAgent,
  getLastActiveAgent,
  isValidAgentName,
} from './agent-manager';
import { startServer, stopServer, startMeridianServer } from './server';
import { startDaemon, setMainWindowAccessor } from './channels/telegram';
import { startFederation } from './channels/federation';
import { cronScheduler } from './channels/cron';
import { mcpRegistry } from './mcp-registry';
import { wireAgent, markBootComplete } from './create-agent';
import { backupAgentData } from './backup';
import { ensureAvatarAssets, ensureAmbientVideo } from './avatar-downloader';
import { initAutoUpdater } from './updater';
import { getAppIcon } from './icon';
import { isAway } from './status';
import { switchboard } from './channels/switchboard';
import { registerIpcHandlers } from './ipc-handlers';
import { registerCallHandlers } from './call';
import { getCustomSetup } from './tray-manager';
import { createLogger } from './logger';
import type { SwitchAgentResult } from './app-context';

const log = createLogger('boot');

export async function boot(ctx: AppContext): Promise<void> {
  log.info('app.whenReady() fired');

  // Parse args
  const args = process.argv.slice(2);
  ctx.isMenuBarMode = args.includes('--app');
  const isServerMode = args.includes('--server');

  if (ctx.isMenuBarMode || isServerMode) {
    app.dock?.hide();
  } else {
    const appIcon = getAppIcon();
    app.dock?.setIcon(appIcon);
  }

  // ── Phase 1: Config + DB ──
  log.info('ensureUserData + config + db init');
  ensureUserData();
  syncBundledPrompts();
  const config = getConfig();
  initDb();

  closeStaleSessionsForAllAgents();

  ctx.currentAgentName = config.AGENT_NAME;
  log.info(`v${config.VERSION} | agent: ${config.AGENT_NAME} | db: ${config.DB_PATH}`);

  // ── Phase 2: Wire managers ──
  ctx.timers = new TimerManager(ctx);
  ctx.tray = new TrayManager(ctx);

  // Wire switchAgent into context (needs managers to exist)
  let switchInProgress = false;
  ctx.switchAgent = async (name: string): Promise<SwitchAgentResult> => {
    if (switchInProgress) throw new Error('Agent switch already in progress');
    switchInProgress = true;
    try {
      return await switchAgentImpl(ctx, name);
    } finally {
      switchInProgress = false;
    }
  };

  // ── Phase 3: IPC ──
  log.info('registering IPC handlers');
  registerIpcHandlers(ctx as any); // AppContext is a superset of IpcContext
  registerAudioHandlers(() => ctx.mainWindow);
  registerWakeWordHandlers();
  registerCallHandlers(
    () => ctx.mainWindow,
    () => {
      if (!ctx.currentSession) {
        ctx.currentSession = new Session();
        ctx.currentSession.start();
        ctx.currentSession.inheritCliSessionId();
      }
      if (!ctx.systemPrompt) {
        ctx.systemPrompt = loadSystemPrompt();
      }
      return ctx.systemPrompt;
    },
    () => ctx.currentSession?.cliSessionId || null,
    (id: string) => { if (ctx.currentSession) ctx.currentSession.setCliSessionId(id); },
  );

  // TTS playback callbacks
  setPlaybackCallbacks({
    onStarted: (index) => {
      ctx.mainWindow?.webContents.send('tts:started', index);
      pauseWakeWord();
    },
    onDone: (index) => {
      ctx.mainWindow?.webContents.send('tts:done', index);
    },
    onQueueEmpty: () => {
      ctx.mainWindow?.webContents.send('tts:queueEmpty');
      resumeWakeWord();
    },
  });

  // Actual quit - called from tray menu or renderer
  ipcMain.handle('app:shutdown', () => {
    ctx.forceQuit = true;
    app.quit();
  });

  // ── Phase 4: Resume last active agent ──
  const lastAgent = getLastActiveAgent();
  if (lastAgent && lastAgent !== config.AGENT_NAME) {
    config.reloadForAgent(lastAgent);
    initDb();
    ctx.currentAgentName = config.AGENT_NAME;
    log.info(`resumed agent: ${config.AGENT_NAME}`);
  }

  // ── Phase 5: Agent wiring ──
  discoverAndWireAgents(ctx);

  // ── Phase 6: Services ──
  const crashSafe = isCrashRateSafe();
  log.info(`crashSafe=${crashSafe}`);
  if (!crashSafe) {
    log.error('CRASH LOOP DETECTED - skipping cron scheduler and Telegram daemon');
  }

  startServices(ctx, crashSafe);

  // ── Phase 7: Timers ──
  ctx.timers.startAll();

  // ── Phase 8: UI ──
  if (isServerMode) {
    const portIdx = args.indexOf('--port');
    const port = portIdx !== -1 ? parseInt(args[portIdx + 1], 10) || 5000 : 5000;
    startServer(port);
    return;
  }

  registerGlobalShortcuts(ctx);

  if (ctx.isMenuBarMode) {
    ctx.tray.create();
    return;
  }

  // GUI mode
  log.info('creating main window');
  ctx.mainWindow = createMainWindow(ctx.hotBundle);
  log.info('main window created, loading renderer');

  ctx.timers.resetJournalNudge();

  if (ctx.mainWindow) {
    initAutoUpdater(ctx.mainWindow);
  }

  if (ctx.hotBundle) {
    log.info(`running on hot bundle v${ctx.hotBundle.version}`);
  }

  Promise.all([
    ensureAvatarAssets(config.AGENT_NAME, ctx.mainWindow),
    ensureAmbientVideo(ctx.mainWindow),
  ]).catch(() => { /* non-critical */ });

  ctx.tray.create();

  // ── Phase 9: Background warm-up ──
  scheduleBackgroundWarmup();
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

function closeStaleSessionsForAllAgents(): void {
  const config = getConfig();
  const defaultAgent = config.AGENT_NAME;
  const allAgents = discoverAgents();
  for (const agent of allAgents) {
    try {
      config.reloadForAgent(agent.name);
      initDb();
      const staleClosed = closeStaleOpenSessions();
      if (staleClosed > 0) {
        log.info(`closed ${staleClosed} stale open session(s) for agent ${agent.name}`);
      }
    } catch (e) {
      log.warn(`failed to clean stale sessions for ${agent.name}: ${e}`);
    }
  }
  config.reloadForAgent(defaultAgent);
  initDb();
}

function discoverAndWireAgents(ctx: AppContext): void {
  // MCP registry
  try {
    mcpRegistry.discover();
    mcpRegistry.registerWithSwitchboard(switchboard);
    log.info(`MCP registry: ${mcpRegistry.getRegistry().length} server(s) discovered`);
  } catch (e) {
    log.warn(`MCP registry init failed (non-fatal): ${e}`);
  }

  // Wire all agents through switchboard
  const agents = discoverAgents();
  let wiredCount = 0;
  for (const agent of agents) {
    try {
      const manifestPath = path.join(getAgentDir(agent.name), 'data', 'agent.json');
      if (fs.existsSync(manifestPath)) {
        const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
        wireAgent(agent.name, manifest);
        wiredCount++;
      } else {
        log.warn(`manifest not found for "${agent.name}" at ${manifestPath}`);
      }
    } catch (e) {
      log.warn(`failed to wire agent "${agent.name}": ${e}`);
    }
  }
  log.info(`switchboard: ${wiredCount}/${agents.length} agent(s) wired`);
  markBootComplete();

  // Initialize tmux pool
  const config = getConfig();
  const pool = getTmuxPool();
  if (pool) {
    pool.ensureSession();
    const primaryAgents = agents.filter(a => {
      try {
        const mp = path.join(getAgentDir(a.name), 'data', 'agent.json');
        const m = JSON.parse(fs.readFileSync(mp, 'utf-8'));
        return m.channels?.desktop?.enabled || m.channels?.telegram?.enabled;
      } catch { return false; }
    });

    for (const agent of primaryAgents) {
      try {
        config.reloadForAgent(agent.name);
        initDb();
        const lastSession = getLastCliSessionId() || uuidv4();
        const mcpConfig = mcpRegistry.buildConfigForAgent(agent.name);

        pool.createWindow(agent.name, {
          sessionId: lastSession,
          claudeBin: config.CLAUDE_BIN,
          mcpConfigPath: mcpConfig,
        });

        setTimeout(() => {
          try { pool.pressEnter(agent.name); } catch (e) {
            log.warn(`[${agent.name}] tmux Enter failed: ${e}`);
          }
        }, 1000);
      } catch (e) {
        log.warn(`[${agent.name}] tmux window creation failed: ${e}`);
      }
    }

    const lastActive = getLastActiveAgent() || 'xan';
    config.reloadForAgent(lastActive);
    initDb();

    log.info(`tmux pool: ${pool.agentNames().length} agent(s) ready`);
    pool.startHealthCheck();
  } else {
    log.info('tmux not available - using one-shot spawn for inference');
  }
}

function startServices(ctx: AppContext, crashSafe: boolean): void {
  // Cron scheduler
  if (crashSafe) {
    try {
      cronScheduler.start();
      cronScheduler.registerWithSwitchboard();
      const schedule = cronScheduler.getSchedule();
      log.info(`cron scheduler: ${schedule.length} job(s) scheduled`);
    } catch (e) {
      log.warn(`cron scheduler start failed (non-fatal): ${e}`);
    }

    // Cron output notification
    cronOutputEmitter.on('output', async (data: { agentName: string; agentDisplayName: string; jobName: string; text: string }) => {
      if (isAway()) return;

      const jobLabel = data.jobName.charAt(0).toUpperCase() + data.jobName.slice(1);
      const played = await sendCronNotification(data.agentDisplayName, jobLabel, data.text);

      if (played) {
        log.info(`[cron-notify] playing TTS for ${data.agentName}.${data.jobName}`);
        try {
          await waitForAudioIdle();

          const cfg = getConfig();
          const prevAgent = cfg.AGENT_NAME;
          if (cfg.AGENT_NAME !== data.agentName) {
            cfg.reloadForAgent(data.agentName);
          }

          const audioPath = await synthesise(data.text);
          if (audioPath) {
            await playAudio(audioPath);
          }

          if (cfg.AGENT_NAME !== prevAgent) {
            cfg.reloadForAgent(prevAgent);
          }
        } catch (err) {
          log.error(`[cron-notify] TTS failed: ${err}`);
        }
      }
    });
  }

  // Reconcile launchd jobs
  try {
    const { execFile } = require('child_process');
    const reconcileScript = path.join(BUNDLE_ROOT, 'scripts', 'reconcile_jobs.py');
    if (fs.existsSync(reconcileScript)) {
      execFile(
        'python3',
        [reconcileScript, '--quiet'],
        {
          cwd: BUNDLE_ROOT,
          env: { ...process.env, PYTHONPATH: BUNDLE_ROOT },
          timeout: 15000,
        },
        (err: Error | null, stdout: string, _stderr: string) => {
          if (err) {
            log.debug(`job reconciler: ${err.message}`);
          } else if (stdout.trim()) {
            log.info(`job reconciler:\n${stdout.trim()}`);
          }
        },
      );
    }
  } catch (e) {
    log.debug(`job reconciler failed (non-fatal): ${e}`);
  }

  // Telegram daemon
  if (crashSafe) {
    log.info('calling startDaemon()');
    const started = startDaemon();
    log.info(`startDaemon returned ${started}`);
    if (started) {
      log.info('Telegram daemon auto-started');
    } else {
      log.debug('Telegram daemon not started (no agents with credentials, or lock held)');
    }
  }

  setMainWindowAccessor(() => ctx.mainWindow);

  // Federation
  startFederation().catch((e) => log.error(`federation start failed: ${e}`));

  // Switchboard queue polling
  switchboard.startQueuePolling();

  // Meridian web handler
  if (!switchboard.hasHandler('meridian:web')) {
    switchboard.register('meridian:web', async () => {
      log.debug('meridian:web received envelope (send-only channel, ignored)');
    }, {
      type: 'channel',
      description: 'Meridian Eye web interface',
      capabilities: ['chat', 'query'],
    });
  }

  // Meridian bridge + Cloudflare tunnel
  const tunnelConfigPath = path.join(USER_DATA, 'services', 'cloudflared', 'config.yml');
  if (fs.existsSync(tunnelConfigPath)) {
    startMeridianServer(3847, '127.0.0.1');

    try {
      const { execFileSync, spawn: spawnTunnel } = require('child_process');
      try { execFileSync('which', ['cloudflared'], { stdio: 'ignore' }); } catch {
        log.info('cloudflared not installed - skipping Meridian tunnel');
        throw new Error('cloudflared not found');
      }
      const tunnelProc = spawnTunnel('cloudflared', ['tunnel', 'run', '--config', tunnelConfigPath], {
        stdio: 'ignore',
        detached: true,
      });
      tunnelProc.unref();
      log.info('Cloudflare Tunnel started for Meridian bridge');
    } catch (e) {
      if (String(e) !== 'Error: cloudflared not found') {
        log.warn(`failed to start Cloudflare Tunnel (non-fatal): ${e}`);
      }
    }
  }

  // Daily agent backup
  backupAgentData();

  // Voice agent
  import('./voice-agent').then(({ configureVoiceAgent }) => {
    configureVoiceAgent({
      getWindow: () => ctx.mainWindow,
      setCliSessionId: (id: string) => { if (ctx.currentSession) ctx.currentSession.setCliSessionId(id); },
    });
  });

  const config = getConfig();
  if (config.ELEVENLABS_API_KEY) {
    import('./voice-agent').then(({ provisionAgent }) => {
      provisionAgent(config.AGENT_NAME).catch(() => { /* non-critical */ });
    });
  }
}

function scheduleBackgroundWarmup(): void {
  setImmediate(() => prefetchContext());

  setTimeout(() => {
    import('./opening').then(({ precacheAllOpenings }) => {
      precacheAllOpenings();
    }).catch(() => { /* non-fatal */ });
  }, 10_000);

  setTimeout(() => {
    import('./kokoro').then(({ ensureKokoroReady }) => {
      ensureKokoroReady().catch(() => { /* non-fatal */ });
    }).catch(() => { /* non-fatal */ });
  }, 20_000);
}

// ---------------------------------------------------------------------------
// Agent switching
// ---------------------------------------------------------------------------

async function switchAgentImpl(ctx: AppContext, name: string): Promise<SwitchAgentResult> {
  if (!isValidAgentName(name)) throw new Error('Invalid agent name');
  const knownAgents = discoverAgents();
  if (!knownAgents.some(a => a.name === name)) {
    throw new Error(`Agent "${name}" not found`);
  }

  stopInference(ctx.currentAgentName ?? undefined);
  clearAudioQueue();

  const oldSession = ctx.currentSession;
  const oldPrompt = ctx.systemPrompt;
  const oldAgentName = ctx.currentAgentName;
  if (oldSession?.sessionId != null) {
    endSession(oldSession.sessionId, null, oldSession.mood);
    if (oldPrompt && oldSession.turnHistory.length >= 4) {
      const sid = oldSession.sessionId;
      const turnHistory = [...oldSession.turnHistory];
      setImmediate(() => {
        generateDeferredSummary(sid, turnHistory, oldPrompt, oldAgentName || '').catch(() => {});
      });
    }
  }
  ctx.currentSession = null;
  ctx.systemPrompt = null;

  const oldDbPath = getConfig().DB_PATH;
  setTimeout(() => {
    import('./memory').then(({ closeForPath }) => closeForPath(oldDbPath));
  }, 5000);

  getConfig().reloadForAgent(name);
  initDb();
  resetMcpConfig();
  invalidateContextCache();
  ctx.currentAgentName = name;
  setLastActiveAgent(name);
  ctx.tray.invalidateAgentCache();

  setImmediate(() => prefetchContext());

  if (getConfig().ELEVENLABS_API_KEY) {
    import('./voice-agent').then(({ provisionAgent }) => {
      provisionAgent(name).catch(() => { /* non-critical */ });
    });
  }

  const c = getConfig();
  return {
    agentName: c.AGENT_NAME,
    agentDisplayName: c.AGENT_DISPLAY_NAME,
    customSetup: getCustomSetup(name),
  };
}

async function generateDeferredSummary(
  sessionId: number,
  turnHistory: { role: string; content: string; turnId: number }[],
  systemPrompt: string,
  oldAgentName: string,
): Promise<void> {
  const turnText = turnHistory
    .map((t) => {
      const label = t.role === 'will' ? 'Will' : oldAgentName;
      return `${label}: ${t.content}`;
    })
    .join('\n');

  const summaryPrompt =
    'Summarise this conversation in 2-4 sentences.\n\n' +
    'Capture what actually happened between these two people, not just the topic.\n' +
    'If something shifted - in the relationship, in understanding, in how they talk ' +
    'to each other - name it. Do not use em dashes - only hyphens.\n\n' +
    turnText;

  try {
    const { runInferenceOneshot } = await import('./inference');
    const summary = await runInferenceOneshot(
      [{ role: 'user', content: summaryPrompt }],
      `You are ${oldAgentName}, writing a memory of a conversation. Third person. 2-4 sentences.`,
    );

    if (summary && summary.trim()) {
      const Database = (await import('better-sqlite3')).default;
      const dbPath = path.join(getAgentDir(oldAgentName), 'data', 'memory.db');
      const db = new Database(dbPath);
      try {
        db.prepare(
          'UPDATE sessions SET ended_at = CURRENT_TIMESTAMP, summary = ? WHERE id = ?',
        ).run(summary.trim(), sessionId);
        db.prepare(
          'INSERT INTO summaries (session_id, content) VALUES (?, ?)',
        ).run(sessionId, summary.trim());
        log.info(`[deferred-summary] written for ${oldAgentName} session ${sessionId}`);
      } finally {
        db.close();
      }
    }
  } catch (err) {
    log.warn(`[deferred-summary] failed for ${oldAgentName}: ${err}`);
  }
}

// ---------------------------------------------------------------------------
// Crash rate limiter
// ---------------------------------------------------------------------------

const CRASH_LOG_PATH = path.join(USER_DATA, 'crash-log.json');
const CRASH_WINDOW_MS = 10 * 60 * 1000;
const MAX_CRASHES_IN_WINDOW = 5;

function readCrashTimestamps(): number[] {
  try {
    if (!fs.existsSync(CRASH_LOG_PATH)) return [];
    const raw = JSON.parse(fs.readFileSync(CRASH_LOG_PATH, 'utf-8'));
    if (Array.isArray(raw) && raw.every((v) => typeof v === 'number')) return raw;
    fs.unlinkSync(CRASH_LOG_PATH);
    return [];
  } catch {
    try { fs.unlinkSync(CRASH_LOG_PATH); } catch { /* already gone */ }
    return [];
  }
}

export function recordCrash(): void {
  try {
    const cutoff = Date.now() - CRASH_WINDOW_MS;
    const timestamps = readCrashTimestamps().filter((t) => t > cutoff);
    timestamps.push(Date.now());
    fs.writeFileSync(CRASH_LOG_PATH, JSON.stringify(timestamps));
  } catch { /* best effort */ }
}

export function isCrashRateSafe(): boolean {
  const cutoff = Date.now() - CRASH_WINDOW_MS;
  const recent = readCrashTimestamps().filter((t) => t > cutoff);
  return recent.length < MAX_CRASHES_IN_WINDOW;
}
```

- [ ] **Step 2: Verify typecheck passes**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit -p tsconfig.node.json 2>&1 | tail -10`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/main/boot.ts
git commit -m "refactor: extract boot sequence orchestrator from app.ts whenReady()"
```

---

### Task 6: Rewrite `app.ts` - Lifecycle Shell Only

**Files:**
- Modify: `src/main/app.ts` (full rewrite - from 1,478 lines to ~120 lines)

This is the payoff. Replace the entire file with a thin lifecycle shell that delegates to the extracted modules.

- [ ] **Step 1: Rewrite `src/main/app.ts`**

Replace the entire contents of `src/main/app.ts` with:

```typescript
/**
 * Electron main process entry point.
 * Loaded by bootstrap.ts - either from the frozen asar or a hot bundle.
 *
 * This file owns ONLY Electron lifecycle hooks. All domain logic lives in:
 * - boot.ts         (startup orchestration)
 * - timers.ts        (interval timers, journal nudge, keep-awake)
 * - tray-manager.ts  (system tray, context menu)
 * - window-manager.ts (window creation, global shortcuts)
 * - app-context.ts   (shared mutable state)
 */

import { app, globalShortcut } from 'electron';

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
```

- [ ] **Step 2: Verify typecheck passes**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit -p tsconfig.node.json 2>&1 | tail -20`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/main/app.ts
git commit -m "refactor: reduce app.ts to lifecycle shell (1478 -> ~120 lines)"
```

---

### Task 7: Update `ipc-handlers.ts` - Migrate IpcContext to AppContext

**Files:**
- Modify: `src/main/ipc-handlers.ts:1-66`

Make `IpcContext` work with `AppContext`. Since `AppContext` is a superset, the IPC handler modules don't need changes - only the type definition and registration function.

- [ ] **Step 1: Update `ipc-handlers.ts` to import from `app-context.ts`**

Replace the entire file contents with:

```typescript
/**
 * IPC handler registration - thin orchestrator.
 * Domain-specific handlers live in src/main/ipc/*.ts.
 * This file defines the shared IpcContext interface and delegates
 * registration to each domain module.
 */

import type { BrowserWindow } from 'electron';
import type { Session } from './session';
import type { HotBundlePaths } from './bundle-updater';
import type { TrayState } from './icon';
import type { AppContext, SwitchAgentResult } from './app-context';

import {
  registerConfigHandlers,
  registerAgentHandlers,
  registerInferenceHandlers,
  registerAudioHandlers,
  registerTelegramHandlers,
  registerSystemHandlers,
  registerWindowHandlers,
} from './ipc/index';

// Re-export for any IPC handler modules that import SwitchAgentResult from here
export type { SwitchAgentResult } from './app-context';

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

/**
 * IpcContext is the view of AppContext that IPC handlers see.
 * It's structurally compatible with AppContext, so passing an AppContext
 * directly works without adapters.
 */
export interface IpcContext {
  mainWindow: BrowserWindow | null;
  currentSession: Session | null;
  systemPrompt: string | null;
  currentAgentName: string | null;
  pendingAskId: string | null;
  pendingAskDestination: string | null;
  pendingAskAgent: string | null;
  pendingBundleVersion: string | null;
  readonly hotBundle: HotBundlePaths | null;
  readonly isMenuBarMode: boolean;
  // Functions - available on both IpcContext and AppContext
  switchAgent: (name: string) => Promise<SwitchAgentResult>;
  rebuildTrayMenu: () => void;
  updateTrayState: (state: TrayState) => void;
  isKeepAwakeActive: () => boolean;
  toggleKeepAwake: () => void;
  resetJournalNudgeTimer: () => void;
  registerDesktopHandler?: (agentName: string) => void;
}

// ---------------------------------------------------------------------------
// Handler registration
// ---------------------------------------------------------------------------

export function registerIpcHandlers(ctx: IpcContext): void {
  registerConfigHandlers(ctx);
  registerAgentHandlers(ctx);
  registerInferenceHandlers(ctx);
  registerAudioHandlers(ctx);
  registerTelegramHandlers(ctx);
  registerSystemHandlers(ctx);
  registerWindowHandlers(ctx);
}
```

- [ ] **Step 2: Update `boot.ts` to pass AppContext as IpcContext-compatible**

In `boot.ts`, the `registerIpcHandlers` call currently uses `ctx as any`. We need to make `AppContext` structurally compatible with `IpcContext` by adding the function delegates. Add this block in `boot.ts` right before the `registerIpcHandlers` call (inside the Phase 3 section):

Find the line `registerIpcHandlers(ctx as any);` in `boot.ts` and replace with:

```typescript
  // Build IpcContext-compatible view of AppContext.
  // IpcContext expects function properties; AppContext stores them on managers.
  const ipcView = Object.create(ctx, {
    rebuildTrayMenu: { get: () => () => ctx.tray.rebuildMenu() },
    updateTrayState: { get: () => (state: any) => ctx.tray.updateState(state) },
    isKeepAwakeActive: { get: () => () => ctx.timers.isKeepAwakeActive() },
    toggleKeepAwake: { get: () => () => ctx.timers.toggleKeepAwake() },
    resetJournalNudgeTimer: { get: () => () => ctx.timers.resetJournalNudge() },
  });
  registerIpcHandlers(ipcView);
```

- [ ] **Step 3: Verify typecheck passes**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx tsc --noEmit -p tsconfig.node.json 2>&1 | tail -20`
Expected: No errors

- [ ] **Step 4: Verify existing tests pass**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && npx vitest run 2>&1 | tail -20`
Expected: All existing tests pass unchanged

- [ ] **Step 5: Commit**

```bash
git add src/main/ipc-handlers.ts src/main/boot.ts
git commit -m "refactor: bridge IpcContext to AppContext for IPC handler compatibility"
```

---

### Task 8: Build Verification + Smoke Test

**Files:**
- None (verification only)

Full build and manual verification that the refactored app works identically.

- [ ] **Step 1: Run typecheck**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && pnpm typecheck 2>&1 | tail -20`
Expected: No errors across both tsconfig.node.json and tsconfig.web.json

- [ ] **Step 2: Run full build**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && pnpm build 2>&1 | tail -20`
Expected: Clean build, no warnings about missing modules

- [ ] **Step 3: Run existing tests**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && pnpm test 2>&1 | tail -30`
Expected: All existing tests pass - no regressions

- [ ] **Step 4: Verify file sizes match expectations**

Run: `cd "/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron" && wc -l src/main/app.ts src/main/app-context.ts src/main/timers.ts src/main/tray-manager.ts src/main/window-manager.ts src/main/boot.ts`

Expected approximate line counts:
- `app.ts`: ~120-150
- `app-context.ts`: ~70-80
- `timers.ts`: ~300-350
- `tray-manager.ts`: ~170-200
- `window-manager.ts`: ~140-170
- `boot.ts`: ~400-450

- [ ] **Step 5: Commit verification results**

No commit needed if all passes. If fixes were required, commit them:

```bash
git add -A
git commit -m "fix: address typecheck/build issues from app.ts decomposition"
```

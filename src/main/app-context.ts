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

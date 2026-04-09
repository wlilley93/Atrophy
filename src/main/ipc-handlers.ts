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
import type { SwitchAgentResult } from './app-context';

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

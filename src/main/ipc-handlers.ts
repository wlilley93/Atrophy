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

import {
  registerConfigHandlers,
  registerAgentHandlers,
  registerInferenceHandlers,
  registerAudioHandlers,
  registerTelegramHandlers,
  registerSystemHandlers,
  registerWindowHandlers,
} from './ipc/index';

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

export interface SwitchAgentResult {
  agentName: string;
  agentDisplayName: string;
  customSetup: string | null;
}

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
  // Functions from app.ts
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

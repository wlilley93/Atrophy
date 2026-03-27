# src/main/ipc-handlers.ts - IPC Handler Registration

**Dependencies:** `electron`, `./session`, `./bundle-updater`, `./icon`, `./ipc/*`  
**Purpose:** Thin orchestrator that defines shared `IpcContext` interface and delegates registration to domain modules

## Overview

This module serves as the central registration point for all IPC (Inter-Process Communication) handlers between the main process and renderer. Instead of having one monolithic handler file, handlers are organized by domain (config, agents, inference, audio, telegram, system, window) in separate files under `src/main/ipc/`.

## IpcContext Interface

The `IpcContext` interface defines the shared state and functions that all IPC handler domains need access to:

```typescript
export interface IpcContext {
  // Window reference
  mainWindow: BrowserWindow | null;
  
  // Session state
  currentSession: Session | null;
  systemPrompt: string | null;
  currentAgentName: string | null;
  
  // Ask-user state
  pendingAskId: string | null;
  pendingAskDestination: string | null;
  
  // Bundle state
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
```

**Why this pattern:** The context object allows IPC handlers to access module-level state from `app.ts` without exporting all those variables. The getter/setter pattern in `app.ts` ensures handlers read current values, not stale closure captures.

## SwitchAgentResult Interface

```typescript
export interface SwitchAgentResult {
  agentName: string;
  agentDisplayName: string;
  customSetup: string | null;
}
```

**Purpose:** Standardized return type for agent switching operations.

## registerIpcHandlers Function

```typescript
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

**Purpose:** Delegate handler registration to domain modules. Called once during app startup in `app.ts`.

**Registration order:** The order doesn't matter since each domain registers independent channels, but the convention is:
1. Config (foundation)
2. Agents (identity)
3. Inference (core functionality)
4. Audio (voice input)
5. Telegram (external channel)
6. System (misc utilities)
7. Window (UI management)

## Domain Modules

| Module | Channels | Line Count |
|--------|----------|------------|
| `ipc/config.ts` | config:reload, config:get, config:apply, config:update | ~140 |
| `ipc/agents.ts` | agent:*, deferral:*, queue:*, mirror:*, ask:respond | ~184 |
| `ipc/inference.ts` | inference:send, inference:stop, status:*, opening:get | ~224 |
| `ipc/audio.ts` | audio:*, tts:*, stt:*, voice-agent:* | ~95 |
| `ipc/telegram.ts` | telegram:* | ~70 |
| `ipc/system.ts` | system:*, usage:*, activity:*, cron:*, mcp:*, server:*, logs:*, updater:* | ~235 |
| `ipc/window.ts` | window:*, setup:*, avatar:*, artefact:* | ~395 |

## Critical Pattern: Config Access

**IMPORTANT:** `getConfig()` must be called INSIDE each handler, never captured in a closure. The config object goes stale after agent switches.

```typescript
// WRONG - captures stale config
ipcMain.handle('some:handler', () => {
  const config = getConfig();  // Captured at registration time
  // This will use wrong agent config after agent switch!
});

// CORRECT - fresh config on each call
ipcMain.handle('some:handler', () => {
  const config = getConfig();  // Called on each invocation
  // Always gets current agent config
});
```

## See Also

- `src/main/app.ts` - Creates IpcContext and calls registerIpcHandlers
- `src/main/ipc/config.ts` - Configuration handlers
- `src/main/ipc/agents.ts` - Agent management handlers
- `src/main/ipc/inference.ts` - Inference handlers
- `src/main/ipc/audio.ts` - Audio handlers
- `src/main/ipc/telegram.ts` - Telegram handlers
- `src/main/ipc/system.ts` - System handlers
- `src/main/ipc/window.ts` - Window handlers

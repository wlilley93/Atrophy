# src/preload/index.ts - Preload Script

**Dependencies:** `electron` (`contextBridge`, `ipcRenderer`)  
**Purpose:** Exposes typed API to renderer via contextBridge

## Overview

The preload script runs in a privileged context between the main process and renderer. It uses Electron's `contextBridge` to expose a typed `AtrophyAPI` to the renderer, while keeping Node.js and Electron APIs inaccessible from renderer code.

## Security Model

```
┌─────────────────────────────────────────────────────────────────┐
│                    Electron Security Model                       │
│                                                                   │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────────┐   │
│  │ Main Process│◀───▶│   Preload   │◀───▶│   Renderer      │   │
│  │  (Node.js)  │ IPC │  (Bridge)   │ API │  (Svelte 5)     │   │
│  └─────────────┘     └─────────────┘     └─────────────────┘   │
│                            │                      │             │
│                            │                      │             │
│                    Full Node.js          No Node.js access      │
│                    access                contextIsolation=true  │
│                                            sandbox=true         │
└─────────────────────────────────────────────────────────────────┘
```

**Key settings (from app.ts):**
- `contextIsolation: true` - Renderer cannot access Node.js APIs
- `sandbox: true` - Additional security restrictions
- `nodeIntegration: false` - Node.js disabled in renderer

## AtrophyAPI Interface

The API is organized by functional area:

### Inference

```typescript
sendMessage: (text: string) => Promise<void>;
onTextDelta: (cb: (text: string) => void) => () => void;
onSentenceReady: (cb: (sentence: string, index: number, ttsActive: boolean) => void) => () => void;
onToolUse: (cb: (name: string) => void) => () => void;
onDone: (cb: (fullText: string) => void) => () => void;
onCompacting: (cb: () => void) => () => void;
onError: (cb: (message: string) => void) => () => void;
stopInference: () => Promise<void>;
```

### Audio Capture

```typescript
startRecording: () => Promise<void>;
stopRecording: () => Promise<string>;
sendAudioChunk: (buffer: ArrayBuffer) => void;
```

### TTS Playback

```typescript
onTtsStarted: (cb: (index: number) => void) => () => void;
onTtsDone: (cb: (index: number) => void) => () => void;
onTtsQueueEmpty: (cb: () => void) => () => void;
```

### Wake Word

```typescript
onWakeWordStart: (cb: (chunkSeconds: number) => void) => () => void;
onWakeWordStop: (cb: () => void) => () => void;
sendWakeWordChunk: (buffer: ArrayBuffer) => void;
```

### Agents

```typescript
switchAgent: (name: string) => Promise<{ agentName: string; agentDisplayName: string; customSetup: string | null }>;
getAgents: () => Promise<string[]>;
getAgentsFull: () => Promise<{ name: string; display_name: string; description: string; role: string }[]>;
onAgentSwitched: (cb: (data: { agentName: string; agentDisplayName: string; customSetup?: string | null }) => void) => () => void;
getAgentNotifyVia: (agentName: string) => Promise<string>;
getAgentDetail: (agentName: string) => Promise<Record<string, unknown> | null>;
updateAgentConfig: (agentName: string, updates: Record<string, unknown>) => Promise<void>;
```

### Agent Management (Settings)

```typescript
listAllAgents: () => Promise<...>;
getAgentManifest: (name: string) => Promise<Record<string, unknown>>;
updateAgentManifest: (name: string, updates: Record<string, unknown>) => Promise<void>;
getAgentPrompt: (name: string, promptName: string) => Promise<string>;
updateAgentPrompt: (name: string, promptName: string, content: string) => Promise<void>;
quickCreateAgent: (opts: {...}) => Promise<Record<string, unknown>>;
deleteAgent: (name: string) => Promise<void>;
```

### Config

```typescript
getConfig: () => Promise<Record<string, unknown>>;
reloadConfig: () => Promise<void>;
applyConfig: (updates: Record<string, unknown>) => Promise<void>;
updateConfig: (updates: Record<string, unknown>) => Promise<void>;
```

### Setup Wizard

```typescript
needsSetup: () => Promise<boolean>;
wizardInference: (text: string) => Promise<string>;
createAgent: (config: Record<string, string>) => Promise<Record<string, unknown>>;
saveSecret: (key: string, value: string) => Promise<void>;
verifyElevenLabs: (key: string) => Promise<{ ok: boolean; error?: string }>;
verifyFal: (key: string) => Promise<{ ok: boolean; error?: string }>;
verifyTelegram: (token: string) => Promise<{ ok: boolean; error?: string }>;
setupSpeak: (text: string) => Promise<void>;
startGoogleOAuth: (wantWorkspace: boolean, wantExtra: boolean) => Promise<string>;
healthCheck: () => Promise<{ ok: boolean; version?: string; bin?: string; hint?: string; error?: string; help?: string }>;
```

### Window Control

```typescript
toggleFullscreen: () => Promise<void>;
toggleAlwaysOnTop: () => Promise<void>;
minimizeWindow: () => Promise<void>;
closeWindow: () => Promise<void>;
```

### Queue Messages

```typescript
onQueueMessage: (cb: (msg: { text: string; source: string }) => void) => () => void;
```

### Opening Line

```typescript
getOpeningLine: () => Promise<string>;
```

### Login Item

```typescript
isLoginItemEnabled: () => Promise<boolean>;
toggleLoginItem: (enabled: boolean) => Promise<void>;
```

### Auto-Updater

```typescript
checkForUpdates: () => Promise<void>;
downloadUpdate: () => Promise<void>;
quitAndInstall: () => Promise<void>;
onUpdateAvailable: (cb: (info: { version: string; releaseNotes: unknown }) => void) => () => void;
onUpdateNotAvailable: (cb: () => void) => () => void;
onUpdateProgress: (cb: (progress: {...}) => void) => () => void;
onUpdateDownloaded: (cb: (info: { version: string }) => void) => () => void;
onUpdateError: (cb: (message: string) => void) => () => void;
```

### Avatar

```typescript
getAvatarAmbientPath: () => Promise<string | null>;
getAvatarVideoPath: (colour?: string, clip?: string) => Promise<string | null>;
listAvatarLoops: () => Promise<string[]>;
onAvatarDownloadStart: (cb: () => void) => () => void;
onAvatarDownloadProgress: (cb: (data: { percent: number; transferred: number; total: number }) => void) => () => void;
onAvatarDownloadComplete: (cb: () => void) => () => void;
onAvatarDownloadError: (cb: (message: string) => void) => () => void;
```

### Intro Audio

```typescript
playIntroAudio: () => Promise<void>;
playAgentAudio: (filename: string) => Promise<void>;
stopPlayback: () => Promise<void>;
setMuted: (muted: boolean) => Promise<void>;
isMuted: () => Promise<boolean>;
```

### GitHub Auth

```typescript
githubAuthStatus: () => Promise<{ installed: boolean; authenticated: boolean; account: string }>;
githubAuthLogin: () => Promise<{ success: boolean; error?: string }>;
```

### Shutdown

```typescript
requestShutdown: () => Promise<void>;
onShutdownRequested: (cb: () => void) => () => void;
```

### Usage & Activity

```typescript
getUsage: (days?: number) => Promise<unknown>;
getUsageDetail: (agentName: string, days?: number) => Promise<unknown>;
getActivity: (days?: number, limit?: number) => Promise<unknown>;
```

### Agent Deferral

```typescript
completeDeferral: (data: { target: string; context: string; user_question: string }) => Promise<{ agentName: string; agentDisplayName: string }>;
onDeferralRequest: (cb: (data: { target: string; context: string; user_question: string }) => void) => () => void;
```

### Ask-User (MCP)

```typescript
onAskUser: (cb: (data: { question: string; action_type: string; request_id: string; input_type?: string; label?: string; destination?: string }) => void) => () => void;
respondToAsk: (requestId: string, response: string | boolean | null) => Promise<void>;
```

### Artefacts

```typescript
getArtefactGallery: () => Promise<unknown[]>;
getArtefactContent: (filePath: string) => Promise<string | null>;
onArtefactLoading: (cb: (data: { name: string; type: string }) => void) => () => void;
```

### Inline Artifacts

```typescript
onArtifact: (cb: (artifact: { id: string; type: string; title: string; language: string; content: string }) => void) => () => void;
```

### Jobs / Cron

```typescript
getSchedule: () => Promise<unknown[]>;
getJobHistory: () => Promise<unknown[]>;
runJobNow: (agentName: string, jobName: string) => Promise<void>;
getSchedulerStatus: () => Promise<{ schedule: unknown[] }>;
addJob: (agentName: string, jobName: string, config: {...}) => Promise<void>;
editJob: (agentName: string, jobName: string, updates: Record<string, unknown>) => Promise<void>;
deleteJob: (agentName: string, jobName: string) => Promise<void>;
```

### Keep Awake

```typescript
toggleKeepAwake: () => Promise<boolean>;
```

### Logs

```typescript
getLogBuffer: () => Promise<unknown[]>;
onLogEntry: (cb: (entry: { timestamp: number; level: string; tag: string; message: string }) => void) => () => void;
```

### Voice Call

```typescript
startVoiceCall: () => Promise<boolean>;
stopVoiceCall: () => Promise<void>;
sendTextToCall: (text: string) => Promise<void>;
onVoiceCallStatus: (cb: (status: string) => void) => () => void;
onVoiceCallUserTranscript: (cb: (text: string) => void) => () => void;
onVoiceCallAgentResponse: (cb: (text: string) => void) => () => void;
onVoiceCallAudio: (cb: (audio: Buffer) => void) => () => void;
onVoiceCallError: (cb: (error: string) => void) => () => void;
onVoiceCallEnded: (cb: () => void) => () => void;
setVoiceCallMic: (muted: boolean) => Promise<void>;
setVoiceCallAudio: (enabled: boolean) => Promise<void>;
```

### Voice Agent

```typescript
startVoiceAgent: () => Promise<boolean>;
stopVoiceAgent: () => Promise<void>;
sendTextToAgent: (text: string) => Promise<void>;
onVoiceAgentStatus: (cb: (status: string) => void) => () => void;
onVoiceAgentUserTranscript: (cb: (text: string) => void) => () => void;
onVoiceAgentAgentResponse: (cb: (text: string) => void) => () => void;
onVoiceAgentAudio: (cb: (audio: Buffer) => void) => () => void;
onVoiceAgentError: (cb: (error: string) => void) => () => void;
onVoiceAgentEnded: (cb: () => void) => () => void;
setVoiceAgentMic: (muted: boolean) => Promise<void>;
setVoiceAgentAudio: (enabled: boolean) => Promise<void>;
```

### System Topology

```typescript
getSystemTopology: () => Promise<unknown>;
toggleConnection: (agentName: string, serverName: string, enabled: boolean) => Promise<void>;
```

### Memory Search

```typescript
memorySearch: (query: string, n?: number) => Promise<unknown[]>;
```

### Telegram

```typescript
telegramStartDaemon: () => Promise<boolean>;
telegramStopDaemon: () => Promise<void>;
telegramIsRunning: () => Promise<boolean>;
telegramDiscoverChatId: (botToken: string, agentName?: string) => Promise<{ chatId: string; chatType: string; chatTitle?: string } | null>;
telegramSaveAgentBotToken: (agentName: string, botToken: string) => Promise<void>;
telegramSetBotPhoto: (agentName: string, botToken: string) => Promise<boolean>;
telegramGetAgentConfig: (agentName: string) => Promise<{ botToken: string; chatId: string }>;
```

### Organizations

```typescript
listOrgs: () => Promise<unknown[]>;
getOrgDetail: (slug: string) => Promise<unknown>;
createOrg: (name: string, type: string, purpose: string) => Promise<unknown>;
dissolveOrg: (slug: string) => Promise<void>;
addAgentToOrg: (orgSlug: string, agentName: string, role: string, tier: number, reportsTo: string | null) => Promise<void>;
removeAgentFromOrg: (agentName: string) => Promise<void>;
```

## Event Listener Pattern

All event listeners return an unsubscribe function:

```typescript
// Subscribe
const unsubscribe = api.onTextDelta((text) => {
  console.log('Delta:', text);
});

// Unsubscribe (e.g., on component unmount)
unsubscribe();
```

## IPC Channel Mapping

Each API method maps to an IPC channel:

```typescript
// Example: sendMessage
sendMessage: (text) => ipcRenderer.invoke('inference:send', text)

// Example: onTextDelta
onTextDelta: (cb) => {
  const listener = (_event, text) => cb(text);
  ipcRenderer.on('inference:textDelta', listener);
  return () => ipcRenderer.removeListener('inference:textDelta', listener);
}
```

## Usage in Renderer

```typescript
// In Svelte component
import { api } from './preload';

// Call API
await api.sendMessage('Hello!');

// Subscribe to events
onMount(() => {
  const unsubscribe = api.onTextDelta((text) => {
    transcript += text;
  });
  
  return unsubscribe;  // Cleanup on unmount
});
```

## Exported API

```typescript
export const api: AtrophyAPI;
```

**Access:** `import { api } from './preload'` in renderer code

## See Also

- `src/main/ipc-handlers.ts` - Main process IPC handler registration
- `src/main/ipc/*.ts` - Individual IPC handler modules
- `src/renderer/components/*.svelte` - Renderer components using the API

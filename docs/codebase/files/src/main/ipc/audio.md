# src/main/ipc/audio.ts - Audio IPC Handlers

**Line count:** ~80 lines  
**Dependencies:** `electron`, `path`, `fs`, `../config`, `../tts`, `../voice-agent`, `../ipc-handlers`  
**Purpose:** IPC handlers for audio playback, muting, and voice agent control

## Overview

This module provides the renderer with controls for:
- Playing intro audio on startup
- Playing named audio files from agent's audio directory
- Stopping playback
- Muting/unmuting TTS
- Voice agent control (start, stop, send text, status, mic, audio output)

## IPC Handlers

### Intro Audio

#### audio:playIntro

```typescript
ipcMain.handle('audio:playIntro', async () => {
  const c = getConfig();
  const introCandidates = [
    path.join(USER_DATA, 'agents', c.AGENT_NAME, 'audio', 'intro.mp3'),
    path.join(BUNDLE_ROOT, 'agents', c.AGENT_NAME, 'audio', 'intro.mp3'),
  ];
  for (const introPath of introCandidates) {
    if (fs.existsSync(introPath)) {
      try {
        await playAudio(introPath, undefined, false);
      } catch { /* non-critical */ }
      break;
    }
  }
});
```

**Purpose:** Play agent-specific intro audio on first launch or boot.

**Search order:**
1. User data: `~/.atrophy/agents/<name>/audio/intro.mp3`
2. Bundle: `<bundle>/agents/<name>/audio/intro.mp3`

**cleanupFile = false:** Intro files are permanent, not temp files.

### Agent Audio

#### audio:playAgentAudio

```typescript
ipcMain.handle('audio:playAgentAudio', async (_event, filename: string) => {
  // Validate filename to prevent path traversal
  if (!/^[a-zA-Z0-9_-]+\.(mp3|wav|m4a)$/.test(filename)) return;
  const c = getConfig();
  const candidates = [
    path.join(USER_DATA, 'agents', c.AGENT_NAME, 'audio', filename),
    path.join(BUNDLE_ROOT, 'agents', c.AGENT_NAME, 'audio', filename),
  ];
  for (const audioPath of candidates) {
    if (fs.existsSync(audioPath)) {
      try {
        await playAudio(audioPath, undefined, false);
      } catch { /* non-critical */ }
      break;
    }
  }
});
```

**Purpose:** Play any named audio file from agent's audio directory.

**Security:** Filename validation prevents path traversal attacks:
```typescript
/^[a-zA-Z0-9_-]+\.(mp3|wav|m4a)$/
```

Only alphanumeric, hyphens, underscores, and safe extensions allowed.

### Playback Control

#### audio:stopPlayback

```typescript
ipcMain.handle('audio:stopPlayback', () => {
  clearAudioQueue();
  stopCurrentPlayback();
});
```

**Purpose:** Stop all audio playback - clears queue and kills current afplay process.

#### audio:setMuted

```typescript
ipcMain.handle('audio:setMuted', (_event, muted: boolean) => {
  setMuted(muted);
});
```

**Purpose:** Mute/unmute TTS playback.

#### audio:isMuted

```typescript
ipcMain.handle('audio:isMuted', () => {
  return isMuted();
});
```

**Returns:** Current mute state

### Voice Agent Control

All voice agent handlers use dynamic imports to avoid circular dependencies:

#### voice-agent:start

```typescript
ipcMain.handle('voice-agent:start', async () => {
  const { startVoiceAgent } = await import('../voice-agent');
  return startVoiceAgent();
});
```

**Returns:** `true` if connection initiated, `false` on failure

#### voice-agent:stop

```typescript
ipcMain.handle('voice-agent:stop', async () => {
  const { stopVoiceAgent } = await import('../voice-agent');
  stopVoiceAgent();
});
```

**Purpose:** Stop voice agent and close WebSocket.

#### voice-agent:sendText

```typescript
ipcMain.handle('voice-agent:sendText', async (_event, text: string) => {
  const { sendText } = await import('../voice-agent');
  await sendText(text);
});
```

**Purpose:** Inject text into voice call as if user spoke it.

#### voice-agent:status

```typescript
ipcMain.handle('voice-agent:status', async () => {
  const { getVoiceAgentStatus } = await import('../voice-agent');
  return getVoiceAgentStatus();
});
```

**Returns:** `{ active: boolean; status: 'connecting' | 'active' | 'disconnected'; muted: boolean }`

#### voice-agent:setMic

```typescript
ipcMain.handle('voice-agent:setMic', async (_event, muted: boolean) => {
  const { setMicMuted } = await import('../voice-agent');
  setMicMuted(muted);
});
```

**Purpose:** Mute/unmute microphone during voice call.

#### voice-agent:setAudio

```typescript
ipcMain.handle('voice-agent:setAudio', async (_event, enabled: boolean) => {
  const { setAudioOutputEnabled } = await import('../voice-agent');
  setAudioOutputEnabled(enabled);
});
```

**Purpose:** Enable/disable audio output (text-only mode when disabled).

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/agents/<name>/audio/intro.mp3` | audio:playIntro |
| Read | `<bundle>/agents/<name>/audio/intro.mp3` | audio:playIntro |
| Read | `~/.atrophy/agents/<name>/audio/<filename>` | audio:playAgentAudio |
| Read | `<bundle>/agents/<name>/audio/<filename>` | audio:playAgentAudio |
| Read/Write | `/tmp/atrophy-tts-*.mp3` | TTS playback |

## Security Considerations

### Filename Validation

```typescript
/^[a-zA-Z0-9_-]+\.(mp3|wav|m4a)$/
```

Prevents path traversal attacks by:
- Only allowing alphanumeric, hyphens, underscores in filename
- Only allowing safe audio extensions
- Rejecting any `/`, `..`, or other path components

### Dynamic Imports

```typescript
const { startVoiceAgent } = await import('../voice-agent');
```

Avoids circular dependencies between audio and voice-agent modules.

## Exported API

| Function | Purpose |
|----------|---------|
| `registerAudioHandlers(ctx)` | Register all audio IPC handlers |

## See Also

- `src/main/tts.ts` - TTS playback and muting
- `src/main/voice-agent.ts` - Voice agent implementation
- `src/main/config.ts` - Path resolution

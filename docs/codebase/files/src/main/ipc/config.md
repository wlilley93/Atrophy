# src/main/ipc/config.ts - Configuration IPC Handlers

**Line count:** ~140 lines  
**Dependencies:** `electron`, `../config`, `../memory`, `../channels/telegram`, `../ipc-handlers`  
**Purpose:** IPC handlers for configuration management (read, update, apply)

## Overview

This module provides the renderer process with controlled access to configuration. It exposes handlers for reading config, applying runtime-only changes, and persisting changes to disk.

## Key Allowlists

### Agent Configuration Keys

```typescript
const agentKeys = new Set([
  'AGENT_DISPLAY_NAME', 'TTS_BACKEND', 'TTS_PLAYBACK_RATE',
  'ELEVENLABS_VOICE_ID', 'ELEVENLABS_MODEL', 'ELEVENLABS_STABILITY',
  'ELEVENLABS_SIMILARITY', 'ELEVENLABS_STYLE', 'FAL_VOICE_ID',
  'HEARTBEAT_ACTIVE_START', 'HEARTBEAT_ACTIVE_END', 'HEARTBEAT_INTERVAL_MINS',
  'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'WINDOW_WIDTH', 'WINDOW_HEIGHT',
  'DISABLED_TOOLS', 'WAKE_WORDS',
]);
```

**Purpose:** These keys are saved to the agent's `agent.json` manifest. Changes affect only the current agent.

### User Configuration Keys

```typescript
const userKeys = new Set([
  'USER_NAME', 'INPUT_MODE', 'PTT_KEY', 'WAKE_WORD_ENABLED',
  'WAKE_CHUNK_SECONDS', 'SAMPLE_RATE', 'MAX_RECORD_SEC',
  'CLAUDE_BIN', 'CLAUDE_MODEL', 'CLAUDE_EFFORT', 'ADAPTIVE_EFFORT',
  'CONTEXT_SUMMARIES', 'MAX_CONTEXT_TOKENS', 'VECTOR_SEARCH_WEIGHT',
  'EMBEDDING_MODEL', 'EMBEDDING_DIM', 'SESSION_SOFT_LIMIT_MINS',
  'NOTIFICATIONS_ENABLED', 'SILENCE_TIMER_ENABLED', 'SILENCE_TIMER_MINUTES',
  'EYE_MODE_DEFAULT', 'MUTE_BY_DEFAULT', 'AVATAR_ENABLED', 'AVATAR_RESOLUTION',
  'OBSIDIAN_VAULT', 'setup_complete',
]);
```

**Purpose:** These keys are saved to the global `~/.atrophy/config.json`. Changes affect all agents.

### Safe Keys

```typescript
const safeKeys = new Set([...agentKeys, ...userKeys]);
```

**Purpose:** Combined allowlist for validation. Any key not in this set is silently dropped.

## IPC Handlers

### config:reload

```typescript
ipcMain.handle('config:reload', () => {
  reloadConfig();
});
```

**Purpose:** Force reload of configuration from disk. Used after external changes.

### config:get

```typescript
ipcMain.handle('config:get', () => {
  const c = getConfig();
  return {
    // Identity
    agentName: c.AGENT_NAME,
    agentDisplayName: c.AGENT_DISPLAY_NAME,
    userName: c.USER_NAME,
    wakeWords: c.WAKE_WORDS,
    disabledTools: c.DISABLED_TOOLS,
    // Voice
    ttsBackend: c.TTS_BACKEND,
    elevenlabsApiKey: c.ELEVENLABS_API_KEY ? '***' : '',  // Masked
    elevenlabsVoiceId: c.ELEVENLABS_VOICE_ID,
    elevenlabsModel: c.ELEVENLABS_MODEL,
    elevenlabsStability: c.ELEVENLABS_STABILITY,
    elevenlabsSimilarity: c.ELEVENLABS_SIMILARITY,
    elevenlabsStyle: c.ELEVENLABS_STYLE,
    ttsPlaybackRate: c.TTS_PLAYBACK_RATE,
    falApiKey: process.env.FAL_KEY ? '***' : '',  // Masked
    falVoiceId: c.FAL_VOICE_ID,
    // Input
    inputMode: c.INPUT_MODE,
    pttKey: c.PTT_KEY,
    wakeWordEnabled: c.WAKE_WORD_ENABLED,
    wakeChunkSeconds: c.WAKE_CHUNK_SECONDS,
    // Audio
    sampleRate: c.SAMPLE_RATE,
    maxRecordSec: c.MAX_RECORD_SEC,
    // Inference
    claudeBin: c.CLAUDE_BIN,
    claudeModel: c.CLAUDE_MODEL,
    claudeEffort: c.CLAUDE_EFFORT,
    adaptiveEffort: c.ADAPTIVE_EFFORT,
    // Memory
    contextSummaries: c.CONTEXT_SUMMARIES,
    maxContextTokens: c.MAX_CONTEXT_TOKENS,
    vectorSearchWeight: c.VECTOR_SEARCH_WEIGHT,
    embeddingModel: c.EMBEDDING_MODEL,
    embeddingDim: c.EMBEDDING_DIM,
    // Session
    sessionSoftLimitMins: c.SESSION_SOFT_LIMIT_MINS,
    // Heartbeat
    heartbeatActiveStart: c.HEARTBEAT_ACTIVE_START,
    heartbeatActiveEnd: c.HEARTBEAT_ACTIVE_END,
    heartbeatIntervalMins: c.HEARTBEAT_INTERVAL_MINS,
    // Telegram
    telegramBotToken: c.TELEGRAM_BOT_TOKEN ? '***' : '',  // Masked
    telegramChatId: c.TELEGRAM_CHAT_ID,
    telegramDaemonRunning: isDaemonRunning(),
    // Keep Awake
    keepAwakeActive: ctx.isKeepAwakeActive(),
    // Notifications
    notificationsEnabled: c.NOTIFICATIONS_ENABLED,
    // Silence timer
    silenceTimerEnabled: c.SILENCE_TIMER_ENABLED,
    silenceTimerMinutes: c.SILENCE_TIMER_MINUTES,
    // UI defaults
    eyeModeDefault: c.EYE_MODE_DEFAULT,
    muteByDefault: c.MUTE_BY_DEFAULT,
    // Window
    windowWidth: c.WINDOW_WIDTH,
    windowHeight: c.WINDOW_HEIGHT,
    avatarEnabled: c.AVATAR_ENABLED,
    avatarResolution: c.AVATAR_RESOLUTION,
    // Paths
    obsidianVault: c.OBSIDIAN_VAULT,
    dbPath: c.DB_PATH,
    whisperBin: c.WHISPER_BIN,
    // Google
    googleConfigured: c.GOOGLE_CONFIGURED,
    // About
    version: c.VERSION,
    bundleVersion: ctx.hotBundle?.version ?? null,
    bundleRoot: BUNDLE_ROOT,
  };
});
```

**Security:** API keys are masked (`***`) before sending to renderer. The renderer never sees actual secret values.

**Returns:** Flat object with all configuration values for the Settings panel.

### config:apply

```typescript
ipcMain.handle('config:apply', (_event, updates: Record<string, unknown>) => {
  const c = getConfig();
  for (const [key, value] of Object.entries(updates)) {
    if (!safeKeys.has(key)) continue;
    if (key in c) {
      (c as unknown as Record<string, unknown>)[key] = value;
    }
  }
});
```

**Purpose:** Apply updates to running config only - no disk write. Lets users test runtime changes before committing them.

**Use case:** Settings panel "Apply" button for testing changes without persistence.

### config:update

```typescript
ipcMain.handle('config:update', (_event, updates: Record<string, unknown>) => {
  const c = getConfig();
  const userUpdates: Record<string, unknown> = {};
  const agentUpdates: Record<string, unknown> = {};

  const previousUserName = c.USER_NAME;

  for (const [key, value] of Object.entries(updates)) {
    if (!safeKeys.has(key)) continue;
    if (key in c) {
      (c as unknown as Record<string, unknown>)[key] = value;
    }
    if (agentKeys.has(key)) {
      agentUpdates[key] = value;
    } else {
      userUpdates[key] = value;
    }
  }

  // When USER_NAME changes, also update agent.json user_name and record observation
  if ('USER_NAME' in userUpdates) {
    const newName = String(userUpdates.USER_NAME);
    agentUpdates['user_name'] = newName;
    if (previousUserName && previousUserName !== newName) {
      try {
        writeObservation(
          `[system] The user changed their name from "${previousUserName}" to "${newName}". ` +
          `Address them as ${newName} going forward.`,
        );
      } catch { /* non-critical */ }
    }
  }

  if (Object.keys(userUpdates).length > 0) {
    saveUserConfig(userUpdates);
  }
  if (Object.keys(agentUpdates).length > 0) {
    saveAgentConfig(c.AGENT_NAME, agentUpdates);
  }
});
```

**Purpose:** Apply updates AND persist to disk.

**Routing logic:**
- Agent keys → `saveAgentConfig()` → `~/.atrophy/agents/<name>/data/agent.json`
- User keys → `saveUserConfig()` → `~/.atrophy/config.json`

**Special handling for USER_NAME:**
1. Also updates `user_name` in agent.json (keeps them in sync)
2. Writes an observation about the name change for agent awareness

**Observation format:**
```
[system] The user changed their name from "OldName" to "NewName". Address them as NewName going forward.
```

## Security Considerations

### Key Allowlisting

Only keys in `safeKeys` (union of `agentKeys` and `userKeys`) can be modified. This prevents:
- Arbitrary config manipulation
- Security-sensitive path changes
- Binary location changes

### Secret Masking

API keys are masked before sending to renderer:
```typescript
elevenlabsApiKey: c.ELEVENLABS_API_KEY ? '***' : ''
```

The renderer never sees actual secret values, only whether they're set.

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/config.json` | config:get (via getConfig()) |
| Read | `~/.atrophy/agents/<name>/data/agent.json` | config:get (via getConfig()) |
| Write | `~/.atrophy/config.json` | config:update (user keys) |
| Write | `~/.atrophy/agents/<name>/data/agent.json` | config:update (agent keys) |
| Write | `~/.atrophy/agents/<name>/data/memory.db` | config:update (USER_NAME change observation) |

## Exported API

| Function | Purpose |
|----------|---------|
| `registerConfigHandlers(ctx)` | Register all config IPC handlers |

## See Also

- `src/main/config.ts` - Configuration system implementation
- `src/main/memory.ts` - writeObservation for name changes
- `src/renderer/components/Settings.svelte` - Primary consumer of config IPC

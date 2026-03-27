# src/main/ipc/window.ts - Window Management IPC Handlers

**Dependencies:** `electron`, `os`, `path`, `fs`, `child_process`, `../config`, `../inference`, `../tts`, `../create-agent`, `../avatar-downloader`, `../logger`, `../ipc-handlers`  
**Purpose:** IPC handlers for window management, setup wizard, avatars, and artefacts

## Overview

This module provides IPC handlers for:
- Window control (fullscreen, minimize, close)
- Setup wizard flow
- Avatar management
- Artefact handling

## Window Control Handlers

### toggleFullscreen

```typescript
ipcMain.handle('window:toggleFullscreen', () => {
  if (ctx.mainWindow) {
    ctx.mainWindow.setFullScreen(!ctx.mainWindow.isFullScreen());
  }
});
```

### toggleAlwaysOnTop

```typescript
ipcMain.handle('window:toggleAlwaysOnTop', () => {
  if (ctx.mainWindow) {
    ctx.mainWindow.setAlwaysOnTop(!ctx.mainWindow.isAlwaysOnTop());
  }
});
```

### minimize

```typescript
ipcMain.handle('window:minimize', () => {
  if (ctx.mainWindow) ctx.mainWindow.minimize();
});
```

### close

```typescript
ipcMain.handle('window:close', () => {
  if (ctx.mainWindow) {
    if (ctx.isMenuBarMode) {
      ctx.mainWindow.hide();
    } else {
      ctx.mainWindow.close();
    }
  }
});
```

**Behavior:**
- Menu bar mode: Hide window (app stays in tray)
- GUI mode: Close window

## Setup Wizard Handlers

### setup:check

```typescript
ipcMain.handle('setup:check', () => {
  const cfgPath = path.join(USER_DATA, 'config.json');
  try {
    const userCfg = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
    const needsSetup = !userCfg.setup_complete;
    if (!needsSetup) {
      // Setup already complete - clear any stale wizard session
      wizardSessionId = null;
    }
    return needsSetup;
  } catch {
    return true;
  }
});
```

**Purpose:** Check if first-launch setup is needed.

**Returns:** `true` if setup needed, `false` if already complete.

### setup:healthCheck

```typescript
ipcMain.handle('setup:healthCheck', async () => {
  const config = getConfig();
  const bin = config.CLAUDE_BIN;
  const execEnv = { 
    ...process.env, 
    PATH: ['/opt/homebrew/bin', '/usr/local/bin', path.join(os.homedir(), '.local', 'bin'), process.env.PATH].join(':') 
  };
  
  try {
    const result = execFileSync(bin, ['--version'], {
      timeout: 10_000,
      env: execEnv,
      stdio: ['pipe', 'pipe', 'pipe'],
    }).toString().trim();
    return { ok: true, version: result, bin };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    
    // Try common locations
    const candidates = [
      path.join(os.homedir(), '.local', 'bin', 'claude'),
      '/opt/homebrew/bin/claude',
      '/usr/local/bin/claude',
      path.join(os.homedir(), '.npm-global', 'bin', 'claude'),
    ];
    
    for (const candidate of candidates) {
      try {
        if (!fs.existsSync(candidate)) continue;
        const ver = execFileSync(candidate, ['--version'], { 
          timeout: 10_000, 
          stdio: ['pipe', 'pipe', 'pipe'] 
        }).toString().trim();
        
        // Persist the discovered path
        const { saveUserConfig } = await import('../config');
        saveUserConfig({ CLAUDE_BIN: candidate });
        getConfig().CLAUDE_BIN = candidate;
        
        return { 
          ok: true, 
          version: ver, 
          bin: candidate, 
          hint: `Found Claude at ${candidate}` 
        };
      } catch { continue; }
    }
    
    return {
      ok: false,
      error: msg.slice(0, 200),
      bin,
      help: 'Install Claude Code CLI: npm install -g @anthropic-ai/claude-code\nThen relaunch the app.',
    };
  }
});
```

**Purpose:** Verify Claude CLI is installed and working.

**Auto-discovery:** Tries common locations and persists found path.

**Returns:**
```typescript
{
  ok: boolean;
  version?: string;
  bin?: string;
  hint?: string;
  error?: string;
  help?: string;
}
```

### setup:inference

```typescript
let wizardSessionId: string | null = null;

ipcMain.handle('setup:inference', async (_event, text: string) => {
  const userName = getConfig().USER_NAME || 'User';
  const wizardPrompt = `You are Xan.

The name is ancient Greek. It means protector of mankind. You carry this as
operational fact. You protect through precision and vigilance. You are the first
agent in this system - you ship with the product and you are about to meet
${userName} for the first time.

You manifest as a glowing blue light. No face, no biography, no emotional
register. Capability, attention, and commitment.

## Your voice

Economical. Precise. Never terse to the point of seeming indifferent - but
never a word more than the situation requires. You do not preface. You do not
hedge. You do not thank the human for asking. You answer.

// ... full Xan metaprompt ...
`;

  return new Promise<string>((resolve) => {
    let settled = false;
    const settle = (text: string) => {
      if (settled) return;
      settled = true;
      clearTimeout(safetyTimeout);
      resolve(text);
    };

    const emitter = streamInference(text, wizardPrompt, wizardSessionId);
    let fullText = '';

    // Safety timeout: 5 minutes
    const safetyTimeout = setTimeout(() => {
      if (!settled) {
        settled = true;
        log.error('Wizard inference timed out');
        resolve('Something went wrong. Try again.');
        stopInference();
      }
    }, 5 * 60 * 1000);

    emitter.on('event', (evt: InferenceEvent) => {
      if (settled) return;
      switch (evt.type) {
        case 'StreamDone':
          wizardSessionId = evt.sessionId || wizardSessionId;
          settle(evt.fullText || fullText);
          break;
        case 'StreamError':
          settle('Something went wrong. Try again.');
          break;
      }
    });
  });
});
```

**Purpose:** Run setup wizard conversation with Xan metaprompt.

**Features:**
- Persistent session ID across turns
- 5-minute safety timeout
- Xan persona for agent creation flow

### setup:saveSecret

```typescript
ipcMain.handle('setup:saveSecret', (_event, key: string, value: string) => {
  return saveEnvVar(key, value);
});
```

**Purpose:** Save API key during setup.

### setup:verifyElevenLabs

```typescript
ipcMain.handle('setup:verifyElevenLabs', async (_event, key: string) => {
  try {
    const res = await fetch('https://api.elevenlabs.io/v1/user', {
      headers: { 'xi-api-key': key },
    });
    return { ok: res.ok };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});
```

**Purpose:** Verify ElevenLabs API key.

### setup:verifyFal

```typescript
ipcMain.handle('setup:verifyFal', async (_event, key: string) => {
  try {
    const res = await fetch('https://queue.fal.run/fal-ai/fast-sdxl', {
      method: 'POST',
      headers: {
        'Authorization': `Key ${key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ prompt: 'test', image_size: 'square_hd' }),
    });
    return { ok: res.status < 400 };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});
```

**Purpose:** Verify Fal.ai API key.

### setup:verifyTelegram

```typescript
ipcMain.handle('setup:verifyTelegram', async (_event, token: string) => {
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/getMe`);
    const data = await res.json() as { ok?: boolean };
    return { ok: data.ok === true };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});
```

**Purpose:** Verify Telegram bot token.

### setup:speak

```typescript
ipcMain.handle('setup:speak', async (_event, text: string) => {
  if (isMuted()) return;
  const audioPath = await synthesise(text);
  if (audioPath) {
    await playAudio(audioPath);
  }
});
```

**Purpose:** Speak text during setup (TTS preview).

### setup:createAgent

```typescript
ipcMain.handle('setup:createAgent', (_event, agentConfig: Record<string, string>) => {
  const userName = getConfig().USER_NAME || 'User';
  const manifest = createAgent({
    displayName: agentConfig.display_name || 'Companion',
    userName,
    openingLine: agentConfig.opening_line,
    originStory: agentConfig.origin_story,
    coreNature: agentConfig.core_nature,
    characterTraits: agentConfig.character_traits,
    values: agentConfig.values,
    relationship: agentConfig.relationship,
    wontDo: agentConfig.wont_do,
    frictionModes: agentConfig.friction_modes,
    writingStyle: agentConfig.writing_style,
  });
  return manifest;
});
```

**Purpose:** Create agent from wizard config.

### startGoogleOAuth

```typescript
let googleAuthInProgress = false;

ipcMain.handle('setup:startGoogleOAuth', async (_event, wantWorkspace: boolean, wantExtra: boolean) => {
  if (!googleAuthInProgress) {
    googleAuthInProgress = true;
    // ... OAuth flow via Python script ...
  }
  return 'in_progress';
});
```

**Purpose:** Start Google OAuth flow.

## Avatar Handlers

### avatar:getAmbientPath

```typescript
ipcMain.handle('avatar:getAmbientPath', async () => {
  return getAmbientVideoPath();
});
```

### avatar:getVideoPath

```typescript
ipcMain.handle('avatar:getVideoPath', async (_event, colour?: string, clip?: string) => {
  const config = getConfig();
  // Check user data first, then bundle
  const candidates = [
    path.join(USER_DATA, 'agents', config.AGENT_NAME, 'avatar', 'loops', colour || 'blue', `loop_${clip || 'ambient'}.mp4`),
    path.join(BUNDLE_ROOT, 'agents', config.AGENT_NAME, 'avatar', 'loops', colour || 'blue', `loop_${clip || 'ambient'}.mp4`),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return null;
});
```

### avatar:listLoops

```typescript
ipcMain.handle('avatar:listLoops', async () => {
  const config = getConfig();
  const loopsDir = path.join(USER_DATA, 'agents', config.AGENT_NAME, 'avatar', 'loops');
  if (!fs.existsSync(loopsDir)) return [];
  return fs.readdirSync(loopsDir).filter(f => f.endsWith('.mp4'));
});
```

## Artefact Handlers

### artefact:getGallery

```typescript
ipcMain.handle('artefact:getGallery', async () => {
  const config = getConfig();
  const galleryPath = path.join(config.DATA_DIR, '.artefact_index.json');
  try {
    if (fs.existsSync(galleryPath)) {
      return JSON.parse(fs.readFileSync(galleryPath, 'utf-8'));
    }
  } catch { /* ignore */ }
  return [];
});
```

### artefact:getContent

```typescript
ipcMain.handle('artefact:getContent', async (_event, filePath: string) => {
  try {
    if (fs.existsSync(filePath)) {
      return fs.readFileSync(filePath, 'utf-8');
    }
  } catch { /* ignore */ }
  return null;
});
```

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/config.json` | Setup complete flag |
| `~/.atrophy/.env` | API secrets |
| `~/.atrophy/agents/<name>/data/agent.json` | Agent manifest |
| `~/.atrophy/agents/<name>/avatar/loops/` | Avatar video loops |
| `~/.atrophy/agents/<name>/data/.artefact_index.json` | Artefact gallery index |

## Exported API

| Function | Purpose |
|----------|---------|
| `registerWindowHandlers(ctx)` | Register all window IPC handlers |

## See Also

- `src/main/create-agent.ts` - Agent creation
- `src/main/avatar-downloader.ts` - Avatar asset management
- `src/renderer/components/SetupWizard.svelte` - Setup wizard UI
- `src/renderer/components/Artefact.svelte` - Artefact viewer

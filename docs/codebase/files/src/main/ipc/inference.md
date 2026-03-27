# src/main/ipc/inference.ts - Inference IPC Handlers

**Dependencies:** `electron`, `fs`, `../config`, `../inference`, `../context`, `../session`, `../status`, `../agency`, `../tts`, `../artifact-parser`, `../opening`, `../logger`, `../channels/switchboard`, `../ipc-handlers`  
**Purpose:** IPC handlers for inference, status management, and opening lines

## Overview

This module provides the renderer with controls for:
- Sending messages to the agent (inference:send)
- Stopping inference (inference:stop)
- Getting/setting user status (status:get, status:set)
- Getting opening lines (opening:get)

It also registers the desktop GUI handler with the switchboard for cross-agent message delivery.

## Desktop Handler Registration

```typescript
// Register desktop GUI handler with the switchboard for all discovered agents
{
  const desktopHandler = async (envelope: Envelope) => {
    if (!ctx.mainWindow) return;
    ctx.mainWindow.webContents.send('inference:done', envelope.text);
  };
  const { discoverAgents } = require('../agent-manager');
  for (const agent of discoverAgents()) {
    switchboard.register(`desktop:${agent.name}`, desktopHandler);
  }
  // Re-register function for agent switches / new agent creation
  ctx.registerDesktopHandler = (agentName: string) => {
    switchboard.register(`desktop:${agentName}`, desktopHandler);
  };
}
```

**Purpose:** Register `desktop:<agent>` addresses so cross-agent messages display in the GUI regardless of which agent is currently active.

**Why inline handling:** Desktop inference has deeply integrated streaming display (TTS, artifacts, session management) that cannot be decoupled from the switchboard's handler delivery without breaking the user experience.

## IPC Handlers

### inference:send

```typescript
ipcMain.handle('inference:send', (_event, text: string) => {
  if (!ctx.mainWindow) {
    log.warn('inference:send called but mainWindow is null');
    return;
  }

  // Mark user active and reset journal nudge timer
  setActive();
  ctx.resetJournalNudgeTimer();

  try {
    // Ensure session exists
    if (!ctx.currentSession) {
      ctx.currentSession = new Session();
      ctx.currentSession.start();
      ctx.currentSession.inheritCliSessionId();
    }

    // Load system prompt once per session
    if (!ctx.systemPrompt) {
      ctx.systemPrompt = loadSystemPrompt();
    }

    // Record user turn
    ctx.currentSession.addTurn('will', text);

    // Detect mood shift
    if (detectMoodShift(text)) {
      ctx.currentSession.updateMood('heavy');
    }

    // Detect away intent
    const awayIntent = detectAwayIntent(text);
    if (awayIntent) {
      setAway(awayIntent);
      ctx.updateTrayState('away');
      ctx.mainWindow.webContents.send('status:changed', 'away');
      log.info(`Away intent detected: "${awayIntent}"`);
    }

    // Record message through switchboard for logging
    const agentName = ctx.currentAgentName || getConfig().AGENT_NAME;
    switchboard.record(switchboard.createEnvelope(
      `desktop:${agentName}`,
      `agent:${agentName}`,
      text,
      {
        type: 'user',
        priority: 'normal',
        replyTo: `desktop:${agentName}`,
        metadata: { source: 'desktop-gui' },
      },
    ));

    // Stream inference
    const emitter = streamInference(
      text,
      ctx.systemPrompt,
      ctx.currentSession.cliSessionId,
    );

    let fullText = '';

    emitter.on('event', (evt: InferenceEvent) => {
      if (!ctx.mainWindow) return;

      switch (evt.type) {
        case 'TextDelta':
          ctx.mainWindow.webContents.send('inference:textDelta', evt.text);
          break;

        case 'SentenceReady': {
          const ttsActive = getConfig().TTS_BACKEND !== 'off' && !isMuted();
          // Tell renderer about sentence boundary + whether to wait for audio
          ctx.mainWindow.webContents.send(
            'inference:sentenceReady', 
            evt.sentence, 
            evt.index, 
            ttsActive
          );
          if (ttsActive) {
            // Capture TTS generation to discard results after agent switch
            const gen = ttsGeneration();
            synthesise(evt.sentence).then((audioPath) => {
              if (audioPath && gen === ttsGeneration()) {
                enqueueAudio(audioPath, evt.index);
              } else if (audioPath) {
                // Stale - agent switched during synthesis; clean up temp file
                try { fs.unlinkSync(audioPath); } catch { /* best-effort */ }
              }
            }).catch((e) => { log.warn(`[tts] synthesise error: ${e}`); });
          }
          break;
        }

        case 'ToolUse':
          ctx.mainWindow.webContents.send('inference:toolUse', evt.name);
          break;

        case 'Compacting':
          ctx.mainWindow.webContents.send('inference:compacting');
          break;

        case 'StreamDone':
          fullText = evt.fullText;
          // Store CLI session ID
          if (ctx.currentSession && !ctx.currentSession.cliSessionId) {
            ctx.currentSession.setCliSessionId(evt.sessionId);
          } else if (ctx.currentSession && evt.sessionId !== ctx.currentSession.cliSessionId) {
            ctx.currentSession.setCliSessionId(evt.sessionId);
          }
          // Record agent turn
          if (ctx.currentSession && fullText) {
            ctx.currentSession.addTurn('agent', fullText);
          }

          // Parse inline artifacts
          const { text: cleanedText, artifacts } = parseArtifacts(fullText);
          if (artifacts.length > 0) {
            for (const art of artifacts) {
              ctx.mainWindow.webContents.send('inference:artifact', art);
            }
            // Send cleaned text with artifact placeholders
            ctx.mainWindow.webContents.send('inference:done', cleanedText);
          } else {
            ctx.mainWindow.webContents.send('inference:done', fullText);
          }

          // Cache opening for next boot if we don't have one yet
          if (ctx.systemPrompt) {
            const cachePath = getConfig().OPENING_CACHE_FILE;
            if (cachePath && !fs.existsSync(cachePath)) {
              cacheNextOpening(ctx.systemPrompt, ctx.currentSession?.cliSessionId ?? undefined);
            }
          }

          // Prefetch context for next message during idle
          setImmediate(() => prefetchContext());
          break;

        case 'StreamError':
          ctx.mainWindow.webContents.send('inference:error', evt.message);
          break;
      }
    });
  } catch (err) {
    log.error('[inference:send] failed to start inference:', err);
    ctx.mainWindow.webContents.send(
      'inference:error', 
      `Inference failed: ${err instanceof Error ? err.message : String(err)}`
    );
  }
});
```

**Flow:**
1. **Validate mainWindow:** Return early if window is null
2. **Mark user active:** Reset journal nudge timer
3. **Ensure session:** Create new session if needed, inherit CLI session ID
4. **Load system prompt:** Once per session
5. **Record user turn:** Add to session history
6. **Detect mood shift:** Update session mood if detected
7. **Detect away intent:** Set away status if user says "goodnight", etc.
8. **Record through switchboard:** For logging/observability
9. **Stream inference:** Spawn Claude CLI subprocess
10. **Handle events:**
    - `TextDelta`: Forward to renderer
    - `SentenceReady`: Send sentence + synthesize TTS
    - `ToolUse`: Notify renderer
    - `Compacting`: Notify renderer
    - `StreamDone`: Record turn, parse artifacts, prefetch context
    - `StreamError`: Forward error

**TTS generation check:**
```typescript
const gen = ttsGeneration();
synthesise(evt.sentence).then((audioPath) => {
  if (audioPath && gen === ttsGeneration()) {
    enqueueAudio(audioPath, evt.index);
  } else if (audioPath) {
    // Stale - agent switched during synthesis
    try { fs.unlinkSync(audioPath); } catch { /* best-effort */ }
  }
});
```

**Purpose:** Discard TTS results if agent switched during synthesis.

### inference:stop

```typescript
ipcMain.handle('inference:stop', () => {
  stopInference();
});
```

**Purpose:** Kill active Claude CLI subprocess.

### status:get

```typescript
ipcMain.handle('status:get', () => {
  return getStatus();
});
```

**Returns:** `{ status: 'active' | 'away'; reason: string; since: string; returned_from?: string; away_since?: string }`

### status:set

```typescript
ipcMain.handle('status:set', (_event, status: 'active' | 'away', reason?: string) => {
  if (status === 'active') {
    setActive();
    ctx.updateTrayState('active');
  } else {
    setAway(reason || 'manual');
    ctx.updateTrayState('away');
  }
  ctx.mainWindow?.webContents.send('status:changed', status);
});
```

**Purpose:** Manually set user status (active/away).

### opening:get

```typescript
ipcMain.handle('opening:get', async () => {
  const shouldSpeak = getConfig().TTS_BACKEND !== 'off' && !isMuted();

  // 1. Try cached opening (instant if available and time bracket matches)
  const cached = loadCachedOpening();
  if (cached) {
    log.info('[opening] Using cached opening');
    if (shouldSpeak && cached.audioPath) {
      playAudio(cached.audioPath).catch(() => { /* non-fatal */ });
    } else if (shouldSpeak) {
      synthesise(cached.text).then((p) => { 
        if (p) playAudio(p).catch(() => {}); 
      }).catch(() => {});
    }
    // Pre-generate next opening in background
    if (!ctx.systemPrompt) ctx.systemPrompt = loadSystemPrompt();
    if (ctx.systemPrompt) {
      cacheNextOpening(ctx.systemPrompt, ctx.currentSession?.cliSessionId ?? undefined);
    }
    return cached.text;
  }

  // 2. Ensure system prompt is loaded
  if (!ctx.systemPrompt) {
    ctx.systemPrompt = loadSystemPrompt();
  }

  // 3. Generate dynamically
  if (ctx.systemPrompt) {
    try {
      const result = await generateOpening(
        ctx.systemPrompt,
        ctx.currentSession?.cliSessionId ?? undefined,
      );
      // Cache next opening in background
      cacheNextOpening(ctx.systemPrompt, ctx.currentSession?.cliSessionId ?? undefined);
      // Speak it
      if (shouldSpeak) {
        synthesise(result.text).then((p) => { 
          if (p) playAudio(p).catch(() => {}); 
        }).catch(() => {});
      }
      return result.text;
    } catch (err) {
      log.error('[opening] Generation failed:', err);
    }
  }

  // 4. Fall back to static line
  const fallback = getStaticFallback();
  log.info(`[opening] Using static fallback: "${fallback}"`);
  if (shouldSpeak) {
    synthesise(fallback).then((p) => { 
      if (p) playAudio(p).catch(() => {}); 
    }).catch(() => {});
  }
  return fallback;
});
```

**Opening line resolution:**
1. **Cached:** Try cached opening (instant, pre-synthesized audio if available)
2. **Dynamic:** Generate via inference if system prompt available
3. **Static fallback:** Varied static lines if generation fails

**Background caching:** After returning an opening, pre-generate next one in background for faster next launch.

## Event Forwarding

The handler forwards these events from inference to renderer:

| Event | Channel | Payload |
|-------|---------|---------|
| `TextDelta` | `inference:textDelta` | `text: string` |
| `SentenceReady` | `inference:sentenceReady` | `sentence: string, index: number, ttsActive: boolean` |
| `ToolUse` | `inference:toolUse` | `name: string` |
| `Compacting` | `inference:compacting` | `{}` |
| `StreamDone` | `inference:done` | `text: string` (with artifact placeholders) |
| `StreamError` | `inference:error` | `message: string` |
| `Artifact` | `inference:artifact` | `{ id, type, title, language, content }` |

## Session Management

**Session lifecycle:**
1. Created on first `inference:send` if not exists
2. CLI session ID inherited from last session
3. System prompt loaded once per session
4. CLI session ID updated after each inference
5. User and agent turns recorded

**Context prefetch:**
```typescript
setImmediate(() => prefetchContext());
```

Called after each inference completes to reduce latency for next message.

## Artifact Parsing

```typescript
const { text: cleanedText, artifacts } = parseArtifacts(fullText);
if (artifacts.length > 0) {
  for (const art of artifacts) {
    ctx.mainWindow.webContents.send('inference:artifact', art);
  }
  ctx.mainWindow.webContents.send('inference:done', cleanedText);
} else {
  ctx.mainWindow.webContents.send('inference:done', fullText);
}
```

**Purpose:** Extract inline artifacts (`<artifact>...</artifact>` blocks) from response and send separately to renderer for display.

## File I/O

| Operation | Path | When |
|-----------|------|------|
| Read | `~/.atrophy/agents/<name>/data/.opening_cache.json` | opening:get (loadCachedOpening) |
| Write | `~/.atrophy/agents/<name>/data/.opening_cache.json` | opening:get (cacheNextOpening) |
| Read/Write | `~/.atrophy/agents/<name>/data/memory.db` | Session turns |
| Read/Write | `/tmp/atrophy-tts-*.mp3` | TTS synthesis |

## Exported API

| Function | Purpose |
|----------|---------|
| `registerInferenceHandlers(ctx)` | Register all inference IPC handlers |

## See Also

- `src/main/inference.ts` - Claude CLI streaming
- `src/main/context.ts` - System prompt loading
- `src/main/session.ts` - Session management
- `src/main/tts.ts` - TTS synthesis and playback
- `src/main/artifact-parser.ts` - Inline artifact extraction
- `src/main/opening.ts` - Opening line generation and caching
- `src/main/agency.ts` - Mood shift and away intent detection

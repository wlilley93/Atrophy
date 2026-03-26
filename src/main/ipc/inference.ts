/**
 * IPC handlers for inference, status, and opening lines.
 * Channels: inference:send, inference:stop, status:get, status:set, opening:get
 */

import { ipcMain } from 'electron';
import * as fs from 'fs';
import { getConfig } from '../config';
import { streamInference, stopInference, prefetchContext, type InferenceEvent } from '../inference';
import { loadSystemPrompt } from '../context';
import { Session } from '../session';
import { setActive, setAway, getStatus, detectAwayIntent } from '../status';
import { detectMoodShift } from '../agency';
import { synthesise, enqueueAudio, playAudio, isMuted, ttsGeneration } from '../tts';
import { parseArtifacts } from '../artifact-parser';
import { loadCachedOpening, generateOpening, cacheNextOpening, getStaticFallback } from '../opening';
import { createLogger } from '../logger';
import { switchboard, type Envelope } from '../channels/switchboard';
import { discoverAgents } from '../agent-manager';
import type { IpcContext } from '../ipc-handlers';

const log = createLogger('ipc:inference');

export function registerInferenceHandlers(ctx: IpcContext): void {
  // Register desktop GUI handler with the switchboard for all discovered agents.
  // Each agent needs a desktop:<name> address so cross-agent messages display
  // regardless of which agent is currently active.
  {
    const desktopHandler = async (envelope: Envelope) => {
      if (!ctx.mainWindow) return;
      ctx.mainWindow.webContents.send('inference:done', envelope.text);
    };
    // discoverAgents imported statically at top (dynamic require breaks Vite bundling)
    for (const agent of discoverAgents()) {
      switchboard.register(`desktop:${agent.name}`, desktopHandler);
    }
    // Also expose a re-register function for agent switches / new agent creation
    ctx.registerDesktopHandler = (agentName: string) => {
      switchboard.register(`desktop:${agentName}`, desktopHandler);
    };
  }

  let _inferring = false;

  ipcMain.handle('inference:send', (_event, text: string) => {
    if (!ctx.mainWindow) {
      log.warn('inference:send called but mainWindow is null');
      return;
    }
    if (_inferring) {
      log.warn('inference:send called while already inferring - ignoring');
      return;
    }
    _inferring = true;

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

      // Detect away intent (e.g. "goodnight", "heading out")
      const awayIntent = detectAwayIntent(text);
      if (awayIntent) {
        setAway(awayIntent);
        ctx.updateTrayState('away');
        ctx.mainWindow.webContents.send('status:changed', 'away');
        log.info(`Away intent detected: "${awayIntent}"`);
      }

      // Record the message through the switchboard for logging/observability.
      // Desktop inference is handled inline below (not routed through the
      // switchboard's handler delivery) because the GUI has deeply integrated
      // streaming display (TTS, artifacts, session management) that cannot
      // be decoupled without breaking the user experience.
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

      // Stream inference (existing logic - unchanged)
      const emitter = streamInference(
        text,
        ctx.systemPrompt,
        ctx.currentSession.cliSessionId,
      );

      let fullText = '';

      emitter.on('event', (evt: InferenceEvent) => {
        if (!ctx.mainWindow || ctx.mainWindow.isDestroyed()) return;

        switch (evt.type) {
          case 'TextDelta':
            ctx.mainWindow.webContents.send('inference:textDelta', evt.text);
            break;

          case 'SentenceReady': {
            const ttsActive = getConfig().TTS_BACKEND !== 'off' && !isMuted();
            // Tell renderer about the sentence boundary + whether to wait for audio
            ctx.mainWindow.webContents.send('inference:sentenceReady', evt.sentence, evt.index, ttsActive);
            if (ttsActive) {
              // Capture TTS generation so we can discard results after an agent switch
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

          case 'ThinkingDelta':
            ctx.mainWindow.webContents.send('inference:thinkingDelta', evt.text);
            break;

          case 'ToolUse':
            ctx.mainWindow.webContents.send('inference:toolUse', evt.name, evt.toolId);
            break;

          case 'ToolResult':
            ctx.mainWindow.webContents.send('inference:toolResult', evt.toolId, evt.toolName, evt.output?.slice(0, 500));
            break;

          case 'Compacting':
            ctx.mainWindow.webContents.send('inference:compacting');
            break;

          case 'StreamDone':
            _inferring = false;
            fullText = evt.fullText;
            // Store CLI session ID after first inference
            if (ctx.currentSession && !ctx.currentSession.cliSessionId) {
              ctx.currentSession.setCliSessionId(evt.sessionId);
            } else if (ctx.currentSession && evt.sessionId !== ctx.currentSession.cliSessionId) {
              ctx.currentSession.setCliSessionId(evt.sessionId);
            }
            // Record agent turn (full text including artifact blocks for history)
            if (ctx.currentSession && fullText) {
              ctx.currentSession.addTurn('agent', fullText);
            }

            // Parse inline artifacts from response
            const { text: cleanedText, artifacts } = parseArtifacts(fullText);
            if (!ctx.mainWindow.isDestroyed()) {
              if (artifacts.length > 0) {
                for (const art of artifacts) {
                  ctx.mainWindow.webContents.send('inference:artifact', art);
                }
                // Send cleaned text (artifact blocks replaced with placeholders)
                ctx.mainWindow.webContents.send('inference:done', cleanedText);
              } else {
                ctx.mainWindow.webContents.send('inference:done', fullText);
              }
            }
            // Cache an opening for next boot if we don't have one yet
            // (proves the CLI is working, so dynamic generation will succeed)
            if (ctx.systemPrompt) {
              const cachePath = getConfig().OPENING_CACHE_FILE;
              if (cachePath && !fs.existsSync(cachePath)) {
                cacheNextOpening(ctx.systemPrompt, ctx.currentSession?.cliSessionId ?? undefined);
              }
            }
            // Prefetch context for the next message during idle
            setImmediate(() => prefetchContext());
            break;

          case 'StreamError':
            _inferring = false;
            if (!ctx.mainWindow.isDestroyed()) {
              ctx.mainWindow.webContents.send('inference:error', evt.message);
            }
            break;
        }
      });
    } catch (err) {
      _inferring = false;
      log.error('[inference:send] failed to start inference:', err);
      ctx.mainWindow?.webContents.send('inference:error', `Inference failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  });

  ipcMain.handle('inference:stop', () => {
    stopInference();
  });

  // -- Status --

  ipcMain.handle('status:get', () => {
    return getStatus();
  });

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

  // -- Opening line --

  ipcMain.handle('opening:get', async () => {
    const shouldSpeak = getConfig().TTS_BACKEND !== 'off' && !isMuted();

    // 1. Try cached opening (instant if available and time bracket matches)
    const cached = loadCachedOpening();
    if (cached) {
      log.info('[opening] Using cached opening');
      // Play pre-synthesised audio if available
      if (shouldSpeak && cached.audioPath) {
        playAudio(cached.audioPath).catch(() => { /* non-fatal */ });
      } else if (shouldSpeak) {
        // Synthesise on the fly
        synthesise(cached.text).then((p) => { if (p) playAudio(p).catch(() => {}); }).catch(() => {});
      }
      // Pre-generate next opening in background
      if (!ctx.systemPrompt) ctx.systemPrompt = loadSystemPrompt();
      if (ctx.systemPrompt) {
        cacheNextOpening(ctx.systemPrompt, ctx.currentSession?.cliSessionId ?? undefined);
      }
      return cached.text;
    }

    // 2. Ensure system prompt is loaded so we can generate dynamically
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
        // Cache next opening in background for next launch
        cacheNextOpening(ctx.systemPrompt, ctx.currentSession?.cliSessionId ?? undefined);
        // Speak it
        if (shouldSpeak) {
          synthesise(result.text).then((p) => { if (p) playAudio(p).catch(() => {}); }).catch(() => {});
        }
        return result.text;
      } catch (err) {
        log.error('[opening] Generation failed:', err);
      }
    } else {
      log.warn('[opening] System prompt not available, skipping dynamic generation');
    }

    // 4. Fall back to a varied static line (not just the agent name)
    const fallback = getStaticFallback();
    log.info(`[opening] Using static fallback: "${fallback}"`);
    if (shouldSpeak) {
      synthesise(fallback).then((p) => { if (p) playAudio(p).catch(() => {}); }).catch(() => {});
    }
    return fallback;
  });
}

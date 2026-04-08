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
import { loadState as loadEmotionalState } from '../inner-life';
import { createLogger } from '../logger';
import { switchboard, type Envelope } from '../channels/switchboard';
import { discoverAgents } from '../agent-manager';
import { fileEntities } from '../entity-extract';
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

      // Ensure config is loaded for the desktop agent before inference.
      // Concurrent telegram/cron dispatches can reload the singleton.
      if (getConfig().AGENT_NAME !== agentName) {
        getConfig().reloadForAgent(agentName);
      }

      // If we showed the user an opening line that this agent's CLI session
      // has not seen, prepend it to the user's first message as bracketed
      // prior context. Without this, Claude CLI sees a session with no
      // history and synthesises a "tell me more" continuation from
      // unrelated context, while the user is staring at a different
      // opening on screen. We keep the addTurn call above on the
      // unmodified `text` so memory.db reflects what the user typed.
      let inferenceText = text;
      const pendingOpening = _pendingOpening.get(agentName);
      if (pendingOpening) {
        inferenceText =
          `[Earlier in this session, you opened with: "${pendingOpening}"]\n\n` +
          text;
        _pendingOpening.delete(agentName);
        log.info(`[opening] Injected pending opening into first message for ${agentName}`);
      }

      const emitter = streamInference(
        inferenceText,
        ctx.systemPrompt,
        ctx.currentSession.cliSessionId,
        { source: 'desktop', processKey: `desktop:${agentName}` },
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

            // Auto-extract entities from response into intelligence.db
            // (no-op for agents without intelligence.db, e.g. xan/companion)
            if (fullText) {
              const agentName = ctx.currentAgentName || getConfig().AGENT_NAME;
              try { fileEntities(agentName, fullText); } catch { /* best effort */ }
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
            // Broadcast emotional state to renderer after each turn
            try {
              const es = loadEmotionalState();
              ctx.mainWindow.webContents.send('emotion:updated', {
                emotions: es.emotions,
                trust: es.trust,
              });
            } catch { /* non-fatal */ }
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

  // Persist the opening line as an `agent` turn in this session's memory.db
  // so the agent's own future context contains a record of having said it.
  // Without this, cached and pre-generated openings appear to the user but
  // never enter the conversation history, leaving the agent with a blind
  // spot when asked "what was your last message?". Idempotency is enforced
  // per session via _openingRecorded so callers can fire opening:get more
  // than once safely (e.g. soft reloads).
  //
  // Persistence to memory.db is necessary but not sufficient. The opening
  // is generated by a throwaway runInferenceOneshot call during pre-cache,
  // its text is saved to a file, and the generating CLI session is
  // discarded. The session that later handles the user's first message
  // (via streamInference) has never seen the opening - so when the user
  // says "tell me more", Claude CLI synthesises a continuation from
  // unrelated context. _pendingOpening fixes this by caching the most
  // recent opening per agent and prepending it to the user's next message
  // as bracketed prior context. Consumed on first inference:send.
  const _openingRecorded = new WeakSet<Session>();
  const _pendingOpening = new Map<string, string>();
  const recordOpening = (text: string): void => {
    try {
      if (!ctx.currentSession) {
        ctx.currentSession = new Session();
        ctx.currentSession.start();
        ctx.currentSession.inheritCliSessionId();
      }
      if (_openingRecorded.has(ctx.currentSession)) return;
      ctx.currentSession.addTurn('agent', text);
      _openingRecorded.add(ctx.currentSession);
      const agentName = ctx.currentAgentName || getConfig().AGENT_NAME;
      _pendingOpening.set(agentName, text);
    } catch (err) {
      log.warn('[opening] failed to persist opening turn:', err);
    }
  };

  ipcMain.handle('opening:get', async () => {
    const shouldSpeak = getConfig().TTS_BACKEND !== 'off' && !isMuted();

    // 1. Try cached opening (instant if available and time bracket matches)
    const cached = loadCachedOpening();
    if (cached) {
      log.info('[opening] Using cached opening');
      recordOpening(cached.text);
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
        recordOpening(result.text);
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
    recordOpening(fallback);
    if (shouldSpeak) {
      synthesise(fallback).then((p) => { if (p) playAudio(p).catch(() => {}); }).catch(() => {});
    }
    return fallback;
  });
}

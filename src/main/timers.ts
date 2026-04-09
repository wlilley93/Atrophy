/**
 * Timer management for the Electron main process.
 * Owns all interval timers, the journal nudge timeout, and the keep-awake blocker.
 * Each timer callback is a named method for readability and testability.
 */

import { powerSaveBlocker } from 'electron';
import * as fs from 'fs';
import * as path from 'path';
import type { AppContext } from './app-context';
import { getConfig } from './config';
import { runCoherenceCheck } from './sentinel';
import { drainAllAgentQueues } from './queue';
import { switchboard } from './channels/switchboard';
import {
  checkDeferralRequest,
  validateDeferralRequest,
  checkAskRequest,
  cleanupAskFiles,
  getAgentDir,
} from './agent-manager';
import { setActive, setAway, isAway, isMacIdle, IDLE_TIMEOUT_SECS } from './status';
import { loadSystemPrompt } from './context';
import { createLogger } from './logger';

const log = createLogger('timers');

export class TimerManager {
  private intervals: Map<string, ReturnType<typeof setInterval>> = new Map();
  private timeouts: Map<string, ReturnType<typeof setTimeout>> = new Map();

  // Keep-awake state
  private keepAwakeBlockerId: number | null = null;

  // Journal nudge state
  private journalNudgeSent = false;
  private lastUserInputTime = Date.now();

  // Canvas mtime tracking
  private canvasLastMtime = 0;

  // Constants
  private static readonly JOURNAL_NUDGE_DELAY_MS = 5 * 60 * 1000;
  private static readonly JOURNAL_NUDGE_PROBABILITY = 0.10;
  private static readonly SESSION_IDLE_THRESHOLD_MS = 30 * 60 * 1000;

  constructor(private ctx: AppContext) {}

  startAll(): void {
    cleanupAskFiles();

    this.intervals.set('sentinel', setInterval(() => this.pollSentinel(), 5 * 60 * 1000));
    this.intervals.set('queue', setInterval(() => this.pollQueue(), 10_000));
    this.intervals.set('mcpState', setInterval(() => this.writeMcpState(), 5_000));
    this.intervals.set('deferral', setInterval(() => this.pollDeferral(), 5_000));
    this.intervals.set('askUser', setInterval(() => this.pollAskUser(), 3_000));
    this.intervals.set('artefact', setInterval(() => this.pollArtefact(), 5_000));
    this.intervals.set('canvas', setInterval(() => this.pollCanvas(), 2_000));
    this.intervals.set('status', setInterval(() => this.pollStatus(), 60_000));
    this.intervals.set('sessionIdle', setInterval(() => this.pollSessionIdle(), 60_000));

    log.info(`started ${this.intervals.size} timers`);
  }

  stopAll(): void {
    for (const [, timer] of this.intervals) {
      clearInterval(timer);
    }
    this.intervals.clear();

    for (const [, timer] of this.timeouts) {
      clearTimeout(timer);
    }
    this.timeouts.clear();

    this.disableKeepAwake();
    log.info('all timers stopped');
  }

  resetJournalNudge(): void {
    this.lastUserInputTime = Date.now();
    const existing = this.timeouts.get('journalNudge');
    if (existing) clearTimeout(existing);
    if (this.journalNudgeSent) return;

    const timer = setTimeout(() => {
      if (this.journalNudgeSent) return;
      if (Math.random() > TimerManager.JOURNAL_NUDGE_PROBABILITY) return;
      this.journalNudgeSent = true;
      this.ctx.mainWindow?.webContents.send('journal:nudge');
    }, TimerManager.JOURNAL_NUDGE_DELAY_MS);

    this.timeouts.set('journalNudge', timer);
  }

  recordUserInput(): void {
    this.lastUserInputTime = Date.now();
  }

  isKeepAwakeActive(): boolean {
    return this.keepAwakeBlockerId !== null && powerSaveBlocker.isStarted(this.keepAwakeBlockerId);
  }

  enableKeepAwake(): void {
    if (this.isKeepAwakeActive()) return;
    this.keepAwakeBlockerId = powerSaveBlocker.start('prevent-display-sleep');
    log.info(`keep awake enabled (blocker id=${this.keepAwakeBlockerId})`);
    this.ctx.tray.rebuildMenu();
  }

  disableKeepAwake(): void {
    if (this.keepAwakeBlockerId !== null) {
      try { powerSaveBlocker.stop(this.keepAwakeBlockerId); } catch { /* already stopped */ }
      log.info(`keep awake disabled (blocker id=${this.keepAwakeBlockerId})`);
      this.keepAwakeBlockerId = null;
    }
  }

  toggleKeepAwake(): void {
    if (this.isKeepAwakeActive()) {
      this.disableKeepAwake();
    } else {
      this.enableKeepAwake();
    }
    this.ctx.tray.rebuildMenu();
  }

  private pollSentinel(): void {
    if (this.ctx.currentSession?.cliSessionId && this.ctx.systemPrompt) {
      runCoherenceCheck(this.ctx.currentSession.cliSessionId, this.ctx.systemPrompt).then((newId) => {
        if (newId && this.ctx.currentSession) {
          this.ctx.currentSession.setCliSessionId(newId);
        }
      }).catch((err) => { log.debug(`sentinel coherence check failed: ${err}`); });
    }
  }

  private pollQueue(): void {
    (async () => {
      const allMessages = await drainAllAgentQueues();
      for (const [, messages] of Object.entries(allMessages)) {
        for (const msg of messages) {
          this.ctx.mainWindow?.webContents.send('queue:message', msg);
        }
      }
    })().catch(err => log.error('queue poll error:', err));
  }

  private pollDeferral(): void {
    if (!this.ctx.mainWindow || !this.ctx.currentAgentName) return;
    const request = checkDeferralRequest();
    if (!request) return;

    if (!validateDeferralRequest(request.target, this.ctx.currentAgentName)) {
      return;
    }

    this.ctx.mainWindow.webContents.send('deferral:request', {
      target: request.target,
      context: request.context,
      user_question: request.user_question,
    });
  }

  private pollAskUser(): void {
    if (!this.ctx.mainWindow) return;
    if (this.ctx.pendingAskId) return;
    const request = checkAskRequest();
    if (!request) return;

    this.ctx.pendingAskId = request.request_id;
    this.ctx.pendingAskDestination = request.destination || null;
    this.ctx.pendingAskAgent = (request as any)._agent || null;
    this.ctx.mainWindow.webContents.send('ask:request', {
      question: request.question,
      action_type: request.action_type,
      request_id: request.request_id,
      input_type: request.input_type,
      label: request.label,
      destination: request.destination,
    });
  }

  private pollArtefact(): void {
    if (!this.ctx.mainWindow) return;
    const config = getConfig();
    const displayFile = config.ARTEFACT_DISPLAY_FILE;
    if (!displayFile || !fs.existsSync(displayFile)) return;

    try {
      const raw = fs.readFileSync(displayFile, 'utf-8');
      const data = JSON.parse(raw) as {
        status?: string;
        type?: string;
        name?: string;
        path?: string;
        file?: string;
      };

      if (data.status === 'generating') {
        this.ctx.mainWindow.webContents.send('artefact:loading', { name: data.name, type: data.type });
        return;
      }

      fs.unlinkSync(displayFile);

      const artefactType = data.type || 'html';
      let content = '';
      let src = '';

      if (data.file) {
        const c = getConfig();
        const artefactsBase = path.resolve(path.join(getAgentDir(c.AGENT_NAME), 'artefacts'));
        let resolvedFile: string;
        try {
          resolvedFile = fs.realpathSync(path.resolve(data.file));
        } catch {
          resolvedFile = '';
        }
        if (!resolvedFile || (!resolvedFile.startsWith(artefactsBase + path.sep) && resolvedFile !== artefactsBase)) {
          log.warn(`artefact watcher blocked path traversal: ${data.file}`);
          return;
        }

        if (artefactType === 'html') {
          try {
            content = fs.readFileSync(resolvedFile, 'utf-8');
          } catch { /* file missing */ }
        } else if (artefactType === 'image' || artefactType === 'video') {
          src = `file://${resolvedFile}`;
        }
      }

      this.ctx.mainWindow.webContents.send('artefact:updated', {
        type: artefactType,
        content,
        src,
        title: data.name || '',
      });
    } catch {
      try { fs.unlinkSync(displayFile); } catch { /* already gone */ }
    }
  }

  private pollCanvas(): void {
    if (!this.ctx.mainWindow) return;
    const config = getConfig();
    const canvasFile = config.CANVAS_CONTENT_FILE;
    if (!canvasFile || !fs.existsSync(canvasFile)) return;

    try {
      const stat = fs.statSync(canvasFile);
      const mtime = stat.mtimeMs;
      if (mtime <= this.canvasLastMtime) return;
      this.canvasLastMtime = mtime;

      const fileUrl = `file://${canvasFile}`;
      this.ctx.mainWindow.webContents.send('canvas:updated', fileUrl);
    } catch { /* file gone mid-read */ }
  }

  private pollStatus(): void {
    (async () => {
      const wasAway = isAway();
      if (await isMacIdle(IDLE_TIMEOUT_SECS)) {
        if (!wasAway) {
          setAway('idle');
          log.info('user idle - setting away');
          this.ctx.tray.updateState('away');
          this.ctx.mainWindow?.webContents.send('status:changed', 'away');
        }
      } else {
        if (wasAway) {
          setActive();
          log.info('user active - setting online');
          this.ctx.tray.updateState('active');
          this.ctx.mainWindow?.webContents.send('status:changed', 'active');
        }
      }
    })().catch(err => log.error('status poll error:', err));
  }

  private pollSessionIdle(): void {
    (async () => {
      if (!this.ctx.currentSession || this.ctx.currentSession.sessionId === null) return;
      if (this.ctx.currentSession.turnHistory.length === 0) return;

      const lastActivity = this.ctx.currentSession.lastActivityAt ?? this.lastUserInputTime;
      const gap = Date.now() - lastActivity;
      if (gap < TimerManager.SESSION_IDLE_THRESHOLD_MS) return;

      const oldSession = this.ctx.currentSession;
      const sys = this.ctx.systemPrompt || loadSystemPrompt();
      try {
        await oldSession.end(sys);
        log.info(`rotated idle session (gap: ${Math.round(gap / 60000)}m, turns: ${oldSession.turnHistory.length})`);
      } catch (e) {
        log.error(`failed to end idle session: ${e}`);
      }
      if (this.ctx.currentSession === oldSession) this.ctx.currentSession = null;
    })().catch(err => log.error('session idle rotation error:', err));
  }

  private writeMcpState(): void {
    switchboard.writeStateForMCP();
  }
}

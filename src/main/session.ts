/**
 * Session lifecycle management.
 * Port of core/session.py.
 */

import { getConfig } from './config';
import * as memory from './memory';
import { runInferenceOneshot } from './inference';
import { reconcileTrustFromDb } from './inner-life';

// ---------------------------------------------------------------------------
// Session class
// ---------------------------------------------------------------------------

export class Session {
  sessionId: number | null = null;
  startedAt: number | null = null;
  turnHistory: { role: string; content: string; turnId: number }[] = [];
  cliSessionId: string | null = null;
  mood: string | null = null;

  start(): number {
    this.sessionId = memory.startSession();
    this.startedAt = Date.now();
    this.turnHistory = [];
    reconcileTrustFromDb();

    // CLI session ID is NOT loaded here - callers must explicitly call
    // inheritCliSessionId() after ensuring the correct agent's DB is loaded.
    // This prevents cross-agent session contamination when memory.ts is a
    // singleton shared across agents.
    return this.sessionId;
  }

  /**
   * Inherit the most recent CLI session ID from the currently-loaded DB.
   * Call this after config.reloadForAgent() + memory.initDb() to ensure
   * the correct agent's DB is active.
   */
  inheritCliSessionId(): void {
    if (!this.cliSessionId) {
      this.cliSessionId = memory.getLastCliSessionId();
    }
  }

  setCliSessionId(cliId: string): void {
    this.cliSessionId = cliId;
    if (this.sessionId !== null) {
      memory.saveCliSessionId(this.sessionId, cliId);
    }
  }

  addTurn(role: 'will' | 'agent', content: string, topicTags?: string, weight = 1): number {
    if (this.sessionId === null) {
      throw new Error('Session not started');
    }
    const turnId = memory.writeTurn(this.sessionId, role, content, topicTags, weight);
    this.turnHistory.push({ role, content, turnId });
    return turnId;
  }

  updateMood(mood: string): void {
    this.mood = mood;
    if (this.sessionId !== null) {
      memory.updateSessionMood(this.sessionId, mood);
    }
  }

  minutesElapsed(): number {
    if (this.startedAt === null) return 0;
    return (Date.now() - this.startedAt) / 60000;
  }

  shouldSoftLimit(): boolean {
    const config = getConfig();
    return this.minutesElapsed() >= config.SESSION_SOFT_LIMIT_MINS;
  }

  async end(systemPrompt: string): Promise<void> {
    if (this.sessionId === null) return;

    if (!this.turnHistory.length || this.turnHistory.length < 4) {
      memory.endSession(this.sessionId);
      return;
    }

    const config = getConfig();
    const turnText = this.turnHistory
      .map((t) => {
        const label = t.role === 'will' ? config.USER_NAME : config.AGENT_DISPLAY_NAME;
        return `${label}: ${t.content}`;
      })
      .join('\n');

    const summaryPrompt =
      'Summarise this conversation in 2-3 sentences. ' +
      'Focus on what mattered, not what was said. ' +
      'Note any new threads, shifts in mood, or observations worth remembering.\n\n' +
      turnText;

    let summary: string;
    try {
      summary = await runInferenceOneshot(
        [{ role: 'user', content: summaryPrompt }],
        'You are summarising a conversation for memory storage. Be concise and precise.',
      );
    } catch (e) {
      summary = `[Summary generation failed: ${e}]`;
    }

    memory.endSession(this.sessionId, summary, this.mood);
    memory.writeSummary(this.sessionId, summary);
  }
}

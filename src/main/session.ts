/**
 * Session lifecycle management.
 * Port of core/session.py.
 */

import { getConfig } from './config';
import * as memory from './memory';
import { runInferenceOneshot } from './inference';
import { reconcileTrustFromDb, loadState, saveState, encodeEmotionalVector, vectorToBlob, type FullState } from './inner-life';
import { scoreSalience, detectDisclosures, mergeDisclosures, emptyDisclosureMap } from './inner-life-salience';

// ---------------------------------------------------------------------------
// Session class
// ---------------------------------------------------------------------------

export class Session {
  sessionId: number | null = null;
  startedAt: number | null = null;
  lastActivityAt: number | null = null;
  turnHistory: { role: string; content: string; turnId: number }[] = [];
  cliSessionId: string | null = null;
  mood: string | null = null;
  private _prevState: FullState | null = null;

  start(): number {
    this.sessionId = memory.startSession();
    this.startedAt = Date.now();
    this.lastActivityAt = Date.now();
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
    // Snapshot the current emotional state as a 32-dim vector so the
    // distributed emotional memory layer accumulates per-turn traces.
    let emotionalVector: Buffer | undefined;
    let currentState: FullState | undefined;
    try {
      currentState = loadState();
      emotionalVector = vectorToBlob(encodeEmotionalVector(currentState));
    } catch { /* non-fatal - write turn without vector */ }

    // Salience scoring - how much should this turn weigh in future aggregation?
    // High salience: emotional displacement, vulnerability, relational depth.
    // Low salience: routine task chat, one-liners.
    // scoreSalience returns 0.0-1.0, DB weight column is INTEGER 1-5.
    let dbWeight = weight;
    if (currentState) {
      try {
        const rawSalience = scoreSalience(content, role, this._prevState, currentState);
        this._prevState = currentState;
        // Map 0.0-1.0 to 1-5: floor(salience * 4) + 1, clamped
        dbWeight = Math.max(1, Math.min(5, Math.floor(rawSalience * 4) + 1));
      } catch { /* non-fatal */ }
    }

    // Disclosure mapping - track what topics have been shared and at what depth.
    // Only applies to user messages (the agent doesn't disclose).
    if (role === 'will' && currentState) {
      try {
        const detected = detectDisclosures(content);
        if (Object.keys(detected).length > 0) {
          const existing = currentState.disclosure || emptyDisclosureMap();
          const merged = mergeDisclosures(existing, detected);
          saveState({ ...currentState, disclosure: merged });
        }
      } catch { /* non-fatal */ }
    }

    const turnId = memory.writeTurn(this.sessionId, role, content, topicTags, dbWeight, 'direct', emotionalVector);
    this.turnHistory.push({ role, content, turnId });
    this.lastActivityAt = Date.now();
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

  async end(_systemPrompt: string): Promise<void> {
    if (this.sessionId === null) return;
    // Capture and null out immediately to prevent double-end from concurrent callers
    const sid = this.sessionId!;
    this.sessionId = null;

    // Pin the DB path before any async work - reloadForAgent() can swap
    // the config to a different agent's DB during summary inference.
    const dbPath = getConfig().DB_PATH;

    if (!this.turnHistory.length || this.turnHistory.length < 4) {
      memory.endSession(sid, null, null, false, dbPath);
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
      'Summarise this conversation in 2-4 sentences.\n\n' +
      'Capture what actually happened between these two people, not just the topic.\n' +
      'If something shifted - in the relationship, in understanding, in how they talk ' +
      'to each other - name it. If someone was vulnerable, direct, or honest in a way ' +
      'that cost something, that matters more than what was discussed.\n' +
      'A session about fixing bugs where nothing personal happened is just that. ' +
      'A session where something real passed between them - name the real thing.\n' +
      'Do not use em dashes - only hyphens.\n\n' +
      turnText;

    let summary: string;
    try {
      summary = await runInferenceOneshot(
        [{ role: 'user', content: summaryPrompt }],
        `You are ${config.AGENT_DISPLAY_NAME}, writing a memory of a conversation you just had with ${config.USER_NAME}. ` +
        'Write in third person. Be honest about what the session was. 2-4 sentences.',
      );
    } catch (e) {
      summary = `[Summary generation failed: ${e}]`;
    }

    memory.endSession(sid, summary, this.mood, false, dbPath);
    memory.writeSummary(sid, summary, undefined, dbPath);
  }
}

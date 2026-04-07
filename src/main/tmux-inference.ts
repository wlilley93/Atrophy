/**
 * Persistent Claude Code CLI sessions via tmux.
 *
 * Replaces spawn-per-message inference with persistent tmux windows.
 * One hidden tmux window per agent. Messages sent via `tmux send-keys`.
 * Responses read from Claude Code's JSONL session files with byte-offset
 * tracking for incremental reads.
 *
 * Exports: parseJsonlEntry, splitSentences, mapToEvents, readNewEntries, TmuxPool
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { execFileSync } from 'child_process';
import { EventEmitter } from 'events';
import { createLogger } from './logger';
import { fileEntities } from './entity-extract';

const log = createLogger('tmux');

// ---------------------------------------------------------------------------
// Sentence boundary detection (matching inference.ts)
// ---------------------------------------------------------------------------

const SENTENCE_RE = /(?<=[.!?])\s+|(?<=[.!?])$/;
const CLAUSE_RE = /(?<=[,; \u2013\-])\s+/;
const CLAUSE_SPLIT_THRESHOLD = 120;

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

export interface ReadResult {
  entries: Array<Record<string, unknown>>;
  newOffset: number;
}

export interface TmuxAgentState {
  agentName: string;
  sessionId: string;
  jsonlPath: string | null;
  byteOffset: number;
  busy: boolean;
  booted: boolean;          // true once claude CLI is ready for input
  bootTimer: ReturnType<typeof setInterval> | null;
  queue: QueuedMessage[];
  previousText: string;
  currentEmitter: EventEmitter | null;
  pollTimer: ReturnType<typeof setInterval> | null;
  sentenceIndex: number;
}

export interface QueuedMessage {
  text: string;
  source: string;
  senderName?: string;
  emitter: EventEmitter;
}

export interface WindowConfig {
  sessionId: string;
  claudeBin: string;
  mcpConfigPath: string;
}

// ---------------------------------------------------------------------------
// Shared tmux exec options
// ---------------------------------------------------------------------------

const TMUX_EXEC_OPTS = {
  encoding: 'utf-8' as const,
  timeout: 10000,
  stdio: ['pipe', 'pipe', 'pipe'] as ['pipe', 'pipe', 'pipe'],
};

// ---------------------------------------------------------------------------
// Part 1: JSONL parsing and event mapping
// ---------------------------------------------------------------------------

/**
 * Parse a single JSONL line. Returns null for invalid/empty lines.
 */
export function parseJsonlEntry(line: string): Record<string, unknown> | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Split text into sentences using sentence and clause boundary regexes.
 * Matches the logic in inference.ts.
 */
export function splitSentences(text: string): string[] {
  const sentences: string[] = [];
  let buffer = text;

  // Split on sentence boundaries first
  const parts = buffer.split(SENTENCE_RE);
  for (let i = 0; i < parts.length; i++) {
    let segment = parts[i].trim();
    if (!segment) continue;

    // For long segments, try clause-level splitting
    if (segment.length >= CLAUSE_SPLIT_THRESHOLD) {
      const cparts = segment.split(CLAUSE_RE);
      if (cparts.length > 1) {
        // Emit all but the last clause segment joined together, then the last separately
        const toEmit = cparts.slice(0, -1).join(' ').trim();
        const remainder = cparts[cparts.length - 1].trim();
        if (toEmit) sentences.push(toEmit);
        if (remainder) sentences.push(remainder);
        continue;
      }
    }
    sentences.push(segment);
  }

  return sentences;
}

/**
 * Map a parsed JSONL entry to inference events.
 *
 * Only processes `type: 'assistant'` entries. Computes text deltas from
 * previousText to avoid re-emitting already-seen content.
 */
export function mapToEvents(
  entry: Record<string, unknown>,
  previousText: string,
): Array<Record<string, unknown>> {
  if (entry.type !== 'assistant') return [];

  const message = entry.message as Record<string, unknown> | undefined;
  if (!message) return [];

  const content = message.content as Array<Record<string, unknown>> | undefined;
  if (!Array.isArray(content)) return [];

  const events: Array<Record<string, unknown>> = [];
  let fullText = '';

  for (const block of content) {
    if (block.type === 'text') {
      fullText += (block.text as string) || '';
    } else if (block.type === 'tool_use') {
      events.push({
        type: 'ToolUse',
        name: (block.name as string) || '',
        toolId: (block.id as string) || '',
        inputJson: JSON.stringify(block.input || {}),
      });
    }
    // type: 'thinking' - skip
  }

  // Compute text delta from previousText
  if (fullText.length > previousText.length && fullText.startsWith(previousText)) {
    const delta = fullText.slice(previousText.length);
    if (delta) {
      events.unshift({ type: 'TextDelta', text: delta });
    }
  } else if (fullText && fullText !== previousText) {
    // Text changed in a non-incremental way - emit the full text as delta
    events.unshift({ type: 'TextDelta', text: fullText });
  }

  // Check for stop_reason: end_turn
  if (message.stop_reason === 'end_turn') {
    // Split full text into sentences and emit SentenceReady events
    const sentences = splitSentences(fullText);
    for (let i = 0; i < sentences.length; i++) {
      events.push({
        type: 'SentenceReady',
        sentence: sentences[i],
        index: i,
      });
    }
    events.push({
      type: 'StreamDone',
      fullText,
      sessionId: '',
    });
  }

  return events;
}

// ---------------------------------------------------------------------------
// Part 2: Byte-offset file reader
// ---------------------------------------------------------------------------

/**
 * Read new JSONL entries from a file starting at the given byte offset.
 * Only advances the offset past successfully parsed lines - partial writes
 * at the end of the file are left for the next read.
 */
export function readNewEntries(filePath: string, byteOffset: number): ReadResult {
  let fd: number | undefined;
  try {
    // Check file exists and get size
    const stat = fs.statSync(filePath);
    let offset = byteOffset;

    // Reset if file was truncated (e.g. new session)
    if (stat.size < offset) {
      offset = 0;
    }

    // Nothing new to read
    if (stat.size === offset) {
      return { entries: [], newOffset: offset };
    }

    // Read from offset to end
    const readLength = stat.size - offset;
    const buffer = Buffer.alloc(readLength);
    fd = fs.openSync(filePath, 'r');
    fs.readSync(fd, buffer, 0, readLength, offset);
    fs.closeSync(fd);
    fd = undefined;

    const text = buffer.toString('utf-8');
    const lines = text.split('\n');

    const entries: Array<Record<string, unknown>> = [];
    let bytesConsumed = 0;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      // Last element after split has no trailing newline
      const isLast = i === lines.length - 1;
      const lineBytes = Buffer.byteLength(line + (isLast ? '' : '\n'), 'utf-8');

      // Skip empty lines but still advance past them
      if (!line.trim()) {
        // Don't advance past a trailing empty string (it has 0 bytes)
        if (!isLast || line.length > 0) {
          bytesConsumed += lineBytes;
        }
        continue;
      }

      // Try to parse - if it fails, this might be a partial write
      const entry = parseJsonlEntry(line);
      if (entry) {
        entries.push(entry);
        bytesConsumed += lineBytes;
      } else {
        // Partial/invalid line - stop here, don't advance past it
        break;
      }
    }

    return {
      entries,
      newOffset: offset + bytesConsumed,
    };
  } catch (e) {
    // File doesn't exist or read error - return unchanged offset
    if (fd !== undefined) {
      try { fs.closeSync(fd); } catch { /* best effort */ }
    }
    return { entries: [], newOffset: byteOffset };
  }
}

// ---------------------------------------------------------------------------
// Part 3: TmuxPool class
// ---------------------------------------------------------------------------

export class TmuxPool {
  private sessionName: string;
  private agents: Map<string, TmuxAgentState> = new Map();

  constructor(sessionName = 'atrophy') {
    this.sessionName = sessionName;
  }

  /**
   * Check if tmux is available on the system.
   */
  static isAvailable(): boolean {
    try {
      execFileSync('which', ['tmux'], TMUX_EXEC_OPTS);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Create the tmux session if it doesn't already exist.
   */
  ensureSession(): void {
    try {
      execFileSync('tmux', ['has-session', '-t', this.sessionName], TMUX_EXEC_OPTS);
      log.debug(`tmux session "${this.sessionName}" already exists`);
    } catch {
      // Session doesn't exist - create it detached
      execFileSync('tmux', [
        'new-session', '-d', '-s', this.sessionName, '-x', '200', '-y', '50',
      ], TMUX_EXEC_OPTS);
      log.info(`created tmux session "${this.sessionName}"`);
    }
  }

  /**
   * Create a new tmux window for an agent and start the Claude CLI in it.
   */
  createWindow(agentName: string, config: WindowConfig): void {
    const { sessionId, claudeBin, mcpConfigPath } = config;
    const target = `${this.sessionName}:${agentName}`;

    // Create the window
    execFileSync('tmux', [
      'new-window', '-t', this.sessionName, '-n', agentName,
    ], TMUX_EXEC_OPTS);

    // Build the claude command
    const claudeCmd = [
      claudeBin,
      '--session-id', sessionId,
      '--output-format', 'stream-json',
      '--mcp-config', mcpConfigPath,
      '--verbose',
    ].join(' ');

    // Send the command to start Claude CLI
    execFileSync('tmux', [
      'send-keys', '-t', target, claudeCmd, 'Enter',
    ], TMUX_EXEC_OPTS);

    // Derive JSONL path
    const jsonlPath = this.findJsonlPath(agentName, sessionId);

    // Initialize agent state - booted=false until CLI is ready for input
    const state: TmuxAgentState = {
      agentName,
      sessionId,
      jsonlPath,
      byteOffset: 0,
      busy: false,
      booted: false,
      bootTimer: null,
      queue: [],
      previousText: '',
      currentEmitter: null,
      pollTimer: null,
      sentenceIndex: 0,
    };
    this.agents.set(agentName, state);

    // Poll terminal for boot completion (CLI shows input prompt when ready)
    state.bootTimer = setInterval(() => {
      try {
        const pane = this.capturePane(agentName);
        // Claude CLI shows a > prompt or an empty line with cursor when ready.
        // During boot, it shows spinner chars or hook output.
        // Check last few lines for absence of spinner and presence of prompt.
        const lines = pane.split('\n').filter(l => l.trim());
        const lastLine = lines[lines.length - 1] || '';
        const hasSpinner = /[*+\u2022\u2023\u25cf\u25cb\u2219\u00b7\u2713\u2717\u23f3\u2026]/.test(lastLine);
        const isReady = !hasSpinner && lines.length > 0 && pane.length > 50;

        if (isReady) {
          clearInterval(state.bootTimer!);
          state.bootTimer = null;
          state.booted = true;

          // Discover JSONL path now that session is active
          if (!state.jsonlPath) {
            state.jsonlPath = this.findJsonlPath(agentName, sessionId);
          }

          log.info(`[${agentName}] tmux agent booted and ready`);

          // Drain any messages that queued during boot
          if (state.queue.length > 0 && !state.busy) {
            const next = state.queue.shift()!;
            this.startMessage(state, next.text, next.source, next.senderName, next.emitter);
          }
        }
      } catch {
        // capturePane failed - keep polling
      }
    }, 1000);

    // Safety: mark as booted after 30s regardless (boot shouldn't take that long)
    setTimeout(() => {
      if (!state.booted) {
        if (state.bootTimer) { clearInterval(state.bootTimer); state.bootTimer = null; }
        state.booted = true;
        log.warn(`[${agentName}] boot timeout - marking as ready anyway`);
        if (state.queue.length > 0 && !state.busy) {
          const next = state.queue.shift()!;
          this.startMessage(state, next.text, next.source, next.senderName, next.emitter);
        }
      }
    }, 30_000);

    log.info(`created tmux window for agent "${agentName}" (session: ${sessionId})`);
  }

  /**
   * Press Enter in an agent's tmux window.
   */
  pressEnter(agentName: string): void {
    const target = `${this.sessionName}:${agentName}`;
    execFileSync('tmux', ['send-keys', '-t', target, '', 'Enter'], TMUX_EXEC_OPTS);
  }

  /**
   * Get the state for an agent.
   */
  get(agentName: string): TmuxAgentState | undefined {
    return this.agents.get(agentName);
  }

  /**
   * Get all registered agent names.
   */
  agentNames(): string[] {
    return Array.from(this.agents.keys());
  }

  /**
   * Check if an agent's tmux window is still alive.
   */
  isWindowAlive(agentName: string): boolean {
    try {
      const target = `${this.sessionName}:${agentName}`;
      execFileSync('tmux', ['has-session', '-t', target], TMUX_EXEC_OPTS);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Capture the current pane contents for an agent's window.
   * Useful for spinner detection and debugging.
   */
  capturePane(agentName: string): string {
    try {
      const target = `${this.sessionName}:${agentName}`;
      return execFileSync('tmux', [
        'capture-pane', '-t', target, '-p',
      ], TMUX_EXEC_OPTS).trim();
    } catch {
      return '';
    }
  }

  /**
   * Kill an agent's tmux window.
   */
  killWindow(agentName: string): void {
    const state = this.agents.get(agentName);
    if (state?.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
    if (state?.bootTimer) { clearInterval(state.bootTimer); state.bootTimer = null; }
    if (state?.currentEmitter) {
      state.currentEmitter.emit('error', new Error('window killed'));
      state.currentEmitter = null;
    }
    try {
      const target = `${this.sessionName}:${agentName}`;
      execFileSync('tmux', ['kill-window', '-t', target], TMUX_EXEC_OPTS);
    } catch {
      // Window may already be gone
    }
    this.agents.delete(agentName);
    log.info(`killed tmux window for agent "${agentName}"`);
  }

  /**
   * Stop all agent windows and kill the tmux session.
   */
  stopAll(): void {
    for (const agentName of this.agentNames()) {
      const state = this.agents.get(agentName);
      if (state?.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
      if (state?.bootTimer) { clearInterval(state.bootTimer); state.bootTimer = null; }
      if (state?.currentEmitter) {
        state.currentEmitter.emit('error', new Error('pool stopped'));
        state.currentEmitter = null;
      }
    }
    this.agents.clear();
    try {
      execFileSync('tmux', ['kill-session', '-t', this.sessionName], TMUX_EXEC_OPTS);
      log.info(`killed tmux session "${this.sessionName}"`);
    } catch {
      // Session may already be gone
    }
  }

  // -------------------------------------------------------------------------
  // Part 4: Message send/poll loop
  // -------------------------------------------------------------------------

  /**
   * Send a message to an agent. Returns an EventEmitter that emits inference events.
   * If the agent is busy, the message is queued and will be sent when the current
   * message completes.
   */
  send(agentName: string, text: string, source: string, senderName?: string): EventEmitter {
    const emitter = new EventEmitter();
    const state = this.agents.get(agentName);

    if (!state) {
      process.nextTick(() => emitter.emit('error', new Error(`agent "${agentName}" not found in pool`)));
      return emitter;
    }

    if (!state.booted || state.busy) {
      state.queue.push({ text, source, senderName, emitter });
      log.debug(`queued message for "${agentName}" (${!state.booted ? 'booting' : 'busy'}, queue depth: ${state.queue.length})`);
      return emitter;
    }

    this.startMessage(state, text, source, senderName, emitter);
    return emitter;
  }

  /**
   * Cancel the current inference for an agent. Sends Ctrl+C to the tmux window,
   * clears the queue, and emits an error on the current emitter.
   */
  cancel(agentName: string): void {
    const state = this.agents.get(agentName);
    if (!state) return;

    // Stop polling
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }

    // Error out current emitter
    if (state.currentEmitter) {
      state.currentEmitter.emit('error', new Error('inference cancelled'));
      state.currentEmitter = null;
    }

    // Send Ctrl+C to abort Claude CLI
    try {
      const target = `${this.sessionName}:${agentName}`;
      execFileSync('tmux', ['send-keys', '-t', target, 'C-c', ''], TMUX_EXEC_OPTS);
    } catch {
      log.warn(`failed to send Ctrl+C to "${agentName}"`);
    }

    // Clear queue - emit error on each queued emitter
    for (const queued of state.queue) {
      queued.emitter.emit('error', new Error('inference cancelled'));
    }
    state.queue = [];
    state.busy = false;
    state.previousText = '';
    state.sentenceIndex = 0;

    log.info(`cancelled inference for "${agentName}"`);
  }

  // -------------------------------------------------------------------------
  // Private methods
  // -------------------------------------------------------------------------

  private startMessage(
    state: TmuxAgentState,
    text: string,
    _source: string,
    _senderName: string | undefined,
    emitter: EventEmitter,
  ): void {
    state.busy = true;
    state.currentEmitter = emitter;
    state.previousText = '';
    state.sentenceIndex = 0;

    // Snapshot the current byte offset before sending
    if (state.jsonlPath) {
      try {
        const stat = fs.statSync(state.jsonlPath);
        state.byteOffset = stat.size;
      } catch {
        // File may not exist yet - that's fine
        state.byteOffset = 0;
      }
    }

    // Send the message text via tmux send-keys
    const target = `${this.sessionName}:${state.agentName}`;
    try {
      execFileSync('tmux', ['send-keys', '-t', target, text, ''], TMUX_EXEC_OPTS);
    } catch (e) {
      state.busy = false;
      state.currentEmitter = null;
      emitter.emit('error', new Error(`failed to send keys: ${e}`));
      return;
    }

    // Press Enter after a short delay to let tmux process the text
    setTimeout(() => {
      try {
        this.pressEnter(state.agentName);
      } catch (e) {
        log.warn(`failed to press enter for "${state.agentName}": ${e}`);
      }
      // Start polling for responses
      this.startPolling(state);
    }, 500);
  }

  private startPolling(state: TmuxAgentState): void {
    if (!state.jsonlPath) {
      log.warn(`no JSONL path for agent "${state.agentName}" - cannot poll`);
      return;
    }

    state.pollTimer = setInterval(() => {
      if (!state.jsonlPath || !state.currentEmitter) return;

      const result = readNewEntries(state.jsonlPath, state.byteOffset);
      state.byteOffset = result.newOffset;

      for (const entry of result.entries) {
        const events = mapToEvents(entry, state.previousText);

        for (const event of events) {
          if (event.type === 'TextDelta') {
            state.previousText += event.text as string;
          }
          state.currentEmitter.emit('event', event);

          if (event.type === 'StreamDone') {
            // Auto-extract entities from final response into intelligence.db
            const finalText = (event.fullText as string) || state.previousText;
            if (finalText) {
              try { fileEntities(state.agentName, finalText); } catch { /* best effort */ }
            }
            this.completeMessage(state);
            return;
          }
        }
      }
    }, 200);
  }

  private completeMessage(state: TmuxAgentState): void {
    // Clear poll timer
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }

    state.currentEmitter = null;
    state.busy = false;
    state.previousText = '';
    state.sentenceIndex = 0;

    // Drain queue - start next message if available
    if (state.queue.length > 0) {
      const next = state.queue.shift()!;
      this.startMessage(state, next.text, next.source, next.senderName, next.emitter);
    }
  }

  /**
   * Derive the JSONL file path for an agent's Claude CLI session.
   *
   * Agent runs from ~/.atrophy/agents/<name>, which Claude CLI maps to
   * ~/.claude/projects/-Users-<user>--atrophy-agents-<name>/<sessionId>.jsonl
   *
   * The slug is the cwd path with `/` replaced by `-` and leading `/` replaced by `-`.
   */
  private findJsonlPath(agentName: string, sessionId: string): string {
    const home = os.homedir();
    const agentCwd = path.join(home, '.atrophy', 'agents', agentName);
    // Convert cwd to Claude CLI project slug: /Users/foo -> -Users-foo
    // Consecutive slashes become single hyphens, but the path uses path.join so no doubles
    const slug = agentCwd.split(path.sep).join('-');
    const jsonlPath = path.join(home, '.claude', 'projects', slug, `${sessionId}.jsonl`);
    return jsonlPath;
  }
}

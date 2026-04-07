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
  // Cache the WindowConfig for each agent so we can recreate the window
  // on death without the caller needing to provide it again.
  private configs: Map<string, WindowConfig> = new Map();
  // Health-check timer for auto-reboot. Polls all agent windows every 30s
  // and recreates any that have died (window missing or no claude process).
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private static HEALTH_CHECK_INTERVAL_MS = 30_000;
  // Track restart count + window per agent to bound auto-reboot loops
  private restartHistory: Map<string, number[]> = new Map();
  private static MAX_RESTARTS_PER_HOUR = 6;

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
   * If a window with the same name already exists (from a previous boot
   * that didn't shut down cleanly), it is killed first to prevent tmux
   * from auto-renaming the new window with a `-` suffix.
   * Also ensures the parent session exists - critical for auto-reboot
   * after the user manually killed the session.
   */
  createWindow(agentName: string, config: WindowConfig): void {
    const { sessionId, claudeBin, mcpConfigPath } = config;
    const target = `${this.sessionName}:${agentName}`;

    // Cache config for auto-reboot
    this.configs.set(agentName, config);

    // Ensure the parent session exists (it may have been killed externally)
    this.ensureSession();

    // Kill ALL windows whose name matches this agent (including dash-suffixed
    // duplicates from prior boots). tmux auto-renames new windows with `-`
    // when there's a name collision, so a stale `general_montgomery-` won't
    // be matched by `kill-window -t atrophy:general_montgomery` - we have to
    // list windows and target each duplicate explicitly.
    try {
      const list = execFileSync(
        'tmux', ['list-windows', '-t', this.sessionName, '-F', '#{window_id} #{window_name}'],
        TMUX_EXEC_OPTS,
      );
      for (const line of list.split('\n')) {
        const [winId, ...nameParts] = line.trim().split(/\s+/);
        const winName = nameParts.join(' ');
        if (!winId || !winName) continue;
        // Match exact name OR name with trailing `-` characters (tmux dedup suffix)
        if (winName === agentName || winName.replace(/-+$/, '') === agentName) {
          try {
            execFileSync('tmux', ['kill-window', '-t', winId], TMUX_EXEC_OPTS);
            log.debug(`killed existing window ${winId} (${winName}) for ${agentName}`);
          } catch { /* race - window may have died between list and kill */ }
        }
      }
    } catch {
      // list-windows failed - session may not exist yet
    }

    // Create the window with the agent's data dir as cwd, so the JSONL file
    // gets written to ~/.claude/projects/-Users-...-atrophy-agents-<name>/
    // (which is what findJsonlPath expects).
    const agentCwd = path.join(os.homedir(), '.atrophy', 'agents', agentName);
    execFileSync('tmux', [
      'new-window', '-t', this.sessionName, '-n', agentName, '-c', agentCwd,
    ], TMUX_EXEC_OPTS);

    // Determine if the session already exists (resume) or is new (--session-id).
    // A session is "existing" if its JSONL file is on disk.
    const existingJsonl = this.findJsonlPath(agentName, sessionId);
    const sessionFlag = existingJsonl ? '--resume' : '--session-id';

    // Build the claude command. Interactive mode (no -p), no --output-format
    // (we read from JSONL files instead). --dangerously-skip-permissions is
    // required so the agent can use its tools without prompting.
    const claudeArgs = [
      claudeBin,
      sessionFlag, sessionId,
      '--dangerously-skip-permissions',
      '--mcp-config', mcpConfigPath,
    ];
    const claudeCmd = claudeArgs.join(' ');

    // Send the command to start Claude CLI
    execFileSync('tmux', [
      'send-keys', '-t', target, claudeCmd, 'Enter',
    ], TMUX_EXEC_OPTS);

    log.debug(`[${agentName}] starting claude with ${sessionFlag} ${sessionId} in ${agentCwd}`);

    // JSONL path - use existing if found, otherwise compute expected path
    const jsonlPath = existingJsonl || this.findJsonlPath(agentName, sessionId);

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

    // Poll for boot completion: check if claude is running as a child process
    // of the tmux pane shell. This is the same check as isWindowAlive() and
    // is more reliable than terminal-character matching (which gets confused
    // by the active-window indicator `*`, hook output, etc.).
    state.bootTimer = setInterval(() => {
      try {
        if (this.isWindowAlive(agentName)) {
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
        // isWindowAlive failed - keep polling
      }
    }, 1000);

    // Safety: mark as booted after 90s regardless. Claude CLI boot with all
    // MCP servers + hooks can take 30-60s the first time, so 30s was too
    // aggressive. The health check loop will detect a real death later.
    setTimeout(() => {
      if (!state.booted) {
        if (state.bootTimer) { clearInterval(state.bootTimer); state.bootTimer = null; }
        state.booted = true;
        log.warn(`[${agentName}] boot timeout (90s) - marking as ready anyway`);
        if (state.queue.length > 0 && !state.busy) {
          const next = state.queue.shift()!;
          this.startMessage(state, next.text, next.source, next.senderName, next.emitter);
        }
      }
    }, 90_000);

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
   * Check if an agent's tmux window exists and has a running claude process.
   * Returns false if the window is missing OR if the window has only a shell
   * (claude crashed and dropped to the prompt). Treats `name-` (dash suffix
   * from tmux dedup) as the same window for matching purposes.
   */
  isWindowAlive(agentName: string): boolean {
    try {
      // List all windows and find the one that matches this agent name.
      // We can't use `list-panes -t atrophy:name` directly because tmux may
      // have renamed our window with a `-` suffix during a duplicate-create.
      const list = execFileSync(
        'tmux', ['list-windows', '-t', this.sessionName, '-F', '#{window_id} #{window_name}'],
        TMUX_EXEC_OPTS,
      );
      let winId: string | null = null;
      for (const line of list.split('\n')) {
        const [id, ...nameParts] = line.trim().split(/\s+/);
        const winName = nameParts.join(' ');
        if (!id || !winName) continue;
        if (winName === agentName || winName.replace(/-+$/, '') === agentName) {
          winId = id;
          break;
        }
      }
      if (!winId) return false;

      // Get the pane PID for this window
      const panePid = execFileSync(
        'tmux', ['list-panes', '-t', winId, '-F', '#{pane_pid}'],
        TMUX_EXEC_OPTS,
      ).trim().split('\n')[0];
      if (!panePid) return false;

      // Check if the pane has any child processes (claude lives as child of shell)
      try {
        const children = execFileSync('pgrep', ['-P', panePid], TMUX_EXEC_OPTS).trim();
        return children.length > 0;
      } catch {
        return false;
      }
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
    this.stopHealthCheck();
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
    this.configs.clear();
    this.restartHistory.clear();
    try {
      execFileSync('tmux', ['kill-session', '-t', this.sessionName], TMUX_EXEC_OPTS);
      log.info(`killed tmux session "${this.sessionName}"`);
    } catch {
      // Session may already be gone
    }
  }

  /**
   * Start the auto-reboot health check. Polls all agent windows every 30s
   * and recreates any that have died, using the cached WindowConfig.
   * Bounded by MAX_RESTARTS_PER_HOUR per agent to prevent crash loops.
   * Skips agents that haven't finished booting (state.booted === false) so
   * it doesn't restart agents during their initial boot sequence.
   */
  startHealthCheck(): void {
    if (this.healthTimer) return;
    log.info(`Starting tmux health check (interval: ${TmuxPool.HEALTH_CHECK_INTERVAL_MS / 1000}s)`);
    this.healthTimer = setInterval(() => {
      for (const agentName of this.configs.keys()) {
        try {
          // Skip agents that haven't finished booting yet - the boot timer
          // is still running and will mark them ready or fail-safe at 90s
          const state = this.agents.get(agentName);
          if (!state?.booted) continue;

          if (!this.isWindowAlive(agentName)) {
            this.handleDeadAgent(agentName);
          }
        } catch (err) {
          log.warn(`health check failed for ${agentName}:`, err);
        }
      }
    }, TmuxPool.HEALTH_CHECK_INTERVAL_MS);
  }

  /** Stop the auto-reboot health check */
  stopHealthCheck(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer);
      this.healthTimer = null;
    }
  }

  /** Handle a dead agent: check restart budget, then recreate */
  private handleDeadAgent(agentName: string): void {
    const now = Date.now();
    const oneHourAgo = now - 3600_000;
    const history = (this.restartHistory.get(agentName) || []).filter(t => t > oneHourAgo);

    if (history.length >= TmuxPool.MAX_RESTARTS_PER_HOUR) {
      // Already restarted MAX times in the last hour - log once per cycle
      log.error(`[${agentName}] dead but restart budget exhausted (${history.length}/${TmuxPool.MAX_RESTARTS_PER_HOUR} in last hour) - manual intervention required`);
      return;
    }

    const config = this.configs.get(agentName);
    if (!config) {
      log.warn(`[${agentName}] dead but no cached config - cannot auto-restart`);
      return;
    }

    log.warn(`[${agentName}] tmux window dead - auto-restarting (restart ${history.length + 1}/${TmuxPool.MAX_RESTARTS_PER_HOUR} this hour)`);
    history.push(now);
    this.restartHistory.set(agentName, history);

    // Clean up old state then recreate
    const state = this.agents.get(agentName);
    if (state?.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
    if (state?.bootTimer) { clearInterval(state.bootTimer); state.bootTimer = null; }
    if (state?.currentEmitter) {
      state.currentEmitter.emit('event', { type: 'StreamError', message: 'tmux window died - restarting' });
    }
    this.agents.delete(agentName);

    try {
      this.createWindow(agentName, config);
      // Press Enter after 1s so the CLI starts processing
      setTimeout(() => {
        try { this.pressEnter(agentName); } catch (e) { log.warn(`[${agentName}] pressEnter failed: ${e}`); }
      }, 1000);
    } catch (err) {
      log.error(`[${agentName}] auto-restart failed:`, err);
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

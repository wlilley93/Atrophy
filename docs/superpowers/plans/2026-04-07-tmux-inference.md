# Tmux-Based Persistent Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Replace spawn-per-message inference with persistent per-agent tmux sessions, eliminating CLI boot overhead and MCP cold-starts for interactive channels.

**Architecture:** One hidden tmux window per primary agent running claude in interactive mode. Messages sent via tmux send-keys. Responses read from Claude Code JSONL session files with byte-offset tracking. The existing streamInference() routes interactive channels through the tmux pool while cron/ephemeral channels keep one-shot spawn.

**Tech Stack:** tmux (via execFileSync), JSONL file reading, existing EventEmitter event types

**Spec:** docs/superpowers/specs/2026-04-07-tmux-inference-design.md

---

## 7 Tasks

### Task 1: JSONL reader and event mapper
Create src/main/tmux-inference.ts with parseJsonlEntry(), splitSentences(), and mapToEvents(). These parse JSONL entries from Claude Code session files and map them to Atrophy event types (TextDelta, SentenceReady, ToolUse, ToolResult, StreamDone). Test file at src/main/__tests__/tmux-inference.test.ts.

### Task 2: Byte-offset file reader
Add readNewEntries(filePath, byteOffset) to tmux-inference.ts. Reads new JSONL lines from a file starting at a byte offset. Handles file truncation and partial writes. Only advances offset past successfully parsed lines.

### Task 3: Tmux session and window management
Add TmuxPool class to tmux-inference.ts. Manages one tmux session (named "atrophy") with one window per agent. Methods: ensureSession(), createWindow(), pressEnter(), capturePane(), killWindow(), stopAll(), isAvailable(). Uses execFileSync for all tmux commands (not exec - safe from injection).

### Task 4: Message sending and JSONL response polling
Add send(), cancel(), startMessage(), startPolling(), completeMessage(), findJsonlPath() to TmuxPool. The send flow: queue if busy, record byte offset, send-keys text, press Enter after 500ms, poll JSONL every 200ms for new entries, map entries to events via mapToEvents(), emit StreamDone on end_turn, drain queue.

### Task 5: Wire streamInference() to tmux pool
Modify src/main/inference.ts. Add getTmuxPool() export. At the start of streamInference(), route interactive channels (desktop/telegram/server) through the tmux pool if available. Extract agent name from processKey. Fall back to one-shot spawn if tmux unavailable or agent not in pool. Update stopInference() and stopAllInference() to cancel/stop via pool.

### Task 6: Boot initialization and shutdown
Modify src/main/app.ts. After wireAgent loop, create tmux windows for primary agents (those with desktop or telegram enabled in manifest). Load last session ID from memory.db, build MCP config, create window, press Enter after 1s delay. stopAllInference() already handles pool shutdown from Task 5.

### Task 7: Integration test
Build, install, verify: tmux windows created at boot, desktop messages route through tmux (fast on second message), agent switching works, cron jobs use ephemeral path.

## Full task details with code

The complete implementation code for each task is provided inline in this conversation. The implementer subagent should reference:
- Spec: docs/superpowers/specs/2026-04-07-tmux-inference-design.md
- ccbot reference: /Users/williamlilley/Projects/Claude/ccbot/src/ccbot/session_monitor.py (JSONL reading pattern)
- JSONL format: type=assistant entries with message.content[].type=text/tool_use, message.stop_reason=end_turn for completion
- Project dir pattern: ~/.claude/projects/ with cwd slug (/ replaced by -)

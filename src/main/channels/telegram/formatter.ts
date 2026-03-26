/**
 * Telegram message formatting and streaming display.
 *
 * Pure formatting functions for rendering inference progress in Telegram
 * messages - tool call display, status lines, Markdown escaping, and
 * the full streaming status builder.
 */

import * as path from 'path';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ToolCallState {
  name: string;
  id: string;
  input: string;
  result: string;
}

export interface StreamState {
  thinkingText: string;
  activeTool: ToolCallState | null;
  pendingTools: Map<string, ToolCallState>;
  completedTools: ToolCallState[];
  responseText: string;
  isCompacting: boolean;
  startTime: number;
}

// ---------------------------------------------------------------------------
// Text utilities
// ---------------------------------------------------------------------------

/**
 * Formats a tool name for display - strips MCP prefixes for readability.
 * e.g. "mcp__memory__recall" -> "recall"
 *      "mcp__google__calendar_events" -> "calendar_events"
 */
export function formatToolName(name: string): string {
  const parts = name.split('__');
  return parts.length > 2 ? parts.slice(2).join('__') : parts[parts.length - 1];
}

/**
 * Truncate text with ellipsis for display in status lines.
 */
export function truncate(text: string, maxLen: number): string {
  const cleaned = text.replace(/\n/g, ' ').trim();
  if (cleaned.length <= maxLen) return cleaned;
  return cleaned.slice(0, maxLen - 1) + '\u2026';
}

/**
 * Escape Markdown special characters to prevent parse failures.
 */
export function escapeMarkdown(text: string): string {
  return text.replace(/[_*`\[\]()~>#+=|{}.!\\-]/g, '\\$&');
}

/**
 * Format elapsed time as human-readable string.
 */
export function formatElapsed(ms: number): string {
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  return `${mins}m ${remSecs}s`;
}

// ---------------------------------------------------------------------------
// Tool display formatting
// ---------------------------------------------------------------------------

/**
 * Extract stats from a tool result for concise display.
 * e.g. Read: "42 lines", Grep: "5 matches", Edit: "changed 3 lines"
 */
export function formatToolResult(toolName: string, input: string, result: string): string {
  const name = formatToolName(toolName).toLowerCase();

  // Count lines in result
  const lines = result.split('\n').filter((l) => l.trim()).length;

  // Try to extract meaningful stats based on tool type
  if (name === 'read' || name === 'cat') {
    return `${lines} lines`;
  }
  if (name === 'grep' || name === 'search') {
    const matchCount = (result.match(/\n/g) || []).length;
    return matchCount > 0 ? `${matchCount} matches` : 'no matches';
  }
  if (name === 'glob' || name === 'find') {
    return `${lines} files`;
  }
  if (name === 'write' || name === 'write_note') {
    return `wrote ${lines} lines`;
  }
  if (name === 'edit') {
    return 'applied';
  }
  if (name === 'bash' || name === 'shell' || name === 'execute') {
    if (lines === 0) return 'done';
    return `${lines} lines output`;
  }
  if (name === 'recall' || name === 'memory' || name === 'search_memory') {
    return lines > 0 ? `${lines} results` : 'no results';
  }
  if (name === 'remember') {
    return 'saved';
  }

  // Generic fallback
  if (lines === 0) return 'done';
  if (lines <= 3) return truncate(result, 80);
  return `${lines} lines`;
}

/**
 * Parse tool input JSON to extract a concise argument summary.
 * e.g. Read("src/main/config.ts"), Grep("pattern", "path")
 */
export function formatToolInput(toolName: string, inputJson: string): string {
  if (!inputJson) return '';
  try {
    const parsed = JSON.parse(inputJson);
    const name = formatToolName(toolName).toLowerCase();

    if (name === 'read' || name === 'cat') {
      const p = parsed.file_path || parsed.path || '';
      return p ? `\`${path.basename(p)}\`` : '';
    }
    if (name === 'grep' || name === 'search') {
      const pattern = parsed.pattern || parsed.query || '';
      return pattern ? `"${truncate(pattern, 30)}"` : '';
    }
    if (name === 'glob' || name === 'find') {
      return parsed.pattern ? `"${truncate(parsed.pattern, 30)}"` : '';
    }
    if (name === 'write' || name === 'write_note') {
      const p = parsed.file_path || parsed.path || parsed.title || '';
      return p ? `\`${path.basename(p)}\`` : '';
    }
    if (name === 'edit') {
      const p = parsed.file_path || parsed.path || '';
      return p ? `\`${path.basename(p)}\`` : '';
    }
    if (name === 'bash' || name === 'shell' || name === 'execute') {
      const cmd = parsed.command || '';
      return cmd ? `\`${truncate(cmd, 40)}\`` : '';
    }
    if (name === 'recall' || name === 'memory' || name === 'search_memory') {
      const q = parsed.query || parsed.action || '';
      return q ? `"${truncate(q, 40)}"` : '';
    }
    if (name === 'remember') {
      const content = parsed.content || parsed.text || '';
      return content ? `"${truncate(content, 40)}"` : '';
    }
    // Generic: show first string value
    for (const v of Object.values(parsed)) {
      if (typeof v === 'string' && v.length > 0) {
        return `"${truncate(v, 40)}"`;
      }
    }
  } catch { /* not valid JSON yet */ }
  return '';
}

// ---------------------------------------------------------------------------
// Status display builder
// ---------------------------------------------------------------------------

/**
 * Build a rich status display for Telegram showing the full inference process.
 *
 * Layout:
 *   [elapsed time]
 *   [thinking block as blockquote if present]
 *   [completed tool calls with stats]
 *   [active tool call if in progress]
 *   [compacting indicator]
 *   [response text as it streams]
 */
export function buildStatusDisplay(state: StreamState): string {
  const parts: string[] = [];
  const elapsed = formatElapsed(Date.now() - state.startTime);

  // Thinking section - show as blockquote (escaped to prevent Markdown breakage)
  if (state.thinkingText) {
    const thinkPreview = escapeMarkdown(truncate(state.thinkingText, 400));
    parts.push(`> ${thinkPreview}`);
    parts.push('');
  }

  // Completed tool calls with stats
  for (const tool of state.completedTools) {
    const name = formatToolName(tool.name);
    const inputDisplay = formatToolInput(tool.name, tool.input);
    const resultDisplay = tool.result ? formatToolResult(tool.name, tool.input, tool.result) : 'done';

    let line = `\u2705 \`${name}\``;
    // inputDisplay already contains backtick-formatted spans - don't double-escape
    if (inputDisplay) line += ` ${inputDisplay}`;
    line += ` - ${escapeMarkdown(resultDisplay)}`;
    parts.push(line);
  }

  // Active tool call (in progress)
  if (state.activeTool) {
    const name = formatToolName(state.activeTool.name);
    const inputDisplay = formatToolInput(state.activeTool.name, state.activeTool.input);
    let line = `\u23f3 \`${name}\``;
    if (inputDisplay) line += ` ${inputDisplay}`;
    else line += '\u2026';
    parts.push(line);
  }

  // Compacting indicator
  if (state.isCompacting) {
    parts.push('_Compacting context\u2026_');
  }

  // Status line with elapsed time
  if (!state.responseText) {
    const toolCount = state.completedTools.length + (state.activeTool ? 1 : 0);
    const statusParts = [elapsed];
    if (toolCount > 0) statusParts.push(`${toolCount} tools`);
    parts.push(`_${statusParts.join(' | ')}_`);
  }

  // Streamed response text
  if (state.responseText) {
    if (parts.length > 0) parts.push(''); // blank line separator
    parts.push(state.responseText);
  } else if (parts.length === 0) {
    parts.push(`_Thinking\u2026 ${elapsed}_`);
  }

  return parts.join('\n');
}

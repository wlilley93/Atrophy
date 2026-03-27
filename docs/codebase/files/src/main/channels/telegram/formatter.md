# src/main/channels/telegram/formatter.ts - Telegram Message Formatter

**Dependencies:** `path`  
**Purpose:** Streaming inference status display formatting for Telegram

## Overview

This module provides pure formatting functions for rendering inference progress in Telegram messages. It handles tool call display, status lines, Markdown escaping, and the full streaming status builder.

## Types

### ToolCallState

```typescript
export interface ToolCallState {
  name: string;
  id: string;
  input: string;
  result: string;
}
```

**Purpose:** Track state of a single tool call during streaming.

### StreamState

```typescript
export interface StreamState {
  thinkingText: string;
  activeTool: ToolCallState | null;
  pendingTools: Map<string, ToolCallState>;
  completedTools: ToolCallState[];
  responseText: string;
  isCompacting: boolean;
  startTime: number;
}
```

**Purpose:** Full streaming state for status display.

## Text Utilities

### formatToolName

```typescript
export function formatToolName(name: string): string {
  const parts = name.split('__');
  return parts.length > 2 ? parts.slice(2).join('__') : parts[parts.length - 1];
}
```

**Purpose:** Strip MCP prefixes for readability.

**Examples:**
- `"mcp__memory__recall"` → `"recall"`
- `"mcp__google__calendar_events"` → `"calendar_events"`

### truncate

```typescript
export function truncate(text: string, maxLen: number): string {
  const cleaned = text.replace(/\n/g, ' ').trim();
  if (cleaned.length <= maxLen) return cleaned;
  return cleaned.slice(0, maxLen - 1) + '\u2026';  // …
}
```

**Purpose:** Truncate text with ellipsis for status lines.

### escapeMarkdown

```typescript
export function escapeMarkdown(text: string): string {
  return text.replace(/[_*`\[\]()~>#+=|{}.!\\-]/g, '\\$&');
}
```

**Purpose:** Escape Markdown special characters to prevent parse failures.

**Escaped characters:** `_ * ` [ ] ( ) ~ > # + = | { } . ! \ -`

### formatElapsed

```typescript
export function formatElapsed(ms: number): string {
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  return `${mins}m ${remSecs}s`;
}
```

**Purpose:** Format elapsed time as human-readable string.

**Examples:**
- `5000` → `"5s"`
- `125000` → `"2m 5s"`

## Tool Display Formatting

### formatToolResult

```typescript
export function formatToolResult(
  toolName: string,
  input: string,
  result: string,
): string {
  const name = formatToolName(toolName).toLowerCase();
  const lines = result.split('\n').filter((l) => l.trim()).length;

  // Tool-specific stats
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
  if (name === 'bash' || name === 'shell') {
    if (lines === 0) return 'done';
    return `${lines} lines output`;
  }
  if (name === 'recall' || name === 'memory') {
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
```

**Purpose:** Extract concise stats from tool results.

**Examples:**
- `Read("config.ts")` → `"42 lines"`
- `Grep("pattern", "src/")` → `"5 matches"`
- `Write("note.md")` → `"wrote 12 lines"`
- `Remember("User likes coffee")` → `"saved"`

### formatToolInput

```typescript
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
    if (name === 'bash' || name === 'shell') {
      const cmd = parsed.command || '';
      return cmd ? `\`${truncate(cmd, 40)}\`` : '';
    }
    if (name === 'recall' || name === 'memory') {
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
```

**Purpose:** Parse tool input JSON to extract concise argument summary.

**Examples:**
- `Read("src/main/config.ts")` → `` `config.ts` ``
- `Grep("pattern", "src/")` → `"pattern"`
- `Bash("git status")` → `` `git status` ``

## Status Display Builder

### buildStatusDisplay

```typescript
export function buildStatusDisplay(state: StreamState): string {
  const parts: string[] = [];
  const elapsed = formatElapsed(Date.now() - state.startTime);

  // Thinking section - blockquote (escaped)
  if (state.thinkingText) {
    const thinkPreview = escapeMarkdown(truncate(state.thinkingText, 400));
    parts.push(`> ${thinkPreview}`);
    parts.push('');
  }

  // Completed tool calls with stats
  for (const tool of state.completedTools) {
    const name = formatToolName(tool.name);
    const inputDisplay = formatToolInput(tool.name, tool.input);
    const resultDisplay = tool.result
      ? formatToolResult(tool.name, tool.input, tool.result)
      : 'done';

    let line = `✅ \`${name}\``;
    if (inputDisplay) line += ` ${inputDisplay}`;
    line += ` - ${escapeMarkdown(resultDisplay)}`;
    parts.push(line);
  }

  // Active tool call (in progress)
  if (state.activeTool) {
    const name = formatToolName(state.activeTool.name);
    const inputDisplay = formatToolInput(state.activeTool.name, state.activeTool.input);
    let line = `⏳ \`${name}\``;
    if (inputDisplay) line += ` ${inputDisplay}`;
    else line += '…';
    parts.push(line);
  }

  // Compacting indicator
  if (state.isCompacting) {
    parts.push('_Compacting context…_');
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
    if (parts.length > 0) parts.push('');  // Blank line separator
    parts.push(state.responseText);
  } else if (parts.length === 0) {
    parts.push(`_Thinking… ${elapsed}_`);
  }

  return parts.join('\n');
}
```

**Purpose:** Build rich status display for Telegram showing full inference process.

**Layout:**
```
[thinking blockquote if present]

[completed tools with ✅ and stats]
[active tool with ⏳ if in progress]
[compacting indicator if applicable]

[elapsed time | tool count]

[response text as it streams]
```

**Example output:**
```
> I'm thinking about the best approach here...

✅ `read` `config.ts` - 42 lines
✅ `grep` "pattern" - 5 matches
⏳ `edit` `src/main.ts`

_2m 15s | 3 tools_

I've found the issue and I'm applying the fix now...
```

## Usage in Daemon

```typescript
// In daemon.ts - dispatchToAgent
const streamState: StreamState = {
  thinkingText: '',
  activeTool: null,
  pendingTools: new Map(),
  completedTools: [],
  responseText: '',
  isCompacting: false,
  startTime: Date.now(),
};

for await (const evt of emitter) {
  switch (evt.type) {
    case 'ThinkingDelta':
      streamState.thinkingText = evt.text;
      break;

    case 'ToolUse':
      streamState.activeTool = {
        name: evt.name,
        id: evt.toolId,
        input: '',
        result: '',
      };
      break;

    case 'ToolInputDelta':
      if (streamState.activeTool) {
        streamState.activeTool.input += evt.delta;
      }
      break;

    case 'ToolResult':
      if (streamState.activeTool) {
        streamState.activeTool.result = evt.output;
        streamState.completedTools.push(streamState.activeTool);
        streamState.activeTool = null;
      }
      break;

    case 'Compacting':
      streamState.isCompacting = true;
      break;

    case 'TextDelta':
      streamState.responseText += evt.text;
      break;
  }

  // Update Telegram message periodically (throttled to 1.5s)
  if (messageId && Date.now() - lastUpdate > 1500) {
    const statusText = buildStatusDisplay(streamState);
    await editMessage(messageId, statusText, chatId, botToken);
    lastUpdate = Date.now();
  }
}
```

## Exported API

| Function | Purpose |
|----------|---------|
| `formatToolName(name)` | Strip MCP prefixes |
| `truncate(text, maxLen)` | Truncate with ellipsis |
| `escapeMarkdown(text)` | Escape special chars |
| `formatElapsed(ms)` | Format elapsed time |
| `formatToolResult(toolName, input, result)` | Extract result stats |
| `formatToolInput(toolName, inputJson)` | Extract input summary |
| `buildStatusDisplay(state)` | Build full status display |
| `ToolCallState` | Tool call state interface |
| `StreamState` | Streaming state interface |

## See Also

- [`api.ts`](api.md) - Telegram Bot API (editMessage for status updates)
- [`daemon.ts`](daemon.md) - Telegram daemon (uses buildStatusDisplay)
- `src/main/inference.ts` - Inference events that update StreamState

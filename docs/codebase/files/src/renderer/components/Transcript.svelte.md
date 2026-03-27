# src/renderer/components/Transcript.svelte - Conversation Transcript

**Line count:** ~646 lines  
**Dependencies:** `svelte`, store imports, `./ThinkingIndicator.svelte`  
**Purpose:** Render conversation transcript with typewriter reveal, markdown rendering, code blocks, auto-scroll

## Overview

This component renders the conversation transcript with character-by-character typewriter reveal animation, markdown rendering (bold, italic, links, code blocks), auto-scroll, and artifact placeholders.

## Props

```typescript
let { onArtifactClick }: { onArtifactClick?: (id: string) => void } = $props();
```

**Purpose:** Callback for artifact card clicks.

## State Variables

```typescript
let container: HTMLDivElement;
let revealTimers = new Map<number, ReturnType<typeof setInterval>>();
let copiedBlockId: string | null = $state(null);
let now = $state(Date.now());
```

**Purpose:**
- `container`: Scroll container reference
- `revealTimers`: Active reveal timers by message ID
- `copiedBlockId`: Currently copied code block ID
- `now`: Current time for relative timestamps

## Constants

```typescript
const REVEAL_RATE = 24;         // Characters per tick
const REVEAL_INTERVAL = 33;     // Milliseconds per tick (~30fps)
```

**Reveal speed:** 24 chars × 30 ticks = 720 characters/second

## Character Reveal Animation

### startReveal

```typescript
function startReveal(msg: Message) {
  if (msg.complete || revealTimers.has(msg.id)) return;

  const timer = setInterval(() => {
    if (!revealTimers.has(msg.id)) return;
    if (msg.revealed < msg.content.length) {
      msg.revealed = Math.min(msg.revealed + REVEAL_RATE, msg.content.length);
    }
    if (msg.revealed >= msg.content.length) {
      clearInterval(timer);
      revealTimers.delete(msg.id);
    }
  }, REVEAL_INTERVAL);
  revealTimers.set(msg.id, timer);
}
```

**Purpose:** Start character reveal for agent message.

**Behavior:**
- Reveals 24 characters every 33ms
- Stops when fully revealed
- Cleans up timer on completion

## Auto-Scroll

```typescript
let scrollRafPending = false;

function scrollToBottom() {
  if (!transcript.autoScroll || !container) return;
  if (scrollRafPending) return;
  scrollRafPending = true;
  requestAnimationFrame(() => {
    scrollRafPending = false;
    if (container) container.scrollTop = container.scrollHeight;
  });
}
```

**Purpose:** Scroll to bottom on new messages (throttled to RAF).

**Auto-scroll toggle:** User can disable by scrolling up.

### onScroll

```typescript
function onScroll() {
  if (!container) return;
  const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;
  transcript.autoScroll = atBottom;
}
```

**Purpose:** Detect if user scrolled to bottom (within 40px threshold).

## Message Watch Effect

```typescript
$effect(() => {
  const msgs = transcript.messages;

  // Transcript cleared (agent switch) - cancel orphaned timers
  if (msgs.length === 0) {
    for (const timer of revealTimers.values()) clearInterval(timer);
    revealTimers.clear();
    return;
  }

  const last = msgs[msgs.length - 1];
  if (last.role === 'agent' && !last.complete) {
    startReveal(last);
  }
  scrollToBottom();
});
```

**Purpose:**
1. Clear timers on transcript clear
2. Start reveal for incomplete agent messages
3. Auto-scroll to bottom

## Markdown Rendering

### renderMarkdown

```typescript
function renderMarkdown(text: string): string {
  // Extract fenced code blocks first
  const codeBlocks: { id: string; lang: string; code: string }[] = [];
  let blockIdx = 0;

  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_match, lang, code) => {
    const id = `cb-${simpleHash(code)}-${blockIdx++}`;
    codeBlocks.push({ id, lang: lang || '', code: code.replace(/\n$/, '') });
    return `\x00CODEBLOCK:${id}\x00`;
  });

  // Escape HTML
  text = escapeHtml(text);

  // Inline code
  text = text.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

  // Bold
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Italic
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Links
  text = text.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (_match, linkText, href) => {
      if (/^https?:\/\//i.test(href)) {
        return `<a href="${href}" target="_blank" rel="noopener" class="md-link">${linkText}</a>`;
      }
      return `${linkText} (${href})`;
    }
  );

  // Bare URLs
  text = text.replace(
    /(?<!")(?<!=)(?<!>)(https?:\/\/[^\s<&]+)/g,
    '<a href="$1" target="_blank" rel="noopener" class="md-link">$1</a>'
  );

  // Line-based syntax (lists, blockquotes)
  // ...
}
```

**Processing order:**
1. Extract code blocks (protect from other processing)
2. Escape HTML
3. Inline code
4. Bold
5. Italic
6. Links (markdown and bare URLs)
7. Line-based syntax (lists, blockquotes, horizontal rules)

### Code Block Rendering

```typescript
function renderCodeBlock(block: { id: string; lang: string; code: string }): string {
  const escapedCode = escapeHtml(block.code);
  const langLabel = block.lang ? `<span class="code-lang">${escapeHtml(block.lang)}</span>` : '';
  
  return `
    <div class="code-block" data-block-id="${block.id}">
      <div class="code-header">
        ${langLabel}
        <button class="copy-btn" onclick="copyCode('${block.id}')">Copy</button>
      </div>
      <pre><code>${escapedCode}</code></pre>
    </div>
  `;
}
```

**Features:**
- Language label
- Copy button
- Syntax highlighting ready (via CSS)

### copyCode

```typescript
async function copyCode(blockId: string) {
  const block = codeBlocks.find(b => b.id === blockId);
  if (!block) return;

  try {
    await navigator.clipboard.writeText(block.code);
    copiedBlockId = blockId;
    setTimeout(() => {
      copiedBlockId = null;
    }, 2000);
  } catch {
    // Fallback
  }
}
```

**Purpose:** Copy code block to clipboard.

**Feedback:** Shows "Copied!" for 2 seconds.

## Timestamp Formatting

```typescript
function formatRelativeTime(timestamp: number): string {
  const diff = now - timestamp;
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return 'just now';
}
```

**Updates:** Every 30 seconds via timestamp timer.

## Template Structure

```svelte
<div class="transcript" bind:this={container} on:scroll={onScroll}>
  {#each transcript.messages as msg (msg.id)}
    <div class="message message-{msg.role}" data-id={msg.id}>
      <!-- Role label -->
      {#if msg.role !== 'divider'}
        <div class="message-role">
          {msg.role === 'user' ? settings.userName : agents.displayName}
        </div>
      {/if}

      <!-- Content -->
      <div class="message-content">
        {#if msg.role === 'divider'}
          <div class="divider-text">{msg.content}</div>
        {:else}
          {@html renderMarkdown(msg.content.slice(0, msg.revealed))}
        {/if}
      </div>

      <!-- Timestamp -->
      <div class="message-time">{formatRelativeTime(msg.timestamp)}</div>
    </div>
  {/each}

  <!-- Thinking indicator -->
  {#if session.inferenceState === 'thinking'}
    <ThinkingIndicator />
  {/if}
</div>
```

## Styling

```css
.transcript {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  scroll-behavior: smooth;
}

.message {
  margin-bottom: 24px;
  max-width: 85%;
}

.message-user {
  margin-left: auto;
  text-align: right;
}

.message-agent {
  margin-right: auto;
}

.message-role {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 4px;
}

.message-content {
  line-height: 1.6;
  color: var(--text-primary);
}

.code-block {
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  margin: 12px 0;
  overflow: hidden;
}

.code-header {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.2);
  font-size: 12px;
}

.copy-btn {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
}

.copy-btn:hover {
  color: var(--text-primary);
}
```

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/stores/transcript.svelte.ts` - Message store
- `src/renderer/stores/artifacts.svelte.ts` - Artifact store
- `src/renderer/components/ThinkingIndicator.svelte` - Thinking indicator

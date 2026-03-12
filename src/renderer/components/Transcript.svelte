<script lang="ts">
  import { transcript, type Message } from '../stores/transcript.svelte';
  import { onMount, tick } from 'svelte';

  let container: HTMLDivElement;
  let revealTimers = new Map<number, ReturnType<typeof setInterval>>();
  let copiedBlockId: string | null = $state(null);
  let now = $state(Date.now());

  // Update relative timestamps every 30s
  let timestampTimer: ReturnType<typeof setInterval>;

  // Character reveal animation - 8 chars per 25ms tick
  const REVEAL_RATE = 8;
  const REVEAL_INTERVAL = 25;

  function startReveal(msg: Message) {
    if (msg.complete || revealTimers.has(msg.id)) return;

    const timer = setInterval(() => {
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

  // Auto-scroll to bottom
  async function scrollToBottom() {
    if (!transcript.autoScroll || !container) return;
    await tick();
    container.scrollTop = container.scrollHeight;
  }

  // Watch for new messages
  $effect(() => {
    const msgs = transcript.messages;
    if (msgs.length === 0) return;

    const last = msgs[msgs.length - 1];
    if (last.role === 'agent' && !last.complete) {
      startReveal(last);
    }
    scrollToBottom();
  });

  function onScroll() {
    if (!container) return;
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;
    transcript.autoScroll = atBottom;
  }

  // ---- Markdown rendering ----

  function escapeHtml(str: string): string {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  let codeBlockCounter = 0;

  function renderMarkdown(text: string): string {
    // Extract fenced code blocks first to protect them from other processing
    const codeBlocks: { id: string; lang: string; code: string }[] = [];

    text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_match, lang: string, code: string) => {
      const id = `codeblock-${codeBlockCounter++}`;
      codeBlocks.push({ id, lang: lang || '', code: code.replace(/\n$/, '') });
      return `\x00CODEBLOCK:${id}\x00`;
    });

    // Escape HTML in remaining text
    text = escapeHtml(text);

    // Inline code (must come before bold/italic)
    text = text.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

    // Bold
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Italic
    text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Links [text](url) - only allow http(s) schemes
    text = text.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      (_match: string, linkText: string, href: string) => {
        if (/^https?:\/\//i.test(href)) {
          return `<a href="${href}" target="_blank" rel="noopener" class="md-link">${linkText}</a>`;
        }
        return `${linkText} (${href})`;
      }
    );

    // Bare URLs - match http(s) URLs not already inside an href or tag
    text = text.replace(
      /(?<!")(?<!=)(https?:\/\/[^\s<&]+)/g,
      '<a href="$1" target="_blank" rel="noopener" class="md-link">$1</a>'
    );

    // Process line-based syntax
    const lines = text.split('\n');
    const processed: string[] = [];
    let listTag: 'ul' | 'ol' | null = null;

    function closeList() {
      if (listTag) { processed.push(`</${listTag}>`); listTag = null; }
    }

    for (let i = 0; i < lines.length; i++) {
      let line = lines[i];

      // Check for code block placeholder
      const codeMatch = line.match(/\x00CODEBLOCK:(codeblock-\d+)\x00/);
      if (codeMatch) {
        closeList();
        const block = codeBlocks.find(b => b.id === codeMatch[1]);
        if (block) {
          const escapedCode = escapeHtml(block.code);
          const langLabel = block.lang ? `<span class="code-lang">${escapeHtml(block.lang)}</span>` : '';
          processed.push(
            `<div class="code-block-wrapper" data-code-id="${block.id}">` +
            `<div class="code-block-header">${langLabel}<button class="copy-btn" data-copy-target="${block.id}">Copy</button></div>` +
            `<pre class="code-block"><code>${escapedCode}</code></pre>` +
            `</div>`
          );
        }
        continue;
      }

      // Headers
      const headerMatch = line.match(/^(#{1,6})\s+(.+)/);
      if (headerMatch) {
        closeList();
        const level = headerMatch[1].length;
        processed.push(`<h${level} class="md-header md-h${level}">${headerMatch[2]}</h${level}>`);
        continue;
      }

      // Blockquotes
      if (line.match(/^&gt;\s?/)) {
        closeList();
        const quoteText = line.replace(/^&gt;\s?/, '');
        processed.push(`<blockquote class="md-blockquote">${quoteText}</blockquote>`);
        continue;
      }

      // Unordered list items
      const listMatch = line.match(/^[-*]\s+(.+)/);
      if (listMatch) {
        if (listTag !== 'ul') { closeList(); processed.push('<ul class="md-list">'); listTag = 'ul'; }
        processed.push(`<li>${listMatch[1]}</li>`);
        continue;
      }

      // Ordered list items
      const olMatch = line.match(/^\d+\.\s+(.+)/);
      if (olMatch) {
        if (listTag !== 'ol') { closeList(); processed.push('<ol class="md-list md-ol">'); listTag = 'ol'; }
        processed.push(`<li>${olMatch[1]}</li>`);
        continue;
      }

      // End list if we hit a non-list line
      closeList();

      processed.push(line);
    }

    closeList();

    return processed.join('\n');
  }

  // Filter display text: strip prosody tags, audio tags
  function displayText(content: string, revealed: number): string {
    let text = content.slice(0, revealed);
    // Strip [prosody] tags (including multi-word tags like [voice breaking])
    text = text.replace(/\[[^\]]+\]/g, '');
    // Strip audio tags
    text = text.replace(/<audio[^>]*>.*?<\/audio>/gs, '');
    // Collapse multiple spaces
    text = text.replace(/ {2,}/g, ' ');
    return text.trim();
  }

  function renderMessage(msg: Message): string {
    const text = displayText(msg.content, msg.revealed);
    if (msg.role === 'agent') {
      return renderMarkdown(text);
    }
    // User messages: escape HTML and linkify URLs
    let escaped = escapeHtml(text);
    escaped = escaped.replace(
      /(https?:\/\/[^\s<&]+)/g,
      '<a href="$1" target="_blank" rel="noopener" class="md-link">$1</a>'
    );
    return escaped;
  }

  // Relative time formatting
  function relativeTime(ts: number, currentNow: number): string {
    const diff = currentNow - ts;
    const seconds = Math.floor(diff / 1000);
    if (seconds < 10) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    // Fall back to short time format
    const d = new Date(ts);
    return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  }

  // Copy code block content
  async function handleCopyClick(e: MouseEvent) {
    const target = e.target as HTMLElement;
    const btn = target.closest('.copy-btn') as HTMLElement | null;
    if (!btn) return;

    const codeId = btn.dataset.copyTarget;
    if (!codeId) return;

    const wrapper = container.querySelector(`[data-code-id="${codeId}"]`);
    if (!wrapper) return;

    const codeEl = wrapper.querySelector('code');
    if (!codeEl) return;

    try {
      await navigator.clipboard.writeText(codeEl.textContent || '');
      copiedBlockId = codeId;
      setTimeout(() => {
        if (copiedBlockId === codeId) copiedBlockId = null;
      }, 1500);
    } catch {
      // Clipboard write failed silently
    }
  }

  // Update copy button text reactively
  $effect(() => {
    if (!container) return;
    const buttons = container.querySelectorAll('.copy-btn');
    buttons.forEach((btn) => {
      const el = btn as HTMLElement;
      const id = el.dataset.copyTarget;
      el.textContent = id === copiedBlockId ? 'Copied' : 'Copy';
    });
  });

  onMount(() => {
    timestampTimer = setInterval(() => { now = Date.now(); }, 30000);
    return () => {
      for (const timer of revealTimers.values()) clearInterval(timer);
      revealTimers.clear();
      clearInterval(timestampTimer);
    };
  });
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="transcript selectable" data-no-drag bind:this={container} onscroll={onScroll} onclick={handleCopyClick}>
  <div class="transcript-inner">
    {#each transcript.messages as msg (msg.id)}
      {#if msg.role === 'divider'}
        <div class="divider">
          <span class="divider-text">{msg.content}</span>
        </div>
      {:else}
        <div class="message {msg.role}">
          <div class="message-text">{@html renderMessage(msg)}</div>
          <span class="message-time">{relativeTime(msg.timestamp, now)}</span>
        </div>
      {/if}
    {/each}
  </div>
</div>

<style>
  .transcript {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 8px var(--pad);
    position: relative;
    z-index: 5;
    max-width: 700px;
    margin: 0 auto;
    width: 100%;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    mask-image: linear-gradient(to bottom, transparent 0%, rgba(0, 0, 0, 0.3) 15%, black 33%);
    -webkit-mask-image: linear-gradient(to bottom, transparent 0%, rgba(0, 0, 0, 0.3) 15%, black 33%);
  }

  .transcript-inner {
    flex-shrink: 0;
  }

  .message {
    margin-bottom: 14px;
    position: relative;
  }

  .message + .message:not(.divider) {
    margin-top: 0;
  }

  .message.user + .message.agent,
  .message.agent + .message.user {
    margin-top: 24px;
  }

  .message-text {
    font-family: var(--font-sans);
    font-size: 14px;
    line-height: 1.65;
    white-space: pre-wrap;
    word-break: break-word;
    text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.5);
  }

  .message.user .message-text {
    color: var(--text-user);
  }

  .message.agent .message-text {
    color: var(--text-companion);
  }

  /* Timestamp */
  .message-time {
    display: block;
    font-size: 10px;
    color: var(--text-dim);
    margin-top: 2px;
    font-family: var(--font-sans);
    opacity: 0;
    transition: opacity 0.2s ease;
  }

  .message:hover .message-time {
    opacity: 1;
  }

  /* Markdown: inline code */
  .message-text :global(.inline-code) {
    font-family: var(--font-mono);
    font-size: 12.5px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 1px 5px;
  }

  /* Markdown: code blocks */
  .message-text :global(.code-block-wrapper) {
    position: relative;
    margin: 8px 0;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid var(--border);
    background: rgba(0, 0, 0, 0.35);
  }

  .message-text :global(.code-block-header) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 4px 10px;
    background: rgba(255, 255, 255, 0.04);
    border-bottom: 1px solid var(--border);
    min-height: 28px;
  }

  .message-text :global(.code-lang) {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .message-text :global(.copy-btn) {
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--text-secondary);
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 2px 8px;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
  }

  .message-text :global(.copy-btn:hover) {
    color: var(--text-primary);
    border-color: var(--text-secondary);
  }

  .message-text :global(.code-block) {
    font-family: var(--font-mono);
    font-size: 12.5px;
    line-height: 1.5;
    padding: 10px 12px;
    margin: 0;
    overflow-x: auto;
    white-space: pre;
    color: var(--text-primary);
  }

  .message-text :global(.code-block code) {
    font-family: inherit;
    font-size: inherit;
    background: none;
    border: none;
    padding: 0;
  }

  /* Markdown: headers */
  .message-text :global(.md-header) {
    margin: 12px 0 4px;
    line-height: 1.3;
    color: var(--text-primary);
  }

  .message-text :global(.md-h1) { font-size: 18px; }
  .message-text :global(.md-h2) { font-size: 16px; }
  .message-text :global(.md-h3) { font-size: 15px; }
  .message-text :global(.md-h4),
  .message-text :global(.md-h5),
  .message-text :global(.md-h6) { font-size: 14px; }

  /* Markdown: blockquotes */
  .message-text :global(.md-blockquote) {
    border-left: 3px solid var(--border);
    padding: 2px 0 2px 12px;
    margin: 6px 0;
    color: var(--text-secondary);
    font-style: italic;
  }

  /* Markdown: lists */
  .message-text :global(.md-list) {
    margin: 4px 0;
    padding-left: 20px;
  }

  .message-text :global(.md-list li) {
    margin: 2px 0;
  }

  .message-text :global(.md-ol) {
    list-style-type: decimal;
  }

  /* Markdown: links */
  .message-text :global(.md-link) {
    color: var(--accent-hover);
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: border-color 0.15s;
  }

  .message-text :global(.md-link:hover) {
    border-bottom-color: var(--accent-hover);
  }

  /* Markdown: bold/italic */
  .message-text :global(strong) {
    font-weight: 600;
    color: var(--text-primary);
  }

  .message-text :global(em) {
    font-style: italic;
  }

  .divider {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px 0;
  }

  .divider-text {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 3px;
    color: var(--divider-green);
    border-top: 1px solid var(--divider-green);
    border-bottom: 1px solid var(--divider-green);
    padding: 4px 12px;
  }
</style>

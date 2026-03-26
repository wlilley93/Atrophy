<script lang="ts">
  import { transcript, type Message } from '../stores/transcript.svelte';
  import { session } from '../stores/session.svelte';
  import { getArtifact } from '../stores/artifacts.svelte';
  import { onMount, tick } from 'svelte';
  import ThinkingIndicator from './ThinkingIndicator.svelte';

  let { onArtifactClick }: { onArtifactClick?: (id: string) => void } = $props();

  let container: HTMLDivElement;
  let revealTimers = new Map<number, ReturnType<typeof setInterval>>();
  let copiedBlockId: string | null = $state(null);
  let now = $state(Date.now());

  // Update relative timestamps every 30s
  let timestampTimer: ReturnType<typeof setInterval>;

  // Character reveal animation - 24 chars per 33ms tick (~30fps, 3x faster reveal)
  const REVEAL_RATE = 24;
  const REVEAL_INTERVAL = 33;

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

    // Transcript was cleared (agent switch) - cancel all orphaned reveal timers
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

  function simpleHash(s: string): string {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return (h >>> 0).toString(36);
  }

  function renderMarkdown(text: string): string {
    // Extract fenced code blocks first to protect them from other processing
    const codeBlocks: { id: string; lang: string; code: string }[] = [];
    let blockIdx = 0;

    text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_match, lang: string, code: string) => {
      // Use content hash so the ID is stable across re-renders during streaming
      const id = `cb-${simpleHash(code)}-${blockIdx++}`;
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

    // Bare URLs - match http(s) URLs not already inside an href attribute or anchor tag text
    text = text.replace(
      /(?<!")(?<!=)(?<!>)(https?:\/\/[^\s<&]+)/g,
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
      const codeMatch = line.match(/\x00CODEBLOCK:(cb-[\w]+-\d+)\x00/);
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

    let result = processed.join('\n');

    // Replace [[artifact:id]] placeholders with clickable cards
    result = result.replace(/\[\[artifact:([^\]]+)\]\]/g, (_match, id: string) => {
      const art = getArtifact(id);
      const title = art ? escapeHtml(art.title) : id;
      const typeLabel = art ? escapeHtml(art.type.toUpperCase()) : 'ARTIFACT';
      const langLabel = art?.language ? escapeHtml(art.language) : '';
      return (
        `<button class="artifact-card" data-artifact-id="${escapeHtml(id)}">` +
        `<span class="artifact-card-type">${typeLabel}</span>` +
        `<span class="artifact-card-title">${title}</span>` +
        (langLabel ? `<span class="artifact-card-lang">${langLabel}</span>` : '') +
        `</button>`
      );
    });

    return result;
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

  // Memoize rendered markdown to avoid re-parsing on every reactive update
  const renderCache = new Map<string, { key: string; html: string }>();

  function renderMessage(msg: Message): string {
    const text = displayText(msg.content, msg.revealed);
    const cacheKey = `${msg.id}:${msg.revealed}:${msg.complete ? 1 : 0}`;
    const cached = renderCache.get(msg.id);
    if (cached && cached.key === cacheKey) return cached.html;

    let html: string;
    if (msg.role === 'agent') {
      html = renderMarkdown(text);
    } else {
      // User messages: escape HTML and linkify URLs
      let escaped = escapeHtml(text);
      escaped = escaped.replace(
        /(https?:\/\/[^\s<&]+)/g,
        '<a href="$1" target="_blank" rel="noopener" class="md-link">$1</a>'
      );
      html = escaped;
    }

    renderCache.set(msg.id, { key: cacheKey, html });
    // Evict old entries to prevent unbounded growth
    if (renderCache.size > 200) {
      const first = renderCache.keys().next().value;
      if (first) renderCache.delete(first);
    }
    return html;
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

  // Handle clicks on transcript elements (copy buttons, artifact cards)
  async function handleCopyClick(e: MouseEvent) {
    const target = e.target as HTMLElement;

    // Artifact card click
    const artCard = target.closest('.artifact-card') as HTMLElement | null;
    if (artCard) {
      const artId = artCard.dataset.artifactId;
      if (artId && onArtifactClick) onArtifactClick(artId);
      return;
    }

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
    {#each transcript.messages as msg, i (msg.id)}
      {#if msg.role === 'divider'}
        <div class="divider">
          <span class="divider-text">{msg.content}</span>
        </div>
      {:else}
        {#if msg.role === 'agent' && !msg.content && session.inferenceState !== 'idle' && i === transcript.messages.length - 1}
          <!-- Brain cycling indicator while waiting for first token -->
          <div class="thinking-row">
            <ThinkingIndicator />
          </div>
        {:else}
          <div class="message {msg.role}">
            <div class="message-text">{@html renderMessage(msg)}</div>
            <span class="message-time">{relativeTime(msg.timestamp, now)}</span>
          </div>
        {/if}
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
    margin-bottom: 0;
    position: relative;
  }

  /* Within a pair (user -> agent): tight 14px gap */
  .message + .message {
    margin-top: 14px;
  }

  /* Between pairs (agent -> next user): larger 24px gap */
  .message.agent + .message.user {
    margin-top: 24px;
  }

  /* System messages stay tight with their neighbours */
  .message.system + .message {
    margin-top: 14px;
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

  .message.system .message-text {
    color: var(--text-dim);
    font-size: 12px;
    font-style: italic;
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

  .thinking-row {
    margin-bottom: 0;
    margin-top: 14px;
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

  /* Inline artifact cards */
  .message-text :global(.artifact-card) {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px;
    margin: 6px 0;
    background: rgba(74, 158, 255, 0.08);
    border: 1px solid rgba(74, 158, 255, 0.25);
    border-radius: 8px;
    cursor: pointer;
    font-family: var(--font-sans);
    transition: background 0.15s, border-color 0.15s;
    white-space: normal;
    text-align: left;
    color: var(--text-primary);
  }

  .message-text :global(.artifact-card:hover) {
    background: rgba(74, 158, 255, 0.14);
    border-color: rgba(74, 158, 255, 0.4);
  }

  .message-text :global(.artifact-card-type) {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1px;
    color: #4a9eff;
    background: rgba(74, 158, 255, 0.15);
    border-radius: 4px;
    padding: 2px 6px;
    flex-shrink: 0;
  }

  .message-text :global(.artifact-card-title) {
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
  }

  .message-text :global(.artifact-card-lang) {
    font-size: 10px;
    color: var(--text-dim);
    margin-left: auto;
    flex-shrink: 0;
  }
</style>

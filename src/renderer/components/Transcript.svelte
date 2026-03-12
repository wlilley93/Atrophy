<script lang="ts">
  import { transcript, type Message } from '../stores/transcript.svelte';
  import { onMount, tick } from 'svelte';

  let container: HTMLDivElement;
  let revealTimers = new Map<number, ReturnType<typeof setInterval>>();

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

  // Filter display text: strip prosody tags, audio tags, code fences
  function displayText(content: string, revealed: number): string {
    let text = content.slice(0, revealed);
    // Strip [prosody] tags
    text = text.replace(/\[[\w_]+\]/g, '');
    // Strip audio tags
    text = text.replace(/<audio[^>]*>.*?<\/audio>/gs, '');
    // Collapse multiple spaces
    text = text.replace(/ {2,}/g, ' ');
    return text.trim();
  }

  onMount(() => {
    return () => {
      for (const timer of revealTimers.values()) clearInterval(timer);
      revealTimers.clear();
    };
  });
</script>

<div class="transcript selectable" data-no-drag bind:this={container} onscroll={onScroll}>
  {#each transcript.messages as msg (msg.id)}
    {#if msg.role === 'divider'}
      <div class="divider">
        <span class="divider-text">{msg.content}</span>
      </div>
    {:else}
      <div class="message {msg.role}">
        <p class="message-text">{displayText(msg.content, msg.revealed)}</p>
      </div>
    {/if}
  {/each}
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
  }

  .message {
    margin-bottom: 14px;
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

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

  interface Props {
    onClose: () => void;
    onRequestShow?: () => void;
  }

  let { onClose, onRequestShow }: Props = $props();

  const api = (window as any).atrophy;

  let url = $state('');
  let visible = $state(false);

  // Debounce timer for rapid updates
  let refreshTimer: ReturnType<typeof setTimeout> | null = null;

  // Fade in on mount
  onMount(() => {
    requestAnimationFrame(() => {
      visible = true;
    });

    // Listen for canvas file updates from main process
    if (api && typeof api.on === 'function') {
      const cleanup = api.on('canvas:updated', (newUrl: string) => {
        debouncedRefresh(newUrl);
      });
      cleanups.push(cleanup);
    }
  });

  let cleanups: (() => void)[] = [];

  onDestroy(() => {
    if (refreshTimer) clearTimeout(refreshTimer);
    cleanups.forEach(fn => fn());
  });

  function debouncedRefresh(newUrl: string) {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
      url = newUrl;
      // Auto-show when content is written
      if (onRequestShow) {
        onRequestShow();
      }
    }, 100);
  }

  function handleClose() {
    visible = false;
    setTimeout(() => {
      onClose();
    }, 300);
  }
</script>

<div
  class="canvas-overlay"
  class:visible
  data-no-drag
>
  <button class="close-btn" onclick={handleClose} aria-label="Close canvas">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  </button>

  <div class="canvas-pip">
    {#if url}
      <webview src={url} class="canvas-webview" partition="persist:canvas"></webview>
    {:else}
      <div class="canvas-empty">
        <p>No canvas content</p>
        <p class="hint">Content will appear here when the agent creates it</p>
      </div>
    {/if}
  </div>
</div>

<style>
  .canvas-overlay {
    position: absolute;
    inset: 0;
    z-index: 45;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: flex-end;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.3s ease;
  }

  .canvas-overlay.visible {
    opacity: 1;
  }

  .canvas-pip {
    position: relative;
    width: 55%;
    height: 50%;
    margin: 0 16px 16px 0;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--border);
    background: rgba(12, 12, 14, 0.95);
    backdrop-filter: blur(20px);
    pointer-events: auto;
    transform: translateX(100%);
    transition: transform 0.3s ease-out;
  }

  .canvas-overlay.visible .canvas-pip {
    transform: translateX(0);
  }

  .close-btn {
    position: absolute;
    bottom: calc(50% + 16px + 8px);
    right: 24px;
    z-index: 2;
    background: rgba(0, 0, 0, 0.5);
    border: none;
    color: var(--text-dim);
    cursor: pointer;
    padding: 4px;
    border-radius: 14px;
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: auto;
    transition: color 0.15s, background 0.15s;
  }

  .close-btn:hover {
    color: white;
    background: rgba(180, 80, 80, 0.8);
  }

  .canvas-webview {
    width: 100%;
    height: 100%;
  }

  .canvas-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-dim);
    font-size: 14px;
  }

  .hint {
    font-size: 12px;
    margin-top: 8px;
    opacity: 0.6;
  }
</style>

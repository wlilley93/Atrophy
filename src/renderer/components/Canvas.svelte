<script lang="ts">
  interface Props {
    onClose: () => void;
  }

  let { onClose }: Props = $props();

  let url = $state('');
</script>

<div class="canvas-overlay" data-no-drag>
  <button class="close-btn" onclick={onClose}>
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  </button>

  <div class="canvas-content">
    {#if url}
      <webview src={url} class="canvas-webview"></webview>
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
    background: rgba(12, 12, 14, 0.95);
    backdrop-filter: blur(20px);
  }

  .close-btn {
    position: absolute;
    top: var(--pad);
    right: var(--pad);
    z-index: 2;
    background: none;
    border: none;
    color: var(--text-dim);
    cursor: pointer;
    padding: 4px;
  }

  .close-btn:hover {
    color: var(--text-secondary);
  }

  .canvas-content {
    flex: 1;
    margin: 60px var(--pad) var(--pad);
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--border);
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

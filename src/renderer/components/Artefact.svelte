<script lang="ts">
  interface Props {
    onClose: () => void;
  }

  let { onClose }: Props = $props();

  // Artefact display state - will be populated via IPC
  let content = $state('');
  let contentType = $state('html'); // html, markdown, code, svg
  let gallery = $state<{ id: number; title: string; type: string }[]>([]);
  let showGallery = $state(false);
</script>

<div class="artefact-overlay" data-no-drag>
  <div class="artefact-header">
    <button class="gallery-btn" onclick={() => showGallery = !showGallery}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
        <rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
      </svg>
    </button>

    <button class="close-btn" onclick={onClose}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
      </svg>
    </button>
  </div>

  <div class="artefact-content">
    {#if content}
      {#if contentType === 'html' || contentType === 'svg'}
        {@html content}
      {:else}
        <pre class="artefact-code">{content}</pre>
      {/if}
    {:else}
      <div class="artefact-empty">
        <p>No artefact to display</p>
      </div>
    {/if}
  </div>

  {#if showGallery}
    <div class="gallery-panel">
      <div class="gallery-header section-header">Artefacts</div>
      {#each gallery as item (item.id)}
        <button class="gallery-item">
          <span class="gallery-type">{item.type}</span>
          <span class="gallery-title">{item.title}</span>
        </button>
      {/each}
      {#if gallery.length === 0}
        <p class="gallery-empty">No artefacts yet</p>
      {/if}
    </div>
  {/if}
</div>

<style>
  .artefact-overlay {
    position: absolute;
    inset: 0;
    z-index: 40;
    display: flex;
    flex-direction: column;
    background: rgba(12, 12, 14, 0.96);
    backdrop-filter: blur(20px);
  }

  .artefact-header {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 8px;
    padding: var(--pad);
  }

  .close-btn, .gallery-btn {
    background: none;
    border: none;
    color: var(--text-dim);
    cursor: pointer;
    padding: 4px;
  }

  .close-btn:hover, .gallery-btn:hover {
    color: var(--text-secondary);
  }

  .artefact-content {
    flex: 1;
    overflow: auto;
    padding: 0 var(--pad) var(--pad);
    color: var(--text-primary);
  }

  .artefact-code {
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .artefact-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-dim);
  }

  .gallery-panel {
    position: absolute;
    left: var(--pad);
    top: 60px;
    bottom: var(--pad);
    width: 240px;
    background: rgba(20, 20, 24, 0.95);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    overflow-y: auto;
  }

  .gallery-header {
    margin-bottom: 16px;
  }

  .gallery-item {
    display: flex;
    flex-direction: column;
    width: 100%;
    padding: 10px 12px;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-primary);
    cursor: pointer;
    text-align: left;
    margin-bottom: 6px;
    transition: border-color 0.15s;
  }

  .gallery-item:hover {
    border-color: var(--border-hover);
  }

  .gallery-type {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text-dim);
  }

  .gallery-title {
    font-size: 13px;
    margin-top: 2px;
  }

  .gallery-empty {
    color: var(--text-dim);
    font-size: 12px;
    text-align: center;
    padding: 20px 0;
  }
</style>

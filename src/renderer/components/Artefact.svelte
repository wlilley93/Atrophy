<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

  interface Props {
    onClose: () => void;
  }

  import { api } from '../api';

  let { onClose }: Props = $props();

  // Artefact display state
  let content = $state('');
  let contentType = $state<'html' | 'svg' | 'code' | 'markdown' | 'image' | 'video'>('html');
  let contentSrc = $state(''); // file:// URL for image/video
  let visible = $state(false);

  // Gallery state
  interface GalleryItem {
    name: string;
    title?: string;
    type: string;
    description?: string;
    path?: string;
    file?: string;
    created_at?: string;
  }
  let gallery = $state<GalleryItem[]>([]);
  let showGallery = $state(false);
  let searchQuery = $state('');
  let activeFilter = $state('all');

  // Loading state
  let loadingName = $state('');

  // Webview/iframe ref for memory cleanup
  let iframeRef = $state<HTMLIFrameElement | null>(null);

  const FILTER_OPTIONS = ['All', 'HTML', 'Code', 'Image', 'Video'] as const;
  const BADGE_COLORS: Record<string, string> = {
    html: '#4a9eff',
    svg: '#4a9eff',
    code: '#a8e6a1',
    markdown: '#a8e6a1',
    image: '#ff6b9d',
    video: '#9b59b6',
  };

  // Fade in on mount
  onMount(() => {
    requestAnimationFrame(() => {
      visible = true;
    });

    // Handle window resize
    window.addEventListener('resize', handleResize);

    // Listen for artefact updates (from main process polling .artefact_display.json)
    if (api && typeof api.on === 'function') {
      const cleanup = api.on('artefact:updated', (data: {
        type: string;
        content?: string;
        src?: string;
        title?: string;
        description?: string;
      }) => {
        loadingName = '';
        loadArtefact(data);
        // Refresh gallery after new artefact
        refreshGallery();
      });
      cleanups.push(cleanup);

      // Listen for loading state
      const loadingCleanup = api.on('artefact:loading', (data: { name: string; type: string }) => {
        loadingName = data.name || 'artefact';
      });
      cleanups.push(loadingCleanup);
    }

    // Listen for inline artifact clicks (from transcript card clicks)
    const handleInlineArtifact = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail) {
        loadingName = '';
        loadArtefact(detail);
      }
    };
    window.addEventListener('inline-artifact', handleInlineArtifact);
    cleanups.push(() => window.removeEventListener('inline-artifact', handleInlineArtifact));

    // Load gallery on mount
    refreshGallery();
  });

  let cleanups: (() => void)[] = [];

  onDestroy(() => {
    window.removeEventListener('resize', handleResize);
    cleanups.forEach(fn => fn());
    // Memory cleanup - clear any iframe/webview content
    clearContent();
  });

  function handleResize() {
    // Force Svelte reactivity update for layout recalculation
    // The CSS handles actual sizing, this just ensures re-render if needed
  }

  function loadArtefact(data: {
    type: string;
    content?: string;
    src?: string;
    title?: string;
    description?: string;
  }) {
    contentType = (data.type || 'html') as typeof contentType;
    content = data.content || '';
    contentSrc = data.src || '';
  }

  function clearContent() {
    content = '';
    contentSrc = '';
    if (iframeRef) {
      iframeRef.srcdoc = '';
      iframeRef.src = 'about:blank';
    }
  }

  function handleClose() {
    visible = false;
    clearContent();
    setTimeout(() => {
      onClose();
    }, 300);
  }

  async function refreshGallery() {
    if (!api?.getArtefactGallery) return;
    try {
      const items = await api.getArtefactGallery();
      gallery = (items as GalleryItem[]).map((item, i) => ({
        ...item,
        title: item.title || item.name || `Artefact ${i + 1}`,
      }));
    } catch { /* gallery unavailable */ }
  }

  async function selectGalleryItem(item: GalleryItem) {
    showGallery = false;

    const aType = (item.type || 'html') as typeof contentType;
    contentType = aType;

    if (aType === 'html' && item.file && api?.getArtefactContent) {
      // Load HTML content from file
      const html = await api.getArtefactContent(item.file);
      content = html || '';
      contentSrc = '';
    } else if ((aType === 'image' || aType === 'video') && item.file) {
      content = '';
      contentSrc = `file://${item.file}`;
    }
  }

  // Filtered + searched gallery items
  let filteredGallery = $derived.by(() => {
    let items = gallery;

    // Apply type filter
    if (activeFilter !== 'all') {
      items = items.filter(item => {
        const t = item.type?.toLowerCase();
        const f = activeFilter.toLowerCase();
        if (f === 'html') return t === 'html' || t === 'svg';
        if (f === 'code') return t === 'code' || t === 'markdown';
        return t === f;
      });
    }

    // Apply search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      items = items.filter(item =>
        (item.title || '').toLowerCase().includes(q) ||
        (item.description || '').toLowerCase().includes(q)
      );
    }

    return items;
  });

  function setFilter(filter: string) {
    activeFilter = filter.toLowerCase();
  }

  function formatDate(dateStr?: string): string {
    if (!dateStr) return '';
    return dateStr.slice(0, 10);
  }

  function formatTitle(title: string): string {
    return title.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }
</script>

<div class="artefact-overlay" class:visible data-no-drag>
  <div class="artefact-header">
    <button class="gallery-btn" onclick={() => showGallery = !showGallery} aria-label="Toggle gallery">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
        <rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
      </svg>
    </button>

    <button class="close-btn" onclick={handleClose} aria-label="Close artefact">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
      </svg>
    </button>
  </div>

  <div class="artefact-content">
    {#if content || contentSrc}
      {#if contentType === 'html' || contentType === 'svg'}
        <iframe
          bind:this={iframeRef}
          srcdoc={content}
          class="artefact-iframe"
          sandbox="allow-scripts"
          title="Artefact content"
        ></iframe>
      {:else if contentType === 'image'}
        <div class="artefact-media">
          <img
            src={contentSrc || `data:image/svg+xml,${encodeURIComponent(content)}`}
            alt="Artefact"
            class="artefact-image"
          />
        </div>
      {:else if contentType === 'video'}
        <div class="artefact-media">
          <video
            src={contentSrc}
            class="artefact-video"
            controls
            autoplay
            loop
          >
            <track kind="captions" />
          </video>
        </div>
      {:else}
        <pre class="artefact-code">{content}</pre>
      {/if}
    {:else if loadingName}
      <div class="artefact-empty">
        <div class="loading-indicator">
          <span class="loading-dot"></span>
          <span>Generating {loadingName}...</span>
        </div>
      </div>
    {:else}
      <div class="artefact-empty">
        <p>No artefact to display</p>
      </div>
    {/if}
  </div>

  {#if showGallery}
    <div class="gallery-panel">
      <div class="gallery-header-row">
        <div class="gallery-title section-header">Artefacts</div>
      </div>

      <!-- Search bar -->
      <div class="gallery-search">
        <input
          type="text"
          placeholder="Search artefacts..."
          bind:value={searchQuery}
          class="search-input"
        />
      </div>

      <!-- Type filter buttons -->
      <div class="filter-row">
        {#each FILTER_OPTIONS as filter}
          <button
            class="filter-btn"
            class:active={activeFilter === filter.toLowerCase()}
            onclick={() => setFilter(filter)}
          >
            {filter}
          </button>
        {/each}
      </div>

      <!-- Artefact cards -->
      <div class="gallery-list">
        {#each filteredGallery as item (item.file || item.name)}
          <button class="gallery-card" onclick={() => selectGalleryItem(item)}>
            <div class="card-top">
              <span
                class="card-badge"
                style="color: {BADGE_COLORS[item.type] || '#888'}"
              >
                {item.type.toUpperCase()}
              </span>
              {#if item.created_at}
                <span class="card-date">{formatDate(item.created_at)}</span>
              {/if}
            </div>
            <span class="card-title">{formatTitle(item.title || item.name)}</span>
            {#if item.description}
              <span class="card-desc">
                {item.description.length > 60
                  ? item.description.slice(0, 60) + '...'
                  : item.description}
              </span>
            {/if}
          </button>
        {/each}
        {#if filteredGallery.length === 0}
          <p class="gallery-empty">
            {searchQuery || activeFilter !== 'all' ? 'No matching artefacts' : 'No artefacts yet'}
          </p>
        {/if}
      </div>
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
    opacity: 0;
    transform: scale(0.98);
    transition: opacity 0.3s ease, transform 0.3s ease;
  }

  .artefact-overlay.visible {
    opacity: 1;
    transform: scale(1);
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
    transition: color 0.15s;
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

  .artefact-iframe {
    width: 100%;
    height: 100%;
    border: none;
    border-radius: 8px;
    background: #141418;
  }

  .artefact-media {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    width: 100%;
  }

  .artefact-image {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 8px;
  }

  .artefact-video {
    /* Never exceed original video dimensions - like watching a vertical
       short on a widescreen. The video stays at its natural size, centered
       in the dark overlay, and only shrinks if the window is smaller. */
    max-width: min(100%, 480px);
    max-height: min(100%, 854px);
    border-radius: 8px;
    object-fit: contain;
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

  /* Gallery panel */

  .gallery-panel {
    position: absolute;
    left: var(--pad);
    top: 60px;
    bottom: var(--pad);
    width: 260px;
    background: rgba(20, 20, 24, 0.95);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .gallery-header-row {
    margin-bottom: 12px;
  }

  .gallery-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    letter-spacing: 0.5px;
  }

  /* Search bar */

  .gallery-search {
    margin-bottom: 10px;
  }

  .search-input {
    width: 100%;
    padding: 7px 10px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-primary);
    font-size: 12px;
    font-family: var(--font-sans);
    outline: none;
    transition: border-color 0.15s;
    box-sizing: border-box;
  }

  .search-input::placeholder {
    color: var(--text-dim);
  }

  .search-input:focus {
    border-color: rgba(255, 255, 255, 0.2);
  }

  /* Filter buttons */

  .filter-row {
    display: flex;
    gap: 4px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }

  .filter-btn {
    padding: 3px 10px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--text-dim);
    font-size: 10px;
    font-family: var(--font-sans);
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }

  .filter-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    color: var(--text-secondary);
  }

  .filter-btn.active {
    background: rgba(255, 255, 255, 0.15);
    color: var(--text-primary);
    border-color: rgba(255, 255, 255, 0.3);
  }

  /* Gallery list */

  .gallery-list {
    flex: 1;
    overflow-y: auto;
  }

  /* Artefact cards */

  .gallery-card {
    display: flex;
    flex-direction: column;
    width: 100%;
    padding: 10px 12px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-primary);
    cursor: pointer;
    text-align: left;
    margin-bottom: 6px;
    transition: background 0.15s, border-color 0.15s;
    font-family: var(--font-sans);
  }

  .gallery-card:hover {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.18);
  }

  .card-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
  }

  .card-badge {
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 1px;
    background: rgba(255, 255, 255, 0.06);
    border-radius: 4px;
    padding: 1px 6px;
  }

  .card-date {
    font-size: 10px;
    color: var(--text-dim);
  }

  .card-title {
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
  }

  .card-desc {
    font-size: 11px;
    color: var(--text-dim);
    margin-top: 2px;
    line-height: 1.4;
  }

  .gallery-empty {
    color: var(--text-dim);
    font-size: 12px;
    text-align: center;
    padding: 20px 0;
  }

  /* Loading indicator */

  .loading-indicator {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--text-secondary);
    font-family: var(--font-sans);
    font-size: 13px;
  }

  .loading-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #4a9eff;
    animation: loadingPulse 1.2s ease-in-out infinite;
  }

  @keyframes loadingPulse {
    0%, 100% { opacity: 0.3; transform: scale(0.8); }
    50% { opacity: 1; transform: scale(1.2); }
  }
</style>

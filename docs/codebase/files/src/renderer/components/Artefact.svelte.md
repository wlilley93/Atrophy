# src/renderer/components/Artefact.svelte - Artefact Viewer

**Line count:** ~617 lines  
**Dependencies:** `svelte`, `../api`  
**Purpose:** Full-screen artefact viewer with gallery, search, and filtering

## Overview

This component displays agent-created artefacts (HTML, SVG, code, images, videos) in a full-screen overlay. It includes a gallery view with search and filtering capabilities.

## Props

```typescript
interface Props {
  onClose: () => void;
}
```

## State Variables

### Artefact Display

```typescript
let content = $state('');
let contentType = $state<'html' | 'svg' | 'code' | 'markdown' | 'image' | 'video'>('html');
let contentSrc = $state('');  // file:// URL for image/video
let visible = $state(false);
```

### Gallery State

```typescript
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
```

### Loading State

```typescript
let loadingName = $state('');
let iframeRef = $state<HTMLIFrameElement | null>(null);
```

### Filter Options

```typescript
const FILTER_OPTIONS = ['All', 'HTML', 'Code', 'Image', 'Video'] as const;
const BADGE_COLORS: Record<string, string> = {
  html: '#4a9eff',
  svg: '#4a9eff',
  code: '#a8e6a1',
  markdown: '#a8e6a1',
  image: '#ff6b9d',
  video: '#9b59b6',
};
```

## Lifecycle

### onMount

```typescript
onMount(() => {
  requestAnimationFrame(() => {
    visible = true;
  });

  // Handle window resize
  window.addEventListener('resize', handleResize);

  // Listen for artefact updates
  if (api && typeof api.on === 'function') {
    const cleanup = api.on('artefact:updated', (data) => {
      loadingName = '';
      loadArtefact(data);
      refreshGallery();
    });
    cleanups.push(cleanup);

    // Listen for loading state
    const loadingCleanup = api.on('artefact:loading', (data) => {
      loadingName = data.name;
    });
    cleanups.push(loadingCleanup);
  }

  // Listen for inline artifact clicks
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
```

**Subscriptions:**
1. `artefact:updated` - New artefact content
2. `artefact:loading` - Loading state indicator
3. `inline-artifact` event - Clicks from transcript cards

### onDestroy

```typescript
onDestroy(() => {
  window.removeEventListener('resize', handleResize);
  cleanups.forEach(fn => fn());
  clearContent();
});
```

**Purpose:** Cleanup subscriptions and iframe content.

## Functions

### loadArtefact

```typescript
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
```

**Purpose:** Load artefact data into display state.

### clearContent

```typescript
function clearContent() {
  content = '';
  contentSrc = '';
  if (iframeRef) {
    iframeRef.srcdoc = '';
    iframeRef.src = 'about:blank';
  }
}
```

**Purpose:** Clear iframe content for memory cleanup.

### handleClose

```typescript
function handleClose() {
  visible = false;
  clearContent();
  setTimeout(() => {
    onClose();
  }, 300);
}
```

**Purpose:** Fade out then close (300ms transition).

### refreshGallery

```typescript
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
```

**Purpose:** Fetch artefact gallery from main process.

### selectGalleryItem

```typescript
async function selectGalleryItem(item: GalleryItem) {
  if (!api?.getArtefactContent) return;
  
  loadingName = item.name;
  try {
    const content = await api.getArtefactContent(item.path || item.file || '');
    loadArtefact({
      type: item.type,
      content: content || undefined,
      title: item.title,
      description: item.description,
    });
    showGallery = false;
  } catch {
    loadingName = '';
  }
}
```

**Purpose:** Load selected gallery item.

### Filtered Gallery

```typescript
$derived(() => {
  const query = searchQuery.toLowerCase();
  return gallery.filter(item => {
    // Type filter
    if (activeFilter !== 'all' && item.type.toLowerCase() !== activeFilter) {
      return false;
    }
    // Search filter
    if (query) {
      const nameMatch = item.name?.toLowerCase().includes(query);
      const titleMatch = item.title?.toLowerCase().includes(query);
      const descMatch = item.description?.toLowerCase().includes(query);
      if (!nameMatch && !titleMatch && !descMatch) return false;
    }
    return true;
  });
})
```

**Filters:**
- Type filter (All, HTML, Code, Image, Video)
- Search query (name, title, description)

## Template Structure

```svelte
<div class="artefact-overlay" class:visible data-no-drag>
  <!-- Close button -->
  <button class="close-btn" onclick={handleClose}>✕</button>

  <!-- Gallery toggle -->
  <button class="gallery-btn" onclick={() => showGallery = !showGallery}>
    📁 Gallery
  </button>

  {#if showGallery}
    <!-- Gallery view -->
    <div class="gallery-view">
      <!-- Search input -->
      <input type="text" bind:value={searchQuery} placeholder="Search artefacts..." />
      
      <!-- Filter tabs -->
      <div class="filter-tabs">
        {#each FILTER_OPTIONS as filter}
          <button 
            class:active={activeFilter === filter.toLowerCase()}
            onclick={() => activeFilter = filter.toLowerCase()}
          >
            {filter}
          </button>
        {/each}
      </div>
      
      <!-- Gallery grid -->
      <div class="gallery-grid">
        {#each filteredGallery as item}
          <div class="gallery-item" onclick={() => selectGalleryItem(item)}>
            <div class="item-badge" style="background: {BADGE_COLORS[item.type]}">
              {item.type}
            </div>
            <h3>{item.title}</h3>
            {#if item.description}
              <p class="item-desc">{item.description}</p>
            {/if}
            {#if item.created_at}
              <p class="item-date">{formatDate(item.created_at)}</p>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {:else}
    <!-- Artefact display -->
    <div class="artefact-content">
      {#if loadingName}
        <div class="loading-state">Loading {loadingName}...</div>
      {:else if contentType === 'html' || contentType === 'svg'}
        <iframe bind:this={iframeRef} srcdoc={content} class="artefact-frame"></iframe>
      {:else if contentType === 'image'}
        <img src={contentSrc} class="artefact-image" />
      {:else if contentType === 'video'}
        <video src={contentSrc} controls class="artefact-video"></video>
      {:else if contentType === 'code'}
        <pre class="artefact-code"><code>{content}</code></pre>
      {/if}
    </div>
  {/if}
</div>
```

## Styling

```css
.artefact-overlay {
  position: absolute;
  inset: 0;
  z-index: 40;
  background: rgba(0, 0, 0, 0.95);
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.artefact-overlay.visible {
  opacity: 1;
  pointer-events: auto;
}

.artefact-content {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.artefact-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: white;
}

.gallery-view {
  padding: 40px;
  overflow-y: auto;
  max-height: 100%;
}

.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
  margin-top: 20px;
}

.gallery-item {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  transition: background 0.2s;
}

.gallery-item:hover {
  background: rgba(255, 255, 255, 0.1);
}

.item-badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  color: white;
  margin-bottom: 12px;
}
```

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/components/Window.svelte` - Parent component
- `src/renderer/stores/artifacts.svelte.ts` - Artifact store
- `src/main/ipc/window.ts` - Artefact IPC handlers

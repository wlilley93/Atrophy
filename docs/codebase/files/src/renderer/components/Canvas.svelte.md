# src/renderer/components/Canvas.svelte - Canvas Overlay

**Line count:** ~167 lines  
**Dependencies:** `svelte`, `../api`  
**Purpose:** Picture-in-picture canvas overlay for agent-created web content

## Overview

This component displays a draggable, resizable picture-in-picture canvas overlay that shows web content created by the agent. It uses a webview element to render external URLs.

## Props

```typescript
interface Props {
  onClose: () => void;
  onRequestShow?: () => void;
}
```

**Purpose:**
- `onClose`: Close handler
- `onRequestShow`: Optional callback when content is written (auto-shows canvas)

## State Variables

```typescript
let url = $state('');
let visible = $state(false);
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let cleanups: (() => void)[] = [];
```

**Purpose:**
- `url`: Current canvas content URL
- `visible`: Visibility state for fade animation
- `refreshTimer`: Debounce timer for rapid updates
- `cleanups`: Cleanup functions for onDestroy

## Lifecycle

### onMount

```typescript
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
```

**Behavior:**
1. Fade in on mount
2. Subscribe to `canvas:updated` IPC events
3. Debounced refresh on URL changes

### onDestroy

```typescript
onDestroy(() => {
  if (refreshTimer) clearTimeout(refreshTimer);
  cleanups.forEach(fn => fn());
  // Clear URL so the webview element is removed and its renderer process released
  url = '';
});
```

**Purpose:** Cleanup timers, subscriptions, and webview renderer process.

## Functions

### debouncedRefresh

```typescript
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
```

**Purpose:** Debounce URL updates (100ms delay).

**Auto-show:** Calls `onRequestShow` when content is written.

### handleClose

```typescript
function handleClose() {
  visible = false;
  setTimeout(() => {
    onClose();
  }, 300);
}
```

**Purpose:** Fade out then close (300ms transition).

## Template

```svelte
<div class="canvas-overlay" class:visible data-no-drag>
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
```

**Structure:**
1. Close button (absolute positioned)
2. Picture-in-picture container
3. WebView (when URL exists) or empty state

## Styling

```css
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
```

**Key styles:**
- Overlay: Full screen, pointer-events none (except canvas-pip)
- Canvas-pip: Bottom-right corner, 55% width × 50% height
- Slide-in animation: translateX(100%) → translateX(0)
- Backdrop blur: 20px for frosted glass effect
- Close button: Red hover state, positioned above canvas

## WebView Configuration

```svelte
<webview src={url} class="canvas-webview" partition="persist:canvas"></webview>
```

**Partition:** `persist:canvas` - Persistent storage for canvas content.

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/components/Window.svelte` - Parent component
- `src/main/ipc/window.ts` - Canvas IPC handlers
- `src/main/context.ts` - Canvas content generation

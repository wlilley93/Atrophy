# src/renderer/main.ts - Renderer Entry Point

**Dependencies:** `./styles/global.css`, `./App.svelte`, `svelte`  
**Purpose:** Mount Svelte application to DOM

## Overview

This is the entry point for the renderer process. It imports the global CSS stylesheet, mounts the root App component, and exports the app instance.

## Code

```typescript
import './styles/global.css';
import App from './App.svelte';
import { mount } from 'svelte';

const app = mount(App, {
  target: document.getElementById('app')!,
});

export default app;
```

## Execution Flow

```
1. Import global CSS (dark theme, custom properties)
2. Import root App component
3. Import Svelte 5 mount function
4. Find #app element in DOM
5. Mount App component to #app
6. Export app instance (for potential external access)
```

## Mount Target

The `#app` element is defined in `src/renderer/index.html`:

```html
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Atrophy</title>
  </head>
  <body>
    <div id="app"></div>
  </body>
</html>
```

## Svelte 5 Mount

The `mount()` function is Svelte 5's new mounting API (replaces `new App()`):

```typescript
import { mount } from 'svelte';

const app = mount(App, {
  target: Element,
  props?: Props,  // Optional props
  intro?: boolean, // Enable transitions
});
```

**Features:**
- Returns app instance
- Supports props passing
- Supports transition enabling
- Proper cleanup on unmount

## App Export

The app instance is exported for potential external access:

```typescript
export default app;
```

**Use cases:**
- Testing (access to component internals)
- Devtools integration
- External script access (rare)

## CSS Import

The global CSS is imported first to ensure styles are loaded before component mounting:

```typescript
import './styles/global.css';
```

**Contents:**
- Dark theme colors
- Custom CSS properties
- Base typography
- Reset/normalize styles

See [`global.css`](../renderer/styles/global.md) for full details.

## Error Handling

No explicit error handling - if mount fails, the app won't start and Electron will show a blank window.

**Common failures:**
- `#app` element not found (null check with `!` assumes it exists)
- CSS import fails (network/file issue)
- App component has initialization error

## File I/O

None - pure runtime code.

## Exported API

| Export | Type | Purpose |
|--------|------|---------|
| `app` | Svelte app instance | Root component instance |

## See Also

- `src/renderer/App.svelte` - Root component
- `src/renderer/index.html` - HTML template with #app target
- `src/renderer/styles/global.css` - Global styles
- `src/main/app.ts` - Main process that creates the BrowserWindow

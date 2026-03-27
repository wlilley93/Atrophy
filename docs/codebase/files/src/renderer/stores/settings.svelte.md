# src/renderer/stores/settings.svelte.ts - Settings Store

**Dependencies:** None (Svelte 5 built-in runes)  
**Purpose:** Mirrored config values from main process

## Overview

This module exports module-level reactive state for configuration values using Svelte 5's `$state` rune. The state is populated during app initialization from the main process config.

## Reactive State

### settings

```typescript
export const settings = $state({
  userName: 'User',
  version: '0.0.0',
  avatarEnabled: false,
  ttsBackend: 'elevenlabs',
  inputMode: 'dual',
  loaded: false,
});
```

**Fields:**

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `userName` | `string` | `'User'` | User's name from config |
| `version` | `string` | `'0.0.0'` | App version |
| `avatarEnabled` | `boolean` | `false` | Whether avatar is enabled |
| `ttsBackend` | `string` | `'elevenlabs'` | TTS backend (elevenlabs, fal, say) |
| `inputMode` | `string` | `'dual'` | Input mode (text, voice, dual) |
| `loaded` | `boolean` | `false` | Whether config has been loaded |

## Population Flow

```
App.svelte initialization
         │
         ▼
┌─────────────────┐
| api.getConfig() │
└─────────────────┘
         │
         ▼
┌─────────────────────────────┐
| settings.userName = config  │
| settings.version = version  │
| settings.avatarEnabled = x  │
| settings.ttsBackend = y     │
| settings.inputMode = z      │
| settings.loaded = true      │
└─────────────────────────────┘
         │
         ▼
   All components
   reactively update
```

## Usage in Components

```svelte
<script lang="ts">
  import { settings } from '../stores/settings.svelte';
  
  // Reactively display user name
  $: greeting = `Hello, ${settings.userName}!`;
  
  // Conditional rendering
  $: showAvatar = settings.avatarEnabled;
  $: inputHint = settings.inputMode === 'voice' ? '🎤' : '⌨️';
</script>

<div class="settings-display">
  {#if settings.loaded}
    <p>Version: {settings.version}</p>
    <p>TTS: {settings.ttsBackend}</p>
  {:else}
    <p>Loading settings...</p>
  {/if}
</div>
```

## Module-Level Reactivity

Svelte 5's `$state` rune creates module-level reactive state:

1. **Single instance:** All imports share the same state object
2. **Fine-grained updates:** Components only re-render when accessed fields change
3. **No store subscriptions:** Direct property access, no `.subscribe()` needed

## Exported API

| Export | Type | Purpose |
|--------|------|---------|
| `settings` | reactive object | Module-level settings state |

## See Also

- [`session.svelte.ts`](session.svelte.md) - App lifecycle state
- `src/main/ipc/config.ts` - Config IPC handlers
- `src/renderer/components/Settings.svelte` - Settings modal

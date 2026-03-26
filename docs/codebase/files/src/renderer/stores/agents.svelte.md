# src/renderer/stores/agents.svelte.ts - Agent List Store

**Line count:** ~10 lines  
**Dependencies:** None (Svelte 5 built-in runes)  
**Purpose:** Reactive agent list and switching state

## Overview

This module exports module-level reactive state for agent management using Svelte 5's `$state` rune. The state tracks the list of available agents, the current agent, and switch animation direction.

## Reactive State

### agents

```typescript
export const agents = $state({
  list: [] as string[],
  current: '',
  displayName: '',
  switchDirection: 0, // -1 up, +1 down, 0 none
});
```

**Fields:**

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `list` | `string[]` | `[]` | Array of agent directory names |
| `current` | `string` | `''` | Currently active agent name |
| `displayName` | `string` | `''` | Current agent's display name |
| `switchDirection` | `number` | `0` | Animation direction for rolodex |

**switchDirection values:**
- `-1`: Switching to previous agent (animate up)
- `0`: No switch in progress
- `+1`: Switching to next agent (animate down)

## Usage in Components

```svelte
<script lang="ts">
  import { agents } from '../stores/agents.svelte';
  import { api } from '../api';
  
  // Display current agent
  $: agentLabel = `${agents.displayName} (${agents.current})`;
  
  // Cycle to next agent
  async function cycleNext() {
    const next = await api.agentCycle(1);
    agents.current = next.name;
    agents.displayName = next.display_name;
    agents.switchDirection = 1;
    
    // Reset direction after animation
    setTimeout(() => { agents.switchDirection = 0; }, 300);
  }
</script>

<div class="agent-name">
  {agents.displayName}
  {#if agents.switchDirection !== 0}
    <span class="direction">{agents.switchDirection > 0 ? '▼' : '▲'}</span>
  {/if}
</div>
```

## Population Flow

```
App.svelte initialization
         │
         ▼
┌─────────────────┐
| api.getAgents() |
└─────────────────┘
         │
         ▼
┌─────────────────────┐
| agents.list = [...] |
| agents.current = x  |
| agents.displayName = y|
└─────────────────────┘
         │
         ▼
   All components
   reactively update
```

## Module-Level Reactivity

Svelte 5's `$state` rune creates module-level reactive state:

1. **Single instance:** All imports share the same state object
2. **Fine-grained updates:** Components only re-render when accessed fields change
3. **No store subscriptions:** Direct property access, no `.subscribe()` needed

```typescript
// All these imports reference the same state object
import { agents } from './agents.svelte';  // Component A
import { agents } from './agents.svelte';  // Component B
import { agents } from './agents.svelte';  // Component C

// Mutation in Component A is visible in B and C
agents.current = 'montgomery';  // All components see the change
```

## Exported API

| Export | Type | Purpose |
|--------|------|---------|
| `agents` | reactive object | Module-level agent state |

## See Also

- [`session.svelte.ts`](session.svelte.md) - App lifecycle state
- `src/renderer/components/AgentName.svelte` - Agent name display with rolodex animation
- `src/main/ipc/agents.ts` - Agent management IPC handlers

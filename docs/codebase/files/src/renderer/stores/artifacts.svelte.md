# src/renderer/stores/artifacts.svelte.ts - Inline Artifact Store

**Dependencies:** None (Svelte 5 built-in runes)  
**Purpose:** Store inline artifacts extracted from agent responses

## Overview

This module manages inline artifacts that are extracted from agent responses during streaming. Artifacts are visual or interactive content (HTML, SVG, code) that display as clickable cards in the transcript.

## Types

### InlineArtifact

```typescript
export interface InlineArtifact {
  id: string;
  type: 'html' | 'svg' | 'code';
  title: string;
  language: string;
  content: string;
}
```

**Fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `id` | `string` | Unique identifier within conversation |
| `type` | `'html' \| 'svg' \| 'code'` | Content type |
| `title` | `string` | Human-readable title for card display |
| `language` | `string` | Content language (html, svg, python, typescript, etc.) |
| `content` | `string` | Full artifact content |

## Reactive State

### _artifacts

```typescript
const _artifacts = $state<Map<string, InlineArtifact>>(new Map());
```

**Purpose:** Map of artifact ID to artifact object.

**Why Map:** O(1) lookup by ID, supports iteration.

### artifacts (exported)

```typescript
export const artifacts = _artifacts;
```

**Purpose:** Exported reference for component access.

## Functions

### storeArtifact

```typescript
export function storeArtifact(artifact: InlineArtifact): void {
  _artifacts.set(artifact.id, artifact);
}
```

**Purpose:** Store an artifact in the map.

**Use case:** Called when `inference:artifact` IPC event is received.

### getArtifact

```typescript
export function getArtifact(id: string): InlineArtifact | undefined {
  return _artifacts.get(id);
}
```

**Purpose:** Retrieve artifact by ID.

**Use case:** Called when rendering artifact card or opening full viewer.

### clearArtifacts

```typescript
export function clearArtifacts(): void {
  _artifacts.clear();
}
```

**Purpose:** Clear all artifacts.

**Use case:** Agent switch, session reset.

## Usage in Components

```svelte
<script lang="ts">
  import { storeArtifact, getArtifact, artifacts } from '../stores/artifacts.svelte';
  import { api } from '../api';
  
  onMount(() => {
    // Listen for artifact events from inference
    const unsub = api.onArtifact((artifact) => {
      storeArtifact(artifact);
    });
    return unsub;
  });
  
  function openArtifact(id: string) {
    const artifact = getArtifact(id);
    if (artifact) {
      // Open full-screen viewer
      openViewer(artifact);
    }
  }
</script>

<!-- In transcript -->
{#each transcript.messages as msg}
  {@const artifactMatches = msg.content.matchAll(/\[\[artifact:(\w+)\]\]/g)}
  {#for match of artifactMatches}
    {@const id = match[1]}
    {@const artifact = getArtifact(id)}
    {#if artifact}
      <ArtifactCard 
        {artifact} 
        on:click={() => openArtifact(id)} 
      />
    {/if}
  {/for}
{/each}
```

## Artifact Flow

```
Claude CLI response text
         │
         ▼
┌─────────────────────┐
| <artifact id="x"    │
|   type="html"       │
|   title="Chart">    │
| ...content...       │
| </artifact>         │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
| artifact-parser.ts  │
| - Extract artifacts │
| - Replace with      │
|   [[artifact:id]]   │
└─────────────────────┘
         │
         ▼
    ┌───┴───┐
    │       │
    ▼       ▼
┌────────┐ ┌──────────────┐
| Store  │ | Cleaned text │
| artifact│ | to transcript│
└────────┘ └──────────────┘
    │
    ▼
Render artifact card
in transcript
```

## Transcript Placeholder

Artifacts in response text are replaced with placeholders:

**Original:**
```
Here's a visualization:

<artifact id="solar-system" type="html" title="Solar System" language="html">
<!DOCTYPE html>
<html>...full HTML content...</html>
</artifact>

Let me know what you think!
```

**After parsing:**
```
Here's a visualization:

[[artifact:solar-system]]

Let me know what you think!
```

**Rendering:** The `[[artifact:solar-system]]` placeholder is replaced with a clickable card that opens the full artifact viewer.

## Module-Level Reactivity

Svelte 5's `$state` rune creates module-level reactive state:

1. **Single instance:** All imports share the same Map
2. **Fine-grained updates:** Components re-render when accessed artifacts change
3. **No store subscriptions:** Direct Map access, no `.subscribe()` needed

## Exported API

| Function | Purpose |
|----------|---------|
| `storeArtifact(artifact)` | Store artifact in map |
| `getArtifact(id)` | Retrieve artifact by ID |
| `clearArtifacts()` | Clear all artifacts |
| `InlineArtifact` | Artifact interface |
| `artifacts` | Exported Map reference |

## See Also

- [`transcript.svelte.ts`](transcript.svelte.md) - Message history store
- `src/main/artifact-parser.ts` - Artifact extraction from responses
- `src/renderer/components/Artefact.svelte` - Artifact viewer component

# src/renderer/stores/transcript.svelte.ts - Message History Store

**Dependencies:** None (Svelte 5 built-in runes)  
**Purpose:** Reactive message history for transcript display with typewriter animation

## Overview

This module manages the conversation transcript displayed in the UI. It uses Svelte 5's `$state` rune for module-level reactive state and provides helper functions for manipulating the message list.

## Types

### Message

```typescript
export interface Message {
  id: number;
  role: 'user' | 'agent' | 'system' | 'divider';
  content: string;
  timestamp: number;
  revealed: number;      // chars revealed so far (for animation)
  complete: boolean;
}
```

**Fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `id` | `number` | Auto-incrementing unique ID |
| `role` | `'user' \| 'agent' \| 'system' \| 'divider'` | Message sender type |
| `content` | `string` | Message text |
| `timestamp` | `number` | `Date.now()` at creation |
| `revealed` | `number` | Chars revealed for typewriter animation |
| `complete` | `boolean` | Whether message is fully streamed |

## Reactive State

### transcript

```typescript
export const transcript = $state({
  messages: [] as Message[],
  autoScroll: true,
});
```

**Fields:**

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `messages` | `Message[]` | `[]` | Array of message objects |
| `autoScroll` | `boolean` | `true` | Whether to auto-scroll to bottom |

## Functions

### addMessage

```typescript
export function addMessage(role: Message['role'], content: string): Message {
  const msg: Message = {
    id: _nextId++,
    role,
    content,
    timestamp: Date.now(),
    revealed: role === 'agent' ? 0 : content.length,
    complete: role !== 'agent',
  };
  transcript.messages.push(msg);
  return msg;
}
```

**Purpose:** Add a new message to the transcript.

**Behavior by role:**
- **user/system/divider:** Immediately complete with full reveal
- **agent:** Start with `revealed: 0`, `complete: false` for typewriter animation

**Returns:** The created message object

### appendToLast

```typescript
export function appendToLast(text: string): void {
  const msgs = transcript.messages;
  if (msgs.length === 0) return;
  const last = msgs[msgs.length - 1];
  if (last.role === 'agent') {
    // Accept text even if complete flag was set
    last.content += text;
    // If already complete, keep revealed in sync
    if (last.complete) last.revealed = last.content.length;
  }
}
```

**Purpose:** Append text to the last agent message.

**Use case:** Called on each `textDelta` event during streaming inference.

**Race condition handling:** Accepts text even if `complete: true` (handles race between `textDelta` and `done` events).

### completeLast

```typescript
export function completeLast(): void {
  const msgs = transcript.messages;
  if (msgs.length === 0) return;
  const last = msgs[msgs.length - 1];
  last.complete = true;
  last.revealed = last.content.length;
}
```

**Purpose:** Mark the last message as complete and fully revealed.

**Use case:** Called when `done` or `error` event fires from inference.

### addDivider

```typescript
export function addDivider(text: string): void {
  addMessage('divider', text);
}
```

**Purpose:** Add a divider message (centered green label).

**Use case:** Separate conversation segments (e.g., after agent switch).

### clearTranscript

```typescript
export function clearTranscript(): void {
  transcript.messages = [];
  transcript.autoScroll = true;
}
```

**Purpose:** Clear all messages and reset auto-scroll.

**Use case:** Agent switching, session reset.

## Usage in Components

```svelte
<script lang="ts">
  import { transcript, addMessage, appendToLast, completeLast } from '../stores/transcript.svelte';
  import { api } from '../api';
  
  // Add user message
  function sendMessage(text: string) {
    addMessage('user', text);
    api.sendMessage(text);
  }
  
  // Subscribe to streaming events
  onMount(() => {
    const unsubDelta = api.onTextDelta((text) => {
      appendToLast(text);
    });
    
    const unsubDone = api.onDone((fullText) => {
      completeLast();
    });
    
    return () => {
      unsubDelta();
      unsubDone();
    };
  });
</script>

<div class="transcript">
  {#each transcript.messages as msg (msg.id)}
    <MessageView {msg} />
  {/each}
</div>
```

## Typewriter Animation

The `revealed` field enables character-by-character reveal animation:

```svelte
<!-- In Transcript.svelte -->
<span class="content">
  {msg.content.slice(0, msg.revealed)}
</span>

{#if !msg.complete}
  <script>
    // Animate revealed counter
    const animate = () => {
      if (msg.revealed < msg.content.length) {
        msg.revealed++;
        requestAnimationFrame(animate);
      }
    };
    animate();
  </script>
{/if}
```

## Message Flow

```
User sends message
       │
       ▼
┌──────────────┐
│ addMessage() │──▶ messages: [user message (complete)]
└──────────────┘
       │
       ▼
┌─────────────────┐
│ Inference runs  │
└─────────────────┘
       │
       ▼
┌──────────────┐
│ addMessage() │──▶ messages: [..., agent message (revealed=0)]
└──────────────┘
       │
       ▼
┌─────────────────┐
│ textDelta events│
└─────────────────┘
       │
       ▼
┌────────────────┐
│ appendToLast() │──▶ content grows, revealed animates
└────────────────┘
       │
       ▼
┌──────────────┐
│ completeLast()│──▶ complete=true, revealed=full length
└──────────────┘
```

## Exported API

| Function | Purpose |
|----------|---------|
| `addMessage(role, content)` | Add new message |
| `appendToLast(text)` | Append text to last agent message |
| `completeLast()` | Mark last message complete |
| `addDivider(text)` | Add divider message |
| `clearTranscript()` | Clear all messages |
| `Message` | Message interface |
| `transcript` | Reactive state object |

## See Also

- [`session.svelte.ts`](session.svelte.md) - App lifecycle state
- `src/renderer/components/Transcript.svelte` - Transcript display component
- `src/renderer/components/InputBar.svelte` - Message input component

# src/renderer/components/AgentName.svelte - Agent Name with Rolodex Animation

**Line count:** ~100 lines  
**Dependencies:** `svelte`  
**Purpose:** Display agent name with rolodex-style switching animation

## Overview

This component displays the current agent's display name with chevron buttons for cycling between agents. It features a smooth rolodex animation when the agent name changes.

## Props

```typescript
interface Props {
  name: string;              // Current agent name
  direction: number;         // Switch direction: -1 up, +1 down, 0 none
  canCycle?: boolean;        // Whether cycling is enabled (default: true)
  onCycleUp: () => void;     // Previous agent handler
  onCycleDown: () => void;   // Next agent handler
}
```

## State Variables

```typescript
let displayName = $state('');
let offset = $state(0);
let animating = $state(false);
let prevName = '';
```

**Purpose:**
- `displayName`: Currently displayed name (for animation)
- `offset`: Vertical offset for rolodex effect
- `animating`: Animation in progress flag
- `prevName`: Previous name for change detection

## Initialization Effect

```typescript
$effect(() => {
  if (!prevName) {
    displayName = name;
    prevName = name;
  }
});
```

**Purpose:** Initialize display name on first render.

## Animation Effect

```typescript
$effect(() => {
  if (name !== prevName && !animating) {
    prevName = name;
    animating = true;
    offset = direction > 0 ? 30 : -30;  // Start offset based on direction

    // Animate to 0
    const start = performance.now();
    const duration = 400;
    const from = offset;
    let rafId = 0;

    function tick(now: number) {
      const elapsed = now - start;
      const t = Math.min(elapsed / duration, 1);
      // Ease out cubic
      const ease = 1 - Math.pow(1 - t, 3);
      offset = from * (1 - ease);

      // Swap name at midpoint
      if (t < 0.5 && displayName !== name) {
        displayName = name;
      }

      if (t < 1) {
        rafId = requestAnimationFrame(tick);
      } else {
        offset = 0;
        animating = false;
        prevName = name;
      }
    }
    rafId = requestAnimationFrame(tick);

    // Cancel animation on cleanup
    return () => cancelAnimationFrame(rafId);
  }
});
```

**Animation flow:**
1. Set initial offset (30px up or down based on direction)
2. Animate offset to 0 over 400ms
3. Use ease-out cubic easing
4. Swap name at midpoint (t < 0.5)
5. Reset state on completion

**Easing formula:** `ease = 1 - (1 - t)³`

## Template

```svelte
<div class="agent-name" data-no-drag>
  <!-- Up chevron -->
  {#if canCycle}
    <button class="chevron chevron-up" onclick={onCycleUp} aria-label="Previous agent">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="18 15 12 9 6 15"/>
      </svg>
    </button>
  {/if}

  <!-- Name with rolodex clip -->
  <div class="name-clip">
    <span class="name-text" style="transform: translateY({offset}px)">
      {displayName}
    </span>
  </div>

  <!-- Down chevron -->
  {#if canCycle}
    <button class="chevron chevron-down" onclick={onCycleDown} aria-label="Next agent">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6 9 12 15 18 9"/>
      </svg>
    </button>
  {/if}
</div>
```

**Structure:**
1. Up chevron button (previous agent)
2. Name clip (overflow hidden for rolodex effect)
3. Name text (translated by offset)
4. Down chevron button (next agent)

## Styling

```css
.agent-name {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
  width: 250px;
}

.chevron {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  padding: 4px 8px;
  line-height: 0;
  opacity: 0;
  transition: opacity 0.2s;
  -webkit-app-region: no-drag;
  position: relative;
  z-index: 20;
}

.agent-name:hover .chevron {
  opacity: 1;
}

.chevron:hover {
  color: var(--text-secondary);
}

.chevron:active {
  color: var(--text-primary);
}

.name-clip {
  height: 30px;
  overflow: hidden;
}

.name-text {
  display: block;
  font-family: var(--font-sans);
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.78);
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
  white-space: nowrap;
  will-change: transform;
}
```

**Key styles:**
- `name-clip`: Fixed height with overflow hidden (creates rolodex mask)
- `name-text`: Translated by offset, uppercase, bold
- `chevron`: Hidden by default, shown on hover
- `data-no-drag`: Prevents window dragging on buttons

## Usage

```svelte
<AgentName 
  name={agents.displayName}
  direction={agents.switchDirection}
  onCycleUp={() => api.cycleAgent(-1)}
  onCycleDown={() => api.cycleAgent(1)}
/>
```

## File I/O

None - pure UI component.

## Exported API

None - component is not exported for external use.

## See Also

- `src/renderer/stores/agents.svelte.ts` - Agent state with switchDirection
- `src/main/ipc/agents.ts` - agent:cycle IPC handler
- `src/renderer/components/Window.svelte` - Parent component

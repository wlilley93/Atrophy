<script lang="ts">
  import { onMount } from 'svelte';

  interface Props {
    name: string;
    direction: number;
    canCycle?: boolean;
    onCycleUp: () => void;
    onCycleDown: () => void;
  }

  let { name, direction, canCycle = true, onCycleUp, onCycleDown }: Props = $props();

  // Rolodex animation state
  let displayName = $state('');
  let offset = $state(0);
  let animating = $state(false);
  let prevName = '';
  let activeRafId = 0;

  // Initialize on first render
  $effect(() => {
    if (!prevName) {
      displayName = name;
      prevName = name;
    }
  });

  $effect(() => {
    if (name !== prevName) {
      // Cancel any in-flight animation and start fresh
      if (activeRafId) cancelAnimationFrame(activeRafId);

      const targetName = name;
      prevName = targetName;
      animating = true;
      offset = direction > 0 ? 30 : -30;

      const start = performance.now();
      const duration = 400;
      const from = offset;

      function tick(now: number) {
        const elapsed = now - start;
        const t = Math.min(elapsed / duration, 1);
        // Ease out cubic
        const ease = 1 - Math.pow(1 - t, 3);
        offset = from * (1 - ease);

        if (t < 0.5 && displayName !== targetName) {
          displayName = targetName;
        }

        if (t < 1) {
          activeRafId = requestAnimationFrame(tick);
        } else {
          offset = 0;
          animating = false;
          activeRafId = 0;
        }
      }
      activeRafId = requestAnimationFrame(tick);

      // Cancel animation on component destroy
      return () => {
        if (activeRafId) { cancelAnimationFrame(activeRafId); activeRafId = 0; }
      };
    }
  });
</script>

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

<style>
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
</style>

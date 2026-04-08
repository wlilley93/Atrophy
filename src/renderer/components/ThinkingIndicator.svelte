<script lang="ts">
  import { onMount } from 'svelte';
  import { session } from '../stores/session.svelte';

  // Brain frames via Vite glob import (00=healthy, 09=decayed)
  const brainFramePaths: string[] = [];
  const frameModules = import.meta.glob(
    '../../../resources/icons/brain_frames/brain_*.png',
    { eager: true, query: '?url', import: 'default' }
  );
  const sortedKeys = Object.keys(frameModules).sort();
  for (const key of sortedKeys) {
    brainFramePaths.push(frameModules[key] as string);
  }

  let currentFrame = $state(0);
  let opacity = $state(0.5);
  let tick = 0;

  // Reactive label - reads from the session store. Empty string hides the
  // label entirely so the default 'thinking' brain pulse is unchanged when
  // the renderer hasn't received any tool/thinking events yet.
  const label = $derived(session.currentActivity);

  onMount(() => {
    const interval = setInterval(() => {
      tick++;
      currentFrame = tick % brainFramePaths.length;
      // Gentle pulse between 0.35 and 0.7
      opacity = 0.35 + 0.35 * Math.sin(tick * 0.2);
    }, 250);

    return () => clearInterval(interval);
  });
</script>

{#if brainFramePaths.length > 0}
  <div class="thinking-brain" style="opacity: {opacity}">
    <img
      src={brainFramePaths[currentFrame]}
      alt=""
      class="brain-frame"
      draggable="false"
    />
    {#if label}
      <span class="activity-label">{label}</span>
    {/if}
  </div>
{/if}

<style>
  .thinking-brain {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 8px;
    padding: 4px 0;
    will-change: opacity;
  }

  .brain-frame {
    width: 24px;
    height: 24px;
    object-fit: contain;
    filter: grayscale(0.3) brightness(0.85);
    pointer-events: none;
    user-select: none;
  }

  .activity-label {
    color: rgba(255, 255, 255, 0.85);
    font-size: 12px;
    font-weight: 400;
    letter-spacing: 0.01em;
    user-select: none;
    /* Soft fade so the label doesn't pop in jarringly when activity flips */
    transition: opacity 120ms ease-out;
  }
</style>

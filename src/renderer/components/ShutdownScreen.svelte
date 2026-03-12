<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

  interface Props {
    /** Call when shutdown animation is complete */
    onComplete: () => void;
  }

  let { onComplete }: Props = $props();

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
  const LAST = brainFramePaths.length - 1;

  // Start at decayed (9), animate to healthy (0) - reverse of startup
  let currentFrame = $state(LAST);
  let opacity = $state(0);
  let brainTimer: ReturnType<typeof setInterval> | null = null;

  // Progress tracks frame animation (0% at frame 9, 100% at frame 0)
  let progress = $derived(LAST > 0 ? ((LAST - currentFrame) / LAST) * 100 : 0);

  function clearTimers() {
    if (brainTimer) { clearInterval(brainTimer); brainTimer = null; }
  }

  // Reverse brain animation: 9 -> 0 at 200ms per frame
  function startBrainRestore() {
    currentFrame = LAST;
    brainTimer = setInterval(() => {
      if (currentFrame > 0) {
        currentFrame--;
      } else {
        clearTimers();
        // Hold briefly on healthy frame, then signal completion
        setTimeout(() => {
          onComplete();
        }, 400);
      }
    }, 200);
  }

  onMount(() => {
    // Fade in
    requestAnimationFrame(() => {
      opacity = 1;
    });
    // Start reverse decay after fade-in
    setTimeout(() => {
      startBrainRestore();
    }, 300);
  });

  onDestroy(() => clearTimers());
</script>

<div class="shutdown" style="opacity: {opacity}">
  <div class="shutdown-content">
    {#if brainFramePaths[currentFrame]}
      <img
        class="brain-img"
        src={brainFramePaths[currentFrame]}
        alt=""
        draggable="false"
      />
    {/if}

    <span class="status-text">Restoring your sanity...</span>

    <div class="progress-bar">
      <div class="progress-fill" style="width: {progress}%"></div>
    </div>
  </div>
</div>

<style>
  .shutdown {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: opacity 0.3s ease;
  }

  .shutdown-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 20px;
  }

  .brain-img {
    width: 80px;
    height: 80px;
    object-fit: contain;
    user-select: none;
    -webkit-user-drag: none;
  }

  .status-text {
    font-family: var(--font-sans);
    font-size: 13px;
    color: rgba(255, 255, 255, 0.4);
    letter-spacing: 0.5px;
  }

  .progress-bar {
    width: 200px;
    height: 2px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 1px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: rgba(100, 140, 255, 0.5);
    transition: width 0.2s ease;
  }
</style>

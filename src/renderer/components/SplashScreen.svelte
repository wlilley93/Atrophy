<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

  // Props
  interface Props {
    phase: 'boot' | 'downloading' | 'ready' | 'shutdown';
    downloadPercent?: number;
    statusText?: string;
    onComplete?: () => void;
  }

  let { phase, downloadPercent = 0, statusText = '', onComplete }: Props = $props();

  // Brain frames via Vite glob import
  const brainFramePaths: string[] = [];
  const frameModules = import.meta.glob(
    '../../../resources/icons/brain_frames/brain_*.png',
    { eager: true, query: '?url', import: 'default' }
  );
  const sortedKeys = Object.keys(frameModules).sort();
  for (const key of sortedKeys) {
    brainFramePaths.push(frameModules[key] as string);
  }
  const FRAME_COUNT = brainFramePaths.length; // 10

  let currentFrame = $state(0);
  let opacity = $state(1);
  let animInterval: ReturnType<typeof setInterval> | null = null;

  // Derive the display label
  let label = $derived(
    statusText || (
      phase === 'boot' ? 'starting...' :
      phase === 'downloading' ? 'downloading avatar...' :
      phase === 'shutdown' ? '' :
      ''
    )
  );

  // ---------------------------------------------------------------------------
  // Animation logic
  // ---------------------------------------------------------------------------

  function startBootAnimation() {
    // Start from decayed (frame 9), animate to healthy (frame 0)
    currentFrame = FRAME_COUNT - 1;
    const stepMs = 250;
    animInterval = setInterval(() => {
      if (currentFrame > 0) {
        currentFrame--;
      } else {
        if (animInterval) clearInterval(animInterval);
        animInterval = null;
        // Hold on healthy frame briefly, then signal ready
        setTimeout(() => {
          opacity = 0;
          setTimeout(() => onComplete?.(), 800);
        }, 400);
      }
    }, stepMs);
  }

  function startShutdownAnimation() {
    // Start from healthy (frame 0), animate to decayed (frame 9)
    currentFrame = 0;
    opacity = 1;
    const stepMs = 150;
    animInterval = setInterval(() => {
      if (currentFrame < FRAME_COUNT - 1) {
        currentFrame++;
      } else {
        if (animInterval) clearInterval(animInterval);
        animInterval = null;
        onComplete?.();
      }
    }, stepMs);
  }

  // For downloading: map download percent to frame (reverse - 9 at 0%, 0 at 100%)
  $effect(() => {
    if (phase === 'downloading') {
      const progress = Math.min(100, Math.max(0, downloadPercent));
      currentFrame = Math.max(0, FRAME_COUNT - 1 - Math.floor((progress / 100) * (FRAME_COUNT - 1)));
    }
  });

  // React to phase changes
  $effect(() => {
    if (phase === 'boot') {
      opacity = 1;
      startBootAnimation();
    } else if (phase === 'shutdown') {
      startShutdownAnimation();
    } else if (phase === 'downloading') {
      opacity = 1;
      currentFrame = FRAME_COUNT - 1;
    } else if (phase === 'ready') {
      opacity = 0;
    }
  });

  onDestroy(() => {
    if (animInterval) clearInterval(animInterval);
  });
</script>

<div class="splash" style="opacity: {opacity}; pointer-events: {opacity > 0 ? 'all' : 'none'}">
  <div class="splash-content">
    {#if brainFramePaths[currentFrame]}
      <img
        class="brain-img"
        src={brainFramePaths[currentFrame]}
        alt="brain"
        draggable="false"
      />
    {/if}

    {#if phase === 'downloading'}
      <div class="progress-bar">
        <div class="progress-fill" style="width: {downloadPercent}%"></div>
      </div>
    {/if}

    {#if label}
      <span class="splash-label">{label}</span>
    {/if}
  </div>
</div>

<style>
  .splash {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: opacity 0.8s ease;
  }

  .splash-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 20px;
  }

  .brain-img {
    width: 140px;
    height: 140px;
    object-fit: contain;
    user-select: none;
    -webkit-user-drag: none;
  }

  .progress-bar {
    width: 180px;
    height: 2px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 1px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: rgba(100, 140, 255, 0.5);
    transition: width 0.4s ease;
  }

  .splash-label {
    font-family: var(--font-sans);
    font-size: 11px;
    letter-spacing: 2px;
    color: rgba(255, 255, 255, 0.25);
    text-transform: lowercase;
  }
</style>

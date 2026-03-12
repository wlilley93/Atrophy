<script lang="ts">
  import { onMount } from 'svelte';

  let opacity = $state(0.25);
  let frame = 0;

  onMount(() => {
    const interval = setInterval(() => {
      frame++;
      // Pulse: 0.25 to 0.8
      opacity = 0.25 + 0.55 * Math.sin(frame * 0.15);
    }, 50);

    return () => clearInterval(interval);
  });
</script>

<div class="thinking" style="opacity: {opacity}">
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
    <!-- Brain icon -->
    <path d="M12 2a7 7 0 0 0-7 7c0 2.38 1.19 4.47 3 5.74V17a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-2.26c1.81-1.27 3-3.36 3-5.74a7 7 0 0 0-7-7z"/>
    <line x1="10" y1="21" x2="14" y2="21"/>
    <line x1="10" y1="19" x2="14" y2="19"/>
  </svg>
</div>

<style>
  .thinking {
    display: flex;
    align-items: center;
    color: var(--text-secondary);
    margin-left: 4px;
    margin-top: 3px;
    will-change: opacity;
  }
</style>

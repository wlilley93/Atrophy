<script lang="ts">
  import { onMount } from 'svelte';

  interface Props {
    onClose: () => void;
  }

  let { onClose }: Props = $props();

  let totalSeconds = $state(0);
  let running = $state(false);
  let interval: ReturnType<typeof setInterval> | null = null;

  function formatTime(s: number): string {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
    return `${m}:${String(sec).padStart(2, '0')}`;
  }

  function toggle() {
    if (running) {
      pause();
    } else {
      start();
    }
  }

  function start() {
    if (totalSeconds <= 0) return;
    running = true;
    interval = setInterval(() => {
      totalSeconds--;
      if (totalSeconds <= 0) {
        totalSeconds = 0;
        pause();
        // Could trigger notification here
      }
    }, 1000);
  }

  function pause() {
    running = false;
    if (interval) clearInterval(interval);
    interval = null;
  }

  function addMinutes(n: number) {
    totalSeconds += n * 60;
  }

  onMount(() => {
    totalSeconds = 5 * 60; // Default 5 minutes
    return () => {
      if (interval) clearInterval(interval);
    };
  });
</script>

<div class="timer-overlay" data-no-drag>
  <button class="close-btn" onclick={onClose}>
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  </button>

  <div class="timer-display">{formatTime(totalSeconds)}</div>

  <div class="timer-controls">
    <button class="timer-btn" onclick={toggle}>
      {running ? 'Pause' : 'Start'}
    </button>
    <button class="timer-btn" onclick={() => addMinutes(1)}>+1m</button>
    <button class="timer-btn" onclick={() => addMinutes(5)}>+5m</button>
  </div>
</div>

<style>
  .timer-overlay {
    position: absolute;
    inset: 0;
    z-index: 50;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: rgba(12, 12, 14, 0.92);
    backdrop-filter: blur(20px);
  }

  .close-btn {
    position: absolute;
    top: var(--pad);
    right: var(--pad);
    background: none;
    border: none;
    color: var(--text-dim);
    cursor: pointer;
    padding: 4px;
  }

  .close-btn:hover {
    color: var(--text-secondary);
  }

  .timer-display {
    font-family: var(--font-mono);
    font-size: 72px;
    font-weight: 300;
    color: rgba(255, 180, 100, 0.9);
    text-shadow: 0 0 40px rgba(255, 140, 50, 0.2);
    letter-spacing: 4px;
  }

  .timer-controls {
    display: flex;
    gap: 12px;
    margin-top: 32px;
  }

  .timer-btn {
    padding: 8px 20px;
    border: 1px solid rgba(255, 180, 100, 0.3);
    border-radius: 20px;
    background: transparent;
    color: rgba(255, 180, 100, 0.8);
    font-family: var(--font-sans);
    font-size: 13px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .timer-btn:hover {
    background: rgba(255, 180, 100, 0.08);
    border-color: rgba(255, 180, 100, 0.5);
  }
</style>

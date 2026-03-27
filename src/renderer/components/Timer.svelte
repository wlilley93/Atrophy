<script lang="ts">
  import { onMount } from 'svelte';

  interface Props {
    onClose: () => void;
  }

  let { onClose }: Props = $props();

  // Monotonic clock state
  let endTime = $state(0); // Date.now() timestamp when timer expires
  let totalSeconds = $state(0); // current remaining seconds (computed from clock delta)
  let running = $state(false);
  let paused = $state(false);
  let pauseRemaining = $state(0); // seconds remaining when paused
  let done = $state(false);
  let alarming = $state(false);
  let tickInterval: ReturnType<typeof setInterval> | null = null;

  // Alarm state
  let alarmTimeouts: ReturnType<typeof setTimeout>[] = [];
  let alarmAudios: HTMLAudioElement[] = [];
  let autoDismissTimeout: ReturnType<typeof setTimeout> | null = null;

  // Drag state
  let dragging = $state(false);
  let dragStartX = 0;
  let dragStartY = 0;
  let posRight = $state(20);
  let posTop = $state(80);
  let posMode = $state<'right' | 'left'>('right'); // track whether we use right or left positioning
  let posLeft = $state(0);

  // Color for final 10 seconds gradient
  let timerColor = $state('rgba(255, 180, 100, 0.9)');
  let timerShadow = $state('0 0 40px rgba(255, 140, 50, 0.2)');

  function formatTime(s: number): string {
    const clamped = Math.max(0, Math.floor(s));
    const h = Math.floor(clamped / 3600);
    const m = Math.floor((clamped % 3600) / 60);
    const sec = clamped % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
    return `${m}:${String(sec).padStart(2, '0')}`;
  }

  function updateDisplay() {
    if (paused || done) return;

    const remaining = Math.max(0, (endTime - Date.now()) / 1000);
    totalSeconds = remaining;

    // Color gradient in final 10 seconds
    if (remaining <= 10 && remaining > 0) {
      const progress = 1 - remaining / 10; // 0 to 1
      const green = Math.round(180 - progress * 140); // 180 -> 40
      const blue = Math.round(100 - progress * 80); // 100 -> 20
      timerColor = `rgba(255, ${green}, ${blue}, 0.9)`;
      timerShadow = `0 0 40px rgba(255, ${Math.round(140 - progress * 100)}, ${Math.round(50 - progress * 50)}, ${0.2 + progress * 0.3})`;
    } else if (remaining > 10) {
      timerColor = 'rgba(255, 180, 100, 0.9)';
      timerShadow = '0 0 40px rgba(255, 140, 50, 0.2)';
    }

    if (remaining <= 0 && !done) {
      done = true;
      totalSeconds = 0;
      timerColor = 'rgba(255, 100, 100, 0.9)';
      timerShadow = '0 0 40px rgba(255, 60, 60, 0.4)';
      fireAlarm();
    }
  }

  function startTick() {
    if (tickInterval) clearInterval(tickInterval);
    tickInterval = setInterval(updateDisplay, 100); // 100ms for smooth display
  }

  function stopTick() {
    if (tickInterval) {
      clearInterval(tickInterval);
      tickInterval = null;
    }
  }

  function toggle() {
    if (done) return;
    if (running) {
      pause();
    } else {
      start();
    }
  }

  function start() {
    if (done) return;
    if (paused) {
      // Resume from pause
      endTime = Date.now() + pauseRemaining * 1000;
      paused = false;
      running = true;
      startTick();
      return;
    }
    if (totalSeconds <= 0) return;
    endTime = Date.now() + totalSeconds * 1000;
    running = true;
    startTick();
  }

  function pause() {
    if (!running || done) return;
    pauseRemaining = Math.max(0, (endTime - Date.now()) / 1000);
    paused = true;
    running = false;
    stopTick();
  }

  function addMinutes(n: number) {
    const addSeconds = n * 60;
    if (done) {
      // Restart from alarm state
      stopAlarm();
      done = false;
      alarming = false;
      timerColor = 'rgba(255, 180, 100, 0.9)';
      timerShadow = '0 0 40px rgba(255, 140, 50, 0.2)';
      endTime = Date.now() + addSeconds * 1000;
      totalSeconds = addSeconds;
      running = true;
      startTick();
    } else if (paused) {
      pauseRemaining += addSeconds;
      totalSeconds = pauseRemaining;
    } else if (running) {
      endTime += addSeconds * 1000;
    } else {
      totalSeconds += addSeconds;
    }
  }

  function fireAlarm() {
    alarming = true;
    running = false;
    stopTick();

    // Play Glass.aiff 6 times with ~1.5s spacing
    for (let i = 0; i < 6; i++) {
      const timeout = setTimeout(() => {
        if (!alarming) return;
        try {
          const audio = new Audio('/System/Library/Sounds/Glass.aiff');
          alarmAudios.push(audio);
          audio.play().catch(() => {
            // Fallback: try using the system beep or just skip
          });
        } catch {
          // Sound not available in this environment
        }
      }, i * 1500);
      alarmTimeouts.push(timeout);
    }

    // macOS notification via web Notification API
    try {
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('Timer complete', { body: 'Your timer has finished.' });
      } else if ('Notification' in window && Notification.permission !== 'denied') {
        Notification.requestPermission().then((perm) => {
          if (perm === 'granted') {
            new Notification('Timer complete', { body: 'Your timer has finished.' });
          }
        });
      }
    } catch {
      // Notification not available
    }

    // Auto-dismiss after 60 seconds
    autoDismissTimeout = setTimeout(() => {
      if (done && alarming) {
        dismissAlarm();
      }
    }, 60_000);
  }

  function stopAlarm() {
    alarming = false;
    // Clear pending alarm timeouts
    for (const t of alarmTimeouts) {
      clearTimeout(t);
    }
    alarmTimeouts = [];
    // Stop all playing audio
    for (const audio of alarmAudios) {
      try {
        audio.pause();
        audio.currentTime = 0;
      } catch {
        // ignore
      }
    }
    alarmAudios = [];
    // Clear auto-dismiss
    if (autoDismissTimeout) {
      clearTimeout(autoDismissTimeout);
      autoDismissTimeout = null;
    }
  }

  function dismissAlarm() {
    stopAlarm();
    stopTick();
    onClose();
  }

  function cancel() {
    stopAlarm();
    stopTick();
    onClose();
  }

  // Drag handlers
  function onMouseDown(e: MouseEvent) {
    // Only drag from the timer body, not from buttons
    if ((e.target as HTMLElement).closest('button')) return;
    dragging = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    e.preventDefault();
  }

  function onMouseMove(e: MouseEvent) {
    if (!dragging) return;
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    dragStartX = e.clientX;
    dragStartY = e.clientY;

    // Switch to left-based positioning on first drag for simpler math
    if (posMode === 'right') {
      // Convert right-based to left-based and apply this frame's delta
      const el = document.querySelector('.timer-overlay') as HTMLElement;
      if (el) {
        const rect = el.getBoundingClientRect();
        posLeft = rect.left + dx;
        posTop = rect.top + dy;
        posMode = 'left';
      }
    } else {
      posLeft += dx;
      posTop += dy;
    }

    // Clamp to keep widget on-screen
    const el = document.querySelector('.timer-overlay') as HTMLElement;
    if (el) {
      const tw = el.offsetWidth;
      const th = el.offsetHeight;
      posLeft = Math.max(0, Math.min(posLeft, window.innerWidth - tw));
      posTop = Math.max(0, Math.min(posTop, window.innerHeight - th));
    }
  }

  function onMouseUp() {
    dragging = false;
  }

  onMount(() => {
    totalSeconds = 5 * 60; // Default 5 minutes
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);

    return () => {
      stopTick();
      stopAlarm();
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="timer-overlay"
  class:dragging
  style={posMode === 'right'
    ? `right: ${posRight}px; top: ${posTop}px;`
    : `left: ${posLeft}px; top: ${posTop}px;`}
  onmousedown={onMouseDown}
>
  <button class="close-btn" onclick={cancel} aria-label="Close timer">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  </button>

  <div
    class="timer-display"
    style="color: {timerColor}; text-shadow: {timerShadow};"
  >
    {formatTime(totalSeconds)}
  </div>

  {#if alarming}
    <div class="timer-controls">
      <button class="timer-btn dismiss-btn" onclick={dismissAlarm}>
        Dismiss
      </button>
    </div>
  {:else}
    <div class="timer-controls">
      <button class="timer-btn" onclick={toggle}>
        {#if running}Pause{:else if paused}Resume{:else}Start{/if}
      </button>
      <button class="timer-btn" onclick={() => addMinutes(1)}>+1m</button>
      <button class="timer-btn" onclick={() => addMinutes(5)}>+5m</button>
    </div>
  {/if}
</div>

<style>
  .timer-overlay {
    position: absolute;
    right: 20px;
    top: 80px;
    z-index: 50;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: rgba(20, 20, 24, 0.88);
    backdrop-filter: blur(20px);
    border-radius: 12px;
    border: 1px solid var(--border);
    padding: 20px 28px 16px;
    min-width: 220px;
    cursor: grab;
    user-select: none;
  }

  .timer-overlay.dragging {
    cursor: grabbing;
  }

  .close-btn {
    position: absolute;
    top: 8px;
    right: 8px;
    background: none;
    border: none;
    color: var(--text-dim);
    cursor: pointer;
    padding: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .close-btn:hover {
    color: var(--text-secondary);
  }

  .timer-display {
    font-family: var(--font-mono);
    font-size: 42px;
    font-weight: 300;
    letter-spacing: 2px;
    transition: color 0.3s ease, text-shadow 0.3s ease;
  }

  .timer-controls {
    display: flex;
    gap: 8px;
    margin-top: 14px;
  }

  .timer-btn {
    padding: 5px 14px;
    border: 1px solid rgba(255, 180, 100, 0.3);
    border-radius: 14px;
    background: transparent;
    color: rgba(255, 180, 100, 0.8);
    font-family: var(--font-sans);
    font-size: 12px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .timer-btn:hover {
    background: rgba(255, 180, 100, 0.08);
    border-color: rgba(255, 180, 100, 0.5);
  }

  .dismiss-btn {
    border-color: rgba(255, 80, 80, 0.4);
    color: rgba(255, 255, 255, 0.85);
    background: rgba(255, 80, 80, 0.25);
    font-weight: 600;
    padding: 6px 24px;
  }

  .dismiss-btn:hover {
    background: rgba(255, 80, 80, 0.4);
    border-color: rgba(255, 80, 80, 0.6);
  }
</style>
